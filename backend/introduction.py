"""Fact-grounded video-introduction generation."""

import json
import re
from typing import Protocol

from .contracts import (
    Highlight,
    IntroductionOptions,
    ReviewedTranscript,
    VideoIntroduction,
    IntroductionError,
    ModelResponseError,
)


_PRICE_RE = re.compile(r"(?:[$₩￦]\s?\d[\d,.]*|\d[\d,.]*\s?(?:원|달러|만원|억))")
_LATIN_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.-]{1,}\b")
_KOREAN_GRADE_RE = re.compile(r"(?:퍼스트|비즈니스|이코노미|프리미엄|[1-5]성급)\s*클래스?")
_NUMBER_RE = re.compile(r"\b\d[\d,.]*\b")
_RESPONSE_KEYS = {
    "title_hook",
    "body",
    "highlights",
    "evidence_segment_ids",
    "question_used",
    "call_to_action",
}


class IntroductionRuntime(Protocol):
    """Injected local structured-output runtime used by introduction generation."""

    def complete(self, prompt: str) -> str:
        """Return one JSON response string for a validated prompt."""
        ...


def extract_highlights(
    transcript: ReviewedTranscript,
) -> tuple[Highlight, ...]:
    """Return source-grounded brand, price, grade, and feature candidates."""
    if not isinstance(transcript, ReviewedTranscript):
        raise TypeError("transcript must be a ReviewedTranscript")
    if not transcript.segments:
        raise IntroductionError("cannot extract highlights from an empty transcript")
    candidates: dict[str, tuple[str, list[str]]] = {}
    for segment in transcript.segments:
        if not hasattr(segment, "source") or not isinstance(segment.final_text, str):
            raise TypeError("transcript segments must be ReviewedSegment values")
        text = segment.final_text
        matches: list[tuple[str, str]] = []
        matches.extend((value, "price") for value in _PRICE_RE.findall(text))
        matches.extend((value, "grade") for value in _KOREAN_GRADE_RE.findall(text))
        matches.extend((value, "brand") for value in _LATIN_TOKEN_RE.findall(text) if not value.isdigit())
        for value in matches:
            key = value[0]
            if key not in candidates:
                candidates[key] = (value[1], [])
            if segment.source.segment_id not in candidates[key][1]:
                candidates[key][1].append(segment.source.segment_id)
    result: list[Highlight] = []
    for text, (category, evidence_ids) in candidates.items():
        result.append(Highlight(text, category, tuple(evidence_ids)))
    return tuple(result)


def build_introduction_prompt(
    transcript: ReviewedTranscript,
    highlights: tuple[Highlight, ...],
    options: IntroductionOptions,
) -> str:
    """Build a deterministic Korean introduction prompt with a strict JSON schema."""
    _validate_common_inputs(transcript, options)
    if not isinstance(highlights, tuple):
        raise TypeError("highlights must be a tuple")
    transcript_ids = {segment.source.segment_id for segment in transcript.segments}
    serializable: list[dict[str, object]] = []
    for highlight in highlights:
        if not isinstance(highlight, Highlight):
            raise TypeError("highlights must contain Highlight values")
        if not highlight.evidence_segment_ids or not set(highlight.evidence_segment_ids) <= transcript_ids:
            raise IntroductionError("highlight evidence does not belong to transcript")
        serializable.append(
            {
                "text": highlight.text,
                "category": highlight.category,
                "evidence_segment_ids": list(highlight.evidence_segment_ids),
            }
        )
    evidence = [
        {"segment_id": segment.source.segment_id, "text": segment.final_text}
        for segment in transcript.segments
    ]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_RESPONSE_KEYS),
        "properties": {
            "title_hook": {"type": "string"},
            "body": {"type": "string"},
            "highlights": {"type": "array", "items": {"type": "string"}},
            "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
            "question_used": {"type": "boolean"},
            "call_to_action": {"type": "string"},
        },
    }
    return "\n".join(
        (
            "당신은 한국어 영상 소개글 편집자다.",
            "전사 근거만 사용해 제목형 한 줄과 2~3문장 본문을 작성하라.",
            "결과를 전부 선공개하지 말고 실제 하이라이트와 시청할 이유를 남겨라.",
            "원문에 없는 브랜드, 가격, 등급, 수상 이력, 숫자를 절대 만들지 마라.",
            "질문은 자연스러울 때 최대 하나만 사용하고, 마지막 문장은 구체적인 시청 CTA로 끝내라.",
            f"본문 문장 수는 {options.minimum_body_sentences}~{options.maximum_body_sentences}개다.",
            "JSON object 하나만 출력하고 markdown이나 설명을 덧붙이지 마라.",
            "아래 schema는 출력 형식 설명일 뿐이다. schema의 type, properties, required를 절대 반환하지 마라.",
            "title_hook, body, highlights, evidence_segment_ids, question_used, call_to_action의 실제 값만 반환하라.",
            "highlights 배열은 Highlight candidates의 text 값을 문자 단위로 그대로 복사하라. 후보에 없는 조합, 번역, 수식어를 highlights에 만들지 마라.",
            "본문의 마지막 문장은 CTA여야 한다. call_to_action 필드는 본문 마지막 문장을 구두점까지 문자 단위로 그대로 복사하라. 별도 문장을 만들지 마라.",
            "JSON schema:",
            json.dumps(schema, ensure_ascii=False, sort_keys=True),
            "Evidence:",
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            "Highlight candidates:",
            json.dumps(serializable, ensure_ascii=False, sort_keys=True),
        )
    )


def validate_introduction(
    introduction: VideoIntroduction,
    transcript: ReviewedTranscript,
    options: IntroductionOptions,
) -> None:
    """Validate style, source evidence, highlights, question, and final CTA."""
    _validate_common_inputs(transcript, options)
    if not isinstance(introduction, VideoIntroduction):
        raise TypeError("introduction must be a VideoIntroduction")
    for name in ("title_hook", "body", "call_to_action"):
        value = getattr(introduction, name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise IntroductionError(f"{name} must be a trimmed non-blank string")
    if "\n" in introduction.title_hook:
        raise IntroductionError("title_hook must be one line")
    if not isinstance(introduction.highlights, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in introduction.highlights
    ):
        raise IntroductionError("highlights must be a tuple of non-blank strings")
    if len(set(introduction.highlights)) != len(introduction.highlights):
        raise IntroductionError("highlights must not repeat")
    ids = [segment.source.segment_id for segment in transcript.segments]
    id_set = set(ids)
    if not isinstance(introduction.evidence_segment_ids, tuple) or not introduction.evidence_segment_ids:
        raise IntroductionError("at least one evidence segment is required")
    if not set(introduction.evidence_segment_ids) <= id_set:
        raise IntroductionError("unknown evidence segment ID")
    source_text = "\n".join(segment.final_text for segment in transcript.segments)
    if any(value not in source_text for value in introduction.highlights):
        raise IntroductionError("highlight is not present in transcript")
    sentence_count = len(re.findall(r"[^.!?。！？]+[.!?。！？]", introduction.body))
    if not (options.minimum_body_sentences <= sentence_count <= options.maximum_body_sentences):
        raise IntroductionError("body sentence count is outside options")
    question_count = introduction.body.count("?") + introduction.body.count("？")
    if question_count > options.maximum_questions or introduction.question_used != (question_count > 0):
        raise IntroductionError("question_used does not match body")
    if not introduction.body.endswith(introduction.call_to_action):
        raise IntroductionError("call_to_action must be the final body sentence")
    for value in _PRICE_RE.findall(introduction.title_hook + " " + introduction.body):
        if value not in source_text:
            raise IntroductionError("introduction contains an ungrounded price")
    for value in _LATIN_TOKEN_RE.findall(introduction.title_hook + " " + introduction.body):
        if value not in source_text:
            raise IntroductionError("introduction contains an ungrounded proper token")


def _validate_common_inputs(transcript: ReviewedTranscript, options: IntroductionOptions) -> None:
    if not isinstance(transcript, ReviewedTranscript):
        raise TypeError("transcript must be a ReviewedTranscript")
    if not transcript.segments:
        raise IntroductionError("transcript must not be empty")
    if not isinstance(options, IntroductionOptions):
        raise TypeError("options must be IntroductionOptions")
    if (
        isinstance(options.minimum_body_sentences, bool)
        or not isinstance(options.minimum_body_sentences, int)
        or isinstance(options.maximum_body_sentences, bool)
        or not isinstance(options.maximum_body_sentences, int)
        or options.minimum_body_sentences < 1
        or options.maximum_body_sentences < options.minimum_body_sentences
        or options.maximum_questions < 0
    ):
        raise ValueError("introduction sentence options are invalid")


def generate_video_introduction(
    transcript: ReviewedTranscript,
    runtime: IntroductionRuntime,
    options: IntroductionOptions = IntroductionOptions(),
) -> VideoIntroduction:
    """Generate and strictly validate video copy without replacing Summary."""
    _validate_common_inputs(transcript, options)
    if not callable(getattr(runtime, "complete", None)):
        raise TypeError("runtime.complete must be callable")
    highlights = extract_highlights(transcript)
    prompt = build_introduction_prompt(transcript, highlights, options)
    try:
        raw = runtime.complete(prompt)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        raise ModelResponseError("introduction runtime failed") from exc
    if not isinstance(raw, str):
        raise ModelResponseError("introduction runtime response must be str")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ModelResponseError("introduction response is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _RESPONSE_KEYS:
        raise ModelResponseError("introduction response schema is invalid")
    if (
        not isinstance(payload["title_hook"], str)
        or not isinstance(payload["body"], str)
        or not isinstance(payload["call_to_action"], str)
        or not isinstance(payload["highlights"], list)
        or not isinstance(payload["evidence_segment_ids"], list)
        or type(payload["question_used"]) is not bool
        or any(not isinstance(value, str) for value in payload["highlights"])
        or any(not isinstance(value, str) for value in payload["evidence_segment_ids"])
    ):
        raise ModelResponseError("introduction response field types are invalid")
    result = VideoIntroduction(
        payload["title_hook"],
        payload["body"],
        tuple(payload["highlights"]),
        tuple(payload["evidence_segment_ids"]),
        payload["question_used"],
        payload["call_to_action"],
    )
    validate_introduction(result, transcript, options)
    return result
