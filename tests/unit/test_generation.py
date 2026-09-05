"""P13-02 generation request, instruction wrapper, and delegation tests."""

import json

import pytest

from backend.contracts import (
    IntroductionError,
    IntroductionOptions,
    ModelResponseError,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
    SummaryOutcome,
    VideoIntroduction,
)
from backend.generation import (
    MAX_GENERATION_INSTRUCTION_CHARS,
    GenerationRequest,
    InstructionRuntime,
    build_generation_prompt,
    generate_from_transcript,
    validate_generation_request,
)


class RecordingRuntime:
    """Record prompts and return one deterministic response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class SequenceRuntime:
    """Return queued responses or raise queued exceptions for retry tests."""

    def __init__(self, values: list[object]) -> None:
        self.values = list(values)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value  # type: ignore[return-value]


def reviewed_transcript() -> ReviewedTranscript:
    first = RawSegment("s1", 0.0, 4.0, "싱가포르항공 A380 퍼스트 클래스")
    second = RawSegment("s2", 4.0, 8.0, "가격은 $1,200이며 좌석과 서비스를 비교합니다")
    return ReviewedTranscript(
        (ReviewedSegment(first, first.raw_text), ReviewedSegment(second, second.raw_text)),
        first.raw_text + "\n" + second.raw_text,
    )


def long_reviewed_transcript() -> ReviewedTranscript:
    segments = tuple(
        RawSegment("s%d" % index, float(index - 1), float(index), "검토 내용 %d" % index)
        for index in range(1, 10)
    )
    return ReviewedTranscript(
        tuple(ReviewedSegment(segment, segment.raw_text) for segment in segments),
        "\n".join(segment.raw_text for segment in segments),
    )


def summary_response(text: str = "싱가포르항공 A380의 좌석과 서비스를 확인합니다.") -> str:
    return json.dumps(
        {"text": text, "evidence_segment_ids": ["s1"]},
        ensure_ascii=False,
    )


def introduction_response() -> str:
    return json.dumps(
        {
            "title_hook": "A380 퍼스트 클래스, $1,200의 경험",
            "body": "싱가포르항공 A380 퍼스트 클래스는 어떤 모습일까요? 좌석과 서비스를 비교합니다. $1,200의 좌석과 서비스를 영상에서 확인해 보세요.",
            "highlights": ["A380", "$1,200"],
            "evidence_segment_ids": ["s1", "s2"],
            "question_used": True,
            "call_to_action": "$1,200의 좌석과 서비스를 영상에서 확인해 보세요.",
        },
        ensure_ascii=False,
    )


def test_none_instruction_preserves_base_and_valid_instruction_is_delimited() -> None:
    base = "Evidence: segment s1\nReturn JSON only."

    assert build_generation_prompt(base, None) == base

    prompt = build_generation_prompt(base, "담백한 문체로 작성해줘")
    assert prompt.startswith(base)
    assert "[USER_GENERATION_INSTRUCTION]" in prompt
    assert "담백한 문체로 작성해줘" in prompt
    assert "[END_USER_GENERATION_INSTRUCTION]" in prompt
    assert "validation rules" in prompt


@pytest.mark.parametrize(
    "instruction",
    ["", " ", " 지시", "지시 ", "a" * (MAX_GENERATION_INSTRUCTION_CHARS + 1), "bad\x00text"],
)
def test_invalid_instruction_is_rejected(instruction: str) -> None:
    with pytest.raises(ValueError):
        build_generation_prompt("base", instruction)


def test_prompt_type_and_boundary_validation() -> None:
    with pytest.raises(TypeError):
        build_generation_prompt(1, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_generation_prompt(" ", None)
    assert len(build_generation_prompt("base", "a" * MAX_GENERATION_INSTRUCTION_CHARS)) > 0


def test_instruction_runtime_calls_wrapped_runtime_once_and_returns_response() -> None:
    runtime = RecordingRuntime('{"text":"ok"}')
    wrapped = InstructionRuntime(runtime, "한국어로 간결하게")

    result = wrapped.complete("Evidence: s1")

    assert result == '{"text":"ok"}'
    assert len(runtime.prompts) == 1
    assert runtime.prompts[0].startswith("Evidence: s1")
    assert "한국어로 간결하게" in runtime.prompts[0]


def test_instruction_runtime_rejects_invalid_prompt_without_call() -> None:
    runtime = RecordingRuntime("unused")
    wrapped = InstructionRuntime(runtime, None)
    with pytest.raises(ValueError):
        wrapped.complete(" ")
    assert runtime.prompts == []


def test_summary_delegation_reuses_existing_retry_contract() -> None:
    runtime = SequenceRuntime(["not json", "not json", "not json"])
    request = GenerationRequest(reviewed_transcript(), "summary", "핵심만 요약해줘")

    with pytest.raises(ModelResponseError):
        generate_from_transcript(request, runtime)

    assert len(runtime.prompts) == 3
    assert all("핵심만 요약해줘" in prompt for prompt in runtime.prompts)


def test_summary_delegation_returns_existing_success_outcome() -> None:
    runtime = RecordingRuntime(summary_response())
    request = GenerationRequest(reviewed_transcript(), "summary", "한 문장으로")

    result = generate_from_transcript(request, runtime)

    assert isinstance(result, SummaryOutcome)
    assert result.status == "success"
    assert result.summary.text == "싱가포르항공 A380의 좌석과 서비스를 확인합니다."
    assert len(runtime.prompts) == 1
    assert "한 문장으로" in runtime.prompts[0]


def test_introduction_delegation_repairs_on_second_attempt() -> None:
    runtime = SequenceRuntime(["not json", introduction_response()])
    request = GenerationRequest(reviewed_transcript(), "introduction", "호기심을 자극해줘")

    result = generate_from_transcript(request, runtime)

    assert isinstance(result, VideoIntroduction)
    assert result.call_to_action.endswith("확인해 보세요.")
    assert len(runtime.prompts) == 2
    assert all("호기심을 자극해줘" in prompt for prompt in runtime.prompts)


def test_user_template_is_sent_with_evidence_and_style_on_every_attempt() -> None:
    from backend.introduction import build_introduction_prompt, extract_highlights

    source = reviewed_transcript()
    base = build_introduction_prompt(source, extract_highlights(source), IntroductionOptions())
    payload = json.loads(introduction_response())
    payload["body"] = "A380은 어떤 모습일까요? " + payload["call_to_action"]
    runtime = SequenceRuntime([json.dumps(payload, ensure_ascii=False)] * 2 + [introduction_response()])
    request = GenerationRequest(source, "introduction", "담백하게 작성해줘", IntroductionOptions(2, 4))

    result = generate_from_transcript(request, runtime)

    assert isinstance(result, VideoIntroduction)
    assert len(runtime.prompts) == 3
    for index, prompt in enumerate(runtime.prompts):
        assert prompt.startswith(base)
        assert prompt.count("[USER_GENERATION_INSTRUCTION]") == 1
        assert "담백하게 작성해줘" in prompt
        assert prompt.index("[검토 완료 전사문 끝]") < prompt.index("[USER_GENERATION_INSTRUCTION]")
        if index:
            assert prompt.index("Repair instruction:") < prompt.index("[USER_GENERATION_INSTRUCTION]")
            assert "현재 2문장입니다." in prompt
            assert "본문을 정확히 3문장" in prompt


def test_introduction_invalid_responses_keep_existing_retry_error() -> None:
    runtime = SequenceRuntime(["not json", "still not json", "again not json"])
    request = GenerationRequest(reviewed_transcript(), "introduction")

    with pytest.raises(ModelResponseError) as caught:
        generate_from_transcript(request, runtime)

    assert getattr(caught.value, "diagnostic_code") == "retry_exhausted"
    assert getattr(caught.value, "diagnostic_detail") == "json_parse_invalid"
    assert len(runtime.prompts) == 3


def test_summary_partial_batch_failure_preserves_existing_fallback() -> None:
    runtime = SequenceRuntime([summary_response(), "bad", "bad", "bad"])
    request = GenerationRequest(long_reviewed_transcript(), "summary", "간결하게")

    result = generate_from_transcript(request, runtime)

    assert isinstance(result, SummaryOutcome)
    assert result.status == "fallback"
    assert result.fallback_source == "batch"
    assert result.summary.text == "싱가포르항공 A380의 좌석과 서비스를 확인합니다."
    assert len(runtime.prompts) == 4


@pytest.mark.parametrize("kind", ["unknown", "both", ""])
def test_invalid_request_does_not_call_runtime(kind: str) -> None:
    runtime = RecordingRuntime("unused")
    request = GenerationRequest(reviewed_transcript(), kind)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        generate_from_transcript(request, runtime)
    assert runtime.prompts == []


def test_invalid_transcript_and_options_fail_before_runtime_call() -> None:
    runtime = RecordingRuntime("unused")
    empty = ReviewedTranscript((), "")
    with pytest.raises(ValueError):
        validate_generation_request(GenerationRequest(empty, "summary"))
    with pytest.raises(ValueError):
        validate_generation_request(
            GenerationRequest(reviewed_transcript(), "introduction", introduction_options=IntroductionOptions(0, 3))
        )
    assert runtime.prompts == []


def test_runtime_type_and_downstream_exceptions_are_preserved() -> None:
    with pytest.raises(TypeError):
        InstructionRuntime(object(), None)  # type: ignore[arg-type]

    class FailingRuntime:
        def complete(self, prompt: str) -> str:
            raise RuntimeError("runtime failure")

    with pytest.raises(ModelResponseError):
        generate_from_transcript(
            GenerationRequest(reviewed_transcript(), "summary"), FailingRuntime()
        )


@pytest.mark.parametrize("limit", [None, 1, 2])
def test_optional_question_limit_is_valid(limit: int | None) -> None:
    validate_generation_request(GenerationRequest(
        reviewed_transcript(), "introduction",
        introduction_options=IntroductionOptions(maximum_questions=limit),
    ))


@pytest.mark.parametrize("limit", [0, -1, True, "1", 1.5])
def test_invalid_question_limit_fails_before_generation(limit: object) -> None:
    runtime = RecordingRuntime("unused")
    with pytest.raises(ValueError):
        generate_from_transcript(GenerationRequest(
            reviewed_transcript(), "introduction",
            introduction_options=IntroductionOptions(maximum_questions=limit),
        ), runtime)
    assert not runtime.prompts
