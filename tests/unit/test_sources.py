"""Unit tests for B04 URL validation and injected audio acquisition."""

import uuid

import pytest

from backend.contracts import InputSourceError, Job, JobOptions, UnsafePathError
from backend.sources import acquire_source_audio, validate_source
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts
from backend.contracts import CleanupPolicy


class RecordingAdapter:
    """Write configured content at the supplied destination without network I/O."""

    def __init__(self, write_output: bool = True, error: Exception | None = None) -> None:
        self.write_output = write_output
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def acquire(self, source_url: str, destination: object) -> None:
        self.calls.append((source_url, destination))
        if self.error is not None:
            raise self.error
        if self.write_output:
            destination.write_bytes(b"fixture audio")  # type: ignore[union-attr]


@pytest.fixture
def job() -> Job:
    """Yield one cleanup-owned B04 job under the approved work root."""
    job_id = "t02-sources-" + uuid.uuid4().hex
    value = Job(
        job_id,
        "https://www.youtube.com/watch?v=fixture123",
        "queued",
        JOB_WORK_ROOT / job_id,
        JobOptions(),
    )
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())


@pytest.mark.parametrize(
    "source",
    [
        "https://www.youtube.com/watch?v=fixture123",
        "https://youtu.be/fixture123",
    ],
)
def test_supported_youtube_urls_are_accepted(source: str) -> None:
    assert validate_source(source) is None


@pytest.mark.parametrize(
    "source",
    [
        " ftp://youtube.com/a",
        "https://youtube.com.evil/watch?v=x",
        "https://youtube.com/watch?v=",
        " https://youtu.be/fixture123",
        "https://youtube.com:bad/watch?v=x",
    ],
)
def test_unsupported_or_malformed_urls_are_rejected(source: str) -> None:
    with pytest.raises(InputSourceError):
        validate_source(source)


def test_acquire_uses_adapter_once_and_returns_work_directory_artifact(job: Job) -> None:
    adapter = RecordingAdapter()

    artifact = acquire_source_audio(job, adapter)  # type: ignore[arg-type]

    assert len(adapter.calls) == 1
    assert adapter.calls[0][0] == job.source
    assert artifact.job_id == job.job_id
    assert artifact.path == job.work_dir.resolve() / "source-audio.wav"
    assert artifact.path.exists()
    assert artifact.path.read_bytes() == b"fixture audio"
    assert artifact.path.is_relative_to(job.work_dir.resolve())


def test_invalid_adapter_and_outside_work_directory_are_rejected(job: Job) -> None:
    with pytest.raises(TypeError):
        acquire_source_audio(job, object())  # type: ignore[arg-type]

    outside = Job(
        "outside",
        job.source,
        "queued",
        JOB_WORK_ROOT.parent / "outside",
        JobOptions(),
    )
    with pytest.raises(UnsafePathError):
        acquire_source_audio(outside, RecordingAdapter())  # type: ignore[arg-type]


def test_adapter_errors_and_missing_destination_are_mapped(job: Job) -> None:
    with pytest.raises(InputSourceError):
        acquire_source_audio(job, RecordingAdapter(error=RuntimeError("download failed")))  # type: ignore[arg-type]

    with pytest.raises(UnsafePathError):
        acquire_source_audio(job, RecordingAdapter(write_output=False))  # type: ignore[arg-type]
