"""Constrained local-LLM correction contracts."""

import json
import re
from typing import Protocol

from .contracts import (
    CorrectionAttempt,
    CorrectionOutcome,
    CorrectionResult,
    EditablePart,
    EditableTextPlan,
    EditProposal,
    ModelResponseError,
    ProtectionError,
    RuleNormalizedText,
)
from .protection import reassemble_locked_parts

MAX_CHUNK_CHARACTERS = 12_000
MAX_CONTEXT_ITEMS = 4
MAX_CONTEXT_CHARACTERS = 2_000
MAX_CORRECTION_ATTEMPTS = 3

_PLACEHOLDER_RE = re.compile(r"\[\[SODAM_PROTECTED_\d+\]\]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


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
    no_op_change = False
    for item in raw_changes:
        if not isinstance(item, dict) or set(item) != {"old", "new"}:
            raise ModelResponseError("each change must be a dict with exactly old and new")
        old = item["old"]
        new = item["new"]
        if not isinstance(old, str) or not isinstance(new, str) or not old or not new:
            raise ModelResponseError("change old/new must be non-empty strings")
        if old == new:
            no_op_change = True
            continue
        changes = changes + ({"old": old, "new": new},)

    review = payload["requires_review"]
    if type(review) is not bool:
        raise ModelResponseError("requires_review must be a bool")

    actual_placeholders = tuple(_PLACEHOLDER_RE.findall(corrected))
    if actual_placeholders != expected_placeholders:
        raise ModelResponseError("protected placeholders were changed or lost")

    if no_op_change:
        if not changes and corrected != input_text:
            raise ModelResponseError(
                "corrected_text changed but changes contain no actual correction"
            )

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
    def complete(value: str):
        try:
            return runtime.complete(value)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise ModelResponseError("runtime.complete raised an error") from exc

    return _parse_response(complete(prompt), text.text, expected_placeholders)


def _validate_plan_group(
    plan_group: tuple[EditableTextPlan, ...],
) -> tuple[set[str], set[str]]:
    """Validate plans and return their editable and locked IDs."""
    if not isinstance(plan_group, tuple):
        raise TypeError("plan_group must be a tuple")
    if not plan_group:
        raise ValueError("plan_group must not be empty")
    editable_ids: set[str] = set()
    locked_ids: set[str] = set()
    for plan in plan_group:
        if not isinstance(plan, EditableTextPlan):
            raise TypeError("plan_group must contain EditableTextPlan values")
        reassemble_locked_parts(plan)
        for part in plan.parts:
            target = editable_ids if isinstance(part, EditablePart) else locked_ids
            if part.part_id in editable_ids or part.part_id in locked_ids:
                raise ProtectionError("part IDs must be unique across plan_group")
            target.add(part.part_id)
    return editable_ids, locked_ids


def _validate_context(context: tuple[str, ...]) -> None:
    """Apply the existing bounded context contract to a correction group."""
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


def _build_edit_prompt(
    plan_group: tuple[EditableTextPlan, ...],
    context: tuple[str, ...],
    repair_reason: str | None,
) -> str:
    """Build a deterministic prompt that asks for editable IDs only."""
    parts = [
        "You are a strict transcription-edit proposal engine.",
        "Return exactly one JSON object and nothing else.",
        "The only top-level keys are edits and requires_review.",
        "Each edit must contain only editable_id and replacement.",
        "Never return a locked part ID, a placeholder, markdown, or commentary.",
        "Locked part text is source-grounded context and must never be edited.",
        "Use an empty replacement only when deleting an editable span is necessary.",
        'JSON schema: {"edits":[{"editable_id":"string","replacement":"string"}],'
        '"requires_review":false}',
    ]
    if repair_reason is not None:
        parts.append("Repair reason category: " + repair_reason)
    parts.append("Context (numbered, original order):")
    for index, item in enumerate(context, start=1):
        parts.append("%d. %s" % (index, json.dumps(item, ensure_ascii=False)))
    parts.append("Plans:")
    for plan in plan_group:
        serialized_parts = []
        for part in plan.parts:
            serialized_parts.append(
                {
                    "part_id": part.part_id,
                    "kind": "editable" if isinstance(part, EditablePart) else "locked",
                    "text": part.text,
                }
            )
        parts.append(
            json.dumps(
                {"segment_id": plan.segment_id, "parts": serialized_parts},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return "\n".join(parts)


def validate_edit_proposal(
    plan_group: tuple[EditableTextPlan, ...],
    raw: str,
) -> tuple[tuple[EditProposal, ...], bool]:
    """Parse and validate an editable-only JSON proposal."""
    editable_ids, _locked_ids = _validate_plan_group(plan_group)
    if not isinstance(raw, str):
        raise ModelResponseError("edit proposal response must be a str")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ModelResponseError("edit proposal response is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"edits", "requires_review"}:
        raise ModelResponseError("edit proposal must contain exactly edits and requires_review")
    raw_edits = payload["edits"]
    if not isinstance(raw_edits, list):
        raise ModelResponseError("edits must be a list")
    proposals: list[EditProposal] = []
    seen: set[str] = set()
    for item in raw_edits:
        if not isinstance(item, dict) or set(item) != {"editable_id", "replacement"}:
            raise ModelResponseError("each edit must contain editable_id and replacement")
        editable_id = item["editable_id"]
        replacement = item["replacement"]
        if not isinstance(editable_id, str) or not isinstance(replacement, str):
            raise ModelResponseError("editable_id and replacement must be strings")
        if editable_id not in editable_ids:
            raise ModelResponseError("edit references an unknown or locked part")
        if editable_id in seen:
            raise ModelResponseError("each editable_id may appear only once")
        if len(replacement) > MAX_CHUNK_CHARACTERS:
            raise ModelResponseError("replacement exceeds MAX_CHUNK_CHARACTERS")
        if _CONTROL_RE.search(replacement) or _PLACEHOLDER_RE.search(replacement):
            raise ModelResponseError("replacement contains forbidden control or placeholder text")
        seen.add(editable_id)
        proposals.append(EditProposal(editable_id, replacement))
    requires_review = payload["requires_review"]
    if type(requires_review) is not bool:
        raise ModelResponseError("requires_review must be a bool")
    return tuple(proposals), requires_review


def propose_edits(
    plan_group: tuple[EditableTextPlan, ...],
    context: tuple[str, ...],
    runtime: QwenRuntime,
    repair_reason: str | None = None,
) -> tuple[tuple[EditProposal, ...], bool]:
    """Call the injected runtime once and return a validated edit proposal."""
    _validate_plan_group(plan_group)
    _validate_context(context)
    if runtime is None or not callable(getattr(runtime, "complete", None)):
        raise TypeError("runtime.complete must be callable")
    if repair_reason is not None and (
        not isinstance(repair_reason, str)
        or not repair_reason
        or len(repair_reason) > 64
    ):
        raise TypeError("repair_reason must be a short non-blank str")
    prompt = _build_edit_prompt(plan_group, context, repair_reason)
    try:
        raw = runtime.complete(prompt)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        error = ModelResponseError("runtime.complete raised an error")
        error.__cause__ = exc
        raise error from exc
    return validate_edit_proposal(plan_group, raw)


def _retry_reason(exc: Exception) -> str:
    """Reduce an exception to a safe, non-sensitive retry category."""
    if isinstance(exc, ModelResponseError) and isinstance(exc.__cause__, TimeoutError):
        return "timeout"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ModelResponseError):
        return "invalid_response"
    return "runtime_error"


def correct_with_retry(
    plan_group: tuple[EditableTextPlan, ...],
    context: tuple[str, ...],
    runtime: QwenRuntime,
    max_attempts: int = 3,
) -> CorrectionOutcome:
    """Return a safe correction outcome after bounded retries or identity fallback."""
    _validate_plan_group(plan_group)
    _validate_context(context)
    if runtime is None or not callable(getattr(runtime, "complete", None)):
        raise TypeError("runtime.complete must be callable")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise TypeError("max_attempts must be an int")
    if not 1 <= max_attempts <= MAX_CORRECTION_ATTEMPTS:
        raise ValueError(
            "max_attempts must be between 1 and %d" % MAX_CORRECTION_ATTEMPTS
        )

    attempts: list[CorrectionAttempt] = []
    last_reason = "invalid_response"
    for attempt_number in range(1, max_attempts + 1):
        try:
            proposals, requires_review = propose_edits(
                plan_group,
                context,
                runtime,
                last_reason if attempt_number > 1 else None,
            )
            replacement_map = {proposal.editable_id: proposal.replacement for proposal in proposals}
            reassembled: list[str] = []
            for plan in plan_group:
                plan_editable_ids = {
                    part.part_id
                    for part in plan.parts
                    if isinstance(part, EditablePart)
                }
                plan_replacements = {
                    part_id: replacement_map[part_id]
                    for part_id in plan_editable_ids
                    if part_id in replacement_map
                }
                reassembled.append(reassemble_locked_parts(plan, plan_replacements))
            text = "\n".join(reassembled)
            attempts.append(CorrectionAttempt(attempt_number, "accepted"))
            return CorrectionOutcome(
                text=text,
                edits=proposals,
                attempts=tuple(attempts),
                identity_applied=False,
                review_reason="model_requested_review" if requires_review else None,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except ProtectionError:
            raise
        except Exception as exc:
            last_reason = _retry_reason(exc)
            if attempt_number < max_attempts:
                attempts.append(CorrectionAttempt(attempt_number, "retrying", last_reason))
                continue
            attempts.append(
                CorrectionAttempt(attempt_number, "identity_applied", last_reason)
            )
            return CorrectionOutcome(
                text="\n".join(plan.original_text for plan in plan_group),
                edits=(),
                attempts=tuple(attempts),
                identity_applied=True,
                review_reason="correction_unapplied:" + last_reason,
            )
    raise AssertionError("bounded correction loop did not return")
