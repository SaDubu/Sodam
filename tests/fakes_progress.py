"""Deterministic collaborators for progress and ETA unit tests."""

from datetime import datetime, timedelta, timezone
import math
from numbers import Real

from backend.contracts import ProgressEvent


def _finite_non_negative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return converted


class FakeClock:
    """Manually advanced monotonic and UTC clock with no system-clock access."""

    def __init__(self, monotonic_seconds: float = 0.0) -> None:
        self._seconds = _finite_non_negative(monotonic_seconds, "monotonic_seconds")

    def monotonic(self) -> float:
        return self._seconds

    def utc_timestamp(self) -> str:
        instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self._seconds)
        return instant.isoformat().replace("+00:00", "Z")

    def advance(self, seconds: float) -> None:
        self._seconds += _finite_non_negative(seconds, "seconds")


class RecordingProgressSink:
    """Record validated ProgressEvent references in arrival order."""

    def __init__(self) -> None:
        self._events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        if not isinstance(event, ProgressEvent):
            raise TypeError("event must be a ProgressEvent")
        self._events.append(event)

    @property
    def events(self) -> tuple[ProgressEvent, ...]:
        return tuple(self._events)
