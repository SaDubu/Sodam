"""Domain contracts for Sodam — immutable data schemas and exception hierarchy.

This module defines only types, exception classes, and frozen dataclass
contracts. It performs NO input validation, I/O, or external calls at
import time.
"""
import pathlib
from dataclasses import dataclass
from typing import Literal


# ---- type alias ----

JobStatus = Literal[
    "queued",
    "acquiring",
    "extracting",
    "transcribing",
    "normalizing",
    "correcting",
    "reviewing",
    "summarizing",
    "completed",
    "cancelling",
    "cancelled",
    "failed",
    "cleaning",
    "archived",
]


# ---- exception hierarchy ----

class SodamError(Exception):
    """Base exception for all domain errors."""


class InputSourceError(SodamError):
    """Raised when the input source is invalid or unsupported."""


class UnsafePathError(SodamError):
    """Raised when a path attempts to leave the job's dedicated directory."""


class ModelResponseError(SodamError):
    """Raised when a model response violates the expected schema."""


class JobStateError(SodamError):
    """Raised when a requested Job status transition is not permitted."""


# ---- storage and processing exceptions ----

class StorageError(SodamError):
    """Raised when a job artifact cannot be encoded, written, or read."""


class MediaExtractionError(SodamError):
    """Raised when media decoding or normalized-audio output fails."""


class TranscriptionError(SodamError):
    """Raised when STT input, engine execution, or segment output is invalid."""


class ProtectionError(SodamError):
    """Raised when protection/restore of tokens fails."""


class NormalizationError(SodamError):
    """Raised when restricted rule normalization would violate an invariant."""


class TranscriptAssemblyError(SodamError):
    """Raised when transcript segments cannot form a valid chronological transcript."""


class EmptyTranscriptError(SodamError):
    """Raised when a summary is requested for an empty transcript."""


# ---- immutable data classes ----

@dataclass(frozen=True)
class JobOptions:
    """Configuration flags for a transcription job.

    All fields default to None so callers can omit anything they do not
    wish to configure.
    """

    retain_raw_transcript: bool | None = None
    retain_result: bool | None = None
    glossary_name: str | None = None


@dataclass(frozen=True)
class Job:
    """Immutable record of a transcription job.

    Attributes:
        job_id: Unique identifier for this job.
        source: Human-readable description or URI of the input source.
        status: Current lifecycle state (JobStatus).
        work_dir: Path to the temporary directory owned by this job.
        options: Optional tuning parameters controlling retention and lookup.
    """

    job_id: str
    source: str
    status: JobStatus
    work_dir: pathlib.Path
    options: JobOptions


@dataclass(frozen=True)
class AudioArtifact:
    """A raw or intermediate audio file extracted from a job.

    Attributes:
        job_id: Parent Job.job_id.
        path: Absolute or relative file system path to the audio chunk.
        duration_seconds: Duration in seconds (None when unknown).
    """

    job_id: str
    path: pathlib.Path
    duration_seconds: float | None = None


@dataclass(frozen=True)
class RawSegment:
    """A single raw transcript segment with temporal metadata.

    Attributes:
        segment_id: Unique identifier for the segment.
        start_seconds: Start timestamp in seconds (inclusive).
        end_seconds: End timestamp in seconds (exclusive).
        raw_text: The verbatim text produced by the STT engine.
        confidence: Confidence score returned by the STT engine (None when unavailable).
    """

    segment_id: str
    start_seconds: float
    end_seconds: float
    raw_text: str
    confidence: float | None = None


@dataclass(frozen=True)
class ProtectedText:
    """Text containing placeholders and the reversible protected-value table.

    Attributes:
        text: Text in which protected values are represented by placeholders.
        replacements: Mapping used to restore each protected value exactly.
    """

    text: str
    replacements: dict[str, str]


@dataclass(frozen=True)
class RuleNormalizedText:
    """Protected text after the restricted rules-only normalization stage.

    Attributes:
        text: The fully normalized string.
        sentence_boundaries: Sentence-boundary positions in text. Empty tuple
            means the caller did not request them.
    """

    text: str
    sentence_boundaries: tuple[int, ...] = ()


@dataclass(frozen=True)
class CorrectionResult:
    """Glossary correction result with change tracking.

    Attributes:
        corrected_text: The text after applying all corrections.
        changes: Ordered list of old-to-new dicts describing each substitution.
        requires_review: True when a human should inspect the output before publishing.
    """

    corrected_text: str
    changes: tuple[dict[str, str], ...] = ()
    requires_review: bool = False


@dataclass(frozen=True)
class ReviewResult:
    """Human review result after examining a correction batch.

    Attributes:
        approved_text: The final text after the reviewer's acceptance.
        review_items: Per-item records containing the reviewer's notes or approvals.
    """

    approved_text: str
    review_items: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class Transcript:
    """Aggregation of all segments into a single textual output.

    Attributes:
        segments: Ordered tuple of RawSegment instances (chronological by start).
        final_text: Concatenated text of all segments for quick consumption.
    """

    segments: tuple[RawSegment, ...]
    final_text: str


@dataclass(frozen=True)
class Summary:
    """AI-generated summary with verifiable evidence.

    Attributes:
        text: The generated summary string.
        evidence_segment_ids: Tuple of segment_id values that support the summary claims.
    """

    text: str
    evidence_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class CleanupReport:
    """Post-job cleanup report for the temporary work_dir.

    Attributes:
        retained: Paths that were explicitly kept (e.g., user-specified retention).
        removed: Paths that were safely deleted by the cleanup routine.
    """

    retained: tuple[pathlib.Path, ...] = ()
    removed: tuple[pathlib.Path, ...] = ()


# ---- cleanup policy ----

@dataclass(frozen=True)
class CleanupPolicy:
    """Retention rules applied during job artifact cleanup.

    Attributes:
        retain_artifact_names: Direct child filenames to keep inside the work directory.
            Only leaf file names (no path separator, no ``.``, ``..``, or absolute paths).
        remove_empty_work_dir: If True and no retained artifacts remain after
            cleanup, the empty work directory itself is removed (reported in ``removed``).
    """

    retain_artifact_names: tuple[str, ...] = ()
    remove_empty_work_dir: bool = True


# ---- end of declarations ----
