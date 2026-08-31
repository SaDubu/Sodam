"""Unit tests for B06 injected STT segment standardization."""

from pathlib import Path
import uuid

import pytest

from backend.contracts import AudioArtifact, CleanupPolicy, Job, JobOptions, TranscriptionError
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts
from backend.transcription import transcribe_audio


class RecordingEngine:
    """Return a configured in-memory STT response and record its path argument."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.paths: list[str] = []

    def transcribe(self, audio_path: str) -> object:
        self.paths.append(audio_path)
        return self.response


@pytest.fixture
def audio() -> AudioArtifact:
    """Yield a regular audio fixture contained in a unique approved job directory."""
    job_id = "t02-stt-" + uuid.uuid4().hex
    job = Job(job_id, "fixture://stt", "queued", JOB_WORK_ROOT / job_id, JobOptions())
    job.work_dir.mkdir(parents=True, exist_ok=True)
    path = job.work_dir / "input.wav"
    path.write_bytes(b"audio fixture")
    try:
        yield AudioArtifact(job_id, path)
    finally:
        cleanup_artifacts(job, CleanupPolicy())


def test_blank_items_are_filtered_and_remaining_segments_are_standardized(
    audio: AudioArtifact,
) -> None:
    response = [
        {"start": 0, "end": 0.5, "text": "   ", "confidence": 0.1},
        {"start": 0.5, "end": 1.5, "text": "first", "confidence": 0.8},
        {"start": 1.5, "end": 2.0, "text": "second"},
    ]
    engine = RecordingEngine(response)

    segments = transcribe_audio(audio, engine)  # type: ignore[arg-type]

    assert engine.paths == [str(audio.path.resolve())]
    assert segments[0].segment_id == "segment-0001"
    assert segments[0].start_seconds == 0.5
    assert segments[0].end_seconds == 1.5
    assert segments[0].raw_text == "first"
    assert segments[0].confidence == 0.8
    assert segments[1].segment_id == "segment-0002"
    assert segments[1].raw_text == "second"
    assert segments[1].confidence is None


@pytest.mark.parametrize(
    "response",
    [
        [
            {"start": 1.0, "end": 2.0, "text": "first"},
            {"start": 0.5, "end": 1.5, "text": "backward"},
        ],
        [{"start": 0, "end": 1, "text": "bad", "confidence": 1.1}],
        iter([{"start": 0, "end": 1, "text": "generator"}]),
    ],
)
def test_invalid_time_confidence_or_container_is_rejected(
    audio: AudioArtifact,
    response: object,
) -> None:
    with pytest.raises(TranscriptionError):
        transcribe_audio(audio, RecordingEngine(response))  # type: ignore[arg-type]


def test_missing_audio_file_and_invalid_engine_are_rejected(audio: AudioArtifact) -> None:
    missing = AudioArtifact(audio.job_id, audio.path.with_name("missing.wav"))
    engine = RecordingEngine([])

    with pytest.raises(TranscriptionError):
        transcribe_audio(missing, engine)  # type: ignore[arg-type]
    assert engine.paths == []
    with pytest.raises(TypeError):
        transcribe_audio(audio, object())  # type: ignore[arg-type]


def test_audio_and_engine_response_are_not_mutated(audio: AudioArtifact) -> None:
    response = [{"start": 0, "end": 1, "text": "unchanged", "confidence": None}]
    engine = RecordingEngine(response)
    original_path = audio.path
    original_response = [dict(item) for item in response]

    transcribe_audio(audio, engine)  # type: ignore[arg-type]

    assert audio.path == original_path
    assert response == original_response
