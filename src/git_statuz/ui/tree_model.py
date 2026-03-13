"""Tree-model helpers for repository file status presentation."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models import FileStatus

NODE_TYPE_ROLE = Qt.ItemDataRole.UserRole + 1
REL_PATH_ROLE = Qt.ItemDataRole.UserRole + 2
FILE_STATUS_ROLE = Qt.ItemDataRole.UserRole + 3

COLOR_CONFLICTED = QColor("#C0392B")
COLOR_UNSTAGED = QColor("#E67E22")
COLOR_STAGED = QColor("#1E8449")
COLOR_UNTRACKED = QColor("#1F618D")
COLOR_IGNORED = QColor("#7F8C8D")


def format_status_text(file_status: FileStatus) -> str:
    """Build the compact status summary text shown in the tree view."""
    parts: list[str] = []
    if file_status.is_tracked:
        parts.append("tracked")
    if file_status.is_untracked:
        parts.append("untracked")
    if file_status.is_ignored:
        parts.append("ignored")
    if file_status.is_conflicted:
        parts.append("conflicted")
    if file_status.is_staged:
        parts.append("staged")
    if file_status.is_unstaged:
        parts.append("modified")
    if file_status.is_deleted:
        parts.append("deleted")
    if file_status.is_renamed:
        parts.append("renamed")
    if file_status.is_tracked and not any(
        [
            file_status.is_untracked,
            file_status.is_ignored,
            file_status.is_conflicted,
            file_status.is_staged,
            file_status.is_unstaged,
            file_status.is_deleted,
            file_status.is_renamed,
        ]
    ):
        parts.append("unchanged")
    if not parts:
        parts.append("clean")
    return "+".join(parts)


def status_color(file_status: FileStatus) -> QColor:
    """Choose the display color for a file status row."""
    if file_status.is_conflicted:
        return COLOR_CONFLICTED
    if file_status.is_unstaged:
        return COLOR_UNSTAGED
    if file_status.is_staged:
        return COLOR_STAGED
    if file_status.is_untracked:
        return COLOR_UNTRACKED
    if file_status.is_ignored:
        return COLOR_IGNORED
    return QColor()


def _set_row_data(
    name_item: QStandardItem,
    modified_item: QStandardItem,
    status_item: QStandardItem,
    node_type: str,
    repo_relpath: str | None,
    file_status: FileStatus | None,
) -> None:
    for item in (name_item, modified_item, status_item):
        item.setData(node_type, NODE_TYPE_ROLE)
        item.setData(repo_relpath, REL_PATH_ROLE)
        item.setData(file_status, FILE_STATUS_ROLE)


def build_tree_model(file_statuses: Sequence[FileStatus]) -> QStandardItemModel:
    """Build the hierarchical tree model for repository file statuses."""
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(["Name", "Last Modified", "Status"])
    root = model.invisibleRootItem()

    dir_cache: dict[tuple[str, str], QStandardItem] = {}
    ignored_group_item: QStandardItem | None = None

    def ensure_ignored_group() -> QStandardItem:
        nonlocal ignored_group_item
        if ignored_group_item is None:
            name_item = QStandardItem("[Ignored]")
            modified_item = QStandardItem("")
            status_item = QStandardItem("ignored group")
            _set_row_data(name_item, modified_item, status_item, "group", None, None)
            brush = QBrush(COLOR_IGNORED)
            name_item.setForeground(brush)
            modified_item.setForeground(brush)
            status_item.setForeground(brush)
            root.appendRow([name_item, modified_item, status_item])
            ignored_group_item = name_item
        return ignored_group_item

    def ensure_dir(
        region: str, dir_path: str, parent: QStandardItem, label: str
    ) -> QStandardItem:
        key = (region, dir_path)
        if key in dir_cache:
            return dir_cache[key]
        name_item = QStandardItem(label)
        modified_item = QStandardItem("")
        status_item = QStandardItem("")
        _set_row_data(
            name_item, modified_item, status_item, "dir", dir_path or None, None
        )
        parent.appendRow([name_item, modified_item, status_item])
        dir_cache[key] = name_item
        return name_item

    for file_status in sorted(file_statuses, key=lambda item: item.repo_relpath):
        parts = PurePosixPath(file_status.repo_relpath).parts
        if not parts:
            continue

        region = "ignored" if file_status.is_ignored else "main"
        parent_item = ensure_ignored_group() if file_status.is_ignored else root

        built_segments: list[str] = []
        for part in parts[:-1]:
            built_segments.append(part)
            full_dir = "/".join(built_segments)
            parent_item = ensure_dir(region, full_dir, parent_item, part)

        name_item = QStandardItem(parts[-1])
        modified_item = QStandardItem(file_status.last_modified_iso or "")
        status_item = QStandardItem(format_status_text(file_status))
        _set_row_data(
            name_item,
            modified_item,
            status_item,
            "file",
            file_status.repo_relpath,
            file_status,
        )

        color = status_color(file_status)
        if color.isValid():
            brush = QBrush(color)
            name_item.setForeground(brush)
            modified_item.setForeground(brush)
            status_item.setForeground(brush)

        parent_item.appendRow([name_item, modified_item, status_item])

    return model


def _base_index(index: QModelIndex) -> QModelIndex:
    return index.siblingAtColumn(0) if index.isValid() else index


def index_node_type(index: QModelIndex) -> str | None:
    """Return the stored node type for a model index."""
    if not index.isValid():
        return None
    return _base_index(index).data(NODE_TYPE_ROLE)


def index_repo_relpath(index: QModelIndex) -> str | None:
    """Return the repository-relative path stored on a model index."""
    if not index.isValid():
        return None
    return _base_index(index).data(REL_PATH_ROLE)


def index_file_status(index: QModelIndex) -> FileStatus | None:
    """Return the file-status payload stored on a model index."""
    if not index.isValid():
        return None
    return _base_index(index).data(FILE_STATUS_ROLE)
