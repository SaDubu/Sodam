"""Persistence, transcript assembly, and safe-cleanup contracts."""

from .contracts import CleanupReport, Job, RawSegment, Transcript


def assemble_transcript(segments: list[RawSegment]) -> Transcript:
    """Assemble valid time-ordered segments into a transcript and time index.

    A later implementation must reject missing/duplicate IDs and reverse timing;
    it will not repair those input errors implicitly.
    """
    raise NotImplementedError("B11: assemble_transcript has not been implemented")


def cleanup_artifacts(job: Job, policy: object) -> CleanupReport:
    """Apply a retention policy exclusively inside `job.work_dir`.

    This skeleton performs no filesystem action.  Implementations must refuse a
    deletion target outside the job-owned workspace.
    """
    raise NotImplementedError("B03: cleanup_artifacts has not been implemented")
