"""CLI contract for reproducible transcript-correction evaluation."""


def evaluate_transcript(fixture_path: str) -> object:
    """Calculate documented correction and safety metrics from fixed fixtures.

    Planned metrics are protected-token preservation, correction agreement,
    risky-auto-approval count, and elapsed processing time.  No metrics are
    calculated by this skeleton.
    """
    raise NotImplementedError("T03: evaluate_transcript has not been implemented")


def main() -> int:
    """Provide the future read-only CLI entry point; parse no arguments yet."""
    raise NotImplementedError("T03: CLI entry point has not been implemented")
