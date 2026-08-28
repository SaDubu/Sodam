"""Token-based text protection and restoration."""

import re

from .contracts import ProtectedText, ProtectionError, RawSegment

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
