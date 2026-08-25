"""Deterministic fake objects for unit/integration tests — no real I/O or models.

Fakes expose public recording lists so callers can inspect what was passed to them.
"""
from __future__ import annotations


class FakeSttEngine:
    """Fake Speech-to-Text engine that records every transcribe call."""

    def __init__(
        self,
        responses: dict[str, object] | None = None,
        default_response: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.transcribed_paths: list[str] = []
        if responses is not None:
            responses = {k: v for k, v in responses.items()}  # shallow copy
        elif responses is None:
            responses = {}
        self._responses: dict[str, object] = responses
        self._default_response = default_response
        self._error = error

    def transcribe(self, audio_path: str) -> object:
        """Return a fake transcription for *audio_path* and record the call.

        Always records first. Raises ``self._error`` (if given) **after** recording.
        """
        self.transcribed_paths.append(audio_path)
        if self._error is not None:
            raise self._error from None
        if audio_path in self._responses:
            return self._responses[audio_path]
        return self._default_response


class FakeQwenRuntime:
    """Fake Qwen LLM runtime that records every complete call."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        default_response: str = "",
        error: Exception | None = None,
    ) -> None:
        self.prompts: list[str] = []
        if responses is not None:
            responses = {k: v for k, v in responses.items()}  # shallow copy
        elif responses is None:
            responses = {}
        self._responses: dict[str, str] = responses
        self._default_response = default_response
        self._error = error

    def complete(self, prompt: str) -> str:
        """Return a fake completion for *prompt* and record the call.

        Always records first. Raises ``self._error`` (if given) **after** recording.
        """
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error from None
        if prompt in self._responses:
            return self._responses[prompt]
        return self._default_response


class FakeFileSystem:
    """Fake POSIX-like file system that records remove operations."""

    def __init__(
        self,
        existing_paths: set[str] | None = None,
        error_paths: set[str] | None = None,
    ) -> None:
        if existing_paths is not None:
            existing_paths = set(existing_paths)  # copy
        elif existing_paths is None:
            existing_paths = set()
        self.existing_paths: set[str] = existing_paths

        if error_paths is not None:
            error_paths = set(error_paths)  # copy
        elif error_paths is None:
            error_paths = set()
        self._error_paths: set[str] = error_paths
        self.removed_paths: list[str] = []

    def remove(self, path: str) -> None:
        """Remove *path* if it exists.

        Raises ``OSError`` when *path* is in the configured error set.
        Raises ``FileNotFoundError(path)`` when *path* does not exist.
        On success updates ``self.existing_paths`` and ``self.removed_paths``.
        """
        if path in self._error_paths:
            raise OSError(f"Simulated OS error for {path}") from None
        if path not in self.existing_paths:
            raise FileNotFoundError(path) from None
        self.existing_paths.remove(path)   # type: ignore[arg-type]
        self.removed_paths.append(path)
