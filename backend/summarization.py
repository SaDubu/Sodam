"""Evidence-linked, maximum-two-sentence transcript summarization."""

import json
import re
from dataclasses import replace

from .contracts import (
    EmptyTranscriptError,
    ModelResponseError,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
    Summary,
    SummaryOutcome,
    Transcript,
)
from .correction import QwenRuntime
from .model_response import normalize_json_response


MAX_SEGMENTS_PER_BATCH = 8
MAX_SUMMARY_CHARACTERS = 1_000
MAX_REDUCE_FAN_IN = 8
MAX_REDUCE_PROMPT_CHARACTERS = 12_000
MAX_ROOT_SUMMARIES = 8
MAX_SUMMARY_ATTEMPTS = 3
SUMMARY_FAILURE_CATEGORIES = frozenset(
    {"batch_failed", "reduce_failed", "final_failed", "retry_exhausted"}
)
SUMMARY_DIAGNOSTIC_CODES = frozenset(
    {
        "response_empty",
        "markdown_fenced_json",
        "json_parse_invalid",
        "schema_invalid",
        "evidence_invalid",
        "summary_constraint_invalid",
        "runtime_unavailable",
    }
)
_FORMAT_REPAIR_INSTRUCTION = (
    "Your previous response did not satisfy the output format. "
    "Return raw JSON only. Do not use Markdown fences. "
    "Do not add commentary before or after the JSON object."
)

_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")

def _normalize_summary_response(raw: object) -> tuple[str, str]:
    """Keep the legacy tuple helper while using the common normalizer."""
    normalized = normalize_json_response(raw)
    return normalized.text, "markdown_fenced_json" if normalized.was_fenced else "unchanged"


def _validate_inputs(transcript: Transcript, runtime: QwenRuntime) -> None:
    """Validate the immutable transcript and injected runtime contracts."""
    if not isinstance(transcript, Transcript):
        raise TypeError("transcript must be a Transcript")
    if not isinstance(transcript.segments, tuple):
        raise ValueError("transcript.segments must be a tuple")
    if not isinstance(transcript.final_text, str):
        raise ValueError("transcript.final_text must be a str")
    if not transcript.segments or not transcript.final_text.strip():
        raise EmptyTranscriptError("transcript must not be empty")
    if not callable(getattr(runtime, "complete", None)):
        raise TypeError("runtime.complete must be callable")

    segment_ids: set[str] = set()
    expected_text_parts: list[str] = []
    for segment in transcript.segments:
        if not isinstance(segment, RawSegment):
            raise ValueError("transcript.segments must contain RawSegment values")
        if (
            not isinstance(segment.segment_id, str)
            or not segment.segment_id
            or segment.segment_id != segment.segment_id.strip()
            or segment.segment_id in segment_ids
        ):
            raise ValueError("segment_id values must be unique, non-blank strings")
        if not isinstance(segment.raw_text, str) or not segment.raw_text.strip():
            raise ValueError("segment raw_text must be a non-blank str")
        segment_ids.add(segment.segment_id)
        expected_text_parts.append(segment.raw_text)
    if transcript.final_text != "\n".join(expected_text_parts):
        raise ValueError("transcript.final_text must match its segment text")


def _sentence_count(text: str) -> int:
    """Count non-empty sentences using the specified terminal punctuation."""
    return sum(1 for part in _SENTENCE_RE.findall(text) if part.strip())


def _parse_summary_response(raw: object, allowed_ids: set[str]) -> Summary:
    """Validate one strict JSON summary response against its allowed evidence."""
    clean_text = normalize_json_response(raw).text
    try:
        payload = json.loads(clean_text)
    except (TypeError, ValueError) as exc:
        error = ModelResponseError("runtime response is not valid JSON")
        error.diagnostic_code = "json_parse_invalid"
        error.response_empty = False
        error.__cause__ = exc
        raise error

    if not isinstance(payload, dict) or set(payload) != {"text", "evidence_segment_ids"}:
        error = ModelResponseError("response schema is invalid")
        error.diagnostic_code = "schema_invalid"
        error.response_empty = False
        raise error

    text = payload["text"]
    if (
        not isinstance(text, str)
        or not text
        or text != text.strip()
        or len(text) > MAX_SUMMARY_CHARACTERS
    ):
        error = ModelResponseError("summary text violates constraints")
        error.diagnostic_code = "summary_constraint_invalid"
        error.response_empty = False
        raise error
    if not 1 <= _sentence_count(text) <= 2:
        error = ModelResponseError("summary text violates sentence constraints")
        error.diagnostic_code = "summary_constraint_invalid"
        error.response_empty = False
        raise error

    evidence = payload["evidence_segment_ids"]
    if not isinstance(evidence, list) or not evidence:
        error = ModelResponseError("evidence list is invalid")
        error.diagnostic_code = "evidence_invalid"
        error.response_empty = False
        raise error
    if any(
        not isinstance(segment_id, str)
        or not segment_id
        or segment_id != segment_id.strip()
        for segment_id in evidence
    ):
        error = ModelResponseError("evidence IDs are invalid")
        error.diagnostic_code = "evidence_invalid"
        error.response_empty = False
        raise error
    if len(set(evidence)) != len(evidence):
        error = ModelResponseError("evidence IDs are duplicated")
        error.diagnostic_code = "evidence_invalid"
        error.response_empty = False
        raise error
    if any(segment_id not in allowed_ids for segment_id in evidence):
        error = ModelResponseError("evidence ID is outside the supplied transcript")
        error.diagnostic_code = "evidence_invalid"
        error.response_empty = False
        raise error
    return Summary(text=text, evidence_segment_ids=tuple(evidence))


def _call_runtime(runtime: QwenRuntime, prompt: str, allowed_ids: set[str]) -> Summary:
    """Call the injected runtime exactly once and validate its response."""
    try:
        response = runtime.complete(prompt)
    except (KeyboardInterrupt, SystemExit):
        raise
    except ModelResponseError:
        raise
    except Exception as exc:
        error = ModelResponseError("runtime.complete raised an error")
        error.diagnostic_code = "runtime_unavailable"
        error.response_empty = False
        error.__cause__ = exc
        raise error
    return _parse_summary_response(response, allowed_ids)


def _summary_failure_category(error: BaseException, stage: str) -> str:
    """Map one failed summary call to a stable, non-sensitive category."""
    if stage not in {"batch", "reduce", "final"}:
        raise ValueError("stage must be batch, reduce, or final")
    if stage == "batch":
        return "batch_failed"
    if stage == "reduce":
        return "reduce_failed"
    return "final_failed"


def _tag_summary_error(error: BaseException, category: str, attempts: int) -> ModelResponseError:
    """Return a safe summary error carrying only allowlisted retry metadata."""
    if category not in SUMMARY_FAILURE_CATEGORIES:
        raise ValueError("unsupported summary failure category")
    safe = ModelResponseError("summary runtime failed after bounded retries")
    safe.__cause__ = error
    safe.summary_failure_category = category
    safe.attempt_count = attempts
    diagnostic = getattr(error, "diagnostic_code", None)
    safe.diagnostic_code = (
        diagnostic
        if isinstance(diagnostic, str) and diagnostic in SUMMARY_DIAGNOSTIC_CODES
        else "runtime_unavailable"
    )
    safe.response_empty = bool(getattr(error, "response_empty", False))
    return safe


def _call_runtime_with_retry(
    runtime: QwenRuntime,
    prompt: str,
    allowed_ids: set[str],
    stage: str,
    max_attempts: int = MAX_SUMMARY_ATTEMPTS,
) -> tuple[Summary, int]:
    """Call and validate a summary runtime response with bounded retries."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-blank string")
    if not isinstance(allowed_ids, set) or not allowed_ids:
        raise ValueError("allowed_ids must be a non-empty set")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise TypeError("max_attempts must be an int")
    if not 1 <= max_attempts <= MAX_SUMMARY_ATTEMPTS:
        raise ValueError("max_attempts is outside the bounded retry limit")
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            attempt_prompt = (
                prompt
                if attempt == 1
                else prompt + "\n\n" + _FORMAT_REPAIR_INSTRUCTION
            )
            return _call_runtime(runtime, attempt_prompt, allowed_ids), attempt
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise _tag_summary_error(
        last_error,
        _summary_failure_category(last_error, stage),
        max_attempts,
    )


def _build_batch_prompt(batch: tuple[RawSegment, ...]) -> str:
    """Build a deterministic JSON-only prompt from one bounded batch."""
    records = [
        {"segment_id": segment.segment_id, "raw_text": segment.raw_text}
        for segment in batch
    ]
    return "\n".join(
        (
            "Return exactly one JSON object and nothing else.",
            "Do not add facts outside the supplied segments.",
            "Use only supplied segment IDs as evidence.",
            "The text field must contain exactly one or two complete sentences.",
            'Schema: {"text":"summary", "evidence_segment_ids":["segment-id"]}',
            "Segments:",
            json.dumps(records, ensure_ascii=False),
        )
    )


def _validate_reviewed_inputs(
    transcript: ReviewedTranscript,
    runtime: QwenRuntime,
) -> None:
    """Validate reviewed text while retaining source segment IDs as evidence."""
    if not isinstance(transcript, ReviewedTranscript):
        raise TypeError("transcript must be a ReviewedTranscript")
    if not isinstance(transcript.segments, tuple):
        raise ValueError("transcript.segments must be a tuple")
    if not isinstance(transcript.final_text, str):
        raise ValueError("transcript.final_text must be a str")
    if not transcript.segments or not transcript.final_text.strip():
        raise EmptyTranscriptError("transcript must not be empty")
    if not callable(getattr(runtime, "complete", None)):
        raise TypeError("runtime.complete must be callable")

    segment_ids: set[str] = set()
    expected_text_parts: list[str] = []
    for segment in transcript.segments:
        if not isinstance(segment, ReviewedSegment):
            raise ValueError("transcript.segments must contain ReviewedSegment values")
        source = segment.source
        if not isinstance(source, RawSegment):
            raise ValueError("reviewed segment source must be a RawSegment")
        if (
            not isinstance(source.segment_id, str)
            or not source.segment_id
            or source.segment_id != source.segment_id.strip()
            or source.segment_id in segment_ids
        ):
            raise ValueError("source segment IDs must be unique, non-blank strings")
        if not isinstance(source.raw_text, str) or not source.raw_text.strip():
            raise ValueError("source segment raw_text must be a non-blank str")
        if not isinstance(segment.final_text, str) or not segment.final_text.strip():
            raise ValueError("reviewed segment final_text must be a non-blank str")
        segment_ids.add(source.segment_id)
        expected_text_parts.append(segment.final_text)
    if transcript.final_text != "\n".join(expected_text_parts):
        raise ValueError("transcript.final_text must match its reviewed segment text")


def _build_reviewed_batch_prompt(batch: tuple[ReviewedSegment, ...]) -> str:
    """Build a deterministic JSON-only prompt from approved segment text."""
    records = [
        {"segment_id": segment.source.segment_id, "final_text": segment.final_text}
        for segment in batch
    ]
    return "\n".join(
        (
            "Return exactly one JSON object and nothing else.",
            "Do not add facts outside the supplied segments.",
            "Use only supplied segment IDs as evidence.",
            "The text field must contain exactly one or two complete sentences.",
            'Schema: {"text":"summary", "evidence_segment_ids":["segment-id"]}',
            "Reviewed segments:",
            json.dumps(records, ensure_ascii=False),
        )
    )


def _build_final_prompt(batch_summaries: tuple[Summary, ...]) -> str:
    """Build the final synthesis prompt from validated intermediate summaries."""
    records = [
        {
            "text": summary.text,
            "evidence_segment_ids": list(summary.evidence_segment_ids),
        }
        for summary in batch_summaries
    ]
    return "\n".join(
        (
            "Return exactly one JSON object and nothing else.",
            "Write a concise, factual Korean summary of the video's central subject and important content.",
            "Use the supplied intermediate summaries as a whole rather than selecting only one batch.",
            "Do not make one early fact, such as an award or ranking, the main theme unless every summary is about it.",
            "Do not add facts outside the supplied intermediate summaries.",
            "Use only supplied segment IDs as evidence.",
            "The text field must contain exactly one or two complete sentences.",
            'Schema: {"text":"summary", "evidence_segment_ids":["segment-id"]}',
            "Validated intermediate summaries:",
            json.dumps(records, ensure_ascii=False),
        )
    )


def _build_reduce_prompt(group: tuple[Summary, ...]) -> str:
    """Build a deterministic prompt for reducing validated summaries."""
    if not group:
        raise ValueError("summary group must not be empty")
    records = [
        {
            "text": summary.text,
            "evidence_segment_ids": list(summary.evidence_segment_ids),
        }
        for summary in group
    ]
    return "\n".join(
        (
            "Return exactly one JSON object and nothing else.",
            "Write a concise, factual Korean summary using every supplied summary.",
            "Do not add facts outside the supplied summaries.",
            "Use only supplied segment IDs as evidence.",
            "The text field must contain exactly one or two complete sentences.",
            '{"text":"summary", "evidence_segment_ids":["segment-id"]}',
            "Validated summaries to reduce:",
            json.dumps(records, ensure_ascii=False),
        )
    )


def _partition_summary_groups(
    summaries: tuple[Summary, ...],
    max_chars: int = MAX_REDUCE_PROMPT_CHARACTERS,
    fan_in: int = MAX_REDUCE_FAN_IN,
) -> tuple[tuple[Summary, ...], ...]:
    """Partition summaries deterministically under fan-in and prompt limits."""
    if not isinstance(summaries, tuple):
        raise TypeError("summaries must be a tuple")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if isinstance(fan_in, bool) or not isinstance(fan_in, int) or fan_in <= 0:
        raise ValueError("fan_in must be a positive integer")

    groups: list[tuple[Summary, ...]] = []
    current: list[Summary] = []
    for summary in summaries:
        if not isinstance(summary, Summary):
            raise ValueError("summaries must contain Summary values")
        candidate = tuple(current + [summary])
        if current and (
            len(current) >= fan_in
            or len(_build_reduce_prompt(candidate)) > max_chars
        ):
            groups.append(tuple(current))
            current = [summary]
            candidate = (summary,)
        if len(_build_reduce_prompt(candidate)) > max_chars:
            raise ModelResponseError("summary reduce prompt exceeds character limit")
        current = list(candidate)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _reduce_summary_group(
    group: tuple[Summary, ...],
    runtime: QwenRuntime,
    allowed_ids: set[str],
) -> Summary:
    """Reduce one bounded Summary group while preserving evidence boundaries."""
    if not group:
        raise ValueError("summary group must not be empty")
    group_ids = {
        segment_id
        for summary in group
        for segment_id in summary.evidence_segment_ids
    }
    if not group_ids.issubset(allowed_ids):
        raise ValueError("allowed_ids must contain group evidence IDs")
    prompt = _build_reduce_prompt(group)
    if len(prompt) > MAX_REDUCE_PROMPT_CHARACTERS:
        raise ModelResponseError("summary reduce prompt exceeds character limit")
    return _call_runtime(runtime, prompt, group_ids)


def _reduce_summary_group_with_retry(
    group: tuple[Summary, ...],
    runtime: QwenRuntime,
    allowed_ids: set[str],
) -> tuple[Summary, int]:
    """Retry one validated reduce group without changing its evidence scope."""
    if not group:
        raise ValueError("summary group must not be empty")
    group_ids = {
        segment_id
        for summary in group
        for segment_id in summary.evidence_segment_ids
    }
    prompt = _build_reduce_prompt(group)
    return _call_runtime_with_retry(runtime, prompt, group_ids, "reduce")


def _select_fallback_summary(
    summaries: tuple[Summary, ...],
    all_ids: set[str],
) -> Summary:
    """Select the first validated candidate without inventing or merging text."""
    if not summaries:
        raise ModelResponseError("no validated summary is available for fallback")
    for summary in summaries:
        if not isinstance(summary, Summary):
            raise ValueError("fallback candidates must contain Summary values")
        if not set(summary.evidence_segment_ids).issubset(all_ids):
            raise ModelResponseError("fallback evidence is outside the transcript")
    return summaries[0]


def _hierarchical_summarize(
    summaries: tuple[Summary, ...],
    runtime: QwenRuntime,
    all_ids: set[str],
) -> SummaryOutcome:
    """Reduce intermediate summaries until a bounded final synthesis is possible."""
    if not summaries:
        raise ValueError("summaries must not be empty")
    current = tuple(summaries)
    attempt_count = 0
    while len(current) > MAX_ROOT_SUMMARIES:
        groups = _partition_summary_groups(current)
        reduced: list[Summary] = []
        for group in groups:
            try:
                summary, attempts = _reduce_summary_group_with_retry(
                    group, runtime, all_ids
                )
            except ModelResponseError as exc:
                fallback = _select_fallback_summary(current, all_ids)
                category = getattr(exc, "summary_failure_category", "reduce_failed")
                return SummaryOutcome(
                    fallback,
                    "fallback",
                    category if category in SUMMARY_FAILURE_CATEGORIES else "reduce_failed",
                    attempt_count + int(getattr(exc, "attempt_count", MAX_SUMMARY_ATTEMPTS)),
                    "reduce",
                )
            reduced.append(summary)
            attempt_count += attempts
        current = tuple(reduced)
    if len(current) == 1:
        return SummaryOutcome(current[0], "success", None, attempt_count)
    final_prompt = _build_final_prompt(current)
    if len(final_prompt) > MAX_REDUCE_PROMPT_CHARACTERS:
        raise ModelResponseError("final summary prompt exceeds character limit")
    try:
        final, attempts = _call_runtime_with_retry(
            runtime, final_prompt, all_ids, "final"
        )
    except ModelResponseError as exc:
        fallback = _select_fallback_summary(current, all_ids)
        category = getattr(exc, "summary_failure_category", "final_failed")
        return SummaryOutcome(
            fallback,
            "fallback",
            category if category in SUMMARY_FAILURE_CATEGORIES else "final_failed",
            attempt_count + int(getattr(exc, "attempt_count", MAX_SUMMARY_ATTEMPTS)),
            "reduce",
        )
    return SummaryOutcome(final, "success", None, attempt_count + attempts)


def _fallback_error(outcome: SummaryOutcome) -> ModelResponseError:
    """Convert a review-only outcome to the legacy exception API safely."""
    error = ModelResponseError("summary generation returned a review-only fallback")
    error.summary_failure_category = outcome.failure_category or "retry_exhausted"
    error.attempt_count = outcome.attempt_count
    return error


def summarize_transcript_outcome(
    transcript: Transcript,
    runtime: QwenRuntime,
) -> SummaryOutcome:
    """Return a success or review-only fallback outcome for a raw transcript."""
    _validate_inputs(transcript, runtime)
    all_ids = {segment.segment_id for segment in transcript.segments}
    batch_summaries: list[Summary] = []
    attempt_count = 0
    for index in range(0, len(transcript.segments), MAX_SEGMENTS_PER_BATCH):
        batch = transcript.segments[index : index + MAX_SEGMENTS_PER_BATCH]
        batch_ids = {segment.segment_id for segment in batch}
        try:
            summary, attempts = _call_runtime_with_retry(
                runtime, _build_batch_prompt(batch), batch_ids, "batch"
            )
        except ModelResponseError as exc:
            if not batch_summaries:
                raise
            fallback = _select_fallback_summary(tuple(batch_summaries), all_ids)
            error_category = getattr(exc, "summary_failure_category", "batch_failed")
            return SummaryOutcome(
                fallback,
                "fallback",
                error_category if error_category in SUMMARY_FAILURE_CATEGORIES else "batch_failed",
                attempt_count + int(getattr(exc, "attempt_count", MAX_SUMMARY_ATTEMPTS)),
                "batch",
            )
        batch_summaries.append(summary)
        attempt_count += attempts

    if len(batch_summaries) == 1:
        return SummaryOutcome(batch_summaries[0], "success", None, attempt_count)
    outcome = _hierarchical_summarize(tuple(batch_summaries), runtime, all_ids)
    return replace(outcome, attempt_count=attempt_count + outcome.attempt_count)


def summarize_reviewed_transcript_outcome(
    transcript: ReviewedTranscript,
    runtime: QwenRuntime,
) -> SummaryOutcome:
    """Return a success or fallback outcome for approved reviewed text."""
    _validate_reviewed_inputs(transcript, runtime)
    all_ids = {segment.source.segment_id for segment in transcript.segments}
    batch_summaries: list[Summary] = []
    attempt_count = 0
    for index in range(0, len(transcript.segments), MAX_SEGMENTS_PER_BATCH):
        batch = transcript.segments[index : index + MAX_SEGMENTS_PER_BATCH]
        batch_ids = {segment.source.segment_id for segment in batch}
        try:
            summary, attempts = _call_runtime_with_retry(
                runtime, _build_reviewed_batch_prompt(batch), batch_ids, "batch"
            )
        except ModelResponseError as exc:
            if not batch_summaries:
                raise
            fallback = _select_fallback_summary(tuple(batch_summaries), all_ids)
            error_category = getattr(exc, "summary_failure_category", "batch_failed")
            return SummaryOutcome(
                fallback,
                "fallback",
                error_category if error_category in SUMMARY_FAILURE_CATEGORIES else "batch_failed",
                attempt_count + int(getattr(exc, "attempt_count", MAX_SUMMARY_ATTEMPTS)),
                "batch",
            )
        batch_summaries.append(summary)
        attempt_count += attempts

    if len(batch_summaries) == 1:
        return SummaryOutcome(batch_summaries[0], "success", None, attempt_count)
    outcome = _hierarchical_summarize(tuple(batch_summaries), runtime, all_ids)
    return replace(outcome, attempt_count=attempt_count + outcome.attempt_count)


def summarize_transcript(
    transcript: Transcript,
    runtime: QwenRuntime,
) -> Summary:
    """Return an evidence-linked summary from bounded transcript batches."""
    outcome = summarize_transcript_outcome(transcript, runtime)
    if outcome.status == "fallback":
        raise _fallback_error(outcome)
    return outcome.summary


def summarize_reviewed_transcript(
    transcript: ReviewedTranscript,
    runtime: QwenRuntime,
) -> Summary:
    """Return an evidence-linked summary of approved, restored segment text."""
    outcome = summarize_reviewed_transcript_outcome(transcript, runtime)
    if outcome.status == "fallback":
        raise _fallback_error(outcome)
    return outcome.summary
