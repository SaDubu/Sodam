"""Token-based text protection and restoration."""

from collections.abc import Mapping
import re

from .contracts import (
    EditablePart,
    EditableTextPlan,
    LockedPart,
    ProtectedText,
    ProtectionError,
    RawSegment,
)

_PLACEHOLDER_KEY_RE = re.compile(r"^\[\[SODAM_PROTECTED_\d+\]\]$")
_PLACEHOLDER_TOKEN_RE = re.compile(r"\[\[SODAM_PROTECTED_\d+\]\]")
_NUMBER_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

def protect_tokens(
    segments: list[RawSegment],
    glossary: tuple[str, ...],
) -> ProtectedText:
    """Protect targets in joined segment text with placeholders."""
    if not isinstance(segments, list):
        raise TypeError("segments must be a list")
    if any(not isinstance(segment, RawSegment) for segment in segments):
        raise TypeError("every segment must be a RawSegment")
    if not isinstance(glossary, tuple):
        raise TypeError("glossary must be a tuple")
    seen_glossary: set[str] = set()
    for item in glossary:
        if not isinstance(item, str):
            raise TypeError("every glossary item must be a str")
        if not item or item != item.strip():
            raise ProtectionError("glossary item must not have surrounding whitespace")
        if item in seen_glossary:
            raise ProtectionError("duplicate glossary item: " + repr(item))
        seen_glossary.add(item)
    text = "\n".join(seg.raw_text for seg in segments)

    glossary_sorted = sorted(glossary, key=len, reverse=True)
    parts = [r"\[\[SODAM_PROTECTED_\d+\]\]"]
    if glossary_sorted:
        parts.append("|".join(re.escape(s) for s in glossary_sorted))
    parts.extend((
        r"https?://[^\s]+",
        r"\d{4}[-/]\d{2}[-/]\d{2}|\d{4}\ub144\d{1,2}\uc6d4\d{1,2}\uc77c",
        rf"(?:[$\u20a9\uffe5]{_NUMBER_PATTERN}|{_NUMBER_PATTERN}\uc6d4)",
        _NUMBER_PATTERN,
        r"[A-Z]{2,10}",
    ))
    try:
        protected_pattern = re.compile("(?:" + "|".join(parts) + ")")
    except re.error as exc:
        raise ProtectionError("could not build protection pattern") from exc

    replacements: dict[str, str] = {}
    next_number = 1
    max_attempts = len(text) + sum(len(item) for item in glossary) + 1

    def replacement_for(match: re.Match[str]) -> str:
        nonlocal next_number
        for _ in range(max_attempts):
            candidate = f"[[SODAM_PROTECTED_{next_number:04d}]]"
            next_number += 1
            if (
                candidate not in text
                and all(candidate not in item for item in glossary)
                and candidate not in replacements
            ):
                replacements[candidate] = match.group(0)
                return candidate
        raise ProtectionError("could not create a collision-free placeholder")

    try:
        protected_text = protected_pattern.sub(replacement_for, text)
    except re.error as exc:
        raise ProtectionError("could not protect tokens") from exc
    return ProtectedText(text=protected_text, replacements=replacements)


# ---- restore_tokens ------------------------------------------------

def restore_tokens(protected: ProtectedText, text: str) -> str:
    """Restore placeholders -- original values back exactly once."""
    if not isinstance(protected, ProtectedText):
        raise TypeError("protected must be ProtectedText")
    if not isinstance(text, str):
        raise TypeError("text must be str")

    replacements = protected.replacements
    if not isinstance(replacements, dict):
        raise ProtectionError("replacements must be a dict[str, str]")

    for key, value in replacements.items():
        if not isinstance(key, str) or not _PLACEHOLDER_KEY_RE.fullmatch(key):
            raise ProtectionError("replacement keys must be valid placeholders")
        if not isinstance(value, str):
            raise ProtectionError("replacement values must be strings")

    found_tokens = set(_PLACEHOLDER_TOKEN_RE.findall(text))
    if found_tokens - set(replacements):
        raise ProtectionError("text contains an unknown placeholder")
    for key in replacements:
        if text.count(key) != 1:
            raise ProtectionError("every placeholder must occur exactly once")

    if not replacements:
        return text
    restore_pattern = re.compile("|".join(re.escape(key) for key in replacements))
    return restore_pattern.sub(lambda match: replacements[match.group(0)], text)


def _validate_protected_for_split(protected: ProtectedText) -> list[re.Match[str]]:
    """Validate ProtectedText integrity and return placeholder matches in order."""
    if not isinstance(protected, ProtectedText):
        raise TypeError("protected must be ProtectedText")
    if not isinstance(protected.text, str):
        raise TypeError("protected.text must be str")
    replacements = protected.replacements
    if not isinstance(replacements, dict):
        raise ProtectionError("replacements must be a dict[str, str]")
    for key, value in replacements.items():
        if not isinstance(key, str) or not _PLACEHOLDER_KEY_RE.fullmatch(key):
            raise ProtectionError("replacement keys must be valid placeholders")
        if not isinstance(value, str):
            raise ProtectionError("replacement values must be strings")
    matches = list(_PLACEHOLDER_TOKEN_RE.finditer(protected.text))
    keys = [match.group(0) for match in matches]
    if len(keys) != len(set(keys)):
        raise ProtectionError("each placeholder must occur only once")
    if set(keys) != set(replacements):
        raise ProtectionError("placeholder map and text are inconsistent")
    return matches


def split_locked_parts(
    protected: ProtectedText,
    segment_id: str,
) -> EditableTextPlan:
    """Split protected text into ordered editable and immutable locked parts."""
    matches = _validate_protected_for_split(protected)
    if not isinstance(segment_id, str):
        raise TypeError("segment_id must be str")
    if not segment_id or segment_id != segment_id.strip():
        raise ValueError("segment_id must be non-blank without surrounding whitespace")

    parts: list[EditablePart | LockedPart] = []
    cursor = 0
    editable_index = 0
    locked_index = 0
    for match in matches:
        parts.append(
            EditablePart(
                f"{segment_id}:editable:{editable_index:04d}",
                protected.text[cursor : match.start()],
            )
        )
        editable_index += 1
        key = match.group(0)
        parts.append(
            LockedPart(
                f"{segment_id}:locked:{locked_index:04d}",
                protected.replacements[key],
            )
        )
        locked_index += 1
        cursor = match.end()
    parts.append(
        EditablePart(
            f"{segment_id}:editable:{editable_index:04d}",
            protected.text[cursor:],
        )
    )
    original_text = restore_tokens(protected, protected.text)
    return EditableTextPlan(segment_id, tuple(parts), original_text)


def reassemble_locked_parts(
    plan: EditableTextPlan,
    replacements: Mapping[str, str] | None = None,
) -> str:
    """Reassemble ordered parts while keeping every locked value immutable."""
    if not isinstance(plan, EditableTextPlan):
        raise TypeError("plan must be EditableTextPlan")
    if not isinstance(plan.segment_id, str) or not plan.segment_id:
        raise ProtectionError("plan.segment_id must be a non-blank str")
    if not isinstance(plan.original_text, str):
        raise TypeError("plan.original_text must be str")
    if not isinstance(plan.parts, tuple):
        raise TypeError("plan.parts must be a tuple")

    editable_ids: set[str] = set()
    locked_ids: set[str] = set()
    for part in plan.parts:
        if not isinstance(part, (EditablePart, LockedPart)):
            raise ProtectionError("plan contains an unknown part type")
        if not isinstance(part.part_id, str) or not part.part_id:
            raise ProtectionError("part_id must be a non-blank str")
        if part.part_id in editable_ids or part.part_id in locked_ids:
            raise ProtectionError("part IDs must be unique")
        if not isinstance(part.text, str):
            raise TypeError("part.text must be str")
        if isinstance(part, EditablePart):
            editable_ids.add(part.part_id)
        else:
            locked_ids.add(part.part_id)

    if replacements is None:
        replacement_map: Mapping[str, str] = {}
    else:
        if not isinstance(replacements, Mapping):
            raise TypeError("replacements must be a mapping")
        replacement_map = replacements
        for part_id, value in replacement_map.items():
            if not isinstance(part_id, str) or not isinstance(value, str):
                raise TypeError("replacement IDs and values must be strings")
            if part_id not in editable_ids:
                raise ProtectionError("only editable part IDs may be replaced")

    result = "".join(
        replacement_map.get(part.part_id, part.text)
        for part in plan.parts
    )
    if replacements is None and result != plan.original_text:
        raise ProtectionError("parts do not reassemble to original text")
    return result
