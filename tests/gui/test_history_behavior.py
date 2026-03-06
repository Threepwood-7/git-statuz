from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from git_statuz.git_adapter import GitAdapter
from git_statuz.models import (
    BranchStatus,
    CommitEntry,
    FileStatus,
    RepoSnapshot,
    StatusCounts,
)
from git_statuz.ui.main_window import MainWindow
from tests.conftest import commit_file, init_repo

if TYPE_CHECKING:
    from pathlib import Path


def test_repo_history_limit_30(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    for i in range(35):
        commit_file(repo, "history.txt", f"line {i}\n", f"commit {i}")

    adapter = GitAdapter(str(repo), history_limit=30)
    history = adapter.load_repo_history()
    assert len(history) == 30


def test_menu_bar_includes_core_file_view_help_actions(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(str(tmp_path), settings=settings)
    qtbot.addWidget(window)

    menus = {action.text(): action for action in window.menuBar().actions()}
    assert "&File" in menus
    assert "&View" in menus
    assert "&Help" in menus

    file_menu = menus["&File"].menu()
    assert file_menu is not None
    exit_action = next((action for action in file_menu.actions() if action.text() == "E&xit"), None)
    assert exit_action is not None
    exit_shortcuts = {shortcut.toString() for shortcut in exit_action.shortcuts()}
    assert {"Ctrl+Q", "Alt+X"} <= exit_shortcuts
    assert any(action.text() == "&Open Directory..." for action in file_menu.actions())
    assert any(action.text() == "Re&cents" for action in file_menu.actions())

    view_menu = menus["&View"].menu()
    assert view_menu is not None
    refresh_action = next((action for action in view_menu.actions() if action.text() == "&Refresh"), None)
    assert refresh_action is not None
    assert refresh_action.shortcut().toString().lower().replace(" ", "") == "f5"

    help_menu = menus["&Help"].menu()
    assert help_menu is not None
    help_action = next((action for action in help_menu.actions() if action.text() == "&Help"), None)
    assert help_action is not None
    assert help_action.shortcut().toString().lower().replace(" ", "") == "f1"


def test_recent_paths_escape_ampersand_in_menu_labels(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(str(tmp_path), settings=settings)
    qtbot.addWidget(window)

    window._recent_paths = [r"C:\repos\R&D"]
    window._rebuild_recent_menu()
    recent_actions = [action.text() for action in window._recent_menu.actions()]
    assert r"C:\repos\R&&D" in recent_actions


def test_main_window_switches_history_by_file_selection(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(str(tmp_path), settings=settings)
    qtbot.addWidget(window)

    tracked = FileStatus(
        repo_relpath="tracked.txt",
        is_tracked=True,
        is_untracked=False,
        is_ignored=False,
        is_staged=False,
        is_unstaged=True,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    untracked = FileStatus(
        repo_relpath="new.txt",
        is_tracked=False,
        is_untracked=True,
        is_ignored=False,
        is_staged=False,
        is_unstaged=False,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    ignored = FileStatus(
        repo_relpath="ignored.log",
        is_tracked=False,
        is_untracked=False,
        is_ignored=True,
        is_staged=False,
        is_unstaged=False,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    unchanged = FileStatus(
        repo_relpath="stable.txt",
        is_tracked=True,
        is_untracked=False,
        is_ignored=False,
        is_staged=False,
        is_unstaged=False,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    window._file_status_by_path = {
        tracked.repo_relpath: tracked,
        untracked.repo_relpath: untracked,
        ignored.repo_relpath: ignored,
        unchanged.repo_relpath: unchanged,
    }

    queued_results: list[object] = [
        [
            CommitEntry(
                short_sha="abc1234",
                author="Alice",
                date_iso="2026-01-01T10:00:00+00:00",
                subject="Tracked file commit",
            )
        ],
        "diff --git a/tracked.txt b/tracked.txt\n+new line\n",
        "UNTRACKED CONTENT",
        "IGNORED CONTENT",
        [
            CommitEntry(
                short_sha="def5678",
                author="Bob",
                date_iso="2026-01-02T10:00:00+00:00",
                subject="Stable file commit",
            )
        ],
        "UNCHANGED CONTENT",
    ]

    def immediate_worker(fn, on_finished, on_failed):
        del fn, on_failed
        on_finished(queued_results.pop(0))

    monkeypatch.setattr(window, "_start_worker", immediate_worker)

    window._handle_file_selected("tracked.txt")
    assert window._history_context == "file:tracked.txt"
    assert window._history_model.rowCount() == 1
    assert window._history_model.item(0, 0).text() == "abc1234"
    assert "+new line" in window.diff_view.toPlainText()

    window._handle_file_selected("new.txt")
    assert window._history_context == "file:new.txt"
    assert "No commit history" in window._history_model.item(0, 3).text()
    assert "UNTRACKED CONTENT" in window.diff_view.toPlainText()

    window._handle_file_selected("ignored.log")
    assert window._history_context == "file:ignored.log"
    assert "No commit history for ignored file" in window._history_model.item(0, 3).text()
    assert "IGNORED CONTENT" in window.diff_view.toPlainText()

    window._handle_file_selected("stable.txt")
    assert window._history_context == "file:stable.txt"
    assert window._history_model.item(0, 0).text() == "def5678"
    assert "UNCHANGED CONTENT" in window.diff_view.toPlainText()


def test_show_untracked_and_ignored_toggles_filter_tree(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_request_repo_diff", lambda self: None)
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(str(tmp_path), settings=settings)
    qtbot.addWidget(window)

    tracked = FileStatus(
        repo_relpath="tracked.txt",
        is_tracked=True,
        is_untracked=False,
        is_ignored=False,
        is_staged=False,
        is_unstaged=False,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    untracked = FileStatus(
        repo_relpath="new.txt",
        is_tracked=False,
        is_untracked=True,
        is_ignored=False,
        is_staged=False,
        is_unstaged=False,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    ignored = FileStatus(
        repo_relpath="ignored.log",
        is_tracked=False,
        is_untracked=False,
        is_ignored=True,
        is_staged=False,
        is_unstaged=False,
        is_conflicted=False,
        is_deleted=False,
        is_renamed=False,
    )
    snapshot = RepoSnapshot(
        branch_status=BranchStatus("main", False, "origin/main", 0, 0),
        file_statuses=[tracked, untracked, ignored],
        counts=StatusCounts(staged=0, unstaged=0, untracked=1, conflicted=0, ignored=1),
        repo_history=[],
        has_commits=False,
    )

    window._handle_snapshot_loaded(snapshot)
    model = window.tree_view.model()
    root_names = [model.item(row, 0).text() for row in range(model.rowCount())]
    assert "tracked.txt" in root_names
    assert "new.txt" in root_names
    assert "[Ignored]" in root_names

    window.show_untracked_checkbox.setChecked(False)
    model = window.tree_view.model()
    root_names = [model.item(row, 0).text() for row in range(model.rowCount())]
    assert "tracked.txt" in root_names
    assert "new.txt" not in root_names
    assert "[Ignored]" in root_names

    window.show_ignored_checkbox.setChecked(False)
    model = window.tree_view.model()
    root_names = [model.item(row, 0).text() for row in range(model.rowCount())]
    assert "tracked.txt" in root_names
    assert "new.txt" not in root_names
    assert "[Ignored]" not in root_names

    window.show_untracked_checkbox.setChecked(True)
    model = window.tree_view.model()
    root_names = [model.item(row, 0).text() for row in range(model.rowCount())]
    assert "tracked.txt" in root_names
    assert "new.txt" in root_names
    assert "[Ignored]" not in root_names

    window.show_ignored_checkbox.setChecked(True)
    model = window.tree_view.model()
    root_names = [model.item(row, 0).text() for row in range(model.rowCount())]
    assert "tracked.txt" in root_names
    assert "new.txt" in root_names
    assert "[Ignored]" in root_names


def test_prompt_open_directory_reprompts_for_non_git_selection(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(str(tmp_path), settings=settings)
    qtbot.addWidget(window)

    non_repo = tmp_path / "folder"
    non_repo.mkdir()
    repo = init_repo(tmp_path / "repo")

    selections = [str(non_repo), str(repo)]
    dialog_calls = 0

    def fake_get_existing_directory(*_args, **_kwargs) -> str:
        nonlocal dialog_calls
        dialog_calls += 1
        if selections:
            return selections.pop(0)
        return ""

    warnings: list[tuple[str, str]] = []

    def fake_warning(_parent, title: str, text: str):
        warnings.append((title, text))
        return QMessageBox.StandardButton.Ok

    opened_paths: list[str] = []

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_get_existing_directory)
    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    monkeypatch.setattr(window, "_open_recent_in_new_instance", lambda path: opened_paths.append(path))

    window._prompt_open_directory_new_instance()

    assert dialog_calls == 2
    assert warnings == [("Invalid repository", f"Not a git repo {non_repo.resolve()}")]
    assert opened_paths == [str(repo.resolve())]
