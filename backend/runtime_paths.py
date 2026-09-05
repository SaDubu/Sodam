"""Shared per-user paths, configurable before starting Sodam."""

import os
from pathlib import Path


DATA_ROOT = Path(os.environ.get("SODAM_DATA_ROOT") or Path.home() / "Sodam-data").expanduser().resolve()
JOB_WORK_ROOT = DATA_ROOT / "tmp" / "jobs"
RESULT_ROOT = Path(os.environ.get("SODAM_RESULT_ROOT") or DATA_ROOT / "jobs").expanduser().resolve()
STT_MODEL_PATH = Path(os.environ.get("SODAM_STT_MODEL") or DATA_ROOT / "models" / "faster-whisper-turbo").expanduser().resolve()
