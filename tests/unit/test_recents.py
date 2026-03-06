from __future__ import annotations

from typing import TYPE_CHECKING

from git_statuz.ui.main_window import update_recent_paths

if TYPE_CHECKING:
    from pathlib import Path


def test_update_recent_paths_puts_new_path_first_and_dedupes(tmp_path: Path) -> None:
    repo_a = str((tmp_path / "a").resolve())
    repo_b = str((tmp_path / "b").resolve())
    repo_c = str((tmp_path / "c").resolve())

    result = update_recent_paths([repo_a, repo_b, repo_a], repo_c, limit=10)
    assert result[0] == repo_c
    assert result[1:] == [repo_a, repo_b]


def test_update_recent_paths_enforces_limit(tmp_path: Path) -> None:
    paths = [str((tmp_path / f"r{i}").resolve()) for i in range(15)]
    result = update_recent_paths(paths, paths[3], limit=10)
    assert len(result) == 10
    assert result[0] == paths[3]

