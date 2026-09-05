"""Unit tests for the shared structured model response normalizer."""

import pytest

from backend.contracts import ModelResponseError
from backend.model_response import NormalizedResponse, normalize_json_response


PAYLOAD = '{"text":"완료.","evidence_segment_ids":["segment-0001"]}'


def test_normalize_json_response_preserves_raw_json_and_metadata() -> None:
    assert normalize_json_response(PAYLOAD) == NormalizedResponse(PAYLOAD, False, False)
    assert normalize_json_response("  " + PAYLOAD + "\n") == NormalizedResponse(
        PAYLOAD, False, True
    )


@pytest.mark.parametrize("marker", ["```json", "```JSON"])
def test_normalize_json_response_removes_only_exact_json_fence(marker: str) -> None:
    result = normalize_json_response(f"{marker}\n{PAYLOAD}\n```")

    assert result == NormalizedResponse(PAYLOAD, True, False)


@pytest.mark.parametrize(
    ("raw", "diagnostic"),
    [
        ("", "response_empty"),
        ("   ", "response_empty"),
        ("```text\n" + PAYLOAD + "\n```", "json_parse_invalid"),
        ("```json\n" + PAYLOAD, "json_parse_invalid"),
    ],
)
def test_normalize_json_response_rejects_malformed_fences(
    raw: str, diagnostic: str
) -> None:
    with pytest.raises(ModelResponseError) as caught:
        normalize_json_response(raw)

    assert getattr(caught.value, "diagnostic_code") == diagnostic


@pytest.mark.parametrize("raw", ["Here is the JSON:\n" + PAYLOAD, PAYLOAD + "\nDone."])
def test_normalize_json_response_does_not_extract_json_from_explanations(raw: str) -> None:
    assert normalize_json_response(raw) == NormalizedResponse(raw, False, False)
