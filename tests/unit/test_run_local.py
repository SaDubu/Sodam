"""Unit tests for the local CLI helpers using only injected collaborators."""

from pathlib import Path
import uuid

import pytest

from backend.contracts import (
    AudioArtifact,
    CorrectionAttempt,
    CorrectionResult,
    Job,
    JobOptions,
    ProgressEvent,
    RawSegment,
    ModelResponseError,
)
from backend.main import PipelineResult
from backend.contracts import ReviewedSegment, ReviewedTranscript, Summary
from backend.storage import JOB_WORK_ROOT, CleanupPolicy, cleanup_artifacts
import tools.run_local as run_local


def test_default_qwen_model_is_the_structured_output_runtime_target() -> None:
    assert run_local.DEFAULT_QWEN_MODEL == "qwen3.6:35b-a3b-agent-64k"


def test_cli_parser_defaults_to_legacy_summary_and_human_progress() -> None:
    args = run_local._parser().parse_args(["input.mp3"])
    assert args.output_mode == "summary"
    assert args.progress_format == "human"
    assert run_local._parser().parse_args(["input.mp3", "--output-mode", "both"]).output_mode == "both"


def test_cli_progress_sink_keeps_progress_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    event = ProgressEvent(
        "op", "job", "transcription", "전사", 0.5, 0.2, 1, 2,
        1.0, 2.0, "working", True, 1, "1970-01-01T00:00:01Z"
    )
    sink = run_local.CliProgressSink("jsonl")
    sink.emit(event)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert '"stage":"transcription"' in captured.err
    assert sink.events == (event,)


def test_resilience_report_serializes_attempts_and_progress_without_raw_details() -> None:
    job = Job("cr05-report-001", "fixture", "archived", Path("D:/jobs/cr05-report-001"), JobOptions())
    result = PipelineResult(
        job=job,
        correction_attempts=(
            (
                CorrectionAttempt(1, "retrying", "timeout"),
                CorrectionAttempt(2, "accepted"),
            ),
        ),
        identity_group_count=0,
        correction_group_count=1,
        review_required_count=2,
    )
    event = ProgressEvent(
        "op", "job", "completed", "완료", 1.0, 1.0, None, None,
        1.0, 0.0, "done", False, 3, "1970-01-01T00:00:01Z"
    )

    report = run_local._build_resilience_report(result, (event,))

    assert report["correction_group_count"] == 1
    assert report["correction_attempt_count"] == 2
    assert report["identity_group_count"] == 0
    assert report["review_required_count"] == 2
    assert report["progress_event_count"] == 1
    assert report["last_stage"] == "completed"
    assert report["terminal_status"] == "archived"
    assert report["attempts"] == [[
        {"attempt_number": 1, "status": "retrying", "reason": "timeout"},
        {"attempt_number": 2, "status": "accepted", "reason": None},
    ]]


def test_safe_error_category_never_returns_raw_exception_details() -> None:
    error = ModelResponseError("secret prompt and D:/private/transcript.txt")
    assert run_local._safe_error_category(error) == "model_response"
    message = run_local._safe_error_message("model_response", error)
    assert "secret" not in message
    assert "transcript" not in message
    assert run_local._safe_error_category(RuntimeError("raw response")) == "runtime_error"


def test_local_source_rejects_url_symlink_and_missing_paths(tmp_path: Path) -> None:
    media = tmp_path / "input.mp3"
    media.write_bytes(b"fixture")
    assert run_local._local_source(str(media)) == media.resolve()
    with pytest.raises(ValueError):
        run_local._local_source("https://example.com/input.mp3")
    with pytest.raises(ValueError):
        run_local._local_source(str(tmp_path / "missing.mp3"))


def test_smoke_report_uses_stages_and_returns_detached_json_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = "p03-test-" + uuid.uuid4().hex
    job = Job(job_id, "fixture", "queued", JOB_WORK_ROOT / job_id, JobOptions())
    source = tmp_path / "input.mp3"
    source.write_bytes(b"fixture")
    audio = AudioArtifact(job_id, tmp_path / "normalized-audio.wav")
    calls: list[str] = []

    def fake_extract(*_: object) -> AudioArtifact:
        calls.append("extract")
        return audio

    def fake_transcribe(*_: object) -> list[RawSegment]:
        calls.append("transcribe")
        return [RawSegment("segment-0001", 0.0, 1.0, "fixture")]

    def fake_correct(*_: object) -> CorrectionResult:
        calls.append("correct")
        return CorrectionResult("Runtime health check.")

    monkeypatch.setattr(run_local, "extract_audio", fake_extract)
    monkeypatch.setattr(run_local, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(run_local, "correct_chunk", fake_correct)

    report = run_local._smoke_report(job, source, object(), object(), object())  # type: ignore[arg-type]

    assert calls == ["extract", "transcribe", "correct"]
    assert report == {
        "mode": "smoke",
        "job_id": job_id,
        "segment_count": 1,
        "qwen_corrected_text": "Runtime health check.",
        "qwen_requires_review": False,
    }


def test_cli_returns_one_for_rejected_url(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_local.main(["https://example.com/audio.mp3"]) == 1
    assert "--allow-url" in capsys.readouterr().err


def test_requested_url_requires_opt_in_and_run_mode() -> None:
    source = "https://youtu.be/abc123"
    with pytest.raises(ValueError, match="--allow-url"):
        run_local._requested_source(source, allow_url=False, mode="run")
    with pytest.raises(ValueError, match="run"):
        run_local._requested_source(source, allow_url=True, mode="smoke")
    assert run_local._requested_source(source, allow_url=True, mode="run") == (source, None)


def test_run_mode_persists_completed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    job = Job("p04-cli-001", "fixture", "queued", JOB_WORK_ROOT / "p04-cli-001", JobOptions())
    raw = RawSegment("segment-0001", 0.0, 1.0, "raw")
    transcript = ReviewedTranscript((ReviewedSegment(raw, "final"),), "final")
    summary = Summary("summary.", ("segment-0001",))
    archived = Job(job.job_id, job.source, "archived", job.work_dir, job.options)
    calls: list[object] = []

    class Application:
        def run(self, supplied: Job) -> PipelineResult:
            assert supplied == job
            return PipelineResult(archived, transcript, summary, ())

    monkeypatch.setattr(run_local, "build_application", lambda **_: Application())
    monkeypatch.setattr(run_local, "persist_result", lambda *values, **kwargs: calls.append((values, kwargs)) or Path("D:/results/p04-cli-001"))

    report = run_local._run_pipeline(job, object(), object(), object(), ())  # type: ignore[arg-type]

    assert len(calls) == 1
    assert report["result_path"] == str(Path("D:/results/p04-cli-001"))
    assert report["status"] == "archived"


def test_url_run_injects_ytdlp_adapter_without_calling_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}
    raw = RawSegment("segment-0001", 0.0, 1.0, "raw")
    transcript = ReviewedTranscript((ReviewedSegment(raw, "final"),), "final")
    summary = Summary("summary.", ("segment-0001",))

    class Application:
        def run(self, job: Job, **_: object) -> PipelineResult:
            assert job.source == "https://youtu.be/abc123"
            return PipelineResult(
                Job(job.job_id, job.source, "archived", job.work_dir, job.options),
                transcript,
                summary,
                (),
            )

    def fake_build_application(**kwargs: object) -> Application:
        seen.update(kwargs)
        return Application()

    monkeypatch.setattr(run_local, "LocalFfmpegRunner", lambda: object())
    monkeypatch.setattr(run_local, "LocalFasterWhisperEngine", lambda _: object())
    monkeypatch.setattr(run_local, "LocalOllamaRuntime", lambda _: object())
    monkeypatch.setattr(run_local, "build_application", fake_build_application)
    monkeypatch.setattr(run_local, "persist_result", lambda *_, **__: Path("D:/results/url"))

    assert run_local.main(["--mode", "run", "--allow-url", "https://youtu.be/abc123"]) == 0
    assert isinstance(seen["source_adapter"], run_local.LocalYtDlpSourceAdapter)
    assert '"mode":"run"' in capsys.readouterr().out
