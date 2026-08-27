"""Speech-to-text adapter and segment-standardization contract."""

import math
import pathlib
from typing import Mapping, Protocol

from .contracts import AudioArtifact, RawSegment, TranscriptionError


class SttEngine(Protocol):
    """Interface for an injected speech recognition engine.

    Engines are passed from the caller so that `transcribe_audio` itself
    stays free of model-loading and network dependencies.
    """

    def transcribe(self, audio_path: str) -> object:
        """Return raw segment data or raise an exception."""


def _is_finite_number(value: object) -> bool:
    """Check that *value* is a finite int/float but not a bool."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    if math.isfinite(float(value)):  # type: ignore[arg-type]
        return True
    return False


def _check_finite_number(value: object, name: str = "value") -> None:
    """Raise TranscriptionError if *value* is not a finite number."""
    if not _is_finite_number(value):
        raise TranscriptionError(
            f"{name} must be a finite int or float, not {type(value).__name__}"
        )


def transcribe_audio(audio: AudioArtifact, engine: SttEngine) -> list[RawSegment]:
    """Return ordered, valid timed segments from an injected local STT engine.

    Steps (in order):
      1. Validate ``audio`` type and ``engine.transcribe`` callability.
      2. Ensure ``audio.path`` exists as a regular file (not symlink).
      3. Call ``engine.transcribe(str(audio.path.resolve()))`` exactly once.
      4. Validate the returned container and each item mapping.
      5. Skip blank-text items; validate time/confidence/monotonicity for
         non-blank items.
      6. Build new RawSegment instances from validated items only.
      7. Return a flat list — never writes or deletes files.

    Raises:
        TypeError: *audio* is not AudioArtifact or *engine* lacks ``transcribe``.
        TranscriptionError: path/symlink errors, engine execution errors,
            invalid container, item schema violations, or time/monotonicity breaches.
    """
    # Step 1: Validate audio type
    if not isinstance(audio, AudioArtifact):
        raise TypeError("audio must be an AudioArtifact")

    # Step 1b: Validate engine callability (getattr with None default)
    transcribe_method = getattr(engine, "transcribe", None)
    if transcribe_method is None or not callable(transcribe_method):
        raise TypeError(
            f"engine does not have a callable transcribe method: {type(engine).__name__}"
        )

    # Step 2: path validation checks in order (symlink -> exists -> is_file)
    try:
        raw_path = pathlib.Path(audio.path)
    except (OSError, TypeError, ValueError) as exc:
        raise TranscriptionError(f"Invalid audio.path: {exc}") from exc

    try:
        is_symlink = raw_path.is_symlink()
    except (OSError, ValueError) as exc:
        raise TranscriptionError(f"Cannot check symlink status of {raw_path}: {exc}") from exc

    if is_symlink:
        raise TranscriptionError(f"audio.path must not be a symlink: {raw_path}")

    try:
        exists = raw_path.exists()
    except (OSError, ValueError) as exc:
        raise TranscriptionError(
            f"Cannot check existence of {raw_path}: {exc}"
        ) from exc

    if not exists:
        raise TranscriptionError(f"audio.path does not exist: {raw_path}")

    try:
        is_file = raw_path.is_file()
    except (OSError, ValueError) as exc:
        raise TranscriptionError(
            f"Cannot check file status of {raw_path}: {exc}"
        ) from exc

    if not is_file:
        raise TranscriptionError(f"audio.path is not a regular file: {raw_path}")

    try:
        resolved_raw = raw_path.resolve()
    except (OSError, ValueError) as exc:
        raise TranscriptionError(
            f"Cannot resolve audio path from {raw_path}: {exc}"
        ) from exc
    resolved_str = str(resolved_raw)

    # Step 3: Call engine.transcribe() exactly once, with exception translation
    try:
        raw_output = engine.transcribe(resolved_str)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        raise TranscriptionError(
            f"Engine {engine!r}.transcribe failed"
        ) from exc

    # Step 4a: Validate returned container
    if not isinstance(raw_output, (list, tuple)):
        raise TranscriptionError(
            f"engine returned {type(raw_output).__name__}; expected list or tuple"
        )

    # Step 4b-6: Process each item
    seen_start: float = -1.0
    seen_end: float = -1.0
    results: list[RawSegment] = []
    segment_counter = 0

    for item in raw_output:
        if not isinstance(item, Mapping):
            raise TranscriptionError(
                f"engine item must be a Mapping, not {type(item).__name__}"
            )
        has_start = "start" in item
        has_end = "end" in item
        has_text = "text" in item

        if not (has_start and has_end and has_text):
            raise TranscriptionError(
                f"segment item is missing required keys: {list(item.keys())}"
            )

        start_val = item["start"]
        end_val = item["end"]
        text = item["text"]

        # text must be str
        if not isinstance(text, str):
            raise TranscriptionError(
                f"text must be a str, not {type(text).__name__}"
            )

        # Step 5: Skip blank-text items (use strip() only for blank check)
        if text.strip() == "":
            continue

        # Validate start/end: finite number >= 0
        _check_finite_number(start_val, "start")
        _check_finite_number(end_val, "end")

        sv = float(start_val)
        ev = float(end_val)

        if sv < 0 or ev < 0:
            raise TranscriptionError("start/end must be >= 0")
        if ev <= sv:
            raise TranscriptionError(
                f"end ({ev}) must be strictly greater than start ({sv})"
            )

        # Step 5b: Monotonicity check — each segment's times must be
        # >= previous segment's times
        if sv < seen_start or ev < seen_end:
            raise TranscriptionError(
                "Start/end values are not strictly increasing "
                f"(prev end={seen_end}, current start={sv})."
            )
        seen_start = sv
        seen_end = ev

        # Step 5c: Validate confidence (optional)
        conf = None
        if "confidence" in item:
            conf_val = item["confidence"]
            if conf_val is not None:
                _check_finite_number(conf_val, "confidence")
                cf = float(conf_val)
                if cf < 0 or cf > 1:
                    raise TranscriptionError(
                        f"confidence must be in [0, 1], not {cf}"
                    )
                conf = cf

        # Step 6: Build result (counter after blank skip)
        segment_counter += 1
        seg_id = f"segment-{segment_counter:04d}"
        results.append(
            RawSegment(
                segment_id=seg_id,
                start_seconds=sv,
                end_seconds=ev,
                raw_text=text,
                confidence=conf,
            )
        )

    # Step 7: Return list (empty is valid)
    return results
