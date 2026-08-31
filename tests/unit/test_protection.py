"""Unit tests for B07 reversible token protection and restoration."""

import pytest

from backend.contracts import ProtectedText, ProtectionError, RawSegment
from backend.protection import protect_tokens, restore_tokens


_TOKEN_ONE = "[[SODAM_PROTECTED_0001]]"


def _segment(text: str) -> RawSegment:
    return RawSegment("s1", 0.0, 1.0, text)


def test_protects_glossary_and_automatic_token_types_then_restores_exactly() -> None:
    text = "OpenAI JFK https://example.com/a?x=1 2026-08-27 $1,200 3000원 1,200 3000"
    segments = [_segment(text)]
    glossary = ("OpenAI",)

    protected = protect_tokens(segments, glossary)

    for original in ("OpenAI", "JFK", "https://example.com/a?x=1", "2026-08-27", "$1,200", "3000원", "1,200", "3000"):
        assert original not in protected.text
    assert restore_tokens(protected, protected.text) == text
    assert segments[0].raw_text == text
    assert glossary == ("OpenAI",)


def test_repeated_original_values_receive_independent_placeholders() -> None:
    protected = protect_tokens([_segment("JFK JFK")], ())

    assert len(protected.replacements) == 2
    assert tuple(protected.replacements.values()) == ("JFK", "JFK")
    assert restore_tokens(protected, protected.text) == "JFK JFK"


def test_existing_placeholder_input_is_reprotected_without_key_collision() -> None:
    text = f"before {_TOKEN_ONE} after"
    glossary = ("OpenAI",)

    protected = protect_tokens([_segment(text)], glossary)

    assert _TOKEN_ONE not in protected.text
    assert tuple(protected.replacements.values()) == (_TOKEN_ONE,)
    assert all(key not in text and key not in glossary[0] for key in protected.replacements)
    assert restore_tokens(protected, protected.text) == text


@pytest.mark.parametrize(
    ("glossary", "exception"),
    [
        (["OpenAI"], TypeError),
        ((123,), TypeError),
        ((" OpenAI",), ProtectionError),
        (("OpenAI", "OpenAI"), ProtectionError),
    ],
)
def test_invalid_glossary_is_rejected(glossary: object, exception: type[Exception]) -> None:
    with pytest.raises(exception):
        protect_tokens([_segment("text")], glossary)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("protected", "text", "exception"),
    [
        (ProtectedText(_TOKEN_ONE, {_TOKEN_ONE: "JFK"}), "text", ProtectionError),
        (ProtectedText(_TOKEN_ONE, {_TOKEN_ONE: "JFK"}), "[[SODAM_PROTECTED_9999]]", ProtectionError),
        (ProtectedText(_TOKEN_ONE, {_TOKEN_ONE: "JFK"}), f"{_TOKEN_ONE} {_TOKEN_ONE}", ProtectionError),
        (object(), _TOKEN_ONE, TypeError),
        (ProtectedText(_TOKEN_ONE, {_TOKEN_ONE: "JFK"}), None, TypeError),
    ],
)
def test_restore_rejects_invalid_placeholder_integrity(
    protected: object,
    text: object,
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        restore_tokens(protected, text)  # type: ignore[arg-type]


def test_restore_does_not_mutate_replacement_mapping() -> None:
    protected = protect_tokens([_segment("JFK")], ())
    original_replacements = dict(protected.replacements)

    restore_tokens(protected, protected.text)

    assert protected.replacements == original_replacements
