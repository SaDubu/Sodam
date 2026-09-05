"""Small, testable bridge from the Tk UI to the existing Sodam CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
from subprocess import Popen
from typing import BinaryIO, Callable, Literal
from urllib.parse import urlsplit

from backend.contracts import ProgressEvent
from backend.sources import validate_source


from backend.runtime_paths import RESULT_ROOT
MAX_STDOUT_BYTES = 32 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 2 * 1024 * 1024
MAX_BUFFER_KEYS = 256


@dataclass(frozen=True)
class GuiSettings:
    """Runtime paths selected by the launcher or injected by a test."""

    python_executable: Path
    runner_path: Path
    hermes_command: Path | None = None
    hermes_python: Path | None = None
    hermes_root: Path | None = None
    hermes_version: str = "0.19.0"
    result_root: Path = RESULT_ROOT


@dataclass(frozen=True)
class SourceSpec:
    """A validated YouTube URL or local regular file."""

    kind: Literal["url", "local"]
    source: str


@dataclass(frozen=True)
class RunRequest:
    """One source and one existing CLI output mode."""

    source: SourceSpec
    output_mode: Literal["summary", "introduction", "both"] = "both"


@dataclass(frozen=True)
class GuiEvent:
    """Message crossing from a worker to the Tk main thread."""

    kind: Literal["progress", "diagnostic", "result", "error", "exited"]
    payload: object


class GuiEventBuffer:
    """Bounded, thread-safe event queue retaining the first stage percentage.

    P15-R1-F05 pending: retain first and pending latest events per stage, order
    progress by sequence, and keep terminal delivery outside diagnostic budgets.
    Existing delivery behavior stays active until implementation approval.
    """

    def __init__(self, diagnostic_limit_bytes: int = MAX_DIAGNOSTIC_BYTES) -> None:
        if isinstance(diagnostic_limit_bytes, bool) or not isinstance(diagnostic_limit_bytes, int):
            raise ValueError("diagnostic_limit_bytes must be an integer")
        if diagnostic_limit_bytes <= 0:
            raise ValueError("diagnostic_limit_bytes must be positive")
        self._limit = diagnostic_limit_bytes
        self._queue: queue.Queue[GuiEvent] = queue.Queue()
        self._lock = threading.Lock()
        self._stage_keys: set[tuple[str, str, str]] = set()
        self._progress_queued: set[tuple[str, str, str]] = set()
        self._progress_delivered: set[tuple[str, str, str]] = set()
        self._latest_progress: dict[tuple[str, str, str], GuiEvent] = {}
        self._diagnostic_bytes = 0
        self._diagnostic_truncated = False
        self._terminal: dict[str, GuiEvent] = {}

    def publish(self, event: GuiEvent) -> None:
        if not isinstance(event, GuiEvent):
            raise TypeError("event must be GuiEvent")
        with self._lock:
            if event.kind == "progress":
                payload = event.payload
                if not isinstance(payload, ProgressEvent):
                    raise TypeError("progress payload must be ProgressEvent")
                key = (payload.operation_id, payload.scope, payload.stage)
                if key in self._stage_keys:
                    self._latest_progress[key] = event
                    if key not in self._progress_queued:
                        self._progress_queued.add(key)
                        self._queue.put(event)
                    return
                if len(self._stage_keys) >= MAX_BUFFER_KEYS:
                    return
                self._stage_keys.add(key)
                self._progress_queued.add(key)
            elif event.kind == "diagnostic":
                text = str(event.payload)
                size = len(text.encode("utf-8", errors="replace"))
                if self._diagnostic_bytes >= self._limit:
                    if not self._diagnostic_truncated:
                        self._queue.put(GuiEvent("diagnostic", "[진단 출력 생략: 최대 보관량 초과]"))
                        self._diagnostic_truncated = True
                    return
                if self._diagnostic_bytes + size > self._limit:
                    available = max(0, self._limit - self._diagnostic_bytes)
                    text = text.encode("utf-8", errors="replace")[:available].decode("utf-8", errors="ignore")
                    event = GuiEvent("diagnostic", text)
                    self._diagnostic_bytes = self._limit
                else:
                    self._diagnostic_bytes += size
            elif event.kind in {"result", "error", "exited"}:
                self._terminal[event.kind] = event
            self._queue.put(event)

    def drain(self, limit: int = 100) -> tuple[GuiEvent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        items: list[GuiEvent] = []
        for _ in range(limit):
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            if event.kind == "progress":
                payload = event.payload
                key = (payload.operation_id, payload.scope, payload.stage)
                with self._lock:
                    self._progress_queued.discard(key)
                    latest = self._latest_progress.pop(key, None)
                    first_delivery = key not in self._progress_delivered
                    self._progress_delivered.add(key)
                if first_delivery:
                    items.append(event)
                if latest is not None:
                    items.append(latest)
            else:
                items.append(event)
        return tuple(items)


def _clean_source(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("source must be str")
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] == '"':
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise ValueError("source is empty")
    if cleaned.startswith("[") and "](" in cleaned:
        raise ValueError("Markdown links are not supported")
    return cleaned


def normalize_source(value: str) -> SourceSpec:
    """Classify and validate one URL or absolute local regular file."""
    cleaned = _clean_source(value)
    parts = urlsplit(cleaned)
    if parts.scheme and not (len(cleaned) >= 3 and cleaned[1:3] in (":\\", ":/")):
        validate_source(cleaned)
        return SourceSpec("url", cleaned)
    if cleaned.startswith(("\\\\", "//")):
        raise ValueError("UNC paths are not supported")
    path = Path(cleaned)
    if not path.is_absolute():
        raise ValueError("local source must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise ValueError("local source must be an existing non-symlink file")
    return SourceSpec("local", str(path.resolve()))


def build_runner_argv(request: RunRequest, settings: GuiSettings) -> list[str]:
    """Build a shell-free argv list for tools/run_local.py.

    P15-R1-F02 pending: insert -u immediately after Python for timely child
    output, preserving every existing option and the final source argument.
    """
    if not isinstance(request, RunRequest) or not isinstance(settings, GuiSettings):
        raise TypeError("request and settings have invalid types")
    if request.output_mode not in {"summary", "introduction", "both"}:
        raise ValueError("unsupported output mode")
    for value, label in ((settings.python_executable, "Python"), (settings.runner_path, "runner")):
        if not isinstance(value, Path) or not value.is_absolute() or not value.is_file():
            raise ValueError(f"{label} path is unavailable")
    argv = [str(settings.python_executable), "-u", str(settings.runner_path), "--mode", "run"]
    if request.source.kind == "url":
        validate_source(request.source.source)
        argv.append("--allow-url")
    elif request.source.kind != "local":
        raise ValueError("unsupported source kind")
    argv += ["--output-mode", request.output_mode, "--generation-backend", "hermes", "--progress-format", "jsonl"]
    for flag, value in (("--hermes-command", settings.hermes_command), ("--hermes-python", settings.hermes_python), ("--hermes-root", settings.hermes_root)):
        if value is not None:
            if not isinstance(value, Path) or not value.is_absolute() or not value.exists():
                raise ValueError(f"{flag} path is unavailable")
            argv += [flag, str(value)]
    argv += ["--hermes-version", settings.hermes_version, request.source.source]
    return argv


def parse_stderr_line(line: str) -> GuiEvent:
    """Decode one JSONL progress line, retaining all other output as diagnostic."""
    if not isinstance(line, str):
        raise TypeError("line must be str")
    if not line:
        return GuiEvent("diagnostic", "")
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return GuiEvent("diagnostic", line)
    if not isinstance(data, dict):
        return GuiEvent("diagnostic", line)
    required = {
        "operation_id", "scope", "stage", "stage_label", "stage_progress",
        "overall_progress", "completed_units", "total_units", "elapsed_seconds",
        "eta_seconds", "message", "can_cancel", "sequence", "timestamp",
    }
    if not required.issubset(data):
        return GuiEvent("diagnostic", line)
    try:
        event = ProgressEvent(**data)
    except (TypeError, ValueError):
        return GuiEvent("diagnostic", line)
    if not isinstance(event.operation_id, str) or not event.operation_id:
        return GuiEvent("diagnostic", line)
    if event.scope not in {"setup", "job"} or event.stage not in {
        "environment_check", "dependency_install", "model_download", "source_validation",
        "source_acquisition", "audio_extraction", "transcription", "text_protection",
        "rule_normalization", "correction", "review_validation", "transcript_assembly",
        "summarization", "introduction", "persistence", "cleanup", "completed", "failed",
        "cancelled",
    }:
        return GuiEvent("diagnostic", line)
    if not isinstance(event.stage_label, str) or not isinstance(event.message, str) or not isinstance(event.timestamp, str):
        return GuiEvent("diagnostic", line)
    if not isinstance(event.can_cancel, bool) or isinstance(event.sequence, bool) or not isinstance(event.sequence, int):
        return GuiEvent("diagnostic", line)
    for value in (event.stage_progress, event.overall_progress, event.completed_units, event.total_units, event.eta_seconds, event.elapsed_seconds):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))):
            return GuiEvent("diagnostic", line)
    if event.stage_progress is not None and not 0 <= event.stage_progress <= 1:
        return GuiEvent("diagnostic", line)
    if event.overall_progress is not None and not 0 <= event.overall_progress <= 1:
        return GuiEvent("diagnostic", line)
    if event.elapsed_seconds < 0 or event.sequence < 0:
        return GuiEvent("diagnostic", line)
    return GuiEvent("progress", event)


def _error_event(message: str) -> GuiEvent:
    return GuiEvent("error", message[:2000])


def _read_progress_pipe(
    pipe: BinaryIO,
    publish: Callable[[GuiEvent], None],
    *,
    line_limit_bytes: int = 65536,
) -> None:
    """P15-R1-F04 scaffold: deliver stderr lines before child completion.

    Require a binary read1-capable pipe, callable publish and a positive integer
    byte limit (not bool). Bad collaborators raise TypeError; invalid limits
    raise ValueError. Read currently available bytes with read1, accumulate until
    LF, strip CRLF, then decode UTF-8 and call parse_stderr_line. Handle the last
    unterminated line at EOF. Do not decode partial multibyte characters.

    Keep at most line_limit_bytes of an unfinished line; report truncation once,
    discard until LF and resume with the next line. Diagnostic truncation must
    not disable later progress. Drain the pipe even after the display budget is
    exhausted. Read faults publish a safe error; the worker owns pipe closure,
    reader joins and child reaping. Never call Tk or launch another process here.

    Verify short lines before GatedPipe.release, byte-split Korean text, CRLF,
    EOF, exact/over-limit lines, recovery after truncation and injected OSError.
    This function is not connected to stream_process in the scaffold stage.
    """
    if not callable(getattr(pipe, "read1", None)) or not callable(publish):
        raise TypeError("pipe must provide read1 and publish must be callable")
    if isinstance(line_limit_bytes, bool) or not isinstance(line_limit_bytes, int) or line_limit_bytes <= 0:
        raise ValueError("line_limit_bytes must be a positive integer")
    pending = bytearray()
    dropping = False
    while True:
        try:
            chunk = pipe.read1(65536)
        except OSError as exc:
            publish(_error_event(f"진행 출력을 읽지 못했습니다: {exc}"))
            return
        if not chunk:
            break
        pending.extend(chunk)
        while b"\n" in pending:
            raw, _, remainder = pending.partition(b"\n")
            pending = bytearray(remainder)
            if dropping:
                dropping = False
                continue
            if len(raw) > line_limit_bytes:
                publish(GuiEvent("diagnostic", "[진단 출력 생략: 한 줄 최대 크기 초과]"))
                dropping = True
                continue
            publish(parse_stderr_line(raw.rstrip(b"\r").decode("utf-8", errors="replace")))
        if len(pending) > line_limit_bytes and not dropping:
            pending.clear()
            dropping = True
            publish(GuiEvent("diagnostic", "[진단 출력 생략: 한 줄 최대 크기 초과]"))
            publish(GuiEvent("diagnostic", "[진단 출력 생략: 한 줄 최대 크기 초과]"))
    if pending and not dropping:
        publish(parse_stderr_line(bytes(pending).rstrip(b"\r").decode("utf-8", errors="replace")))


def parse_runner_report(text: str, exit_code: int, request: RunRequest, *, result_root: Path = RESULT_ROOT) -> GuiEvent:
    """Accept a final report only when exit, schema, mode and job directory agree."""
    if not isinstance(text, str) or not isinstance(exit_code, int) or not isinstance(request, RunRequest):
        raise TypeError("invalid report arguments")
    if exit_code != 0:
        return _error_event(f"Sodam 실행이 종료되었습니다 (ExitCode: {exit_code}).\n{text[-1500:]}")
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        return _error_event("최종 결과 JSON을 읽지 못했습니다.")
    if not isinstance(report, dict) or report.get("status") != "archived" or not report.get("job_id"):
        return _error_event("최종 결과 형식이 올바르지 않습니다.")
    if report.get("mode") != "run":
        return _error_event("최종 결과의 실행 모드가 올바르지 않습니다.")
    if request.output_mode in {"summary", "both"} and not report.get("summary"):
        return _error_event("요약 결과가 누락되었습니다.")
    if request.output_mode in {"introduction", "both"} and not report.get("introduction"):
        return _error_event("소개글 결과가 누락되었습니다.")
    raw_path = report.get("result_path")
    if not isinstance(raw_path, str):
        return _error_event("결과 폴더 경로가 없습니다.")
    try:
        root = Path(result_root).resolve()
        target_path = Path(raw_path)
        if target_path.is_symlink():
            return _error_event("결과 폴더를 확인할 수 없습니다.")
        target = target_path.resolve()
        expected = (root / str(report["job_id"])).resolve()
        if target != expected:
            return _error_event("결과 폴더가 허용된 작업 폴더 밖에 있습니다.")
        if not target.is_dir():
            return _error_event("결과 폴더를 확인할 수 없습니다.")
    except (OSError, RuntimeError, TypeError):
        return _error_event("결과 폴더를 확인할 수 없습니다.")
    return GuiEvent("result", report)


def stream_process(argv: list[str], cwd: Path, publish: Callable[[GuiEvent], None], *, request: RunRequest, result_root: Path = RESULT_ROOT, process_factory: Callable[..., Popen[bytes]] = Popen) -> None:
    """Launch and fully drain one CLI process from a worker thread."""
    if not isinstance(argv, list) or not callable(publish):
        raise TypeError("invalid process arguments")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["SODAM_RESULT_ROOT"] = str(result_root.resolve())
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = process_factory(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, env=env, creationflags=creationflags)
    except OSError as exc:
        publish(_error_event(f"Sodam 프로세스를 시작하지 못했습니다: {exc}"))
        publish(GuiEvent("exited", 1))
        return
    stdout = bytearray()
    diagnostics: list[str] = []
    overflow = False

    def read_stdout() -> None:
        nonlocal overflow
        try:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                if len(stdout) < MAX_STDOUT_BYTES:
                    stdout.extend(chunk[: MAX_STDOUT_BYTES - len(stdout)])
                if len(stdout) >= MAX_STDOUT_BYTES:
                    overflow = True
        except (OSError, ValueError) as exc:
            publish(_error_event(f"결과 출력을 읽지 못했습니다: {exc}"))

    def read_stderr() -> None:
        try:
            _read_progress_pipe(process.stderr, publish)
        except (OSError, ValueError, TypeError) as exc:
            publish(_error_event(f"진행 출력을 읽지 못했습니다: {exc}"))

    readers = [threading.Thread(target=read_stdout, name="sodam-gui-stdout"), threading.Thread(target=read_stderr, name="sodam-gui-stderr")]
    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join()
    try:
        exit_code = process.wait()
    finally:
        for pipe in (process.stdout, process.stderr):
            try:
                pipe.close()
            except OSError:
                pass
    if overflow:
        publish(_error_event("최종 결과 출력이 허용된 크기를 초과했습니다."))
    report_text = bytes(stdout).decode("utf-8", errors="replace")
    result_event = parse_runner_report(report_text, exit_code, request, result_root=result_root)
    publish(result_event)
    publish(GuiEvent("exited", exit_code))
