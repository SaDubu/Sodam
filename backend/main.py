"""Injected local job-pipeline composition and orchestration."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import time
from typing import Callable
from urllib.parse import urlsplit

from .contracts import (
    AudioArtifact,
    CorrectionAttempt,
    EditablePart,
    EditableTextPlan,
    Job,
    JobStateError,
    OutputMode,
    ProtectionError,
    ProtectedText,
    ReviewMappingError,
    ReviewSpan,
    RuleNormalizedText,
    ReviewedTranscript,
    Summary,
    SummaryOutcome,
    TranscriptAssemblyError,
    VideoIntroduction,
)
from .correction import QwenRuntime, correct_with_retry
from .generation import GenerationRequest, build_generation_prompt, generate_from_transcript
from .jobs import request_cancellation, transition_job
from .introduction import generate_video_introduction
from .media import FfmpegRunner, extract_audio
from .protection import (
    protect_tokens,
    reassemble_locked_parts,
    restore_tokens,
    split_locked_parts,
)
from .sources import SourceAudioAdapter, acquire_source_audio
from .storage import CleanupPolicy, assemble_reviewed_transcript, assemble_transcript, cleanup_artifacts
from .summarization import summarize_reviewed_transcript_outcome
from .progress import Clock, ProgressSink, ProgressTracker
from .text_rules import normalize_rules
from .transcription import SttEngine, transcribe_audio
from .validation import validate_revision


@dataclass(frozen=True)
class PipelineResult:
    """Terminal result of one local pipeline run."""

    job: Job
    transcript: ReviewedTranscript | None = None
    summary: Summary | None = None
    introduction: VideoIntroduction | None = None
    review_items: tuple[dict[str, str], ...] = ()
    review_locations: tuple[dict[str, object], ...] = ()
    correction_attempts: tuple[tuple[CorrectionAttempt, ...], ...] = ()
    identity_group_count: int = 0
    correction_group_count: int = 0
    review_required_count: int = 0
    summary_outcome: SummaryOutcome | None = None


def _review_locations(
    segment_id: str,
    reviewed_text: str,
    review_items: tuple[dict[str, str], ...],
    first_index: int,
) -> tuple[dict[str, object], ...]:
    """Locate review changes sequentially in one immutable reviewed segment."""
    cursor = 0
    locations: list[dict[str, object]] = []
    for offset, item in enumerate(review_items):
        raw = item["raw"]
        if raw == "":
            start: int | None = None
            end: int | None = None
        else:
            start = reviewed_text.find(raw, cursor)
            if start < 0:
                raise TranscriptAssemblyError(
                    "review item raw text cannot be located in its reviewed segment"
                )
            end = start + len(raw)
            cursor = end
        locations.append(
            {
                "review_index": first_index + offset,
                "segment_id": segment_id,
                "start_offset": start,
                "end_offset": end,
            }
        )
    return tuple(locations)


def _review_locations_from_spans(
    segment_id: str,
    approved_text: str,
    review_items: tuple[dict[str, str], ...],
    spans: tuple[ReviewSpan, ...],
    first_index: int,
) -> tuple[dict[str, object], ...]:
    """Validate exact source-coordinate ranges without searching repeated text."""
    if not isinstance(segment_id, str) or not isinstance(approved_text, str):
        raise TypeError("segment_id and approved_text must be strings")
    if not segment_id.strip():
        raise ValueError("segment_id must not be blank")
    if not isinstance(review_items, tuple) or not isinstance(spans, tuple):
        raise TypeError("review_items and spans must be tuples")
    if type(first_index) is not int or first_index < 0:
        raise ValueError("first_index must be a non-negative integer")
    if len(review_items) != len(spans):
        raise ReviewMappingError("review_span_count_invalid", segment_id)

    locations: list[dict[str, object]] = []
    previous_end = 0
    for index, (item, span) in enumerate(zip(review_items, spans)):
        if not isinstance(item, dict) or not isinstance(item.get("raw"), str):
            raise TypeError("review items must contain a string raw value")
        if not isinstance(span, ReviewSpan):
            raise ReviewMappingError("review_span_range_invalid", segment_id)
        raw = item["raw"]
        start, end = span.start_offset, span.end_offset
        if raw == "":
            if start is not None or end is not None:
                raise ReviewMappingError("review_span_range_invalid", segment_id)
        else:
            if (
                type(start) is not int or type(end) is not int
                or start < previous_end or end <= start or end > len(approved_text)
            ):
                raise ReviewMappingError("review_span_range_invalid", segment_id)
            if approved_text[start:end] != raw:
                raise ReviewMappingError("review_location_mismatch", segment_id)
            previous_end = end
        locations.append({
            "review_index": first_index + index,
            "segment_id": segment_id,
            "start_offset": start,
            "end_offset": end,
        })
    return tuple(locations)


_PLACEHOLDER_TOKEN_RE = re.compile(r"\[\[SODAM_PROTECTED_\d+\]\]")


class _CorrectionRuntimeAdapter:
    """Normalize a legacy summary-envelope fake to a safe no-op proposal."""

    def __init__(self, runtime: QwenRuntime) -> None:
        self._runtime = runtime

    def complete(self, prompt: str) -> str:
        raw = self._runtime.complete(prompt)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        if (
            isinstance(payload, dict)
            and set(payload) == {"text", "evidence_segment_ids"}
        ):
            return json.dumps({"edits": [], "requires_review": True})
        return raw


def _build_correction_groups(
    prepared: tuple[tuple[ProtectedText, RuleNormalizedText], ...],
    *,
    max_characters: int = 2_000,
) -> tuple[tuple[EditableTextPlan, ...], ...]:
    """Convert normalized protected segments into bounded ordered plan groups."""
    if not isinstance(prepared, tuple):
        raise TypeError("prepared must be a tuple")
    if isinstance(max_characters, bool) or not isinstance(max_characters, int):
        raise TypeError("max_characters must be an int")
    if max_characters <= 0:
        raise ValueError("max_characters must be positive")

    plans: list[EditableTextPlan] = []
    for index, item in enumerate(prepared):
        if not isinstance(item, tuple) or len(item) not in {2, 3}:
            raise TypeError("prepared items must be (ProtectedText, RuleNormalizedText)")
        protected = item[0]
        normalized = item[1]
        if not isinstance(protected, ProtectedText):
            raise TypeError("prepared protected value must be ProtectedText")
        if not isinstance(normalized, RuleNormalizedText):
            raise TypeError("prepared normalized value must be RuleNormalizedText")
        segment_id = item[2] if len(item) == 3 else "segment-%04d" % (index + 1)
        if not isinstance(segment_id, str):
            raise TypeError("segment_id must be str")
        normalized_protected = ProtectedText(
            normalized.text,
            dict(protected.replacements),
        )
        plans.append(split_locked_parts(normalized_protected, segment_id))

    groups: list[tuple[EditableTextPlan, ...]] = []
    current: list[EditableTextPlan] = []
    current_length = 0
    for plan in plans:
        plan_length = len(plan.original_text)
        separator_length = 1 if current else 0
        if current and current_length + separator_length + plan_length > max_characters:
            groups.append(tuple(current))
            current = []
            current_length = 0
            separator_length = 0
        current.append(plan)
        current_length += separator_length + plan_length
        if current_length > max_characters:
            groups.append(tuple(current))
            current = []
            current_length = 0
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _proposal_text_for_validation(
    plan: EditableTextPlan,
    protected: ProtectedText,
    replacements: dict[str, str],
) -> str:
    """Rebuild a placeholder-bearing candidate for the B10 validator."""
    tokens = iter(_PLACEHOLDER_TOKEN_RE.findall(protected.text))
    pieces: list[str] = []
    for part in plan.parts:
        if isinstance(part, EditablePart):
            pieces.append(replacements.get(part.part_id, part.text))
        else:
            try:
                pieces.append(next(tokens))
            except StopIteration as exc:
                raise ProtectionError("locked part/token count mismatch") from exc
    try:
        next(tokens)
    except StopIteration:
        return "".join(pieces)
    raise ProtectionError("locked part/token count mismatch")


@dataclass(frozen=True)
class PipelineApplication:
    """A pipeline that uses only dependencies provided by its caller."""

    source_adapter: SourceAudioAdapter
    ffmpeg_runner: FfmpegRunner
    stt_engine: SttEngine
    qwen_runtime: QwenRuntime
    glossary: tuple[str, ...] = ()
    generation_runtime: QwenRuntime | None = None

    def _finish_failed(self, job: Job) -> None:
        """Best-effort failed cleanup; the original pipeline error wins."""
        try:
            failed = transition_job(job, "failed")
            cleaning = transition_job(failed, "cleaning")
            try:
                cleanup_artifacts(cleaning, CleanupPolicy())
            except BaseException:
                pass
            try:
                transition_job(cleaning, "archived")
            except BaseException:
                pass
        except BaseException:
            pass

    def run(
        self,
        job: Job,
        *,
        output_mode: OutputMode = "summary",
        cancellation_requested: Callable[[Job], bool] | None = None,
        progress_sink: ProgressSink | None = None,
        progress_clock: Clock | None = None,
        summary_instruction: str | None = None,
        introduction_instruction: str | None = None,
    ) -> PipelineResult:
        """Process one queued job while preserving the summary-compatible default."""
        if not isinstance(job, Job):
            raise TypeError("job must be a Job")
        if job.status != "queued":
            raise JobStateError("pipeline jobs must start in queued status")
        if cancellation_requested is not None and not callable(cancellation_requested):
            raise TypeError("cancellation_requested must be callable or None")
        if output_mode not in {"summary", "introduction", "both"}:
            raise ValueError("output_mode must be summary, introduction, or both")
        if summary_instruction is not None:
            build_generation_prompt("pipeline instruction validation", summary_instruction)
        if introduction_instruction is not None:
            build_generation_prompt("pipeline instruction validation", introduction_instruction)
        if progress_sink is not None and progress_clock is None:
            progress_clock = _SystemClock()
        if progress_sink is not None and progress_clock is None:
            raise TypeError("progress_clock is required when progress_sink is provided")

        current = job
        terminal_cleanup = False
        progress_tracker = (
            ProgressTracker(job.job_id, "job", progress_sink, progress_clock)
            if progress_sink is not None and progress_clock is not None
            else None
        )
        progress_terminal = False

        def start_progress(stage: str, total_units: float | None = None, message: str = "") -> None:
            if progress_tracker is not None:
                progress_tracker.start_stage(stage, total_units, message)  # type: ignore[arg-type]

        def complete_progress() -> None:
            if progress_tracker is not None and progress_tracker._current_stage is not None:
                progress_tracker.advance(1.0, "단계 완료")

        def cancellation_result() -> PipelineResult | None:
            nonlocal current, terminal_cleanup
            if cancellation_requested is None or not cancellation_requested(current):
                return None
            cancelled = request_cancellation(current)
            current = transition_job(cancelled, "cancelled")
            current = transition_job(current, "cleaning")
            terminal_cleanup = True
            cleanup_artifacts(current, CleanupPolicy())
            current = transition_job(current, "archived")
            if progress_tracker is not None and not progress_terminal:
                progress_tracker.finish("cancelled", "작업이 취소되었습니다")
            return PipelineResult(job=current)

        try:
            start_progress("source_validation", 1, "입력 확인")
            complete_progress()
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "acquiring")
            start_progress("source_acquisition", 1, "소스 획득")
            result = cancellation_result()
            if result is not None:
                return result

            source_scheme = urlsplit(current.source).scheme.lower()
            acquired: AudioArtifact | None = None
            if source_scheme in {"http", "https"}:
                acquired = acquire_source_audio(current, self.source_adapter)
            complete_progress()
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "extracting")
            start_progress("audio_extraction", 1, "오디오 추출")
            source_path = acquired.path if acquired is not None else current.source
            audio = extract_audio(current, source_path, self.ffmpeg_runner)
            complete_progress()
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "transcribing")
            start_progress("transcription", 1, "전사")
            raw_segments = transcribe_audio(audio, self.stt_engine)
            raw_transcript = assemble_transcript(raw_segments)
            complete_progress()
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "normalizing")
            start_progress("rule_normalization", len(raw_transcript.segments), "텍스트 정규화")
            prepared = []
            for segment in raw_transcript.segments:
                protected = protect_tokens([segment], self.glossary)
                normalized = normalize_rules(protected)
                prepared.append((protected, normalized, segment.segment_id))
            result = cancellation_result()
            if result is not None:
                return result
            if progress_tracker is not None:
                progress_tracker.advance(float(len(prepared)), "정규화 완료")

            current = transition_job(current, "correcting")
            groups = _build_correction_groups(tuple(prepared))
            start_progress("correction", len(groups), "문맥 교정")
            corrections = []
            prior_context: list[str] = []
            correction_runtime = _CorrectionRuntimeAdapter(self.qwen_runtime)
            correction_attempts: list[tuple[CorrectionAttempt, ...]] = []
            identity_group_count = 0
            for group_index, group in enumerate(groups):
                context = tuple(prior_context[-4:])
                outcome = correct_with_retry(group, context, correction_runtime)
                correction_attempts.append(outcome.attempts)
                if outcome.identity_applied:
                    identity_group_count += 1
                replacements = {
                    proposal.editable_id: proposal.replacement
                    for proposal in outcome.edits
                }
                reassembled_parts: list[str] = []
                for plan in group:
                    plan_editable_ids = {
                        part.part_id
                        for part in plan.parts
                        if isinstance(part, EditablePart)
                    }
                    plan_replacements = {
                        part_id: replacements[part_id]
                        for part_id in plan_editable_ids
                        if part_id in replacements
                    }
                    reassembled_parts.append(
                        reassemble_locked_parts(plan, plan_replacements)
                    )
                reassembled_group = tuple(reassembled_parts)
                if "\n".join(reassembled_group) != outcome.text:
                    raise ProtectionError("correction outcome text does not match reassembly")
                for plan, reassembled_text in zip(group, reassembled_group):
                    source = next(
                        item for item in prepared if item[2] == plan.segment_id
                    )
                    protected, normalized, _segment_id = source
                    validation_protected = ProtectedText(
                        normalized.text,
                        dict(protected.replacements),
                    )
                    candidate = _proposal_text_for_validation(
                        plan,
                        validation_protected,
                        replacements,
                    )
                    corrections.append(
                        (
                            protected,
                            normalized,
                            plan,
                            candidate,
                            reassembled_text,
                            outcome,
                        )
                    )
                    prior_context.append(plan.original_text[:2_000])
                if progress_tracker is not None:
                    attempts = len(outcome.attempts)
                    progress_tracker.advance(
                        float(group_index + 1),
                        "교정 그룹 처리 (%d회 시도)" % attempts,
                    )
                result = cancellation_result()
                if result is not None:
                    return result

            current = transition_job(current, "reviewing")
            start_progress("review_validation", len(corrections), "검토 검증")
            approved_texts: list[str] = []
            review_items: tuple[dict[str, str], ...] = ()
            review_locations: tuple[dict[str, object], ...] = ()
            for segment, (
                protected,
                normalized,
                plan,
                candidate,
                _reassembled_text,
                outcome,
            ) in zip(
                raw_transcript.segments,
                corrections,
            ):
                validation_protected = ProtectedText(
                    normalized.text,
                    dict(protected.replacements),
                )
                try:
                    review = validate_revision(
                        normalized.text,
                        candidate,
                        validation_protected,
                    )
                    approved_text = restore_tokens(validation_protected, review.approved_text)
                    segment_review_items = review.review_items
                    segment_spans = review.review_spans
                    if outcome.identity_applied:
                        if not approved_text:
                            raise ReviewMappingError("review_span_range_invalid", segment.segment_id)
                        segment_review_items = segment_review_items + (
                            {
                                "kind": "correction_unapplied",
                                "raw": plan.original_text,
                                "corrected": plan.original_text,
                                "reason": outcome.review_reason or "correction_unapplied",
                            },
                        )
                        segment_spans = segment_spans + (ReviewSpan(0, len(approved_text)),)
                    review_locations = review_locations + _review_locations_from_spans(
                        segment.segment_id,
                        approved_text,
                        segment_review_items,
                        segment_spans,
                        len(review_items),
                    )
                except (ProtectionError, TranscriptAssemblyError) as exc:
                    exc.stage = "review_validation"
                    exc.segment_id = segment.segment_id
                    raise
                approved_texts.append(approved_text)
                review_items = review_items + segment_review_items
                if progress_tracker is not None:
                    progress_tracker.advance(float(len(approved_texts)), "검토 항목 검증")
            try:
                reviewed_transcript = assemble_reviewed_transcript(
                    raw_transcript,
                    approved_texts,
                )
            except TranscriptAssemblyError as exc:
                exc.stage = "review_validation"
                raise
            result = cancellation_result()
            if result is not None:
                return result

            summary: Summary | None = None
            summary_outcome: SummaryOutcome | None = None
            introduction: VideoIntroduction | None = None
            generation_runtime = self.generation_runtime or self.qwen_runtime
            if output_mode in {"summary", "both"}:
                current = transition_job(current, "summarizing")
                start_progress("summarization", 1, "요약 생성")
                summary_result = generate_from_transcript(
                    GenerationRequest(
                        reviewed_transcript,
                        "summary",
                        summary_instruction,
                    ),
                    generation_runtime,
                )
                if not isinstance(summary_result, SummaryOutcome):
                    raise TypeError("summary generation returned an invalid result")
                summary_outcome = summary_result
                if summary_outcome.status == "success":
                    summary = summary_outcome.summary
                complete_progress()
                result = cancellation_result()
                if result is not None:
                    return result
            else:
                # The lifecycle contract has no separate introduction status;
                # reuse the terminal-generation state for introduction-only runs.
                current = transition_job(current, "summarizing")
            if output_mode in {"introduction", "both"}:
                start_progress("introduction", 1, "영상 소개글 생성")
                introduction_result = generate_from_transcript(
                    GenerationRequest(
                        reviewed_transcript,
                        "introduction",
                        introduction_instruction,
                    ),
                    generation_runtime,
                )
                if not isinstance(introduction_result, VideoIntroduction):
                    raise TypeError("introduction generation returned an invalid result")
                introduction = introduction_result
                complete_progress()
                result = cancellation_result()
                if result is not None:
                    return result

            current = transition_job(current, "completed")
            current = transition_job(current, "cleaning")
            terminal_cleanup = True
            cleanup_artifacts(current, CleanupPolicy())
            current = transition_job(current, "archived")
            if progress_tracker is not None:
                progress_tracker.finish("completed", "작업이 완료되었습니다")
                progress_terminal = True
            return PipelineResult(
                job=current,
                transcript=reviewed_transcript,
                summary=summary,
                introduction=introduction,
                review_items=review_items,
                review_locations=review_locations,
                correction_attempts=tuple(correction_attempts),
                identity_group_count=identity_group_count,
                correction_group_count=len(groups),
                review_required_count=len(review_items),
                summary_outcome=summary_outcome,
            )
        except BaseException:
            if progress_tracker is not None and not progress_terminal:
                try:
                    progress_tracker.finish("failed", "작업이 실패했습니다")
                    progress_terminal = True
                except BaseException:
                    pass
            if not terminal_cleanup:
                self._finish_failed(current)
            raise


def _validate_build_inputs(
    source_adapter: SourceAudioAdapter,
    ffmpeg_runner: FfmpegRunner,
    stt_engine: SttEngine,
    qwen_runtime: QwenRuntime,
    glossary: tuple[str, ...],
    generation_runtime: QwenRuntime | None,
) -> None:
    """Validate injected collaborators without calling their external work."""
    if not callable(getattr(source_adapter, "acquire", None)):
        raise TypeError("source_adapter.acquire must be callable")
    if not callable(getattr(ffmpeg_runner, "run", None)):
        raise TypeError("ffmpeg_runner.run must be callable")
    if not callable(getattr(stt_engine, "transcribe", None)):
        raise TypeError("stt_engine.transcribe must be callable")
    if not callable(getattr(qwen_runtime, "complete", None)):
        raise TypeError("qwen_runtime.complete must be callable")
    if generation_runtime is not None and not callable(getattr(generation_runtime, "complete", None)):
        raise TypeError("generation_runtime.complete must be callable")
    if not isinstance(glossary, tuple):
        raise TypeError("glossary must be a tuple[str, ...]")

    seen: set[str] = set()
    for item in glossary:
        if not isinstance(item, str):
            raise TypeError("every glossary item must be a str")
        if not item or item != item.strip():
            raise ProtectionError("glossary items must be non-blank and trimmed")
        if item in seen:
            raise ProtectionError("duplicate glossary item: %r" % (item,))
        seen.add(item)


def build_application(
    *,
    source_adapter: SourceAudioAdapter,
    ffmpeg_runner: FfmpegRunner,
    stt_engine: SttEngine,
    qwen_runtime: QwenRuntime,
    glossary: tuple[str, ...] = (),
    generation_runtime: QwenRuntime | None = None,
) -> PipelineApplication:
    """Return a dependency-injected local pipeline without external setup."""
    _validate_build_inputs(
        source_adapter,
        ffmpeg_runner,
        stt_engine,
        qwen_runtime,
        glossary,
        generation_runtime,
        )
    return PipelineApplication(
        source_adapter=source_adapter,
        ffmpeg_runner=ffmpeg_runner,
        stt_engine=stt_engine,
        qwen_runtime=qwen_runtime,
        glossary=glossary,
        generation_runtime=generation_runtime,
    )


class _SystemClock:
    """Production clock adapter used only when callers request progress events."""

    def monotonic(self) -> float:
        return time.monotonic()

    def utc_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
