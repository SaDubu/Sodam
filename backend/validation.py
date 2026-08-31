"""Revision-difference and review-queue contracts."""

import re
from difflib import SequenceMatcher

from .contracts import ProtectedText, ProtectionError, ReviewResult

SAFE_PUNCTUATION = frozenset(".,!?;:()[]{}'\"-")

_PLACEHOLDER_TOKEN_RE = re.compile(r"\[\[SODAM_PROTECTED_\d+\]\]")
_PLACEHOLDER_KEY_RE = re.compile(r"^\[\[SODAM_PROTECTED_\d+\]\]$")


def _validate_inputs(raw: str, corrected: str, protections: ProtectedText) -> None:
    """Validate types, replacement-map shape, and placeholder integrity."""
    if not isinstance(raw, str):
        raise TypeError("raw must be str")
    if not isinstance(corrected, str):
        raise TypeError("corrected must be str")
    if not isinstance(protections, ProtectedText):
        raise TypeError("protections must be a ProtectedText")
    replacements = protections.replacements
    if not isinstance(replacements, dict):
        raise ProtectionError("replacements must be a dict[str, str]")
    for key, value in replacements.items():
        if not isinstance(key, str) or not _PLACEHOLDER_KEY_RE.fullmatch(key):
            raise ProtectionError(
                "replacement keys must be valid placeholder tokens, got %r" % (key,)
            )
        if not isinstance(value, str):
            raise ProtectionError("replacement values must be str")

    raw_tokens = tuple(_PLACEHOLDER_TOKEN_RE.findall(raw))
    corrected_tokens = tuple(_PLACEHOLDER_TOKEN_RE.findall(corrected))
    if corrected_tokens != raw_tokens:
        raise ProtectionError(
            "placeholder tokens were lost, added, duplicated, or reordered"
        )

    # Every placeholder-shaped token in raw and corrected must be a known key.
    unknown_in_raw = [token for token in raw_tokens if token not in replacements]
    if unknown_in_raw:
        raise ProtectionError("raw contains unknown placeholders: %r" % (unknown_in_raw,))
    unknown_in_corrected = [token for token in corrected_tokens if token not in replacements]
    if unknown_in_corrected:
        raise ProtectionError("corrected contains unknown placeholders: %r" % (unknown_in_corrected,))

    # Every known key must occur exactly once in raw and in corrected.
    for key in replacements:
        if raw.count(key) != 1:
            raise ProtectionError(
                "known placeholder %r must occur exactly once in raw" % (key,)
            )
        if corrected.count(key) != 1:
            raise ProtectionError(
                "known placeholder %r must occur exactly once in corrected" % (key,)
            )


def _is_safe_formatting(piece_raw: str, piece_corrected: str) -> bool:
    """True when the combined operands only contain whitespace and SAFE_PUNCTUATION."""
    combined = piece_raw + piece_corrected
    return all(ch.isspace() or ch in SAFE_PUNCTUATION for ch in combined)


def validate_revision(
    raw: str,
    corrected: str,
    protections: ProtectedText,
) -> ReviewResult:
    """Classify revision differences as safe or user-review-required.

    Whitespace and SAFE_PUNCTUATION-only edits are auto-approved; every other
    change keeps the raw text and returns ordered review items. Lost, added,
    duplicated, or reordered protected tokens are rejected outright.
    """
    _validate_inputs(raw, corrected, protections)

    matcher = SequenceMatcher(a=raw, b=corrected, autojunk=False)
    review_items: tuple[dict[str, str], ...] = ()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        piece_raw = raw[i1:i2]
        piece_corrected = corrected[j1:j2]
        if _is_safe_formatting(piece_raw, piece_corrected):
            continue
        review_items = review_items + (
            {
                "kind": "review_required",
                "raw": piece_raw,
                "corrected": piece_corrected,
                "reason": "non_formatting_change",
            },
        )

    if review_items:
        return ReviewResult(approved_text=raw, review_items=review_items)
    return ReviewResult(approved_text=corrected, review_items=())
