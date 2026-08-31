"""Record one explicit immutable decision for a persisted review queue item."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.contracts import SodamError
from backend.persistence import RESULT_ROOT, load_result, record_review_decision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("review_index", type=int)
    parser.add_argument(
        "--decision",
        required=True,
        choices=("accept_suggested", "keep_original", "custom_text"),
    )
    parser.add_argument("--text", help="required only for custom_text")
    parser.add_argument("--result-root", type=Path, default=RESULT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate one user choice, atomically record it, and print one JSON record."""
    args = _parser().parse_args(argv)
    try:
        if args.decision == "custom_text":
            if args.text is None:
                raise ValueError("--text is required for custom_text")
            resolved_text = args.text
        else:
            if args.text is not None:
                raise ValueError("--text is only allowed for custom_text")
            result = load_result(args.job_id, args.result_root)
            if args.review_index < 0 or args.review_index >= len(result.review_items):
                raise ValueError("review_index is outside the persisted review queue")
            review = result.review_items[args.review_index]
            resolved_text = review["corrected"] if args.decision == "accept_suggested" else review["raw"]
        recorded = record_review_decision(
            args.job_id,
            args.review_index,
            args.decision,
            resolved_text,
            args.result_root,
        )
        refreshed = load_result(args.job_id, args.result_root)
    except (TypeError, ValueError, SodamError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "review_index": recorded.review_index,
                "decision": recorded.decision,
                "resolved_text": recorded.resolved_text,
                "applied_to_transcript": recorded.review_index in refreshed.applied_review_indices,
                "summary_is_stale": refreshed.summary_is_stale,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
