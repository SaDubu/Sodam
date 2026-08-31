"""Explicit-consent setup bootstrap (not a setuptools package definition)."""

import argparse
from collections.abc import Callable, Sequence
import platform
import shutil
from pathlib import Path

from backend.contracts import InstallationError, InstallationPlan, InstallationReceipt, RuntimeProfile, SystemProfile
from backend.installer import SystemProbe, plan_installation, probe_system
from backend.runtime_profile import default_runtime_profile


class _LocalSystemProbe:
    """Read-only standard-library probe used by the human-facing bootstrap."""

    def collect(self) -> SystemProfile:
        system_name = platform.system().lower()
        operating_system = {"windows": "windows", "darwin": "macos"}.get(system_name, system_name)
        try:
            free_disk = shutil.disk_usage(Path.cwd()).free
        except OSError:
            free_disk = None
        return SystemProfile(
            operating_system=operating_system,
            architecture=platform.machine() or "unknown",
            cpu_name=platform.processor() or None,
            ram_bytes=None,
            gpu_name=None,
            vram_bytes=None,
            free_disk_bytes=free_disk,
            tool_versions=(),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show and explicitly approve the Sodam installation plan.")
    parser.add_argument("--yes", action="store_true", help="approve the displayed plan without prompting")
    parser.add_argument("--plan-only", action="store_true", help="display the plan without executing it")
    parser.add_argument("--profile", default=None, help="runtime profile name (default: platform quality profile)")
    return parser


def _print_plan(plan: InstallationPlan, output_fn: Callable[[str], None]) -> None:
    output_fn(f"Installation profile: {plan.requested_profile}")
    output_fn(f"Required disk: {plan.required_disk_bytes} bytes")
    output_fn(f"Download: {plan.total_download_bytes or 0} bytes")
    for action in plan.actions:
        size = action.download_bytes if action.download_bytes is not None else 0
        output_fn(f"- {action.action_id}: {action.label} ({size} bytes)")
    for warning in plan.warnings:
        output_fn(f"Warning: {warning}")


def main(
    argv: Sequence[str] | None = None,
    *,
    probe: SystemProbe | None = None,
    requested_profile: RuntimeProfile | None = None,
    executor: Callable[[InstallationPlan], InstallationReceipt] | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Show a plan and execute it only after explicit consent.

    The injectable collaborators make this entry point safe to test without
    network, subprocess, package-manager, or filesystem mutation.
    """
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        system = probe_system(probe or _LocalSystemProbe())
        profile = requested_profile or default_runtime_profile(system.operating_system)
        if args.profile is not None and args.profile != profile.profile_name:
            profile = RuntimeProfile(
                args.profile,
                profile.qwen_model,
                profile.stt_model_path,
                profile.ffmpeg_path,
                profile.ollama_endpoint,
                profile.qwen_context_tokens,
            )
        plan = plan_installation(system, profile)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        output_fn(f"Setup planning failed: {exc}")
        return 2
    _print_plan(plan, output_fn)
    if args.plan_only:
        return 0

    approved = args.yes
    if not approved and executor is not None:
        try:
            approved = input_fn("Execute this plan? [y/N] ").strip().lower() in {"y", "yes"}
        except (KeyboardInterrupt, EOFError):
            output_fn("Setup cancelled.")
            return 4
    if not approved:
        if executor is None:
            output_fn("Plan displayed only. Re-run with --yes after reviewing it.")
            return 0
        output_fn("Setup not approved.")
        return 4
    if executor is None:
        output_fn("No installer backend is configured; no changes were made.")
        return 3
    try:
        receipt = executor(plan)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        output_fn(f"Setup execution failed: {exc}")
        return 3
    if not isinstance(receipt, InstallationReceipt):
        output_fn("Setup execution returned an invalid receipt.")
        return 3
    output_fn(f"Setup complete: {receipt.profile_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
