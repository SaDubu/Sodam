"""A small non-installed Tk interface for the existing Sodam CLI."""

from __future__ import annotations

import argparse
import math
from numbers import Real
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tools.gui_runner import (
    RESULT_ROOT,
    GuiEvent,
    GuiEventBuffer,
    GuiSettings,
    RunRequest,
    build_runner_argv,
    normalize_source,
    parse_runner_report,
    stream_process,
)


def format_elapsed(seconds: float) -> str:
    """P15-R1-F01 scaffold: format measured elapsed time as HH:MM:SS.

    Accept finite non-negative real seconds, floor fractional seconds and keep
    cumulative hours above 24. Reject bool/non-real with TypeError and negative,
    NaN or infinite values with ValueError. Return a string with no I/O or clock
    access. Direct tests cover 0, 59.9, 60, 3599, 3600, 86400 and invalid values.
    This helper computes neither remaining time nor a completion estimate.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, Real):
        raise TypeError("seconds must be a real number")
    if not math.isfinite(float(seconds)) or seconds < 0:
        raise ValueError("seconds must be finite and non-negative")
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


class SodamWindow:
    """Main-thread view/controller for one active Sodam CLI job."""

    _clock: Callable[[], float]
    _run_started_at: float | None
    _stage_started_at: float | None
    _finished_at: float | None
    _elapsed_timer_id: str | None
    _logged_stage_keys: set[tuple[str, str, str]]
    _latest_sequence: int
    _last_overall_progress: float | None
    _worker: threading.Thread | None
    _terminal_error: str | None
    progress_var: tk.StringVar
    total_elapsed_var: tk.StringVar
    stage_elapsed_var: tk.StringVar
    progress_bar: ttk.Progressbar

    def __init__(self, root: tk.Tk, settings: GuiSettings, *, launch_worker: Callable[..., object] | None = None, choose_path: Callable[[], str] | None = None, open_folder: Callable[[Path], None] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        """Build the non-installed Tk view and initialize one-run UI state."""
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.root = root
        self.settings = settings
        self.launch_worker = launch_worker or self._launch_worker
        self.choose_path = choose_path or self._native_choose_path
        self.open_folder = open_folder or self._native_open_folder
        self.state = "idle"
        self._buffer: GuiEventBuffer | None = None
        self._request: RunRequest | None = None
        self._report: dict[str, object] | None = None
        self._result_path: Path | None = None
        self._exit_code: int | None = None
        self._poll_id: str | None = None
        self._last_stage_key: tuple[str, str, str] | None = None
        self._close_notice_shown = False
        self._clock = clock
        self._run_started_at = None
        self._stage_started_at = None
        self._finished_at = None
        self._elapsed_timer_id = None
        self._logged_stage_keys = set()
        self._latest_sequence = -1
        self._last_overall_progress = None
        self._worker = None
        self._terminal_error = None

        root.title("Sodam")
        root.geometry("900x650")
        root.minsize(680, 480)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        input_frame = ttk.Frame(root, padding=12)
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.columnconfigure(1, weight=1)
        ttk.Label(input_frame, text="영상 주소 또는 파일 경로").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.source_var = tk.StringVar()
        self.source_entry = ttk.Entry(input_frame, textvariable=self.source_var)
        self.source_entry.grid(row=0, column=1, sticky="ew")
        self.file_button = ttk.Button(input_frame, text="파일 선택", command=self.choose_file)
        self.file_button.grid(row=0, column=2, padx=(8, 0))

        controls = ttk.Frame(root, padding=(12, 0, 12, 8))
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Label(controls, text="결과").pack(side="left")
        self.mode_var = tk.StringVar(value="both")
        self.mode_combo = ttk.Combobox(controls, state="readonly", width=16, textvariable=self.mode_var, values=("summary", "introduction", "both"))
        self.mode_combo.pack(side="left", padx=(8, 16))
        self.run_button = ttk.Button(controls, text="실행", command=self.start_run)
        self.run_button.pack(side="left")
        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(controls, textvariable=self.status_var).pack(side="left", padx=(16, 0))
        self.review_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.review_var).pack(side="right")

        progress_frame = ttk.LabelFrame(root, text="진행 상황", padding=(12, 8))
        progress_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        progress_frame.columnconfigure(1, weight=1)
        ttk.Label(progress_frame, text="현재 작업").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.current_task_var = tk.StringVar(value="대기 중")
        ttk.Label(progress_frame, textvariable=self.current_task_var).grid(row=0, column=1, columnspan=2, sticky="w")
        self.progress_var = tk.StringVar(value="전체 진행률: --")
        ttk.Label(progress_frame, textvariable=self.progress_var, width=18).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=100, value=0)
        self.progress_bar.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        self.total_elapsed_var = tk.StringVar(value="전체 경과 시간: 00:00:00")
        self.stage_elapsed_var = tk.StringVar(value="현재 단계 경과 시간: 00:00:00")
        ttk.Label(progress_frame, textvariable=self.total_elapsed_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(progress_frame, textvariable=self.stage_elapsed_var).grid(row=2, column=2, sticky="e", pady=(6, 0))

        result_frame = ttk.Frame(root, padding=(12, 0, 12, 12))
        result_frame.grid(row=3, column=0, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(result_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.text_widgets: dict[str, tk.Text] = {}
        for key, label in (("transcript", "전사문"), ("summary", "요약"), ("introduction", "소개글"), ("log", "실행 기록")):
            tab = ttk.Frame(self.notebook, padding=6)
            tab.rowconfigure(0, weight=1)
            tab.columnconfigure(0, weight=1)
            text = tk.Text(tab, wrap="word", state="disabled")
            text.grid(row=0, column=0, sticky="nsew")
            scroll = ttk.Scrollbar(tab, orient="vertical", command=text.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            text.configure(yscrollcommand=scroll.set)
            self.notebook.add(tab, text=label)
            self.text_widgets[key] = text
        actions = ttk.Frame(result_frame)
        actions.grid(row=1, column=0, sticky="e", pady=(8, 0))
        self.copy_button = ttk.Button(actions, text="복사", command=self.copy_result, state="disabled")
        self.copy_button.pack(side="left", padx=(0, 8))
        self.folder_button = ttk.Button(actions, text="결과 폴더 열기", command=self.open_result_folder, state="disabled")
        self.folder_button.pack(side="left")

    def _native_choose_path(self) -> str:
        return filedialog.askopenfilename(title="영상 파일 선택", filetypes=(("Video", "*.mp4 *.mkv *.mov *.avi *.webm *.wav"), ("All files", "*.*")))

    def _native_open_folder(self, path: Path) -> None:
        os.startfile(str(path))

    def _launch_worker(self, argv: list[str], request: RunRequest, buffer: GuiEventBuffer) -> threading.Thread:
        thread = threading.Thread(target=stream_process, kwargs={"argv": argv, "cwd": self.settings.runner_path.parent.parent, "publish": buffer.publish, "request": request, "result_root": self.settings.result_root}, daemon=True)
        thread.start()
        return thread

    def _set_text(self, key: str, value: str) -> None:
        widget = self.text_widgets[key]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.source_entry.configure(state=state)
        self.file_button.configure(state=state)
        self.mode_combo.configure(state="readonly" if enabled else "disabled")
        self.run_button.configure(state=state)

    def choose_file(self) -> None:
        if self.state in {"running", "finalizing"}:
            return
        selected = self.choose_path()
        if selected:
            self.source_var.set(selected)

    def start_run(self) -> None:
        if self.state in {"running", "finalizing"}:
            return
        try:
            source = normalize_source(self.source_var.get())
            request = RunRequest(source, self.mode_var.get())
            argv = build_runner_argv(request, self.settings)
        except Exception as exc:
            self._set_text("log", f"입력 오류: {exc}")
            self.status_var.set("입력 확인 필요")
            return
        self._request = request
        self._buffer = GuiEventBuffer()
        self._report = None
        self._result_path = None
        self._exit_code = None
        self._last_stage_key = None
        self._close_notice_shown = False
        self._run_started_at = self._clock()
        self._stage_started_at = None
        self._finished_at = None
        self._logged_stage_keys = set()
        self._latest_sequence = -1
        self._last_overall_progress = None
        self._terminal_error = None
        self._elapsed_timer_id = None
        self.current_task_var.set("시작 준비")
        self.progress_var.set("전체 진행률: --")
        self.progress_bar.configure(value=0)
        self.total_elapsed_var.set("전체 경과 시간: 00:00:00")
        self.stage_elapsed_var.set("현재 단계 경과 시간: 00:00:00")
        for key in self.text_widgets:
            self._set_text(key, "")
        self._set_controls(False)
        self.state = "running"
        self.status_var.set("실행 중")
        try:
            worker = self.launch_worker(argv, request, self._buffer)
            self._worker = worker if isinstance(worker, threading.Thread) else None
        except Exception as exc:
            self.state = "failed"
            self._set_controls(True)
            self._set_text("log", f"프로세스 시작 오류: {exc}")
            self.status_var.set("실패")
            return
        self._poll_id = self.root.after(100, self.drain_events)
        self._elapsed_timer_id = self.root.after(1000, self._tick_elapsed)

    def drain_events(self) -> None:
        self._poll_id = None
        if self._buffer is None:
            return
        for event in self._buffer.drain(100):
            if event.kind == "progress":
                progress = event.payload
                key = (progress.operation_id, progress.scope, progress.stage)
                if progress.sequence <= self._latest_sequence:
                    continue
                self._latest_sequence = progress.sequence
                self.current_task_var.set(progress.stage_label or progress.stage)
                if progress.overall_progress is not None:
                    self._last_overall_progress = progress.overall_progress
                    self.progress_var.set(f"전체 진행률: {progress.overall_progress * 100:.1f}%")
                    self.progress_bar.configure(value=progress.overall_progress * 100)
                elif self._last_overall_progress is None:
                    self.progress_var.set("전체 진행률: --")
                if key != self._last_stage_key:
                    self._last_stage_key = key
                    self._stage_started_at = self._clock()
                    percent = "" if progress.overall_progress is None else f"[{progress.overall_progress * 100:.1f}%] "
                    self.status_var.set(f"{percent}{progress.stage_label or progress.stage}")
                    if key not in self._logged_stage_keys:
                        self._logged_stage_keys.add(key)
                        self._append_log(f"{percent}{progress.stage}: {progress.message or progress.stage_label or progress.stage}")
                if progress.stage in {"completed", "failed", "cancelled"}:
                    self.state = "finalizing"
            elif event.kind == "diagnostic":
                self._append_log(str(event.payload))
            elif event.kind == "error":
                self._terminal_error = str(event.payload)
                self._append_log(str(event.payload))
            elif event.kind == "result":
                self._report = event.payload
            elif event.kind == "exited":
                self._exit_code = int(event.payload)
        worker_done = self._worker is None or not self._worker.is_alive()
        if self._exit_code is not None and worker_done and self._report is not None and self._exit_code == 0 and self._terminal_error is None:
            self.render_result(self._report)
            self.state = "succeeded"
            self._finished_at = self._clock()
            self._tick_elapsed()
            self._set_controls(True)
            self.status_var.set("완료")
        elif self._exit_code is not None and worker_done and (self._exit_code != 0 or self._report is None or self._terminal_error is not None):
            self.state = "failed"
            self._finished_at = self._clock()
            self._tick_elapsed()
            self._set_controls(True)
            self.current_task_var.set("실행 실패")
            self.status_var.set("실패")
        if self.state in {"running", "finalizing"}:
            self._poll_id = self.root.after(100, self.drain_events)

    def _tick_elapsed(self) -> None:
        """Refresh total and current-stage elapsed clocks without estimating ETA."""
        self._elapsed_timer_id = None
        if self._run_started_at is None:
            return
        try:
            now = self._clock()
            if not isinstance(now, Real) or isinstance(now, bool) or not math.isfinite(float(now)):
                raise ValueError("clock returned an invalid value")
            finish = self._finished_at if self._finished_at is not None else now
            total = max(0.0, finish - self._run_started_at)
            stage = 0.0 if self._stage_started_at is None else max(0.0, finish - self._stage_started_at)
            total_text = format_elapsed(total)
            stage_text = format_elapsed(stage)
        except (TypeError, ValueError, OverflowError):
            return
        self.total_elapsed_var.set(f"전체 경과 시간: {total_text}")
        self.stage_elapsed_var.set(f"현재 단계 경과 시간: {stage_text}")
        if self.state in {"running", "finalizing"}:
            self._elapsed_timer_id = self.root.after(1000, self._tick_elapsed)

    def _append_log(self, value: str) -> None:
        current = self.text_widgets["log"]
        current.configure(state="normal")
        current.insert("end", value + "\n")
        current.configure(state="disabled")
        current.see("end")

    def render_result(self, report: dict[str, object]) -> None:
        self._set_text("transcript", str(report.get("transcript") or ""))
        self._set_text("summary", str(report.get("summary") or ""))
        introduction = report.get("introduction")
        if isinstance(introduction, dict):
            intro_text = f"{introduction.get('title_hook', '')}\n\n{introduction.get('body', '')}"
        else:
            intro_text = ""
        self._set_text("introduction", intro_text)
        count = report.get("review_item_count", 0)
        self.review_var.set("검토 필요 " + str(count) + "건" if count else "")
        raw_path = report.get("result_path")
        if isinstance(raw_path, str):
            self._result_path = Path(raw_path)
            self.folder_button.configure(state="normal")
        self.copy_button.configure(state="normal")

    def copy_result(self) -> None:
        if self.state != "succeeded":
            return
        tab_id = self.notebook.select()
        key = next((key for key, widget in self.text_widgets.items() if str(widget.master) == tab_id), None)
        if key is None:
            index = self.notebook.index(tab_id)
            key = ("transcript", "summary", "introduction", "log")[index]
        try:
            value = self.text_widgets[key].get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status_var.set("복사 완료")
        except tk.TclError as exc:
            self._append_log(f"복사 오류: {exc}")

    def open_result_folder(self) -> None:
        if self._result_path is None or self._report is None:
            return
        try:
            root = self.settings.result_root.resolve()
            if self._result_path.is_symlink():
                raise ValueError("결과 폴더를 확인할 수 없습니다")
            target = self._result_path.resolve()
            expected = (root / str(self._report.get("job_id"))).resolve()
            if target != expected or not target.is_dir():
                raise ValueError("결과 폴더를 확인할 수 없습니다")
            self.open_folder(target)
        except (OSError, RuntimeError, ValueError) as exc:
            self._append_log(f"결과 폴더 오류: {exc}")

    def on_close(self) -> None:
        if self.state in {"running", "finalizing"}:
            if not self._close_notice_shown:
                self._close_notice_shown = True
                messagebox.showinfo("처리 중", "현재 작업이 끝난 뒤 창을 닫을 수 있습니다.", parent=self.root)
            return
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        if self._elapsed_timer_id is not None:
            self.root.after_cancel(self._elapsed_timer_id)
            self._elapsed_timer_id = None
        self.root.destroy()


def _settings(args: argparse.Namespace) -> GuiSettings:
    root = Path(__file__).resolve().parents[1]
    hermes = Path(args.hermes_command) if args.hermes_command else Path(shutil.which("hermes") or root / ".hermes-venv" / "Scripts" / "hermes.exe")
    hermes_python = Path(args.hermes_python) if args.hermes_python else hermes.parent / "python.exe"
    hermes_root = Path(args.hermes_root) if args.hermes_root else hermes.parent.parent / "Lib" / "site-packages"
    return GuiSettings(Path(args.python_path or sys.executable), root / "tools" / "run_local.py", hermes, hermes_python, hermes_root, args.hermes_version, Path(args.result_root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sodam simple local UI")
    parser.add_argument("--python-path")
    parser.add_argument("--hermes-command")
    parser.add_argument("--hermes-python")
    parser.add_argument("--hermes-root")
    parser.add_argument("--hermes-version", default="0.19.0")
    parser.add_argument("--result-root", default=str(RESULT_ROOT))
    args = parser.parse_args(argv)
    try:
        settings = _settings(args)
        if not settings.python_executable.is_file() or not settings.runner_path.is_file():
            raise ValueError("Python 또는 Sodam runner 경로를 확인하세요")
        root = tk.Tk()
        SodamWindow(root, settings)
        root.mainloop()
        return 0
    except (OSError, tk.TclError, ValueError) as exc:
        print(f"SODAM_GUI_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
