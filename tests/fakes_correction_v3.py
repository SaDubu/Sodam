"""Skeleton collaborators for the constrained-correction contract tests.

CR-01 only declares the deterministic fake interfaces.  Runtime behavior,
response sequencing, and assertions belong to the later CR-03 test task.
"""

from collections.abc import Sequence


class RecordingQwenRuntime:
    """Record prompts for a future correction test without calling Ollama."""

    def __init__(self, responses: Sequence[str] = ()) -> None:
        """Store deterministic responses and expose prompt recording."""
        if isinstance(responses, (str, bytes)):
            raise TypeError("responses must be a sequence of strings")
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        """Record a prompt and return the next configured response."""
        self.prompts.append(prompt)
        if not self.responses:
            raise RuntimeError("no fake response remains")
        return self.responses.pop(0)


class MalformedThenValidRuntime:
    """Represent a fake that emits malformed JSON before a valid response."""

    def __init__(self, valid_response: str) -> None:
        self._runtime = RecordingQwenRuntime(("not json", valid_response))

    @property
    def prompts(self) -> list[str]:
        return self._runtime.prompts

    def complete(self, prompt: str) -> str:
        """Return malformed JSON once, followed by the valid response."""
        return self._runtime.complete(prompt)


class TimeoutThenValidRuntime:
    """Represent a fake that raises a timeout before a valid response."""

    def __init__(self, valid_response: str) -> None:
        self._runtime = RecordingQwenRuntime((valid_response,))
        self._timed_out = False

    @property
    def prompts(self) -> list[str]:
        return self._runtime.prompts

    def complete(self, prompt: str) -> str:
        """Raise TimeoutError once, followed by the valid response."""
        self._runtime.prompts.append(prompt)
        if not self._timed_out:
            self._timed_out = True
            raise TimeoutError("fake timeout")
        if not self._runtime.responses:
            raise RuntimeError("no fake response remains")
        return self._runtime.responses.pop(0)


class AlwaysInvalidRuntime:
    """Represent a fake whose every response violates the contract."""

    def __init__(self, response: str = "not json") -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        """Return a contract-invalid response for every attempt."""
        self.prompts.append(prompt)
        return self.response
