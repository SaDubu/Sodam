"""Evidence-linked, maximum-two-sentence transcript summarization."""

import json
import re

from .contracts import (
    EmptyTranscriptError,
    ModelResponseError,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
    Summary,
    Transcript,
)
from .correction import QwenRuntime


MAX_SEGMENTS_PER_BATCH = 8
MAX_SUMMARY_CHARACTERS = 1_000

_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")


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
    if not isinstance(raw, str):
        raise ModelResponseError("runtime response must be a str")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ModelResponseError("runtime response is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"text", "evidence_segment_ids"}:
        raise ModelResponseError("response must contain exactly text and evidence_segment_ids")

    text = payload["text"]
    if (
        not isinstance(text, str)
        or not text
        or text != text.strip()
        or len(text) > MAX_SUMMARY_CHARACTERS
    ):
        raise ModelResponseError("summary text must be trimmed and within bounds")
    if not 1 <= _sentence_count(text) <= 2:
        raise ModelResponseError("summary text must contain one or two sentences")

    evidence = payload["evidence_segment_ids"]
    if not isinstance(evidence, list) or not evidence:
        raise ModelResponseError("evidence_segment_ids must be a non-empty list")
    if any(
        not isinstance(segment_id, str)
        or not segment_id
        or segment_id != segment_id.strip()
        for segment_id in evidence
    ):
        raise ModelResponseError("evidence IDs must be non-blank strings")
    if len(set(evidence)) != len(evidence):
        raise ModelResponseError("evidence IDs must not be duplicated")
    if any(segment_id not in allowed_ids for segment_id in evidence):
        raise ModelResponseError("evidence IDs must belong to the supplied transcript")
    return Summary(text=text, evidence_segment_ids=tuple(evidence))


def _call_runtime(runtime: QwenRuntime, prompt: str, allowed_ids: set[str]) -> Summary:
    """Call the injected runtime exactly once and validate its response."""
    try:
        response = runtime.complete(prompt)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        raise ModelResponseError("runtime.complete raised an error") from exc
    return _parse_summary_response(response, allowed_ids)


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
            "Do not add facts outside the supplied intermediate summaries.",
            "Use only supplied segment IDs as evidence.",
            'Schema: {"text":"summary", "evidence_segment_ids":["segment-id"]}',
            "Validated intermediate summaries:",
            json.dumps(records, ensure_ascii=False),
        )
    )


def summarize_transcript(
    transcript: Transcript,
    runtime: QwenRuntime,
) -> Summary:
    """Return an evidence-linked summary from bounded transcript batches."""
    _validate_inputs(transcript, runtime)
    all_ids = {segment.segment_id for segment in transcript.segments}
    batch_summaries: list[Summary] = []
    for index in range(0, len(transcript.segments), MAX_SEGMENTS_PER_BATCH):
        batch = transcript.segments[index : index + MAX_SEGMENTS_PER_BATCH]
        batch_ids = {segment.segment_id for segment in batch}
        batch_summaries.append(
            _call_runtime(runtime, _build_batch_prompt(batch), batch_ids)
        )

    if len(batch_summaries) == 1:
        return batch_summaries[0]
    return _call_runtime(
        runtime,
        _build_final_prompt(tuple(batch_summaries)),
        all_ids,
    )


def summarize_reviewed_transcript(
    transcript: ReviewedTranscript,
    runtime: QwenRuntime,
) -> Summary:
    """Return an evidence-linked summary of approved, restored segment text."""
    _validate_reviewed_inputs(transcript, runtime)
    all_ids = {segment.source.segment_id for segment in transcript.segments}
    batch_summaries: list[Summary] = []
    for index in range(0, len(transcript.segments), MAX_SEGMENTS_PER_BATCH):
        batch = transcript.segments[index : index + MAX_SEGMENTS_PER_BATCH]
        batch_ids = {segment.source.segment_id for segment in batch}
        batch_summaries.append(
            _call_runtime(runtime, _build_reviewed_batch_prompt(batch), batch_ids)
        )

    if len(batch_summaries) == 1:
        return batch_summaries[0]
    return _call_runtime(
        runtime,
        _build_final_prompt(tuple(batch_summaries)),
        all_ids,
    )
