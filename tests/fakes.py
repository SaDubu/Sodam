"""Fake-dependency contracts shared by future unit and integration tests.

No fake behavior is implemented yet: each fake must become deterministic only
when the associated implementation task is approved.
"""


class FakeSttEngine:
    """Planned fake for STT segment responses and engine failures."""

    def transcribe(self, audio_path: str) -> object:
        """Return a configured fake response or documented failure."""
        raise NotImplementedError("T01: FakeSttEngine has not been implemented")


class FakeQwenRuntime:
    """Planned fake for JSON correction and summary model responses."""

    def complete(self, prompt: str) -> str:
        """Return configured JSON text or a deterministic model error."""
        raise NotImplementedError("T01: FakeQwenRuntime has not been implemented")


class FakeFileSystem:
    """Planned fake for job-owned paths and deletion-boundary verification."""

    def remove(self, path: str) -> None:
        """Record a removal request without touching the host filesystem."""
        raise NotImplementedError("T01: FakeFileSystem has not been implemented")
