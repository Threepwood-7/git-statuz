from __future__ import annotations

from PySide6.QtGui import QColor

from git_statuz.models import FileStatus
from git_statuz.ui.tree_model import build_tree_model, format_status_text, status_color


def _status(
    path: str,
    *,
    tracked: bool = True,
    untracked: bool = False,
    ignored: bool = False,
    staged: bool = False,
    unstaged: bool = False,
    conflicted: bool = False,
    deleted: bool = False,
    renamed: bool = False,
    last_modified_iso: str | None = None,
) -> FileStatus:
    return FileStatus(
        repo_relpath=path,
        is_tracked=tracked,
        is_untracked=untracked,
        is_ignored=ignored,
        is_staged=staged,
        is_unstaged=unstaged,
        is_conflicted=conflicted,
        is_deleted=deleted,
        is_renamed=renamed,
        last_modified_iso=last_modified_iso,
    )


def test_build_tree_model_places_ignored_in_group() -> None:
    model = build_tree_model(
        [
            _status("src/main.py", tracked=True, unstaged=True, last_modified_iso="2026-03-04 10:30:00"),
            _status("tmp/cache.bin", tracked=False, ignored=True),
        ]
    )
    assert model.columnCount() == 3
    assert model.horizontalHeaderItem(0).text() == "Name"
    assert model.horizontalHeaderItem(1).text() == "Last Modified"
    assert model.horizontalHeaderItem(2).text() == "Status"

    root_names = [model.item(row, 0).text() for row in range(model.rowCount())]
    assert "src" in root_names
    assert "[Ignored]" in root_names

    src_item = next(model.item(row, 0) for row in range(model.rowCount()) if model.item(row, 0).text() == "src")
    assert src_item.child(0, 0).text() == "main.py"
    assert src_item.child(0, 1).text() == "2026-03-04 10:30:00"

    ignored_item = next(model.item(row, 0) for row in range(model.rowCount()) if model.item(row, 0).text() == "[Ignored]")
    assert model.item(ignored_item.row(), 1).text() == ""
    assert ignored_item.rowCount() == 1
    assert ignored_item.child(0, 0).text() == "tmp"


def test_status_text_and_color_precedence() -> None:
    both = _status("a.txt", staged=True, unstaged=True)
    conflict = _status("b.txt", staged=True, conflicted=True)
    unchanged = _status("c.txt")

    assert format_status_text(both) == "tracked+staged+modified"
    assert format_status_text(unchanged) == "tracked+unchanged"
    assert status_color(both).name().lower() == QColor("#E67E22").name().lower()
    assert status_color(conflict).name().lower() == QColor("#C0392B").name().lower()
