"""Unit tests for the O01 injected, checksum-verified model installer."""

import hashlib
import json
from pathlib import Path
import subprocess


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "setup-models.ps1"
_MANIFEST = _ROOT / "models" / "manifest.json"


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _manifest(filename: str, sha256: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "profiles": [
            {
                "name": "fixture",
                "files": [
                    {
                        "filename": filename,
                        "url": "https://example.invalid/fixture-model.bin",
                        "sha256": sha256,
                    }
                ],
            }
        ],
    }


def _run_install(
    manifest_path: Path,
    model_home: Path,
    source_path: Path,
    profile: str = "fixture",
) -> subprocess.CompletedProcess[str]:
    command = (
        "& { "
        "$ErrorActionPreference = 'Stop'; "
        f". {_ps_quote(_SCRIPT)}; "
        f"$source = {_ps_quote(source_path)}; "
        "$copy = { param($url, $destination) "
        "Copy-Item -LiteralPath $source -Destination $destination -ErrorAction Stop }; "
        f"$result = Install-SodamModels -Profile {_ps_quote(profile)} "
        f"-ModelHome {_ps_quote(model_home)} -ManifestPath {_ps_quote(manifest_path)} "
        "-DownloadFile $copy; "
        "$result | ConvertTo-Json -Compress "
        "}"
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        text=True,
        capture_output=True,
        check=False,
    )


def test_injected_copy_downloader_installs_a_verified_file(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"fixture model bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(_manifest("fixture-model.bin", hashlib.sha256(source.read_bytes()).hexdigest())),
        encoding="utf-8",
    )
    model_home = tmp_path / "models"

    completed = _run_install(manifest, model_home, source)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    installed = model_home / "fixture-model.bin"
    assert result["profile"] == "fixture"
    assert Path(result["model_home"]) == model_home.resolve()
    assert result["installed_files"] == [str(installed)]
    assert installed.read_bytes() == b"fixture model bytes"
    assert not list(model_home.glob("*.partial"))


def test_invalid_paths_profiles_checksums_and_existing_targets_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"fixture model bytes")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest("fixture-model.bin", checksum)), encoding="utf-8")

    inside_repository = _run_install(manifest, _ROOT / "models", source)
    assert inside_repository.returncode != 0

    traversal = tmp_path / "traversal.json"
    traversal.write_text(json.dumps(_manifest("../escape.bin", checksum)), encoding="utf-8")
    traversal_home = tmp_path / "traversal-home"
    assert _run_install(traversal, traversal_home, source).returncode != 0
    assert not traversal_home.exists()

    unknown_home = tmp_path / "unknown-home"
    assert _run_install(manifest, unknown_home, source, profile="missing").returncode != 0
    assert not unknown_home.exists()

    wrong_hash = tmp_path / "wrong-hash.json"
    wrong_hash.write_text(json.dumps(_manifest("fixture-model.bin", "0" * 64)), encoding="utf-8")
    wrong_home = tmp_path / "wrong-home"
    assert _run_install(wrong_hash, wrong_home, source).returncode != 0
    assert not (wrong_home / "fixture-model.bin").exists()
    assert not list(wrong_home.glob("*.partial"))

    existing_home = tmp_path / "existing-home"
    existing_home.mkdir()
    existing_target = existing_home / "fixture-model.bin"
    existing_target.write_bytes(b"do not overwrite")
    assert _run_install(manifest, existing_home, source).returncode != 0
    assert existing_target.read_bytes() == b"do not overwrite"


def test_default_downloader_is_not_reached_for_an_unknown_default_profile(tmp_path: Path) -> None:
    model_home = tmp_path / "not-created"
    completed = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_SCRIPT),
            "-Profile", "missing", "-ModelHome", str(model_home),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert not model_home.exists()


def test_declaration_manifest_uses_schema_one_with_no_selected_models() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert manifest == {"schema_version": "1", "profiles": []}
