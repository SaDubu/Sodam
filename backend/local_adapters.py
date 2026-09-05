"""Concrete collaborators for the explicitly invoked local Sodam pipeline."""

from collections.abc import Callable, Sequence
import json
from pathlib import Path
import subprocess
import sys
from urllib import request
from urllib.parse import urlsplit

from .contracts import InputSourceError
from .sources import validate_source


DEFAULT_YTDLP_PYTHON = sys.executable
DEFAULT_QWEN_MODEL = "qwen3.6:35b-a3b-agent-64k"
MAX_QWEN_TIMEOUT_SECONDS = 600


def _run_ytdlp(command: Sequence[str]) -> None:
    """Run one prevalidated yt-dlp command without a shell."""
    subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class LocalFfmpegRunner:
    """Run one prevalidated FFmpeg vector without a shell or overwrite flag."""

    def __init__(self, executable: str = "ffmpeg") -> None:
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("executable must be a non-blank str")
        self.executable = executable

    def run(self, arguments: Sequence[str]) -> None:
        """Execute exactly ``[executable, *arguments]`` and propagate failures."""
        if isinstance(arguments, (str, bytes)) or not isinstance(arguments, Sequence):
            raise TypeError("arguments must be a sequence of str values")
        if any(not isinstance(argument, str) for argument in arguments):
            raise TypeError("arguments must contain only str values")
        subprocess.run(
            [self.executable, *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


class LocalFasterWhisperEngine:
    """Use a pinned, already-downloaded faster-whisper model directory."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        if not isinstance(model_path, (str, Path)):
            raise TypeError("model_path must be str or Path")
        if not isinstance(device, str) or not device.strip():
            raise ValueError("device must be a non-blank str")
        if not isinstance(compute_type, str) or not compute_type.strip():
            raise ValueError("compute_type must be a non-blank str")

        model_dir = Path(model_path)
        if model_dir.is_symlink() or not model_dir.is_dir():
            raise ValueError("model_path must be an existing non-symlink directory")

        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            str(model_dir.resolve()),
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )

    def transcribe(self, audio_path: str) -> list[dict[str, object]]:
        """Consume one local STT response and detach the required segment fields."""
        if not isinstance(audio_path, str):
            raise TypeError("audio_path must be a str")
        segments, _info = self._model.transcribe(audio_path)
        return [
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in segments
        ]


class LocalOllamaRuntime:
    """Call an explicitly local Ollama chat endpoint once per supplied prompt."""

    _LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})

    def __init__(
        self,
        model: str = DEFAULT_QWEN_MODEL,
        endpoint: str = "http://127.0.0.1:11434/api/chat",
        timeout_seconds: int = MAX_QWEN_TIMEOUT_SECONDS,
        context_tokens: int = 32768,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-blank str")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= MAX_QWEN_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"timeout_seconds must be an int from 1 to {MAX_QWEN_TIMEOUT_SECONDS}"
            )
        if (
            isinstance(context_tokens, bool)
            or not isinstance(context_tokens, int)
            or not 1024 <= context_tokens <= 262144
        ):
            raise ValueError("context_tokens must be an int from 1024 to 262144")
        if not isinstance(endpoint, str):
            raise ValueError("endpoint must be a str")
        try:
            parts = urlsplit(endpoint)
            port = parts.port
        except ValueError as exc:
            raise ValueError("endpoint port is invalid") from exc
        if (
            parts.scheme != "http"
            or parts.hostname not in self._LOOPBACK_HOSTS
            or port != 11434
            or parts.path != "/api/chat"
            or parts.query
            or parts.fragment
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError("endpoint must be the local Ollama /api/chat endpoint")
        self.model = model
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.context_tokens = context_tokens

    def complete(self, prompt: str) -> str:
        """POST one JSON-only request and return its local model content string."""
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        payload = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0, "num_ctx": self.context_tokens},
                "messages": [{"role": "user", "content": prompt}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request_value = request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with request.urlopen(request_value, timeout=self.timeout_seconds) as response:
            try:
                body = json.loads(response.read().decode("utf-8"))
                content = body["message"]["content"]
            except (KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
                raise RuntimeError("Ollama returned a malformed chat response") from exc
        if not isinstance(content, str):
            raise RuntimeError("Ollama response message.content must be a str")
        return content


class LocalYtDlpSourceAdapter:
    """Acquire one explicitly authorized YouTube source as ``source-audio.wav``.

    The caller must already have made the opt-in decision.  This adapter still
    repeats URL and destination checks so a downloader process cannot be aimed
    outside a single pre-existing, non-symlink work directory.
    """

    _DESTINATION_NAME = "source-audio.wav"

    def __init__(
        self,
        python_executable: str = DEFAULT_YTDLP_PYTHON,
        *,
        command_runner: Callable[[Sequence[str]], None] = _run_ytdlp,
    ) -> None:
        if not isinstance(python_executable, str) or not python_executable.strip():
            raise ValueError("python_executable must be a non-blank str")
        if not callable(command_runner):
            raise TypeError("command_runner must be callable")
        self.python_executable = python_executable
        self._command_runner = command_runner

    def acquire(self, source_url: str, destination: Path) -> None:
        """Download one source to the exact destination or raise ``InputSourceError``."""
        validate_source(source_url)
        if not isinstance(destination, Path):
            raise TypeError("destination must be a Path")

        try:
            parent = destination.parent
            if (
                destination.name != self._DESTINATION_NAME
                or parent.is_symlink()
                or not parent.is_dir()
            ):
                raise InputSourceError("destination must be in a regular work directory")
            if destination.is_symlink() or destination.exists():
                raise InputSourceError("destination must not already exist or be a symlink")
            resolved_parent = parent.resolve(strict=True)
            if destination.parent.resolve(strict=True) != resolved_parent:
                raise InputSourceError("destination parent could not be resolved safely")
        except (OSError, ValueError) as exc:
            raise InputSourceError("destination is not safely accessible") from exc

        output_template = str(resolved_parent / "source-audio.%(ext)s")
        command = (
            self.python_executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--no-progress",
            "--no-warnings",
            "--extract-audio",
            "--audio-format",
            "wav",
            "--output",
            output_template,
            source_url,
        )
        try:
            self._command_runner(command)
            if destination.is_symlink() or not destination.is_file():
                raise InputSourceError("yt-dlp did not create a regular WAV destination")
            for candidate in resolved_parent.iterdir():
                if (
                    candidate != destination
                    and candidate.name.startswith("source-audio.")
                    and candidate.is_file()
                    and not candidate.is_symlink()
                ):
                    candidate.unlink()
        except (KeyboardInterrupt, SystemExit):
            raise
        except InputSourceError:
            raise
        except Exception as exc:
            raise InputSourceError("yt-dlp acquisition failed") from exc


class RejectingUrlSourceAdapter:
    """Reject URL acquisition in a CLI that deliberately accepts local files only."""

    def acquire(self, source_url: str, destination: Path) -> None:
        raise InputSourceError("the local CLI does not acquire URL sources")
