"""Typed domain contracts shared by the backend layers.

The data classes describe values only.  Validation, persistence, serialization,
and state-transition logic belong to their separately scheduled modules.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

JobStatus = Literal[
    "queued", "acquiring", "extracting", "transcribing", "normalizing",
    "correcting", "reviewing", "summarizing", "completed", "cancelling",
    "cancelled", "failed", "cleaning", "archived",
]


class SodamError(Exception):
    """Base exception for a documented Sodam contract violation."""


class InputSourceError(SodamError):
    """Raised when a submitted source cannot be accepted."""


class UnsafePathError(SodamError):
    """Raised when an operation would escape its job-owned directory."""


class ModelResponseError(SodamError):
    """Raised when a model result violates the documented response schema."""


@dataclass(frozen=True)
class JobOptions:
    """User-selected, serializable job options; defaults are not chosen yet."""

    retain_raw_transcript: bool | None = None
    retain_result: bool | None = None
    glossary_name: str | None = None


@dataclass(frozen=True)
class Job:
    """A job identity, source reference, state, and owned temporary directory."""

    job_id: str
    source: str
    status: JobStatus
    work_dir: Path
    options: JobOptions


@dataclass(frozen=True)
class AudioArtifact:
    """A normalized audio artifact owned by exactly one job."""

    job_id: str
    path: Path
    duration_seconds: float | None = None


@dataclass(frozen=True)
class RawSegment:
    """An STT text segment with its immutable source timing."""

    segment_id: str
    start_seconds: float
    end_seconds: float
    raw_text: str
    confidence: float | None = None


@dataclass(frozen=True)
class ProtectedText:
    """Text containing placeholders and the reversible protected-value table."""

    text: str
    replacements: dict[str, str]


@dataclass(frozen=True)
class RuleNormalizedText:
    """Protected text after the restricted rules-only normalization stage."""

    text: str
    sentence_boundaries: tuple[int, ...] = ()


@dataclass(frozen=True)
class CorrectionResult:
    """Schema-validated correction for one or more adjacent source segments."""

    corrected_text: str
    changes: tuple[dict[str, str], ...] = ()
    requires_review: bool = False


@dataclass(frozen=True)
class ReviewResult:
    """Validated revision with changes safe to apply and changes for review."""

    approved_text: str
    review_items: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class Transcript:
    """Final transcript retaining source segments and a time-addressable index."""

    segments: tuple[RawSegment, ...]
    final_text: str


@dataclass(frozen=True)
class Summary:
    """A two-sentence-or-fewer summary and the supporting source segment IDs."""

    text: str
    evidence_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class CleanupReport:
    """A read-only report of artifacts selected for retention or removal."""

    retained: tuple[Path, ...] = ()
    removed: tuple[Path, ...] = ()
