"""Snapshot, history, and diff-loading helpers for the GitStatuz main window."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import QCheckBox, QHeaderView, QMessageBox

from ..models import CommitEntry, FileStatus, RepoSnapshot
from .main_window_core import (
    STATUS_FILTER_ORDER,
    STATUS_FILTER_SETTINGS_KEYS,
    MainWindowCore,
    coerce_bool,
    truncate_preview_text,
)
from .tree_model import build_tree_model, index_node_type, index_repo_relpath

if TYPE_CHECKING:
    from PySide6.QtCore import QModelIndex


class MainWindowSnapshotMixin(MainWindowCore):
    """Repository snapshot, history loading, and diff preview helpers."""

    def _restore_tree_column_widths(self) -> None: ...

    def _apply_tree_depth(self) -> None: ...

    def refresh(self) -> None:
        """Load a fresh repository snapshot unless one is already in flight."""
        if self._is_loading_snapshot:
            return
        self._is_loading_snapshot = True
        self.refresh_button.setEnabled(False)
        self.status_label.setText("Loading repository snapshot...")
        self._pending_history_path = None
        self._pending_diff_token += 1
        self._set_diff_text("Loading repository diff...")
        self._start_worker(
            self._git_adapter.load_snapshot,
            self._handle_snapshot_loaded,
            self._handle_snapshot_error,
        )

    def _handle_snapshot_loaded(self, result: object) -> None:
        """Apply a loaded repository snapshot to the UI."""
        self._is_loading_snapshot = False
        self.refresh_button.setEnabled(True)
        if not isinstance(result, RepoSnapshot):
            self._handle_snapshot_error("Unexpected snapshot result type.")
            return
        self._snapshot = result
        self._file_status_by_path = {
            status.repo_relpath: status for status in result.file_statuses
        }
        self._history_context = "repo"
        self.history_context_changed.emit("repo")

        upstream_name = result.branch_status.upstream or "none"
        self.branch_label.setText(
            "branch: "
            f"{result.branch_status.branch_name} | upstream: {upstream_name} | "
            f"ahead {result.branch_status.ahead} / behind {result.branch_status.behind}"
        )
        self.counts_label.setText(
            " | ".join(
                [
                    f"staged {result.counts.staged}",
                    f"unstaged {result.counts.unstaged}",
                    f"untracked {result.counts.untracked}",
                    f"conflicted {result.counts.conflicted}",
                    f"ignored {result.counts.ignored}",
                ]
            )
        )

        self._rebuild_tree_model()
        self._show_repo_history()
        self._request_repo_diff()
        self.status_label.setText("Ready")

    def _handle_snapshot_error(self, message: str) -> None:
        """Show a snapshot-loading failure to the user."""
        self._is_loading_snapshot = False
        self.refresh_button.setEnabled(True)
        self.status_label.setText("Load failed")
        QMessageBox.critical(self, "GitStatuz error", message)

    def _show_repo_history(self) -> None:
        """Populate the history view with repository-level commit history."""
        if self._snapshot is None:
            self._history_model.set_empty_message("No repository loaded.")
            return
        if not self._snapshot.has_commits:
            self._history_model.set_empty_message("Repository has no commits yet.")
            return
        self._history_model.set_commits(self._snapshot.repo_history)

    def _visible_file_statuses(self) -> list[FileStatus]:
        """Return file statuses that pass the active status filter set."""
        if self._snapshot is None:
            return []
        enabled_statuses = {
            tag for tag, enabled in self._status_filter_enabled.items() if enabled
        }
        if not enabled_statuses:
            return []
        return [
            status
            for status in self._snapshot.file_statuses
            if self._status_tags_for_file(status) & enabled_statuses
        ]

    def _rebuild_tree_model(self) -> None:
        """Rebuild the tree model from the currently visible file statuses."""
        tree_model = build_tree_model(self._visible_file_statuses())
        self.tree_view.setModel(tree_model)
        self.tree_view.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree_view.header().setStretchLastSection(False)
        self._restore_tree_column_widths()
        self._apply_tree_depth()
        selection_model = self.tree_view.selectionModel()
        selection_model.selectionChanged.connect(self._handle_tree_selection_changed)

    def _is_tracked_unchanged(self, file_status: FileStatus) -> bool:
        """Return whether a file is tracked but otherwise unchanged."""
        return (
            file_status.is_tracked
            and not file_status.is_untracked
            and not file_status.is_ignored
            and not file_status.is_staged
            and not file_status.is_unstaged
            and not file_status.is_conflicted
            and not file_status.is_deleted
            and not file_status.is_renamed
        )

    def _status_tags_for_file(self, file_status: FileStatus) -> set[str]:
        """Return the active status tags represented by one file row."""
        tags: set[str] = set()
        if file_status.is_unstaged:
            tags.add("modified")
        if file_status.is_staged:
            tags.add("staged")
        if file_status.is_conflicted:
            tags.add("conflicted")
        if file_status.is_deleted:
            tags.add("deleted")
        if file_status.is_renamed:
            tags.add("renamed")
        if file_status.is_untracked:
            tags.add("untracked")
        if file_status.is_ignored:
            tags.add("ignored")
        if self._is_tracked_unchanged(file_status):
            tags.add("unchanged")
        return tags

    def _handle_status_filter_toggled(self, tag: str, checked: bool) -> None:
        """Persist one status filter toggle and refresh the tree."""
        self._status_filter_enabled[tag] = checked
        self._settings.set_value(STATUS_FILTER_SETTINGS_KEYS[tag], checked)
        self._refresh_after_filter_toggle()

    def _load_status_filter_settings(self) -> dict[str, bool]:
        """Load the persisted status filter state."""
        return {
            tag: coerce_bool(
                self._settings.value(STATUS_FILTER_SETTINGS_KEYS[tag], True),
                True,
            )
            for tag in STATUS_FILTER_ORDER
        }

    def _create_status_filter_checkbox(self, tag: str, label: str) -> QCheckBox:
        """Create and register one status filter checkbox."""
        checkbox = QCheckBox(label)
        checkbox.setChecked(self._status_filter_enabled[tag])
        self._status_filter_checkboxes[tag] = checkbox
        return checkbox

    def _make_status_filter_toggle_handler(self, tag: str):
        def _handle_toggle(checked: bool) -> None:
            self._handle_status_filter_toggled(tag, checked)

        return _handle_toggle

    def _refresh_after_filter_toggle(self) -> None:
        """Refresh the tree and preview after a status filter change."""
        if self._snapshot is None:
            return
        self._rebuild_tree_model()
        if not self.tree_view.currentIndex().isValid():
            self._history_context = "repo"
            self.history_context_changed.emit("repo")
            self._show_repo_history()
            self._request_repo_diff()

    def _handle_tree_selection_changed(self, *_args: object) -> None:
        """Update history and diff preview when the tree selection changes."""
        selected_indexes = self.tree_view.selectedIndexes()
        if not selected_indexes:
            return
        first_col = next(
            (idx for idx in selected_indexes if idx.column() == 0),
            selected_indexes[0].siblingAtColumn(0),
        )
        node_type = index_node_type(first_col)
        if node_type != "file":
            self._history_context = "repo"
            self.history_context_changed.emit("repo")
            self._show_repo_history()
            self._request_repo_diff()
            return

        repo_relpath = index_repo_relpath(first_col)
        if repo_relpath:
            self.file_selected.emit(repo_relpath)

    def _handle_tree_double_clicked(self, index: QModelIndex) -> None:
        """Open or diff the selected file when it is activated in the tree."""
        node_type = index_node_type(index)
        if node_type != "file":
            return
        repo_relpath = index_repo_relpath(index)
        if repo_relpath:
            self.file_activated.emit(repo_relpath)

    def _handle_file_selected(self, repo_relpath: str) -> None:
        """Load file history and preview for the newly selected tree item."""
        file_status = self._file_status_by_path.get(repo_relpath)
        if file_status is None:
            return

        self._history_context = f"file:{repo_relpath}"
        self.history_context_changed.emit(self._history_context)

        if file_status.is_untracked:
            self._pending_diff_token += 1
            self._history_model.set_empty_message(
                "No commit history for untracked file."
            )
            self.status_label.setText(f"Loading content for {repo_relpath}...")
            self._request_file_content(repo_relpath)
            return

        if file_status.is_ignored:
            self._pending_diff_token += 1
            self._history_model.set_empty_message("No commit history for ignored file.")
            self.status_label.setText(f"Loading content for {repo_relpath}...")
            self._request_file_content(repo_relpath)
            return

        self._pending_history_path = repo_relpath
        self.status_label.setText(f"Loading history and preview for {repo_relpath}...")
        self._start_worker(
            lambda: self._git_adapter.load_file_history(repo_relpath),
            lambda result: self._handle_file_history_loaded(repo_relpath, result),
            self._handle_history_error,
        )
        if self._is_tracked_unchanged(file_status):
            self._request_file_content(repo_relpath)
        else:
            self._request_file_diff(repo_relpath)

    def _handle_file_history_loaded(self, repo_relpath: str, result: object) -> None:
        """Apply the loaded history for the selected file."""
        if self._pending_history_path != repo_relpath:
            return
        if not isinstance(result, list):
            self._handle_history_error("Unexpected file history result type.")
            return

        entries = cast("list[object]", result)
        commits = [entry for entry in entries if isinstance(entry, CommitEntry)]
        if commits:
            self._history_model.set_commits(commits)
        else:
            self._history_model.set_empty_message("No commits found for selected file.")
        self.status_label.setText("Ready")

    def _handle_history_error(self, message: str) -> None:
        """Show a file-history loading failure to the user."""
        self.status_label.setText("History load failed")
        self._history_model.set_empty_message("Failed to load history.")
        QMessageBox.warning(self, "GitStatuz history error", message)

    def _handle_file_activated(self, repo_relpath: str) -> None:
        """Launch the selected file in the configured diff/open action."""
        file_status = self._file_status_by_path.get(repo_relpath)
        if file_status is None:
            return
        try:
            self._diff_launcher.open_for_file(file_status, self._git_adapter)
        except Exception as exc:
            QMessageBox.warning(self, "GitStatuz open/diff error", str(exc))

    def _set_diff_text(self, text: str) -> None:
        """Set the diff preview text using the size-safe truncation helper."""
        self.diff_view.setPlainText(truncate_preview_text(text))

    def _request_repo_diff(self) -> None:
        """Request the repository-wide diff preview."""
        self._pending_diff_token += 1
        token = self._pending_diff_token
        self._set_diff_text("Loading repository diff...")
        self._start_worker(
            self._git_adapter.load_repo_diff,
            lambda result: self._handle_diff_loaded(token, result),
            lambda message: self._handle_diff_error(token, message),
        )

    def _request_file_diff(self, repo_relpath: str) -> None:
        """Request a diff preview for one tracked file."""
        self._pending_diff_token += 1
        token = self._pending_diff_token
        self._set_diff_text(f"Loading diff for {repo_relpath}...")
        self._start_worker(
            lambda: self._git_adapter.load_file_diff(repo_relpath),
            lambda result: self._handle_diff_loaded(token, result),
            lambda message: self._handle_diff_error(token, message),
        )

    def _request_file_content(self, repo_relpath: str) -> None:
        """Request a working-tree content preview for one file."""
        self._pending_diff_token += 1
        token = self._pending_diff_token
        self._set_diff_text(f"Loading content for {repo_relpath}...")
        self._start_worker(
            lambda: self._git_adapter.load_working_file_text(repo_relpath),
            lambda result: self._handle_diff_loaded(token, result),
            lambda message: self._handle_diff_error(token, message),
        )

    def _handle_diff_loaded(self, token: int, result: object) -> None:
        """Apply a loaded diff or content preview when it is still current."""
        if token != self._pending_diff_token:
            return
        if not isinstance(result, str):
            self._handle_diff_error(token, "Unexpected diff result type.")
            return
        self._set_diff_text(result)
        self.status_label.setText("Ready")

    def _handle_diff_error(self, token: int, message: str) -> None:
        """Show a diff-loading failure when it is still current."""
        if token != self._pending_diff_token:
            return
        self.status_label.setText("Diff load failed")
        self._set_diff_text("Failed to load diff.")
        QMessageBox.warning(self, "GitStatuz diff error", message)
