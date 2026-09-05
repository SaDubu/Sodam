"""Static contracts for the personal PowerShell launcher.

These tests never run PowerShell, Ollama, the desktop executable, or a model.
They only inspect the launcher source so local setup remains an explicit manual
action.
"""

from __future__ import annotations

from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[2] / "tools" / "start_desktop.ps1"
ROOT = LAUNCHER.parents[1]
README = ROOT / "README.md"


def _source() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def test_launcher_declares_portable_runtime_parameters_and_exact_model_tag() -> None:
    source = _source()
    for parameter in (
        "RepositoryRoot",
        "PythonPath",
        "FfmpegPath",
        "SttModelPath",
        "DesktopExecutable",
        "OllamaExecutable",
        "QwenModel",
    ):
        assert f"[string]$" + parameter in source
    assert "qwen3.6:35b-a3b-agent-64k" in source
    assert "apps/desktop/src-tauri/target/debug/sodam-desktop.exe" in source


def test_launcher_scopes_runtime_values_to_the_desktop_child_only() -> None:
    source = _source()
    assert "$startInfo.UseShellExecute = $false" in source
    assert "$startInfo.WorkingDirectory = $resolvedRepositoryRoot" in source
    for key in (
        "SODAM_REPOSITORY_ROOT",
        "SODAM_PYTHON",
        "SODAM_FFMPEG",
        "SODAM_MODEL_PATH",
    ):
        assert f'$startInfo.Environment["{key}"]' in source
        assert f"$env:{key}" not in source


def test_launcher_only_checks_ollama_and_never_installs_or_removes_software() -> None:
    source = _source()
    assert "& $Executable list" in source
    assert "ollama pull " in source
    assert "ProcessStartInfo" in source
    for forbidden in (
        "ollama pull $QwenModel",
        " install ",
        " uninstall ",
        "Remove-Item",
        "Invoke-WebRequest",
        "Start-BitsTransfer",
    ):
        assert forbidden not in source


def test_launcher_uses_safe_error_categories_and_validates_paths() -> None:
    source = _source()
    assert "SODAM_LAUNCHER_INPUT" in source
    assert "SODAM_LAUNCHER_RUNTIME" in source
    assert "Resolve-ExistingFile" in source
    assert "Resolve-ExistingDirectory" in source
    assert "Test-ChildPath" in source


def test_personal_use_document_links_launcher_and_exact_manual_model_steps() -> None:
    document = README.read_text(encoding="utf-8")
    assert "docs/personal-use.md" not in document
    assert "ollama pull qwen3.6:35b-a3b" in document
    assert "ollama create qwen3.6:35b-a3b-agent-64k" in document
    assert "ollama list" in document
    assert "start_simple_gui.ps1" in document
    for parameter in ("PythonPath", "HermesCommand", "HermesPython", "HermesRoot"):
        assert parameter in document


def test_personal_use_document_keeps_installation_manual_and_data_outside_git() -> None:
    document = README.read_text(encoding="utf-8")
    assert "py -3.12 -m venv .venv" in document
    assert "pip install -r requirements.txt" in document
    assert "hermes-agent==0.19.0" in document
    assert "SODAM_DATA_ROOT" in document
    assert ".local/work-docs/" in document
    for forbidden in ("Invoke-WebRequest", "Start-BitsTransfer", "irm ", "curl "):
        assert forbidden not in document
