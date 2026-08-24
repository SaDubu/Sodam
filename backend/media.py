"""Local-media validation and audio-normalization contract."""

from .contracts import AudioArtifact, Job


def extract_audio(job: Job) -> AudioArtifact:
    """Convert a job-owned local input to the documented standard audio format.

    The implementation will use an injected FFmpeg runner, write only inside the
    job workspace, and raise a media-specific error for decode failures.
    """
    raise NotImplementedError("B05: extract_audio has not been implemented")
