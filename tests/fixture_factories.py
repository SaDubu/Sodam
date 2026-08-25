"""Fixture factories for B01 domain types — pure dataclass constructors.

Imports only ``backend.contracts``; uses no time, UUID, temp-dir, env-vars,
or real-file-system APIs.
"""
from __future__ import annotations

import pathlib

from backend.contracts import JobOptions, Job, RawSegment, Transcript


def make_job_options(**overrides: object) -> JobOptions:
    """Create a :class:`~backend.contracts.JobOptions` with optional field overrides."""
    return JobOptions(**overrides)


def make_job(**overrides: object) -> Job:
    """Create a :class:`~backend.contracts.Job` with safe defaults.

    ``options`` default is always a **new** ``JobOptions`` instance so callers
    cannot mutate shared state between calls.
    """
    base = {
        "job_id": "job-001",
        "source": "fixture://source",
        "status": "queued",
        "work_dir": pathlib.Path("fixture-work"),
        "options": JobOptions(),
    }
    return Job(**{**base, **overrides})


def make_raw_segment(**overrides: object) -> RawSegment:
    """Create a :class:`~backend.contracts.RawSegment` with safe defaults."""
    base = {
        "segment_id": "segment-001",
        "start_seconds": 0.0,
        "end_seconds": 1.0,
        "raw_text": "fixture text",
        "confidence": None,
    }
    return RawSegment(**{**base, **overrides})


def make_transcript(**overrides: object) -> Transcript:
    """Create a :class:`~backend.contracts.Transcript` with safe defaults.

    ``segments`` default is always a **new** tuple so separate calls are independent.
    """
    base = {
        "segments": (make_raw_segment(),),
        "final_text": "fixture text",
    }
    return Transcript(**{**base, **overrides})
