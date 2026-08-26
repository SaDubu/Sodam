"""URL source validation and temporary audio-acquisition contracts."""

import pathlib
from pathlib import Path
from typing import Protocol

from urllib.parse import urlsplit, parse_qs

from .contracts import (
    AudioArtifact,
    InputSourceError,
    Job,
    UnsafePathError,
)

# Import the B03 work-dir validator — required by SoS Section 5 item 4
from .storage import _validate_job_work_dir


_ALLOWED_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
})


# ---------------------------------------------------------------------------
# SourceAudioAdapter protocol
# ---------------------------------------------------------------------------

class SourceAudioAdapter(Protocol):
    """External adapter that acquires a single audio file for a source URL."""

    def acquire(self, source_url: str, destination: pathlib.Path) -> None:
        """Write one acquired audio file to *destination* or raise an exception."""


# ---------------------------------------------------------------------------
# validate_source  (compliant with SoS Section 4)
# ---------------------------------------------------------------------------

def validate_source(source: str) -> None:
    """Validate a supported, user-authorized URL without contacting it.

    Invalid, unsupported, or malformed sources must raise ``InputSourceError``.
    Platform-specific retrieval is deliberately outside this declaration.
    """
    # -- 1. type / emptiness -------------------------------------------
    if not isinstance(source, str):
        raise InputSourceError("source must be a str")

    if source != source.strip() or source == "":
        raise InputSourceError(
            "source must not have leading/trailing whitespace and may not be empty"
        )

    # -- 2. parse -------------------------------------------------------
    try:
        parts = urlsplit(source)

        # Scheme check
        if parts.scheme.lower() not in ("http", "https"):
            raise InputSourceError(f"unsupported scheme: {parts.scheme}")

        # No userinfo
        if parts.username is not None or parts.password is not None:
            raise InputSourceError("URL must not contain userinfo")

        # No fragment
        if parts.fragment != "":
            raise InputSourceError("URL must not contain a fragment")

        # No explicit port (urlsplit stores hostname only; port is separate)
        if parts.port is not None:
            raise InputSourceError("URL must not contain an explicit port")
    except ValueError as exc:
        raise InputSourceError(str(exc)) from exc

    # -- 3. host check
    hostname = (parts.hostname or "").lower()

    if hostname not in _ALLOWED_HOSTS:
        raise InputSourceError(f"unsupported host: {hostname}")

    # -- 4. path check by host ------------------------------------------
    if hostname == "youtu.be":
        # /<video_id> — exactly one non-empty segment
        segments = [s for s in parts.path.split("/") if s != "" and s is not None]
        if not segments:
            raise InputSourceError(
                "youtu.be must have a non-empty video ID path segment"
            )

    elif hostname in (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    ):
        # Normalise: urlsplit may leave empty trailing slash as [""] but not []
        segments = [s for s in parts.path.split("/") if s != "" and s is not None]

        if not segments:
            raise InputSourceError("YouTube path must not be empty")

        first_path = segments[0]

        if first_path == "watch":
            # /watch?v=<vid> — 'v' qparam required, non-empty
            qs = parse_qs(parts.query)  # keys are always lower-case
            v_vals = qs.get("v")
            if not v_vals or v_vals[0] == "":
                raise InputSourceError(
                    "/watch must have a non-empty 'v' query parameter"
                )

        elif first_path == "shorts":
            # /shorts/<non-empty-id>
            if len(segments) < 2:
                raise InputSourceError("/shorts must have a non-empty ID")

        elif first_path == "embed":
            if len(segments) < 2:
                raise InputSourceError("/embed must have a non-empty ID")

        elif first_path == "live":
            if len(segments) < 2:
                raise InputSourceError("/live must have a non-empty ID")

        else:
            raise InputSourceError(
                f"unsupported YouTube path segment: {first_path!r}"
            )


# ---------------------------------------------------------------------------
# acquire_source_audio  (SoS Section 5-7)
# ---------------------------------------------------------------------------

def acquire_source_audio(job: Job, adapter: SourceAudioAdapter) -> AudioArtifact:
    """Acquire audio for *job* via the provided *adapter*.

    Raises TypeError / InputSourceError / UnsafePathError per SoS Section 4.
    """
    # -- 1. Type checks -----------------------------------------------
    if not isinstance(job, Job):
        raise TypeError("job must be a Job")

    if not callable(getattr(adapter, "acquire", None)):
        raise TypeError(
            f"adapter must have an 'acquire' callable; got {type(adapter).__name__}"
        )

    # -- 2. source validation -----------------------------------------
    validate_source(job.source)

    # -- 3. work-dir validation (B03) — UnsafePathError is propagated ---
    _validate_job_work_dir(job)

    # -- 3b. Create work directory — OSError → InputSourceError ----------
    try:
        pathlib.Path(job.work_dir).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputSourceError(str(exc)) from exc

    # -- 4. determine target path & guard against overwrite / symlink ----
    work = pathlib.Path(job.work_dir)
    dest = work / Path("source-audio.wav")

    if dest.exists():
        raise UnsafePathError(
            f"destination already exists: {dest!r}"
        )

    if dest.is_symlink():
        raise UnsafePathError(
            f"destination is a symlink: {dest!r}"
        )

    try:
        # -- 5. call adapter (exactly once) ----------------------------
        adapter.acquire(job.source, dest)
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        raise InputSourceError(str(exc)) from exc

    # -- 6. re-verify file after write --------------------------------
    if not dest.exists():
        raise UnsafePathError(
            f"destination does not exist after adapter call: {dest!r}"
        )

    if dest.is_symlink():
        raise UnsafePathError(
            f"destination became a symlink after write: {dest!r}"
        )

    # ensure path is still inside job.work_dir  (Section 5 item 6)
    resolved = dest.resolve()
    work_resolved = pathlib.Path(work).resolve()
    if not resolved.is_relative_to(work_resolved):
        raise UnsafePathError(
            f"acquired file escaped work directory: {resolved!r}"
        )

    # -- 7. return ---------------------------------------------------
    return AudioArtifact(
        job_id=job.job_id,
        path=resolved,
        duration_seconds=None,
    )
