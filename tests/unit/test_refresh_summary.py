"""CLI tests for explicit resolved-summary refresh without a live model."""

import json

from backend.contracts import Summary
from tools import refresh_summary


def test_refresh_cli_emits_one_json_summary(monkeypatch, capsys) -> None:
    class Runtime:
        pass

    monkeypatch.setattr(refresh_summary, "LocalOllamaRuntime", lambda *args, **kwargs: Runtime())
    monkeypatch.setattr(
        refresh_summary,
        "refresh_resolved_summary",
        lambda *args, **kwargs: Summary("Refreshed.", ("segment-0001",)),
    )

    assert refresh_summary.main(["job-001"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "text": "Refreshed.", "evidence_segment_ids": ["segment-0001"]
    }


def test_refresh_cli_reports_local_validation_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(refresh_summary, "LocalOllamaRuntime", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad runtime")))

    assert refresh_summary.main(["job-001"]) == 1
    assert "bad runtime" in capsys.readouterr().err
