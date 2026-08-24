"""Reversible protected-token transformation contracts."""

from .contracts import ProtectedText, RawSegment


def protect_tokens(segments: list[RawSegment], glossary: tuple[str, ...]) -> ProtectedText:
    """Replace protected values with collision-free placeholders.

    The eventual result must retain a one-to-one restoration map for numbers,
    dates, amounts, URLs, abbreviations, and glossary entries.
    """
    raise NotImplementedError("B07: protect_tokens has not been implemented")


def restore_tokens(protected: ProtectedText, text: str) -> str:
    """Restore every protected placeholder or raise on a missing/altered token."""
    raise NotImplementedError("B07: restore_tokens has not been implemented")
