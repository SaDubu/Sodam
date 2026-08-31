"""Tests for V2-P01 measured progress and ETA calculation."""

import math

import pytest

from backend.contracts import ProgressStateError
from backend.progress import ProgressTracker, estimate_eta
from tests.fakes_progress import FakeClock, RecordingProgressSink


def tracker() -> tuple[ProgressTracker, FakeClock, RecordingProgressSink]:
    clock = FakeClock()
    sink = RecordingProgressSink()
    return ProgressTracker("op-1", "job", sink, clock), clock, sink


def test_known_total_progress_is_determinate_and_monotonic() -> None:
    progress, clock, sink = tracker()
    first = progress.start_stage("transcription", 10, "start")
    clock.advance(2)
    middle = progress.advance(5, "half")
    clock.advance(2)
    last = progress.advance(10, "done")
    assert first.stage_progress == 0
    assert middle.stage_progress == 0.5
    assert last.stage_progress == 1
    assert all(event.sequence == index for index, event in enumerate(sink.events, 1))
    assert [event.overall_progress for event in sink.events] == sorted(
        event.overall_progress for event in sink.events if event.overall_progress is not None
    )
    assert last.elapsed_seconds == 4


def test_zero_and_unknown_totals() -> None:
    progress, _, _ = tracker()
    zero = progress.start_stage("cleanup", 0)
    assert zero.stage_progress == 1
    progress.start_stage("transcription", None)
    current = progress.advance(3)
    assert current.stage_progress is None
    assert current.overall_progress is None
    assert current.completed_units == 3
    assert current.total_units is None


def test_finish_is_single_terminal_event() -> None:
    progress, _, sink = tracker()
    progress.start_stage("persistence", 1)
    completed = progress.finish("completed", "finished")
    assert completed.overall_progress == 1
    assert completed.can_cancel is False
    with pytest.raises(ProgressStateError):
        progress.finish("completed")
    with pytest.raises(ProgressStateError):
        progress.advance(1)
    assert len(sink.events) == 2


def test_invalid_lifecycle_and_values() -> None:
    clock = FakeClock()
    sink = RecordingProgressSink()
    with pytest.raises(TypeError):
        ProgressTracker("", "job", sink, clock)
    with pytest.raises(ValueError):
        ProgressTracker("op", "other", sink, clock)
    progress, _, _ = tracker()
    with pytest.raises(ProgressStateError):
        progress.advance(1)
    with pytest.raises(ValueError):
        progress.start_stage("not-a-stage")  # type: ignore[arg-type]
    progress.start_stage("transcription", 2)
    with pytest.raises(ValueError):
        progress.advance(-1)
    with pytest.raises(ValueError):
        progress.advance(3)
    progress.advance(1)
    with pytest.raises(ValueError):
        progress.advance(0)
    with pytest.raises(ValueError):
        progress.start_stage("cleanup", math.nan)


def test_eta_uses_recent_measured_interval_only() -> None:
    assert estimate_eta(((0, 0), (2, 4)), 6) == 3
    assert estimate_eta(((0, 0),), 3) is None
    assert estimate_eta(((0, 0), (2, 0)), 3) is None
    assert estimate_eta(((0, 0), (2, 4)), 0) == 0
    with pytest.raises(ValueError):
        estimate_eta(((2, 0), (1, 1)), 1)
    with pytest.raises(ValueError):
        estimate_eta(((0, math.inf), (1, 2)), 1)


def test_unknown_total_does_not_invent_eta() -> None:
    progress, clock, _ = tracker()
    progress.start_stage("model_download")
    clock.advance(10)
    event = progress.advance(5)
    assert event.eta_seconds is None
