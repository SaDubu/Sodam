"""Local-media validation and audio-normalization contract."""

from pathlib import Path
from typing import Protocol, Sequence

from .contracts import (
    AudioArtifact,
    InputSourceError,
    Job,
    MediaExtractionError,
    SodamError,
    UnsafePathError,
)
from .storage import _validate_job_work_dir


class FfmpegRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> None:
        """Run a prevalidated FFmpeg argument vector or raise an exception."""


_SUPPORTED_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".mov", ".webm",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
})


def extract_audio(
    job: Job,
    source_path: str | Path,
    runner: FfmpegRunner,
) -> AudioArtifact:
    """Extract normalized WAV audio from a local media file.

    Validation order (Section 5):
        1. Type checks for job/runner/source_path
        2. Source file system queries (symlink first, then others)
        3. work-dir validation via _validate_job_work_dir(job)
        4. Work directory creation
        5. Output path calculation with overwrite/symlink guard
        6. Source resolve and same-path guard
        7. runner.run() call (exactly once)
        8. output existence/type/size/boundary verification
        9. Return AudioArtifact

    Raises:
        TypeError: for invalid job/runner/source_path types.
        InputSourceError: for source validation failures.
        UnsafePathError: for overwrite/symlink/policy violations.
        MediaExtractionError: for extraction/failure errors.
    """
    # ---- 1. type checks ------------------------------------------
    if not isinstance(job, Job):
        raise TypeError("job must be a Job")

    if not callable(getattr(runner, "run", None)):
        raise TypeError(
            f"runner must have a 'run' callable; got {type(runner).__name__}"
        )

    # ---- 2. source_path validation ---------------------------------
    if not isinstance(source_path, (str, Path)):
        raise InputSourceError("source_path must be str or Path")

    try:
        src = Path(source_path)
    except Exception as exc:
        raise InputSourceError(str(exc)) from exc

    ext = src.suffix.lower()
    if not ext or ext not in _SUPPORTED_EXTENSIONS:
        raise InputSourceError(
            f"unsupported or empty file extension: {ext!r}"
        )

    # symlink 판정 먼저 (SoA Section 8: symlink를 다른 파일 시스템 조회보다 먼저 검사)
    # ValueError도 반드시 InputSourceError로 변환 (user request)
    try:
        is_link = src.is_symlink()
    except (OSError, ValueError) as exc:
        raise InputSourceError(str(exc)) from exc

    if is_link:
        raise InputSourceError("source must not be a symlink")

    # source filesystem 조회 (OSError/ValueError -> InputSourceError)
    try:
        is_exist = src.exists()
        is_file_ = src.is_file()
    except (OSError, ValueError) as exc:
        raise InputSourceError(str(exc)) from exc

    if not is_file_:
        reason = "source must be a regular file"
        if not is_exist:
            reason = f"source does not exist: {src!r}"
        else:
            reason += (
                f", not a directory or other special file: {src!r}"
            )
        raise InputSourceError(reason)

    # ---- 3. work-dir validation (B03) -------------------------------
    _validate_job_work_dir(job)

    # ---- 4. Work dir creation -------------------------------------
    try:
        work = Path(job.work_dir)
        work.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MediaExtractionError(str(exc)) from exc

    # ---- 5. Output path + overwrite/symlink guard -------------------
    output_path = work / "normalized-audio.wav"

    # IMPORTANT: is_symlink()를 exists()보다 먼저 실행 (user B05 request)
    try:
        is_out_link = output_path.is_symlink()
    except OSError as exc:
        raise MediaExtractionError(str(exc)) from exc

    if is_out_link:
        raise UnsafePathError(
            f"output path is a symlink, refusing to follow: {output_path!r}"
        )

    # 그 다음에 exists() 확인
    try:
        has_out = output_path.exists()
    except OSError as exc:
        raise MediaExtractionError(str(exc)) from exc

    if has_out:
        raise UnsafePathError(
            f"output already exists, refusing to overwrite: {output_path!r}"
        )

    # ---- 6. source resolve + same-path guard ------------------------
    try:
        source_resolved = src.resolve()
    except OSError as exc:
        raise InputSourceError(str(exc)) from exc

    if source_resolved == output_path.resolve():
        raise UnsafePathError(
            "source and output resolve to the same path"
        )

    # ---- 7. runner.call (exactly once) ----------------------------
    arguments = [
        "-i", str(source_resolved),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-sample_fmt", "s16",
        str(output_path),
    ]

    try:
        runner.run(arguments)
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        raise MediaExtractionError(str(exc)) from exc

    # ---- 8. output verification (request order: symlink, exists, is_file, stat/resolve/boundary) --
    # Step A: symlink first (before other filesystem queries)
    try:
        out_is_link = output_path.is_symlink()
    except OSError as exc:
        raise MediaExtractionError(str(exc)) from exc

    if out_is_link:
        raise UnsafePathError(
            f"output became a symlink after runner call: {output_path!r}"
        )

    # Step B: existence check
    try:
        out_exist = output_path.exists()
    except OSError as exc:
        raise MediaExtractionError(str(exc)) from exc

    if not out_exist:
        raise MediaExtractionError(
            f"output missing after extraction: {output_path!r}"
        )

    # Step C: is_file verification
    try:
        out_is_file = output_path.is_file()
    except OSError as exc:
        raise MediaExtractionError(str(exc)) from exc

    if not out_is_file:
        raise MediaExtractionError(
            f"output is not a regular file: {output_path!r}"
        )

    # Step D: stat, resolve, boundary checks
    try:
        out_size = output_path.stat().st_size
        out_resolved = output_path.resolve()
        work_resolved = work.resolve()
        esc = out_resolved.is_relative_to(work_resolved)
    except (OSError, ValueError) as exc:
        raise MediaExtractionError(str(exc)) from exc

    if out_size == 0:
        raise MediaExtractionError(
            f"output file is zero bytes: {output_path!r}"
        )

    if not esc:
        raise UnsafePathError(
            f"output escaped work directory: {out_resolved!r}"
        )

    # ---- 9. return --------------------------------------------------
    return AudioArtifact(
        job_id=job.job_id,
        path=output_path.resolve(),
        duration_seconds=None,
    )
