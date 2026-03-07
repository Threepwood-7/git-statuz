from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from pathlib import Path


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        raise RuntimeError(stderr or stdout or "git command failed")
    return proc.stdout


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run_git(path.parent if path.name else path, "init", "-b", "main", str(path))
    run_git(path, "config", "user.name", "Test User")
    run_git(path, "config", "user.email", "test@example.invalid")
    return path


def commit_file(repo: Path, rel_path: str, content: str, message: str) -> Path:
    file_path = repo / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    run_git(repo, "add", rel_path)
    run_git(repo, "commit", "-m", message)
    return file_path


@pytest.fixture
def window(qtbot: object) -> QWidget:
    widget = QWidget()
    add_widget = qtbot.addWidget
    add_widget(widget)
    widget.show()
    yield widget
    widget.close()
