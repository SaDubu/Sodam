"""Unit tests for V2-T01 deterministic test collaborators."""

from datetime import datetime

import pytest

from backend.contracts import ProgressEvent, SystemProfile
from tests.fakes_productization import (
    FakeCancellationToken,
    FakeSystemProbe,
    RecordingInstallerBackend,
    RecordingIntroductionRuntime,
)
from tests.fakes_progress import FakeClock, RecordingProgressSink


def _event(sequence: int = 1) -> ProgressEvent:
    return ProgressEvent(
        operation_id="op-1",
        scope="job",
        stage="transcription",
        stage_label="전사",
        stage_progress=0.5,
        overall_progress=0.2,
        completed_units=1,
        total_units=2,
        elapsed_seconds=1.0,
        eta_seconds=1.0,
        message="working",
        can_cancel=True,
        sequence=sequence,
        timestamp="1970-01-01T00:00:01Z",
    )


def _profile() -> SystemProfile:
    return SystemProfile("windows", "x86_64", "cpu", 32, "gpu", 16, 100)


def test_fake_clock_is_deterministic_and_validates_values() -> None:
    clock = FakeClock(1.5)
    assert clock.monotonic() == 1.5
    assert datetime.fromisoformat(clock.utc_timestamp().replace("Z", "+00:00")).year == 1970
    clock.advance(2.5)
    assert clock.monotonic() == 4.0
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(TypeError):
        FakeClock(True)


def test_progress_sink_returns_snapshot_and_checks_type() -> None:
    sink = RecordingProgressSink()
    event = _event()
    sink.emit(event)
    assert sink.events == (event,)
    with pytest.raises(TypeError):
        sink.emit(object())  # type: ignore[arg-type]


def test_introduction_runtime_is_fifo_and_records_prompts() -> None:
    runtime = RecordingIntroductionRuntime(("one", "two"))
    assert runtime.complete("p1") == "one"
    assert runtime.complete("p2") == "two"
    assert runtime.prompts == ("p1", "p2")
    assert runtime.call_count == 2
    with pytest.raises(RuntimeError):
        runtime.complete("p3")


def test_probe_and_cancellation_are_local_and_monotonic() -> None:
    probe = FakeSystemProbe(_profile())
    assert probe.collect() == _profile()
    assert probe.call_count == 1
    token = FakeCancellationToken()
    assert not token.is_cancelled()
    token.cancel()
    token.cancel()
    assert token.is_cancelled()


def test_installer_records_events_and_honors_pre_requested_cancel() -> None:
    backend = RecordingInstallerBackend({"download": (_event(),)})
    emitted: list[ProgressEvent] = []
    backend.execute_action("download", emitted.append, FakeCancellationToken())
    assert backend.action_ids == ("download",)
    assert emitted == [_event()]
    emitted.clear()
    backend.execute_action("download", emitted.append, FakeCancellationToken(True))
    assert emitted == []
    with pytest.raises(KeyError):
        backend.execute_action("missing", emitted.append, FakeCancellationToken())
