"""P15-R1 contracts only; skipped declarations are not passing regression tests.

Run after implementation: py -3.12 -B -m pytest -q tests/unit/test_gui_progress.py
No fixture is constructed and no model, UI, clock or subprocess runs on import.
"""

from __future__ import annotations

import threading
import json
from typing import TYPE_CHECKING

import pytest

from tests.fakes_gui import FakeMonotonic

if TYPE_CHECKING:
    from tests.fakes_gui import FakeMonotonic, FakeRoot
    from tools.simple_gui import SodamWindow


def make_progress_window(
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeMonotonic,
    root: FakeRoot,
) -> SodamWindow:
    """R1-H03: patch widget factories, dialogs and worker to inspect the UI.

    Accept pytest MonkeyPatch and valid clock/root fakes, otherwise TypeError.
    Return an idle window with recorded widget values, after callbacks and worker
    calls; never create real Tk, dialogs or subprocesses. Monkeypatch owns teardown.
    Verify this helper directly before using it to certify product behavior.
    """
    raise NotImplementedError("P15-R1-H03: observable progress window fixture")


def test_fake_monotonic_contract() -> None:
    """TH01: origin/read/advance, invalid types and overflow leave time unchanged."""
    clock = FakeMonotonic(1.5)
    assert clock() == 1.5
    clock.advance(0)
    clock.advance(0.25)
    clock.advance(90)
    clock.advance(86400)
    assert clock() == 86491.75
    before = clock()
    for value, error in ((True, TypeError), ("1", TypeError), (None, TypeError), (-1, ValueError), (float("nan"), ValueError), (float("inf"), ValueError)):
        with pytest.raises(error):
            clock.advance(value)
        assert clock() == before
    with pytest.raises(ValueError):
        FakeMonotonic(-1)
    near_limit = FakeMonotonic(float.fromhex("0x1.fffffffffffffp1023"))
    with pytest.raises(ValueError):
        near_limit.advance(float.fromhex("0x1.fffffffffffffp1023"))
    assert near_limit() == float.fromhex("0x1.fffffffffffffp1023")
    assert clock() == before


def test_gated_pipe_contract() -> None:
    """TH02: chunks/partial reads/fault/EOF gate, invalid sizes and close release.

    Always release in finally and join within five seconds; no orphan threads.
    """
    from tests.fakes_gui import GatedPipe

    pipe = GatedPipe((b"abc", b"def"))
    assert pipe.read1(2) == b"ab"
    assert pipe.read1(10) == b"cdef"
    finished = threading.Event()
    values: list[bytes] = []

    def read_eof() -> None:
        values.append(pipe.read1(1))
        finished.set()

    reader = threading.Thread(target=read_eof)
    reader.start()
    try:
        assert not finished.wait(0.2)
        pipe.release()
        assert finished.wait(5)
        assert values == [b""]
        pipe.release()
        pipe.close()
        pipe.close()
        assert pipe._closed is True
    finally:
        pipe.release()
        reader.join(5)
    with pytest.raises(ValueError):
        pipe.read1(1)

    faulty = GatedPipe((b"x",), OSError("read failed"))
    assert faulty.read1(2) == b"x"
    with pytest.raises(OSError, match="read failed"):
        faulty.read1(2)
    faulty.release()
    assert faulty.read1(2) == b""
    for bad in (0, -1):
        with pytest.raises(ValueError):
            GatedPipe(()).read1(bad)
    with pytest.raises(TypeError):
        GatedPipe(()).read1(True)


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_progress_window_fixture_contract() -> None:
    """TH03: fake scheduler IDs/cancel, view recording, invalid collaborators.

    Creating the fixture must leave real Tk, clipboard, clock and process unused.
    """
    raise NotImplementedError("P15-R1-TH03")


def test_format_elapsed_contract() -> None:
    """T01: 0/59.9/60/3599/3600/86400, type/value errors, no daily wraparound."""
    from tools.simple_gui import format_elapsed

    assert format_elapsed(0) == "00:00:00"
    assert format_elapsed(59.9) == "00:00:59"
    assert format_elapsed(60) == "00:01:00"
    assert format_elapsed(3599) == "00:59:59"
    assert format_elapsed(3600) == "01:00:00"
    assert format_elapsed(86400) == "24:00:00"
    for value in (True, "1", None):
        with pytest.raises(TypeError):
            format_elapsed(value)
    for value in (-1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            format_elapsed(value)


def test_unbuffered_runner_argv_contract(tmp_path) -> None:
    """T02: Python -u precedes script, URL/local/three modes and spaces preserved."""
    from pathlib import Path

    from tools.gui_runner import GuiSettings, RunRequest, SourceSpec, build_runner_argv

    import sys
    runner = tmp_path / "runner with spaces.py"
    runner.touch()
    settings = GuiSettings(Path(sys.executable), runner)
    source = RunRequest(SourceSpec("local", r"C:\Videos\한글 & sample.mp4"), "both")
    argv = build_runner_argv(source, settings)
    assert argv[:3] == [str(settings.python_executable), "-u", str(settings.runner_path)]
    assert argv[-1] == source.source.source
    assert "--allow-url" not in argv
    assert "--progress-format" in argv and argv[argv.index("--progress-format") + 1] == "jsonl"
    assert build_runner_argv(RunRequest(SourceSpec("url", "https://youtu.be/abc"), "summary"), settings)[1] == "-u"


def test_progress_decoder_contract() -> None:
    """T03: valid schema, boundary percentages and malformed payloads are safe."""
    from tools.gui_runner import parse_stderr_line

    payload = {
        "operation_id": "op-1", "scope": "job", "stage": "transcription",
        "stage_label": "전사", "stage_progress": 0.0, "overall_progress": 0.0,
        "completed_units": 0, "total_units": 10, "elapsed_seconds": 0.0,
        "eta_seconds": None, "message": "시작", "can_cancel": True,
        "sequence": 1, "timestamp": "2026-09-05T00:00:00+09:00",
    }
    event = parse_stderr_line(json.dumps(payload, ensure_ascii=False))
    assert event.kind == "progress"
    assert event.payload.overall_progress == 0.0
    payload["overall_progress"] = 1.0
    assert parse_stderr_line(json.dumps(payload)).kind == "progress"
    for bad in ("not-json", json.dumps({"stage": "transcription"}), json.dumps({**payload, "sequence": True}), json.dumps({**payload, "overall_progress": float("nan")}), json.dumps({**payload, "stage": "unknown"})):
        assert parse_stderr_line(bad).kind == "diagnostic"


def test_progress_reader_delivers_before_eof() -> None:
    """T04: publish a short line while GatedPipe is still withholding EOF."""
    from tests.fakes_gui import GatedPipe
    from tools.gui_runner import _read_progress_pipe

    pipe = GatedPipe((b"diagnostic before eof\n",))
    values = []
    published = threading.Event()
    reader = threading.Thread(target=lambda: _read_progress_pipe(pipe, lambda event: (values.append(event), published.set())))
    reader.start()
    try:
        assert published.wait(2)
        assert values[0].kind == "diagnostic"
        assert reader.is_alive()
        pipe.release()
        reader.join(5)
        assert not reader.is_alive()
    finally:
        pipe.release()
        reader.join(5)


def test_progress_reader_split_utf8_and_limits() -> None:
    """T04: split UTF-8, CRLF, unterminated EOF, truncation and recovery."""
    from tests.fakes_gui import GatedPipe
    from tools.gui_runner import _read_progress_pipe

    payload = json.dumps({
        "operation_id": "op-1", "scope": "job", "stage": "introduction",
        "stage_label": "소개글", "stage_progress": 0.5, "overall_progress": 0.75,
        "completed_units": 1, "total_units": 2, "elapsed_seconds": 1.0,
        "eta_seconds": None, "message": "한글", "can_cancel": False,
        "sequence": 2, "timestamp": "now",
    }, ensure_ascii=False).encode()
    chunks = (payload[:7], payload[7:] + b"\r\n", b"x" * 5 + b"\n", payload + b"\n")
    pipe = GatedPipe(chunks)
    values = []
    reader = threading.Thread(target=lambda: _read_progress_pipe(pipe, values.append, line_limit_bytes=len(payload) + 1))
    reader.start()
    pipe.release()
    reader.join(5)
    assert not reader.is_alive()
    assert any(event.kind == "progress" and event.payload.message == "한글" for event in values)
    assert any(event.kind == "diagnostic" and "초과" in str(event.payload) for event in values)


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_progress_reader_split_utf8_and_limits() -> None:
    """T04: Korean split bytes/CRLF/final line/64KiB boundary/long-line recovery.

    Inject read errors; later valid progress survives diagnostic budget exhaustion.
    """
    raise NotImplementedError("P15-R1-T04")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_progress_buffer_first_latest_and_terminal_contract() -> None:
    """T05: 10000 updates, sequence ordering, 256 keys, bounded errors/diagnostics.

    Preserve first log event/latest percent and terminal outcome; reject bad inputs.
    """
    raise NotImplementedError("P15-R1-T05")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_final_report_job_directory_contract(tmp_path) -> None:
    """T06: root/job_id succeeds; missing/mismatched/linked/escaped paths fail.

    Cover exit0 malformed report and stdout overflow; use no real result directory.
    """
    raise NotImplementedError("P15-R1-T06")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_stream_process_terminal_delivery_contract() -> None:
    """T07: concurrent draining, launch/read/decode/report faults and exit0/exit1.

    Owned child/readers are reaped before exactly one final exited event. No Tk.
    """
    raise NotImplementedError("P15-R1-T07")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_progress_layout_initial_state_contract() -> None:
    """T08: idle labels/bar/times, no ETA widget or scheduled work at construction.

    Check fake grid constraints; native geometry/DPI verification remains manual.
    """
    raise NotImplementedError("P15-R1-T08")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_elapsed_tick_without_progress_contract() -> None:
    """T09: 90 seconds without events, callback delay/duplicates/bad clock/end.

    Values use elapsed differences; one timer, fixed terminal values, no ETA.
    """
    raise NotImplementedError("P15-R1-T09")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_start_run_resets_progress_contract() -> None:
    """T10: accepted run resets timing/results, one worker/timer, duplicate lock.

    Failed validation/worker start and a second run cannot retain stale success.
    """
    raise NotImplementedError("P15-R1-T10")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_live_progress_and_once_per_stage_log_contract() -> None:
    """T11: 40 -> 45 shows 45 but logs first 40 once; None/stale sequence cases.

    Only a new stage resets stage time; total time and latest valid percent persist.
    """
    raise NotImplementedError("P15-R1-T11")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_finalizing_and_error_exit_zero_contract() -> None:
    """T11: completed stays finalizing; result+exit0 succeeds; error+exit0 fails.

    Dead worker with drained buffer cannot leave the UI running forever.
    """
    raise NotImplementedError("P15-R1-T11")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_open_result_folder_revalidation_contract(tmp_path) -> None:
    """T12: exact job path only, replacement/escape/missing path or pre-success.

    Inject folder opener to assert targets without launching a native file browser.
    """
    raise NotImplementedError("P15-R1-T12")


@pytest.mark.skip(reason="P15-R1 scaffold: awaiting implementation")
def test_close_cancels_both_callbacks_contract() -> None:
    """T13: all states, pending poll/timer and repeated close; no process kills.

    Active child keeps root alive; terminal close leaves zero pending callbacks.
    """
    raise NotImplementedError("P15-R1-T13")
