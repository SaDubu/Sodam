"""Versioned, atomic storage for completed Sodam text results.

Temporary media belongs to ``tmp/jobs`` and is never handled here.  This
module stores only validated text artifacts in a separate result root.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .contracts import (
    Job,
    RawSegment,
    ReviewedTranscript,
    StorageError,
    Summary,
    Transcript,
    TranscriptAssemblyError,
    UnsafePathError,
    IntroductionOptions,
    ProgressEvent,
    VideoIntroduction,
)
from .introduction import validate_introduction
from .storage import assemble_reviewed_transcript, assemble_transcript
from .summarization import summarize_reviewed_transcript


RESULT_ROOT = Path(r"D:\AI-Legion\Sodam-data\jobs")
SCHEMA_VERSION = 1
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REVIEW_KEYS = frozenset({"kind", "raw", "corrected", "reason"})
_DECISION_VALUES = frozenset({"accept_suggested", "keep_original", "custom_text"})
_LOCATION_KEYS = frozenset({"review_index", "segment_id", "start_offset", "end_offset"})
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PersistedResult:
    """Detached completed result reloaded from schema-v1 JSON artifacts."""

    job_id: str
    status: str
    source: str
    transcript: ReviewedTranscript
    summary: Summary | None
    review_items: tuple[dict[str, str], ...]
    introduction: VideoIntroduction | None = None
    progress_events: tuple[ProgressEvent, ...] = ()
    review_decisions: tuple["ReviewDecision", ...] = ()
    review_locations: tuple[dict[str, object], ...] = ()
    resolved_transcript: ReviewedTranscript | None = None
    applied_review_indices: tuple[int, ...] = ()
    unapplied_review_indices: tuple[int, ...] = ()
    summary_is_stale: bool = False
    resolved_summary: Summary | None = None


@dataclass(frozen=True)
class ReviewDecision:
    """One immutable user resolution for an indexed persisted review item."""

    review_index: int
    decision: str
    resolved_text: str


def _validated_job_id(job_id: object) -> str:
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        raise UnsafePathError("job_id must match the persisted-result safe ID format")
    return job_id


def _validated_root(result_root: Path | str) -> Path:
    if not isinstance(result_root, (str, Path)):
        raise TypeError("result_root must be str or Path")
    candidate = Path(result_root).expanduser()
    try:
        if candidate.is_symlink():
            raise UnsafePathError("result_root must not be a symlink")
        root = candidate.resolve()
        repository = _REPOSITORY_ROOT.resolve()
    except OSError as exc:
        raise StorageError("could not resolve result_root") from exc
    if root.is_relative_to(repository):
        raise UnsafePathError("result_root must be outside the repository")
    return root


def _target_path(root: Path, job_id: str) -> Path:
    target = root / _validated_job_id(job_id)
    try:
        if target.is_symlink() or target.resolve().parent != root.resolve():
            raise UnsafePathError("result target must be a direct non-symlink child")
    except OSError as exc:
        raise StorageError("could not validate result target") from exc
    return target


def _review_items(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, tuple):
        raise TypeError("review_items must be a tuple")
    copied: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _REVIEW_KEYS:
            raise StorageError("review items must contain exactly kind/raw/corrected/reason")
        if any(not isinstance(item[name], str) for name in _REVIEW_KEYS):
            raise StorageError("review item values must be strings")
        copied.append({name: item[name] for name in sorted(_REVIEW_KEYS)})
    return tuple(copied)


def _review_locations(
    value: object,
    review_items: tuple[dict[str, str], ...],
    transcript: ReviewedTranscript,
) -> tuple[dict[str, object], ...]:
    """Validate detached queue locations against reviewed segment text."""
    if not isinstance(value, tuple):
        raise TypeError("review_locations must be a tuple")
    if not value:
        return ()
    if len(value) != len(review_items):
        raise StorageError("review locations must map every review item exactly once")
    texts = {item.source.segment_id: item.final_text for item in transcript.segments}
    copied: list[dict[str, object]] = []
    for expected_index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != _LOCATION_KEYS:
            raise StorageError("review location schema is invalid")
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
            raise StorageError("review location index or segment is invalid")
        raw = review_items[index]["raw"]
        if raw == "":
            if start is not None or end is not None:
                raise StorageError("insertion review locations must use null offsets")
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
            raise StorageError("review location range does not match its raw text")
        copied.append(
            {
                "review_index": index,
                "segment_id": segment_id,
                "start_offset": start,
                "end_offset": end,
            }
        )
    return tuple(copied)


def _validated_result_inputs(
    job: Job,
    transcript: ReviewedTranscript,
    summary: Summary | None,
    review_items: tuple[dict[str, str], ...],
    review_locations: tuple[dict[str, object], ...],
    introduction: VideoIntroduction | None,
) -> tuple[Transcript, tuple[dict[str, str], ...], tuple[dict[str, object], ...]]:
    if not isinstance(job, Job):
        raise TypeError("job must be a Job")
    if job.status != "archived":
        raise StorageError("only archived jobs may be persisted")
    _validated_job_id(job.job_id)
    if not isinstance(job.source, str):
        raise StorageError("job.source must be a string")
    if not isinstance(transcript, ReviewedTranscript):
        raise TypeError("transcript must be a ReviewedTranscript")
    if summary is not None and not isinstance(summary, Summary):
        raise TypeError("summary must be a Summary or None")
    if introduction is not None and not isinstance(introduction, VideoIntroduction):
        raise TypeError("introduction must be a VideoIntroduction or None")
    if summary is None and introduction is None:
        raise StorageError("at least one summary or introduction is required")
    if not transcript.segments:
        raise StorageError("completed transcript must contain segments")

    raw = assemble_transcript([item.source for item in transcript.segments])
    rebuilt = assemble_reviewed_transcript(
        raw,
        [item.final_text for item in transcript.segments],
    )
    if rebuilt != transcript:
        raise StorageError("reviewed transcript is not a valid source-aligned transcript")
    if summary is not None:
        if not isinstance(summary.text, str) or not summary.text.strip():
            raise StorageError("summary.text must be a non-blank string")
        if (
            not isinstance(summary.evidence_segment_ids, tuple)
            or not summary.evidence_segment_ids
            or len(set(summary.evidence_segment_ids)) != len(summary.evidence_segment_ids)
            or any(item not in {segment.segment_id for segment in raw.segments} for item in summary.evidence_segment_ids)
        ):
            raise StorageError("summary evidence IDs must be unique transcript segment IDs")
    if introduction is not None:
        try:
            validate_introduction(introduction, transcript, IntroductionOptions())
        except Exception as exc:
            raise StorageError("introduction does not satisfy its source contract") from exc
    copied_review = _review_items(review_items)
    return raw, copied_review, _review_locations(review_locations, copied_review, transcript)


def _raw_payload(transcript: Transcript) -> dict[str, object]:
    return {
        "segments": [
            {
                "segment_id": segment.segment_id,
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "raw_text": segment.raw_text,
                "confidence": segment.confidence,
            }
            for segment in transcript.segments
        ],
        "final_text": transcript.final_text,
    }


def _reviewed_payload(transcript: ReviewedTranscript) -> dict[str, object]:
    return {
        "segments": [
            {
                "segment_id": segment.source.segment_id,
                "start_seconds": segment.source.start_seconds,
                "end_seconds": segment.source.end_seconds,
                "text": segment.final_text,
            }
            for segment in transcript.segments
        ],
        "final_text": transcript.final_text,
    }


def _introduction_payload(introduction: VideoIntroduction) -> dict[str, object]:
    return {
        "title_hook": introduction.title_hook,
        "body": introduction.body,
        "highlights": list(introduction.highlights),
        "evidence_segment_ids": list(introduction.evidence_segment_ids),
        "question_used": introduction.question_used,
        "call_to_action": introduction.call_to_action,
    }


def _progress_payload(event: ProgressEvent) -> dict[str, object]:
    return {
        "operation_id": event.operation_id,
        "scope": event.scope,
        "stage": event.stage,
        "stage_label": event.stage_label,
        "stage_progress": event.stage_progress,
        "overall_progress": event.overall_progress,
        "completed_units": event.completed_units,
        "total_units": event.total_units,
        "elapsed_seconds": event.elapsed_seconds,
        "eta_seconds": event.eta_seconds,
        "message": event.message,
        "can_cancel": event.can_cancel,
        "sequence": event.sequence,
        "timestamp": event.timestamp,
    }


def _write_json(path: Path, payload: object) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )


def persist_result(
    job: Job,
    transcript: ReviewedTranscript,
    summary: Summary | None,
    review_items: tuple[dict[str, str], ...],
    result_root: Path | str = RESULT_ROOT,
    review_locations: tuple[dict[str, object], ...] = (),
    introduction: VideoIntroduction | None = None,
    progress_events: tuple[ProgressEvent, ...] = (),
) -> Path:
    """Atomically publish a schema-v1 completed result without overwriting one."""
    raw, copied_review, copied_locations = _validated_result_inputs(
        job, transcript, summary, review_items, review_locations, introduction
    )
    if not isinstance(progress_events, tuple) or any(
        not isinstance(event, ProgressEvent) for event in progress_events
    ):
        raise TypeError("progress_events must be a tuple of ProgressEvent values")
    if progress_events:
        operation_id = progress_events[0].operation_id
        expected_sequence = 1
        for event in progress_events:
            if event.operation_id != operation_id or event.sequence != expected_sequence:
                raise StorageError("progress events must have one operation and increasing sequence")
            expected_sequence += 1
    root = _validated_root(result_root)
    target = _target_path(root, job.job_id)
    if target.exists():
        raise StorageError("a persisted result already exists for this job_id")

    try:
        root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".sodam-result-", dir=root))
    except OSError as exc:
        raise StorageError("could not create persistent result staging directory") from exc

    payloads: dict[str, object] = {
        "format.json": {"schema_version": SCHEMA_VERSION},
        "metadata.json": {"job_id": job.job_id, "status": job.status, "source": job.source},
        "raw_transcript.json": _raw_payload(raw),
        "transcript.json": _reviewed_payload(transcript),
        "review.json": {"review_items": list(copied_review)},
    }
    if summary is not None:
        payloads["summary.json"] = {
            "text": summary.text,
            "evidence_segment_ids": list(summary.evidence_segment_ids),
        }
    if introduction is not None:
        payloads["introduction.json"] = _introduction_payload(introduction)
    if progress_events:
        payloads["progress.jsonl"] = "".join(
            json.dumps(_progress_payload(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for event in progress_events
        )
    if copied_locations:
        payloads["review_locations.json"] = {
            "schema_version": SCHEMA_VERSION,
            "locations": list(copied_locations),
        }
    try:
        for name, payload in payloads.items():
            _write_json(temporary / name, payload)
        os.replace(temporary, target)
    except (OSError, TypeError, ValueError) as exc:
        try:
            shutil.rmtree(temporary)
        except OSError:
            pass
        raise StorageError("could not atomically persist result") from exc
    return target.resolve()


def _read_json(root: Path, name: str) -> Any:
    path = root / name
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root.resolve():
            raise UnsafePathError("persisted artifact must be a direct regular file: %s" % name)
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StorageError("could not read persisted artifact: %s" % name) from exc


def _load_review_decisions(
    root: Path,
    review_items: tuple[dict[str, str], ...],
) -> tuple[ReviewDecision, ...]:
    """Read optional immutable decision state without changing base artifacts."""
    path = root / "review_resolution.json"
    if not path.exists() and not path.is_symlink():
        return ()
    payload = _read_json(root, "review_resolution.json")
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "decisions"}:
        raise StorageError("review resolution schema is invalid")
    if payload["schema_version"] != SCHEMA_VERSION or not isinstance(payload["decisions"], list):
        raise StorageError("review resolution version is invalid")
    decisions: list[ReviewDecision] = []
    previous_index = -1
    for item in payload["decisions"]:
        if not isinstance(item, dict) or set(item) != {"review_index", "decision", "resolved_text"}:
            raise StorageError("review decision schema is invalid")
        index = item["review_index"]
        decision = item["decision"]
        text = item["resolved_text"]
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index <= previous_index
            or index < 0
            or index >= len(review_items)
            or decision not in _DECISION_VALUES
            or not isinstance(text, str)
        ):
            raise StorageError("review decision values are invalid")
        review = review_items[index]
        if (
            decision == "accept_suggested" and text != review["corrected"]
        ) or (
            decision == "keep_original" and text != review["raw"]
        ) or (
            decision == "custom_text" and (not text or text != text.strip())
        ):
            raise StorageError("review decision text is inconsistent with its action")
        decisions.append(ReviewDecision(index, decision, text))
        previous_index = index
    return tuple(decisions)


def _load_review_locations(
    root: Path,
    review_items: tuple[dict[str, str], ...],
    transcript: ReviewedTranscript,
) -> tuple[dict[str, object], ...]:
    """Read optional persisted location data through the same strict contract."""
    path = root / "review_locations.json"
    if not path.exists() and not path.is_symlink():
        return ()
    payload = _read_json(root, "review_locations.json")
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "locations"}:
        raise StorageError("review locations schema is invalid")
    if payload["schema_version"] != SCHEMA_VERSION or not isinstance(payload["locations"], list):
        raise StorageError("review locations version is invalid")
    return _review_locations(tuple(payload["locations"]), review_items, transcript)


def _atomic_replace_json(path: Path, payload: object) -> None:
    """Publish one whole JSON file through a same-directory temporary file."""
    if path.is_symlink():
        raise UnsafePathError("review resolution path must not be a symlink")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=".sodam-review-", suffix=".tmp", dir=path.parent
        )
        temporary = Path(raw_temporary)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = None
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise StorageError("could not atomically write review resolution") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _transcript_fingerprint(transcript: ReviewedTranscript) -> str:
    return hashlib.sha256(transcript.final_text.encode("utf-8")).hexdigest()


def _summary_from_payload(payload: object, segment_ids: set[str]) -> Summary:
    if not isinstance(payload, dict) or set(payload) != {"text", "evidence_segment_ids"}:
        raise StorageError("summary schema is invalid")
    text = payload["text"]
    evidence = payload["evidence_segment_ids"]
    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(evidence, list)
        or not evidence
        or len(set(evidence)) != len(evidence)
        or any(not isinstance(item, str) or item not in segment_ids for item in evidence)
    ):
        raise StorageError("summary evidence is invalid")
    return Summary(text, tuple(evidence))


def _introduction_from_payload(
    payload: object,
    transcript: ReviewedTranscript,
) -> VideoIntroduction:
    if not isinstance(payload, dict) or set(payload) != {
        "title_hook", "body", "highlights", "evidence_segment_ids", "question_used", "call_to_action"
    }:
        raise StorageError("introduction schema is invalid")
    if (
        not isinstance(payload["title_hook"], str)
        or not isinstance(payload["body"], str)
        or not isinstance(payload["highlights"], list)
        or not isinstance(payload["evidence_segment_ids"], list)
        or type(payload["question_used"]) is not bool
        or not isinstance(payload["call_to_action"], str)
        or any(not isinstance(value, str) for value in payload["highlights"])
        or any(not isinstance(value, str) for value in payload["evidence_segment_ids"])
    ):
        raise StorageError("introduction field types are invalid")
    introduction = VideoIntroduction(
        payload["title_hook"],
        payload["body"],
        tuple(payload["highlights"]),
        tuple(payload["evidence_segment_ids"]),
        payload["question_used"],
        payload["call_to_action"],
    )
    try:
        validate_introduction(introduction, transcript, IntroductionOptions())
    except Exception as exc:
        raise StorageError("persisted introduction evidence is invalid") from exc
    return introduction


def _load_progress_events(root: Path) -> tuple[ProgressEvent, ...]:
    path = root / "progress.jsonl"
    if not path.exists() and not path.is_symlink():
        return ()
    try:
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root.resolve():
            raise UnsafePathError("progress artifact must be a direct regular file")
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError("could not read progress artifact") from exc
    events: list[ProgressEvent] = []
    for expected, line in enumerate(lines, 1):
        try:
            payload = json.loads(line)
        except (TypeError, ValueError) as exc:
            raise StorageError("progress artifact contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise StorageError("progress artifact line must be an object")
        try:
            event = ProgressEvent(**payload)
        except TypeError as exc:
            raise StorageError("progress artifact schema is invalid") from exc
        if event.sequence != expected:
            raise StorageError("progress sequence is not strictly increasing")
        events.append(event)
    return tuple(events)


def _load_resolved_summary(
    root: Path,
    transcript: ReviewedTranscript,
) -> Summary | None:
    """Read a matching resolved-summary projection; old fingerprints stay stale."""
    path = root / "resolved_summary.json"
    if not path.exists() and not path.is_symlink():
        return None
    payload = _read_json(root, "resolved_summary.json")
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "transcript_sha256", "summary"}:
        raise StorageError("resolved summary schema is invalid")
    fingerprint = payload["transcript_sha256"]
    if (
        payload["schema_version"] != SCHEMA_VERSION
        or not isinstance(fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    ):
        raise StorageError("resolved summary version or fingerprint is invalid")
    summary = _summary_from_payload(
        payload["summary"], {item.source.segment_id for item in transcript.segments}
    )
    if fingerprint != _transcript_fingerprint(transcript):
        return None
    return summary


def refresh_resolved_summary(
    job_id: str,
    runtime: object,
    result_root: Path | str = RESULT_ROOT,
) -> Summary:
    """Explicitly call an injected runtime and atomically publish a fresh projection."""
    result = load_result(job_id, result_root)
    if not result.summary_is_stale or result.resolved_transcript is None:
        raise StorageError("resolved transcript does not require a summary refresh")
    summary = summarize_reviewed_transcript(result.resolved_transcript, runtime)  # type: ignore[arg-type]
    root = _validated_root(result_root)
    target = _target_path(root, job_id)
    _atomic_replace_json(
        target / "resolved_summary.json",
        {
            "schema_version": SCHEMA_VERSION,
            "transcript_sha256": _transcript_fingerprint(result.resolved_transcript),
            "summary": {"text": summary.text, "evidence_segment_ids": list(summary.evidence_segment_ids)},
        },
    )
    return summary


def record_review_decision(
    job_id: str,
    review_index: int,
    decision: str,
    resolved_text: str,
    result_root: Path | str = RESULT_ROOT,
) -> ReviewDecision:
    """Append one immutable, validated decision for a persisted review item."""
    result = load_result(job_id, result_root)
    if isinstance(review_index, bool) or not isinstance(review_index, int):
        raise TypeError("review_index must be an int")
    if review_index < 0 or review_index >= len(result.review_items):
        raise StorageError("review_index is outside the persisted review queue")
    if not isinstance(decision, str) or decision not in _DECISION_VALUES:
        raise StorageError("decision is invalid")
    if not isinstance(resolved_text, str):
        raise TypeError("resolved_text must be a str")
    review = result.review_items[review_index]
    if (
        decision == "accept_suggested" and resolved_text != review["corrected"]
    ) or (
        decision == "keep_original" and resolved_text != review["raw"]
    ) or (
        decision == "custom_text" and (not resolved_text or resolved_text != resolved_text.strip())
    ):
        raise StorageError("resolved_text is invalid for the requested decision")
    if any(item.review_index == review_index for item in result.review_decisions):
        raise StorageError("review item already has an immutable decision")

    root = _validated_root(result_root)
    target = _target_path(root, job_id)
    decision_value = ReviewDecision(review_index, decision, resolved_text)
    all_decisions = tuple(sorted((*result.review_decisions, decision_value), key=lambda item: item.review_index))
    _atomic_replace_json(
        target / "review_resolution.json",
        {
            "schema_version": SCHEMA_VERSION,
            "decisions": [
                {
                    "review_index": item.review_index,
                    "decision": item.decision,
                    "resolved_text": item.resolved_text,
                }
                for item in all_decisions
            ],
        },
    )
    return decision_value


def _project_resolved_transcript(
    transcript: ReviewedTranscript,
    decisions: tuple[ReviewDecision, ...],
    locations: tuple[dict[str, object], ...],
) -> tuple[ReviewedTranscript, tuple[int, ...], tuple[int, ...]]:
    """Derive resolved text from non-overlapping, source-coordinate decisions."""
    locations_by_index = {item["review_index"]: item for item in locations}
    grouped: dict[str, list[tuple[int, int, str, int]]] = {}
    unapplied: list[int] = []
    for decision in decisions:
        location = locations_by_index.get(decision.review_index)
        if location is None or location["start_offset"] is None:
            unapplied.append(decision.review_index)
            continue
        start = location["start_offset"]
        end = location["end_offset"]
        if not isinstance(start, int) or not isinstance(end, int):
            raise StorageError("applicable review location offsets must be integers")
        grouped.setdefault(location["segment_id"], []).append(
            (start, end, decision.resolved_text, decision.review_index)
        )

    resolved_by_id: dict[str, str] = {}
    applied: list[int] = []
    for segment in transcript.segments:
        replacements = sorted(grouped.get(segment.source.segment_id, []))
        cursor = 0
        parts: list[str] = []
        for start, end, replacement, index in replacements:
            if start < cursor or end <= start or end > len(segment.final_text):
                raise StorageError("review decision locations overlap or escape their segment")
            parts.extend((segment.final_text[cursor:start], replacement))
            cursor = end
            applied.append(index)
        parts.append(segment.final_text[cursor:])
        resolved_by_id[segment.source.segment_id] = "".join(parts)

    raw = assemble_transcript([item.source for item in transcript.segments])
    resolved = assemble_reviewed_transcript(
        raw,
        [resolved_by_id[item.source.segment_id] for item in transcript.segments],
    )
    return resolved, tuple(sorted(applied)), tuple(sorted(unapplied))


def load_result(job_id: str, result_root: Path | str = RESULT_ROOT) -> PersistedResult:
    """Read and validate one schema-v1 persisted result without changing it."""
    root = _validated_root(result_root)
    target = _target_path(root, _validated_job_id(job_id))
    if not target.is_dir():
        raise StorageError("persisted result does not exist")

    format_payload = _read_json(target, "format.json")
    if format_payload != {"schema_version": SCHEMA_VERSION}:
        raise StorageError("unsupported persisted-result schema version")
    metadata = _read_json(target, "metadata.json")
    raw_payload = _read_json(target, "raw_transcript.json")
    reviewed_payload = _read_json(target, "transcript.json")
    review_payload = _read_json(target, "review.json")
    summary_path = target / "summary.json"
    summary_payload = _read_json(target, "summary.json") if summary_path.exists() or summary_path.is_symlink() else None
    introduction_path = target / "introduction.json"
    introduction_payload = (
        _read_json(target, "introduction.json")
        if introduction_path.exists() or introduction_path.is_symlink()
        else None
    )

    if not isinstance(metadata, dict) or set(metadata) != {"job_id", "status", "source"}:
        raise StorageError("metadata schema is invalid")
    if metadata.get("job_id") != job_id or metadata.get("status") != "archived" or not isinstance(metadata.get("source"), str):
        raise StorageError("metadata values are invalid")
    if not isinstance(raw_payload, dict) or set(raw_payload) != {"segments", "final_text"}:
        raise StorageError("raw transcript schema is invalid")
    raw_items = raw_payload["segments"]
    if not isinstance(raw_items, list) or not isinstance(raw_payload["final_text"], str):
        raise StorageError("raw transcript values are invalid")
    try:
        raw = assemble_transcript([
            RawSegment(
                item["segment_id"], item["start_seconds"], item["end_seconds"],
                item["raw_text"], item["confidence"],
            )
            for item in raw_items
            if isinstance(item, dict) and set(item) == {"segment_id", "start_seconds", "end_seconds", "raw_text", "confidence"}
        ])
    except (KeyError, TypeError, ValueError, TranscriptAssemblyError) as exc:
        raise StorageError("raw transcript segments are invalid") from exc
    if len(raw.segments) != len(raw_items) or raw.final_text != raw_payload["final_text"]:
        raise StorageError("raw transcript final_text is invalid")

    if not isinstance(reviewed_payload, dict) or set(reviewed_payload) != {"segments", "final_text"}:
        raise StorageError("reviewed transcript schema is invalid")
    reviewed_items = reviewed_payload["segments"]
    if not isinstance(reviewed_items, list) or not isinstance(reviewed_payload["final_text"], str):
        raise StorageError("reviewed transcript values are invalid")
    by_id = {segment.segment_id: segment for segment in raw.segments}
    try:
        if len(reviewed_items) != len(raw.segments):
            raise ValueError("segment count differs")
        sources = [
            by_id[item["segment_id"]]
            for item in reviewed_items
            if isinstance(item, dict) and set(item) == {"segment_id", "start_seconds", "end_seconds", "text"}
            and item["start_seconds"] == by_id[item["segment_id"]].start_seconds
            and item["end_seconds"] == by_id[item["segment_id"]].end_seconds
        ]
        final_texts = [item["text"] for item in reviewed_items]
        reviewed = assemble_reviewed_transcript(raw, final_texts)
    except (KeyError, TypeError, ValueError, TranscriptAssemblyError) as exc:
        raise StorageError("reviewed transcript segments are invalid") from exc
    if len(sources) != len(raw.segments) or tuple(sources) != raw.segments or reviewed.final_text != reviewed_payload["final_text"]:
        raise StorageError("reviewed transcript alignment is invalid")

    base_summary = None if summary_payload is None else _summary_from_payload(summary_payload, set(by_id))
    introduction = None if introduction_payload is None else _introduction_from_payload(introduction_payload, reviewed)
    progress_events = _load_progress_events(target)
    if base_summary is None and introduction is None:
        raise StorageError("persisted result has no summary or introduction")
    if not isinstance(review_payload, dict) or set(review_payload) != {"review_items"} or not isinstance(review_payload["review_items"], list):
        raise StorageError("review schema is invalid")
    review_items = _review_items(tuple(review_payload["review_items"]))
    review_locations = _load_review_locations(target, review_items, reviewed)
    review_decisions = _load_review_decisions(target, review_items)
    resolved, applied_indices, unapplied_indices = _project_resolved_transcript(
        reviewed, review_decisions, review_locations
    )
    resolved_summary = _load_resolved_summary(target, resolved)
    return PersistedResult(
        job_id=job_id,
        status="archived",
        source=metadata["source"],
        transcript=reviewed,
        summary=base_summary,
        introduction=introduction,
        progress_events=progress_events,
        review_items=review_items,
        review_decisions=review_decisions,
        review_locations=review_locations,
        resolved_transcript=resolved,
        applied_review_indices=applied_indices,
        unapplied_review_indices=unapplied_indices,
        summary_is_stale=(
            resolved.final_text != reviewed.final_text and resolved_summary is None
        ),
        resolved_summary=resolved_summary,
    )
