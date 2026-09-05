"""Unit tests for V2-R01 runtime profile selection and persistence."""

import json
from pathlib import Path

import pytest

from backend.contracts import RuntimeProfile
from backend.runtime_profile import (
    default_runtime_profile,
    evaluate_runtime_readiness,
    load_runtime_profile,
    save_runtime_profile,
)


def test_default_profiles_select_quality_qwen_without_io() -> None:
    windows = default_runtime_profile("Windows")
    linux = default_runtime_profile("linux")
    darwin = default_runtime_profile("darwin")
    assert windows.qwen_model == "qwen3.6:35b-a3b-agent-64k"
    assert linux.qwen_model == windows.qwen_model == darwin.qwen_model
    assert windows.ollama_endpoint == "http://127.0.0.1:11434/api/chat"
    with pytest.raises(ValueError):
        default_runtime_profile("plan9")


def test_profile_json_round_trip_and_atomic_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "config" / "runtime.json"
    profile = RuntimeProfile(
        "quality",
        "qwen3.6:35b-a3b-agent-64k",
        tmp_path / "stt",
        Path("ffmpeg.exe"),
        "http://127.0.0.1:11434/api/chat",
        4096,
    )
    assert save_runtime_profile(profile, path) == path
    assert load_runtime_profile(path) == profile
    save_runtime_profile(profile, path)
    assert not list(path.parent.glob("*.partial"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"extra": True}),
        lambda value: value.pop("qwen_model"),
        lambda value: value.update({"ollama_endpoint": "https://example.com/api/chat"}),
        lambda value: value.update({"qwen_context_tokens": 512}),
    ],
)
def test_invalid_profile_json_is_rejected(tmp_path: Path, mutate) -> None:
    profile = default_runtime_profile("windows")
    payload = {
        "profile_name": profile.profile_name,
        "qwen_model": profile.qwen_model,
        "stt_model_path": str(profile.stt_model_path),
        "ffmpeg_path": str(profile.ffmpeg_path),
        "ollama_endpoint": profile.ollama_endpoint,
        "qwen_context_tokens": profile.qwen_context_tokens,
    }
    mutate(payload)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((TypeError, ValueError)):
        load_runtime_profile(path)


def test_profile_rejects_non_profile_and_symlink_paths(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        save_runtime_profile(object(), tmp_path / "runtime.json")  # type: ignore[arg-type]
    path = tmp_path / "runtime.json"
    path.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this Windows host")
    with pytest.raises(ValueError):
        load_runtime_profile(link)


def test_readiness_reports_each_runtime_dependency_independently(tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"fixture")
    stt = tmp_path / "stt"
    stt.mkdir()
    profile = RuntimeProfile(
        "quality",
        "qwen3.6:35b-a3b-agent-64k",
        stt,
        ffmpeg,
        "http://127.0.0.1:11434/api/chat",
        4096,
    )
    readiness = evaluate_runtime_readiness(
        profile,
        python_ready=True,
        ollama_ready=True,
        qwen_model_ready=False,
    )
    assert readiness.ffmpeg_ready is True
    assert readiness.stt_model_ready is True
    assert readiness.is_ready is False
    assert readiness.required_actions == ("qwen3.6:35b-a3b-agent-64k 모델 준비",)


def test_readiness_flags_require_booleans_without_side_effects(tmp_path: Path) -> None:
    profile = default_runtime_profile("linux")
    with pytest.raises(TypeError):
        evaluate_runtime_readiness(
            profile,
            python_ready=1,  # type: ignore[arg-type]
            ollama_ready=False,
            qwen_model_ready=False,
        )
