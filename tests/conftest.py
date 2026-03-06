from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QSettings

if TYPE_CHECKING:
    from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run_git(repo_path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git command failed: {' '.join(args)}")
    return proc.stdout.strip()


def init_repo(repo_path: Path) -> Path:
    repo_path.mkdir(parents=True, exist_ok=True)
    run_git(repo_path, "init")
    run_git(repo_path, "config", "user.email", "test@example.com")
    run_git(repo_path, "config", "user.name", "Test User")
    return repo_path


def commit_file(repo_path: Path, relpath: str, content: str, message: str) -> None:
    abs_path = repo_path / relpath
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    run_git(repo_path, "add", relpath)
    run_git(repo_path, "commit", "-m", message)


@pytest.fixture
def window(qtbot, tmp_path: Path, monkeypatch):
    from git_statuz.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_request_repo_diff", lambda self: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(str(tmp_path), settings=settings)
    qtbot.addWidget(win)
    return win
