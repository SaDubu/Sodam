"""Persistence, transcript assembly, and safe-cleanup contracts."""

import json
import math
import pathlib
import shutil
from typing import Any

from .contracts import (
    CleanupPolicy,
    CleanupReport,
    Job,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
    StorageError,
    Transcript,
    TranscriptAssemblyError,
    UnsafePathError,
)

from .runtime_paths import JOB_WORK_ROOT


# ---- internal helpers ----


def _validate_job(job: Any) -> None:
    """Raise TypeError if *job* is not a valid Job instance."""
    if not isinstance(job, Job):
        raise TypeError("job must be an instance of contracts.Job")


def _validate_artifact_name(artifact_name: str) -> None:
    """Raise UnsafePathError on forbidden artifact names.

    Allowed: non-empty, single filename (no separators), ends with '.json'.
    Forbidden: path separator, '.', '..', absolute path, symlink traversal.
    """
    if not artifact_name or not isinstance(artifact_name, str):
        raise UnsafePathError("artifact_name must be a non-empty string")
    if "/" in artifact_name or "\\" in artifact_name:
        raise UnsafePathError("artifact_name must be a single file name (no separators)")
    if artifact_name.startswith(".") or artifact_name == ".":
        raise UnsafePathError("artifact_name may not start with '.'")
    if ".." in artifact_name:
        raise UnsafePathError("artifact_name may not contain '..'")
    if pathlib.PurePosixPath(artifact_name).is_absolute():
        raise UnsafePathError("artifact_name must not be an absolute path")
    if not artifact_name.endswith(".json"):
        raise UnsafePathError("artifact_name must end with '.json'")


def _validate_job_work_dir(job: Job) -> pathlib.Path:
    """Verify job work_dir is a direct child of JOB_WORK_ROOT with matching ID.

    Returns the resolved, normalised work directory Path.  Raises
    UnsafePathError on any security violation.
    """
    _validate_job(job)
    work = job.work_dir.resolve()
    root = JOB_WORK_ROOT.resolve()

    # Must be a direct child: work must equal ROOT / job_id
    if not work.parents:
        raise UnsafePathError("work_dir cannot be resolved")

    if not work.is_relative_to(root):
        raise UnsafePathError(
            "job.work_dir must be inside the job working root"
        )

    # Must be exactly one level below (direct child)
    rel = work.relative_to(root)
    if len(rel.parts) != 1:
        raise UnsafePathError("job.work_dir must be a direct child of JOB_WORK_ROOT")

    # Directory name must match job.job_id exactly
    if str(rel) != job.job_id:
        raise UnsafePathError(
            "job.work_dir directory name must equal job.job_id"
        )

    return work


def _is_safe_under(path: pathlib.Path, base: pathlib.Path) -> bool:
    """Return True if *path* resolves inside *base*."""
    # resolve() follows symlinks (if any); works on non-existent paths too since we only call this on existing paths or just-created targets.
    target = path.resolve()
    # is_relative_to can raise ValueError when base does not exist — treat that as safe for write-time
    try:
        return target.is_relative_to(base)
    except ValueError:
        return True


def _assert_safe_under(path: pathlib.Path, artifact_name: str, work: pathlib.Path, context: str) -> None:
    """Raise UnsafePathError if *path* resolved outside *work*."""
    try:
        target = path.resolve()
        if not target.is_relative_to(work):
            raise UnsafePathError(f"{context} artifact resolves outside job.work_dir: {artifact_name}")
    except ValueError:  # work does not exist — can't verify; caller already validated parent
        pass


def _assert_artifact_in_work(artifact_path: pathlib.Path, work_dir: pathlib.Path) -> None:
    """Ensure *artifact_path* resolves strictly inside *work_dir*.

    Uses :py:meth:`pathlib.Path.is_relative_to` (not ``startswith`` strings).
    Raises :class:`contracts.UnsafePathError` on any violation.
    """
    real = artifact_path.resolve()
    if not real.is_relative_to(work_dir):
        raise UnsafePathError(
            f"artifact resolves outside job.work_dir: {artifact_path}"
        )


# ---- public API (B03) ----


def write_job_json(job: Job, artifact_name: str, payload: Any) -> pathlib.Path:
    """Write *payload* as UTF-8 JSON into *job*'s work directory.

    Returns the absolute Path to the written file.
    """
    work = _validate_job_work_dir(job)
    _validate_artifact_name(artifact_name)

    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"work directory creation failed: {exc}") from exc

    target = work / artifact_name

    # Resolve to confirm no symlink traversal during write path — check inside *work*
    _assert_artifact_in_work(target, work)

    try:
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (TypeError, ValueError) as exc:
        raise StorageError(f"payload JSON encoding failed: {exc}") from exc
    except OSError as exc:
        raise StorageError(f"artifact write failed: {exc}") from exc

    return target


def read_job_json(job: Job, artifact_name: str) -> Any:
    """Read and decode the JSON artifact for *job*.*artifact_name*.

    Returns the deserialized Python object.
    """
    work = _validate_job_work_dir(job)
    _validate_artifact_name(artifact_name)

    target = work / artifact_name

    # Guard against symlink traversal at read time
    if target.is_symlink():
        _assert_artifact_in_work(target, work)
    elif not target.exists():
        raise StorageError(f"artifact does not exist: {artifact_name}")

    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"artifact read failed: {exc}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(f"artifact JSON decode failed: {exc}") from exc


def cleanup_artifacts(
    job: Job, policy: CleanupPolicy
) -> CleanupReport:
    """Apply *policy* inside the job work directory and return a report."""
    _validate_job(job)

    if not isinstance(policy, CleanupPolicy):
        raise TypeError("policy must be an instance of contracts.CleanupPolicy")

    # Validate retain names before touching anything
    for name in policy.retain_artifact_names:
        _validate_artifact_name(name)

    work = _validate_job_work_dir(job)

    # No work directory -> empty report
    if not work.exists():
        return CleanupReport()

    # Collect items inside the work directory
    try:
        entries = [e for e in work.iterdir()]
    except OSError as exc:
        raise StorageError(f"work directory iteration failed: {exc}") from exc

    retain_names = set(policy.retain_artifact_names)
    retained_paths: list[pathlib.Path] = []
    remove_list: list[pathlib.Path] = []
    removed_paths: list[pathlib.Path] = []

    for entry in entries:
        basename = entry.name
        if basename in retain_names:
            # Symlink check *must* apply equally to retained artifacts (same test)
            if entry.is_symlink():
                _assert_artifact_in_work(entry, work)
            retained_paths.append(entry.resolve())
        elif entry.is_symlink():
            # Verify symlink target stays inside *work_dir* (not JOB_WORK_ROOT)
            _assert_artifact_in_work(entry, work)
            remove_list.append(entry)
        else:
            remove_list.append(entry)

    # Post-order deletion (files before parent directories)
    def _postorder(paths: list[pathlib.Path]) -> list[pathlib.Path]:
        """Sort so children are processed before parents."""
        def _sort_key(p: pathlib.Path) -> tuple[int, int]:
            try:
                rel = p.resolve().relative_to(work.resolve())
                return (-len(rel.parts), str(rel))  # deeper first
            except ValueError:
                return (0, str(p))

        return sorted(paths, key=_sort_key)

    for item in _postorder(remove_list):
        try:
            if item.is_symlink():
                item.unlink()
            elif item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
            else:
                pass  # non-existent race guard
            removed_paths.append(item.resolve())
        except OSError as exc:
            raise StorageError(f"artifact deletion failed: {item}: {exc}") from exc

    # If no retained artifacts and policy allows, remove empty work dir
    if (not retained_paths and policy.remove_empty_work_dir):
        try:
            removed_paths.append(work.resolve())
            shutil.rmtree(work)
        except OSError as exc:
            raise StorageError(f"work directory removal failed: {exc}") from exc

    return CleanupReport(
        retained=tuple(retained_paths),
        removed=tuple(removed_paths),
    )


def _validate_segments(segments) -> None:
    """Validate the segment list contract (types only)."""
    if not isinstance(segments, list):
        raise TypeError("segments must be a list")
    for segment in segments:
        if not isinstance(segment, RawSegment):
            raise TypeError("every segment must be a RawSegment")


def _validate_finite_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TranscriptAssemblyError("%s must be a finite int or float" % name)
    number = float(value)
    if not math.isfinite(number):
        raise TranscriptAssemblyError("%s must be finite" % name)
    return number


def assemble_transcript(segments: list[RawSegment]) -> Transcript:
    """Assemble valid time-ordered segments into a transcript and time index.

    Rejects missing/duplicate IDs and reverse timing; it does not repair
    those input errors implicitly.
    """
    _validate_segments(segments)
    if not segments:
        return Transcript(segments=(), final_text="")

    seen_ids: set[str] = set()
    previous_start: float | None = None
    previous_end: float | None = None

    for segment in segments:
        segment_id = segment.segment_id
        if (
            not isinstance(segment_id, str)
            or not segment_id
            or segment_id != segment_id.strip()
        ):
            raise TranscriptAssemblyError(
                "segment_id must be a non-blank str without surrounding whitespace"
            )
        if segment_id in seen_ids:
            raise TranscriptAssemblyError("duplicate segment_id: %r" % (segment_id,))
        seen_ids.add(segment_id)

        start = _validate_finite_number(segment.start_seconds, "start_seconds")
        end = _validate_finite_number(segment.end_seconds, "end_seconds")
        if start < 0:
            raise TranscriptAssemblyError("start_seconds must be >= 0")
        if end <= start:
            raise TranscriptAssemblyError("end_seconds must be greater than start_seconds")

        if previous_start is not None and (start < previous_start or end < previous_end):
            raise TranscriptAssemblyError("segments must not move backwards in time")
        previous_start = start
        previous_end = end

        raw_text = segment.raw_text
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise TranscriptAssemblyError("raw_text must be a non-blank str")

        confidence = segment.confidence
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise TranscriptAssemblyError("confidence must be None or a finite number")
            confidence_value = float(confidence)
            if not math.isfinite(confidence_value) or not (0 <= confidence_value <= 1):
                raise TranscriptAssemblyError("confidence must be between 0 and 1")

    final_text = "\n".join(segment.raw_text for segment in segments)
    return Transcript(segments=tuple(segments), final_text=final_text)


def assemble_reviewed_transcript(
    transcript: Transcript,
    approved_segment_texts: list[str],
) -> ReviewedTranscript:
    """Pair approved segment text with a validated source transcript.

    The source ``RawSegment`` objects are retained unchanged so their IDs and
    timestamps remain the evidence basis for later reviewed-text summarization.
    """
    if not isinstance(transcript, Transcript):
        raise TypeError("transcript must be a Transcript")
    if not isinstance(approved_segment_texts, list):
        raise TypeError("approved_segment_texts must be a list")
    if not isinstance(transcript.segments, tuple):
        raise TranscriptAssemblyError("transcript.segments must be a tuple")
    if not isinstance(transcript.final_text, str):
        raise TranscriptAssemblyError("transcript.final_text must be a str")

    validated_source = assemble_transcript(list(transcript.segments))
    if transcript.final_text != validated_source.final_text:
        raise TranscriptAssemblyError(
            "transcript.final_text must match its source segment text"
        )
    if len(approved_segment_texts) != len(transcript.segments):
        raise TranscriptAssemblyError(
            "approved_segment_texts must match transcript segment count"
        )
    for text in approved_segment_texts:
        if not isinstance(text, str) or not text.strip():
            raise TranscriptAssemblyError(
                "approved segment text must be a non-blank str"
            )

    reviewed_segments = tuple(
        ReviewedSegment(source=segment, final_text=text)
        for segment, text in zip(transcript.segments, approved_segment_texts)
    )
    return ReviewedTranscript(
        segments=reviewed_segments,
        final_text="\n".join(approved_segment_texts),
    )
