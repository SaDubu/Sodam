"""URL source validation and temporary audio-acquisition contracts."""

from .contracts import AudioArtifact, Job


def validate_source(source: str) -> None:
    """Validate a supported, user-authorized URL without contacting it.

    Invalid, unsupported, or malformed sources must raise ``InputSourceError``.
    Platform-specific retrieval is deliberately outside this declaration.
    """
    raise NotImplementedError("B04: validate_source has not been implemented")


def acquire_source_audio(job: Job) -> AudioArtifact:
    """Acquire standard audio into `job.work_dir` through an injected adapter.

    A later implementation must remove any downloaded source container after
    successful audio extraction and map adapter failures to the source contract.
    """
    raise NotImplementedError("B04: acquire_source_audio has not been implemented")
