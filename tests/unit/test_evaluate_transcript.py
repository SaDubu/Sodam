"""Unit tests for the T03 reproducible evaluation CLI."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tools.evaluate_transcript import _evaluate_payload, evaluate_transcript, main


_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "evaluation_cases.json"


def test_versioned_fixture_produces_the_documented_metrics() -> None:
    report = evaluate_transcript(str(_FIXTURE))

    assert report == {
        "total_cases": 3,
        "exact_match_count": 2,
        "correction_accuracy": pytest.approx(2 / 3),
        "protected_token_preservation_count": 2,
        "protected_token_preservation_rate": pytest.approx(2 / 3),
        "risky_auto_approval_count": 1,
        "risky_auto_approval_rate": pytest.approx(1 / 3),
        "total_duration_seconds": pytest.approx(0.6),
        "average_duration_seconds": pytest.approx(0.2),
    }


def test_reordered_or_missing_protected_values_make_auto_approval_risky() -> None:
    report = _evaluate_payload(
        {
            "cases": [
                {
                    "case_id": "reordered",
                    "expected_text": "JFK JFK NASA",
                    "actual_text": "JFK NASA JFK",
                    "protected_tokens": ["JFK", "NASA"],
                    "auto_approved": True,
                    "duration_seconds": 0,
                }
            ]
        }
    )

    assert report["protected_token_preservation_count"] == 0
    assert report["risky_auto_approval_count"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"cases": []},
        {
            "cases": [
                {
                    "case_id": "same",
                    "expected_text": "a",
                    "actual_text": "a",
                    "protected_tokens": [],
                    "auto_approved": False,
                    "duration_seconds": 0,
                },
                {
                    "case_id": "same",
                    "expected_text": "b",
                    "actual_text": "b",
                    "protected_tokens": [],
                    "auto_approved": False,
                    "duration_seconds": 0,
                },
            ]
        },
        {
            "cases": [
                {
                    "case_id": "bool-duration",
                    "expected_text": "a",
                    "actual_text": "a",
                    "protected_tokens": [],
                    "auto_approved": False,
                    "duration_seconds": True,
                }
            ]
        },
        {"unexpected": []},
    ],
)
def test_invalid_fixture_schemas_are_rejected(payload: object) -> None:
    with pytest.raises(ValueError):
        _evaluate_payload(payload)


def test_cli_prints_the_same_one_line_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_transcript.py", str(_FIXTURE)])

    assert main() == 0

    printed = capsys.readouterr().out
    assert printed.endswith("\n")
    assert json.loads(printed) == evaluate_transcript(str(_FIXTURE))


def test_evaluation_does_not_modify_its_fixture() -> None:
    before = hashlib.sha256(_FIXTURE.read_bytes()).digest()

    evaluate_transcript(str(_FIXTURE))

    assert hashlib.sha256(_FIXTURE.read_bytes()).digest() == before
