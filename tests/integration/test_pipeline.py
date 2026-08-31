"""Fake-only integration tests for the B13 sequential local pipeline."""

import json
from pathlib import Path
import uuid

import pytest

from backend.contracts import CleanupPolicy, Job, JobOptions, MediaExtractionError
from backend.main import build_application
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts


class RecordingSourceAdapter:
    """Record URL acquisition attempts; local-media tests must not call it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def acquire(self, source_url: str, destination: Path) -> None:
        self.calls.append((source_url, destination))
        destination.write_bytes(b"source audio")


class RecordingRunner:
    """Write a non-empty normalized artifact or raise the configured failure."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, arguments: list[str]) -> None:
        self.calls.append(list(arguments))
        if self.error is not None:
            raise self.error
        Path(arguments[-1]).write_bytes(b"normalized audio")


class RecordingSttEngine:
    """Return one deterministic segment and record the resolved audio path."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def transcribe(self, audio_path: str) -> object:
        self.paths.append(audio_path)
        return [{"start": 0.0, "end": 1.0, "text": "OpenAI fixture line."}]


class PipelineRuntime:
    """Return a correction response or final evidence-linked summary by prompt kind."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Target text:" in prompt:
            target = json.loads(prompt.rsplit("\n", 1)[-1])
            return json.dumps(
                {"corrected_text": target, "changes": [], "requires_review": False}
            )
        return json.dumps(
            {
                "text": "Integration summary.",
                "evidence_segment_ids": ["segment-0001"],
            }
        )


@pytest.fixture
def job() -> Job:
    """Yield a job whose source and every generated artifact stay in one work dir."""
    job_id = "t05-" + uuid.uuid4().hex
    work_dir = JOB_WORK_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "input.mp3"
    source.write_bytes(b"local media")
    value = Job(job_id, str(source), "queued", work_dir, JobOptions())
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())
        assert not work_dir.exists()


def _application(
    source_adapter: RecordingSourceAdapter,
    runner: RecordingRunner,
    stt: RecordingSttEngine,
    runtime: PipelineRuntime,
):
    return build_application(
        source_adapter=source_adapter,
        ffmpeg_runner=runner,
        stt_engine=stt,
        qwen_runtime=runtime,
        glossary=("OpenAI",),
    )


def test_local_success_runs_injected_collaborators_then_archives_and_cleans(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner()
    stt = RecordingSttEngine()
    runtime = PipelineRuntime()

    result = _application(source_adapter, runner, stt, runtime).run(job)

    assert result.job.status == "archived"
    assert result.transcript is not None
    assert result.transcript.final_text == "OpenAI fixture line."
    assert result.summary is not None
    assert result.summary.text == "Integration summary."
    assert result.summary.evidence_segment_ids == ("segment-0001",)
    assert result.review_items == ()
    assert source_adapter.calls == []
    assert len(runner.calls) == 1
    assert runner.calls[0][0:2] == ["-i", str((job.work_dir / "input.mp3").resolve())]
    assert len(stt.paths) == 1
    assert len(runtime.prompts) == 2
    assert not job.work_dir.exists()


def test_start_cancellation_archives_and_cleans_without_collaborator_calls(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner()
    stt = RecordingSttEngine()
    runtime = PipelineRuntime()

    result = _application(source_adapter, runner, stt, runtime).run(
        job,
        cancellation_requested=lambda _: True,
    )

    assert result.job.status == "archived"
    assert result.transcript is None
    assert result.summary is None
    assert source_adapter.calls == []
    assert runner.calls == []
    assert stt.paths == []
    assert runtime.prompts == []
    assert not job.work_dir.exists()


def test_runner_failure_propagates_as_media_error_and_cleans(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner(RuntimeError("ffmpeg failed"))

    with pytest.raises(MediaExtractionError):
        _application(source_adapter, runner, RecordingSttEngine(), PipelineRuntime()).run(job)

    assert len(runner.calls) == 1
    assert not job.work_dir.exists()


def test_keyboard_interrupt_is_re_raised_after_best_effort_cleanup(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        _application(source_adapter, runner, RecordingSttEngine(), PipelineRuntime()).run(job)

    assert len(runner.calls) == 1
    assert not job.work_dir.exists()
