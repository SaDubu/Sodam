"""Read-only diagnostics for the local Sodam runtime."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import os


_CHECKS = ("python", "ffmpeg", "ollama", "qwen_model", "stt_runtime", "stt_snapshot", "data_root")


@dataclass(frozen=True)
class DoctorConfig:
    runtime_python: Path = Path(r"D:\AI-Legion\Sodam-runtime\Scripts\python.exe")
    stt_snapshot: Path = Path(r"D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9")
    data_root: Path = Path(r"D:\AI-Legion\Sodam-data")
    qwen_model: str = "qwen3.6:35b-a3b-agent-64k"
    ffmpeg_path: Path | None = None


class SystemProbe:
    """Read-only local executable and path probes."""

    def command(self, *arguments: str) -> tuple[bool, str]:
        try:
            completed = subprocess.run(arguments, text=True, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, type(exc).__name__
        detail = (completed.stdout or completed.stderr).strip()
        return completed.returncode == 0, detail or f"exit {completed.returncode}"

    def executable(self, name: str) -> bool:
        return shutil.which(name) is not None

    def file_executable(self, path: Path) -> bool:
        return path.is_file()

    def path_state(self, path: Path, writable: bool = False) -> bool:
        if not path.is_dir():
            return False
        return not writable or path.exists() and path.is_dir()


def collect_diagnostics(config: DoctorConfig, probe: SystemProbe) -> dict[str, object]:
    """Return a deterministic, side-effect-free readiness report."""
    if not isinstance(config, DoctorConfig) or not isinstance(probe, SystemProbe):
        raise TypeError("config and probe must have their declared types")
    checks: dict[str, dict[str, object]] = {}
    checks["python"] = {"ok": config.runtime_python.is_file(), "detail": str(config.runtime_python)}
    ffmpeg_path = config.ffmpeg_path
    if ffmpeg_path is not None and not isinstance(ffmpeg_path, Path):
        raise TypeError("ffmpeg_path must be a Path or None")
    explicit_ffmpeg_ok = bool(
        ffmpeg_path is not None
        and ffmpeg_path.is_absolute()
        and probe.file_executable(ffmpeg_path)
    )
    path_ffmpeg_ok = probe.executable("ffmpeg")
    checks["ffmpeg"] = {
        "ok": explicit_ffmpeg_ok or path_ffmpeg_ok,
        "detail": str(ffmpeg_path) if explicit_ffmpeg_ok else "ffmpeg on PATH",
    }
    ollama_ok, ollama_detail = probe.command("ollama", "--version") if probe.executable("ollama") else (False, "ollama missing")
    checks["ollama"] = {"ok": ollama_ok, "detail": ollama_detail}
    listed, models = probe.command("ollama", "list") if ollama_ok else (False, "ollama unavailable")
    checks["qwen_model"] = {"ok": listed and config.qwen_model in models, "detail": config.qwen_model}
    stt_ok, stt_detail = probe.command(str(config.runtime_python), "-B", "-c", "import faster_whisper") if config.runtime_python.is_file() else (False, "runtime Python missing")
    checks["stt_runtime"] = {"ok": stt_ok, "detail": stt_detail}
    required = ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json")
    checks["stt_snapshot"] = {"ok": config.stt_snapshot.is_dir() and all((config.stt_snapshot / item).is_file() for item in required), "detail": str(config.stt_snapshot)}
    checks["data_root"] = {"ok": probe.path_state(config.data_root, writable=True), "detail": str(config.data_root)}
    actions = [f"resolve {name}" for name in _CHECKS if not checks[name]["ok"]]
    return {"is_ready": not actions, "checks": checks, "required_actions": actions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit one-line JSON")
    args = parser.parse_args(argv)
    configured_ffmpeg = os.environ.get("SODAM_FFMPEG")
    ffmpeg_path = Path(configured_ffmpeg) if configured_ffmpeg else None
    report = collect_diagnostics(DoctorConfig(ffmpeg_path=ffmpeg_path), SystemProbe())
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["is_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
