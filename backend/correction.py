"""Constrained local-LLM correction contracts."""

import json
import re
from typing import Protocol

from .contracts import (
    CorrectionResult,
    ModelResponseError,
    RuleNormalizedText,
)

MAX_CHUNK_CHARACTERS = 12_000
MAX_CONTEXT_ITEMS = 4
MAX_CONTEXT_CHARACTERS = 2_000

_PLACEHOLDER_RE = re.compile(r"\[\[SODAM_PROTECTED_\d+\]\]")


class QwenRuntime(Protocol):
    def complete(self, prompt: str) -> str:
        ...


def _validate_inputs(text, context, runtime) -> None:
    """Validate text, context and runtime contract before any call."""
    if not isinstance(text, RuleNormalizedText):
        raise TypeError("text must be a RuleNormalizedText")
    raw_text = text.text
    if not isinstance(raw_text, str):
        raise ValueError("text.text must be str")
    if not (1 <= len(raw_text) <= MAX_CHUNK_CHARACTERS):
        raise ValueError(
            "text.text length must be between 1 and %d" % MAX_CHUNK_CHARACTERS
        )

    boundaries = text.sentence_boundaries
    if not isinstance(boundaries, tuple):
        raise ValueError("sentence_boundaries must be tuple[int, ...]")
    previous = 0
    for boundary in boundaries:
        if isinstance(boundary, bool) or not isinstance(boundary, int):
            raise ValueError("sentence_boundaries must contain only int")
        if boundary < 1 or boundary > len(raw_text):
            raise ValueError("sentence boundary out of range")
        if boundary <= previous:
            raise ValueError("sentence_boundaries must be strictly increasing")
        previous = boundary

    if not isinstance(context, tuple):
        raise TypeError("context must be a tuple[str, ...]")
    if len(context) > MAX_CONTEXT_ITEMS:
        raise ValueError("at most %d context items" % MAX_CONTEXT_ITEMS)
    for item in context:
        if not isinstance(item, str):
            raise TypeError("every context item must be str")
        if len(item) > MAX_CONTEXT_CHARACTERS:
            raise ValueError(
                "context item exceeds %d characters" % MAX_CONTEXT_CHARACTERS
            )

    if runtime is None:
        raise TypeError("runtime must expose a callable 'complete' method")
    if not callable(getattr(runtime, "complete", None)):
        raise TypeError("runtime.complete must be callable")


def _build_prompt(text: str, context: tuple[str, ...]) -> str:
    """Build the deterministic correction prompt (JSON-only contract)."""
    parts = [
        "You are a strict transcription-correction engine.",
        "Return exactly one JSON object and nothing else.",
        "Do not add markdown fences, comments, or any characters outside the JSON object.",
        "Rules:",
        "1. Only fix local errors inside the target text.",
        "2. Never change, drop, insert, or reorder any protected placeholder "
        "matching [[SODAM_PROTECTED_\\d+]], not even by a single character.",
        "3. List every correction in \"changes\" as {\"old\": \"...\", \"new\": \"...\"}.",
        "4. \"requires_review\" must be a boolean.",
        "JSON schema:",
        '{"corrected_text": "string", "changes": [{"old": "string", "new": "string"}], "requires_review": false}',
        "Context (numbered, original order):",
    ]
    for index, item in enumerate(context, start=1):
        parts.append("%d. %s" % (index, json.dumps(item, ensure_ascii=False)))
    parts.append("Target text:")
    parts.append(json.dumps(text, ensure_ascii=False))
    return "\n".join(parts)


def _parse_response(
    raw, input_text: str, expected_placeholders: tuple[str, ...]
) -> CorrectionResult:
    """Parse and strictly validate one runtime response into CorrectionResult."""
    try:
        if not isinstance(raw, str):
            raise ModelResponseError("runtime response must be a str")
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ModelResponseError("runtime response is not a single JSON object") from exc
    if not isinstance(payload, dict):
        raise ModelResponseError("runtime response must be a single JSON object")
    if set(payload) != {"corrected_text", "changes", "requires_review"}:
        raise ModelResponseError(
            "response must contain exactly corrected_text, changes, requires_review"
        )

    corrected = payload["corrected_text"]
    if not isinstance(corrected, str):
        raise ModelResponseError("corrected_text must be str")
    if not corrected:
        raise ModelResponseError("corrected_text must not be empty")
    if len(corrected) > MAX_CHUNK_CHARACTERS:
        raise ModelResponseError("corrected_text exceeds MAX_CHUNK_CHARACTERS")

    raw_changes = payload["changes"]
    if not isinstance(raw_changes, list):
        raise ModelResponseError("changes must be a list")
    changes: tuple[dict[str, str], ...] = ()
    for item in raw_changes:
        if not isinstance(item, dict) or set(item) != {"old", "new"}:
            raise ModelResponseError("each change must be a dict with exactly old and new")
        old = item["old"]
        new = item["new"]
        if not isinstance(old, str) or not isinstance(new, str) or not old or not new:
            raise ModelResponseError("change old/new must be non-empty strings")
        if old == new:
            raise ModelResponseError("change old and new must differ")
        changes = changes + ({"old": old, "new": new},)

    review = payload["requires_review"]
    if type(review) is not bool:
        raise ModelResponseError("requires_review must be a bool")

    actual_placeholders = tuple(_PLACEHOLDER_RE.findall(corrected))
    if actual_placeholders != expected_placeholders:
        raise ModelResponseError("protected placeholders were changed or lost")

    if not changes and corrected == input_text and review is True:
        raise ModelResponseError("no-op response must not set requires_review to True")

    return CorrectionResult(
        corrected_text=corrected,
        changes=changes,
        requires_review=review,
    )


def correct_chunk(
    text: RuleNormalizedText,
    context: tuple[str, ...],
    runtime: QwenRuntime,
) -> CorrectionResult:
    """Send a bounded chunk to the injected runtime and validate its JSON reply.

    The runtime is called exactly once. No real runtime, environment lookup,
    network access, or file I/O is performed by this module.
    """
    _validate_inputs(text, context, runtime)
    expected_placeholders = tuple(_PLACEHOLDER_RE.findall(text.text))
    prompt = _build_prompt(text.text, context)
    try:
        raw_response = runtime.complete(prompt)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        raise ModelResponseError("runtime.complete raised an error") from exc
    return _parse_response(raw_response, text.text, expected_placeholders)
