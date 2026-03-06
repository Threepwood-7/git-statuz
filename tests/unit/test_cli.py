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


@pytest.mark.parametrize("valid_repo", [False, True])
def test_resolve_input_repo_path_validation(valid_repo: bool, tmp_path: Path) -> None:
    target = tmp_path / "repo"
    if valid_repo:
        init_repo(target)
        commit_file(target, "a.txt", "hello", "init")
        assert Path(resolve_input_repo(str(target))) == target
    else:
        with pytest.raises(GitCommandError):
            resolve_input_repo(str(target))


def test_main_exits_nonzero_for_invalid_repo(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["-i", str(tmp_path / "not-a-repo")])
    assert exc_info.value.code == 2
