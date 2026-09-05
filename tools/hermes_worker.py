"""One-request worker for the installed Hermes Agent command."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

# The worker is launched by absolute script path, so Python's default import
# root is ``tools`` rather than the repository root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.hermes_runtime import HERMES_PROTOCOL_VERSION, HermesExecutionProfile


ERROR_CODES = frozenset(
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


def _utf8_environment() -> dict[str, str]:
    """Return a child environment that preserves non-ASCII prompts."""
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _configure_utf8_stdio() -> None:
    """Make worker JSON stdin/stdout independent of the Windows console locale."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


class HermesWorkerError(Exception):
    """Internal error carrying only an allowlisted worker diagnostic."""

    def __init__(self, code: str) -> None:
        self.code = code if code in ERROR_CODES else "runtime_unavailable"
        super().__init__(self.code)


def run_hermes_request(
    prompt: str,
    profile: HermesExecutionProfile,
    *,
    agent_factory: Callable[..., object] | None = None,
) -> str:
    """Run one fresh Hermes one-shot and return only its final stdout text."""
    if not isinstance(prompt, str) or not prompt.strip() or prompt != prompt.strip():
        raise HermesWorkerError("protocol_invalid")
    if len(prompt.encode("utf-8")) > profile.max_prompt_bytes:
        raise HermesWorkerError("context_limit")
    if agent_factory is not None:
        try:
            agent = agent_factory(
                enabled_toolsets=[],
                skip_memory=True,
                max_iterations=1,
                fallback_model=None,
            )
            result = agent.run_conversation(prompt)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise HermesWorkerError("runtime_unavailable") from exc
        if not isinstance(result, dict) or not isinstance(result.get("final_response"), str):
            raise HermesWorkerError("protocol_invalid")
        final_response = result["final_response"]
    else:
        command = profile.hermes_command
        if command is None:
            raise HermesWorkerError("runtime_incompatible")
        argv = [
            str(command),
            "--oneshot",
            prompt,
            "--model",
            profile.model,
            "--provider",
            "custom",
            "--ignore-rules",
            "-t",
            "",
        ]
        kwargs: dict[str, object] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": _utf8_environment(),
            "timeout": profile.timeout_seconds,
            "check": False,
            "shell": False,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            completed = subprocess.run(argv, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise HermesWorkerError("runtime_timeout") from exc
        except OSError as exc:
            raise HermesWorkerError("runtime_unavailable") from exc
        if completed.returncode != 0:
            raise HermesWorkerError("hermes_process_failed")
        final_response = completed.stdout if isinstance(completed.stdout, str) else ""
    if not final_response.strip():
        raise HermesWorkerError("response_empty")
    if len(final_response.encode("utf-8")) > profile.max_final_response_bytes:
        raise HermesWorkerError("response_too_large")
    return final_response


def _envelope(request_id: object, status: str, **fields: object) -> dict[str, object]:
    """Build the only stdout shape exposed by this worker."""
    result: dict[str, object] = {
        "protocol_version": HERMES_PROTOCOL_VERSION,
        "request_id": request_id,
        "status": status,
    }
    result.update(fields)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--hermes-command", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-prompt-bytes", type=int, required=True)
    parser.add_argument("--max-response-bytes", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Read one request, execute one Hermes call, and emit one safe envelope."""
    try:
        _configure_utf8_stdio()
        args = _parser().parse_args(argv)
        line = sys.stdin.readline()
        if not line or sys.stdin.readline(1):
            raise HermesWorkerError("protocol_invalid")
        request = json.loads(line)
        if not isinstance(request, dict) or set(request) != {"protocol_version", "request_id", "prompt"}:
            raise HermesWorkerError("protocol_invalid")
        request_id = request["request_id"]
        if request["protocol_version"] != HERMES_PROTOCOL_VERSION:
            raise HermesWorkerError("protocol_invalid")
        if not isinstance(request_id, str) or not request_id.strip():
            raise HermesWorkerError("protocol_invalid")
        prompt = request["prompt"]
        if not isinstance(prompt, str) or not prompt.strip() or prompt != prompt.strip():
            raise HermesWorkerError("protocol_invalid")
        command = Path(args.hermes_command)
        profile = HermesExecutionProfile(
            python_executable=Path(sys.executable),
            hermes_root=command.parent,
            expected_version="unknown",
            model=args.model,
            base_url="http://127.0.0.1:11434/v1",
            timeout_seconds=args.timeout_seconds,
            max_prompt_bytes=args.max_prompt_bytes,
            max_final_response_bytes=args.max_response_bytes,
            hermes_command=command,
        )
        response = run_hermes_request(prompt, profile)
        print(json.dumps(_envelope(request_id, "completed", final_response=response), ensure_ascii=False))
        return 0
    except HermesWorkerError as exc:
        request_id = locals().get("request_id")
        print(json.dumps(_envelope(request_id, "failed", error_code=exc.code), ensure_ascii=False))
        return 1
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        request_id = locals().get("request_id")
        print(json.dumps(_envelope(request_id, "failed", error_code="protocol_invalid"), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
