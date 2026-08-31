"""Unit tests for B03 job JSON persistence and artifact cleanup."""

import uuid

import pytest

from backend.contracts import CleanupPolicy, Job, JobOptions, StorageError, UnsafePathError
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts, read_job_json, write_job_json


@pytest.fixture
def job() -> Job:
    """Yield a unique, cleanup-owned job whose files stay under JOB_WORK_ROOT."""
    job_id = "t02-storage-" + uuid.uuid4().hex
    value = Job(job_id, "fixture://storage", "queued", JOB_WORK_ROOT / job_id, JobOptions())
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())


def test_write_then_read_json_round_trips_inside_its_job_directory(job: Job) -> None:
    payload = {"title": "테스트", "count": 2, "tags": ["one", "two"]}

    path = write_job_json(job, "metadata.json", payload)

    assert path == job.work_dir / "metadata.json"
    assert path.exists()
    assert path.is_relative_to(job.work_dir)
    assert read_job_json(job, "metadata.json") == payload


def test_cleanup_retains_requested_json_and_removes_other_artifacts(job: Job) -> None:
    metadata = write_job_json(job, "metadata.json", {"keep": True})
    temporary = job.work_dir / "audio.tmp"
    temporary.write_text("temporary", encoding="utf-8")

    report = cleanup_artifacts(job, CleanupPolicy(("metadata.json",)))

    assert metadata in report.retained
    assert metadata.exists()
    assert not temporary.exists()
    assert job.work_dir.exists()


def test_cleanup_without_retention_removes_the_complete_work_directory(job: Job) -> None:
    path = write_job_json(job, "metadata.json", {"remove": True})

    report = cleanup_artifacts(job, CleanupPolicy())

    assert not job.work_dir.exists()
    assert path in report.removed
    assert job.work_dir in report.removed


def test_work_directory_outside_job_root_is_rejected() -> None:
    outside = Job(
        "outside",
        "fixture://storage",
        "queued",
        JOB_WORK_ROOT.parent / "outside",
        JobOptions(),
    )

    with pytest.raises(UnsafePathError):
        write_job_json(outside, "metadata.json", {})


def test_invalid_artifact_name_and_missing_artifact_are_rejected(job: Job) -> None:
    with pytest.raises(UnsafePathError):
        write_job_json(job, "../escape.json", {})
    with pytest.raises(StorageError):
        read_job_json(job, "missing.json")
