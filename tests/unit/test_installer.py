"""Contract tests for the V2-SETUP01 installer manager."""

from pathlib import Path
import sys

import pytest

from backend.contracts import (
    BuildError,
    InstallationError,
    ProgressEvent,
    RuntimeProfile,
    SystemProfile,
)
from backend.installer import (
    build_desktop,
    execute_installation,
    plan_installation,
    probe_system,
)
from tests.fakes_productization import (
    FakeCancellationToken,
    FakeSystemProbe,
    RecordingInstallerBackend,
)


def _profile(*, disk: int | None = 40 * 1024**3, tools=()) -> SystemProfile:
    return SystemProfile("windows", "x86_64", "cpu", 16 * 1024**3, None, None, disk, tools)


def _runtime() -> RuntimeProfile:
    return RuntimeProfile("quality", "qwen3.6:35b-a3b-agent-64k", Path("stt"), Path("ffmpeg"))


def test_probe_delegates_once_and_rejects_bad_probe() -> None:
    probe = FakeSystemProbe(_profile())
    assert probe_system(probe) == _profile()
    assert probe.call_count == 1
    with pytest.raises(TypeError):
        probe_system(object())  # type: ignore[arg-type]


def test_plan_has_deterministic_actions_and_skips_existing_models() -> None:
    plan = plan_installation(_profile(), _runtime())
    assert [action.action_id for action in plan.actions] == [
        "verify-ollama",
        "verify-ffmpeg",
        "download-qwen",
        "download-stt",
    ]
    existing = plan_installation(
        _profile(tools=(("qwen", "present"), ("stt", "present"))), _runtime()
    )
    assert [action.action_id for action in existing.actions] == ["verify-ollama", "verify-ffmpeg"]
    assert existing.total_download_bytes == 0


def test_plan_rejects_unsupported_system_and_insufficient_disk() -> None:
    with pytest.raises(InstallationError):
        plan_installation(SystemProfile("plan9", "x86_64", None, None, None, None, None), _runtime())
    with pytest.raises(InstallationError):
        plan_installation(_profile(disk=1), _runtime())
    warning_plan = plan_installation(_profile(disk=None), _runtime())
    assert warning_plan.warnings


def test_execute_calls_backend_in_order_and_returns_receipt() -> None:
    plan = plan_installation(_profile(), _runtime())
    backend = RecordingInstallerBackend({action.action_id: () for action in plan.actions})
    receipt = execute_installation(plan, backend, cancellation=FakeCancellationToken())
    assert backend.action_ids == tuple(action.action_id for action in plan.actions)
    assert receipt.profile_name == "quality"
    assert receipt.installed_tools == (("ollama", "verified"), ("ffmpeg", "verified"))
    assert receipt.completed_at.endswith("Z")


def test_execute_cancellation_prevents_backend_and_wraps_failures() -> None:
    plan = plan_installation(_profile(), _runtime())
    cancelled = FakeCancellationToken(True)
    backend = RecordingInstallerBackend({action.action_id: () for action in plan.actions})
    with pytest.raises(InstallationError, match="cancelled"):
        execute_installation(plan, backend, cancellation=cancelled)
    assert backend.action_ids == ()

    class FailingBackend:
        def execute_action(self, action_id, emit, cancellation):
            raise RuntimeError("boom")

    with pytest.raises(InstallationError, match="failed") as caught:
        execute_installation(plan, FailingBackend(), cancellation=FakeCancellationToken())
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_execute_validates_events_and_duplicate_actions() -> None:
    from backend.contracts import InstallationAction, InstallationPlan

    duplicate = InstallationPlan("quality", (InstallationAction("x", "x"), InstallationAction("x", "x")), 0, 0)
    backend = RecordingInstallerBackend({"x": ()})
    with pytest.raises(InstallationError, match="duplicate"):
        execute_installation(duplicate, backend, cancellation=FakeCancellationToken())

    class BadEventBackend:
        def execute_action(self, action_id, emit, cancellation):
            emit(object())

    valid = InstallationPlan("quality", (InstallationAction("x", "x"),), 0, 0)
    with pytest.raises(InstallationError, match="progress"):
        execute_installation(valid, BadEventBackend(), cancellation=FakeCancellationToken())


def test_build_desktop_rejects_cross_os_and_defers_packaging() -> None:
    current = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform, sys.platform)
    other = "linux" if current != "linux" else "windows"
    with pytest.raises(BuildError, match="cross-OS"):
        build_desktop(other, "release")
    with pytest.raises(BuildError, match="not implemented"):
        build_desktop(current, "development")
