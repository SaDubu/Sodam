"""Read-only CLI for inspecting a completed job's JSON artifacts."""

import argparse
import json
import math
from pathlib import Path
from typing import Any


_ARTIFACT_NAMES = ("metadata.json", "transcript.json", "review.json", "summary.json")
_METADATA_KEYS = frozenset({"job_id", "status", "source"})
_TRANSCRIPT_KEYS = frozenset({"segments", "final_text"})
_SEGMENT_KEYS = frozenset({"segment_id", "start_seconds", "end_seconds", "text"})
_REVIEW_KEYS = frozenset({"review_items"})
_REVIEW_ITEM_KEYS = frozenset({"kind", "raw", "corrected", "reason"})
_SUMMARY_KEYS = frozenset({"text", "evidence_segment_ids"})


def _is_finite_number(value: object) -> bool:
    """Return whether value is a finite numeric timestamp but not a bool."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _read_artifacts(job_path: str) -> dict[str, object]:
    """Read required direct-child JSON artifacts without following symlinks."""
    if not isinstance(job_path, str) or not job_path.strip():
        raise ValueError("job_path must be a non-blank string")
    try:
        root = Path(job_path).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError("job_path must resolve to an existing directory") from exc
    if not root.is_dir():
        raise ValueError("job_path must be a directory")

    artifacts: dict[str, object] = {}
    for name in _ARTIFACT_NAMES:
        path = root / name
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
                raise ValueError("required artifact is not a direct regular file: %s" % name)
            artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("required artifact"):
                raise
            raise ValueError("could not read UTF-8 JSON artifact: %s" % name) from exc
    return artifacts


def _validate_metadata(payload: object) -> dict[str, str]:
    """Return a copied, validated metadata payload."""
    if not isinstance(payload, dict) or set(payload) != _METADATA_KEYS:
        raise ValueError("metadata.json must contain exactly job_id, status, source")
    result: dict[str, str] = {}
    for name in ("job_id", "status", "source"):
        value = payload[name]
        if not isinstance(value, str):
            raise ValueError("metadata.%s must be a string" % name)
        if name != "source" and (not value or value != value.strip()):
            raise ValueError("metadata.%s must be a non-blank trimmed string" % name)
        result[name] = value
    return result


def _validate_transcript(payload: object) -> tuple[list[dict[str, str | float]], set[str]]:
    """Validate transcript artifact and return copied timeline plus its IDs."""
    if not isinstance(payload, dict) or set(payload) != _TRANSCRIPT_KEYS:
        raise ValueError("transcript.json must contain exactly segments and final_text")
    segments = payload["segments"]
    final_text = payload["final_text"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("transcript.segments must be a non-empty list")
    if not isinstance(final_text, str):
        raise ValueError("transcript.final_text must be a string")

    timeline: list[dict[str, str | float]] = []
    ids: set[str] = set()
    previous_start: float | None = None
    previous_end: float | None = None
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != _SEGMENT_KEYS:
            raise ValueError("each transcript segment must contain the documented keys")
        segment_id = segment["segment_id"]
        text = segment["text"]
        start = segment["start_seconds"]
        end = segment["end_seconds"]
        if (
            not isinstance(segment_id, str)
            or not segment_id
            or segment_id != segment_id.strip()
            or segment_id in ids
        ):
            raise ValueError("segment_id values must be unique non-blank trimmed strings")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("segment text must be a non-blank string")
        if not _is_finite_number(start) or not _is_finite_number(end):
            raise ValueError("segment timestamps must be finite numbers")
        start_value = float(start)
        end_value = float(end)
        if start_value < 0 or end_value <= start_value:
            raise ValueError("segment timestamps must satisfy 0 <= start < end")
        if previous_start is not None and (
            start_value < previous_start or end_value < previous_end
        ):
            raise ValueError("transcript timestamps must not move backwards")
        ids.add(segment_id)
        timeline.append(
            {
                "segment_id": segment_id,
                "start_seconds": start_value,
                "end_seconds": end_value,
                "text": text,
            }
        )
        previous_start = start_value
        previous_end = end_value

    if final_text != "\n".join(item["text"] for item in timeline):
        raise ValueError("transcript.final_text must join segment text with newlines")
    return timeline, ids


def _validate_review(payload: object) -> list[dict[str, str]]:
    """Return copied review queue items with their strict string schema."""
    if not isinstance(payload, dict) or set(payload) != _REVIEW_KEYS:
        raise ValueError("review.json must contain exactly review_items")
    items = payload["review_items"]
    if not isinstance(items, list):
        raise ValueError("review_items must be a list")
    copied: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != _REVIEW_ITEM_KEYS:
            raise ValueError("each review item must contain exactly kind/raw/corrected/reason")
        if any(not isinstance(item[name], str) for name in _REVIEW_ITEM_KEYS):
            raise ValueError("each review item value must be a string")
        copied.append({name: item[name] for name in sorted(_REVIEW_ITEM_KEYS)})
    return copied


def _validate_summary(payload: object, segment_ids: set[str]) -> tuple[str, list[str]]:
    """Return copied summary text and evidence IDs after evidence validation."""
    if not isinstance(payload, dict) or set(payload) != _SUMMARY_KEYS:
        raise ValueError("summary.json must contain exactly text and evidence_segment_ids")
    text = payload["text"]
    evidence_ids = payload["evidence_segment_ids"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("summary.text must be a non-blank string")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ValueError("summary evidence_segment_ids must be a non-empty list")
    if any(
        not isinstance(item, str)
        or not item
        or item != item.strip()
        or item not in segment_ids
        for item in evidence_ids
    ) or len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("summary evidence IDs must be unique existing trimmed segment IDs")
    return text, list(evidence_ids)


def _build_report(
    metadata_payload: object,
    transcript_payload: object,
    review_payload: object,
    summary_payload: object,
) -> dict[str, object]:
    """Build one detached inspection report from four decoded artifact payloads."""
    metadata = _validate_metadata(metadata_payload)
    timeline, segment_ids = _validate_transcript(transcript_payload)
    review_items = _validate_review(review_payload)
    summary_text, evidence_ids = _validate_summary(summary_payload, segment_ids)
    return {
        "job_id": metadata["job_id"],
        "status": metadata["status"],
        "source": metadata["source"],
        "segment_count": len(timeline),
        "timeline": timeline,
        "review_item_count": len(review_items),
        "review_items": review_items,
        "summary_text": summary_text,
        "summary_evidence_segment_ids": evidence_ids,
    }


def inspect_job(job_path: str) -> dict[str, object]:
    """Read and format one completed job directory without altering its artifacts."""
    artifacts = _read_artifacts(job_path)
    return _build_report(
        artifacts["metadata.json"],
        artifacts["transcript.json"],
        artifacts["review.json"],
        artifacts["summary.json"],
    )


def main() -> int:
    """Print one deterministic JSON inspection report for a job directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_path", help="directory containing completed-job JSON artifacts")
    arguments = parser.parse_args()
    try:
        report = inspect_job(arguments.job_path)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
