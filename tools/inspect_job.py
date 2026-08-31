"""Read-only CLI for inspecting a completed job's JSON artifacts."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


_REQUIRED_ARTIFACT_NAMES = ("metadata.json", "transcript.json", "review.json")
_OPTIONAL_ARTIFACT_NAMES = ("summary.json", "introduction.json")
_METADATA_KEYS = frozenset({"job_id", "status", "source"})
_TRANSCRIPT_KEYS = frozenset({"segments", "final_text"})
_SEGMENT_KEYS = frozenset({"segment_id", "start_seconds", "end_seconds", "text"})
_REVIEW_KEYS = frozenset({"review_items"})
_REVIEW_ITEM_KEYS = frozenset({"kind", "raw", "corrected", "reason"})
_SUMMARY_KEYS = frozenset({"text", "evidence_segment_ids"})
_FORMAT_KEYS = frozenset({"schema_version"})
_DECISION_KEYS = frozenset({"review_index", "decision", "resolved_text"})
_DECISION_VALUES = frozenset({"accept_suggested", "keep_original", "custom_text"})
_LOCATION_KEYS = frozenset({"review_index", "segment_id", "start_offset", "end_offset"})


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
    format_path = root / "format.json"
    if format_path.exists() or format_path.is_symlink():
        try:
            if format_path.is_symlink() or not format_path.is_file() or format_path.resolve().parent != root:
                raise ValueError("format artifact is not a direct regular file")
            format_payload = json.loads(format_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("format artifact"):
                raise
            raise ValueError("could not read UTF-8 JSON artifact: format.json") from exc
        if (
            not isinstance(format_payload, dict)
            or set(format_payload) != _FORMAT_KEYS
            or type(format_payload["schema_version"]) is not int
            or format_payload["schema_version"] != 1
        ):
            raise ValueError("unsupported persisted-result schema version")
    for name in _REQUIRED_ARTIFACT_NAMES:
        path = root / name
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
                raise ValueError("required artifact is not a direct regular file: %s" % name)
            artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("required artifact"):
                raise
            raise ValueError("could not read UTF-8 JSON artifact: %s" % name) from exc
    for name in _OPTIONAL_ARTIFACT_NAMES:
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
                raise ValueError("optional artifact is not a direct regular file: %s" % name)
            artifacts[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("optional artifact"):
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


def _validate_introduction(payload: object, segment_ids: set[str]) -> dict[str, object]:
    keys = {"title_hook", "body", "highlights", "evidence_segment_ids", "question_used", "call_to_action"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("introduction.json schema is invalid")
    if (
        not isinstance(payload["title_hook"], str)
        or not payload["title_hook"].strip()
        or not isinstance(payload["body"], str)
        or not payload["body"].strip()
        or not isinstance(payload["highlights"], list)
        or any(not isinstance(item, str) or not item.strip() for item in payload["highlights"])
        or not isinstance(payload["evidence_segment_ids"], list)
        or not payload["evidence_segment_ids"]
        or any(item not in segment_ids for item in payload["evidence_segment_ids"])
        or type(payload["question_used"]) is not bool
        or not isinstance(payload["call_to_action"], str)
    ):
        raise ValueError("introduction evidence is invalid")
    return {
        "title_hook": payload["title_hook"],
        "body": payload["body"],
        "highlights": list(payload["highlights"]),
        "evidence_segment_ids": list(payload["evidence_segment_ids"]),
        "question_used": payload["question_used"],
        "call_to_action": payload["call_to_action"],
    }


def _build_report(
    metadata_payload: object,
    transcript_payload: object,
    review_payload: object,
    summary_payload: object | None,
    introduction_payload: object | None = None,
) -> dict[str, object]:
    """Build one detached inspection report from four decoded artifact payloads."""
    metadata = _validate_metadata(metadata_payload)
    timeline, segment_ids = _validate_transcript(transcript_payload)
    review_items = _validate_review(review_payload)
    summary_text, evidence_ids = (None, []) if summary_payload is None else _validate_summary(summary_payload, segment_ids)
    introduction = None if introduction_payload is None else _validate_introduction(introduction_payload, segment_ids)
    if summary_payload is None and introduction_payload is None:
        raise ValueError("result must contain summary.json or introduction.json")
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
        "introduction": introduction,
    }


def _read_review_decisions(root: Path, review_items: list[dict[str, str]]) -> list[dict[str, object]]:
    """Read optional immutable resolution state for a schema-v1 result."""
    path = root / "review_resolution.json"
    if not path.exists() and not path.is_symlink():
        return []
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            raise ValueError("review resolution is not a direct regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("review resolution"):
            raise
        raise ValueError("could not read UTF-8 JSON artifact: review_resolution.json") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "decisions"}:
        raise ValueError("review resolution schema is invalid")
    if payload["schema_version"] != 1 or not isinstance(payload["decisions"], list):
        raise ValueError("review resolution version is invalid")
    result: list[dict[str, object]] = []
    previous = -1
    for item in payload["decisions"]:
        if not isinstance(item, dict) or set(item) != _DECISION_KEYS:
            raise ValueError("review decision schema is invalid")
        index = item["review_index"]
        decision = item["decision"]
        text = item["resolved_text"]
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index <= previous
            or index < 0
            or index >= len(review_items)
            or decision not in _DECISION_VALUES
            or not isinstance(text, str)
        ):
            raise ValueError("review decision values are invalid")
        review = review_items[index]
        if (
            decision == "accept_suggested" and text != review["corrected"]
        ) or (
            decision == "keep_original" and text != review["raw"]
        ) or (
            decision == "custom_text" and (not text or text != text.strip())
        ):
            raise ValueError("review decision text is inconsistent")
        result.append({"review_index": index, "decision": decision, "resolved_text": text})
        previous = index
    return result


def _read_review_locations(
    root: Path,
    review_items: list[dict[str, str]],
    timeline: list[dict[str, str | float]],
) -> list[dict[str, object]]:
    """Read optional strict locations without changing reviewed text or queue."""
    path = root / "review_locations.json"
    if not path.exists() and not path.is_symlink():
        return []
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            raise ValueError("review locations are not a direct regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("review locations"):
            raise
        raise ValueError("could not read UTF-8 JSON artifact: review_locations.json") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "locations"}:
        raise ValueError("review locations schema is invalid")
    if payload["schema_version"] != 1 or not isinstance(payload["locations"], list):
        raise ValueError("review locations version is invalid")
    if len(payload["locations"]) != len(review_items):
        raise ValueError("review locations must map every review item")
    texts = {item["segment_id"]: item["text"] for item in timeline}
    copied: list[dict[str, object]] = []
    for expected_index, item in enumerate(payload["locations"]):
        if not isinstance(item, dict) or set(item) != _LOCATION_KEYS:
            raise ValueError("review location schema is invalid")
        index = item["review_index"]
        segment_id = item["segment_id"]
        start = item["start_offset"]
        end = item["end_offset"]
        if (
            isinstance(index, bool)
            or index != expected_index
            or not isinstance(segment_id, str)
            or segment_id not in texts
        ):
            raise ValueError("review location index or segment is invalid")
        raw = review_items[index]["raw"]
        if raw == "":
            if start is not None or end is not None:
                raise ValueError("insertion review location must use null offsets")
        elif (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(texts[segment_id])
            or texts[segment_id][start:end] != raw
        ):
            raise ValueError("review location range does not match raw text")
        copied.append({"review_index": index, "segment_id": segment_id, "start_offset": start, "end_offset": end})
    return copied


def _project_resolved_timeline(
    timeline: list[dict[str, str | float]],
    decisions: list[dict[str, object]],
    locations: list[dict[str, object]],
) -> tuple[list[dict[str, str | float]], list[int], list[int]]:
    """Apply only valid non-null location decisions to a detached timeline copy."""
    by_index = {item["review_index"]: item for item in locations}
    grouped: dict[str, list[tuple[int, int, str, int]]] = {}
    unapplied: list[int] = []
    for decision in decisions:
        index = decision["review_index"]
        location = by_index.get(index)
        if location is None or location["start_offset"] is None:
            unapplied.append(index)  # type: ignore[arg-type]
            continue
        start = location["start_offset"]
        end = location["end_offset"]
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("applicable review location offsets must be integers")
        grouped.setdefault(location["segment_id"], []).append(
            (start, end, decision["resolved_text"], index)  # type: ignore[arg-type]
        )

    resolved: list[dict[str, str | float]] = []
    applied: list[int] = []
    for segment in timeline:
        text = segment["text"]
        assert isinstance(text, str)
        cursor = 0
        parts: list[str] = []
        for start, end, replacement, index in sorted(grouped.get(segment["segment_id"], [])):
            if start < cursor or end <= start or end > len(text):
                raise ValueError("review decision locations overlap or escape their segment")
            parts.extend((text[cursor:start], replacement))
            cursor = end
            applied.append(index)
        parts.append(text[cursor:])
        resolved.append({**segment, "text": "".join(parts)})
    return resolved, sorted(applied), sorted(unapplied)


def _read_resolved_summary(
    root: Path,
    resolved_timeline: list[dict[str, str | float]],
) -> dict[str, object] | None:
    """Read a matching optional resolved-summary projection without model calls."""
    path = root / "resolved_summary.json"
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            raise ValueError("resolved summary is not a direct regular file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("resolved summary"):
            raise
        raise ValueError("could not read UTF-8 JSON artifact: resolved_summary.json") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "transcript_sha256", "summary"}:
        raise ValueError("resolved summary schema is invalid")
    resolved_text = "\n".join(item["text"] for item in resolved_timeline)
    fingerprint = payload["transcript_sha256"]
    if (
        payload["schema_version"] != 1
        or not isinstance(fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    ):
        raise ValueError("resolved summary version or fingerprint is invalid")
    summary = payload["summary"]
    ids = {item["segment_id"] for item in resolved_timeline}
    if (
        not isinstance(summary, dict)
        or set(summary) != _SUMMARY_KEYS
        or not isinstance(summary["text"], str)
        or not summary["text"].strip()
        or not isinstance(summary["evidence_segment_ids"], list)
        or not summary["evidence_segment_ids"]
        or len(set(summary["evidence_segment_ids"])) != len(summary["evidence_segment_ids"])
        or any(not isinstance(item, str) or item not in ids for item in summary["evidence_segment_ids"])
    ):
        raise ValueError("resolved summary evidence is invalid")
    if fingerprint != hashlib.sha256(resolved_text.encode("utf-8")).hexdigest():
        return None
    return {"text": summary["text"], "evidence_segment_ids": list(summary["evidence_segment_ids"])}


def inspect_job(job_path: str) -> dict[str, object]:
    """Read and format one completed job directory without altering its artifacts."""
    artifacts = _read_artifacts(job_path)
    report = _build_report(
        artifacts["metadata.json"],
        artifacts["transcript.json"],
        artifacts["review.json"],
        artifacts.get("summary.json"),
        artifacts.get("introduction.json"),
    )
    root = Path(job_path).resolve(strict=True)
    decisions = _read_review_decisions(root, report["review_items"])  # type: ignore[arg-type]
    locations = _read_review_locations(root, report["review_items"], report["timeline"])  # type: ignore[arg-type]
    resolved_timeline, applied, unapplied = _project_resolved_timeline(
        report["timeline"], decisions, locations  # type: ignore[arg-type]
    )
    report["review_decisions"] = decisions
    report["review_locations"] = locations
    report["pending_review_item_count"] = report["review_item_count"] - len(decisions)  # type: ignore[operator]
    report["resolved_timeline"] = resolved_timeline
    report["resolved_final_text"] = "\n".join(item["text"] for item in resolved_timeline)
    report["applied_review_indices"] = applied
    report["unapplied_review_indices"] = unapplied
    report["summary_is_stale"] = report["resolved_final_text"] != "\n".join(
        item["text"] for item in report["timeline"]  # type: ignore[index]
    )
    resolved_summary = _read_resolved_summary(root, resolved_timeline)
    report["resolved_summary_text"] = resolved_summary["text"] if resolved_summary else None
    report["resolved_summary_evidence_segment_ids"] = (
        resolved_summary["evidence_segment_ids"] if resolved_summary else []
    )
    if resolved_summary is not None:
        report["summary_is_stale"] = False
    return report


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
