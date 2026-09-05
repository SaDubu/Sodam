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

OutputMode = Literal["summary", "introduction", "both"]

SummaryFailureCategory = Literal[
    "batch_failed",
    "reduce_failed",
    "final_failed",
    "retry_exhausted",
]

ProgressScope = Literal["setup", "job"]

ProgressStage = Literal[
    "environment_check",
    "dependency_install",
    "model_download",
    "source_validation",
    "source_acquisition",
    "audio_extraction",
    "transcription",
    "text_protection",
    "rule_normalization",
    "correction",
    "review_validation",
    "transcript_assembly",
    "summarization",
    "introduction",
    "persistence",
    "cleanup",
    "completed",
    "failed",
    "cancelled",
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


class ReviewMappingError(TranscriptAssemblyError):
    """Review coordinates cannot be safely applied to their source segment."""

    def __init__(self, diagnostic_code: str, segment_id: str | None = None) -> None:
        super().__init__("review coordinates do not match the source contract")
        self.diagnostic_code = diagnostic_code
        self.segment_id = segment_id
        self.stage = "review_validation"


class EmptyTranscriptError(SodamError):
    """Raised when a summary is requested for an empty transcript."""


class IntroductionError(SodamError):
    """Raised when a generated video introduction violates its contract."""


class ProgressStateError(SodamError):
    """Raised when progress events violate the operation lifecycle."""


class InstallationError(SodamError):
    """Raised when a system probe, installation, or verification step fails."""


class BuildError(SodamError):
    """Raised when an operating-system-specific desktop build cannot complete."""


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
class ReviewSpan:
    """A review item's range in restored source text; insertions have no range."""

    start_offset: int | None
    end_offset: int | None


@dataclass(frozen=True)
class ReviewResult:
    """Human review result after examining a correction batch.

    Attributes:
        approved_text: The final text after the reviewer's acceptance.
        review_items: Per-item records containing the reviewer's notes or approvals.
        review_spans: Source-coordinate ranges aligned with review_items.
    """

    approved_text: str
    review_items: tuple[dict[str, str], ...] = ()
    review_spans: tuple[ReviewSpan, ...] = ()


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
class ReviewedSegment:
    """One source segment paired with its approved, restored final text."""

    source: RawSegment
    final_text: str


@dataclass(frozen=True)
class ReviewedTranscript:
    """An ordered reviewed transcript that retains its raw segment evidence."""

    segments: tuple[ReviewedSegment, ...]
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


# ---- approved v2 contract skeletons ----

@dataclass(frozen=True)
class Highlight:
    """One source-grounded candidate for use in a video introduction."""

    text: str
    category: str
    evidence_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class SummaryOutcome:
    """A validated Summary together with success or review-only fallback state."""

    summary: Summary
    status: Literal["success", "fallback"]
    failure_category: str | None = None
    attempt_count: int = 1
    fallback_source: Literal["batch", "reduce"] | None = None


@dataclass(frozen=True)
class IntroductionOptions:
    """Style limits for a video introduction without changing summary behavior."""

    minimum_body_sentences: int = 2
    maximum_body_sentences: int = 3
    maximum_questions: int | None = None
    exclude_promotional_segments: bool = True
    require_first_question: bool = False


# Generation follows the current prompt; archived results retain legacy defaults.
INTRODUCTION_GENERATION_OPTIONS = IntroductionOptions(
    minimum_body_sentences=3, maximum_body_sentences=3, require_first_question=True
)


@dataclass(frozen=True)
class VideoIntroduction:
    """Fact-grounded promotional copy stored separately from Summary."""

    title_hook: str
    body: str
    highlights: tuple[str, ...]
    evidence_segment_ids: tuple[str, ...]
    question_used: bool
    call_to_action: str


@dataclass(frozen=True)
class ProgressEvent:
    """Validated setup or job progress payload shared by CLI and desktop UI."""

    operation_id: str
    scope: ProgressScope
    stage: ProgressStage
    stage_label: str
    stage_progress: float | None
    overall_progress: float | None
    completed_units: float | None
    total_units: float | None
    elapsed_seconds: float
    eta_seconds: float | None
    message: str
    can_cancel: bool
    sequence: int
    timestamp: str


@dataclass(frozen=True)
class RuntimeProfile:
    """User-selected local runtime paths, model tags, and bounded context settings."""

    profile_name: str
    qwen_model: str
    stt_model_path: pathlib.Path
    ffmpeg_path: pathlib.Path
    ollama_endpoint: str = "http://127.0.0.1:11434/api/chat"
    qwen_context_tokens: int = 32768


@dataclass(frozen=True)
class SystemProfile:
    """Read-only host capability report used to plan an installation."""

    operating_system: str
    architecture: str
    cpu_name: str | None
    ram_bytes: int | None
    gpu_name: str | None
    vram_bytes: int | None
    free_disk_bytes: int | None
    tool_versions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class InstallationAction:
    """One explicit, user-visible step in an installation plan."""

    action_id: str
    label: str
    download_bytes: int | None = None
    required_disk_bytes: int | None = None


@dataclass(frozen=True)
class InstallationPlan:
    """Immutable installation proposal created before external changes occur."""

    requested_profile: str
    actions: tuple[InstallationAction, ...]
    total_download_bytes: int | None
    required_disk_bytes: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstallationReceipt:
    """Verified record of installed tools and exact local model identifiers."""

    profile_name: str
    installed_tools: tuple[tuple[str, str], ...]
    model_identifiers: tuple[tuple[str, str], ...]
    completed_at: str


@dataclass(frozen=True)
class BuildArtifact:
    """One operating-system-specific desktop build output and its digest."""

    target_os: str
    path: pathlib.Path
    sha256: str


# ---- v3 constrained-correction skeleton contracts ----

@dataclass(frozen=True)
class EditablePart:
    """A model-editable text span identified independently of its content."""

    part_id: str
    text: str


@dataclass(frozen=True)
class LockedPart:
    """An immutable source-grounded span reinserted by the application."""

    part_id: str
    text: str


CorrectionPart = EditablePart | LockedPart


@dataclass(frozen=True)
class EditableTextPlan:
    """Ordered editable/locked spans for one transcript segment or group."""

    segment_id: str
    parts: tuple[CorrectionPart, ...]
    original_text: str


@dataclass(frozen=True)
class EditProposal:
    """One proposed replacement for an editable part."""

    editable_id: str
    replacement: str


@dataclass(frozen=True)
class CorrectionAttempt:
    """Metadata for one constrained-correction model attempt."""

    attempt_number: int
    status: Literal["accepted", "retrying", "identity_applied"]
    reason: str | None = None


@dataclass(frozen=True)
class CorrectionOutcome:
    """Validated correction output, including retry and review metadata."""

    text: str
    edits: tuple[EditProposal, ...]
    attempts: tuple[CorrectionAttempt, ...]
    identity_applied: bool
    review_reason: str | None = None


# ---- end of declarations ----
