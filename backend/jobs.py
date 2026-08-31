"""Job creation, status transitions, and cancellation contracts.

Implements B02 contracts: create_job, transition_job, request_cancellation.
All functions return new frozen Job instances without side-effects.
"""

from __future__ import annotations

import pathlib
import uuid
from dataclasses import replace
from urllib.parse import urlparse


from .contracts import (
    InputSourceError,
    Job,
    JobOptions,
    JobStateError,
    JobStatus,
)

# -- allowed transitions per B02 Section 4 --

_TRANSITION_TABLE: dict[str, frozenset[str]] = {
    "queued": frozenset({"acquiring", "cancelling", "failed"}),
    "acquiring": frozenset({"extracting", "cancelling", "failed"}),
    "extracting": frozenset({"transcribing", "cancelling", "failed"}),
    "transcribing": frozenset({"normalizing", "cancelling", "failed"}),
    "normalizing": frozenset({"correcting", "cancelling", "failed"}),
    "correcting": frozenset({"reviewing", "cancelling", "failed"}),
    "reviewing": frozenset({"summarizing", "cancelling", "failed"}),
    "summarizing": frozenset({"completed", "cancelling", "failed"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "completed": frozenset({"cleaning"}),
    "cancelled": frozenset({"cleaning"}),
    "failed": frozenset({"cleaning"}),
    "cleaning": frozenset({"archived"}),
}

# Work directory root — must exist *outside* the Git work tree
_WORK_DIR_ROOT: pathlib.Path = pathlib.Path(r"D:\AI-Legion\Sodam-data\tmp\jobs")

# Cancel-able source states per B02 Section 4 (request_cancellation)
_CANCELABLE_STATES: frozenset[str] = frozenset(
    {
        "queued",
        "acquiring",
        "extracting",
        "transcribing",
        "normalizing",
        "correcting",
        "reviewing",
        "summarizing",
    }
)


def _normalize_source(source: str, options: JobOptions) -> str:
    """Validate and normalise *source* per B02 §4 create_job contract."""

    # source must be a non-blank str
    if not isinstance(source, str):
        raise InputSourceError(f"source must be str, got {type(source).__name__}")
    stripped = source.strip()
    if not stripped:
        raise InputSourceError("source is empty after stripping whitespace")

    # options must be JobOptions instance
    if not isinstance(options, JobOptions):
        raise TypeError(
            f"options must be JobOptions, got {type(options).__name__}"
        )

    is_windows_drive_absolute = (
        len(stripped) >= 3
        and stripped[0].isalpha()
        and stripped[1] == ":"
        and stripped[2] in ("\\", "/")
    )
    parsed = urlparse(stripped)
    scheme = "" if is_windows_drive_absolute else parsed.scheme.lower()

    # http/https URL case → verify hostname not empty
    if scheme in ("http", "https"):
        netloc = parsed.netloc.split("@")[-1]
        hostname = netloc.split(":")[0].lower()
        if not hostname:
            raise InputSourceError(
                f"http(s) URL has no valid hostname: {stripped!r}"
            )
        return stripped

    # unsupported schemes with scheme present (ftp, file, data, etc.)
    if scheme != "":
        raise InputSourceError(
            f"unsupported source scheme ({scheme}): {stripped!r}"
        )

    # local file path case — must exist and be a regular file
    try:
        raw_path = pathlib.Path(stripped).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise InputSourceError(
            f"local source does not exist: {stripped!r}"
        ) from exc
    except OSError:
        raise InputSourceError(
            f"invalid local-path syntax (not a valid file path): {stripped!r}"
        )

    if not raw_path.is_file():
        raise InputSourceError(
            f"local source is not an existing file: {stripped!r}"
        )
    return str(raw_path)


def _ensure_valid_transition(job: Job, target_status: str) -> None:
    """Validate transition permission per B02 §4 table."""

    if not isinstance(job, Job):
        raise TypeError(f"job must be Job, got {type(job).__name__}")

    # Valid statuses per B02 Table 1
    VALID_STATUSES = frozenset(
        ("queued", "acquiring", "extracting", "transcribing",
         "normalizing", "correcting", "reviewing", "summarizing",
         "completed", "cancelling", "cancelled", "failed",
         "cleaning", "archived")
    )
    if not isinstance(target_status, str) or target_status not in VALID_STATUSES:
        raise TypeError(
            f"target_status must be a valid JobStatus string, got {target_status!r}"
        )

    current = job.status
    # identical-to-same not allowed
    if target_status == current:
        raise JobStateError(
            f"transition from {current!r} to {target_status!r} is not permitted"
        )

    allowed = _TRANSITION_TABLE.get(current)
    if not allowed or target_status not in allowed:
        raise JobStateError(
            f"no transition from {current!r} to {target_status!r}"
        )


def create_job(source: str, options: JobOptions) -> Job:
    """Create a queued job for a readable local path or supported URL.

    Contract (B02 §4):
      - Normalise and validate *source*.
      - Allocate a work_dir under the fixed parent root.
      - Return a new frozen Job with status="queued".
      - Raises InputSourceError on bad source, TypeError on wrong options type.
      - NO side-effects: no directory/file creation, DB writes, network calls.
    """

    normalised = _normalize_source(source, options)

    job_id = uuid.uuid4().hex
    work_dir = _WORK_DIR_ROOT / job_id

    return Job(
        job_id=job_id,
        source=normalised,
        status="queued",
        work_dir=work_dir,
        options=options,
    )


def transition_job(job: Job, target_status: JobStatus) -> Job:
    """Return a new frozen Job with the requested status, without mutating *job*.

    Per B02 §4:
      - Validates permission table.
      - Raises TypeError on bad inputs, JobStateError on illegal transition.
      - Returns NEW instance (via dataclasses.replace).
    """
    _ensure_valid_transition(job, target_status)

    return replace(job, status=target_status)


def request_cancellation(job: Job) -> Job:
    """Move *job* to "cancelling" only from allowed running states.

    Per B02 §4:
      - Allowed from: queued + all intermediate running states.
      - Not allowed from: cancelling, completed, cancelled, failed, cleaning, archived.
      - Delegates the actual transition to transition_job().
    """
    _ensure_valid_transition(job, "cancelling")

    if not isinstance(job, Job):
        raise TypeError(f"job must be Job, got {type(job).__name__}")

    current = job.status

    # B02 §4: cancellation only from queued or executing states
    if current not in _CANCELABLE_STATES:
        raise JobStateError(
            f"cannot request cancellation from {current!r}"
        )

    return transition_job(job, "cancelling")
