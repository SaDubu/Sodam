"""No-network setup flow integration checks using only injected collaborators."""

from backend.contracts import InstallationError, ProgressEvent, SystemProfile
from backend.installer import execute_installation, plan_installation, probe_system
from backend.runtime_profile import default_runtime_profile
from tests.fakes_productization import FakeCancellationToken, FakeSystemProbe, RecordingInstallerBackend


def test_setup_probe_plan_execute_flow_is_external_side_effect_free() -> None:
    system = SystemProfile("windows", "x86_64", "fake-cpu", 8, None, None, 40 * 1024**3, ())
    profile = default_runtime_profile("windows")
    assert probe_system(FakeSystemProbe(system)) == system
    plan = plan_installation(system, profile)
    backend = RecordingInstallerBackend({action.action_id: () for action in plan.actions})
    receipt = execute_installation(plan, backend, cancellation=FakeCancellationToken())
    assert receipt.profile_name == profile.profile_name
    assert backend.action_ids == tuple(action.action_id for action in plan.actions)


def test_setup_failure_preserves_cause_and_stops_following_actions() -> None:
    system = SystemProfile("windows", "x86_64", "fake-cpu", 8, None, None, 40 * 1024**3, ())
    plan = plan_installation(system, default_runtime_profile("windows"))

    class FailingBackend:
        def __init__(self):
            self.calls = []

        def execute_action(self, action_id, emit, cancellation):
            self.calls.append(action_id)
            if action_id == "download-qwen":
                raise OSError("checksum mismatch")

    backend = FailingBackend()
    try:
        execute_installation(plan, backend, cancellation=FakeCancellationToken())
    except InstallationError as exc:
        assert isinstance(exc.__cause__, OSError)
    else:
        raise AssertionError("expected InstallationError")
    assert backend.calls == ["verify-ollama", "verify-ffmpeg", "download-qwen"]
