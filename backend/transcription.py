"""Speech-to-text adapter and segment-standardization contract."""

from .contracts import AudioArtifact, RawSegment


def transcribe_audio(audio: AudioArtifact, config: object) -> list[RawSegment]:
    """Return ordered, valid timed segments from an injected local STT engine.

    A future implementation must reject unavailable models and invalid engine
    output; it must not load or call a model in this skeleton.
    """
    raise NotImplementedError("B06: transcribe_audio has not been implemented")
