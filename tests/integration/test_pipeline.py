"""Fake-only integration tests for the B13 sequential local pipeline."""

import json
from pathlib import Path
import uuid

import pytest

from backend.contracts import CleanupPolicy, Job, JobOptions, MediaExtractionError
from backend.main import _build_correction_groups, _review_locations, build_application
from backend.storage import JOB_WORK_ROOT, cleanup_artifacts


class RecordingSourceAdapter:
    """Record URL acquisition attempts; local-media tests must not call it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def acquire(self, source_url: str, destination: Path) -> None:
        self.calls.append((source_url, destination))
        destination.write_bytes(b"source audio")


class RecordingRunner:
    """Write a non-empty normalized artifact or raise the configured failure."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, arguments: list[str]) -> None:
        self.calls.append(list(arguments))
        if self.error is not None:
            raise self.error
        Path(arguments[-1]).write_bytes(b"normalized audio")


class RecordingSttEngine:
    """Return one deterministic segment and record the resolved audio path."""

    def __init__(self, texts: tuple[str, ...] = ("OpenAI fixture line.",)) -> None:
        self.paths: list[str] = []
        self.texts = texts

    def transcribe(self, audio_path: str) -> object:
        self.paths.append(audio_path)
        return [
            {"start": float(index), "end": float(index + 1), "text": text}
            for index, text in enumerate(self.texts)
        ]


class PipelineRuntime:
    """Return a correction response or final evidence-linked summary by prompt kind."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Plans:" in prompt:
            return json.dumps({"edits": [], "requires_review": False})
        return json.dumps(
            {
                "text": "Integration summary.",
                "evidence_segment_ids": ["segment-0001"],
            }
        )


class ReviewRuntime(PipelineRuntime):
    """Return one deliberate non-formatting change for location mapping tests."""

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Plans:" in prompt:
            plan = json.loads(prompt.rsplit("\n", 1)[-1])
            editable = next(
                part for part in plan["parts"]
                if part["kind"] == "editable" and "fixture" in part["text"]
            )
            return json.dumps(
                {
                    "edits": [
                        {
                            "editable_id": editable["part_id"],
                            "replacement": editable["text"].replace("fixture", "reviewed"),
                        }
                    ],
                    "requires_review": True,
                }
            )
        return json.dumps(
            {"text": "Integration summary.", "evidence_segment_ids": ["segment-0001"]}
        )


class IdentityThenValidRuntime(PipelineRuntime):
    """Force one group through identity fallback before accepting the next."""

    def __init__(self) -> None:
        super().__init__()
        self.correction_calls = 0

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Plans:" in prompt:
            self.correction_calls += 1
            if self.correction_calls <= 3:
                return "not json"
            return json.dumps({"edits": [], "requires_review": False})
        return json.dumps(
            {
                "text": "Integration summary.",
                "evidence_segment_ids": ["segment-0001"],
            }
        )


@pytest.fixture
def job() -> Job:
    """Yield a job whose source and every generated artifact stay in one work dir."""
    job_id = "t05-" + uuid.uuid4().hex
    work_dir = JOB_WORK_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "input.mp3"
    source.write_bytes(b"local media")
    value = Job(job_id, str(source), "queued", work_dir, JobOptions())
    try:
        yield value
    finally:
        cleanup_artifacts(value, CleanupPolicy())
        assert not work_dir.exists()


def _application(
    source_adapter: RecordingSourceAdapter,
    runner: RecordingRunner,
    stt: RecordingSttEngine,
    runtime: PipelineRuntime,
):
    return build_application(
        source_adapter=source_adapter,
        ffmpeg_runner=runner,
        stt_engine=stt,
        qwen_runtime=runtime,
        glossary=("OpenAI",),
    )


def test_local_success_runs_injected_collaborators_then_archives_and_cleans(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner()
    stt = RecordingSttEngine()
    runtime = PipelineRuntime()

    result = _application(source_adapter, runner, stt, runtime).run(job)

    assert result.job.status == "archived"
    assert result.transcript is not None
    assert result.transcript.final_text == "OpenAI fixture line."
    assert result.summary is not None
    assert result.summary.text == "Integration summary."
    assert result.summary.evidence_segment_ids == ("segment-0001",)
    assert result.review_items == ()
    assert result.correction_group_count == 1
    assert result.identity_group_count == 0
    assert len(result.correction_attempts) == 1
    assert len(result.correction_attempts[0]) == 1
    assert source_adapter.calls == []
    assert len(runner.calls) == 1
    assert runner.calls[0][0:2] == ["-i", str((job.work_dir / "input.mp3").resolve())]
    assert len(stt.paths) == 1
    assert len(runtime.prompts) == 2
    assert not job.work_dir.exists()


def test_start_cancellation_archives_and_cleans_without_collaborator_calls(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner()
    stt = RecordingSttEngine()
    runtime = PipelineRuntime()

    result = _application(source_adapter, runner, stt, runtime).run(
        job,
        cancellation_requested=lambda _: True,
    )

    assert result.job.status == "archived"
    assert result.transcript is None
    assert result.summary is None
    assert source_adapter.calls == []
    assert runner.calls == []
    assert stt.paths == []
    assert runtime.prompts == []
    assert not job.work_dir.exists()


def test_runner_failure_propagates_as_media_error_and_cleans(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner(RuntimeError("ffmpeg failed"))

    with pytest.raises(MediaExtractionError):
        _application(source_adapter, runner, RecordingSttEngine(), PipelineRuntime()).run(job)

    assert len(runner.calls) == 1
    assert not job.work_dir.exists()


def test_keyboard_interrupt_is_re_raised_after_best_effort_cleanup(job: Job) -> None:
    source_adapter = RecordingSourceAdapter()
    runner = RecordingRunner(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        _application(source_adapter, runner, RecordingSttEngine(), PipelineRuntime()).run(job)

    assert len(runner.calls) == 1
    assert not job.work_dir.exists()


def test_review_items_receive_segment_bound_offsets(job: Job) -> None:
    result = _application(
        RecordingSourceAdapter(), RecordingRunner(), RecordingSttEngine(), ReviewRuntime()
    ).run(job)

    assert result.transcript is not None
    assert result.transcript.final_text == "OpenAI fixture line."
    assert result.review_items == (
        {"kind": "review_required", "raw": "fixtu", "corrected": "", "reason": "non_formatting_change"},
        {"kind": "review_required", "raw": "", "corrected": "viewed", "reason": "non_formatting_change"},
    )
    assert result.review_locations == (
        {"review_index": 0, "segment_id": "segment-0001", "start_offset": 7, "end_offset": 12},
        {"review_index": 1, "segment_id": "segment-0001", "start_offset": None, "end_offset": None},
    )


def test_location_helper_uses_occurrence_order_and_null_for_insertions() -> None:
    items = (
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
        {"kind": "review_required", "raw": "JFK", "corrected": "NASA", "reason": "fixture"},
        {"kind": "review_required", "raw": "", "corrected": "new", "reason": "fixture"},
    )

    assert _review_locations("segment-0001", "JFK JFK", items, 4) == (
        {"review_index": 4, "segment_id": "segment-0001", "start_offset": 0, "end_offset": 3},
        {"review_index": 5, "segment_id": "segment-0001", "start_offset": 4, "end_offset": 7},
        {"review_index": 6, "segment_id": "segment-0001", "start_offset": None, "end_offset": None},
    )


def test_correction_groups_preserve_order_and_respect_budget(job: Job) -> None:
    from backend.contracts import ProtectedText, RuleNormalizedText

    prepared = tuple(
        (
            ProtectedText(text, {}),
            RuleNormalizedText(text),
            "segment-%04d" % (index + 1),
        )
        for index, text in enumerate(("one", "two", "three"))
    )
    groups = _build_correction_groups(prepared, max_characters=7)
    assert [[plan.segment_id for plan in group] for group in groups] == [
        ["segment-0001", "segment-0002"],
        ["segment-0003"],
    ]


def test_identity_group_is_reviewed_but_pipeline_still_archives(job: Job) -> None:
    first = "first " * 450
    second = "second " * 450
    runtime = IdentityThenValidRuntime()
    result = _application(
        RecordingSourceAdapter(),
        RecordingRunner(),
        RecordingSttEngine((first, second)),
        runtime,
    ).run(job)

    assert result.job.status == "archived"
    assert result.transcript is not None
    assert result.transcript.segments[0].final_text == first.strip()
    assert result.transcript.segments[1].final_text == second.strip()
    assert result.summary is not None
    assert result.review_items == (
        {
            "kind": "correction_unapplied",
            "raw": first.strip(),
            "corrected": first.strip(),
            "reason": "correction_unapplied:invalid_response",
        },
    )
    assert result.review_locations == (
        {
            "review_index": 0,
            "segment_id": "segment-0001",
            "start_offset": 0,
            "end_offset": len(first.strip()),
        },
    )
    assert runtime.correction_calls == 4
    assert result.correction_group_count == 2
    assert result.identity_group_count == 1
    assert [len(group) for group in result.correction_attempts] == [3, 1]
