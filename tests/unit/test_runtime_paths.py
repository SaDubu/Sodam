"""Check fresh-process settings so a different PC never needs the author's drives."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("custom", [False, True])
def test_runtime_paths_agree_across_pipeline_and_ui(tmp_path, custom):
    env = os.environ.copy()
    for key in ("SODAM_DATA_ROOT", "SODAM_RESULT_ROOT", "SODAM_STT_MODEL"):
        env.pop(key, None)
    if custom:
        env.update(SODAM_DATA_ROOT=str(tmp_path / "data"), SODAM_RESULT_ROOT=str(tmp_path / "results"), SODAM_STT_MODEL=str(tmp_path / "model"))
    command = """
import json, sys
from backend.runtime_paths import DATA_ROOT, JOB_WORK_ROOT, RESULT_ROOT, STT_MODEL_PATH
from backend.jobs import _WORK_DIR_ROOT
from backend.storage import JOB_WORK_ROOT as storage_root
from backend.persistence import RESULT_ROOT as persistence_root
from backend.local_adapters import DEFAULT_YTDLP_PYTHON
from tools.gui_runner import RESULT_ROOT as gui_root
from tools.run_local import DEFAULT_MODEL_PATH
assert _WORK_DIR_ROOT == storage_root == JOB_WORK_ROOT
assert persistence_root == gui_root == RESULT_ROOT
assert DEFAULT_MODEL_PATH == STT_MODEL_PATH
assert DEFAULT_YTDLP_PYTHON == sys.executable
print(json.dumps([str(DATA_ROOT), str(RESULT_ROOT), str(STT_MODEL_PATH)]))
"""
    result = subprocess.run([sys.executable, "-B", "-c", command], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, check=True)
    data, results, model = map(Path, json.loads(result.stdout))
    assert data == (tmp_path / "data" if custom else Path.home() / "Sodam-data").resolve()
    assert results == (tmp_path / "results" if custom else data / "jobs").resolve()
    assert model == (tmp_path / "model" if custom else data / "models" / "faster-whisper-turbo").resolve()
    assert not (tmp_path / "data").exists()


def test_worker_passes_selected_result_root_to_child(tmp_path):
    import io
    from tools.gui_runner import RunRequest, SourceSpec, stream_process

    captured = {}
    class Process:
        stdout = io.BytesIO(b"{}")
        stderr = io.BytesIO(b"")
        def wait(self):
            return 0
    def factory(argv, **kwargs):
        captured.update(kwargs)
        return Process()
    events = []
    stream_process([sys.executable], tmp_path, events.append, request=RunRequest(SourceSpec("local", "fixture.mp4")), result_root=tmp_path / "chosen", process_factory=factory)
    assert captured["env"]["SODAM_RESULT_ROOT"] == str((tmp_path / "chosen").resolve())
    assert [event.kind for event in events] == ["error", "exited"]
