"""Unit tests for B12 evidence-linked transcript summarization."""

import json

import pytest

from backend.contracts import (
    EmptyTranscriptError,
    ModelResponseError,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
    Summary,
    SummaryOutcome,
    Transcript,
)
from backend.summarization import (
    MAX_REDUCE_PROMPT_CHARACTERS,
    _partition_summary_groups,
    _normalize_summary_response,
    _parse_summary_response,
    summarize_transcript_outcome,
    summarize_reviewed_transcript,
    summarize_transcript,
)


class RecordingRuntime:
    """Return configured JSON values in call order and retain every prompt."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> object:
        self.prompts.append(prompt)
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _summary(text: str, evidence_ids: list[str]) -> str:
    return json.dumps({"text": text, "evidence_segment_ids": evidence_ids})


def _transcript(count: int = 1) -> Transcript:
    segments = tuple(
        RawSegment(
            "segment-%04d" % index,
            float(index - 1),
            float(index),
            "source text %d" % index,
        )
        for index in range(1, count + 1)
    )
    return Transcript(segments, "\n".join(item.raw_text for item in segments))


def test_normalize_accepts_only_exact_json_markdown_fence() -> None:
    payload = _summary("Fenced summary.", ["segment-0001"])

    assert _normalize_summary_response("  " + payload + "  ") == (payload, "unchanged")
    assert _normalize_summary_response("```json\n" + payload + "\n```") == (
        payload,
        "markdown_fenced_json",
    )
    assert _normalize_summary_response("```JSON\n" + payload + "\n```") == (
        payload,
        "markdown_fenced_json",
    )


@pytest.mark.parametrize(
    ("response", "diagnostic"),
    [
        ("", "response_empty"),
        ("   ", "response_empty"),
        ("not json", "json_parse_invalid"),
        ("```text\nnot json\n```", "json_parse_invalid"),
        ("```json\n{}", "json_parse_invalid"),
    ],
)
def test_normalize_or_parse_classifies_malformed_responses(
    response: str, diagnostic: str
) -> None:
    with pytest.raises(ModelResponseError) as caught:
        _parse_summary_response(response, {"segment-0001"})

    assert getattr(caught.value, "diagnostic_code") == diagnostic
    assert "not json" not in str(caught.value)


@pytest.mark.parametrize(
    ("response", "diagnostic"),
    [
        ("{}", "schema_invalid"),
        (_summary("Unknown evidence.", ["segment-9999"]), "evidence_invalid"),
        (_summary("One. Two. Three.", ["segment-0001"]), "summary_constraint_invalid"),
    ],
)
def test_parse_classifies_contract_failures(response: str, diagnostic: str) -> None:
    with pytest.raises(ModelResponseError) as caught:
        _parse_summary_response(response, {"segment-0001"})

    assert getattr(caught.value, "diagnostic_code") == diagnostic


def test_fenced_json_is_validated_without_changing_summary_content() -> None:
    raw = "```json\n" + _summary("Fenced summary.", ["segment-0001"]) + "\n```"

    summary = _parse_summary_response(raw, {"segment-0001"})

    assert summary == Summary("Fenced summary.", ("segment-0001",))


def test_retry_adds_format_only_instruction_and_preserves_diagnostic() -> None:
    runtime = RecordingRuntime(["not json", "still not json", "nope"])

    with pytest.raises(ModelResponseError) as caught:
        summarize_transcript_outcome(_transcript(), runtime)  # type: ignore[arg-type]

    assert getattr(caught.value, "diagnostic_code") == "json_parse_invalid"
    assert getattr(caught.value, "attempt_count") == 3
    assert getattr(caught.value, "response_empty") is False
    assert len(runtime.prompts) == 3
    assert "Return raw JSON only" in runtime.prompts[1]
    assert "Do not use Markdown fences" in runtime.prompts[2]


def test_partition_respects_fan_in_prompt_limit_and_order() -> None:
    summaries = tuple(
        Summary("Summary %d." % index, ("segment-%04d" % index,))
        for index in range(1, 10)
    )

    groups = _partition_summary_groups(summaries, max_chars=MAX_REDUCE_PROMPT_CHARACTERS)

    assert [len(group) for group in groups] == [8, 1]
    assert [item.text for group in groups for item in group] == [
        item.text for item in summaries
    ]


def test_partition_rejects_single_oversize_summary() -> None:
    summary = Summary("x" * 1_000, ("segment-0001",))

    with pytest.raises(ModelResponseError):
        _partition_summary_groups((summary,), max_chars=100)


def test_nine_segments_use_two_batches_and_one_final_synthesis() -> None:
    transcript = _transcript(9)
    runtime = RecordingRuntime(
        [
            _summary("First batch summary.", ["segment-0001"]),
            _summary("Second batch summary.", ["segment-0009"]),
            _summary("Final combined summary.", ["segment-0001", "segment-0009"]),
        ]
    )

    result = summarize_transcript(transcript, runtime)  # type: ignore[arg-type]

    assert result.text == "Final combined summary."
    assert result.evidence_segment_ids == ("segment-0001", "segment-0009")
    assert len(runtime.prompts) == 3
    assert "segment-0001" in runtime.prompts[0]
    assert "segment-0009" in runtime.prompts[1]
    assert "Validated intermediate summaries:" in runtime.prompts[2]
    assert all(
        "exactly one or two complete sentences" in prompt
        for prompt in runtime.prompts
    )
    final_prompt = runtime.prompts[2]
    assert "factual Korean summary" in final_prompt
    assert "supplied intermediate summaries as a whole" in final_prompt
    assert "introduction" not in final_prompt.lower()
    assert "CTA" not in final_prompt
    assert "curiosity" not in final_prompt.lower()
    assert "one early fact" in final_prompt


def test_one_batch_returns_its_response_without_final_synthesis() -> None:
    transcript = _transcript()
    runtime = RecordingRuntime([_summary("Single summary.", ["segment-0001"])])

    result = summarize_transcript(transcript, runtime)  # type: ignore[arg-type]

    assert result.text == "Single summary."
    assert len(runtime.prompts) == 1


def test_long_transcript_uses_bounded_hierarchical_reduce() -> None:
    transcript = _transcript(1_305)
    batch_count = (1_305 + 7) // 8
    batch_ids = [
        "segment-%04d" % (index * 8 + 1)
        for index in range(batch_count)
    ]
    responses = [
        _summary("Batch %03d." % index, [segment_id])
        for index, segment_id in enumerate(batch_ids)
    ]
    level = list(batch_ids)
    while len(level) > 8:
        next_level: list[str] = []
        for start in range(0, len(level), 8):
            next_level.append(level[start])
            responses.append(_summary("Reduced %03d." % len(next_level), [level[start]]))
        level = next_level
    responses.append(_summary("Long transcript summary.", level))
    runtime = RecordingRuntime(responses)

    result = summarize_transcript(transcript, runtime)  # type: ignore[arg-type]

    assert result.text == "Long transcript summary."
    assert len(runtime.prompts) == batch_count + 21 + 3 + 1
    assert all(len(prompt) <= MAX_REDUCE_PROMPT_CHARACTERS for prompt in runtime.prompts)
    assert any("Validated summaries to reduce:" in prompt for prompt in runtime.prompts)
    assert len(json.loads(runtime.prompts[-1].split("Validated intermediate summaries:\n", 1)[1])) == 3


def test_reviewed_transcript_uses_same_hierarchical_path() -> None:
    source_segments = tuple(
        RawSegment("segment-%04d" % index, index - 1, index, "raw %d" % index)
        for index in range(1, 10)
    )
    reviewed = ReviewedTranscript(
        tuple(ReviewedSegment(segment, "reviewed %d" % index) for index, segment in enumerate(source_segments, 1)),
        "\n".join("reviewed %d" % index for index in range(1, 10)),
    )
    runtime = RecordingRuntime(
        [
            _summary("First reviewed.", ["segment-0001"]),
            _summary("Second reviewed.", ["segment-0009"]),
            _summary("Reviewed final.", ["segment-0001", "segment-0009"]),
        ]
    )

    result = summarize_reviewed_transcript(reviewed, runtime)  # type: ignore[arg-type]

    assert result.text == "Reviewed final."
    assert len(runtime.prompts) == 3
    assert "Reviewed segments:" in runtime.prompts[0]


def test_final_failure_returns_labeled_review_only_fallback() -> None:
    transcript = _transcript(9)
    runtime = RecordingRuntime(
        [
            _summary("First batch summary.", ["segment-0001"]),
            _summary("Second batch summary.", ["segment-0009"]),
            RuntimeError("secret prompt"),
            RuntimeError("secret prompt"),
            RuntimeError("secret prompt"),
        ]
    )

    outcome = summarize_transcript_outcome(transcript, runtime)  # type: ignore[arg-type]

    assert isinstance(outcome, SummaryOutcome)
    assert outcome.status == "fallback"
    assert outcome.failure_category == "final_failed"
    assert outcome.fallback_source == "reduce"
    assert outcome.attempt_count == 5
    assert outcome.summary.text == "First batch summary."
    assert len(runtime.prompts) == 5


def test_batch_failure_returns_partial_fallback_without_raw_error() -> None:
    transcript = _transcript(9)
    runtime = RecordingRuntime(
        [
            _summary("First batch summary.", ["segment-0001"]),
            "not json",
            "not json",
            "not json",
        ]
    )

    outcome = summarize_transcript_outcome(transcript, runtime)  # type: ignore[arg-type]

    assert outcome.status == "fallback"
    assert outcome.failure_category == "batch_failed"
    assert outcome.fallback_source == "batch"
    assert outcome.summary.evidence_segment_ids == ("segment-0001",)
    assert len(runtime.prompts) == 4


def test_all_batch_attempts_fail_with_safe_category() -> None:
    runtime = RecordingRuntime([RuntimeError("secret transcript")] * 3)

    with pytest.raises(ModelResponseError) as caught:
        summarize_transcript_outcome(_transcript(), runtime)  # type: ignore[arg-type]

    assert getattr(caught.value, "summary_failure_category") == "batch_failed"
    assert "secret" not in str(caught.value)
    assert len(runtime.prompts) == 3


def test_empty_transcript_is_rejected() -> None:
    with pytest.raises(EmptyTranscriptError):
        summarize_transcript(Transcript((), ""), RecordingRuntime([]))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "response",
    [
        _summary("Unsupported evidence.", ["not-a-segment"]),
        "not json",
    ],
)
def test_invalid_response_or_unknown_evidence_is_rejected(response: object) -> None:
    with pytest.raises(ModelResponseError):
        summarize_transcript(_transcript(), RecordingRuntime([response]))  # type: ignore[arg-type]


def test_missing_runtime_contract_is_rejected() -> None:
    with pytest.raises(TypeError):
        summarize_transcript(_transcript(), object())  # type: ignore[arg-type]


def test_input_transcript_is_not_mutated() -> None:
    transcript = _transcript()
    original_segments = transcript.segments
    original_text = transcript.final_text

    summarize_transcript(
        transcript,
        RecordingRuntime([_summary("Summary remains valid.", ["segment-0001"])]),
    )  # type: ignore[arg-type]

    assert transcript.segments == original_segments
    assert transcript.final_text == original_text
