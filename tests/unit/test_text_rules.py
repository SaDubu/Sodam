"""Unit tests for B08 restricted rules-only normalization."""

import pytest

from backend.contracts import NormalizationError, ProtectedText
from backend.text_rules import normalize_rules


_TOKEN = "[[SODAM_PROTECTED_0001]]"


def test_applies_only_the_four_spacing_rules_and_preserves_placeholder() -> None:
    protected = ProtectedText(
        f" \t{_TOKEN}  안녕  ,  ( 세계 ) [ 테스트 ] {{ 끝 }}  !  ",
        {_TOKEN: "JFK"},
    )

    normalized = normalize_rules(protected)

    assert normalized.text == f"{_TOKEN} 안녕, (세계) [테스트] {{끝}}!"
    assert normalized.text.count(_TOKEN) == 1
    assert "".join(ch for ch in normalized.text if not ch.isspace()) == "".join(
        ch for ch in protected.text if not ch.isspace()
    )


def test_reports_terminal_sentence_boundaries_as_slice_end_indexes() -> None:
    protected = ProtectedText(
        f"{_TOKEN} 첫째 . 둘째! 셋째 ?",
        {_TOKEN: "JFK"},
    )

    normalized = normalize_rules(protected)

    assert normalized.text == f"{_TOKEN} 첫째. 둘째! 셋째?"
    assert normalized.sentence_boundaries == (
        normalized.text.index(".") + 1,
        normalized.text.index("!") + 1,
        normalized.text.index("?") + 1,
    )


@pytest.mark.parametrize(
    "protected",
    [
        object(),
        ProtectedText("text", {"not-a-placeholder": "value"}),
        ProtectedText(_TOKEN, {_TOKEN: 123}),
        ProtectedText("text", {_TOKEN: "JFK"}),
        ProtectedText(f"{_TOKEN} {_TOKEN}", {_TOKEN: "JFK"}),
        ProtectedText("[[SODAM_PROTECTED_9999]]", {_TOKEN: "JFK"}),
    ],
)
def test_rejects_invalid_protected_text_contract(protected: object) -> None:
    exception = TypeError if not isinstance(protected, ProtectedText) else NormalizationError

    with pytest.raises(exception):
        normalize_rules(protected)  # type: ignore[arg-type]


def test_normalization_does_not_mutate_input_or_replacements() -> None:
    protected = ProtectedText(f"{_TOKEN}  text", {_TOKEN: "JFK"})
    original_text = protected.text
    original_replacements = dict(protected.replacements)

    normalize_rules(protected)

    assert protected.text == original_text
    assert protected.replacements == original_replacements
