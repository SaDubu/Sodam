"""Local Hermes compatibility checks and one-shot worker adapter."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from urllib.parse import urlsplit

from .contracts import ModelResponseError


HERMES_PROTOCOL_VERSION = 1
MAX_HERMES_TIMEOUT_SECONDS = 600
MAX_HERMES_CONTEXT_TOKENS = 262_144
MAX_HERMES_PROMPT_BYTES = 1_048_576
MAX_HERMES_RESPONSE_BYTES = 1_048_576
MAX_HERMES_WORKER_STDOUT_BYTES = 4_194_304
HERMES_DIAGNOSTIC_CODES = frozenset(
    {
        "runtime_unavailable",
        "runtime_incompatible",
        "runtime_timeout",
        "context_limit",
        "response_too_large",
        "protocol_invalid",
        "hermes_process_failed",
        "response_empty",
    }
)


@dataclass(frozen=True)
class HermesExecutionProfile:
    """Declare the isolated local Hermes runtime selected by the caller.

    P13-03 will validate each field before worker creation. The profile contains
    no authentication token, user prompt, transcript, or persistent history.
    """

    python_executable: Path
    hermes_root: Path
    expected_version: str
    model: str
    base_url: str
    timeout_seconds: int = MAX_HERMES_TIMEOUT_SECONDS
    max_prompt_bytes: int = 131_072
    max_final_response_bytes: int = 65_536
    max_worker_stdout_bytes: int = 524_288
    context_tokens: int = 32_768
    hermes_command: Path | None = None


def validate_hermes_profile(profile: HermesExecutionProfile) -> None:
    """Validate static profile values without probing a local installation.

    This check is static and does not start Hermes or Ollama.
    """
    if not isinstance(profile, HermesExecutionProfile):
        raise TypeError("profile must be a HermesExecutionProfile")
    if not isinstance(profile.python_executable, Path) or not isinstance(profile.hermes_root, Path):
        raise TypeError("profile paths must be Path values")
    if not profile.python_executable.is_absolute() or not profile.hermes_root.is_absolute():
        raise ValueError("profile paths must be absolute")
    if profile.python_executable.is_symlink() or profile.hermes_root.is_symlink():
        raise ValueError("profile paths must not be symlinks")
    if not profile.python_executable.is_file() or not profile.hermes_root.is_dir():
        raise ValueError("profile paths must exist with the expected type")
    if not isinstance(profile.hermes_command, (Path, type(None))):
        raise TypeError("hermes_command must be a Path or None")
    if profile.hermes_command is not None and (
        not profile.hermes_command.is_absolute()
        or profile.hermes_command.is_symlink()
        or not profile.hermes_command.is_file()
    ):
        raise ValueError("hermes_command must be an existing absolute file")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (profile.expected_version, profile.model)
    ):
        raise ValueError("expected_version and model must be non-blank strings")
    if (
        isinstance(profile.timeout_seconds, bool)
        or not isinstance(profile.timeout_seconds, int)
        or not 1 <= profile.timeout_seconds <= MAX_HERMES_TIMEOUT_SECONDS
        or isinstance(profile.context_tokens, bool)
        or not isinstance(profile.context_tokens, int)
        or not 1 <= profile.context_tokens <= MAX_HERMES_CONTEXT_TOKENS
        or isinstance(profile.max_prompt_bytes, bool)
        or not isinstance(profile.max_prompt_bytes, int)
        or not 1 <= profile.max_prompt_bytes <= MAX_HERMES_PROMPT_BYTES
        or isinstance(profile.max_final_response_bytes, bool)
        or not isinstance(profile.max_final_response_bytes, int)
        or not 1 <= profile.max_final_response_bytes <= MAX_HERMES_RESPONSE_BYTES
        or isinstance(profile.max_worker_stdout_bytes, bool)
        or not isinstance(profile.max_worker_stdout_bytes, int)
        or not 1 <= profile.max_worker_stdout_bytes <= MAX_HERMES_WORKER_STDOUT_BYTES
    ):
        raise ValueError("Hermes runtime limits are outside their bounded ranges")
    try:
        endpoint = urlsplit(profile.base_url)
        endpoint_port = endpoint.port
    except ValueError as exc:
        raise ValueError("base_url port is invalid") from exc
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"127.0.0.1", "::1"}
        or endpoint_port != 11434
        or endpoint.path != "/v1"
        or endpoint.query
        or endpoint.fragment
        or endpoint.username is not None
        or endpoint.password is not None
    ):
        raise ValueError("base_url must be the local Ollama OpenAI endpoint")
    if profile.hermes_command is None and shutil.which("hermes") is None:
        raise ValueError("Hermes command is unavailable")


def check_hermes_compatibility(profile: HermesExecutionProfile) -> dict[str, object]:
    """Perform the future isolated preflight before transcript transmission.

    The completed check will verify the pinned Hermes API and disabled tool,
    memory, trajectory, fallback, and background-review capabilities. It will
    not install software, mutate a personal Hermes profile, or invoke a model.
    """
    if not isinstance(profile, HermesExecutionProfile):
        raise TypeError("profile must be a HermesExecutionProfile")
    if not isinstance(profile.python_executable, Path) or not isinstance(profile.hermes_root, Path):
        raise TypeError("profile paths must be Path values")
    if not profile.python_executable.is_absolute() or not profile.hermes_root.is_absolute():
        raise ValueError("profile paths must be absolute")
    if profile.python_executable.is_symlink() or profile.hermes_root.is_symlink():
        raise ValueError("profile paths must not be symlinks")
    if not profile.python_executable.is_file() or not profile.hermes_root.is_dir():
        raise ValueError("profile paths must exist with the expected type")
    command = profile.hermes_command
    if command is None:
        discovered = shutil.which("hermes")
        command = Path(discovered) if discovered else None
    elif not isinstance(command, Path):
        raise TypeError("hermes_command must be a Path or None")
    if command is not None:
        if not command.is_absolute() or command.is_symlink() or not command.is_file():
            raise ValueError("hermes_command must be an existing absolute file")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (profile.expected_version, profile.model)
    ):
        raise ValueError("expected_version and model must be non-blank strings")
    if (
        isinstance(profile.timeout_seconds, bool)
        or not isinstance(profile.timeout_seconds, int)
        or not 1 <= profile.timeout_seconds <= MAX_HERMES_TIMEOUT_SECONDS
        or isinstance(profile.context_tokens, bool)
        or not isinstance(profile.context_tokens, int)
        or not 1 <= profile.context_tokens <= MAX_HERMES_CONTEXT_TOKENS
        or isinstance(profile.max_prompt_bytes, bool)
        or not isinstance(profile.max_prompt_bytes, int)
        or not 1 <= profile.max_prompt_bytes <= MAX_HERMES_PROMPT_BYTES
        or isinstance(profile.max_final_response_bytes, bool)
        or not isinstance(profile.max_final_response_bytes, int)
        or not 1 <= profile.max_final_response_bytes <= MAX_HERMES_RESPONSE_BYTES
        or isinstance(profile.max_worker_stdout_bytes, bool)
        or not isinstance(profile.max_worker_stdout_bytes, int)
        or not 1 <= profile.max_worker_stdout_bytes <= MAX_HERMES_WORKER_STDOUT_BYTES
    ):
        raise ValueError("Hermes runtime limits are outside their bounded ranges")
    try:
        endpoint = urlsplit(profile.base_url)
        endpoint_port = endpoint.port
    except ValueError as exc:
        raise ValueError("base_url port is invalid") from exc
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"127.0.0.1", "::1"}
        or endpoint_port != 11434
        or endpoint.path != "/v1"
        or endpoint.query
        or endpoint.fragment
        or endpoint.username is not None
        or endpoint.password is not None
    ):
        raise ValueError("base_url must be the local Ollama OpenAI endpoint")

    runner_path = profile.hermes_root / "run_agent.py"
    agent_init_path = profile.hermes_root / "agent" / "agent_init.py"
    source_files = {
        "runner": runner_path.is_file() and not runner_path.is_symlink(),
        "agent_init": agent_init_path.is_file() and not agent_init_path.is_symlink(),
    }
    api_checks = {
        "version": False,
        "AIAgent": False,
        "run_conversation": False,
        "final_response": False,
        "enabled_toolsets": False,
        "skip_memory": False,
        "skip_background_review": False,
        "max_iterations": False,
        "fallback_model": False,
    }
    missing_checks: list[str] = []
    if command is None:
        missing_checks.append("command")
    else:
        try:
            version_result = subprocess.run(
                [str(command), "--version"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=profile.timeout_seconds,
                shell=False,
            )
            version_text = f"{version_result.stdout}\n{version_result.stderr}"
            version_match = re.search(r"\bv?(\d+\.\d+\.\d+)\b", version_text)
            api_checks["version"] = (
                version_result.returncode == 0
                and version_match is not None
                and version_match.group(1) == profile.expected_version
            )
        except (OSError, subprocess.TimeoutExpired):
            api_checks["version"] = False
    if not api_checks["version"]:
        missing_checks.append("version")
    parsed_sources: dict[str, ast.AST] = {}
    for name, path in (("runner", runner_path), ("agent_init", agent_init_path)):
        if not source_files[name]:
            missing_checks.append(name)
            continue
        try:
            parsed_sources[name] = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        except (OSError, UnicodeError, SyntaxError, ValueError):
            missing_checks.append(f"{name}_source")

    runner_tree = parsed_sources.get("runner")
    if runner_tree is not None:
        api_checks["AIAgent"] = any(
            isinstance(node, ast.ClassDef) and node.name == "AIAgent"
            for node in ast.walk(runner_tree)
        )
        api_checks["run_conversation"] = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "run_conversation"
            for node in ast.walk(runner_tree)
        )
        api_checks["final_response"] = any(
            isinstance(node, ast.Constant) and node.value == "final_response"
            for node in ast.walk(runner_tree)
        )

    agent_init_tree = parsed_sources.get("agent_init")
    if agent_init_tree is not None:
        parameter_names = {
            argument.arg
            for node in ast.walk(agent_init_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        }
        for name in (
            "enabled_toolsets",
            "skip_memory",
            "skip_background_review",
            "max_iterations",
            "fallback_model",
        ):
            api_checks[name] = name in parameter_names

    for name, present in source_files.items():
        if not present and name not in missing_checks:
            missing_checks.append(name)
    for name, present in api_checks.items():
        if not present and name != "skip_background_review":
            missing_checks.append(name)
    missing_checks = sorted(set(missing_checks))
    return {
        "status": "compatible" if not missing_checks else "incompatible",
        "hermes_root": str(profile.hermes_root),
        "expected_version": profile.expected_version,
        "source_files": {"command": command is not None, **source_files},
        "api_checks": api_checks,
        "missing_checks": missing_checks,
        "model": profile.model,
        "base_url": profile.base_url,
        "model_calls": 0,
    }


class LocalHermesRuntime:
    """Future ``QwenRuntime``-compatible client for one Hermes worker request.

    It uses argv execution and a bounded JSON stdin/stdout protocol. It passes
    only a completed final response to Sodam's existing validators.
    """

    def __init__(self, profile: HermesExecutionProfile) -> None:
        """Retain a prevalidated profile without spawning a worker process."""
        validate_hermes_profile(profile)
        self._profile = profile
        self._command = _resolve_hermes_command(profile)
        self._worker_path = Path(__file__).resolve().parent.parent / "tools" / "hermes_worker.py"
        if not self._worker_path.is_file():
            raise ValueError("Hermes worker is unavailable")

    def complete(self, prompt: str) -> str:
        """Return one completed Hermes final response or a safe runtime error."""
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        if not prompt.strip():
            raise ValueError("prompt must be non-blank")
        if prompt != prompt.strip():
            raise ValueError("prompt must be trimmed")
        if len(prompt.encode("utf-8")) > self._profile.max_prompt_bytes:
            raise ModelResponseError("Hermes prompt exceeds the context limit")
        request_id = uuid.uuid4().hex
        request = {
            "protocol_version": HERMES_PROTOCOL_VERSION,
            "request_id": request_id,
            "prompt": prompt,
        }
        worker_args = [
            str(self._profile.python_executable),
            str(self._worker_path),
            "--hermes-command",
            str(self._command),
            "--model",
            self._profile.model,
            "--max-prompt-bytes",
            str(self._profile.max_prompt_bytes),
            "--max-response-bytes",
            str(self._profile.max_final_response_bytes),
            "--timeout-seconds",
            str(self._profile.timeout_seconds),
        ]
        kwargs: dict[str, object] = {
            "input": json.dumps(request, ensure_ascii=False) + "\n",
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": _utf8_environment(),
            "timeout": self._profile.timeout_seconds,
            "check": False,
            "shell": False,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(worker_args, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise _runtime_error("runtime_timeout") from exc
        except OSError as exc:
            raise _runtime_error("runtime_unavailable") from exc
        stdout = result.stdout if isinstance(result.stdout, str) else ""
        if len(stdout.encode("utf-8")) > self._profile.max_worker_stdout_bytes:
            raise _runtime_error("response_too_large")
        try:
            envelope = json.loads(stdout)
        except (TypeError, ValueError) as exc:
            raise _runtime_error("protocol_invalid") from exc
        if not isinstance(envelope, dict) or envelope.get("protocol_version") != HERMES_PROTOCOL_VERSION:
            raise _runtime_error("protocol_invalid")
        if envelope.get("request_id") != request_id:
            raise _runtime_error("protocol_invalid")
        if envelope.get("status") != "completed" or not isinstance(envelope.get("final_response"), str):
            code = envelope.get("error_code")
            raise _runtime_error(code if isinstance(code, str) else "protocol_invalid")
        final_response = envelope["final_response"]
        if not final_response.strip():
            raise _runtime_error("protocol_invalid")
        if len(final_response.encode("utf-8")) > self._profile.max_final_response_bytes:
            raise _runtime_error("response_too_large")
        if result.returncode != 0:
            raise _runtime_error("runtime_unavailable")
        return final_response


def _resolve_hermes_command(profile: HermesExecutionProfile) -> Path:
    """Resolve the explicitly configured command or PATH-installed Hermes."""
    if profile.hermes_command is not None:
        return profile.hermes_command
    discovered = shutil.which("hermes")
    if discovered is None:
        raise ValueError("Hermes command is unavailable")
    return Path(discovered)


def _utf8_environment() -> dict[str, str]:
    """Return a child environment that preserves non-ASCII prompts and output."""
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _runtime_error(code: str) -> ModelResponseError:
    """Create a non-sensitive model error with one allowlisted diagnostic code."""
    safe_code = code if code in HERMES_DIAGNOSTIC_CODES else "protocol_invalid"
    error = ModelResponseError("Hermes runtime failed")
    error.diagnostic_code = safe_code
    return error
