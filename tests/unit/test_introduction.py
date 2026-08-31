"""Unit tests for V2-I01 fact-grounded video introductions."""

import json

import pytest

from backend.contracts import (
    IntroductionError,
    IntroductionOptions,
    ModelResponseError,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
)
from backend.introduction import (
    build_introduction_prompt,
    extract_highlights,
    generate_video_introduction,
)
from tests.fakes_productization import RecordingIntroductionRuntime


def transcript() -> ReviewedTranscript:
    first = RawSegment("s1", 0.0, 4.0, "싱가포르항공 A380 퍼스트 클래스와 특별한 스위트")
    second = RawSegment("s2", 4.0, 8.0, "가격은 $1,200이며 실제 좌석과 서비스를 비교합니다")
    return ReviewedTranscript(
        (ReviewedSegment(first, first.raw_text), ReviewedSegment(second, second.raw_text)),
        first.raw_text + "\n" + second.raw_text,
    )


def response(**overrides: object) -> str:
    payload: dict[str, object] = {
        "title_hook": "A380 퍼스트 클래스, $1,200의 경험",
        "body": "싱가포르항공 A380 퍼스트 클래스와 특별한 스위트는 어떤 모습일까요? $1,200의 좌석과 서비스가 실제로 값어치를 하는지 영상에서 확인해 보세요.",
        "highlights": ["A380", "$1,200"],
        "evidence_segment_ids": ["s1", "s2"],
        "question_used": True,
        "call_to_action": "$1,200의 좌석과 서비스가 실제로 값어치를 하는지 영상에서 확인해 보세요.",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_extract_highlights_preserves_source_evidence() -> None:
    values = extract_highlights(transcript())
    by_text = {item.text: item for item in values}
    assert "$1,200" in by_text
    assert "A380" in by_text
    assert "s2" in by_text["$1,200"].evidence_segment_ids
    assert "s1" in by_text["A380"].evidence_segment_ids


def test_prompt_is_deterministic_and_contains_grounding_rules() -> None:
    source = transcript()
    highlights = extract_highlights(source)
    first = build_introduction_prompt(source, highlights, IntroductionOptions())
    second = build_introduction_prompt(source, highlights, IntroductionOptions())
    assert first == second
    assert "한국어 영상 소개글" in first
    assert "원문에 없는 브랜드" in first
    assert "시청 CTA" in first
    assert "$1,200" in first
    assert "JSON schema" in first
    assert "schema의 type, properties, required를 절대 반환하지 마라" in first
    assert "실제 값만 반환하라" in first
    assert "문자 단위로 그대로 복사하라" in first
    assert "call_to_action 필드는 본문 마지막 문장을" in first


def test_generate_valid_introduction_calls_runtime_once() -> None:
    runtime = RecordingIntroductionRuntime((response(),))
    result = generate_video_introduction(transcript(), runtime)
    assert result.highlights == ("A380", "$1,200")
    assert result.evidence_segment_ids == ("s1", "s2")
    assert runtime.call_count == 1
    assert runtime.prompts[0].startswith("당신은 한국어 영상 소개글 편집자")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        b"{}",
        json.dumps({"wrong": "shape"}),
    ],
)
def test_invalid_model_response_is_rejected(raw: object) -> None:
    class Runtime:
        def complete(self, prompt: str) -> object:
            return raw

    with pytest.raises(ModelResponseError):
        generate_video_introduction(transcript(), Runtime())


def test_ungrounded_price_and_cta_are_rejected() -> None:
    with pytest.raises(IntroductionError):
        generate_video_introduction(
            transcript(),
            RecordingIntroductionRuntime((response(body="$9,999짜리 결과를 지금 확인하세요.", call_to_action="$9,999짜리 결과를 지금 확인하세요."),)),
        )
    with pytest.raises(IntroductionError):
        generate_video_introduction(
            transcript(),
            RecordingIntroductionRuntime((response(call_to_action="다음 영상에서 확인하세요."),)),
        )


def test_empty_transcript_and_runtime_errors() -> None:
    empty = ReviewedTranscript((), "")
    with pytest.raises(IntroductionError):
        extract_highlights(empty)
    with pytest.raises(TypeError):
        generate_video_introduction(transcript(), object())

    class FailingRuntime:
        def complete(self, prompt: str) -> str:
            raise RuntimeError("offline")

    with pytest.raises(ModelResponseError):
        generate_video_introduction(transcript(), FailingRuntime())

    class InterruptingRuntime:
        def __init__(self, error: BaseException) -> None:
            self.error = error

        def complete(self, prompt: str) -> str:
            raise self.error

    with pytest.raises(KeyboardInterrupt):
        generate_video_introduction(transcript(), InterruptingRuntime(KeyboardInterrupt()))
    with pytest.raises(SystemExit):
        generate_video_introduction(transcript(), InterruptingRuntime(SystemExit(2)))


def test_too_many_questions_are_rejected() -> None:
    body = "첫 번째 질문일까요? 두 번째 질문일까요? 마지막 결과를 영상에서 확인해 보세요."
    with pytest.raises(IntroductionError):
        generate_video_introduction(
            transcript(),
            RecordingIntroductionRuntime((response(body=body, call_to_action="마지막 결과를 영상에서 확인해 보세요."),)),
        )
