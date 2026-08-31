"""Unit tests for B09 injected Qwen correction-response validation."""

import json

import pytest

from backend.contracts import ModelResponseError, RuleNormalizedText
from backend.correction import correct_chunk


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
    with pytest.raises(ModelResponseError):
        correct_chunk(_text(), (), RecordingRuntime(response))  # type: ignore[arg-type]


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
