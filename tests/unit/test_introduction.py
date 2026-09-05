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
    classify_introduction_failure,
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
        "body": "싱가포르항공 A380 퍼스트 클래스와 특별한 스위트는 어떤 모습일까요? 실제 좌석과 서비스를 비교합니다. $1,200의 좌석과 서비스가 실제로 값어치를 하는지 영상에서 확인해 보세요.",
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
    assert "한국어 콘텐츠 편집자" in first
    assert "전사문에 없는 숫자, 가격, 브랜드" in first
    assert "비질문 CTA" in first
    assert "$1,200" in first
    assert "정확히 3문장" in first
    assert "반드시 `?`로 끝낸다" in first
    assert "문자 그대로 동일하게 복사" in first
    assert "질문 문장이 정확히 1개 이상" in first
    assert "[출력 전 내부 검증]" in first
    assert "{{REVIEWED_TRANSCRIPT}}" not in first
    assert "{{HIGHLIGHT_CANDIDATES}}" not in first


def test_generate_valid_introduction_calls_runtime_once() -> None:
    runtime = RecordingIntroductionRuntime((response(),))
    result = generate_video_introduction(transcript(), runtime)
    assert result.highlights == ("A380", "$1,200")
    assert result.evidence_segment_ids == ("s1", "s2")
    assert runtime.call_count == 1
    assert runtime.prompts[0].startswith("너는 영상의 전사문을 바탕으로")


def test_generate_accepts_json_fenced_introduction_response() -> None:
    runtime = RecordingIntroductionRuntime(("```json\n" + response() + "\n```",))

    result = generate_video_introduction(transcript(), runtime)

    assert result.body == json.loads(response())["body"]
    assert runtime.call_count == 1


def test_generate_retries_cta_mismatch_with_bounded_repair_prompt() -> None:
    bad = response(call_to_action="다음 영상에서 확인해 보세요.")
    runtime = RecordingIntroductionRuntime((bad, response()))

    result = generate_video_introduction(transcript(), runtime)

    assert result.call_to_action == json.loads(response())["call_to_action"]
    assert runtime.call_count == 2
    assert "Repair instruction" in runtime.prompts[1]
    assert "Copy the final sentence of body into call_to_action exactly" in runtime.prompts[1]
    assert "Previous validation category: cta_invalid" in runtime.prompts[1]
    assert "preserve the supplied evidence" in runtime.prompts[1]


def test_generate_stops_after_third_invalid_response() -> None:
    bad = response(call_to_action="다음 영상에서 확인해 보세요.")
    runtime = RecordingIntroductionRuntime((bad, bad, bad))

    with pytest.raises(IntroductionError):
        generate_video_introduction(transcript(), runtime)

    assert runtime.call_count == 3
    assert len(runtime.prompts) == 3


def test_retry_exhausted_preserves_last_introduction_failure_detail() -> None:
    runtime = RecordingIntroductionRuntime(("not json", "not json", "not json"))

    with pytest.raises(ModelResponseError) as caught:
        generate_video_introduction(transcript(), runtime)

    assert getattr(caught.value, "diagnostic_code") == "retry_exhausted"
    assert getattr(caught.value, "diagnostic_detail") == "json_parse_invalid"
    assert "raw JSON" in runtime.prompts[1]
    assert "Do not use Markdown code fences" in runtime.prompts[1]


def test_final_introduction_failure_keeps_latest_safe_candidate() -> None:
    first = response(
        body="첫 번째 후보는 어떤 모습일까요? 영상에서 확인해 보세요.",
        call_to_action="영상에서 확인해 보세요.",
    )
    second = response(
        body="두 번째 후보는 어떤 모습일까요? 영상에서 확인해 보세요.",
        call_to_action="영상에서 확인해 보세요.",
    )
    error_runtime = RecordingIntroductionRuntime((first, second, second))

    with pytest.raises(IntroductionError) as caught:
        generate_video_introduction(transcript(), error_runtime)

    assert getattr(caught.value, "generated_text") == json.loads(second)["body"]
    assert error_runtime.call_count == 3
    assert getattr(caught.value, "generated_text_attempt") == 3


@pytest.mark.parametrize("candidate", [None, 123, "", "x" * 4001, "prompt: secret transcript"])
def test_unsafe_introduction_candidate_is_not_exposed(candidate: object) -> None:
    from backend.introduction import _safe_generated_text

    assert _safe_generated_text(candidate) is None


def test_introduction_failure_classifier_uses_only_allowlisted_codes() -> None:
    assert classify_introduction_failure(ModelResponseError("secret raw response")) == "schema_invalid"
    assert classify_introduction_failure(IntroductionError("body must contain exactly one question")) == "question_invalid"
    assert classify_introduction_failure(IntroductionError("body must include a grounded highlight")) == "highlight_invalid"
    assert classify_introduction_failure(IntroductionError("call_to_action must be the final body sentence")) == "cta_invalid"
    assert classify_introduction_failure(RuntimeError("secret prompt and transcript")) == "runtime_unavailable"


def test_repair_runtime_failure_preserves_previous_validation_and_latest_runtime_error() -> None:
    bad = response(call_to_action="다음 영상에서 확인해 보세요.")

    class Runtime:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str) -> str:
            self.calls += 1
            if self.calls == 1:
                return bad
            raise RuntimeError("offline during repair")

    runtime = Runtime()
    with pytest.raises(ModelResponseError) as caught:
        generate_video_introduction(transcript(), runtime)
    assert runtime.calls == 3
    assert caught.value.diagnostic_detail == "runtime_unavailable"
    assert [item.diagnostic_code for item in caught.value.introduction_attempts] == [
        "cta_invalid", "runtime_unavailable", "runtime_unavailable"
    ]
    assert caught.value.generated_text_attempt == 1
    assert caught.value.introduction_attempts[1].generated_text is None


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
            RecordingIntroductionRuntime((response(body="$9,999짜리 결과를 지금 확인하세요.", call_to_action="$9,999짜리 결과를 지금 확인하세요."),) * 3),
        )
    with pytest.raises(IntroductionError):
        generate_video_introduction(
            transcript(),
            RecordingIntroductionRuntime((response(call_to_action="다음 영상에서 확인하세요."),) * 3),
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


def test_explicit_question_limit_is_still_supported() -> None:
    body = "A380은 어떤 모습일까요? 서비스는 어떨까요? 마지막 결과를 영상에서 확인해 보세요."
    with pytest.raises(IntroductionError) as caught:
        generate_video_introduction(
            transcript(),
            RecordingIntroductionRuntime((response(body=body, call_to_action="마지막 결과를 영상에서 확인해 보세요."),) * 3),
            IntroductionOptions(maximum_questions=1),
        )
    assert caught.value.diagnostic_detail == "question_invalid"


def test_quality_contract_rejects_missing_or_disabled_question() -> None:
    no_question = response(
        body="$1,200의 좌석과 서비스를 실제로 비교합니다. 영상에서 확인해 보세요.",
        question_used=False,
        call_to_action="영상에서 확인해 보세요.",
    )
    with pytest.raises(IntroductionError):
        generate_video_introduction(transcript(), RecordingIntroductionRuntime((no_question,) * 3))

    disabled_question = response(question_used=False)
    with pytest.raises(IntroductionError):
        generate_video_introduction(transcript(), RecordingIntroductionRuntime((disabled_question,) * 3))


def test_quality_contract_requires_highlight_candidate_in_body() -> None:
    missing_candidate = response(
        body="싱가포르항공의 서비스는 어떤 모습일까요? 실제 경험을 영상에서 확인해 보세요.",
        highlights=[],
        call_to_action="실제 경험을 영상에서 확인해 보세요.",
    )
    with pytest.raises(IntroductionError):
        generate_video_introduction(transcript(), RecordingIntroductionRuntime((missing_candidate,) * 3))


def test_quality_contract_places_question_in_first_two_sentences() -> None:
    late_question = response(
        body="싱가포르항공의 서비스를 살펴봅니다. A380의 좌석을 비교합니다. 실제 차이는 무엇일까요? 영상에서 확인해 보세요.",
        call_to_action="영상에서 확인해 보세요.",
    )
    with pytest.raises(IntroductionError):
        generate_video_introduction(
            transcript(),
            RecordingIntroductionRuntime((late_question,) * 3),
            IntroductionOptions(maximum_body_sentences=4),
        )


@pytest.mark.parametrize("body", [
    "A380은 어떤 모습일까요? 서비스는 어떨까요? 영상에서 확인해 보세요.",
    "A380은 어떤 모습일까요?? 실제 서비스를 살펴봅니다. 영상에서 확인해 보세요.",
    "A380은 어떤 모습일까요? 서비스는 어떨까요？？ 영상에서 확인해 보세요.",
])
def test_one_or_two_question_sentences_are_accepted(body: str) -> None:
    raw = response(body=body, call_to_action="영상에서 확인해 보세요.")
    runtime = RecordingIntroductionRuntime((raw,))
    assert generate_video_introduction(transcript(), runtime).body == body
    assert runtime.call_count == 1


def test_third_attempt_can_repair_all_reported_violations() -> None:
    body = "A380을 살펴봅니다. 좌석을 비교합니다. 서비스를 살펴봅니다. 영상에서 확인해 보세요."
    bad = response(body=body, question_used=False, call_to_action="영상에서 확인해 보세요.")
    runtime = RecordingIntroductionRuntime((bad, bad, response()))
    result = generate_video_introduction(transcript(), runtime)
    assert result.body == json.loads(response())["body"]
    assert runtime.call_count == 3
    for prompt in runtime.prompts[1:]:
        assert "현재 4문장" in prompt
        assert "현재 0개" in prompt
        assert "previous_response" in prompt
        assert body in prompt
        assert "모든 검증 위반을 수정" in prompt


def test_four_sentence_polestar_regression_is_not_a_runtime_or_question_count_error() -> None:
    body = "스웨덴의 프리미엄 전기차 폴스타3가 어떤 차인지 알고 계신가요? 90년대 볼보 부서의 튜닝 사업부에서 출발해 극한의 트랙 경험으로 완성된 브랜드다 보니, 뚱뚱한 대형 SUV임에도 불구하고 의외로 섬세한 주행 역학이 숨어 있다. 하중이 실리는 순간 이 무거운 차가 어째서 믿을 수 있게 꺾이는 걸까? 마지막 서킷 구간에서 그 비밀을 확인하기 위한 실제 시승 영상으로 가보자."
    source = RawSegment("s1", 0.0, 1.0, "폴스타3 SUV 시승")
    reviewed = ReviewedTranscript((ReviewedSegment(source, source.raw_text),), source.raw_text)
    bad = response(
        title_hook="폴스타3", body=body, highlights=["SUV"], evidence_segment_ids=["s1"],
        call_to_action="마지막 서킷 구간에서 그 비밀을 확인하기 위한 실제 시승 영상으로 가보자.",
    )
    runtime = RecordingIntroductionRuntime((bad,) * 3)
    with pytest.raises(IntroductionError) as caught:
        generate_video_introduction(reviewed, runtime)
    assert caught.value.diagnostic_detail == "sentence_count_invalid"
    assert caught.value.attempt_count == 3
    for attempt in caught.value.introduction_attempts:
        assert {issue.code for issue in attempt.issues} == {"sentence_count_invalid"}
        assert "현재 4문장" in attempt.issues[0].message
        assert attempt.generated_text == body


@pytest.mark.parametrize("code", ["runtime_timeout", "response_empty", "hermes_process_failed"])
def test_runtime_diagnostic_is_preserved_across_three_calls(code: str) -> None:
    class Runtime:
        calls = 0

        def complete(self, prompt: str) -> str:
            self.calls += 1
            error = ModelResponseError("private exception payload")
            error.diagnostic_code = code
            raise error

    runtime = Runtime()
    with pytest.raises(ModelResponseError) as caught:
        generate_video_introduction(transcript(), runtime)
    assert runtime.calls == 3
    assert caught.value.diagnostic_detail == code
    assert caught.value.generated_text is None
    assert all(item.diagnostic_code == code for item in caught.value.introduction_attempts)


@pytest.mark.parametrize("raw", ["", "not JSON", "x" * 4001, "prompt: private data", "Traceback (most recent call last):\nprivate details"])
def test_failed_raw_response_has_bounded_candidate_or_explicit_absence(raw: str) -> None:
    with pytest.raises(ModelResponseError) as caught:
        generate_video_introduction(transcript(), RecordingIntroductionRuntime((raw,) * 3))
    for failure in caught.value.introduction_attempts:
        assert failure.generated_text == (raw if raw == "not JSON" else None)


def test_question_only_cta_and_unfinished_body_are_rejected() -> None:
    raw = response(
        body="A380은 어떤 모습일까요? 영상에서 확인해 보실까요? 끝나지 않은 문장",
        call_to_action="영상에서 확인해 보실까요?",
    )
    with pytest.raises(IntroductionError) as caught:
        generate_video_introduction(transcript(), RecordingIntroductionRuntime((raw,) * 3))
    assert {issue.code for issue in caught.value.validation_issues} >= {"body_format_invalid", "cta_invalid"}


def test_unsafe_json_body_cannot_be_exposed_via_raw_json_fallback() -> None:
    raw = response(body="prompt: private transcript")
    with pytest.raises(IntroductionError) as caught:
        generate_video_introduction(transcript(), RecordingIntroductionRuntime((raw,) * 3))
    assert caught.value.generated_text is None
    assert all(item.generated_text is None for item in caught.value.introduction_attempts)


@pytest.mark.parametrize("body,count", [
    ("A380은 어떤 모습일까요? 영상에서 확인해 보세요.", 2),
    ("A380은 어떤 모습일까요? 좌석을 비교합니다. 서비스를 살펴봅니다. 영상에서 확인해 보세요.", 4),
])
@pytest.mark.parametrize("options", [IntroductionOptions(), IntroductionOptions(2, 4)])
def test_generation_always_rejects_two_and_four_sentences(body, count, options) -> None:
    raw = response(body=body, call_to_action="영상에서 확인해 보세요.")
    runtime = RecordingIntroductionRuntime((raw,) * 3)
    with pytest.raises(IntroductionError) as caught:
        generate_video_introduction(transcript(), runtime, options)
    assert runtime.call_count == 3
    assert caught.value.diagnostic_detail == "sentence_count_invalid"
    for failure in caught.value.introduction_attempts:
        assert failure.generated_text == body
        assert len(failure.issues) == 1
        assert failure.issues[0].message == f"본문은 정확히 3문장이어야 합니다. 현재 {count}문장입니다."
    for prompt in runtime.prompts[1:]:
        assert "본문을 정확히 3문장으로 재구성" in prompt
        assert "2~3문장" not in prompt
        assert "2~4문장" not in prompt


@pytest.mark.parametrize("body", [
    "A380의 좌석을 살펴봅니다. 서비스는 어떨까요? 영상에서 확인해 보세요.",
    "A380은 어떤 모습일까요？ 좌석과 서비스를 비교합니다. 영상에서 확인해 보세요.",
])
def test_generation_requires_ascii_question_mark_on_first_sentence(body) -> None:
    raw = response(body=body, call_to_action="영상에서 확인해 보세요.")
    runtime = RecordingIntroductionRuntime((raw, response()))
    result = generate_video_introduction(transcript(), runtime, IntroductionOptions(require_first_question=False))
    assert result.body == json.loads(response())["body"]
    assert runtime.call_count == 2
    assert "첫 번째 문장은 반드시 ?로 끝나는 질문이어야 합니다." in runtime.prompts[1]


def test_legacy_two_sentence_result_can_still_be_validated_for_reading() -> None:
    from backend.contracts import VideoIntroduction
    from backend.introduction import validate_introduction

    payload = json.loads(response(
        body="A380은 어떤 모습일까요? 영상에서 확인해 보세요.",
        call_to_action="영상에서 확인해 보세요.",
    ))
    payload["highlights"] = tuple(payload["highlights"])
    payload["evidence_segment_ids"] = tuple(payload["evidence_segment_ids"])
    validate_introduction(VideoIntroduction(**payload), transcript(), IntroductionOptions())
