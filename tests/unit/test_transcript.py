"""Unit tests for B11 transcript assembly contracts."""

import pytest

from backend.contracts import RawSegment, TranscriptAssemblyError
from backend.storage import assemble_transcript


def _segment(
    segment_id: str = "segment-0001",
    start: float = 0.0,
    end: float = 1.0,
    text: str = "first line",
    confidence: float | None = 0.9,
) -> RawSegment:
    return RawSegment(segment_id, start, end, text, confidence)


def test_valid_segments_preserve_order_and_build_final_text() -> None:
    segments = [
        _segment(),
        _segment("segment-0002", 1.0, 2.0, "second line", None),
    ]

    transcript = assemble_transcript(segments)

    assert transcript.segments == tuple(segments)
    assert transcript.final_text == "first line\nsecond line"


def test_empty_list_returns_an_empty_transcript() -> None:
    transcript = assemble_transcript([])

    assert transcript.segments == ()
    assert transcript.final_text == ""


@pytest.mark.parametrize(
    "segments",
    [
        [_segment(), _segment("segment-0001", 1.0, 2.0)],
        [_segment(" segment-0001 ")],
        [_segment(), _segment("segment-0002", -0.1, 0.5)],
        [_segment(), _segment("segment-0002", 0.5, 0.75)],
        [_segment(text="   ")],
        [_segment(confidence=1.1)],
    ],
)
def test_invalid_segment_contracts_are_rejected(segments: list[RawSegment]) -> None:
    with pytest.raises(TranscriptAssemblyError):
        assemble_transcript(segments)


@pytest.mark.parametrize(
    "value",
    [(), [_segment(), object()]],
)
def test_non_list_or_non_raw_segment_input_is_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        assemble_transcript(value)  # type: ignore[arg-type]


def test_input_list_and_segments_are_not_mutated() -> None:
    segment = _segment()
    segments = [segment]

    assemble_transcript(segments)

    assert segments == [segment]
    assert segments[0] is segment
