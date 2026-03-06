from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


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

