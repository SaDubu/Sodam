"""Unit tests for the local CLI helpers using only injected collaborators."""

import json
from dataclasses import asdict, replace
from pathlib import Path
import uuid

import pytest

from backend.contracts import (
    AudioArtifact,
    CorrectionAttempt,
    CorrectionResult,
    IntroductionError,
    Job,
    JobOptions,
    ProgressEvent,
    RawSegment,
    ModelResponseError,
    SummaryOutcome,
)
from backend.main import PipelineResult
from backend.contracts import ReviewedSegment, ReviewedTranscript, Summary
from backend.storage import JOB_WORK_ROOT, CleanupPolicy, cleanup_artifacts
import tools.run_local as run_local


def test_runner_root_is_derived_from_runner_location_not_cwd() -> None:
    assert run_local.REPOSITORY_ROOT == Path(run_local.__file__).resolve().parents[1]
    assert run_local.REPOSITORY_ROOT.joinpath("backend").is_dir()


@pytest.mark.parametrize("code,reason", [
    ("review_span_count_invalid", "항목 수"),
    ("review_span_range_invalid", "범위"),
    ("review_location_mismatch", "원문"),
])
def test_review_mapping_diagnostics_include_segment_and_safe_reason(code, reason) -> None:
    from backend.contracts import ReviewMappingError

    error = ReviewMappingError(code, "segment-0087")
    category = run_local._safe_error_category(error)
    assert category == "review_validation"
    message = run_local._safe_error_message(category, error)
    assert "단계: review_validation" in message
    assert "세그먼트: segment-0087" in message
    assert code in message
    assert reason in message


@pytest.mark.parametrize("segment_id", [None, "x" * 65, "s1\nprivate secret", "C:/private/secret", "s1\x00"])
def test_unsafe_review_segment_or_unknown_code_is_not_printed(segment_id) -> None:
    from backend.contracts import ReviewMappingError

    error = ReviewMappingError("secret unknown diagnostic", segment_id)
    error.args = ("private traceback transcript",)
    message = run_local._safe_error_message(run_local._safe_error_category(error), error)
    assert "review_validation_failed" in message
    assert "세그먼트:" not in message
    assert "private" not in message
    assert "secret" not in message
    assert "traceback" not in message


def test_review_stage_preserves_protection_type_and_generic_assembly_reason() -> None:
    from backend.contracts import ProtectionError, TranscriptAssemblyError

    for error, category, code in [
        (ProtectionError("secret tokens"), "protection", "protected_token_invalid"),
        (TranscriptAssemblyError("secret raw"), "review_validation", "transcript_assembly_invalid"),
    ]:
        error.stage = "review_validation"
        error.segment_id = "segment-0002"
        assert run_local._safe_error_category(error) == category
        message = run_local._safe_error_message(category, error)
        assert "review_validation" in message
        assert "segment-0002" in message
        assert code in message
        assert "secret" not in message
    assert run_local._safe_error_category(TranscriptAssemblyError("unrelated")) == "sodam_error"


def test_assembly_failure_without_segment_does_not_invent_one() -> None:
    from backend.contracts import TranscriptAssemblyError

    error = TranscriptAssemblyError("private")
    error.stage = "review_validation"
    message = run_local._safe_error_message(run_local._safe_error_category(error), error)
    assert "transcript_assembly_invalid" in message
    assert "세그먼트:" not in message


def test_tauri_bundle_declares_portable_backend_resources() -> None:
    config_path = Path(__file__).resolve().parents[2] / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    resources = config["bundle"]["resources"]
    assert resources == {
        "../../../backend": "backend",
        "../../../tools/run_local.py": "tools/run_local.py",
    }
    assert all(not Path(source).is_absolute() for source in resources)
    assert "targets" in config["bundle"]


def test_default_qwen_model_is_the_structured_output_runtime_target() -> None:
    assert run_local.DEFAULT_QWEN_MODEL == "qwen3.6:35b-a3b-agent-64k"


def test_cli_parser_defaults_to_legacy_summary_and_human_progress() -> None:
    args = run_local._parser().parse_args(["input.mp3"])
    assert args.output_mode == "summary"
    assert args.progress_format == "human"
    assert args.qwen_timeout_seconds == 600
    assert run_local._parser().parse_args(["input.mp3", "--output-mode", "both"]).output_mode == "both"
    assert run_local._parser().parse_args(
        ["input.mp3", "--qwen-timeout-seconds", "1"]
    ).qwen_timeout_seconds == 1


def test_cli_parser_exposes_hermes_generation_and_instruction_options() -> None:
    args = run_local._parser().parse_args(
        [
            "input.mp3",
            "--generation-backend",
            "hermes",
            "--hermes-command",
            "D:/Hermes/hermes.exe",
            "--hermes-python",
            "D:/Hermes/python.exe",
            "--hermes-root",
            "D:/Hermes/site-packages",
            "--hermes-version",
            "0.19.0",
            "--summary-instruction",
            "핵심만",
            "--introduction-instruction",
            "호기심 있게",
        ]
    )
    assert args.generation_backend == "hermes"
    assert args.hermes_command == Path("D:/Hermes/hermes.exe")
    assert args.summary_instruction == "핵심만"
    assert args.introduction_instruction == "호기심 있게"


def test_hermes_generation_runtime_runs_compatibility_before_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = tmp_path / "hermes.exe"
    python = tmp_path / "python.exe"
    root = tmp_path / "site-packages"
    (root / "agent").mkdir(parents=True)
    command.write_text("fixture", encoding="utf-8")
    python.write_text("fixture", encoding="utf-8")
    (root / "run_agent.py").write_text(
        "class AIAgent:\n    def run_conversation(self):\n        return {'final_response': ''}\n",
        encoding="utf-8",
    )
    (root / "agent" / "agent_init.py").write_text(
        "def init(enabled_toolsets=None, skip_memory=False, max_iterations=1, fallback_model=None):\n    pass\n",
        encoding="utf-8",
    )
    args = run_local._parser().parse_args(
        ["input.mp3", "--generation-backend", "hermes", "--hermes-command", str(command),
         "--hermes-python", str(python), "--hermes-root", str(root)]
    )
    monkeypatch.setattr(
        run_local, "check_hermes_compatibility",
        lambda profile: {"status": "compatible"},
    )

    runtime = run_local._build_generation_runtime(args)

    assert isinstance(runtime, run_local.LocalHermesRuntime)


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


@pytest.fixture
def review_progress_event() -> ProgressEvent:
    return ProgressEvent(
        "op", "job", "review_validation", "검토 검증", 0.0, 0.6, 0, 500,
        1.0, None, "검토 검증", True, 1, "1970-01-01T00:00:01Z",
    )


def test_human_progress_prints_first_stage_event_but_keeps_every_event(review_progress_event, capsys) -> None:
    sink = run_local.CliProgressSink()
    events = [review_progress_event] + [
        replace(review_progress_event, sequence=index + 1, stage_progress=index / 500,
                overall_progress=0.6 + 0.05 * index / 500, completed_units=index,
                eta_seconds=0.0, message="검토 항목 검증")
        for index in range(1, 501)
    ]
    events += [replace(review_progress_event, stage="summarization", overall_progress=0.65, message="요약 생성")]
    for event in events:
        sink.emit(event)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "[60.0%] review_validation: 검토 검증", "[65.0%] summarization: 요약 생성",
    ]
    assert sink.events == tuple(events)


@pytest.mark.parametrize("progress,prefix", [(0.0, "[0.0%] "), (0.1234, "[12.3%] "), (1.0, "[100.0%] "), (None, "")])
@pytest.mark.parametrize("eta", [None, 0.0, 0.2, 120.0])
def test_human_percentage_is_preserved_without_eta(review_progress_event, capsys, progress, prefix, eta) -> None:
    sink = run_local.CliProgressSink()
    sink.emit(replace(review_progress_event, overall_progress=progress, eta_seconds=eta))
    assert capsys.readouterr().err == prefix + "review_validation: 검토 검증\n"


@pytest.mark.parametrize("stage,percent,message", [
    ("completed", 1.0, "작업이 완료되었습니다"),
    ("failed", None, "작업이 실패했습니다"),
    ("cancelled", None, "작업이 취소되었습니다"),
])
def test_human_terminal_event_is_shown_once(review_progress_event, capsys, stage, percent, message) -> None:
    sink = run_local.CliProgressSink()
    sink.emit(review_progress_event)
    end = replace(review_progress_event, stage=stage, overall_progress=percent, message=message)
    sink.emit(end)
    sink.emit(end)
    lines = capsys.readouterr().err.splitlines()
    prefix = "[100.0%] " if stage == "completed" else ""
    assert lines == ["[60.0%] review_validation: 검토 검증", prefix + stage + ": " + message]
    assert len(sink.events) == 3


def test_human_dedup_is_scoped_to_operation_and_scope_and_handles_stage_reentry(review_progress_event, capsys) -> None:
    sink = run_local.CliProgressSink()
    events = (
        review_progress_event,
        replace(review_progress_event, operation_id="other"),
        replace(review_progress_event, scope="setup"),
        replace(review_progress_event, stage="summarization"),
        review_progress_event,
    )
    for event in events:
        sink.emit(event)
    assert len(capsys.readouterr().err.splitlines()) == 4
    assert sink.events == events
    other_sink = run_local.CliProgressSink()
    other_sink.emit(review_progress_event)
    assert len(capsys.readouterr().err.splitlines()) == 1


@pytest.mark.parametrize("label,expected", [("검토", "검토"), ("", "review_validation")])
def test_human_blank_message_uses_label_then_stage(review_progress_event, capsys, label, expected) -> None:
    sink = run_local.CliProgressSink()
    sink.emit(replace(review_progress_event, message="", stage_label=label))
    assert capsys.readouterr().err == "[60.0%] review_validation: " + expected + "\n"


@pytest.mark.parametrize("mode", ["human", "jsonl", "none"])
def test_progress_modes_preserve_history_and_invalid_event_has_no_side_effect(review_progress_event, capsys, mode) -> None:
    sink = run_local.CliProgressSink(mode)
    with pytest.raises(TypeError):
        sink.emit(object())
    assert sink.events == ()
    assert capsys.readouterr().err == ""
    sink.emit(review_progress_event)
    snapshot = sink.events
    sink.emit(review_progress_event)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert snapshot == (review_progress_event,)
    assert sink.events == (review_progress_event,) * 2
    if mode == "jsonl":
        assert [json.loads(line) for line in captured.err.splitlines()] == [asdict(review_progress_event)] * 2
    else:
        assert len(captured.err.splitlines()) == (1 if mode == "human" else 0)


def test_progress_sink_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        run_local.CliProgressSink("unknown")


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


def test_resilience_report_marks_summary_fallback_without_raw_details() -> None:
    job = Job("p12-fallback-001", "fixture", "archived", Path("D:/jobs/p12-fallback-001"), JobOptions())
    summary = Summary("검토가 필요한 요약.", ("segment-0001",))
    result = PipelineResult(
        job=job,
        summary_outcome=SummaryOutcome(
            summary, "fallback", "final_failed", 5, "reduce"
        ),
    )

    report = run_local._build_resilience_report(result, ())

    assert report["summary_status"] == "fallback"
    assert report["summary_failure_category"] == "final_failed"
    assert report["summary_fallback_source"] == "reduce"
    assert report["summary_attempt_count"] == 5
    assert report["summary_evidence_segment_ids"] == ["segment-0001"]


def test_safe_error_category_never_returns_raw_exception_details() -> None:
    error = ModelResponseError("secret prompt and D:/private/transcript.txt")
    assert run_local._safe_error_category(error) == "model_response"
    message = run_local._safe_error_message("model_response", error)
    assert "secret" not in message
    assert "transcript" not in message
    assert run_local._safe_error_category(RuntimeError("raw response")) == "runtime_error"


def test_safe_error_category_exposes_introduction_contract_failure_as_model_response() -> None:
    error = IntroductionError("body must contain exactly one question")
    error.diagnostic_code = "retry_exhausted"
    error.diagnostic_detail = "question_invalid"

    assert run_local._safe_error_category(error) == "model_response"
    message = run_local._safe_error_message("model_response", error)
    assert "진단: retry_exhausted" in message
    assert "원인: question_invalid" in message


def test_safe_diagnostic_code_allowlist_never_exposes_raw_details() -> None:
    error = ModelResponseError("secret prompt and transcript")
    error.diagnostic_code = "question_invalid"
    assert run_local._safe_diagnostic_code(error) == "question_invalid"
    message = run_local._safe_error_message("model_response", error)
    assert "question_invalid" in message
    assert "secret" not in message
    assert "transcript" not in message

    error.diagnostic_code = "secret raw response"
    assert run_local._safe_diagnostic_code(error) == "runtime_unavailable"
    assert "secret" not in run_local._safe_error_message("model_response", error)


def test_safe_error_message_includes_bounded_summary_attempt_metadata() -> None:
    error = ModelResponseError("secret prompt and transcript")
    error.diagnostic_code = "json_parse_invalid"
    error.attempt_count = 3
    error.response_empty = False

    message = run_local._safe_error_message("model_response", error)

    assert "진단: json_parse_invalid" in message
    assert "시도: 3" in message
    assert "response_empty=false" in message
    assert "secret" not in message


def test_safe_error_message_includes_allowlisted_diagnostic_detail() -> None:
    error = ModelResponseError("secret prompt and transcript")
    error.diagnostic_code = "retry_exhausted"
    error.diagnostic_detail = "json_parse_invalid"

    message = run_local._safe_error_message("model_response", error)

    assert "진단: retry_exhausted" in message
    assert "원인: json_parse_invalid" in message
    assert "secret" not in message


def test_safe_error_message_exposes_only_bounded_review_candidate() -> None:
    error = ModelResponseError("secret prompt and transcript path")
    error.diagnostic_code = "retry_exhausted"
    error.generated_text = "A380의 숨은 매력을 확인해 보세요."

    message = run_local._safe_error_message("model_response", error)

    assert "SODAM_GENERATED_TEXT:" in message
    assert "A380의 숨은 매력을 확인해 보세요." in message
    assert "secret" not in message
    assert "transcript path" not in message


def test_cli_reports_each_failed_candidate_and_all_validation_reasons(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.introduction import generate_video_introduction
    from tests.fakes_productization import RecordingIntroductionRuntime

    source = RawSegment("s1", 0.0, 1.0, "A380 좌석 시승")
    reviewed = ReviewedTranscript((ReviewedSegment(source, source.raw_text),), source.raw_text)
    bodies = [
        f"A380의 {number}번째 후보입니다. 좌석을 비교합니다. 서비스를 살펴봅니다. 영상에서 확인하세요."
        for number in (1, 2, 3)
    ]
    responses = tuple(json.dumps({
        "title_hook": "A380", "body": body, "highlights": ["A380"],
        "evidence_segment_ids": ["s1"], "question_used": False,
        "call_to_action": "영상에서 확인하세요.",
    }, ensure_ascii=False) for body in bodies)
    runtime = RecordingIntroductionRuntime(responses)

    def failing_pipeline(*args: object) -> None:
        generate_video_introduction(reviewed, runtime)

    monkeypatch.setattr(run_local, "_run_pipeline", failing_pipeline)
    monkeypatch.setattr(run_local, "_requested_source", lambda *args, **kwargs: ("fixture", None))
    monkeypatch.setattr(run_local, "create_job", lambda *args: object())
    monkeypatch.setattr(run_local, "_build_generation_runtime", lambda *args: object())
    for name in ("LocalFfmpegRunner", "LocalFasterWhisperEngine", "LocalOllamaRuntime", "LocalYtDlpSourceAdapter"):
        monkeypatch.setattr(run_local, name, lambda *args, **kwargs: object())

    assert run_local.main(["fixture", "--mode", "run", "--output-mode", "introduction"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert runtime.call_count == 3
    assert "진단: retry_exhausted" in captured.err
    assert "원인: sentence_count_invalid" in captured.err
    assert "시도: 3" in captured.err
    for number, body in enumerate(bodies, start=1):
        assert f"{number}회차 실패" in captured.err
        assert body in captured.err
    assert captured.err.count("현재 4문장") == 3
    assert captured.err.count("현재 0개") == 3
    assert "SODAM_GENERATED_TEXT:" in captured.err
    assert "Traceback" not in captured.err


def test_cli_keeps_runtime_failure_separate_from_earlier_candidate() -> None:
    from backend.introduction import generate_video_introduction

    source = RawSegment("s1", 0.0, 1.0, "A380 시승")
    reviewed = ReviewedTranscript((ReviewedSegment(source, source.raw_text),), source.raw_text)

    class Runtime:
        calls = 0

        def complete(self, prompt: str) -> str:
            self.calls += 1
            if self.calls == 1:
                return "형식이 잘못된 첫 응답"
            error = ModelResponseError("secret prompt and D:/private/traceback.txt")
            error.diagnostic_code = "runtime_timeout"
            raise error

    with pytest.raises(ModelResponseError) as caught:
        generate_video_introduction(reviewed, Runtime())
    message = run_local._safe_error_message("model_response", caught.value)
    assert "1회차 실패 (json_parse_invalid)" in message
    assert "2회차 실패 (runtime_timeout)" in message
    assert "3회차 실패 (runtime_timeout)" in message
    assert "아래 검토용 후보는 1회차 응답" in message
    assert "응답 시간이 초과" in message
    assert message.count("표시 가능한 생성 내용이 없습니다") == 2
    assert "secret" not in message
    assert "D:/private" not in message


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
    def fake_runtime(*args: object, **kwargs: object) -> object:
        seen["qwen_runtime_args"] = args
        seen["qwen_runtime_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(run_local, "LocalOllamaRuntime", fake_runtime)
    monkeypatch.setattr(run_local, "build_application", fake_build_application)
    monkeypatch.setattr(run_local, "persist_result", lambda *_, **__: Path("D:/results/url"))

    assert run_local.main(
        [
            "--mode",
            "run",
            "--allow-url",
            "--qwen-timeout-seconds",
            "1",
            "https://youtu.be/abc123",
        ]
    ) == 0
    assert isinstance(seen["source_adapter"], run_local.LocalYtDlpSourceAdapter)
    assert seen["qwen_runtime_kwargs"] == {"timeout_seconds": 1}
    assert '"mode":"run"' in capsys.readouterr().out
