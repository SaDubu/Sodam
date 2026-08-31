"""Export raw local Whisper segments for an explicitly supplied local media file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.contracts import CleanupPolicy, Job, JobOptions
from backend.local_adapters import LocalFasterWhisperEngine, LocalFfmpegRunner
from backend.media import extract_audio
from backend.storage import cleanup_artifacts
from backend.transcription import transcribe_audio


DEFAULT_MODEL_PATH = Path(r"D:\AI-Legion\Sodam-models\faster-whisper\turbo-0a363e9")
DEFAULT_WORK_DIR = Path(r"D:\AI-Legion\Sodam-data\tmp\jobs\p06-whisper-capture")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()

    source = args.source.expanduser().resolve(strict=True)
    job = Job("p06-whisper-capture", str(source), "queued", DEFAULT_WORK_DIR, JobOptions())
    try:
        audio = extract_audio(job, source, LocalFfmpegRunner())
        segments = transcribe_audio(audio, LocalFasterWhisperEngine(args.model_path))
        print(
            json.dumps(
                [
                    {
                        "id": item.segment_id,
                        "start": item.start_seconds,
                        "end": item.end_seconds,
                        "text": item.raw_text,
                    }
                    for item in segments
                ],
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        cleanup_artifacts(job, CleanupPolicy())


if __name__ == "__main__":
    raise SystemExit(main())
