"""P15 deterministic test tools; no real process, Tk, model or network.

Implement these tools independently before using them to certify product code.
The H01 process fakes are implemented; H02/H03 remain intentionally inactive.
"""

from __future__ import annotations

import math
from numbers import Real
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tools.gui_runner import GuiEvent, RunRequest


class FakePipe:
    """Deterministic byte stream with read/close recording and fault injection."""

    __slots__ = ("_data", "_pos", "_closed", "_error", "read_calls", "close_calls")

    def __init__(self, chunks: tuple[bytes, ...], error: OSError | None = None) -> None:
        if not isinstance(chunks, tuple):
            raise TypeError("chunks must be a tuple of bytes")
        for i, c in enumerate(chunks):
            if not isinstance(c, bytes):
                raise TypeError(f"chunks[{i}] must be bytes")
        self._data = bytearray(b"".join(chunks))
        self._pos = 0
        self._closed = False
        self._error: OSError | None = error
        self.read_calls: list[int] = []
        self.close_calls = 0

    def read(self, size: int = -1) -> bytes:
        if self._closed:
            raise ValueError("read on closed FakePipe")
        if not isinstance(size, int) or isinstance(size, bool):
            raise TypeError(f"size must be int, got {type(size).__name__}")
        if size == 0:
            return b""
        if size < -1:
            raise ValueError(f"invalid size: {size}")
        self.read_calls.append(size)
        if size == -1:
            result = bytes(self._data[self._pos:])
            self._pos = len(self._data)
            if not result and self._error is not None:
                err, self._error = self._error, None
                raise err
            return result
        remaining = len(self._data) - self._pos
        if remaining <= 0:
            if self._error is not None:
                err, self._error = self._error, None
                raise err
            return b""
        taken = min(size, remaining)
        result = bytes(self._data[self._pos : self._pos + taken])
        self._pos += taken
        return result

    def close(self) -> None:
        self._closed = True
        self.close_calls += 1


class FakeProcess:
    """Owned-child lifecycle fixture; never starts an OS process."""

    stdout: FakePipe
    stderr: FakePipe
    returncode: int | None

    def __init__(self, stdout: FakePipe, stderr: FakePipe, exit_code: int = 0) -> None:
        """Start in simulated running state; bad pipe/code types raise TypeError."""
        if not isinstance(stdout, FakePipe) or not isinstance(stderr, FakePipe):
            raise TypeError("stdout and stderr must be FakePipe instances")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise TypeError("exit_code must be an integer")
        self.stdout = stdout
        self.stderr = stderr
        self._exit_code = exit_code
        self.returncode = None
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        """Return None before wait, configured code afterward, without mutation."""
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        """Record reap and return configured code; negative timeout is ValueError.

        This deterministic fake does not simulate wall-clock process scheduling.
        Pipe concurrency also needs a blocking handshake fixture in worker tests.
        """
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, Real)):
            raise ValueError("timeout must be a non-negative number or None")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be a non-negative number or None")
        self.wait_calls.append(timeout)
        self.returncode = self._exit_code
        return self._exit_code


class FakeProcessFactory:
    """Record Popen arguments or raise a configured launch failure."""

    def __init__(self, process: FakeProcess, error: OSError | None = None) -> None:
        """Require a FakeProcess; initialize an empty call history, no I/O."""
        if not isinstance(process, FakeProcess):
            raise TypeError("process must be a FakeProcess instance")
        if error is not None and not isinstance(error, OSError):
            raise TypeError("error must be an OSError or None")
        self.process = process
        self.error = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> FakeProcess:
        """Record argv, cwd, shell, environment, pipe and window flags.

        Return the configured process or raise configured OSError; never execute
        any supplied command. A fixture instance is used for one worker run.
        """
        self.calls.append((tuple(args), dict(kwargs)))
        if self.error is not None:
            raise self.error
        return self.process


class FakeRoot:
    """Manual scheduler/clipboard fixture; no real display or automatic timer."""

    def __init__(self) -> None:
        """Initialize empty callbacks, clipboard and destruction history."""
        raise NotImplementedError("P15-H02: fake Tk root")

    def after(self, delay_ms: int, callback: Callable[[], object]) -> str:
        """Record a callback and return unique ID without running it.

        Negative delay raises ValueError; non-callable callback raises TypeError.
        Tests invoke recorded callbacks explicitly to avoid sleeps and recursion.
        """
        raise NotImplementedError("P15-H02: scheduled polling fixture")

    def after_cancel(self, callback_id: str) -> None:
        """Remove a pending callback; an already removed ID is a no-op."""
        raise NotImplementedError("P15-H02: polling cancellation fixture")

    def clipboard_clear(self) -> None:
        """Clear only the in-memory clipboard, never the user's clipboard."""
        raise NotImplementedError("P15-H02: fake clipboard clear")

    def clipboard_append(self, text: str) -> None:
        """Append exact text; non-string raises TypeError without mutation."""
        raise NotImplementedError("P15-H02: fake clipboard append")

    def destroy(self) -> None:
        """Record root destruction; repeated calls have no additional effect."""
        raise NotImplementedError("P15-H02: fake root destruction")


class FakeView:
    """Recording text/control surface for patched Tk widget collaborators.

    Widget factories in UI tests adapt this surface to the actual ttk signatures;
    it is a test helper, not a new application rendering abstraction.
    """

    def __init__(self) -> None:
        """Initialize empty named values and control states, without a Tk root."""
        raise NotImplementedError("P15-H02: recording view fixture")

    def set_value(self, name: str, value: object) -> None:
        """Record exact input/status/text/control value; empty name is ValueError."""
        raise NotImplementedError("P15-H02: view value recording")

    def get_value(self, name: str) -> object:
        """Return the recorded value; unknown name raises KeyError, no mutation."""
        raise NotImplementedError("P15-H02: view value inspection")


def make_runner_report(request: RunRequest, job_directory: Path) -> dict[str, object]:
    """Build an existing CLI-schema report for a supplied temporary job directory.

    No directory creation occurs here; pytest tmp_path owns filesystem setup.
    Match selected output mode and existing introduction/resilience contracts.
    Invalid request/path types raise TypeError. Tests mutate a copy for bad cases.
    """
    raise NotImplementedError("P15-H03: final report fixture")


def make_gui_event_sequence(scenario: str) -> tuple[GuiEvent, ...]:
    """Return deterministic progress/diagnostic/terminal events, without I/O.

    Scenarios: success, failure, completed_without_report, result_before_exit,
    exit_before_result, repeated_stage. Unknown names raise ValueError. Use real
    ProgressEvent schema and preserve percentages, including zero and None.
    """
    raise NotImplementedError("P15-H03: event sequence fixture")


class FakeMonotonic:
    """P15-R1-H01 scaffold: deterministic clock without real sleeping."""

    __slots__ = ("_time",)

    def __init__(self, initial: float = 0.0) -> None:
        """Require finite non-negative real time; TypeError/ValueError otherwise.

        Reject bool. Initialize only in-memory clock state after validation.
        Test default zero, fractional origin and invalid inputs directly.
        """
        if isinstance(initial, bool):
            raise TypeError(f"initial must be a number, got {type(initial).__name__}")
        if not isinstance(initial, Real):
            raise TypeError(f"initial must be a Real, got {type(initial).__name__}")
        if math.isnan(initial) or math.isinf(initial):
            raise ValueError("initial must be finite")
        if initial < 0:
            raise ValueError("initial must be non-negative")
        self._time = float(initial)

    def __call__(self) -> float:
        """Return stored time unchanged, without accessing the system clock."""
        return self._time

    def advance(self, seconds: float) -> None:
        """Add finite non-negative real seconds, rejecting bool/non-real types.

        TypeError/ValueError must leave the clock unchanged, including overflow.
        Test zero/fractional/90-second/24-hour jumps; never sleep in this helper.
        """
        if isinstance(seconds, bool):
            raise TypeError(f"seconds must be a number, got {type(seconds).__name__}")
        if not isinstance(seconds, Real):
            raise TypeError(f"seconds must be a Real, got {type(seconds).__name__}")
        if math.isnan(seconds) or math.isinf(seconds):
            raise ValueError("seconds must be finite")
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        candidate = self._time + seconds
        if not math.isfinite(candidate):
            raise ValueError("candidate time would exceed finite range")
        self._time = candidate


class GatedPipe(FakePipe):
    """P15-R1-H02 scaffold: byte chunks followed by explicitly released EOF.

    Subclass FakePipe so the existing FakeProcess accepts it. Implement read1
    independently; inherited read is not a substitute for the streaming contract.
    Tests must release/close in finally and use bounded joins of at most five
    seconds, including on assertion failure. No OS pipe/process is created.
    """

    def __init__(self, chunks: tuple[bytes, ...], error: OSError | None = None) -> None:
        """Validate byte tuple/optional OSError before allocating gate state.

        Bad inputs raise TypeError. A configured read fault happens once after
        supplied data; normal EOF is withheld until release/close. Retain an
        observable read history so tests can prove publication before EOF.
        """
        if not isinstance(chunks, tuple) or any(not isinstance(chunk, bytes) for chunk in chunks):
            raise TypeError("chunks must be a tuple of bytes")
        if error is not None and not isinstance(error, OSError):
            raise TypeError("error must be an OSError or None")
        self._data = bytearray(b"".join(chunks))
        self._pos = 0
        self._error = error
        self._closed = False
        self._released = threading.Event()
        self.read1_calls: list[int] = []

    def read1(self, size: int) -> bytes:
        """Return available bytes up to positive size, preserving chunk remainder.

        Reject bool/non-int with TypeError and non-positive sizes with ValueError.
        Wait at the gate after chunks; release returns EOF, close unblocks waiting
        readers. Reads started after close raise ValueError. Inject configured
        OSError once and record calls without touching any real subprocess.
        """
        if self._closed:
            raise ValueError("read1 on closed GatedPipe")
        if not isinstance(size, int) or isinstance(size, bool):
            raise TypeError("size must be an integer")
        if size <= 0:
            raise ValueError("size must be positive")
        self.read1_calls.append(size)
        remaining = len(self._data) - self._pos
        if remaining:
            taken = min(size, remaining)
            result = bytes(self._data[self._pos : self._pos + taken])
            self._pos += taken
            return result
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        self._released.wait()
        if self._closed:
            raise ValueError("read1 on closed GatedPipe")
        return b""

    def release(self) -> None:
        """Idempotently unblock gate waiters to permit EOF; do not discard data."""
        self._released.set()

    def close(self) -> None:
        """Mark closed and unblock all gate waiters; repeated calls are harmless."""
        self._closed = True
        self._released.set()
