"""Re-run stored reviewed transcripts through direct and Hermes generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.contracts import IntroductionOptions, SummaryOutcome, VideoIntroduction
from backend.generation import GenerationRequest, generate_from_transcript, validate_generation_request
from backend.hermes_runtime import HermesExecutionProfile, LocalHermesRuntime, check_hermes_compatibility
from backend.local_adapters import LocalOllamaRuntime
from backend.persistence import PersistedResult, load_result


class CountingRuntime:
    """Count generation calls while preserving the injected runtime contract."""

    def __init__(self, runtime: object) -> None:
        if not callable(getattr(runtime, "complete", None)):
            raise TypeError("runtime.complete must be callable")
        self._runtime = runtime
        self.call_count = 0

    def complete(self, prompt: str) -> str:
        self.call_count += 1
        return self._runtime.complete(prompt)  # type: ignore[no-any-return]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _transcript_hash(result: PersistedResult) -> str:
    transcript = result.resolved_transcript or result.transcript
    payload = [
        {"segment_id": segment.source.segment_id, "final_text": segment.final_text}
        for segment in transcript.segments
    ]
    return _sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _instruction_hash(instruction: str | None) -> str:
    return _sha256(instruction or "")


def _load_persisted_result(result_path: Path) -> PersistedResult:
    """Load one direct-child persisted job without modifying its artifacts."""
    if not isinstance(result_path, Path):
        raise TypeError("result_path must be a Path")
    if result_path.is_symlink() or not result_path.is_dir():
        raise ValueError("result_path must be a non-symlink directory")
    job_id = result_path.name
    if not job_id:
        raise ValueError("result_path must identify one job")
    return load_result(job_id, result_path.parent)


def _result_payload(value: object) -> dict[str, object]:
    if isinstance(value, SummaryOutcome):
        return {
            "status": value.status,
            "text": value.summary.text,
            "evidence_segment_ids": list(value.summary.evidence_segment_ids),
            "failure_category": value.failure_category,
            "fallback_source": value.fallback_source,
            "attempt_count": value.attempt_count,
        }
    if isinstance(value, VideoIntroduction):
        return {
            "status": "success",
            "title_hook": value.title_hook,
            "body": value.body,
            "highlights": list(value.highlights),
            "evidence_segment_ids": list(value.evidence_segment_ids),
            "question_used": value.question_used,
            "call_to_action": value.call_to_action,
        }
    raise TypeError("unsupported generation result")


def _safe_diagnostic(error: BaseException) -> str:
    code = getattr(error, "diagnostic_code", None)
    if isinstance(code, str) and code:
        return code
    return "generation_failed"


def _run_backend(
    result: PersistedResult,
    backend: str,
    *,
    output_mode: str,
    summary_instruction: str | None,
    introduction_instruction: str | None,
    runtime_factory: Callable[[str], object],
) -> dict[str, object]:
    transcript = result.resolved_transcript or result.transcript
    runtime: CountingRuntime | None = None
    output: dict[str, object] = {
        "status": "completed",
        "summary": None,
        "introduction": None,
        "diagnostic_code": None,
        "call_count": 0,
    }
    try:
        runtime = CountingRuntime(runtime_factory(backend))
        if output_mode in {"summary", "both"}:
            summary = generate_from_transcript(
                GenerationRequest(transcript, "summary", summary_instruction), runtime
            )
            output["summary"] = _result_payload(summary)
        if output_mode in {"introduction", "both"}:
            introduction = generate_from_transcript(
                GenerationRequest(
                    transcript,
                    "introduction",
                    introduction_instruction,
                    IntroductionOptions(),
                ),
                runtime,
            )
            output["introduction"] = _result_payload(introduction)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        output["status"] = "failed"
        output["diagnostic_code"] = _safe_diagnostic(exc)
    output["call_count"] = runtime.call_count if runtime is not None else 0
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--output-mode", choices=("summary", "introduction", "both"), default="summary")
    parser.add_argument("--backend", choices=("direct", "hermes"), default="direct")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--summary-instruction", default=None)
    parser.add_argument("--introduction-instruction", default=None)
    parser.add_argument("--qwen-model", default="qwen3.6:35b-a3b-agent-64k")
    parser.add_argument("--qwen-timeout-seconds", type=int, default=600)
    parser.add_argument("--hermes-command", type=Path, default=None)
    parser.add_argument("--hermes-python", type=Path, default=None)
    parser.add_argument("--hermes-root", type=Path, default=None)
    parser.add_argument("--hermes-version", default="0.19.0")
    return parser


def _runtime_factory(args: argparse.Namespace) -> Callable[[str], object]:
    """Build direct/Hermes runtime collaborators without touching media."""
    hermes_runtime: object | None = None

    def factory(backend: str) -> object:
        nonlocal hermes_runtime
        if backend == "direct":
            return LocalOllamaRuntime(args.qwen_model, timeout_seconds=args.qwen_timeout_seconds)
        if hermes_runtime is None:
            command = args.hermes_command
            if command is None:
                raise ValueError("Hermes command is unavailable; use --hermes-command")
            python = args.hermes_python or Path(sys.executable)
            root = args.hermes_root or command.parent
            profile = HermesExecutionProfile(
                python,
                root,
                args.hermes_version,
                args.qwen_model,
                "http://127.0.0.1:11434/v1",
                timeout_seconds=args.qwen_timeout_seconds,
                hermes_command=command,
            )
            report = check_hermes_compatibility(profile)
            if report["status"] != "compatible":
                raise ValueError("Hermes runtime is incompatible")
            hermes_runtime = LocalHermesRuntime(profile)
        return hermes_runtime

    return factory


def main(argv: list[str] | None = None) -> int:
    """Compare generation backends against one immutable persisted transcript."""
    args = _parser().parse_args(argv)
    if args.report_path is not None and args.report_path.exists():
        raise ValueError("report_path already exists")
    if not args.dry_run and args.report_path is None:
        raise ValueError("--report-path is required unless --dry-run is used")
    result = _load_persisted_result(args.result_path)
    transcript = result.resolved_transcript or result.transcript
    for kind, instruction in (
        ("summary", args.summary_instruction),
        ("introduction", args.introduction_instruction),
    ):
        validate_generation_request(GenerationRequest(transcript, kind, instruction))
    transcript_hash = _transcript_hash(result)
    instruction_hashes = {
        "summary": _instruction_hash(args.summary_instruction),
        "introduction": _instruction_hash(args.introduction_instruction),
    }
    if args.dry_run:
        print(json.dumps({"mode": "dry-run", "job_id": result.job_id, "transcript_sha256": transcript_hash}, ensure_ascii=False, separators=(",", ":")))
        return 0
    backends = ("direct", "hermes") if args.compare else (args.backend,)
    factory = _runtime_factory(args)
    backend_results = {
        backend: _run_backend(
            result,
            backend,
            output_mode=args.output_mode,
            summary_instruction=args.summary_instruction,
            introduction_instruction=args.introduction_instruction,
            runtime_factory=factory,
        )
        for backend in backends
    }
    report = {
        "schema_version": 1,
        "job_id": result.job_id,
        "source": result.source,
        "output_mode": args.output_mode,
        "transcript_sha256": transcript_hash,
        "instruction_sha256": instruction_hashes,
        "human_quality": None,
        "backends": backend_results,
    }
    report_path = args.report_path
    assert report_path is not None
    if not report_path.parent.is_dir():
        raise ValueError("report parent directory must exist")
    with report_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"mode": "compare", "job_id": result.job_id, "report_path": str(report_path)}, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
