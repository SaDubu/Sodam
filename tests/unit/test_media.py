"""Unit tests for B05 local-media extraction using an in-memory runner."""

from pathlib import Path
import uuid

import pytest

from backend.contracts import (
    CleanupPolicy,
    InputSourceError,
    Job,
    JobOptions,
    MediaExtractionError,
    UnsafePathError,
)
from backend.media import extract_audio
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts


class RecordingRunner:
    """Record the FFmpeg vector and optionally create the requested output."""

    def __init__(self, write_output: bool = True, error: Exception | None = None) -> None:
        self.write_output = write_output
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, arguments: list[str]) -> None:
        self.calls.append(list(arguments))
        if self.error is not None:
            raise self.error
        if self.write_output:
            Path(arguments[-1]).write_bytes(b"normalized wav fixture")


@pytest.fixture
def job() -> Job:
    """Yield one job whose only test files live in its approved work directory."""
    job_id = "t02-media-" + uuid.uuid4().hex
    value = Job(job_id, "fixture://media", "queued", JOB_WORK_ROOT / job_id, JobOptions())
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())


def _source(job: Job, name: str = "input.mp3") -> Path:
    job.work_dir.mkdir(parents=True, exist_ok=True)
    path = job.work_dir / name
    path.write_bytes(b"source fixture")
    return path


def test_runner_receives_exact_normalization_vector_and_returns_artifact(job: Job) -> None:
    source = _source(job)
    runner = RecordingRunner()

    artifact = extract_audio(job, source, runner)  # type: ignore[arg-type]

    output = job.work_dir / "normalized-audio.wav"
    assert runner.calls == [
        [
            "-i", str(source.resolve()), "-vn", "-ac", "1", "-ar", "16000",
            "-sample_fmt", "s16", str(output),
        ]
    ]
    assert artifact.job_id == job.job_id
    assert artifact.path == output.resolve()
    assert artifact.duration_seconds is None
    assert artifact.path.is_file()
    assert artifact.path.stat().st_size > 0


@pytest.mark.parametrize("source_name", ["missing.wav", "unsupported.txt"])
def test_missing_or_unsupported_source_is_rejected(job: Job, source_name: str) -> None:
    with pytest.raises(InputSourceError):
        extract_audio(job, job.work_dir / source_name, RecordingRunner())  # type: ignore[arg-type]


def test_runner_failure_and_missing_output_are_mapped(job: Job) -> None:
    source = _source(job)

    with pytest.raises(MediaExtractionError):
        extract_audio(job, source, RecordingRunner(error=RuntimeError("ffmpeg failed")))  # type: ignore[arg-type]
    with pytest.raises(MediaExtractionError):
        extract_audio(job, source, RecordingRunner(write_output=False))  # type: ignore[arg-type]


def test_unsafe_work_directory_and_existing_output_are_rejected(job: Job) -> None:
    source = _source(job)
    outside = Job(
        "outside",
        "fixture://media",
        "queued",
        JOB_WORK_ROOT.parent / "outside",
        JobOptions(),
    )
    with pytest.raises(UnsafePathError):
        extract_audio(outside, source, RecordingRunner())  # type: ignore[arg-type]

    (job.work_dir / "normalized-audio.wav").write_bytes(b"already present")
    with pytest.raises(UnsafePathError):
        extract_audio(job, source, RecordingRunner())  # type: ignore[arg-type]


def test_invalid_runner_contract_is_rejected(job: Job) -> None:
    with pytest.raises(TypeError):
        extract_audio(job, _source(job), object())  # type: ignore[arg-type]
