"""Run the installed local Sodam collaborators against one local media file."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit


def _resolve_runner_root() -> Path:
    """Return the resource/repository root containing the backend package."""
    root = Path(__file__).resolve().parents[1]
    if not root.joinpath("backend").is_dir():
        raise ImportError("run_local.py resource is missing its backend package")
    return root


REPOSITORY_ROOT = _resolve_runner_root()
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.contracts import (
    CleanupPolicy,
    IntroductionError,
    InputSourceError,
    Job,
    JobOptions,
    MediaExtractionError,
    ModelResponseError,
    ProgressEvent,
    ProtectionError,
    ReviewMappingError,
    RuleNormalizedText,
    SodamError,
    StorageError,
    SummaryOutcome,
    TranscriptionError,
    TranscriptAssemblyError,
    UnsafePathError,
)
from backend.correction import correct_chunk
from backend.jobs import create_job
from backend.local_adapters import (
    LocalFasterWhisperEngine,
    LocalFfmpegRunner,
    LocalOllamaRuntime,
    LocalYtDlpSourceAdapter,
    DEFAULT_QWEN_MODEL,
    MAX_QWEN_TIMEOUT_SECONDS,
    RejectingUrlSourceAdapter,
)
from backend.main import build_application
from backend.main import PipelineResult
from backend.hermes_runtime import (
    HERMES_DIAGNOSTIC_CODES,
    HermesExecutionProfile,
    LocalHermesRuntime,
    check_hermes_compatibility,
)
from backend.media import extract_audio
from backend.introduction import (
    INTRODUCTION_DIAGNOSTIC_CODES,
    MAX_INTRODUCTION_ATTEMPTS,
    IntroductionAttemptFailure,
    IntroductionValidationIssue,
    _safe_generated_text,
)
from backend.summarization import SUMMARY_DIAGNOSTIC_CODES
from backend.persistence import persist_result
from backend.sources import validate_source
from backend.storage import cleanup_artifacts
from backend.transcription import transcribe_audio


from backend.runtime_paths import STT_MODEL_PATH as DEFAULT_MODEL_PATH
_SAFE_ATTEMPT_REASONS = frozenset(
    {"invalid_response", "timeout", "runtime_error", "correction_unapplied"}
)
_REVIEW_FAILURE_MESSAGES = {
    "review_span_count_invalid": "검토 항목 수와 위치 정보 수가 일치하지 않습니다.",
    "review_span_range_invalid": "검토 위치가 원문 범위를 벗어나거나 서로 겹칩니다.",
    "review_location_mismatch": "검토 위치의 원문이 검토 항목과 일치하지 않습니다.",
}


class CliProgressSink:
    """Render validated ProgressEvent values to stderr without contaminating stdout."""

    def __init__(self, output_format: str = "human") -> None:
        if output_format not in {"human", "jsonl", "none"}:
            raise ValueError("progress format must be human, jsonl, or none")
        self.output_format = output_format
        self._events: list[ProgressEvent] = []
        self._displayed_stages: set[tuple[str, str, str]] = set()

    def emit(self, event: ProgressEvent) -> None:
        if not isinstance(event, ProgressEvent):
            raise TypeError("event must be a ProgressEvent")
        self._events.append(event)
        if self.output_format == "none":
            return
        if self.output_format == "jsonl":
            print(json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
            return
        key = (event.operation_id, event.scope, event.stage)
        if key in self._displayed_stages:
            return
        prefix = "" if event.overall_progress is None else f"[{event.overall_progress * 100:.1f}%] "
        message = event.message or event.stage_label or event.stage
        print(f"{prefix}{event.stage}: {message}", file=sys.stderr)
        self._displayed_stages.add(key)

    @property
    def events(self) -> tuple[ProgressEvent, ...]:
        return tuple(self._events)


def _safe_error_category(error: BaseException) -> str:
    """Map any failure to a stable category without exposing its details."""
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    if isinstance(error, SystemExit):
        return "system_exit"
    if isinstance(error, (InputSourceError, UnsafePathError)):
        return "input_source"
    if isinstance(error, MediaExtractionError):
        return "media_extraction"
    if isinstance(error, TranscriptionError):
        return "transcription"
    if isinstance(error, (ModelResponseError, IntroductionError)):
        return "model_response"
    if isinstance(error, ReviewMappingError) or (
        isinstance(error, TranscriptAssemblyError)
        and getattr(error, "stage", None) == "review_validation"
    ):
        return "review_validation"
    if isinstance(error, ProtectionError):
        return "protection"
    if isinstance(error, StorageError):
        return "storage"
    if isinstance(error, (TypeError, ValueError)):
        return "invalid_input"
    if isinstance(error, SodamError):
        return "sodam_error"
    return "runtime_error"


def _safe_diagnostic_code(error: BaseException) -> str | None:
    """Return an explicitly attached introduction code, never raw exception text."""
    value = getattr(error, "diagnostic_code", None)
    if value is None:
        return None
    allowed_codes = (
        INTRODUCTION_DIAGNOSTIC_CODES
        | SUMMARY_DIAGNOSTIC_CODES
        | HERMES_DIAGNOSTIC_CODES
    )
    if isinstance(value, str) and value in allowed_codes:
        return value
    return "runtime_unavailable"


def _safe_diagnostic_detail(error: BaseException) -> str | None:
    """Return a bounded underlying model-response diagnostic, if present."""
    value = getattr(error, "diagnostic_detail", None)
    if value is None:
        return None
    allowed_codes = (
        INTRODUCTION_DIAGNOSTIC_CODES
        | SUMMARY_DIAGNOSTIC_CODES
        | HERMES_DIAGNOSTIC_CODES
    )
    if isinstance(value, str) and value in allowed_codes:
        return value
    return None


def _safe_introduction_failure_lines(error: BaseException) -> list[str]:
    """Explain bounded introduction attempts without printing raw exceptions."""
    history = getattr(error, "introduction_attempts", ())
    if not isinstance(history, tuple):
        return []
    lines: list[str] = []
    for failure in history[:MAX_INTRODUCTION_ATTEMPTS]:
        if not isinstance(failure, IntroductionAttemptFailure):
            continue
        if (
            type(failure.attempt_number) is not int
            or not 1 <= failure.attempt_number <= MAX_INTRODUCTION_ATTEMPTS
            or failure.diagnostic_code not in INTRODUCTION_DIAGNOSTIC_CODES
        ):
            continue
        lines.append(f"{failure.attempt_number}회차 실패 ({failure.diagnostic_code}):")
        for issue in failure.issues:
            if isinstance(issue, IntroductionValidationIssue) and issue.code in INTRODUCTION_DIAGNOSTIC_CODES:
                reason = _safe_generated_text(issue.message)
                if reason is not None:
                    lines.append(f"  - {reason}")
        candidate = _safe_generated_text(failure.generated_text)
        if candidate is not None:
            lines.append("  생성 내용(검증 미통과): " + json.dumps(candidate, ensure_ascii=False))
        else:
            lines.append("  표시 가능한 생성 내용이 없습니다. 응답 없음 또는 표시 제한 상태입니다.")
    return lines


def _safe_error_message(category: str, error: BaseException) -> str:
    """Return a stable user-facing message with no raw exception payload."""
    if category == "invalid_input" and "--allow-url" in str(error):
        return "URL sources require the explicit --allow-url flag"
    messages = {
        "input_source": "입력 소스를 확인하세요.",
        "media_extraction": "오디오 추출에 실패했습니다.",
        "transcription": "전사에 실패했습니다.",
        "model_response": "모델 응답을 처리하지 못했습니다.",
        "review_validation": "교정 결과의 검토 검증에 실패했습니다.",
        "protection": "보호 텍스트 검증에 실패했습니다.",
        "storage": "결과 저장에 실패했습니다.",
        "invalid_input": "입력값이 올바르지 않습니다.",
        "interrupted": "작업이 중단되었습니다.",
        "system_exit": "작업이 종료되었습니다.",
        "sodam_error": "작업을 완료하지 못했습니다.",
        "runtime_error": "작업 실행 중 오류가 발생했습니다.",
    }
    message = messages.get(category, "작업 실행 중 오류가 발생했습니다.")
    if category == "review_validation" or (
        category == "protection" and getattr(error, "stage", None) == "review_validation"
    ):
        code = "review_validation_failed"
        reason = "검토 결과의 정합성을 확인하지 못했습니다."
        if isinstance(error, ReviewMappingError):
            candidate_code = getattr(error, "diagnostic_code", None)
            if isinstance(candidate_code, str) and candidate_code in _REVIEW_FAILURE_MESSAGES:
                code = candidate_code
                reason = _REVIEW_FAILURE_MESSAGES[code]
        elif isinstance(error, ProtectionError):
            code = "protected_token_invalid"
            reason = "보호 토큰 검증에 실패했습니다."
        elif isinstance(error, TranscriptAssemblyError):
            code = "transcript_assembly_invalid"
            reason = "검토 전사문을 조립하지 못했습니다."
        message += f" (단계: review_validation) (진단: {code})"
        segment_id = getattr(error, "segment_id", None)
        if isinstance(segment_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", segment_id):
            message += f" (세그먼트: {segment_id})"
        return message + "\n  - " + reason
    diagnostic = _safe_diagnostic_code(error)
    if category == "model_response" and diagnostic is not None:
        message = f"{message} (진단: {diagnostic})"
        detail = _safe_diagnostic_detail(error)
        if detail is not None:
            message += f" (원인: {detail})"
        attempt_count = getattr(error, "attempt_count", None)
        if isinstance(attempt_count, int) and attempt_count > 0:
            message += f" (시도: {attempt_count})"
        if isinstance(getattr(error, "response_empty", None), bool):
            message += f" (response_empty={str(error.response_empty).lower()})"
        attempt_lines = _safe_introduction_failure_lines(error)
        if attempt_lines:
            message += "\n" + "\n".join(attempt_lines)
    candidate = _safe_generated_text(getattr(error, "generated_text", None))
    if candidate is not None:
        candidate_attempt = getattr(error, "generated_text_attempt", None)
        if type(candidate_attempt) is int and 1 <= candidate_attempt <= MAX_INTRODUCTION_ATTEMPTS:
            message += f"\n아래 검토용 후보는 {candidate_attempt}회차 응답입니다. 최종 검증을 통과한 결과가 아닙니다."
        return message + "\nSODAM_GENERATED_TEXT:" + json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return message


def _build_resilience_report(
    result: PipelineResult,
    progress_events: tuple[ProgressEvent, ...],
) -> dict[str, object]:
    """Build JSON-safe correction and progress metadata for the CLI report."""
    if not isinstance(result, PipelineResult):
        raise TypeError("result must be a PipelineResult")
    if not isinstance(progress_events, tuple):
        raise TypeError("progress_events must be a tuple")
    if any(not isinstance(event, ProgressEvent) for event in progress_events):
        raise TypeError("progress_events must contain ProgressEvent values")

    attempts_by_group: list[list[dict[str, object]]] = []
    total_attempts = 0
    for group in result.correction_attempts:
        if not isinstance(group, tuple):
            raise TypeError("correction_attempts groups must be tuples")
        serialized_group: list[dict[str, object]] = []
        for attempt in group:
            if not hasattr(attempt, "attempt_number") or not hasattr(attempt, "status"):
                raise TypeError("correction attempts contain invalid values")
            reason = attempt.reason
            if reason is not None and reason not in _SAFE_ATTEMPT_REASONS:
                reason = "runtime_error"
            serialized_group.append(
                {
                    "attempt_number": int(attempt.attempt_number),
                    "status": str(attempt.status),
                    "reason": reason,
                }
            )
            total_attempts += 1
        attempts_by_group.append(serialized_group)

    outcome = result.summary_outcome
    if outcome is None and result.summary is not None:
        summary_status = "success"
        summary_failure_category = None
        summary_fallback_source = None
        summary_attempt_count = 1
        summary_evidence = list(result.summary.evidence_segment_ids)
    elif isinstance(outcome, SummaryOutcome):
        summary_status = outcome.status
        summary_failure_category = (
            outcome.failure_category
            if outcome.failure_category in {
                "batch_failed", "reduce_failed", "final_failed", "retry_exhausted"
            }
            else "retry_exhausted"
        ) if outcome.status == "fallback" else None
        summary_fallback_source = outcome.fallback_source if outcome.status == "fallback" else None
        summary_attempt_count = int(outcome.attempt_count)
        summary_evidence = list(outcome.summary.evidence_segment_ids)
    else:
        summary_status = None
        summary_failure_category = None
        summary_fallback_source = None
        summary_attempt_count = 0
        summary_evidence = []

    return {
        "correction_group_count": int(result.correction_group_count),
        "correction_attempt_count": total_attempts,
        "identity_group_count": int(result.identity_group_count),
        "review_required_count": int(result.review_required_count),
        "attempts": attempts_by_group,
        "progress_event_count": len(progress_events),
        "last_stage": progress_events[-1].stage if progress_events else None,
        "terminal_status": result.job.status,
        "summary_status": summary_status,
        "summary_failure_category": summary_failure_category,
        "summary_fallback_source": summary_fallback_source,
        "summary_attempt_count": summary_attempt_count,
        "summary_evidence_segment_ids": summary_evidence,
    }


def _local_source(value: str) -> Path:
    """Return an existing regular local source, rejecting URLs and symlinks."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("SOURCE must be a non-blank local file path")
    parts = urlsplit(value)
    if parts.scheme and not (len(value) >= 3 and value[1:3] in (":\\", ":/")):
        raise ValueError("SOURCE must be a local file path, not a URL")
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("SOURCE must be an existing non-symlink regular file")
    return path.resolve()


def _is_nonlocal_url(value: str) -> bool:
    """Return whether *value* is URL-shaped rather than a Windows local path."""
    parts = urlsplit(value)
    return bool(parts.scheme) and not (
        len(value) >= 3 and value[1:3] in (":\\", ":/")
    )


def _requested_source(value: str, *, allow_url: bool, mode: str) -> tuple[str, Path | None]:
    """Return the job source and local path, if any, after explicit URL gating."""
    if _is_nonlocal_url(value):
        if not allow_url:
            raise ValueError("URL sources require the explicit --allow-url flag")
        if mode != "run":
            raise ValueError("URL sources are available only with --mode run")
        validate_source(value)
        return value, None
    source = _local_source(value)
    return str(source), source


def _smoke_report(
    job: Job,
    source: Path,
    runner: LocalFfmpegRunner,
    engine: LocalFasterWhisperEngine,
    runtime: LocalOllamaRuntime,
) -> dict[str, object]:
    """Exercise FFmpeg, STT, and one strict Qwen correction response."""
    audio = extract_audio(job, source, runner)
    segments = transcribe_audio(audio, engine)
    correction = correct_chunk(
        RuleNormalizedText("Runtime health check."),
        (),
        runtime,
    )
    return {
        "mode": "smoke",
        "job_id": job.job_id,
        "segment_count": len(segments),
        "qwen_corrected_text": correction.corrected_text,
        "qwen_requires_review": correction.requires_review,
    }


def _run_pipeline(
    job: Job,
    runner: LocalFfmpegRunner,
    engine: LocalFasterWhisperEngine,
    runtime: LocalOllamaRuntime,
    glossary: tuple[str, ...],
    source_adapter: object | None = None,
    output_mode: str = "summary",
    progress_sink: CliProgressSink | None = None,
    generation_runtime: object | None = None,
    summary_instruction: str | None = None,
    introduction_instruction: str | None = None,
) -> dict[str, object]:
    """Build the existing injected pipeline and return a detached terminal report."""
    application = build_application(
        source_adapter=source_adapter or RejectingUrlSourceAdapter(),
        ffmpeg_runner=runner,
        stt_engine=engine,
        qwen_runtime=runtime,
        glossary=glossary,
        generation_runtime=generation_runtime,
    )
    has_generation_options = (
        generation_runtime is not None
        or summary_instruction is not None
        or introduction_instruction is not None
    )
    if output_mode == "summary" and progress_sink is None and not has_generation_options:
        result = application.run(job)
    else:
        result = application.run(
            job,
            output_mode=output_mode,
            progress_sink=progress_sink,
            summary_instruction=summary_instruction,
            introduction_instruction=introduction_instruction,
        )
    if result.transcript is None:
        raise RuntimeError("a completed pipeline result must include transcript")
    if output_mode in {"summary", "both"} and result.summary is None and result.summary_outcome is None:
        raise RuntimeError("requested summary result is missing")
    if output_mode in {"introduction", "both"} and result.introduction is None:
        raise RuntimeError("requested introduction result is missing")
    progress_events = progress_sink.events if progress_sink is not None else ()
    resilience = _build_resilience_report(result, progress_events)
    result_path = persist_result(
        result.job,
        result.transcript,
        result.summary,
        result.review_items,
        review_locations=result.review_locations,
        introduction=result.introduction,
        progress_events=progress_events,
        summary_outcome=result.summary_outcome,
    )
    output_summary = result.summary
    if output_summary is None and result.summary_outcome is not None:
        output_summary = result.summary_outcome.summary
    return {
        "mode": "run",
        "job_id": result.job.job_id,
        "status": result.job.status,
        "transcript": result.transcript.final_text if result.transcript else None,
        "summary": output_summary.text if output_summary else None,
        "evidence_segment_ids": list(output_summary.evidence_segment_ids)
        if output_summary
        else [],
        "introduction": asdict(result.introduction) if result.introduction else None,
        "review_item_count": len(result.review_items),
        "resilience": resilience,
        "result_path": str(result_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", metavar="SOURCE", help="existing local media file or supported YouTube URL")
    parser.add_argument("--mode", choices=("smoke", "run"), default="smoke")
    parser.add_argument(
        "--allow-url",
        action="store_true",
        help="explicitly authorize one supported YouTube URL download (run mode only)",
    )
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--qwen-model", default=DEFAULT_QWEN_MODEL)
    parser.add_argument(
        "--qwen-timeout-seconds",
        type=int,
        default=MAX_QWEN_TIMEOUT_SECONDS,
        help=f"Qwen 응답 대기 상한(초, 1~{MAX_QWEN_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--output-mode",
        choices=("summary", "introduction", "both"),
        default="summary",
        help="결과 종류: 기존 요약, 영상 소개글, 또는 둘 다",
    )
    parser.add_argument(
        "--generation-backend",
        choices=("direct", "hermes"),
        default="direct",
        help="생성 runtime: direct Ollama 또는 설치된 Hermes",
    )
    parser.add_argument("--summary-instruction", default=None)
    parser.add_argument("--introduction-instruction", default=None)
    parser.add_argument("--hermes-command", type=Path, default=None)
    parser.add_argument("--hermes-python", type=Path, default=None)
    parser.add_argument("--hermes-root", type=Path, default=None)
    parser.add_argument("--hermes-version", default="0.19.0")
    parser.add_argument(
        "--progress-format",
        choices=("human", "jsonl", "none"),
        default="human",
        help="진행 정보를 stderr에 표시하는 형식",
    )
    parser.add_argument("--glossary", action="append", default=[], metavar="TERM")
    return parser


def _build_generation_runtime(args: argparse.Namespace) -> object | None:
    """Build and preflight Hermes only when generation backend requests it."""
    if args.generation_backend == "direct":
        return None
    command = args.hermes_command
    if command is None:
        discovered = shutil.which("hermes")
        if discovered is None:
            raise ValueError("Hermes command is unavailable; use --hermes-command")
        command = Path(discovered)
    command = command.resolve()
    python_executable = args.hermes_python
    if python_executable is None:
        candidate = command.parent / "python.exe"
        python_executable = candidate if candidate.is_file() else Path(sys.executable)
    hermes_root = args.hermes_root
    if hermes_root is None:
        candidate = command.parent.parent / "Lib" / "site-packages"
        hermes_root = candidate if candidate.is_dir() else command.parent
    profile = HermesExecutionProfile(
        python_executable=python_executable,
        hermes_root=hermes_root,
        expected_version=args.hermes_version,
        model=args.qwen_model,
        base_url="http://127.0.0.1:11434/v1",
        timeout_seconds=args.qwen_timeout_seconds,
        hermes_command=command,
    )
    report = check_hermes_compatibility(profile)
    if report["status"] != "compatible":
        raise ValueError("Hermes runtime is incompatible")
    return LocalHermesRuntime(profile)


def main(argv: list[str] | None = None) -> int:
    """Run the selected local operation and print one UTF-8 JSON report."""
    args = _parser().parse_args(argv)
    try:
        source_value, local_source = _requested_source(
            args.source,
            allow_url=args.allow_url,
            mode=args.mode,
        )
        job = create_job(source_value, JobOptions())
        runner = LocalFfmpegRunner()
        engine = LocalFasterWhisperEngine(args.model_path)
        runtime = LocalOllamaRuntime(
            args.qwen_model,
            timeout_seconds=args.qwen_timeout_seconds,
        )
        generation_runtime = _build_generation_runtime(args)
        if args.mode == "smoke":
            if local_source is None:
                raise RuntimeError("URL source passed smoke-mode validation unexpectedly")
            try:
                report = _smoke_report(job, local_source, runner, engine, runtime)
            finally:
                cleanup_artifacts(job, CleanupPolicy())
        else:
            progress_sink = CliProgressSink(args.progress_format)
            report = _run_pipeline(
                job,
                runner,
                engine,
                runtime,
                tuple(args.glossary),
                LocalYtDlpSourceAdapter() if local_source is None else None,
                args.output_mode,
                progress_sink,
                generation_runtime,
                args.summary_instruction,
                args.introduction_instruction,
            )
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        category = _safe_error_category(exc)
        print(
            f"{category}: {_safe_error_message(category, exc)}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
