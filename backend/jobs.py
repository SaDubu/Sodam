"""Job creation, status transitions, and cancellation contracts."""

from .contracts import Job, JobOptions


def create_job(source: str, options: JobOptions) -> Job:
    """Create a queued job for a readable local path or supported URL.

    Contract: normalize and validate `source`, allocate a job-owned temporary
    directory, persist the queued state, or raise ``InputSourceError``.  This
    skeleton intentionally creates no directories and persists nothing.
    """
    raise NotImplementedError("B02: create_job has not been implemented")


def request_cancellation(job: Job) -> Job:
    """Request a safe cancellation without deleting job artifacts.

    Implementation must permit cancellation only from documented running states
    and return the updated job state.
    """
    raise NotImplementedError("B02: request_cancellation has not been implemented")
