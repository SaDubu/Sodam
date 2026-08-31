"""Measured progress and ETA calculation for setup and pipeline operations."""

from collections.abc import Sequence
import math
from numbers import Real
from typing import Protocol

from .contracts import ProgressEvent, ProgressStage, ProgressStateError


_TERMINAL_STAGES = {"completed", "failed", "cancelled"}
_STAGE_WEIGHTS: dict[str, float] = {
    "environment_check": 1,
    "dependency_install": 2,
    "model_download": 8,
    "source_validation": 1,
    "source_acquisition": 5,
    "audio_extraction": 4,
    "transcription": 30,
    "text_protection": 3,
    "rule_normalization": 5,
    "correction": 15,
    "review_validation": 5,
    "transcript_assembly": 3,
    "summarization": 8,
    "introduction": 8,
    "persistence": 1,
    "cleanup": 1,
}
_TOTAL_WEIGHT = sum(_STAGE_WEIGHTS.values())


def _finite_non_negative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return converted


class ProgressSink(Protocol):
    """Receive validated progress events without controlling product state."""

    def emit(self, event: ProgressEvent) -> None:
        """Deliver one event whose sequence is newer than the previous event."""
        ...


class Clock(Protocol):
    """Provide monotonic elapsed time and a UTC timestamp for deterministic tests."""

    def monotonic(self) -> float:
        """Return a monotonic time value in seconds."""
        ...

    def utc_timestamp(self) -> str:
        """Return the current UTC timestamp in ISO 8601 form."""
        ...


class ProgressTracker:
    """Build monotonic stage and overall progress events for one operation."""

    def __init__(
        self,
        operation_id: str,
        scope: str,
        sink: ProgressSink,
        clock: Clock,
    ) -> None:
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise TypeError("operation_id must be a non-blank string")
        if not isinstance(scope, str) or scope not in {"setup", "job"}:
            raise ValueError("scope must be setup or job")
        if not callable(getattr(sink, "emit", None)):
            raise TypeError("sink must provide emit")
        if not callable(getattr(clock, "monotonic", None)) or not callable(
            getattr(clock, "utc_timestamp", None)
        ):
            raise TypeError("clock must provide monotonic and utc_timestamp")
        self._operation_id = operation_id
        self._scope = scope
        self._sink = sink
        self._clock = clock
        self._started_at = _finite_non_negative(clock.monotonic(), "clock.monotonic()")
        self._sequence = 0
        self._current_stage: str | None = None
        self._current_total: float | None = None
        self._completed_units: float | None = None
        self._samples: list[tuple[float, float]] = []
        self._completed_weight = 0.0
        self._last_overall: float | None = None
        self._terminal = False

    def _ensure_active(self) -> None:
        if self._terminal:
            raise ProgressStateError("progress tracker is terminal")
        if self._current_stage is None:
            raise ProgressStateError("a stage must be started first")

    def _emit(
        self,
        stage: str,
        stage_progress: float | None,
        completed_units: float | None,
        total_units: float | None,
        message: str,
        can_cancel: bool,
        eta_seconds: float | None,
    ) -> ProgressEvent:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if stage_progress is not None:
            stage_progress = min(1.0, max(0.0, stage_progress))
        overall: float | None
        if stage in _STAGE_WEIGHTS and stage_progress is not None:
            overall = (self._completed_weight + _STAGE_WEIGHTS[stage] * stage_progress) / _TOTAL_WEIGHT
            if self._last_overall is not None:
                overall = max(self._last_overall, overall)
            overall = min(1.0, overall)
            self._last_overall = overall
        elif stage == "completed":
            overall = 1.0
            self._last_overall = overall
        else:
            overall = None
        now = _finite_non_negative(self._clock.monotonic(), "clock.monotonic()")
        elapsed = max(0.0, now - self._started_at)
        self._sequence += 1
        event = ProgressEvent(
            operation_id=self._operation_id,
            scope=self._scope,
            stage=stage,  # type: ignore[arg-type]
            stage_label=stage,
            stage_progress=stage_progress,
            overall_progress=overall,
            completed_units=completed_units,
            total_units=total_units,
            elapsed_seconds=elapsed,
            eta_seconds=eta_seconds,
            message=message,
            can_cancel=can_cancel,
            sequence=self._sequence,
            timestamp=self._clock.utc_timestamp(),
        )
        self._sink.emit(event)
        return event

    def start_stage(
        self,
        stage: ProgressStage,
        total_units: float | None = None,
        message: str = "",
    ) -> ProgressEvent:
        self._ensure_active_start()
        if not isinstance(stage, str):
            raise TypeError("stage must be a string")
        if stage not in _STAGE_WEIGHTS:
            raise ValueError("stage must be a supported non-terminal stage")
        if total_units is not None:
            total_units = _finite_non_negative(total_units, "total_units")
        if self._current_stage is not None:
            self._completed_weight += _STAGE_WEIGHTS[self._current_stage]
        self._current_stage = stage
        self._current_total = total_units
        self._completed_units = 0.0 if total_units is not None else None
        self._samples = []
        fraction = 1.0 if total_units == 0 else (0.0 if total_units is not None else None)
        return self._emit(stage, fraction, self._completed_units, total_units, message, True, None)

    def _ensure_active_start(self) -> None:
        if self._terminal:
            raise ProgressStateError("progress tracker is terminal")

    def advance(self, completed_units: float, message: str = "") -> ProgressEvent:
        self._ensure_active()
        completed = _finite_non_negative(completed_units, "completed_units")
        previous = self._completed_units
        if previous is not None and completed < previous:
            raise ValueError("completed_units must not decrease")
        if self._current_total is not None and completed > self._current_total:
            raise ValueError("completed_units cannot exceed total_units")
        self._completed_units = completed
        now = _finite_non_negative(self._clock.monotonic(), "clock.monotonic()")
        self._samples.append((now, completed))
        fraction = None if self._current_total is None else (
            1.0 if self._current_total == 0 else completed / self._current_total
        )
        remaining = None if self._current_total is None else max(0.0, self._current_total - completed)
        eta = estimate_eta(self._samples, remaining) if remaining is not None else None
        return self._emit(
            self._current_stage or "failed", fraction, completed, self._current_total, message, True, eta
        )

    def finish(self, stage: ProgressStage, message: str = "") -> ProgressEvent:
        self._ensure_active()
        if not isinstance(stage, str):
            raise TypeError("stage must be a string")
        if stage not in _TERMINAL_STAGES:
            raise ValueError("finish stage must be completed, failed, or cancelled")
        self._terminal = True
        if stage == "completed":
            self._completed_weight = _TOTAL_WEIGHT
            return self._emit(stage, 1.0, None, None, message, False, 0.0)
        return self._emit(stage, None, None, None, message, False, None)


def estimate_eta(
    samples: Sequence[tuple[float, float]],
    remaining_units: float,
) -> float | None:
    """Estimate remaining seconds from the most recent measured throughput."""
    remaining = _finite_non_negative(remaining_units, "remaining_units")
    if remaining == 0:
        return 0.0
    if not isinstance(samples, Sequence):
        raise TypeError("samples must be a sequence")
    if len(samples) < 2:
        return None
    previous_time: float | None = None
    previous_units: float | None = None
    for sample in samples:
        if not isinstance(sample, Sequence) or len(sample) != 2:
            raise TypeError("each sample must contain time and completed units")
        sample_time = _finite_non_negative(sample[0], "sample time")
        sample_units = _finite_non_negative(sample[1], "sample units")
        if previous_time is not None and sample_time < previous_time:
            raise ValueError("sample times must not decrease")
        if previous_units is not None and sample_units < previous_units:
            raise ValueError("sample units must not decrease")
        previous_time, previous_units = sample_time, sample_units
    assert previous_time is not None and previous_units is not None
    first_time = _finite_non_negative(samples[-2][0], "sample time")
    first_units = _finite_non_negative(samples[-2][1], "sample units")
    elapsed = previous_time - first_time
    completed = previous_units - first_units
    if elapsed <= 0 or completed <= 0:
        return None
    eta = remaining * elapsed / completed
    return eta if math.isfinite(eta) and eta >= 0 else None
