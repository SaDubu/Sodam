"""Shared, lossless normalization for structured model responses."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ModelResponseError


@dataclass(frozen=True)
class NormalizedResponse:
    """A model response after serialization-only normalization."""

    text: str
    was_fenced: bool
    was_trimmed: bool


def normalize_json_response(raw: object) -> NormalizedResponse:
    """Remove outer whitespace or one exact JSON Markdown fence.

    No JSON substring extraction or semantic repair is performed. Explanatory
    text and unsupported fences remain invalid so the feature validator can
    reject them instead of silently selecting an ambiguous JSON fragment.
    """
    if not isinstance(raw, str) or not raw.strip():
        error = ModelResponseError("structured model response is empty")
        error.diagnostic_code = "response_empty"
        error.response_empty = True
        raise error

    candidate = raw.strip()
    was_trimmed = candidate != raw
    lines = candidate.splitlines()
    if lines and lines[0] in {"```json", "```JSON"}:
        if len(lines) < 2 or lines[-1] != "```":
            error = ModelResponseError("JSON fenced response is incomplete")
            error.diagnostic_code = "json_parse_invalid"
            error.response_empty = False
            raise error
        body = "\n".join(lines[1:-1]).strip()
        if not body:
            error = ModelResponseError("structured model response is empty")
            error.diagnostic_code = "response_empty"
            error.response_empty = True
            raise error
        return NormalizedResponse(body, True, was_trimmed)

    if candidate.startswith("```") or candidate.endswith("```"):
        error = ModelResponseError("unsupported Markdown fence in structured response")
        error.diagnostic_code = "json_parse_invalid"
        error.response_empty = False
        raise error

    return NormalizedResponse(candidate, False, was_trimmed)
