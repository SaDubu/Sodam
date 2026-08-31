import importlib.util
from pathlib import Path


_PATH = Path(__file__).resolve().parents[2] / "tools" / "doctor.py"
_SPEC = importlib.util.spec_from_file_location("doctor", _PATH)
doctor = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(doctor)


class FakeProbe(doctor.SystemProbe):
    def __init__(self, missing: str = "") -> None: self.missing = missing
    def executable(self, name: str) -> bool: return name != self.missing
    def command(self, *arguments: str) -> tuple[bool, str]: return (False, "missing") if arguments[0] == self.missing else (True, "qwen3.6:35b-a3b-agent-64k")
    def path_state(self, path: Path, writable: bool = False) -> bool: return self.missing != "data"


def _config(tmp_path: Path) -> doctor.DoctorConfig:
    runtime = tmp_path / "python.exe"; runtime.write_text("")
    snapshot = tmp_path / "snapshot"; snapshot.mkdir()
    for name in ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json"): (snapshot / name).write_text("")
    data = tmp_path / "data"; data.mkdir()
    return doctor.DoctorConfig(runtime, snapshot, data, "qwen3.6:35b-a3b-agent-64k")


def test_ready_report_has_stable_schema(tmp_path: Path) -> None:
    report = doctor.collect_diagnostics(_config(tmp_path), FakeProbe())
    assert set(report) == {"is_ready", "checks", "required_actions"}
    assert report["is_ready"] is True and report["required_actions"] == []


def test_missing_dependency_is_reported(tmp_path: Path) -> None:
    report = doctor.collect_diagnostics(_config(tmp_path), FakeProbe("ffmpeg"))
    assert report["is_ready"] is False
    assert report["required_actions"] == ["resolve ffmpeg"]


def test_explicit_ffmpeg_path_is_preferred_over_path_probe(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_text("")
    config = doctor.DoctorConfig(config.runtime_python, config.stt_snapshot, config.data_root, config.qwen_model, ffmpeg)
    report = doctor.collect_diagnostics(config, FakeProbe("ffmpeg"))
    assert report["checks"]["ffmpeg"] == {"ok": True, "detail": str(ffmpeg)}


def test_relative_explicit_ffmpeg_path_is_not_ready(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = doctor.DoctorConfig(config.runtime_python, config.stt_snapshot, config.data_root, config.qwen_model, Path("ffmpeg.exe"))
    report = doctor.collect_diagnostics(config, FakeProbe("ffmpeg"))
    assert report["checks"]["ffmpeg"]["ok"] is False
