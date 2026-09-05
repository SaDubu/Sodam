"""Explicitly refresh a stale persisted resolved-transcript summary with local Ollama."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.contracts import SodamError
from backend.local_adapters import LocalOllamaRuntime, MAX_QWEN_TIMEOUT_SECONDS
from backend.persistence import RESULT_ROOT, refresh_resolved_summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--qwen-model", default="qwen3:8b")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=MAX_QWEN_TIMEOUT_SECONDS,
        help=f"Qwen 응답 대기 상한(초, 1~{MAX_QWEN_TIMEOUT_SECONDS})",
    )
    parser.add_argument("--result-root", type=Path, default=RESULT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run only the explicit local summary refresh and print its validated result."""
    args = _parser().parse_args(argv)
    try:
        runtime = LocalOllamaRuntime(args.qwen_model, timeout_seconds=args.timeout_seconds)
        summary = refresh_resolved_summary(args.job_id, runtime, args.result_root)
    except (TypeError, ValueError, SodamError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"text": summary.text, "evidence_segment_ids": list(summary.evidence_segment_ids)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
