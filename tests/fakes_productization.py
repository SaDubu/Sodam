"""Deterministic collaborators for introduction and installation tests."""

from collections.abc import Callable
from collections.abc import Mapping, Sequence

from backend.contracts import ProgressEvent, SystemProfile


class RecordingIntroductionRuntime:
    """FIFO Qwen fake with prompt recording and no model or network access."""

    def __init__(self, responses: tuple[str, ...] = ()) -> None:
        if not isinstance(responses, tuple) or any(not isinstance(item, str) for item in responses):
            raise TypeError("responses must be a tuple of strings")
        self._responses = tuple(responses)
        self._prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        self._prompts.append(prompt)
        if not self._responses:
            raise RuntimeError("configured introduction responses are exhausted")
        response, *remaining = self._responses
        self._responses = tuple(remaining)
        return response

    @property
    def prompts(self) -> tuple[str, ...]:
        return tuple(self._prompts)

    @property
    def call_count(self) -> int:
        return len(self._prompts)


class FakeSystemProbe:
    """Read-only fake host probe returning one configured SystemProfile."""

    def __init__(self, profile: SystemProfile) -> None:
        if not isinstance(profile, SystemProfile):
            raise TypeError("profile must be a SystemProfile")
        self._profile = profile
        self._call_count = 0

    def collect(self) -> SystemProfile:
        self._call_count += 1
        return self._profile

    @property
    def call_count(self) -> int:
        return self._call_count


class FakeCancellationToken:
    """Cooperative cancellation token controlled only by the test."""

    def __init__(self, cancelled: bool = False) -> None:
        if not isinstance(cancelled, bool):
            raise TypeError("cancelled must be bool")
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class RecordingInstallerBackend:
    """Record preconfigured progress events without external installation."""

    def __init__(self, progress_events: Mapping[str, Sequence[ProgressEvent]] | None = None) -> None:
        if progress_events is None:
            progress_events = {}
        if not isinstance(progress_events, Mapping):
            raise TypeError("progress_events must be a mapping")
        copied: dict[str, tuple[ProgressEvent, ...]] = {}
        for action_id, events in progress_events.items():
            if not isinstance(action_id, str):
                raise TypeError("action_id must be a string")
            if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
                raise TypeError("progress events must be a sequence")
            if any(not isinstance(event, ProgressEvent) for event in events):
                raise TypeError("progress events must contain ProgressEvent values")
            copied[action_id] = tuple(events)
        self._progress_events = copied
        self._action_ids: list[str] = []

    def execute_action(
        self,
        action_id: str,
        emit: Callable[[ProgressEvent], None],
        cancellation: FakeCancellationToken,
    ) -> None:
        if not isinstance(action_id, str):
            raise TypeError("action_id must be a string")
        if not callable(emit):
            raise TypeError("emit must be callable")
        if not isinstance(cancellation, FakeCancellationToken):
            raise TypeError("cancellation must be a FakeCancellationToken")
        if action_id not in self._progress_events:
            raise KeyError(action_id)
        self._action_ids.append(action_id)
        if cancellation.is_cancelled():
            return
        for event in self._progress_events[action_id]:
            emit(event)

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(self._action_ids)
