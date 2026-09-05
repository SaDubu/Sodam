"""P13-03 Hermes one-shot worker contract tests."""

from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.hermes_worker as worker
from backend.hermes_runtime import HermesExecutionProfile


def profile(tmp_path: Path) -> HermesExecutionProfile:
    python = tmp_path / "python.exe"
    python.write_text("fixture", encoding="utf-8")
    command = tmp_path / "hermes.exe"
    command.write_text("fixture", encoding="utf-8")
    return HermesExecutionProfile(
        python,
        tmp_path,
        "0.19.0",
        "qwen3.6:35b-a3b-agent-64k",
        "http://127.0.0.1:11434/v1",
        hermes_command=command,
    )


def test_one_shot_uses_installed_command_and_safe_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"text":"완료"}', stderr="secret stderr")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    result = worker.run_hermes_request("전사문으로 요약해줘", profile(tmp_path))

    assert result == '{"text":"완료"}'
    argv = calls[0][0]
    assert argv[:2] == [str(tmp_path / "hermes.exe"), "--oneshot"]
    assert "전사문으로 요약해줘" in argv
    assert ["--model", "qwen3.6:35b-a3b-agent-64k"] == argv[3:5]
    assert "--provider" in argv and "custom" in argv
    assert "--ignore-rules" in argv
    assert argv[-2:] == ["-t", ""]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["env"]["PYTHONUTF8"] == "1"
    assert calls[0][1]["env"]["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (SimpleNamespace(returncode=1, stdout="", stderr="secret"), "hermes_process_failed"),
        (SimpleNamespace(returncode=0, stdout="", stderr=""), "response_empty"),
        (SimpleNamespace(returncode=0, stdout="x" * 100, stderr=""), "response_too_large"),
    ],
)
def test_failed_one_shot_returns_allowlisted_error_without_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    result: SimpleNamespace,
    code: str,
) -> None:
    monkeypatch.setattr(worker.subprocess, "run", lambda *args, **kwargs: result)
    current = profile(tmp_path)
    if code == "response_too_large":
        current = HermesExecutionProfile(
            current.python_executable,
            current.hermes_root,
            current.expected_version,
            current.model,
            current.base_url,
            max_final_response_bytes=10,
            hermes_command=current.hermes_command,
        )

    with pytest.raises(worker.HermesWorkerError) as caught:
        worker.run_hermes_request("prompt", current)
    assert caught.value.code == code
    assert "secret" not in str(caught.value)


def test_fake_agent_accepts_only_final_response() -> None:
    current = HermesExecutionProfile(
        Path("C:/fixture/python.exe"),
        Path("C:/fixture"),
        "0.19.0",
        "model",
        "http://127.0.0.1:11434/v1",
    )

    class Agent:
        def run_conversation(self, prompt: str) -> dict[str, object]:
            return {"messages": ["trace"], "final_response": "final"}

    assert worker.run_hermes_request("prompt", current, agent_factory=lambda **_: Agent()) == "final"


def test_main_emits_one_completed_envelope(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    command = tmp_path / "hermes.exe"
    command.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="final response", stderr=""),
    )
    monkeypatch.setattr(worker.sys, "stdin", StringIO(json.dumps({
        "protocol_version": 1,
        "request_id": "request-1",
        "prompt": "prompt",
    }) + "\n"))

    status = worker.main([
        "--hermes-command", str(command),
        "--model", "model",
        "--max-prompt-bytes", "1000",
        "--max-response-bytes", "1000",
        "--timeout-seconds", "10",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload == {
        "protocol_version": 1,
        "request_id": "request-1",
        "status": "completed",
        "final_response": "final response",
    }


def test_main_rejects_extra_request_fields_without_running_hermes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = False

    def fail_run(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal called
        called = True
        raise AssertionError("Hermes must not run")

    monkeypatch.setattr(worker.subprocess, "run", fail_run)
    monkeypatch.setattr(worker.sys, "stdin", StringIO(json.dumps({
        "protocol_version": 1,
        "request_id": "request-1",
        "prompt": "prompt",
        "secret": "must not leak",
    }) + "\n"))

    status = worker.main([
        "--hermes-command", "C:/fixture/hermes.exe",
        "--model", "model",
        "--max-prompt-bytes", "1000",
        "--max-response-bytes", "1000",
        "--timeout-seconds", "10",
    ])

    output = capsys.readouterr().out
    assert status == 1
    assert not called
    assert "must not leak" not in output
    assert json.loads(output)["error_code"] == "protocol_invalid"
