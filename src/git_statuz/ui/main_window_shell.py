"""Menus, recent paths, layout persistence, and close handling for GitStatuz."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..git_adapter import GitCommandError, resolve_repo_root
from .main_window_core import (
    MAX_RECENT_PATHS,
    SETTINGS_HISTORY_WIDTHS_KEY,
    SETTINGS_MAIN_SPLITTER_SIZES_KEY,
    SETTINGS_RIGHT_SPLITTER_SIZES_KEY,
    SETTINGS_TREE_WIDTHS_KEY,
    STATUS_FILTER_SETTINGS_KEYS,
    coerce_width_list,
)
from .main_window_snapshot import MainWindowSnapshotMixin


class MainWindowShellMixin(MainWindowSnapshotMixin):
    """Menu, recent-path, and persisted-layout helpers."""

    def _build_file_menu(self) -> None:
        """Build the File menu and its recent-path submenu."""
        file_menu = self.menuBar().addMenu("&File")
        open_action = file_menu.addAction("&Open Directory...")
        open_action.triggered.connect(self._prompt_open_directory_new_instance)
        self._recent_menu = file_menu.addMenu("Re&cents")
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcuts([QKeySequence("Ctrl+Q"), QKeySequence("Alt+X")])
        exit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        exit_action.triggered.connect(self.close)

    def _build_view_menu(self) -> None:
        """Build the View menu."""
        view_menu = self.menuBar().addMenu("&View")
        refresh_action = view_menu.addAction("&Refresh")
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        refresh_action.triggered.connect(self.refresh_requested.emit)

    def _build_help_menu(self) -> None:
        """Build the Help menu."""
        help_menu = self.menuBar().addMenu("&Help")
        help_action = help_menu.addAction("&Help")
        help_action.setShortcut(QKeySequence("F1"))
        help_action.triggered.connect(self._show_help)

    def _show_help(self) -> None:
        """Show the built-in keyboard shortcut help."""
        QMessageBox.information(
            self,
            "Help",
            "Keyboard shortcuts:\n"
            "F5: Refresh repository snapshot and diffs\n"
            "Ctrl+Q / Alt+X: Exit application",
        )

    def _prompt_open_directory_new_instance(self) -> None:
        """Prompt for a repository directory and open it in a new window."""
        start_dir = str(self.repo_root)
        while True:
            selected = QFileDialog.getExistingDirectory(
                self,
                "Open Repository Directory",
                start_dir,
                options=QFileDialog.Option.ShowDirsOnly,
            )
            if not selected:
                return

            normalized = str(Path(selected).resolve())
            if not self._is_git_repo_path(normalized):
                QMessageBox.warning(
                    self,
                    "Invalid repository",
                    f"Not a git repo {normalized}",
                )
                start_dir = normalized
                continue
            self._open_recent_in_new_instance(normalized)
            return

    def _is_git_repo_path(self, path: str) -> bool:
        """Return whether the given path resolves to a Git repository root."""
        try:
            resolve_repo_root(path)
        except GitCommandError:
            return False
        return True

    def _push_recent_path(self, path: str) -> None:
        """Push one repository path into the recents list."""
        from .recent_paths import update_recent_paths

        self._recent_paths = update_recent_paths(
            self._recent_paths,
            path,
            limit=MAX_RECENT_PATHS,
        )
        from .recent_paths import SETTINGS_RECENT_PATHS_KEY

        self._settings.set_value(SETTINGS_RECENT_PATHS_KEY, self._recent_paths)
        if hasattr(self, "_recent_menu"):
            self._rebuild_recent_menu()

    def _drop_recent_path(self, path: str) -> None:
        """Remove one repository path from the recents list."""
        from .recent_paths import SETTINGS_RECENT_PATHS_KEY, drop_recent_path

        self._recent_paths = drop_recent_path(self._recent_paths, path)
        self._settings.set_value(SETTINGS_RECENT_PATHS_KEY, self._recent_paths)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        """Rebuild the recent-path submenu from the persisted recents list."""
        self._recent_menu.clear()
        if not self._recent_paths:
            empty_action = self._recent_menu.addAction("N&o recent directories")
            empty_action.setEnabled(False)
            return

        for path in self._recent_paths:
            action = self._recent_menu.addAction(path.replace("&", "&&"))
            action.setToolTip(path)
            action.triggered.connect(
                lambda checked=False, selected=path: self._open_recent_in_new_instance(
                    selected
                )
            )

    def _open_recent_in_new_instance(self, path: str) -> None:
        """Launch a new GitStatuz process for one recent repository path."""
        normalized = str(Path(path).resolve())
        if not Path(normalized).exists():
            QMessageBox.warning(
                self,
                "Recent directory missing",
                f"Directory not found:\n{normalized}",
            )
            self._drop_recent_path(normalized)
            return

        self._push_recent_path(normalized)
        args = [
            "-m",
            "git_statuz",
            "-i",
            normalized,
            "--history-limit",
            str(self._history_limit),
        ]
        if self._winmerge_path:
            args.extend(["--winmerge", self._winmerge_path])
        launched = self._start_detached_python(args)
        if not launched:
            QMessageBox.warning(
                self,
                "Launch failed",
                f"Could not launch new instance for:\n{normalized}",
            )

    def _start_detached_python(self, args: list[str]) -> bool:
        """Start a detached Python process for the given argument vector."""
        return self._start_process(sys.executable, args)

    @staticmethod
    def _start_process(program: str, args: list[str]) -> bool:
        """Start a detached process and return whether it launched."""
        launched = QProcess.startDetached(program, args)
        launched_ok, _pid = launched
        return bool(launched_ok)

    def _restore_tree_column_widths(self) -> None:
        """Restore persisted tree-view column widths."""
        widths = coerce_width_list(
            self._settings.value(SETTINGS_TREE_WIDTHS_KEY),
            expected_count=3,
            defaults=[560, 260, 280],
        )
        for index, width in enumerate(widths):
            self.tree_view.setColumnWidth(index, width)

    def _restore_history_column_widths(self) -> None:
        """Restore persisted history-table column widths."""
        widths = coerce_width_list(
            self._settings.value(SETTINGS_HISTORY_WIDTHS_KEY),
            expected_count=4,
            defaults=[110, 250, 180, 620],
        )
        for index, width in enumerate(widths):
            self.history_view.setColumnWidth(index, width)

    def _restore_splitter_sizes(self) -> None:
        """Restore persisted main and right splitter sizes."""
        if self._main_splitter is not None:
            main_sizes = coerce_width_list(
                self._settings.value(SETTINGS_MAIN_SPLITTER_SIZES_KEY),
                expected_count=2,
                defaults=[520, 780],
            )
            self._main_splitter.setSizes(main_sizes)
        if self._right_splitter is not None:
            right_sizes = coerce_width_list(
                self._settings.value(SETTINGS_RIGHT_SPLITTER_SIZES_KEY),
                expected_count=2,
                defaults=[420, 260],
            )
            self._right_splitter.setSizes(right_sizes)

    def _save_tree_column_widths(self, *_args: object) -> None:
        """Persist current tree-view column widths."""
        widths = [self.tree_view.columnWidth(index) for index in range(3)]
        self._settings.set_value(SETTINGS_TREE_WIDTHS_KEY, widths)

    def _save_history_column_widths(self, *_args: object) -> None:
        """Persist current history-table column widths."""
        widths = [self.history_view.columnWidth(index) for index in range(4)]
        self._settings.set_value(SETTINGS_HISTORY_WIDTHS_KEY, widths)

    def _save_splitter_sizes(self, *_args: object) -> None:
        """Persist current splitter sizes."""
        if self._main_splitter is not None:
            self._settings.set_value(
                SETTINGS_MAIN_SPLITTER_SIZES_KEY,
                self._main_splitter.sizes(),
            )
        if self._right_splitter is not None:
            self._settings.set_value(
                SETTINGS_RIGHT_SPLITTER_SIZES_KEY,
                self._right_splitter.sizes(),
            )

    def _max_tree_depth(self) -> int:
        """Return the maximum depth present in the current tree model."""
        model = self.tree_view.model()
        max_depth = -1
        stack = [(model.index(row, 0), 0) for row in range(model.rowCount())]
        while stack:
            index, depth = stack.pop()
            if not index.isValid():
                continue
            if depth > max_depth:
                max_depth = depth
            for row in range(model.rowCount(index)):
                stack.append((model.index(row, 0, index), depth + 1))
        return max_depth

    def _apply_tree_depth(self) -> None:
        """Apply the currently requested expansion depth to the tree."""
        max_depth = self._max_tree_depth()
        if max_depth < 0:
            return
        self._tree_depth_target = min(self._tree_depth_target, max_depth)
        self.tree_view.collapseAll()
        if self._tree_depth_target >= 0:
            self.tree_view.expandToDepth(self._tree_depth_target)

    def _adjust_tree_depth(self, delta: int) -> None:
        """Adjust the requested tree expansion depth by one delta."""
        max_depth = self._max_tree_depth()
        if max_depth < 0:
            return
        self._tree_depth_target = max(
            -1,
            min(max_depth, self._tree_depth_target + delta),
        )
        self._apply_tree_depth()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist window geometry and filter settings during shutdown."""
        self._save_tree_column_widths()
        self._save_history_column_widths()
        self._save_splitter_sizes()
        for tag, enabled in self._status_filter_enabled.items():
            self._settings.set_value(STATUS_FILTER_SETTINGS_KEYS[tag], enabled)
        self._settings.sync()
        super().closeEvent(event)
