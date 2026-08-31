"""Unit tests for B07 reversible token protection and restoration."""

import pytest

from backend.contracts import (
    EditablePart,
    EditableTextPlan,
    LockedPart,
    ProtectedText,
    ProtectionError,
    RawSegment,
)
from backend.protection import (
    protect_tokens,
    reassemble_locked_parts,
    restore_tokens,
    split_locked_parts,
)


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


def test_split_and_reassemble_preserve_order_and_locked_values() -> None:
    original = "앞 JFK 중 OpenAI 뒤 2026-08-27"
    protected = protect_tokens([_segment(original)], ("OpenAI",))

    plan = split_locked_parts(protected, "s1")

    assert isinstance(plan, EditableTextPlan)
    assert "".join(part.text for part in plan.parts) == original
    assert [part.part_id for part in plan.parts] == [
        "s1:editable:0000",
        "s1:locked:0000",
        "s1:editable:0001",
        "s1:locked:0001",
        "s1:editable:0002",
        "s1:locked:0002",
        "s1:editable:0003",
    ]
    assert [part.text for part in plan.parts if isinstance(part, LockedPart)] == [
        "JFK",
        "OpenAI",
        "2026-08-27",
    ]
    assert reassemble_locked_parts(plan) == original


def test_split_without_placeholder_and_empty_text_have_editable_part() -> None:
    plain = ProtectedText("plain text", {})
    empty = ProtectedText("", {})

    plain_plan = split_locked_parts(plain, "plain")
    empty_plan = split_locked_parts(empty, "empty")

    assert plain_plan.parts == (EditablePart("plain:editable:0000", "plain text"),)
    assert empty_plan.parts == (EditablePart("empty:editable:0000", ""),)
    assert reassemble_locked_parts(plain_plan) == "plain text"
    assert reassemble_locked_parts(empty_plan) == ""


def test_repeated_locked_values_keep_independent_part_ids() -> None:
    protected = protect_tokens([_segment("JFK JFK")], ())

    plan = split_locked_parts(protected, "repeat")
    locked = [part for part in plan.parts if isinstance(part, LockedPart)]

    assert [part.text for part in locked] == ["JFK", "JFK"]
    assert [part.part_id for part in locked] == [
        "repeat:locked:0000",
        "repeat:locked:0001",
    ]
    assert reassemble_locked_parts(plan) == "JFK JFK"


def test_editable_replacement_does_not_change_locked_parts() -> None:
    protected = protect_tokens([_segment("before JFK after")], ())
    plan = split_locked_parts(protected, "s1")

    result = reassemble_locked_parts(
        plan,
        {"s1:editable:0000": "BEFORE ", "s1:editable:0001": " AFTER"},
    )

    assert result == "BEFORE JFK AFTER"
    assert "JFK" in result


@pytest.mark.parametrize(
    ("protected", "segment_id", "exception"),
    [
        (object(), "s1", TypeError),
        (ProtectedText("text", {}), 1, TypeError),
        (ProtectedText("text", {}), "", ValueError),
        (ProtectedText("text", {}), " s1", ValueError),
        (ProtectedText("[[SODAM_PROTECTED_0001]]", {}), "s1", ProtectionError),
        (ProtectedText("[[SODAM_PROTECTED_0001]]", {"invalid": "x"}), "s1", ProtectionError),
    ],
)
def test_split_rejects_invalid_inputs(
    protected: object,
    segment_id: object,
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        split_locked_parts(protected, segment_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("replacements", "exception"),
    [
        ([], TypeError),
        ({"s1:locked:0000": "changed"}, ProtectionError),
        ({"unknown": "changed"}, ProtectionError),
        ({"s1:editable:0000": 1}, TypeError),
    ],
)
def test_reassemble_rejects_invalid_replacements(
    replacements: object,
    exception: type[Exception],
) -> None:
    plan = split_locked_parts(
        protect_tokens([_segment("before JFK after")], ()),
        "s1",
    )

    with pytest.raises(exception):
        reassemble_locked_parts(plan, replacements)  # type: ignore[arg-type]


def test_split_and_reassemble_do_not_mutate_protected_text() -> None:
    protected = protect_tokens([_segment("JFK OpenAI")], ("OpenAI",))
    original_text = protected.text
    original_map = dict(protected.replacements)

    plan = split_locked_parts(protected, "s1")
    reassemble_locked_parts(plan)

    assert protected.text == original_text
    assert protected.replacements == original_map
