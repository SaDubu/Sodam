"""P13-05 stored-transcript comparison tool tests."""

import hashlib
import json
from pathlib import Path

import pytest

from backend.contracts import Job, JobOptions, RawSegment, ReviewedSegment, ReviewedTranscript, Summary
from backend.persistence import persist_result
import tools.evaluate_generation as evaluation


def stored_result(tmp_path: Path) -> Path:
    raw = RawSegment("segment-0001", 0.0, 1.0, "Reviewed source line.")
    transcript = ReviewedTranscript((ReviewedSegment(raw, raw.raw_text),), raw.raw_text)
    job = Job("p13-eval-001", "C:/media/input.mp3", "archived", tmp_path / "ignored", JobOptions())
    return persist_result(
        job,
        transcript,
        Summary("Existing summary.", ("segment-0001",)),
        (),
        tmp_path / "results",
    )


class FakeRuntime:
    def __init__(self, label: str) -> None:
        self.label = label
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"text": self.label + " summary.", "evidence_segment_ids": ["segment-0001"]})


def test_dry_run_reads_no_runtime_and_writes_no_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result_path = stored_result(tmp_path)
    before = (result_path / "transcript.json").read_bytes()
    report_path = tmp_path / "dry-run-report.json"

    assert evaluation.main(["--result-path", str(result_path), "--dry-run", "--report-path", str(report_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert not report_path.exists()
    assert (result_path / "transcript.json").read_bytes() == before


def test_compare_uses_one_canonical_transcript_for_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result_path = stored_result(tmp_path)
    report_path = tmp_path / "compare.json"
    source_before = {
        path.name: path.read_bytes()
        for path in result_path.iterdir()
        if path.is_file()
    }
    direct = FakeRuntime("direct")
    hermes = FakeRuntime("hermes")
    monkeypatch.setattr(evaluation, "LocalOllamaRuntime", lambda *args, **kwargs: direct)
    monkeypatch.setattr(evaluation, "LocalHermesRuntime", lambda profile: hermes)
    monkeypatch.setattr(evaluation, "check_hermes_compatibility", lambda profile: {"status": "compatible"})
    command = tmp_path / "hermes.exe"
    python = tmp_path / "python.exe"
    root = tmp_path / "hermes-root"
    command.write_text("fixture", encoding="utf-8")
    python.write_text("fixture", encoding="utf-8")
    root.mkdir()

    assert evaluation.main(
        [
            "--result-path", str(result_path), "--compare", "--report-path", str(report_path),
            "--summary-instruction", "간결하게", "--hermes-command", str(command),
            "--hermes-python", str(python), "--hermes-root", str(root),
        ]
    ) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report["backends"]) == {"direct", "hermes"}
    assert report["backends"]["direct"]["status"] == "completed"
    assert report["backends"]["hermes"]["status"] == "completed"
    assert report["backends"]["direct"]["call_count"] == 1
    assert report["backends"]["hermes"]["call_count"] == 1
    assert report["human_quality"] is None
    assert report["instruction_sha256"]["summary"] == hashlib.sha256("간결하게".encode()).hexdigest()
    assert source_before == {
        path.name: path.read_bytes()
        for path in result_path.iterdir()
        if path.is_file()
    }
    assert '"mode":"compare"' in capsys.readouterr().out


def test_one_backend_failure_does_not_stop_the_other() -> None:
    class Stored:
        job_id = "job"
        source = "source"
        transcript = ReviewedTranscript(
            (ReviewedSegment(RawSegment("segment-0001", 0.0, 1.0, "line"), "line"),),
            "line",
        )
        resolved_transcript = None

    created: list[str] = []

    def factory(backend: str) -> object:
        created.append(backend)
        if backend == "hermes":
            raise RuntimeError("secret prompt")
        return FakeRuntime("direct")

    direct = evaluation._run_backend(
        Stored(), "direct", output_mode="summary", summary_instruction=None,
        introduction_instruction=None, runtime_factory=factory,
    )
    failed = evaluation._run_backend(
        Stored(), "hermes", output_mode="summary", summary_instruction=None,
        introduction_instruction=None, runtime_factory=factory,
    )
    assert direct["status"] == "completed"
    assert failed["status"] == "failed"
    assert failed["call_count"] == 0
    assert created == ["direct", "hermes"]
