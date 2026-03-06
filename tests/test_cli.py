from __future__ import annotations

from pathlib import Path

import pytest

from git_statuz.cli import main, resolve_input_repo
from git_statuz.git_adapter import GitCommandError
from tests.conftest import commit_file, init_repo


def test_resolve_input_repo_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_file(repo, "a.txt", "hello", "init")
    monkeypatch.chdir(repo)

    resolved = resolve_input_repo(None)
    assert Path(resolved) == repo


def test_resolve_input_repo_invalid_path_raises(tmp_path: Path) -> None:
    invalid = tmp_path / "missing"
    with pytest.raises(GitCommandError):
        resolve_input_repo(str(invalid))


def test_resolve_input_repo_valid_path(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_file(repo, "a.txt", "hello", "init")

    resolved = resolve_input_repo(str(repo))
    assert Path(resolved) == repo


def test_main_exits_nonzero_for_invalid_repo(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["-i", str(tmp_path / "not-a-repo")])
    assert exc_info.value.code == 2

