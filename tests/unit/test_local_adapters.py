"""Unit tests for local adapter wiring without real subprocesses or models."""

import json
from pathlib import Path
import sys
import types

import pytest

from backend.contracts import InputSourceError
from backend.local_adapters import (
    DEFAULT_QWEN_MODEL,
    MAX_QWEN_TIMEOUT_SECONDS,
    LocalFasterWhisperEngine,
    LocalFfmpegRunner,
    LocalOllamaRuntime,
    LocalYtDlpSourceAdapter,
    RejectingUrlSourceAdapter,
)
import backend.local_adapters as adapters


def test_ffmpeg_runner_uses_exact_vector_without_overwrite_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append({"command": command, **kwargs})

    monkeypatch.setattr(adapters.subprocess, "run", fake_run)

    LocalFfmpegRunner("ffmpeg-test").run(("-i", "input.mp3", "output.wav"))

    assert calls == [{
        "command": ["ffmpeg-test", "-i", "input.mp3", "output.wav"],
        "check": True,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }]
    with pytest.raises(TypeError):
        LocalFfmpegRunner().run("-i input.mp3")  # type: ignore[arg-type]


def test_faster_whisper_engine_is_local_and_returns_detached_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[object] = []

    class Segment:
        start = 0.0
        end = 1.0
        text = "fixture"

    class StubWhisperModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

        def transcribe(self, audio_path: str) -> tuple[list[Segment], object]:
            calls.append(audio_path)
            return [Segment()], object()

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = StubWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    engine = LocalFasterWhisperEngine(model_dir)
    assert engine.transcribe("audio.wav") == [{"start": 0.0, "end": 1.0, "text": "fixture"}]
    assert calls[0] == ((str(model_dir.resolve()),), {"device": "cpu", "compute_type": "int8", "local_files_only": True})
    assert calls[1] == "audio.wav"


def test_ollama_runtime_posts_one_utf8_json_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"message":{"content":"reply"}}'

    def fake_urlopen(value: object, timeout: int) -> Response:
        seen["url"] = value.full_url  # type: ignore[attr-defined]
        seen["body"] = json.loads(value.data.decode("utf-8"))  # type: ignore[attr-defined]
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(adapters.request, "urlopen", fake_urlopen)
    runtime = LocalOllamaRuntime()

    assert runtime.complete("hello") == "reply"
    assert seen == {
        "url": "http://127.0.0.1:11434/api/chat",
        "body": {
            "model": DEFAULT_QWEN_MODEL,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": 32768},
            "messages": [{"role": "user", "content": "hello"}],
        },
        "timeout": MAX_QWEN_TIMEOUT_SECONDS,
    }
    with pytest.raises(ValueError):
        LocalOllamaRuntime(endpoint="https://example.com/api/chat")
    runtime = LocalOllamaRuntime("qwen3.6:35b-a3b-agent-64k", context_tokens=4096)
    assert runtime.model == "qwen3.6:35b-a3b-agent-64k"
    assert runtime.context_tokens == 4096
    with pytest.raises(ValueError):
        LocalOllamaRuntime(context_tokens=512)


@pytest.mark.parametrize("timeout_seconds", [1, MAX_QWEN_TIMEOUT_SECONDS])
def test_ollama_runtime_accepts_bounded_timeout(timeout_seconds: int) -> None:
    runtime = LocalOllamaRuntime(timeout_seconds=timeout_seconds)
    assert runtime.timeout_seconds == timeout_seconds


@pytest.mark.parametrize("timeout_seconds", [0, -1, MAX_QWEN_TIMEOUT_SECONDS + 1, True, "600"])
def test_ollama_runtime_rejects_invalid_timeout(timeout_seconds: object) -> None:
    with pytest.raises(ValueError):
        LocalOllamaRuntime(timeout_seconds=timeout_seconds)  # type: ignore[arg-type]


def test_rejecting_url_adapter_never_writes(tmp_path: Path) -> None:
    destination = tmp_path / "source.webm"
    with pytest.raises(InputSourceError):
        RejectingUrlSourceAdapter().acquire("https://example.com/a", destination)
    assert not destination.exists()


def test_ytdlp_adapter_uses_one_safe_command_and_cleans_direct_byproduct(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "source-audio.wav"
    calls: list[tuple[str, ...]] = []

    def fake_command(command: object) -> None:
        calls.append(tuple(command))  # type: ignore[arg-type]
        destination.write_bytes(b"wav")
        (tmp_path / "source-audio.webm").write_bytes(b"download")

    adapter = LocalYtDlpSourceAdapter("python-test", command_runner=fake_command)
    adapter.acquire("https://youtu.be/abc123", destination)

    assert calls == [
        (
            "python-test", "-m", "yt_dlp", "--ignore-config", "--no-playlist",
            "--no-progress", "--no-warnings", "--extract-audio", "--audio-format",
            "wav", "--output", str(tmp_path / "source-audio.%(ext)s"),
            "https://youtu.be/abc123",
        )
    ]
    assert destination.read_bytes() == b"wav"
    assert not (tmp_path / "source-audio.webm").exists()
    assert not any(
        flag in calls[0]
        for flag in ("--cookies", "--cookies-from-browser", "--username", "--password", "--proxy")
    )


def test_ytdlp_adapter_rejects_unsafe_destination_and_maps_runner_failure(
    tmp_path: Path,
) -> None:
    adapter = LocalYtDlpSourceAdapter("python-test", command_runner=lambda _: None)
    with pytest.raises(InputSourceError):
        adapter.acquire("https://youtu.be/abc123", tmp_path / "other.wav")

    def failing_command(_: object) -> None:
        raise RuntimeError("downloader failed")

    with pytest.raises(InputSourceError):
        LocalYtDlpSourceAdapter("python-test", command_runner=failing_command).acquire(
            "https://youtu.be/abc123", tmp_path / "source-audio.wav"
        )
