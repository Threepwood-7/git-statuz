from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from git_statuz.models import FileStatus
from git_statuz.services import diff_launcher
from git_statuz.services.diff_launcher import DiffLauncher, resolve_winmerge_path

class _DummyGitAdapter:
    def has_head(self) -> bool:
        return True

    def get_head_file_bytes(self, repo_relpath: str) -> bytes:
        del repo_relpath
        return b"from head\n"


def _file_status(
    path: str, *, tracked: bool, untracked: bool = False, ignored: bool = False
) -> FileStatus:
    return FileStatus(
        repo_relpath=path,
        is_tracked=tracked,
        is_untracked=untracked,
        is_ignored=ignored,
        is_staged=False,
        is_unstaged=bool(tracked),
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )


def test_resolve_winmerge_path_uses_explicit(tmp_path: Path) -> None:
    exe = tmp_path / "WinMergeU.exe"
    exe.write_text("", encoding="utf-8")
    assert resolve_winmerge_path(str(exe)) == str(exe)


def test_resolve_winmerge_path_uses_common_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        diff_launcher,
        "find_first_available_executable",
        lambda **_kwargs: Path(r"C:\Tools\WinMergeU.exe"),
    )

    assert resolve_winmerge_path() == r"C:\Tools\WinMergeU.exe"


def test_open_untracked_uses_default_editor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        diff_launcher, "resolve_winmerge_path", lambda preferred_path=None: None
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "new.txt"
    file_path.write_text("new", encoding="utf-8")

    opened: list[Path] = []
    monkeypatch.setattr(
        diff_launcher, "open_path_in_default_app", lambda path: opened.append(Path(path)) or True
    )

    launcher = DiffLauncher(str(repo))
    launcher.open_for_file(
        _file_status("new.txt", tracked=False, untracked=True), _DummyGitAdapter()
    )

    assert opened == [file_path]


def test_open_tracked_uses_winmerge(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "tracked.txt"
    file_path.write_text("working tree\n", encoding="utf-8")
    winmerge = tmp_path / "WinMergeU.exe"
    winmerge.write_text("", encoding="utf-8")

    calls: list[list[str]] = []
    monkeypatch.setattr(
        diff_launcher.subprocess, "Popen", lambda args: calls.append(args)
    )

    launcher = DiffLauncher(str(repo), winmerge_path=str(winmerge))
    launcher.open_for_file(
        _file_status("tracked.txt", tracked=True), _DummyGitAdapter()
    )

    assert len(calls) == 1
    assert calls[0][0] == str(winmerge)
    assert calls[0][-1] == str(file_path)


def test_open_tracked_without_winmerge_falls_back_to_editor(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        diff_launcher, "resolve_winmerge_path", lambda preferred_path=None: None
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "tracked.txt"
    file_path.write_text("working tree\n", encoding="utf-8")

    opened: list[Path] = []
    monkeypatch.setattr(
        diff_launcher, "open_path_in_default_app", lambda path: opened.append(Path(path)) or True
    )

    launcher = DiffLauncher(str(repo))
    launcher.open_for_file(
        _file_status("tracked.txt", tracked=True), _DummyGitAdapter()
    )

    assert opened == [file_path]
