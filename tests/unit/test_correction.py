"""Unit tests for B09 injected Qwen correction-response validation."""

import json

import pytest

from backend.contracts import (
    EditablePart,
    EditableTextPlan,
    LockedPart,
    ModelResponseError,
    RuleNormalizedText,
)
from backend.correction import (
    correct_chunk,
    correct_with_retry,
    propose_edits,
    validate_edit_proposal,
)
from tests.fakes_correction_v3 import (
    AlwaysInvalidRuntime,
    MalformedThenValidRuntime,
    TimeoutThenValidRuntime,
)


_TOKEN_ONE = "[[SODAM_PROTECTED_0001]]"
_TOKEN_TWO = "[[SODAM_PROTECTED_0002]]"


class RecordingRuntime:
    """In-memory runtime that records the one prompt passed to it."""

    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> object:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response


def _text() -> RuleNormalizedText:
    value = f"{_TOKEN_ONE} sample text."
    return RuleNormalizedText(value, (len(value),))


def _response(
    corrected_text: str,
    changes: list[dict[str, str]] | None = None,
    requires_review: bool = False,
) -> str:
    return json.dumps(
        {
            "corrected_text": corrected_text,
            "changes": [] if changes is None else changes,
            "requires_review": requires_review,
        },
        ensure_ascii=False,
    )


def test_valid_response_returns_result_and_calls_runtime_once() -> None:
    text = _text()
    context = ("earlier sentence", "second context")
    runtime = RecordingRuntime(
        _response(
            f"{_TOKEN_ONE} corrected text.",
            [{"old": "sample", "new": "corrected"}],
        )
    )

    result = correct_chunk(text, context, runtime)  # type: ignore[arg-type]

    assert result.corrected_text == f"{_TOKEN_ONE} corrected text."
    assert result.changes == ({"old": "sample", "new": "corrected"},)
    assert result.requires_review is False
    assert len(runtime.prompts) == 1
    assert text.text in runtime.prompts[0]
    assert "earlier sentence" in runtime.prompts[0]
    assert "second context" in runtime.prompts[0]


@pytest.mark.parametrize("response", ["not json", b'{"corrected_text":"text"}'])
def test_invalid_or_non_string_runtime_response_is_rejected(response: object) -> None:
    runtime = RecordingRuntime(response)
    with pytest.raises(ModelResponseError):
        correct_chunk(_text(), (), runtime)  # type: ignore[arg-type]
    assert len(runtime.prompts) == 1


def test_runtime_exception_is_wrapped_as_model_response_error() -> None:
    with pytest.raises(ModelResponseError) as raised:
        correct_chunk(_text(), (), RecordingRuntime(error=RuntimeError("offline")))  # type: ignore[arg-type]

    assert isinstance(raised.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    "corrected",
    [
        "sample text.",
        f"{_TOKEN_TWO} {_TOKEN_ONE} sample text.",
    ],
)
def test_missing_or_reordered_placeholder_is_rejected(corrected: str) -> None:
    text = RuleNormalizedText(f"{_TOKEN_ONE} {_TOKEN_TWO} sample text.", ())

    with pytest.raises(ModelResponseError):
        correct_chunk(text, (), RecordingRuntime(_response(corrected)))  # type: ignore[arg-type]


def test_duplicate_sentence_boundaries_are_rejected_before_runtime_call() -> None:
    runtime = RecordingRuntime(_response("text."))

    with pytest.raises(ValueError):
        correct_chunk(RuleNormalizedText("text.", (5, 5)), (), runtime)  # type: ignore[arg-type]

    assert runtime.prompts == []


def test_invalid_context_and_runtime_contracts_are_rejected() -> None:
    with pytest.raises(TypeError):
        correct_chunk(_text(), ["not a tuple"], RecordingRuntime(_response(_text().text)))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        correct_chunk(_text(), (), object())  # type: ignore[arg-type]


def test_inputs_are_not_mutated() -> None:
    text = _text()
    context = ("immutable context",)
    runtime = RecordingRuntime(_response(text.text))

    correct_chunk(text, context, runtime)  # type: ignore[arg-type]

    assert text == _text()
    assert context == ("immutable context",)


def test_semantically_empty_no_op_changes_are_normalized_once() -> None:
    text = _text()
    runtime = RecordingRuntime(
        _response(
            text.text,
            [
                {"old": "same", "new": "same"},
                {"old": "again", "new": "again"},
            ],
        )
    )

    assert correct_chunk(text, (), runtime).changes == ()  # type: ignore[arg-type]
    assert len(runtime.prompts) == 1


@pytest.mark.parametrize(
    ("corrected", "changes", "requires_review"),
    [
        (f"{_TOKEN_ONE} changed text.", [{"old": "same", "new": "same"}], False),
        (_text().text, [{"old": "same", "new": "same"}], True),
    ],
)
def test_unsafe_no_op_change_combinations_are_rejected_once(
    corrected: str,
    changes: list[dict[str, str]],
    requires_review: bool,
) -> None:
    runtime = RecordingRuntime(_response(corrected, changes, requires_review))

    with pytest.raises(ModelResponseError):
        correct_chunk(_text(), (), runtime)  # type: ignore[arg-type]

    assert len(runtime.prompts) == 1


def test_no_op_entries_are_removed_but_actual_change_and_review_are_preserved() -> None:
    text = _text()
    runtime = RecordingRuntime(
        _response(
            f"{_TOKEN_ONE} corrected text.",
            [
                {"old": "same", "new": "same"},
                {"old": "sample", "new": "corrected"},
            ],
            requires_review=True,
        )
    )

    result = correct_chunk(text, (), runtime)  # type: ignore[arg-type]

    assert result.changes == ({"old": "sample", "new": "corrected"},)
    assert result.requires_review is True
    assert len(runtime.prompts) == 1


def test_no_op_change_with_placeholder_loss_is_rejected_once() -> None:
    text = _text()
    runtime = RecordingRuntime(
        _response("placeholder was removed", [{"old": "same", "new": "same"}])
    )

    with pytest.raises(ModelResponseError):
        correct_chunk(text, (), runtime)  # type: ignore[arg-type]

    assert len(runtime.prompts) == 1


def _plan_group() -> tuple[EditableTextPlan, ...]:
    return (
        EditableTextPlan(
            "s1",
            (
                EditablePart("s1:editable:0000", "before "),
                LockedPart("s1:locked:0000", "JFK"),
                EditablePart("s1:editable:0001", " after"),
            ),
            "before JFK after",
        ),
    )


def _edit_response(
    editable_id: str = "s1:editable:0000",
    replacement: str = "BEFORE ",
    requires_review: bool = False,
) -> str:
    return json.dumps(
        {
            "edits": [{"editable_id": editable_id, "replacement": replacement}],
            "requires_review": requires_review,
        }
    )


def test_validate_edit_proposal_accepts_editable_ids_only() -> None:
    edits, requires_review = validate_edit_proposal(
        _plan_group(),
        _edit_response(),
    )

    assert edits[0].editable_id == "s1:editable:0000"
    assert edits[0].replacement == "BEFORE "
    assert requires_review is False


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"edits": [{"editable_id": "s1:locked:0000", "replacement": "x"}], "requires_review": False}),
        json.dumps({"edits": [{"editable_id": "unknown", "replacement": "x"}], "requires_review": False}),
        json.dumps({"edits": [{"editable_id": "s1:editable:0000", "replacement": "[[SODAM_PROTECTED_0001]]"}], "requires_review": False}),
        json.dumps({"edits": [{"editable_id": "s1:editable:0000", "replacement": "bad\ntext"}], "requires_review": False}),
        json.dumps({"edits": [{"editable_id": "s1:editable:0000", "replacement": "x"}, {"editable_id": "s1:editable:0000", "replacement": "y"}], "requires_review": False}),
        json.dumps({"edits": [], "requires_review": "false"}),
        "not json",
    ],
)
def test_validate_edit_proposal_rejects_invalid_responses(raw: str) -> None:
    with pytest.raises(ModelResponseError):
        validate_edit_proposal(_plan_group(), raw)


def test_propose_edits_calls_runtime_once_and_includes_structured_plan() -> None:
    runtime = RecordingRuntime(_edit_response())

    edits, requires_review = propose_edits(_plan_group(), ("context",), runtime)  # type: ignore[arg-type]

    assert len(runtime.prompts) == 1
    assert "s1:editable:0000" in runtime.prompts[0]
    assert "s1:locked:0000" in runtime.prompts[0]
    assert edits[0].replacement == "BEFORE "
    assert requires_review is False


def test_correct_with_retry_recovers_from_malformed_response() -> None:
    runtime = MalformedThenValidRuntime(_edit_response())

    outcome = correct_with_retry(_plan_group(), (), runtime)  # type: ignore[arg-type]

    assert outcome.text == "BEFORE JFK after"
    assert outcome.identity_applied is False
    assert [attempt.status for attempt in outcome.attempts] == ["retrying", "accepted"]
    assert len(runtime.prompts) == 2


def test_correct_with_retry_classifies_timeout_and_recovers() -> None:
    runtime = TimeoutThenValidRuntime(_edit_response())

    outcome = correct_with_retry(_plan_group(), (), runtime)  # type: ignore[arg-type]

    assert outcome.text == "BEFORE JFK after"
    assert outcome.attempts[0].reason == "timeout"
    assert outcome.identity_applied is False


def test_correct_with_retry_uses_identity_after_bounded_failures() -> None:
    runtime = AlwaysInvalidRuntime()

    outcome = correct_with_retry(_plan_group(), (), runtime, max_attempts=3)  # type: ignore[arg-type]

    assert outcome.text == "before JFK after"
    assert outcome.identity_applied is True
    assert outcome.review_reason == "correction_unapplied:invalid_response"
    assert [attempt.status for attempt in outcome.attempts] == [
        "retrying",
        "retrying",
        "identity_applied",
    ]
    assert len(runtime.prompts) == 3


@pytest.mark.parametrize(
    ("plan_group", "context", "runtime", "max_attempts", "exception"),
    [
        ([], (), AlwaysInvalidRuntime(), 3, TypeError),
        ((), (), AlwaysInvalidRuntime(), 3, ValueError),
        (_plan_group(), ["context"], AlwaysInvalidRuntime(), 3, TypeError),
        (_plan_group(), (), AlwaysInvalidRuntime(), 0, ValueError),
        (_plan_group(), (), AlwaysInvalidRuntime(), 4, ValueError),
        (_plan_group(), (), AlwaysInvalidRuntime(), True, TypeError),
    ],
)
def test_correct_with_retry_rejects_invalid_inputs(
    plan_group: object,
    context: object,
    runtime: object,
    max_attempts: object,
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        correct_with_retry(  # type: ignore[arg-type]
            plan_group,
            context,
            runtime,
            max_attempts,
        )


def test_correct_with_retry_propagates_keyboard_interrupt() -> None:
    class InterruptingRuntime:
        def complete(self, prompt: str) -> str:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        correct_with_retry(_plan_group(), (), InterruptingRuntime())  # type: ignore[arg-type]
