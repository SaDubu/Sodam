"""First-run installation and OS-specific build contract skeletons.

Importing this module performs no probe, download, installation, build, or file
mutation. External work will require a validated plan and explicit user consent.
"""

from collections.abc import Callable
from datetime import datetime, timezone
import platform
import sys
from typing import Protocol

from .contracts import (
    BuildArtifact,
    BuildError,
    InstallationAction,
    InstallationError,
    InstallationPlan,
    InstallationReceipt,
    ProgressEvent,
    RuntimeProfile,
    SystemProfile,
)
from .progress import ProgressSink


class CancellationToken(Protocol):
    """Expose cooperative cancellation without owning process termination policy."""

    def is_cancelled(self) -> bool:
        """Return True after the user has requested cancellation."""
        ...


class SystemProbe(Protocol):
    """Read host capabilities without changing local state."""

    def collect(self) -> SystemProfile:
        """Return the available host and tool information."""
        ...


class InstallerBackend(Protocol):
    """Perform one predeclared action and report measurable progress."""

    def execute_action(
        self,
        action_id: str,
        emit: Callable[[ProgressEvent], None],
        cancellation: CancellationToken,
    ) -> None:
        """Execute only the exact action selected from a validated plan."""
        ...


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


_SUPPORTED_OS = {"windows", "macos", "linux"}
_SUPPORTED_ARCHITECTURES = {"x86_64", "amd64", "arm64", "aarch64"}
_QWEN_DOWNLOAD_BYTES = 23 * 1024**3
_STT_DOWNLOAD_BYTES = 2 * 1024**3
_REQUIRED_DISK_BYTES = _QWEN_DOWNLOAD_BYTES + _STT_DOWNLOAD_BYTES


def _require_callable(value: object, name: str) -> None:
    if not callable(getattr(value, name, None)):
        raise TypeError(f"{name} must be provided")


def _validate_system(system: object) -> SystemProfile:
    if not isinstance(system, SystemProfile):
        raise TypeError("system must be a SystemProfile")
    operating_system = system.operating_system.strip().lower()
    architecture = system.architecture.strip().lower()
    if operating_system not in _SUPPORTED_OS:
        raise InstallationError(f"unsupported operating system: {system.operating_system!r}")
    if architecture not in _SUPPORTED_ARCHITECTURES:
        raise InstallationError(f"unsupported architecture: {system.architecture!r}")
    if system.free_disk_bytes is not None and (
        isinstance(system.free_disk_bytes, bool)
        or not isinstance(system.free_disk_bytes, int)
        or system.free_disk_bytes < 0
    ):
        raise InstallationError("free_disk_bytes must be a non-negative integer or None")
    return system


def _validate_runtime(profile: object) -> RuntimeProfile:
    if not isinstance(profile, RuntimeProfile):
        raise TypeError("requested_profile must be a RuntimeProfile")
    if not profile.profile_name.strip() or not profile.qwen_model.strip():
        raise InstallationError("runtime profile name and qwen model must be non-blank")
    return profile


def probe_system(probe: SystemProbe) -> SystemProfile:
    """Collect a read-only host profile while preserving unavailable fields."""
    _require_callable(probe, "collect")
    try:
        result = probe.collect()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        raise InstallationError("system probe failed") from exc
    if not isinstance(result, SystemProfile):
        raise InstallationError("system probe returned an invalid profile")
    return _validate_system(result)


def plan_installation(
    system: SystemProfile,
    requested_profile: RuntimeProfile,
) -> InstallationPlan:
    """Return a complete, user-reviewable plan before any external change."""
    system = _validate_system(system)
    requested_profile = _validate_runtime(requested_profile)
    installed = {name.strip().lower() for name, _ in system.tool_versions}
    actions: list[InstallationAction] = [
        InstallationAction("verify-ollama", "Verify Ollama runtime"),
        InstallationAction("verify-ffmpeg", "Verify FFmpeg executable"),
    ]
    if requested_profile.qwen_model.lower() not in installed and "qwen" not in installed:
        actions.append(
            InstallationAction(
                "download-qwen",
                f"Download Qwen model {requested_profile.qwen_model}",
                _QWEN_DOWNLOAD_BYTES,
                _QWEN_DOWNLOAD_BYTES,
            )
        )
    if "stt" not in installed and "faster-whisper" not in installed:
        actions.append(
            InstallationAction(
                "download-stt",
                "Download faster-whisper STT model",
                _STT_DOWNLOAD_BYTES,
                _STT_DOWNLOAD_BYTES,
            )
        )
    total_download = sum(
        action.download_bytes or 0 for action in actions
    )
    required_disk = sum(action.required_disk_bytes or 0 for action in actions)
    warnings: list[str] = []
    if system.free_disk_bytes is None:
        warnings.append("free disk capacity unavailable; verify before execution")
    elif system.free_disk_bytes < required_disk:
        raise InstallationError(
            f"insufficient free disk space: need {required_disk} bytes, have {system.free_disk_bytes}"
        )
    return InstallationPlan(
        requested_profile=requested_profile.profile_name,
        actions=tuple(actions),
        total_download_bytes=total_download or 0,
        required_disk_bytes=required_disk,
        warnings=tuple(warnings),
    )


def execute_installation(
    plan: InstallationPlan,
    backend: InstallerBackend,
    sink: ProgressSink | None = None,
    cancellation: CancellationToken | None = None,
) -> InstallationReceipt:
    """Execute an approved plan and return verified exact versions and model IDs."""
    if not isinstance(plan, InstallationPlan):
        raise TypeError("plan must be an InstallationPlan")
    _require_callable(backend, "execute_action")
    if sink is not None:
        _require_callable(sink, "emit")
    if cancellation is None:
        cancellation = _NeverCancelled()
    _require_callable(cancellation, "is_cancelled")
    action_ids: list[str] = []
    for action in plan.actions:
        if not isinstance(action, InstallationAction) or not action.action_id.strip():
            raise InstallationError("installation plan contains an invalid action")
        if action.action_id in action_ids:
            raise InstallationError(f"duplicate installation action: {action.action_id}")
        if cancellation.is_cancelled():
            raise InstallationError("installation cancelled")
        action_ids.append(action.action_id)

        def emit(event: ProgressEvent) -> None:
            if not isinstance(event, ProgressEvent):
                raise InstallationError("installer emitted an invalid progress event")
            if sink is not None:
                sink.emit(event)

        try:
            backend.execute_action(action.action_id, emit, cancellation)
        except (KeyboardInterrupt, SystemExit):
            raise
        except InstallationError:
            raise
        except Exception as exc:
            raise InstallationError(f"installation action failed: {action.action_id}") from exc
    if cancellation.is_cancelled():
        raise InstallationError("installation cancelled")
    completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    installed_tools = tuple(
        (action_id.removeprefix("verify-"), "verified")
        for action_id in action_ids
        if action_id.startswith("verify-")
    )
    model_identifiers = tuple(
        (action_id.removeprefix("download-"), "completed")
        for action_id in action_ids
        if action_id.startswith("download-")
    )
    return InstallationReceipt(
        profile_name=plan.requested_profile,
        installed_tools=installed_tools,
        model_identifiers=model_identifiers,
        completed_at=completed_at,
    )


def build_desktop(target_os: str, mode: str) -> BuildArtifact:
    """Build only for the current supported OS into the designated build root."""
    if not isinstance(target_os, str) or not isinstance(mode, str):
        raise TypeError("target_os and mode must be strings")
    target = target_os.strip().lower()
    if target not in _SUPPORTED_OS:
        raise BuildError(f"unsupported target OS: {target_os!r}")
    if mode not in {"development", "release"}:
        raise BuildError(f"unsupported build mode: {mode!r}")
    current = {
        "win32": "windows",
        "darwin": "macos",
        "linux": "linux",
    }.get(sys.platform, sys.platform)
    if target != current:
        raise BuildError(f"cross-OS build is not permitted: {target} on {current}")
    # Packaging is deliberately deferred to V2-BUILD01; do not pretend that
    # a bundle exists before the OS-specific builder and signing policy land.
    raise BuildError("desktop packaging is not implemented in V2-SETUP01")
