"""Fake-only V2-PIPE02 tests for summary and video-introduction modes."""

import json
from pathlib import Path
import uuid

import pytest

from backend.contracts import CleanupPolicy, Job, JobOptions
from backend.main import build_application
from backend.local_adapters import RejectingUrlSourceAdapter
from backend.progress import ProgressTracker
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts


class Runner:
    def run(self, arguments: list[str]) -> None:
        Path(arguments[-1]).write_bytes(b"wav")


class Stt:
    def transcribe(self, audio_path: str) -> list[dict[str, object]]:
        return [{"start": 0.0, "end": 1.0, "text": "OpenAI fixture line."}]


class Runtime:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Target text:" in prompt:
            target = json.loads(prompt.rsplit("\n", 1)[-1])
            return json.dumps({"corrected_text": target, "changes": [], "requires_review": False})
        if "영상 소개글 편집자" in prompt:
            return json.dumps(
                {
                    "title_hook": "OpenAI fixture의 숨은 포인트",
                    "body": "OpenAI fixture line에서 놓치기 쉬운 포인트를 살펴볼까요? 실제 내용을 영상에서 확인해 보세요.",
                    "highlights": ["OpenAI"],
                    "evidence_segment_ids": ["segment-0001"],
                    "question_used": True,
                    "call_to_action": "실제 내용을 영상에서 확인해 보세요.",
                },
                ensure_ascii=False,
            )
        return json.dumps({"text": "Integration summary.", "evidence_segment_ids": ["segment-0001"]})


@pytest.fixture
def job() -> Job:
    job_id = "v2-pipe-" + uuid.uuid4().hex
    work_dir = JOB_WORK_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "input.mp3"
    source.write_bytes(b"media")
    value = Job(job_id, str(source), "queued", work_dir, JobOptions())
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())


def application(runtime: Runtime):
    return build_application(
        source_adapter=RejectingUrlSourceAdapter(),
        ffmpeg_runner=Runner(),
        stt_engine=Stt(),
        qwen_runtime=runtime,
        glossary=("OpenAI",),
    )


def test_summary_mode_remains_default_and_introduction_is_empty(job: Job) -> None:
    runtime = Runtime()
    result = application(runtime).run(job)
    assert result.summary is not None
    assert result.introduction is None
    assert result.job.status == "archived"
    assert len(runtime.prompts) == 2


def test_introduction_mode_returns_only_video_introduction(job: Job) -> None:
    runtime = Runtime()
    result = application(runtime).run(job, output_mode="introduction")
    assert result.summary is None
    assert result.introduction is not None
    assert result.introduction.highlights == ("OpenAI",)
    assert len(runtime.prompts) == 2


def test_both_mode_reuses_transcript_and_returns_two_independent_outputs(job: Job) -> None:
    runtime = Runtime()
    result = application(runtime).run(job, output_mode="both")
    assert result.summary is not None
    assert result.introduction is not None
    assert result.summary.text == "Integration summary."
    assert result.introduction.title_hook == "OpenAI fixture의 숨은 포인트"
    assert len(runtime.prompts) == 3


def test_progress_sink_receives_monotonic_terminal_events(job: Job) -> None:
    from tests.fakes_progress import FakeClock, RecordingProgressSink

    runtime = Runtime()
    sink = RecordingProgressSink()
    clock = FakeClock()
    result = application(runtime).run(job, progress_sink=sink, progress_clock=clock)
    assert result.job.status == "archived"
    assert sink.events[-1].stage == "completed"
    values = [event.overall_progress for event in sink.events if event.overall_progress is not None]
    assert values == sorted(values)
    assert sink.events[-1].can_cancel is False
