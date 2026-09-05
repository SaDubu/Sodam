"""Validated local runtime-profile persistence and model selection."""

import json
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
from urllib.parse import urlsplit

from .contracts import RuntimeProfile
from .runtime_paths import STT_MODEL_PATH


_DEFAULT_MODEL = "qwen3.6:35b-a3b-agent-64k"
_DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"
_PROFILE_KEYS = {
    "profile_name",
    "qwen_model",
    "stt_model_path",
    "ffmpeg_path",
    "ollama_endpoint",
    "qwen_context_tokens",
}


@dataclass(frozen=True)
class RuntimeReadiness:
    """Safe, path-free readiness facts consumed by the desktop doctor."""

    python_ready: bool
    ffmpeg_ready: bool
    stt_model_ready: bool
    ollama_ready: bool
    qwen_model_ready: bool
    required_actions: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return all(
            (
                self.python_ready,
                self.ffmpeg_ready,
                self.stt_model_ready,
                self.ollama_ready,
                self.qwen_model_ready,
            )
        )


def evaluate_runtime_readiness(
    profile: RuntimeProfile,
    *,
    python_ready: bool,
    ollama_ready: bool,
    qwen_model_ready: bool,
) -> RuntimeReadiness:
    """Evaluate local readiness without starting processes or contacting models."""
    _validate_profile(profile)
    if not isinstance(python_ready, bool) or not isinstance(ollama_ready, bool):
        raise TypeError("readiness flags must be bool")
    if not isinstance(qwen_model_ready, bool):
        raise TypeError("readiness flags must be bool")
    ffmpeg_ready = profile.ffmpeg_path.is_file()
    stt_model_ready = profile.stt_model_path.is_dir()
    actions: list[str] = []
    if not python_ready:
        actions.append("Python 실행 환경 설정")
    if not ffmpeg_ready:
        actions.append("FFmpeg 실행 파일 경로 설정")
    if not stt_model_ready:
        actions.append("faster-whisper 모델 경로 설정")
    if not ollama_ready:
        actions.append("Ollama를 127.0.0.1:11434에서 실행")
    if not qwen_model_ready:
        actions.append(f"{profile.qwen_model} 모델 준비")
    return RuntimeReadiness(
        python_ready,
        ffmpeg_ready,
        stt_model_ready,
        ollama_ready,
        qwen_model_ready,
        tuple(actions),
    )


def _validate_endpoint(endpoint: object) -> str:
    if not isinstance(endpoint, str):
        raise TypeError("ollama_endpoint must be a string")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("ollama_endpoint port is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port != 11434
        or parsed.path != "/api/chat"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("ollama_endpoint must be loopback /api/chat")
    return endpoint


def _validate_profile(profile: RuntimeProfile) -> RuntimeProfile:
    if not isinstance(profile, RuntimeProfile):
        raise TypeError("profile must be a RuntimeProfile")
    if not isinstance(profile.profile_name, str) or not profile.profile_name.strip():
        raise ValueError("profile_name must be non-blank")
    if not isinstance(profile.qwen_model, str) or not profile.qwen_model.strip():
        raise ValueError("qwen_model must be non-blank")
    if not isinstance(profile.stt_model_path, Path) or not isinstance(profile.ffmpeg_path, Path):
        raise TypeError("runtime paths must be Path values")
    _validate_endpoint(profile.ollama_endpoint)
    if (
        isinstance(profile.qwen_context_tokens, bool)
        or not isinstance(profile.qwen_context_tokens, int)
        or not 1024 <= profile.qwen_context_tokens <= 262144
    ):
        raise ValueError("qwen_context_tokens must be an int from 1024 to 262144")
    return profile


def default_runtime_profile(system_name: str) -> RuntimeProfile:
    """Return an OS-appropriate declaration without probing or creating files."""
    if not isinstance(system_name, str):
        raise TypeError("system_name must be a string")
    normalized = system_name.strip().lower()
    if normalized not in {"windows", "linux", "darwin"}:
        raise ValueError("unsupported system_name")
    if normalized == "windows":
        stt = STT_MODEL_PATH
        ffmpeg = Path("ffmpeg.exe")
    else:
        stt = Path.home() / ".local" / "share" / "sodam" / "models" / "faster-whisper"
        ffmpeg = Path("ffmpeg")
    return RuntimeProfile("quality", _DEFAULT_MODEL, stt, ffmpeg, _DEFAULT_ENDPOINT, 32768)


def load_runtime_profile(path: str | Path) -> RuntimeProfile:
    """Read and validate one profile without accepting arbitrary remote endpoints."""
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be str or Path")
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("profile path must be a regular file")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("runtime profile is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _PROFILE_KEYS:
        raise ValueError("runtime profile schema is invalid")
    if not isinstance(payload["stt_model_path"], str) or not isinstance(payload["ffmpeg_path"], str):
        raise TypeError("runtime paths in JSON must be strings")
    profile = RuntimeProfile(
        payload["profile_name"],
        payload["qwen_model"],
        Path(payload["stt_model_path"]),
        Path(payload["ffmpeg_path"]),
        payload["ollama_endpoint"],
        payload["qwen_context_tokens"],
    )
    return _validate_profile(profile)


def save_runtime_profile(profile: RuntimeProfile, path: str | Path) -> Path:
    """Persist one validated profile atomically outside model and job directories."""
    _validate_profile(profile)
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be str or Path")
    candidate = Path(path)
    if candidate.exists() and candidate.is_symlink():
        raise ValueError("profile path must not be a symlink")
    parent = candidate.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile_name": profile.profile_name,
        "qwen_model": profile.qwen_model,
        "stt_model_path": str(profile.stt_model_path),
        "ffmpeg_path": str(profile.ffmpeg_path),
        "ollama_endpoint": profile.ollama_endpoint,
        "qwen_context_tokens": profile.qwen_context_tokens,
    }
    fd, temporary_name = tempfile.mkstemp(prefix=".runtime-profile-", suffix=".partial", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, candidate)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return candidate
