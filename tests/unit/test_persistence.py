"""Tests for schema-v1 permanent text result persistence."""

from pathlib import Path

import pytest

from backend.contracts import (
    Job,
    JobOptions,
    ProgressEvent,
    RawSegment,
    ReviewedSegment,
    ReviewedTranscript,
    StorageError,
    Summary,
    UnsafePathError,
    VideoIntroduction,
)
import backend.persistence as persistence
from backend.persistence import (
    load_result,
    persist_result,
    record_review_decision,
    refresh_resolved_summary,
)
from tools.inspect_job import inspect_job


def _result() -> tuple[Job, ReviewedTranscript, Summary, tuple[dict[str, str], ...]]:
    raw = RawSegment("segment-0001", 0.0, 1.0, "Raw fixture.")
    transcript = ReviewedTranscript(
        (ReviewedSegment(raw, "Reviewed fixture."),),
        "Reviewed fixture.",
    )
    job = Job("p04-result-001", "C:/media/input.mp3", "archived", Path("C:/tmp/ignored"), JobOptions())
    summary = Summary("Fixture summary.", ("segment-0001",))
    review = ({"kind": "review_required", "raw": "Raw", "corrected": "Reviewed", "reason": "fixture"},)
    return job, transcript, summary, review


def _introduction() -> VideoIntroduction:
    return VideoIntroduction(
        "Reviewed video",
        "Reviewed fixture 내용을 살펴봅니다. 실제 결과를 영상에서 확인하세요.",
        ("Reviewed",),
        ("segment-0001",),
        False,
        "실제 결과를 영상에서 확인하세요.",
    )


def _progress() -> ProgressEvent:
    return ProgressEvent(
        "p04-result-001", "job", "completed", "완료", 1.0, 1.0, None, None,
        1.0, 0.0, "done", False, 1, "1970-01-01T00:00:01Z"
    )


def test_persist_load_and_existing_inspector_round_trip(tmp_path: Path) -> None:
    job, transcript, summary, review = _result()

    path = persist_result(job, transcript, summary, review, tmp_path / "results")
    loaded = load_result(job.job_id, tmp_path / "results")
    report = inspect_job(str(path))

    assert path.name == job.job_id
    assert loaded.transcript == transcript
    assert loaded.summary == summary
    assert loaded.review_items == review
    assert report["summary_text"] == "Fixture summary."
    assert report["timeline"][0]["text"] == "Reviewed fixture."


def test_introduction_and_progress_artifacts_round_trip_without_replacing_summary(tmp_path: Path) -> None:
    job, transcript, summary, review = _result()
    path = persist_result(
        job, transcript, summary, review, tmp_path / "both", introduction=_introduction(), progress_events=(_progress(),)
    )
    loaded = load_result(job.job_id, tmp_path / "both")
    assert loaded.summary == summary
    assert loaded.introduction == _introduction()
    assert loaded.progress_events == (_progress(),)
    assert (path / "summary.json").exists()
    assert (path / "introduction.json").exists()
    assert (path / "progress.jsonl").exists()


def test_introduction_only_result_is_reopenable(tmp_path: Path) -> None:
    job, transcript, _summary, review = _result()
    path = persist_result(job, transcript, None, review, tmp_path / "intro", introduction=_introduction())
    loaded = load_result(job.job_id, tmp_path / "intro")
    assert loaded.summary is None
    assert loaded.introduction == _introduction()
    assert not (path / "summary.json").exists()
    report = inspect_job(str(path))
    assert report["summary_text"] is None
    assert report["introduction"]["title_hook"] == "Reviewed video"  # type: ignore[index]


def test_introduction_or_summary_is_required_and_malformed_intro_is_rejected(tmp_path: Path) -> None:
    job, transcript, _summary, review = _result()
    with pytest.raises(StorageError):
        persist_result(job, transcript, None, review, tmp_path / "empty")
    path = persist_result(job, transcript, None, review, tmp_path / "bad", introduction=_introduction())
    (path / "introduction.json").write_text(
        '{"title_hook":"fake","body":"fake.","highlights":["not-source"],"evidence_segment_ids":["segment-0001"],"question_used":false,"call_to_action":"fake."}',
        encoding="utf-8",
    )
    with pytest.raises(StorageError):
        load_result(job.job_id, tmp_path / "bad")


def test_write_failure_leaves_no_partial_visible_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job, transcript, summary, review = _result()
    original = persistence._write_json
    calls = 0

    def fail_after_first(path: Path, payload: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture write failure")
        original(path, payload)

    monkeypatch.setattr(persistence, "_write_json", fail_after_first)
    root = tmp_path / "results"
    with pytest.raises(StorageError):
        persist_result(job, transcript, summary, review, root)

    assert not (root / job.job_id).exists()
    assert list(root.glob(".sodam-result-*")) == []


def test_duplicate_schema_mismatch_and_unsafe_roots_are_rejected(tmp_path: Path) -> None:
    job, transcript, summary, review = _result()
    root = tmp_path / "results"
    path = persist_result(job, transcript, summary, review, root)
    original_metadata = (path / "metadata.json").read_bytes()

    with pytest.raises(StorageError):
        persist_result(job, transcript, summary, review, root)
    assert (path / "metadata.json").read_bytes() == original_metadata

    (path / "format.json").write_text('{"schema_version":2}', encoding="utf-8")
    with pytest.raises(StorageError):
        load_result(job.job_id, root)
    with pytest.raises(UnsafePathError):
        load_result("../escape", root)
    with pytest.raises(UnsafePathError):
        persist_result(job, transcript, summary, review, Path(__file__).resolve().parents[2] / "unsafe-results")


@pytest.mark.parametrize(
    ("decision", "resolved_text"),
    [
        ("accept_suggested", "Reviewed"),
        ("keep_original", "Raw"),
        ("custom_text", "Human choice"),
    ],
)
def test_review_decision_round_trip_for_each_allowed_action(
    tmp_path: Path,
    decision: str,
    resolved_text: str,
) -> None:
    job, transcript, summary, review = _result()
    root = tmp_path / decision
    persist_result(job, transcript, summary, review, root)

    recorded = record_review_decision(job.job_id, 0, decision, resolved_text, root)
    loaded = load_result(job.job_id, root)

    assert loaded.review_decisions == (recorded,)


def test_review_decision_rejects_duplicate_bad_index_and_failed_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job, transcript, summary, review = _result()
    root = tmp_path / "results"
    persist_result(job, transcript, summary, review, root)
    record_review_decision(job.job_id, 0, "accept_suggested", "Reviewed", root)
    path = root / job.job_id / "review_resolution.json"
    before = path.read_bytes()

    with pytest.raises(StorageError):
        record_review_decision(job.job_id, 0, "accept_suggested", "Reviewed", root)
    with pytest.raises(StorageError):
        record_review_decision(job.job_id, 9, "custom_text", "other", root)
    with pytest.raises(StorageError):
        record_review_decision(job.job_id, 0, "keep_original", "wrong", root)
    assert path.read_bytes() == before

    path.write_text('{"schema_version":1,"decisions":[{"review_index":0,"decision":"custom_text","resolved_text":""}]}', encoding="utf-8")
    with pytest.raises(StorageError):
        load_result(job.job_id, root)


def test_failed_atomic_decision_update_preserves_previous_valid_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job, transcript, summary, review = _result()
    review = review + (
        {"kind": "review_required", "raw": "one", "corrected": "two", "reason": "fixture"},
    )
    root = tmp_path / "results"
    persist_result(job, transcript, summary, review, root)
    record_review_decision(job.job_id, 0, "accept_suggested", "Reviewed", root)
    audit = root / job.job_id / "review_resolution.json"
    before = audit.read_bytes()

    def fail_atomic(*_: object) -> None:
        raise StorageError("fixture atomic failure")

    monkeypatch.setattr(persistence, "_atomic_replace_json", fail_atomic)
    with pytest.raises(StorageError):
        record_review_decision(job.job_id, 1, "keep_original", "one", root)

    assert audit.read_bytes() == before


def test_review_location_round_trip_and_malformed_location_rejection(tmp_path: Path) -> None:
    raw = RawSegment("segment-0001", 0.0, 1.0, "JFK JFK")
    transcript = ReviewedTranscript((ReviewedSegment(raw, "JFK JFK"),), "JFK JFK")
    job = Job("p04-location-001", "fixture", "archived", Path("C:/tmp/ignored"), JobOptions())
    summary = Summary("Fixture summary.", ("segment-0001",))
    review = (
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
    )
    locations = (
        {"review_index": 0, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 3},
        {"review_index": 1, "segment_id": "segment-0001", "start_offset": 4, "end_offset": 7},
    )
    root = tmp_path / "results"
    path = persist_result(job, transcript, summary, review, root, locations)

    assert load_result(job.job_id, root).review_locations == locations

    (path / "review_locations.json").write_text(
        '{"schema_version":1,"locations":[{"review_index":0,"segment_id":"segment-0001","start_offset":0,"end_offset":2},{"review_index":1,"segment_id":"segment-0001","start_offset":4,"end_offset":7}]}',
        encoding="utf-8",
    )
    with pytest.raises(StorageError):
        load_result(job.job_id, root)


def test_resolved_projection_applies_ordered_locations_and_marks_summary_stale(tmp_path: Path) -> None:
    raw = RawSegment("segment-0001", 0.0, 1.0, "JFK JFK")
    transcript = ReviewedTranscript((ReviewedSegment(raw, "JFK JFK"),), "JFK JFK")
    job = Job("p04-resolved-001", "fixture", "archived", Path("C:/tmp/ignored"), JobOptions())
    summary = Summary("Fixture summary.", ("segment-0001",))
    review = (
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
    )
    locations = (
        {"review_index": 0, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 3},
        {"review_index": 1, "segment_id": "segment-0001", "start_offset": 4, "end_offset": 7},
    )
    root = tmp_path / "results"
    persist_result(job, transcript, summary, review, root, locations)
    record_review_decision(job.job_id, 0, "accept_suggested", "NASA", root)
    record_review_decision(job.job_id, 1, "keep_original", "JFK", root)

    loaded = load_result(job.job_id, root)

    assert loaded.resolved_transcript is not None
    assert loaded.resolved_transcript.final_text == "NASA JFK"
    assert loaded.applied_review_indices == (0, 1)
    assert loaded.unapplied_review_indices == ()
    assert loaded.summary_is_stale is True


def test_legacy_or_null_location_decisions_remain_unapplied(tmp_path: Path) -> None:
    job, transcript, summary, review = _result()
    root = tmp_path / "legacy"
    persist_result(job, transcript, summary, review, root)
    record_review_decision(job.job_id, 0, "accept_suggested", "Reviewed", root)

    loaded = load_result(job.job_id, root)

    assert loaded.resolved_transcript == transcript
    assert loaded.applied_review_indices == ()
    assert loaded.unapplied_review_indices == (0,)
    assert loaded.summary_is_stale is False


def test_overlapping_location_decisions_are_rejected_on_projection(tmp_path: Path) -> None:
    raw = RawSegment("segment-0001", 0.0, 1.0, "JFK")
    transcript = ReviewedTranscript((ReviewedSegment(raw, "JFK"),), "JFK")
    job = Job("p04-overlap-001", "fixture", "archived", Path("C:/tmp/ignored"), JobOptions())
    summary = Summary("Fixture summary.", ("segment-0001",))
    review = (
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
    )
    locations = (
        {"review_index": 0, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 3},
        {"review_index": 1, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 3},
    )
    root = tmp_path / "overlap"
    persist_result(job, transcript, summary, review, root, locations)
    record_review_decision(job.job_id, 0, "accept_suggested", "NASA", root)
    record_review_decision(job.job_id, 1, "accept_suggested", "NASA", root)

    with pytest.raises(StorageError):
        load_result(job.job_id, root)


def test_explicit_resolved_summary_refresh_preserves_base_summary(tmp_path: Path) -> None:
    raw = RawSegment("segment-0001", 0.0, 1.0, "JFK")
    transcript = ReviewedTranscript((ReviewedSegment(raw, "JFK"),), "JFK")
    job = Job("p04-summary-001", "fixture", "archived", Path("C:/tmp/ignored"), JobOptions())
    base_summary = Summary("Base summary.", ("segment-0001",))
    review = ({"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},)
    locations = ({"review_index": 0, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 3},)
    root = tmp_path / "results"
    persist_result(job, transcript, base_summary, review, root, locations)
    record_review_decision(job.job_id, 0, "accept_suggested", "NASA", root)

    class Runtime:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return '{"text":"Resolved summary.","evidence_segment_ids":["segment-0001"]}'

    runtime = Runtime()
    refreshed = refresh_resolved_summary(job.job_id, runtime, root)
    loaded = load_result(job.job_id, root)

    assert len(runtime.prompts) == 1
    assert refreshed.text == "Resolved summary."
    assert loaded.summary == base_summary
    assert loaded.resolved_summary == refreshed
    assert loaded.summary_is_stale is False
    with pytest.raises(StorageError):
        refresh_resolved_summary(job.job_id, runtime, root)
