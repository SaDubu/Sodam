"""Unit tests for B02 job creation, state transitions, and cancellation."""

import re
from pathlib import Path

import pytest

from backend.contracts import (
    InputSourceError,
    Job,
    JobOptions,
    JobStateError,
    SodamError,
)
from backend.jobs import create_job, request_cancellation, transition_job


def _queued_job() -> Job:
    """Return an in-memory queued Job for transition-only tests."""
    return Job(
        job_id="unit-job",
        source="fixture://unit",
        status="queued",
        work_dir=Path(r"D:\AI-Legion\Sodam-data\tmp\jobs\unit-job"),
        options=JobOptions(),
    )


def test_create_job_normalizes_existing_local_source_without_side_effects() -> None:
    source_path = Path(__file__).resolve()

    job = create_job(str(source_path), JobOptions())
    slash_job = create_job(str(source_path).replace("\\", "/"), JobOptions())

    assert job.status == "queued"
    assert job.source == str(source_path)
    assert slash_job.status == "queued"
    assert slash_job.source == str(source_path)
    assert re.fullmatch(r"[0-9a-f]{32}", job.job_id)
    assert job.work_dir.name == job.job_id
    from backend.runtime_paths import JOB_WORK_ROOT
    assert job.work_dir.parent == JOB_WORK_ROOT
    assert not job.work_dir.exists()


def test_create_job_normalizes_url_and_rejects_invalid_inputs() -> None:
    job = create_job(" https://example.com/watch ", JobOptions())

    assert job.source == "https://example.com/watch"
    with pytest.raises(InputSourceError):
        create_job("ftp://example.com/audio", JobOptions())
    with pytest.raises(InputSourceError):
        create_job("not-found.media", JobOptions())
    with pytest.raises(TypeError):
        create_job("https://example.com/watch", object())  # type: ignore[arg-type]


def test_transition_returns_new_job_for_allowed_transition() -> None:
    queued = _queued_job()

    transitioned = transition_job(queued, "acquiring")

    assert transitioned is not queued
    assert transitioned.status == "acquiring"
    assert queued.status == "queued"
    assert transitioned.job_id == queued.job_id


def test_transition_rejects_invalid_or_disallowed_targets() -> None:
    queued = _queued_job()

    with pytest.raises(JobStateError):
        transition_job(queued, "completed")
    with pytest.raises(JobStateError):
        transition_job(queued, "queued")
    with pytest.raises(TypeError):
        transition_job(queued, "not-a-status")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        transition_job(queued, 12345)  # type: ignore[arg-type]


def test_request_cancellation_allows_running_job_and_blocks_terminal_states() -> None:
    acquiring = transition_job(_queued_job(), "acquiring")

    cancelling = request_cancellation(acquiring)

    assert cancelling.status == "cancelling"
    assert acquiring.status == "acquiring"
    with pytest.raises(JobStateError):
        request_cancellation(cancelling)
    with pytest.raises(JobStateError):
        request_cancellation(
            Job(
                job_id="completed-job",
                source="fixture://unit",
                status="completed",
                work_dir=Path(r"D:\AI-Legion\Sodam-data\tmp\jobs\completed-job"),
                options=JobOptions(),
            )
        )


def test_job_state_error_is_a_domain_error() -> None:
    assert issubclass(JobStateError, SodamError)
