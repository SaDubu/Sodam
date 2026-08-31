"""Unit tests for the T04 read-only job-inspection CLI."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from tools.inspect_job import _build_report, inspect_job, main


_ROOT = Path(__file__).resolve().parents[2]
_JOB_DIR = _ROOT / "tests" / "fixtures" / "inspection_job"


def _payloads() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    names = ("metadata.json", "transcript.json", "review.json", "summary.json")
    values = tuple(json.loads((_JOB_DIR / name).read_text(encoding="utf-8")) for name in names)
    return values  # type: ignore[return-value]


def test_versioned_job_fixture_returns_metadata_timeline_review_and_evidence() -> None:
    report = inspect_job(str(_JOB_DIR))

    assert report["job_id"] == "fixture-job-001"
    assert report["status"] == "archived"
    assert report["source"] == "fixture://inspection"
    assert report["segment_count"] == 2
    assert report["timeline"] == [
        {
            "segment_id": "segment-0001",
            "start_seconds": 0.0,
            "end_seconds": 1.25,
            "text": "First fixture line.",
        },
        {
            "segment_id": "segment-0002",
            "start_seconds": 1.25,
            "end_seconds": 2.5,
            "text": "Second fixture line.",
        },
    ]
    assert report["review_item_count"] == 1
    assert report["review_items"] == [
        {
            "kind": "review_required",
            "raw": "teh",
            "corrected": "the",
            "reason": "non_formatting_change",
        }
    ]
    assert report["summary_text"] == "The fixture contains two ordered lines."
    assert report["summary_evidence_segment_ids"] == ["segment-0001", "segment-0002"]


@pytest.mark.parametrize("kind", ["backward", "bad_final_text", "unknown_evidence", "bad_review"])
def test_invalid_decoded_artifacts_are_rejected(kind: str) -> None:
    metadata, transcript, review, summary = _payloads()
    if kind == "backward":
        transcript["segments"][1]["start_seconds"] = 0.5  # type: ignore[index]
        transcript["segments"][1]["end_seconds"] = 1.0  # type: ignore[index]
    elif kind == "bad_final_text":
        transcript["final_text"] = "mismatch"
    elif kind == "unknown_evidence":
        summary["evidence_segment_ids"] = ["unknown"]
    else:
        review["review_items"] = [{"kind": "missing keys"}]

    with pytest.raises(ValueError):
        _build_report(metadata, transcript, review, summary)


def test_cli_prints_same_one_line_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["inspect_job.py", str(_JOB_DIR)])

    assert main() == 0

    output = capsys.readouterr().out
    assert output.endswith("\n")
    assert json.loads(output) == inspect_job(str(_JOB_DIR))


def test_inspection_is_read_only_for_every_fixture_artifact() -> None:
    paths = sorted(_JOB_DIR.glob("*.json"))
    before = {path.name: hashlib.sha256(path.read_bytes()).digest() for path in paths}

    inspect_job(str(_JOB_DIR))

    assert {path.name: hashlib.sha256(path.read_bytes()).digest() for path in paths} == before


def test_schema_v1_format_is_accepted_but_unknown_version_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "persisted"
    shutil.copytree(_JOB_DIR, copied)
    (copied / "format.json").write_text('{"schema_version":1}', encoding="utf-8")

    assert inspect_job(str(copied))["job_id"] == "fixture-job-001"

    (copied / "format.json").write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_job(str(copied))


def test_inspector_reports_valid_optional_review_decision(tmp_path: Path) -> None:
    copied = tmp_path / "persisted"
    shutil.copytree(_JOB_DIR, copied)
    (copied / "review_resolution.json").write_text(
        '{"schema_version":1,"decisions":[{"review_index":0,"decision":"accept_suggested","resolved_text":"the"}]}',
        encoding="utf-8",
    )
    resolved_text = "First! fixture line.\nSecond fixture line."
    (copied / "resolved_summary.json").write_text(
        '{"schema_version":1,"transcript_sha256":"%s","summary":{"text":"Resolved summary.","evidence_segment_ids":["segment-0001"]}}'
        % hashlib.sha256(resolved_text.encode("utf-8")).hexdigest(),
        encoding="utf-8",
    )

    report = inspect_job(str(copied))

    assert report["pending_review_item_count"] == 0
    assert report["review_decisions"] == [
        {"review_index": 0, "decision": "accept_suggested", "resolved_text": "the"}
    ]


def test_inspector_reports_valid_review_locations(tmp_path: Path) -> None:
    copied = tmp_path / "persisted"
    shutil.copytree(_JOB_DIR, copied)
    (copied / "review.json").write_text(
        '{"review_items":[{"kind":"review_required","raw":"First","corrected":"First!","reason":"fixture"}]}',
        encoding="utf-8",
    )
    (copied / "review_locations.json").write_text(
        '{"schema_version":1,"locations":[{"review_index":0,"segment_id":"segment-0001","start_offset":0,"end_offset":5}]}',
        encoding="utf-8",
    )
    (copied / "review_resolution.json").write_text(
        '{"schema_version":1,"decisions":[{"review_index":0,"decision":"accept_suggested","resolved_text":"First!"}]}',
        encoding="utf-8",
    )
    resolved_text = "First! fixture line.\nSecond fixture line."
    (copied / "resolved_summary.json").write_text(
        '{"schema_version":1,"transcript_sha256":"%s","summary":{"text":"Resolved summary.","evidence_segment_ids":["segment-0001"]}}'
        % hashlib.sha256(resolved_text.encode("utf-8")).hexdigest(),
        encoding="utf-8",
    )

    report = inspect_job(str(copied))
    assert report["review_locations"] == [
        {"review_index": 0, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 5}
    ]
    assert report["resolved_final_text"].startswith("First! fixture line.")
    assert report["applied_review_indices"] == [0]
    assert report["summary_is_stale"] is False
    assert report["resolved_summary_text"] == "Resolved summary."
