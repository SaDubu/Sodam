"""CLI tests for explicit immutable persisted-review decisions."""

import json
from pathlib import Path

from backend.persistence import persist_result
from tests.unit.test_persistence import _result
from tools import resolve_review


def _root(tmp_path: Path) -> tuple[Path, str]:
    job, transcript, summary, review = _result()
    root = tmp_path / "results"
    persist_result(job, transcript, summary, review, root)
    return root, job.job_id


def test_cli_records_one_decision_as_json(tmp_path: Path, capsys) -> None:
    root, job_id = _root(tmp_path)

    assert resolve_review.main([
        job_id, "0", "--decision", "accept_suggested", "--result-root", str(root)
    ]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "review_index": 0,
        "decision": "accept_suggested",
        "resolved_text": "Reviewed",
        "applied_to_transcript": False,
        "summary_is_stale": False,
    }


def test_cli_rejects_missing_custom_text(tmp_path: Path, capsys) -> None:
    root, job_id = _root(tmp_path)

    assert resolve_review.main([
        job_id, "0", "--decision", "custom_text", "--result-root", str(root)
    ]) == 1

    assert "--text is required" in capsys.readouterr().err
