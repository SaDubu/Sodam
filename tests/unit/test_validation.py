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
