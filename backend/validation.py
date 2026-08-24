"""Revision-difference and review-queue contracts."""

from .contracts import ProtectedText, ReviewResult


def validate_revision(raw: str, corrected: str, protections: ProtectedText) -> ReviewResult:
    """Classify revision differences as safe or user-review-required.

    A future implementation must reject lost protected tokens and prevent
    automatic approval of numbers, proper nouns, and fact-changing edits.
    """
    raise NotImplementedError("B10: validate_revision has not been implemented")
