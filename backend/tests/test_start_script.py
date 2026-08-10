from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from cryptography.fernet import Fernet


PROJECT_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = PROJECT_ROOT / "scripts" / "start.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


def test_initialize_creates_valid_secret_without_printing_it(tmp_path: Path) -> None:
    root = _project_fixture(tmp_path)

    result = _run_start(root)

    assert result.returncode == 0, result.stderr
    secret = _env_value(root, "SETTINGS_ENCRYPTION_KEY")
    Fernet(secret)
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_initialize_reuses_existing_secret(tmp_path: Path) -> None:
    root = _project_fixture(tmp_path)
    first = _run_start(root)
    assert first.returncode == 0, first.stderr
    original = _env_value(root, "SETTINGS_ENCRYPTION_KEY")

    second = _run_start(root)

    assert second.returncode == 0, second.stderr
    assert _env_value(root, "SETTINGS_ENCRYPTION_KEY") == original


def test_initialize_rejects_invalid_existing_secret_without_overwriting_it(
    tmp_path: Path,
) -> None:
    root = _project_fixture(tmp_path)
    invalid = "not-a-fernet-key"
    (root / ".env").write_text(
        f"SETTINGS_ENCRYPTION_KEY={invalid}\nFRONTEND_PORT=3000\nBACKEND_PORT=8000\n",
        encoding="utf-8",
    )

    result = _run_start(root)

    assert result.returncode != 0
    assert _env_value(root, "SETTINGS_ENCRYPTION_KEY") == invalid
    assert invalid not in result.stdout
    assert invalid not in result.stderr


def test_initialize_refuses_unignored_env_file(tmp_path: Path) -> None:
    root = _project_fixture(tmp_path, ignore_env=False)

    result = _run_start(root)

    assert result.returncode != 0
    assert not (root / ".env").exists()
    assert "not ignored" in result.stderr.lower()


def test_initialize_refuses_tracked_env_file(tmp_path: Path) -> None:
    root = _project_fixture(tmp_path)
    (root / ".env").write_text(
        "SETTINGS_ENCRYPTION_KEY=\nFRONTEND_PORT=3000\nBACKEND_PORT=8000\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-f", ".env"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    result = _run_start(root)

    assert result.returncode != 0
    assert "tracked by git" in result.stderr.lower()


def _project_fixture(tmp_path: Path, *, ignore_env: bool = True) -> Path:
    assert POWERSHELL is not None, "Windows PowerShell is required for this test"
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(START_SCRIPT, scripts / "start.ps1")
    shutil.copy2(PROJECT_ROOT / ".env.example", root / ".env.example")
    (root / ".gitignore").write_text(".env\n" if ignore_env else ".tmp\n", encoding="utf-8")
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return root


def _run_start(root: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("SETTINGS_ENCRYPTION_KEY", None)
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "scripts" / "start.ps1"),
            "-InitializeOnly",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _env_value(root: Path, name: str) -> str:
    prefix = f"{name}="
    for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    raise AssertionError(f"{name} missing from .env")
