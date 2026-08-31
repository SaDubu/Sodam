"""Read-only, reproducible transcript-correction evaluation CLI."""

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


_CASE_KEYS = frozenset(
    {
        "case_id",
        "expected_text",
        "actual_text",
        "protected_tokens",
        "auto_approved",
        "duration_seconds",
    }
)


def _validate_case(case: object, seen_case_ids: set[str]) -> dict[str, Any]:
    """Validate one fixture case and return it with its precise dict type."""
    if not isinstance(case, dict) or set(case) != _CASE_KEYS:
        raise ValueError("each case must contain exactly the documented keys")

    case_id = case["case_id"]
    if not isinstance(case_id, str) or not case_id or case_id != case_id.strip():
        raise ValueError("case_id must be a non-blank trimmed string")
    if case_id in seen_case_ids:
        raise ValueError("case_id values must be unique")
    seen_case_ids.add(case_id)

    for name in ("expected_text", "actual_text"):
        if not isinstance(case[name], str):
            raise ValueError("%s must be a string" % name)

    tokens = case["protected_tokens"]
    if not isinstance(tokens, list) or any(
        not isinstance(token, str) or not token for token in tokens
    ):
        raise ValueError("protected_tokens must be a list of non-empty strings")

    if type(case["auto_approved"]) is not bool:
        raise ValueError("auto_approved must be a bool")

    duration = case["duration_seconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or duration < 0
    ):
        raise ValueError("duration_seconds must be a finite number >= 0")

    return case


def _token_sequence(text: str, tokens: list[str]) -> tuple[str, ...]:
    """Return protected token occurrences in text, longest token first on ties."""
    unique_tokens = sorted(set(tokens), key=lambda token: (-len(token), token))
    if not unique_tokens:
        return ()
    pattern = re.compile("|".join(re.escape(token) for token in unique_tokens))
    return tuple(match.group(0) for match in pattern.finditer(text))


def _preserves_protected_tokens(case: dict[str, Any]) -> bool:
    """Check token counts and occurrence order between expected and actual text."""
    tokens: list[str] = case["protected_tokens"]
    expected = case["expected_text"]
    actual = case["actual_text"]
    return (
        _token_sequence(expected, tokens) == _token_sequence(actual, tokens)
        and all(expected.count(token) == actual.count(token) for token in set(tokens))
    )


def _evaluate_payload(payload: object) -> dict[str, int | float]:
    """Validate one decoded fixture object and return deterministic metrics."""
    if not isinstance(payload, dict) or set(payload) != {"cases"}:
        raise ValueError("fixture must be an object containing exactly 'cases'")
    cases = payload["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")

    seen_case_ids: set[str] = set()
    exact_match_count = 0
    protected_count = 0
    risky_auto_approval_count = 0
    total_duration_seconds = 0.0

    for raw_case in cases:
        case = _validate_case(raw_case, seen_case_ids)
        exact_match = case["actual_text"] == case["expected_text"]
        protected = _preserves_protected_tokens(case)
        if exact_match:
            exact_match_count += 1
        if protected:
            protected_count += 1
        if case["auto_approved"] and (not exact_match or not protected):
            risky_auto_approval_count += 1
        total_duration_seconds += float(case["duration_seconds"])

    total_cases = len(cases)
    return {
        "total_cases": total_cases,
        "exact_match_count": exact_match_count,
        "correction_accuracy": exact_match_count / total_cases,
        "protected_token_preservation_count": protected_count,
        "protected_token_preservation_rate": protected_count / total_cases,
        "risky_auto_approval_count": risky_auto_approval_count,
        "risky_auto_approval_rate": risky_auto_approval_count / total_cases,
        "total_duration_seconds": total_duration_seconds,
        "average_duration_seconds": total_duration_seconds / total_cases,
    }


def evaluate_transcript(fixture_path: str) -> dict[str, int | float]:
    """Read one fixed fixture and calculate documented correction/safety metrics."""
    if not isinstance(fixture_path, str) or not fixture_path.strip():
        raise ValueError("fixture_path must be a non-blank string")
    try:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("fixture could not be read as UTF-8 JSON") from exc
    return _evaluate_payload(payload)


def main() -> int:
    """Print a deterministic JSON report for one evaluation fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_path", help="UTF-8 JSON evaluation fixture path")
    arguments = parser.parse_args()
    try:
        report = evaluate_transcript(arguments.fixture_path)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
