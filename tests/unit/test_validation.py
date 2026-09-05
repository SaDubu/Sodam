"""Unit tests for B10 review classification and CR01 input compatibility."""

import pytest

from backend.contracts import ProtectedText, ProtectionError
from backend.validation import validate_revision


_TOKEN_ONE = "[[SODAM_PROTECTED_0001]]"
_TOKEN_TWO = "[[SODAM_PROTECTED_0002]]"


def _protected_text() -> ProtectedText:
    return ProtectedText(
        f"{_TOKEN_ONE}  안녕  ,  세계",
        {_TOKEN_ONE: "JFK"},
    )


def test_normalized_protected_text_is_safe_even_when_not_original_text() -> None:
    protected = _protected_text()
    normalized = f"{_TOKEN_ONE} 안녕, 세계"

    result = validate_revision(normalized, normalized, protected)

    assert result.approved_text == normalized
    assert result.review_items == ()


def test_whitespace_and_safe_punctuation_changes_are_auto_approved() -> None:
    protected = _protected_text()
    raw = f"{_TOKEN_ONE} 안녕 , 세계"
    corrected = f"{_TOKEN_ONE} 안녕, 세계"

    result = validate_revision(raw, corrected, protected)

    assert result.approved_text == corrected
    assert result.review_items == ()


def test_non_formatting_change_is_returned_for_review_instead_of_approval() -> None:
    protected = _protected_text()
    raw = f"{_TOKEN_ONE} 안녕, 세계"
    corrected = f"{_TOKEN_ONE} 서울, 세계"

    result = validate_revision(raw, corrected, protected)

    assert result.approved_text == raw
    assert result.review_items == (
        {
            "kind": "review_required",
            "raw": "안녕",
            "corrected": "서울",
            "reason": "non_formatting_change",
        },
    )


@pytest.mark.parametrize(
    ("raw", "corrected", "protected"),
    [
        (
            f"{_TOKEN_ONE} text",
            "text",
            ProtectedText(f"{_TOKEN_ONE} text", {_TOKEN_ONE: "JFK"}),
        ),
        (
            f"{_TOKEN_ONE} text",
            f"{_TOKEN_TWO} text",
            ProtectedText(f"{_TOKEN_ONE} text", {_TOKEN_ONE: "JFK"}),
        ),
        (
            f"{_TOKEN_ONE} {_TOKEN_ONE} text",
            f"{_TOKEN_ONE} {_TOKEN_ONE} text",
            ProtectedText(f"{_TOKEN_ONE} text", {_TOKEN_ONE: "JFK"}),
        ),
        (
            "text",
            "text",
            ProtectedText(f"{_TOKEN_ONE} text", {_TOKEN_ONE: "JFK"}),
        ),
        (
            f"{_TOKEN_ONE} {_TOKEN_TWO}",
            f"{_TOKEN_TWO} {_TOKEN_ONE}",
            ProtectedText(
                f"{_TOKEN_ONE} {_TOKEN_TWO}",
                {_TOKEN_ONE: "JFK", _TOKEN_TWO: "NASA"},
            ),
        ),
    ],
)
def test_placeholder_integrity_violations_are_rejected(
    raw: str,
    corrected: str,
    protected: ProtectedText,
) -> None:
    with pytest.raises(ProtectionError):
        validate_revision(raw, corrected, protected)


@pytest.mark.parametrize(
    ("raw", "corrected", "protected"),
    [
        (None, "text", _protected_text()),
        ("text", None, _protected_text()),
        ("text", "text", object()),
    ],
)
def test_invalid_argument_types_are_rejected(
    raw: object,
    corrected: object,
    protected: object,
) -> None:
    with pytest.raises(TypeError):
        validate_revision(raw, corrected, protected)  # type: ignore[arg-type]


def test_validation_does_not_mutate_protected_text_or_replacements() -> None:
    protected = _protected_text()
    original_text = protected.text
    original_replacements = dict(protected.replacements)

    validate_revision(
        f"{_TOKEN_ONE} 안녕, 세계",
        f"{_TOKEN_ONE} 안녕, 세계",
        protected,
    )

    assert protected.text == original_text
    assert protected.replacements == original_replacements


def test_long_text_moving_across_locked_token_keeps_review_coordinates() -> None:
    from backend.protection import restore_tokens

    phrase = "서킷의 코너에서 차체 움직임과 핸들링을 직접 자세하게 확인합니다"
    raw = f"{phrase} {_TOKEN_ONE} 시승"
    proposed = f"시승 {_TOKEN_ONE} {phrase}"
    protected = ProtectedText(raw, {_TOKEN_ONE: "SUV"})
    result = validate_revision(raw, proposed, protected)
    assert result.approved_text == raw
    restored = restore_tokens(protected, result.approved_text)
    assert len(result.review_spans) == len(result.review_items) > 0
    for item, span in zip(result.review_items, result.review_spans):
        assert "SODAM_PROTECTED" not in item["raw"] + item["corrected"]
        if item["raw"]:
            assert restored[span.start_offset:span.end_offset] == item["raw"]
            assert span.end_offset <= len(phrase) + 1 or span.start_offset >= len(phrase) + 4
        else:
            assert span.start_offset is span.end_offset is None


@pytest.mark.parametrize("prefix,locked", [("", "SUV"), ("안녕 ", "아주 긴 보호 표현"), ("\U0001f680 ", "\U0001f680")])
def test_review_span_selects_second_repeated_word_after_restoration(prefix, locked) -> None:
    from backend.protection import restore_tokens

    raw = f"{prefix}고장 {_TOKEN_ONE} 고장"
    corrected = f"{prefix}고장 {_TOKEN_ONE} 수리"
    protected = ProtectedText(raw, {_TOKEN_ONE: locked})
    result = validate_revision(raw, corrected, protected)
    restored = restore_tokens(protected, raw)
    span = result.review_spans[0]
    assert (span.start_offset, span.end_offset) == (len(restored) - 2, len(restored))
    assert result.review_items[0]["raw"] == "고장"
    assert result.review_items[0]["corrected"] == "수리"


@pytest.mark.parametrize("raw,corrected,replacements", [
    ("고장", "수리", {}),
    (f"{_TOKEN_ONE}{_TOKEN_TWO}고장", f"{_TOKEN_ONE}{_TOKEN_TWO}수리", {_TOKEN_ONE: "SUV", _TOKEN_TWO: "한글"}),
    (f"고장{_TOKEN_ONE}", f"{_TOKEN_ONE}", {_TOKEN_ONE: "SUV"}),
    (f"{_TOKEN_ONE}", f"추가{_TOKEN_ONE}", {_TOKEN_ONE: "SUV"}),
    (f"{_TOKEN_ONE} 끝", f"{_TOKEN_ONE} 끝 추가", {_TOKEN_ONE: "SUV"}),
])
def test_editable_span_boundary_cases(raw, corrected, replacements) -> None:
    from backend.protection import restore_tokens

    protected = ProtectedText(raw, replacements)
    result = validate_revision(raw, corrected, protected)
    assert result.approved_text == raw
    assert len(result.review_items) == len(result.review_spans) > 0
    restored = restore_tokens(protected, raw)
    for item, span in zip(result.review_items, result.review_spans):
        if item["raw"]:
            assert restored[span.start_offset:span.end_offset] == item["raw"]
        else:
            assert span.start_offset is span.end_offset is None


def test_safe_formatting_is_not_partially_applied_with_meaning_change() -> None:
    raw = f"{_TOKEN_ONE}  고장 , 끝"
    proposed = f"{_TOKEN_ONE} 수리, 끝"
    result = validate_revision(raw, proposed, ProtectedText(raw, {_TOKEN_ONE: "SUV"}))
    assert result.approved_text == raw
    assert len(result.review_spans) == len(result.review_items) > 0


def test_formatting_only_and_legacy_result_have_empty_spans() -> None:
    from backend.contracts import ReviewResult

    raw = f"{_TOKEN_ONE}  안녕 , 세계"
    proposed = f"{_TOKEN_ONE} 안녕, 세계"
    result = validate_revision(raw, proposed, ProtectedText(raw, {_TOKEN_ONE: "SUV"}))
    assert result.approved_text == proposed
    assert result.review_spans == result.review_items == ()
    assert ReviewResult("legacy").review_spans == ()


def test_gap_iterator_counts_restored_lengths_including_empty_gaps() -> None:
    from backend.validation import _iter_editable_revision_pairs, _validate_inputs

    raw = f"앞{_TOKEN_ONE}{_TOKEN_TWO}뒤"
    proposed = f"시작{_TOKEN_ONE}삽입{_TOKEN_TWO}끝"
    protected = ProtectedText(raw, {_TOKEN_ONE: "SUV", _TOKEN_TWO: "한글"})
    _validate_inputs(raw, proposed, protected)
    assert list(_iter_editable_revision_pairs(raw, proposed, protected)) == [
        ("앞", "시작", 0), ("", "삽입", 4), ("뒤", "끝", 6),
    ]
