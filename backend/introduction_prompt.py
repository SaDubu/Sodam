"""Render the user-authored introduction template without rewriting its data."""

import json
from pathlib import Path
import re


TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "introduction.md"
_PLACEHOLDERS = ("{{REVIEWED_TRANSCRIPT}}", "{{HIGHLIGHT_CANDIDATES}}")
_PLACEHOLDER_RE = re.compile("|".join(re.escape(value) for value in _PLACEHOLDERS))


def render_introduction_prompt(
    evidence: list[dict[str, object]], highlights: list[dict[str, object]]
) -> str:
    """Read the UTF-8 template and substitute its two data slots once.

    Missing files raise OSError; missing or repeated slots raise ValueError.
    JSON serialization errors propagate. Inserted data is never reinterpreted
    as template syntax, even when it contains the same placeholder strings.
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if any(template.count(value) != 1 for value in _PLACEHOLDERS):
        raise ValueError("introduction template must contain each data slot exactly once")
    values = {
        _PLACEHOLDERS[0]: json.dumps(evidence, ensure_ascii=False),
        _PLACEHOLDERS[1]: json.dumps(highlights, ensure_ascii=False),
    }
    return _PLACEHOLDER_RE.sub(lambda match: values[match.group()], template).strip()
