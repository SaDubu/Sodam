"""Run the installed local Sodam collaborators against one local media file."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.contracts import (
    CleanupPolicy,
    InputSourceError,
    Job,
    JobOptions,
    MediaExtractionError,
    ModelResponseError,
    ProgressEvent,
    ProtectionError,
    RuleNormalizedText,
    SodamError,
    StorageError,
    TranscriptionError,
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
    RejectingUrlSourceAdapter,
)
from backend.main import build_application
from backend.main import PipelineResult
from backend.media import extract_audio
from backend.persistence import persist_result
from backend.sources import validate_source
from backend.storage import cleanup_artifacts
from backend.transcription import transcribe_audio


DEFAULT_MODEL_PATH = Path(r"D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9")
_SAFE_ATTEMPT_REASONS = frozenset(
    {"invalid_response", "timeout", "runtime_error", "correction_unapplied"}
)


class CliProgressSink:
    """Render validated ProgressEvent values to stderr without contaminating stdout."""

    def __init__(self, output_format: str = "human") -> None:
        if output_format not in {"human", "jsonl", "none"}:
            raise ValueError("progress format must be human, jsonl, or none")
        self.output_format = output_format
        self._events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        if not isinstance(event, ProgressEvent):
            raise TypeError("event must be a ProgressEvent")
        self._events.append(event)
        if self.output_format == "none":
            return
        if self.output_format == "jsonl":
            print(json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
            return
        if event.overall_progress is None:
            progress = "측정 중"
        else:
            progress = f"{event.overall_progress * 100:.1f}%"
        eta = "계산 중" if event.eta_seconds is None else f"약 {event.eta_seconds:.0f}초 남음"
        print(f"[{progress}] {event.stage_label}: {event.message} ({eta})", file=sys.stderr)

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
    if isinstance(error, ModelResponseError):
        return "model_response"
    if isinstance(error, ProtectionError):
        return "protection"
    if isinstance(error, StorageError):
        return "storage"
    if isinstance(error, (TypeError, ValueError)):
        return "invalid_input"
    if isinstance(error, SodamError):
        return "sodam_error"
    return "runtime_error"


def _safe_error_message(category: str, error: BaseException) -> str:
    """Return a stable user-facing message with no raw exception payload."""
    if category == "invalid_input" and "--allow-url" in str(error):
        return "URL sources require the explicit --allow-url flag"
    messages = {
        "input_source": "입력 소스를 확인하세요.",
        "media_extraction": "오디오 추출에 실패했습니다.",
        "transcription": "전사에 실패했습니다.",
        "model_response": "모델 응답을 처리하지 못했습니다.",
        "protection": "보호 텍스트 검증에 실패했습니다.",
        "storage": "결과 저장에 실패했습니다.",
        "invalid_input": "입력값이 올바르지 않습니다.",
        "interrupted": "작업이 중단되었습니다.",
        "system_exit": "작업이 종료되었습니다.",
        "sodam_error": "작업을 완료하지 못했습니다.",
        "runtime_error": "작업 실행 중 오류가 발생했습니다.",
    }
    return messages.get(category, "작업 실행 중 오류가 발생했습니다.")


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

    return {
        "correction_group_count": int(result.correction_group_count),
        "correction_attempt_count": total_attempts,
        "identity_group_count": int(result.identity_group_count),
        "review_required_count": int(result.review_required_count),
        "attempts": attempts_by_group,
        "progress_event_count": len(progress_events),
        "last_stage": progress_events[-1].stage if progress_events else None,
        "terminal_status": result.job.status,
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
) -> dict[str, object]:
    """Build the existing injected pipeline and return a detached terminal report."""
    application = build_application(
        source_adapter=source_adapter or RejectingUrlSourceAdapter(),
        ffmpeg_runner=runner,
        stt_engine=engine,
        qwen_runtime=runtime,
        glossary=glossary,
    )
    if output_mode == "summary" and progress_sink is None:
        result = application.run(job)
    else:
        result = application.run(
            job,
            output_mode=output_mode,
            progress_sink=progress_sink,
        )
    if result.transcript is None:
        raise RuntimeError("a completed pipeline result must include transcript")
    if output_mode in {"summary", "both"} and result.summary is None:
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
    )
    return {
        "mode": "run",
        "job_id": result.job.job_id,
        "status": result.job.status,
        "transcript": result.transcript.final_text if result.transcript else None,
        "summary": result.summary.text if result.summary else None,
        "evidence_segment_ids": list(result.summary.evidence_segment_ids)
        if result.summary
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
        "--output-mode",
        choices=("summary", "introduction", "both"),
        default="summary",
        help="결과 종류: 기존 요약, 영상 소개글, 또는 둘 다",
    )
    parser.add_argument(
        "--progress-format",
        choices=("human", "jsonl", "none"),
        default="human",
        help="진행 정보를 stderr에 표시하는 형식",
    )
    parser.add_argument("--glossary", action="append", default=[], metavar="TERM")
    return parser


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
        runtime = LocalOllamaRuntime(args.qwen_model)
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
