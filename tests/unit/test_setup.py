"""CLI contract tests for setup.py using injected collaborators."""

import importlib.util
from pathlib import Path

from backend.contracts import InstallationPlan, InstallationReceipt, RuntimeProfile, SystemProfile
from tests.fakes_productization import FakeSystemProbe


def _module():
    spec = importlib.util.spec_from_file_location("sodam_setup_bootstrap", Path("setup.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe():
    return FakeSystemProbe(SystemProfile("windows", "x86_64", "cpu", 1, None, None, 40 * 1024**3, ()))


def _profile():
    return RuntimeProfile("quality", "qwen3.6:35b-a3b-agent-64k", Path("stt"), Path("ffmpeg"))


def test_help_and_plan_only_are_read_only() -> None:
    setup = _module()
    output: list[str] = []
    assert setup.main(["--plan-only"], probe=_probe(), requested_profile=_profile(), output_fn=output.append) == 0
    assert any("download-qwen" in line for line in output)


def test_yes_executes_injected_executor_once() -> None:
    setup = _module()
    output: list[str] = []
    calls: list[InstallationPlan] = []

    def executor(plan):
        calls.append(plan)
        return InstallationReceipt(plan.requested_profile, (), (), "now")

    assert setup.main(["--yes"], probe=_probe(), requested_profile=_profile(), executor=executor, output_fn=output.append) == 0
    assert len(calls) == 1
    assert any("complete" in line.lower() for line in output)


def test_reject_and_missing_executor_have_stable_codes() -> None:
    setup = _module()
    output: list[str] = []
    assert setup.main([], probe=_probe(), requested_profile=_profile(), executor=lambda plan: None, input_fn=lambda _: "n", output_fn=output.append) == 4
    assert setup.main(["--yes"], probe=_probe(), requested_profile=_profile(), output_fn=output.append) == 3


def test_plan_only_wins_over_yes_and_executor_not_called() -> None:
    setup = _module()
    calls = []
    assert setup.main(["--yes", "--plan-only"], probe=_probe(), requested_profile=_profile(), executor=lambda plan: calls.append(plan), output_fn=lambda _: None) == 0
    assert calls == []


def test_bad_probe_or_executor_receipt_returns_error() -> None:
    setup = _module()
    assert setup.main([], probe=object(), requested_profile=_profile(), output_fn=lambda _: None) == 2
    assert setup.main(["--yes"], probe=_probe(), requested_profile=_profile(), executor=lambda plan: object(), output_fn=lambda _: None) == 3
