"""Read-only CLI contract for human inspection of a completed job."""


def inspect_job(job_path: str) -> object:
    """Format transcript timing, review items, and summary evidence for review.

    The future tool must never alter job data or cause model/media operations.
    """
    raise NotImplementedError("T04: inspect_job has not been implemented")


def main() -> int:
    """Provide the future read-only CLI entry point; parse no arguments yet."""
    raise NotImplementedError("T04: CLI entry point has not been implemented")
