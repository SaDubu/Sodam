"""Unit tests for B12 evidence-linked transcript summarization."""

import json

import pytest

from backend.contracts import EmptyTranscriptError, ModelResponseError, RawSegment, Transcript
from backend.summarization import summarize_transcript


class RecordingRuntime:
    """Return configured JSON values in call order and retain every prompt."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> object:
        self.prompts.append(prompt)
        return self._responses.pop(0)


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


def test_one_batch_returns_its_response_without_final_synthesis() -> None:
    transcript = _transcript()
    runtime = RecordingRuntime([_summary("Single summary.", ["segment-0001"])])

    result = summarize_transcript(transcript, runtime)  # type: ignore[arg-type]

    assert result.text == "Single summary."
    assert len(runtime.prompts) == 1


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
