"""Injected local job-pipeline composition and orchestration."""

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .contracts import (
    AudioArtifact,
    Job,
    JobStateError,
    ProtectionError,
    ReviewedTranscript,
    Summary,
)
from .correction import QwenRuntime, correct_chunk
from .jobs import request_cancellation, transition_job
from .media import FfmpegRunner, extract_audio
from .protection import protect_tokens, restore_tokens
from .sources import SourceAudioAdapter, acquire_source_audio
from .storage import CleanupPolicy, assemble_reviewed_transcript, assemble_transcript, cleanup_artifacts
from .summarization import summarize_reviewed_transcript
from .text_rules import normalize_rules
from .transcription import SttEngine, transcribe_audio
from .validation import validate_revision


@dataclass(frozen=True)
class PipelineResult:
    """Terminal result of one local pipeline run."""

    job: Job
    transcript: ReviewedTranscript | None = None
    summary: Summary | None = None
    review_items: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class PipelineApplication:
    """A pipeline that uses only dependencies provided by its caller."""

    source_adapter: SourceAudioAdapter
    ffmpeg_runner: FfmpegRunner
    stt_engine: SttEngine
    qwen_runtime: QwenRuntime
    glossary: tuple[str, ...] = ()

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
        cancellation_requested: Callable[[Job], bool] | None = None,
    ) -> PipelineResult:
        """Process one queued job through acquisition, review, and summary."""
        if not isinstance(job, Job):
            raise TypeError("job must be a Job")
        if job.status != "queued":
            raise JobStateError("pipeline jobs must start in queued status")
        if cancellation_requested is not None and not callable(cancellation_requested):
            raise TypeError("cancellation_requested must be callable or None")

        current = job
        terminal_cleanup = False

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
            return PipelineResult(job=current)

        try:
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "acquiring")
            result = cancellation_result()
            if result is not None:
                return result

            source_scheme = urlsplit(current.source).scheme.lower()
            acquired: AudioArtifact | None = None
            if source_scheme in {"http", "https"}:
                acquired = acquire_source_audio(current, self.source_adapter)
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "extracting")
            source_path = acquired.path if acquired is not None else current.source
            audio = extract_audio(current, source_path, self.ffmpeg_runner)
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "transcribing")
            raw_segments = transcribe_audio(audio, self.stt_engine)
            raw_transcript = assemble_transcript(raw_segments)
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "normalizing")
            prepared = []
            for segment in raw_transcript.segments:
                protected = protect_tokens([segment], self.glossary)
                prepared.append((protected, normalize_rules(protected)))
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "correcting")
            corrections = []
            for index, (protected, normalized) in enumerate(prepared):
                context = tuple(item[1].text for item in prepared[max(0, index - 4) : index])
                corrections.append(
                    (protected, normalized, correct_chunk(normalized, context, self.qwen_runtime))
                )
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "reviewing")
            approved_texts: list[str] = []
            review_items: tuple[dict[str, str], ...] = ()
            for protected, normalized, correction in corrections:
                review = validate_revision(
                    normalized.text,
                    correction.corrected_text,
                    protected,
                )
                approved_texts.append(restore_tokens(protected, review.approved_text))
                review_items = review_items + review.review_items
            reviewed_transcript = assemble_reviewed_transcript(
                raw_transcript,
                approved_texts,
            )
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "summarizing")
            summary = summarize_reviewed_transcript(reviewed_transcript, self.qwen_runtime)
            result = cancellation_result()
            if result is not None:
                return result

            current = transition_job(current, "completed")
            current = transition_job(current, "cleaning")
            terminal_cleanup = True
            cleanup_artifacts(current, CleanupPolicy())
            current = transition_job(current, "archived")
            return PipelineResult(
                job=current,
                transcript=reviewed_transcript,
                summary=summary,
                review_items=review_items,
            )
        except BaseException:
            if not terminal_cleanup:
                self._finish_failed(current)
            raise


def _validate_build_inputs(
    source_adapter: SourceAudioAdapter,
    ffmpeg_runner: FfmpegRunner,
    stt_engine: SttEngine,
    qwen_runtime: QwenRuntime,
    glossary: tuple[str, ...],
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
) -> PipelineApplication:
    """Return a dependency-injected local pipeline without external setup."""
    _validate_build_inputs(
        source_adapter,
        ffmpeg_runner,
        stt_engine,
        qwen_runtime,
        glossary,
    )
    return PipelineApplication(
        source_adapter=source_adapter,
        ffmpeg_runner=ffmpeg_runner,
        stt_engine=stt_engine,
        qwen_runtime=qwen_runtime,
        glossary=glossary,
    )
