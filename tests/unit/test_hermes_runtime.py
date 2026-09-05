"""P13-01 compatibility and P13-03 local adapter contract tests."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.hermes_runtime import (
    HermesExecutionProfile,
    LocalHermesRuntime,
    check_hermes_compatibility,
)
from backend.contracts import ModelResponseError
import backend.hermes_runtime as hermes_runtime


@pytest.fixture(autouse=True)
def fake_hermes_version_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every compatibility test use a fake --version command."""
    monkeypatch.setattr(
        hermes_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Hermes Agent v0.1.0 (fixture)",
            stderr="",
        ),
    )


def _write_source(root: Path, *, runner: str | None = None, agent_init: str | None = None) -> None:
    """Create only the source fixture files inspected by the compatibility checker."""
    (root / "agent").mkdir(parents=True, exist_ok=True)
    (root / "run_agent.py").write_text(
        runner
        or "class AIAgent:\n    def run_conversation(self):\n        return {'final_response': ''}\n",
        encoding="utf-8",
    )
    (root / "agent" / "agent_init.py").write_text(
        agent_init
        or (
            "def init(enabled_toolsets=None, skip_memory=False, "
            "skip_background_review=False, max_iterations=1, fallback_model=None):\n"
            "    return None\n"
        ),
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")


def _profile(root: Path, **overrides: object) -> HermesExecutionProfile:
    """Build a valid profile whose executable is a fixture file and is never run."""
    executable = root / "python.exe"
    executable.write_text("fixture", encoding="utf-8")
    hermes_command = root / "hermes.exe"
    hermes_command.write_text("fixture", encoding="utf-8")
    value = HermesExecutionProfile(
        python_executable=executable,
        hermes_root=root,
        expected_version="0.1.0",
        model="qwen3.6:35b-a3b-agent-64k",
        base_url="http://127.0.0.1:11434/v1",
        hermes_command=hermes_command,
    )
    return replace(value, **overrides)


def test_compatible_fixture_reports_all_required_checks_and_zero_model_calls(tmp_path: Path) -> None:
    """A complete pinned source fixture is compatible without importing Hermes."""
    _write_source(tmp_path)

    report = check_hermes_compatibility(_profile(tmp_path))

    assert report["status"] == "compatible"
    assert report["source_files"] == {"command": True, "runner": True, "agent_init": True}
    required_checks = {
        name: value
        for name, value in report["api_checks"].items()
        if name != "skip_background_review"
    }
    assert all(required_checks.values())
    assert report["api_checks"]["skip_background_review"] is True
    assert report["missing_checks"] == []
    assert report["model_calls"] == 0


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("runner_missing", "runner"),
        ("agent_init_missing", "agent_init"),
        ("agent_class_missing", "AIAgent"),
        ("conversation_missing", "run_conversation"),
        ("final_key_missing", "final_response"),
        ("agent_option_missing", "fallback_model"),
    ],
)
def test_missing_source_or_api_symbol_is_reported_without_raw_source_error(
    tmp_path: Path, variant: str, expected: str
) -> None:
    """Each missing compatibility requirement produces a deterministic safe report."""
    _write_source(tmp_path)
    if variant == "runner_missing":
        (tmp_path / "run_agent.py").unlink()
    elif variant == "agent_init_missing":
        (tmp_path / "agent" / "agent_init.py").unlink()
    elif variant == "agent_class_missing":
        _write_source(tmp_path, runner="def run_conversation(self):\n    return {'final_response': ''}\n")
    elif variant == "conversation_missing":
        _write_source(tmp_path, runner="class AIAgent:\n    pass\n")
    elif variant == "final_key_missing":
        _write_source(tmp_path, runner="class AIAgent:\n    def run_conversation(self):\n        return {}\n")
    else:
        _write_source(tmp_path, agent_init="def init(enabled_toolsets=None, skip_memory=False):\n    return None\n")

    report = check_hermes_compatibility(_profile(tmp_path))

    assert report["status"] == "incompatible"
    assert expected in report["missing_checks"]
    assert "traceback" not in str(report).lower()


@pytest.mark.parametrize(
    "field",
    [
        "base_url",
        "timeout_seconds",
        "context_tokens",
        "max_prompt_bytes",
        "max_final_response_bytes",
        "max_worker_stdout_bytes",
    ],
)
def test_invalid_profile_is_rejected_before_source_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Static profile failures do not inspect Hermes source files."""
    _write_source(tmp_path)
    values = {
        "base_url": "https://example.com/v1",
        "timeout_seconds": 0,
        "context_tokens": 262_145,
        "max_prompt_bytes": 1_048_577,
        "max_final_response_bytes": 1_048_577,
        "max_worker_stdout_bytes": 4_194_305,
    }
    profile = _profile(tmp_path, **{field: values[field]})
    reads = 0
    original = Path.read_text

    def spy(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal reads
        reads += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    with pytest.raises(ValueError):
        check_hermes_compatibility(profile)
    assert reads == 0


def test_malformed_sources_are_safe_and_do_not_expose_source_text(tmp_path: Path) -> None:
    """Parser failures become incompatible checks rather than raw exceptions."""
    secret = "prompt transcript credential SHOULD_NOT_LEAK"
    _write_source(tmp_path, runner=secret, agent_init="def [broken(:\n    pass\n")
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")

    report = check_hermes_compatibility(_profile(tmp_path))

    assert report["status"] == "incompatible"
    assert report["model_calls"] == 0
    assert secret not in repr(report)
    assert "TOMLDecodeError" not in repr(report)


def test_wrong_type_relative_path_symlink_and_nonlocal_endpoint_are_rejected(
    tmp_path: Path,
) -> None:
    """Profile boundary errors are rejected without compatibility results."""
    _write_source(tmp_path)
    with pytest.raises(TypeError):
        check_hermes_compatibility(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        check_hermes_compatibility(_profile(tmp_path, base_url="http://127.0.0.1:11434/v1?x=1"))
    with pytest.raises(ValueError):
        check_hermes_compatibility(_profile(tmp_path, hermes_root=Path("relative")))


def test_command_version_mismatch_is_reported_without_exposing_process_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed command must match the pinned version before use."""
    _write_source(tmp_path)
    monkeypatch.setattr(
        hermes_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Hermes Agent v9.9.9; secret prompt SHOULD_NOT_LEAK",
            stderr="",
        ),
    )

    report = check_hermes_compatibility(_profile(tmp_path))

    assert report["status"] == "incompatible"
    assert "version" in report["missing_checks"]
    assert "SHOULD_NOT_LEAK" not in repr(report)


def test_local_runtime_sends_one_envelope_to_worker_and_returns_final_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_source(tmp_path)
    current = _profile(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs))
        request = json.loads(str(kwargs["input"]))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "protocol_version": 1,
                    "request_id": request["request_id"],
                    "status": "completed",
                    "final_response": '{"text":"ok"}',
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(hermes_runtime.subprocess, "run", fake_run)
    result = LocalHermesRuntime(current).complete("prompt")

    assert result == '{"text":"ok"}'
    assert len(calls) == 1
    assert calls[0][0][0] == str(current.python_executable)
    assert calls[0][0][1].endswith("tools\\hermes_worker.py")
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["env"]["PYTHONUTF8"] == "1"
    assert calls[0][1]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert json.loads(str(calls[0][1]["input"]))["prompt"] == "prompt"


def test_local_runtime_rejects_oversized_prompt_before_child_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_source(tmp_path)
    current = _profile(tmp_path, max_prompt_bytes=3)
    called = False

    def fail_run(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal called
        called = True
        raise AssertionError("worker must not run")

    monkeypatch.setattr(hermes_runtime.subprocess, "run", fail_run)
    with pytest.raises(ModelResponseError):
        LocalHermesRuntime(current).complete("four")
    assert not called


def test_local_runtime_maps_malformed_worker_response_to_safe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_source(tmp_path)
    monkeypatch.setattr(
        hermes_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="secret", stderr="traceback"),
    )

    with pytest.raises(ModelResponseError) as caught:
        LocalHermesRuntime(_profile(tmp_path)).complete("prompt")
    assert getattr(caught.value, "diagnostic_code") == "protocol_invalid"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("diagnostic", ["response_empty", "hermes_process_failed"])
def test_local_runtime_preserves_worker_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diagnostic: str
) -> None:
    _write_source(tmp_path)
    request_id = "request-id"

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        request = json.loads(str(kwargs["input"]))
        assert request["request_id"]
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "protocol_version": 1,
                    "request_id": request["request_id"],
                    "status": "failed",
                    "error_code": diagnostic,
                }
            ),
            stderr="secret stderr",
        )

    monkeypatch.setattr(hermes_runtime.subprocess, "run", fake_run)
    with pytest.raises(ModelResponseError) as caught:
        LocalHermesRuntime(_profile(tmp_path)).complete("prompt")

    assert getattr(caught.value, "diagnostic_code") == diagnostic
    assert request_id not in str(caught.value)
