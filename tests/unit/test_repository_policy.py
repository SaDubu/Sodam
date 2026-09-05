"""Unit tests for the O02 read-only Git-path repository policy checker."""

import hashlib
import json
from pathlib import Path
import subprocess


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check-repository-clean.ps1"


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_check(repository: Path, paths: list[str], max_bytes: int = 10_485_760) -> subprocess.CompletedProcess[str]:
    path_list = ", ".join(_ps_quote(path) for path in paths)
    command = (
        "& { "
        "$ErrorActionPreference = 'Stop'; "
        f". {_ps_quote(_SCRIPT)}; "
        f"$paths = @({path_list}); "
        "$provider = { param($root) $paths }; "
        f"$result = Test-SodamRepositoryClean -RepositoryRoot {_ps_quote(repository)} "
        f"-MaxFileBytes {max_bytes} -GitPathProvider $provider; "
        "$result | ConvertTo-Json -Compress -Depth 3 "
        "}"
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        text=True,
        capture_output=True,
        check=False,
    )


def test_safe_duplicate_git_paths_produce_one_clean_checked_file(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "safe.py").write_text("print('safe')\n", encoding="utf-8")

    completed = _run_check(repository, ["safe.py", "safe.py"])

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["is_clean"] is True
    assert report["checked_files"] == 1
    assert report["violations"] == []


def test_policy_reports_extensions_models_size_secrets_and_path_escape(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "video.mp3").write_bytes(b"media")
    (repository / "models").mkdir()
    (repository / "models" / "custom.json").write_text("{}", encoding="utf-8")
    (repository / "big.txt").write_text("01234567890", encoding="utf-8")
    (repository / "secret.txt").write_text(
        'api' + '_key = "12345678"',
        encoding="utf-8",
    )

    completed = _run_check(
        repository,
        ["video.mp3", "models/custom.json", "big.txt", "secret.txt", "../escape.txt"],
        max_bytes=10,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    reasons = {(item["path"], item["reason"]) for item in report["violations"]}
    assert ("video.mp3", "prohibited_extension:.mp3") in reasons
    assert ("models/custom.json", "unexpected_models_path") in reasons
    assert ("big.txt", "file_exceeds_size_limit") in reasons
    assert ("secret.txt", "secret_pattern") in reasons
    assert ("../escape.txt", "unsafe_path") in reasons


def test_invalid_root_and_non_positive_size_are_terminating_errors(tmp_path: Path) -> None:
    missing = _run_check(tmp_path / "missing", ["safe.py"])
    assert missing.returncode != 0

    repository = tmp_path / "repo"
    repository.mkdir()
    invalid_size = _run_check(repository, [], max_bytes=0)
    assert invalid_size.returncode != 0


def test_inspection_does_not_modify_provider_files(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    artifact = repository / "safe.txt"
    artifact.write_text("read only", encoding="utf-8")
    before = hashlib.sha256(artifact.read_bytes()).digest()

    completed = _run_check(repository, ["safe.txt"])

    assert completed.returncode == 0, completed.stderr
    assert hashlib.sha256(artifact.read_bytes()).digest() == before


def test_private_work_documents_are_rejected_but_model_recipe_is_allowed(tmp_path: Path) -> None:
    paths = [".local/work-docs/note.md", "docs/ai/plan.md", "AGENTS.md", "Statement_of_Functions.md", "models/Modelfile.qwen"]
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    completed = _run_check(tmp_path, paths)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert {(item["path"], item["reason"]) for item in report["violations"]} == {
        (path, "private_work_document") for path in paths[:-1]
    }
