"""P13-04 fake-only pipeline wiring tests."""

import json
from pathlib import Path
import uuid

import pytest

from backend.contracts import CleanupPolicy, Job, JobOptions
from backend.main import build_application
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts
from tests.integration.test_pipeline import RecordingRunner, RecordingSourceAdapter, RecordingSttEngine


class CorrectionRuntime:
    """Return the correction identity response and record correction prompts."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Plans:" in prompt:
            return json.dumps({"edits": [], "requires_review": False})
        raise AssertionError("correction runtime received a generation prompt")


class HermesGenerationRuntime:
    """Return a strict summary response and record generation prompts."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {"text": "Hermes 생성 요약입니다.", "evidence_segment_ids": ["segment-0001"]},
            ensure_ascii=False,
        )


@pytest.fixture
def job() -> Job:
    job_id = "p13-04-" + uuid.uuid4().hex
    work_dir = JOB_WORK_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "input.mp3"
    source.write_bytes(b"local media")
    value = Job(job_id, str(source), "queued", work_dir, JobOptions())
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())


def test_hermes_generation_does_not_replace_correction_runtime(job: Job) -> None:
    correction = CorrectionRuntime()
    generation = HermesGenerationRuntime()
    application = build_application(
        source_adapter=RecordingSourceAdapter(),
        ffmpeg_runner=RecordingRunner(),
        stt_engine=RecordingSttEngine(),
        qwen_runtime=correction,
        generation_runtime=generation,
    )

    result = application.run(job, summary_instruction="핵심만 간결하게")

    assert result.summary is not None
    assert result.summary.text == "Hermes 생성 요약입니다."
    assert correction.prompts
    assert all("Plans:" in prompt for prompt in correction.prompts)
    assert len(generation.prompts) == 1
    assert "핵심만 간결하게" in generation.prompts[0]


def test_invalid_generation_request_fails_before_media_or_stt(job: Job) -> None:
    correction = CorrectionRuntime()
    generation = HermesGenerationRuntime()
    application = build_application(
        source_adapter=RecordingSourceAdapter(),
        ffmpeg_runner=RecordingRunner(),
        stt_engine=RecordingSttEngine(),
        qwen_runtime=correction,
        generation_runtime=generation,
    )

    with pytest.raises(ValueError):
        application.run(job, summary_instruction=" ")

    assert correction.prompts == []
    assert generation.prompts == []
