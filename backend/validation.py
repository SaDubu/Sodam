"""Revision-difference and review-queue contracts."""

import re
from difflib import SequenceMatcher
from typing import Iterator

from .contracts import ProtectedText, ProtectionError, ReviewResult, ReviewSpan

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


def _iter_editable_revision_pairs(
    raw: str, corrected: str, protections: ProtectedText
) -> Iterator[tuple[str, str, int]]:
    """Yield gaps between matching tokens after _validate_inputs has passed.

    Offsets count restored source characters, not placeholder characters or
    proposed replacement lengths. Empty gaps are retained for insertion review.
    """
    raw_cursor = corrected_cursor = restored_offset = 0
    for raw_token, corrected_token in zip(
        _PLACEHOLDER_TOKEN_RE.finditer(raw), _PLACEHOLDER_TOKEN_RE.finditer(corrected)
    ):
        raw_gap = raw[raw_cursor:raw_token.start()]
        yield raw_gap, corrected[corrected_cursor:corrected_token.start()], restored_offset
        restored_offset += len(raw_gap) + len(protections.replacements[raw_token.group()])
        raw_cursor = raw_token.end()
        corrected_cursor = corrected_token.end()
    yield raw[raw_cursor:], corrected[corrected_cursor:], restored_offset


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

    review_items: list[dict[str, str]] = []
    review_spans: list[ReviewSpan] = []
    for raw_gap, corrected_gap, base in _iter_editable_revision_pairs(raw, corrected, protections):
        matcher = SequenceMatcher(a=raw_gap, b=corrected_gap, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            piece_raw = raw_gap[i1:i2]
            piece_corrected = corrected_gap[j1:j2]
            if _is_safe_formatting(piece_raw, piece_corrected):
                continue
            review_items.append(
                {
                    "kind": "review_required",
                    "raw": piece_raw,
                    "corrected": piece_corrected,
                    "reason": "non_formatting_change",
                }
            )
            review_spans.append(
                ReviewSpan(base + i1, base + i2) if piece_raw else ReviewSpan(None, None)
            )

    if review_items:
        return ReviewResult(raw, tuple(review_items), tuple(review_spans))
    return ReviewResult(approved_text=corrected, review_items=())
