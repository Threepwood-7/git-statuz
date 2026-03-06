from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QProcess,
    QRunnable,
    QSettings,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..git_adapter import GitAdapter, GitCommandError, resolve_repo_root
from ..models import CommitEntry, FileStatus, HistoryContext, RepoSnapshot
from ..services.diff_launcher import DiffLauncher
from .diff_highlighter import GitDiffHighlighter
from .history_model import HistoryTableModel
from .recent_paths import (
    MAX_RECENT_PATHS,
    SETTINGS_RECENT_PATHS_KEY,
    drop_recent_path,
    load_recent_paths,
    update_recent_paths,
)
from .tree_model import build_tree_model, index_node_type, index_repo_relpath

if TYPE_CHECKING:
    from collections.abc import Callable

SETTINGS_TREE_WIDTHS_KEY = "ui/tree_column_widths"
SETTINGS_HISTORY_WIDTHS_KEY = "ui/history_column_widths"
SETTINGS_MAIN_SPLITTER_SIZES_KEY = "ui/main_splitter_sizes"
SETTINGS_RIGHT_SPLITTER_SIZES_KEY = "ui/right_splitter_sizes"
SETTINGS_SHOW_UNTRACKED_KEY = "ui/show_untracked"
SETTINGS_SHOW_IGNORED_KEY = "ui/show_ignored"
PREVIEW_MAX_CHARS = 512 * 1024


def _coerce_width_list(raw_value: object, expected_count: int, defaults: list[int]) -> list[int]:
    values: list[int] = []
    source: list[str]
    if isinstance(raw_value, list):
        source = [str(item) for item in cast("list[object]", raw_value)]
    elif isinstance(raw_value, str):
        source = raw_value.split(",")
    else:
        source = []

    for value in source[:expected_count]:
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue

    if len(values) != expected_count:
        return defaults[:]
    return values


def _coerce_bool(raw_value: object, default: bool) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int):
        return raw_value != 0
    if isinstance(raw_value, str):
        lowered = raw_value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def truncate_preview_text(text: str, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    safe_text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    if len(safe_text) <= max_chars:
        return safe_text

    suffix = f"\n\n[Preview truncated at {max_chars} characters]"
    head_len = max_chars - len(suffix)
    if head_len <= 0:
        return safe_text[:max_chars]
    return safe_text[:head_len] + suffix


class _WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _FunctionWorker(QRunnable):
    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # pragma: no cover - Qt worker branch
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    refresh_requested = Signal()
    file_selected = Signal(str)
    file_activated = Signal(str)
    history_context_changed = Signal(str)

    def __init__(
        self,
        repo_root: str,
        winmerge_path: str | None = None,
        history_limit: int = 30,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.repo_root = Path(repo_root)
        self._history_limit = history_limit
        self._winmerge_path = winmerge_path
        self._settings = settings or QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "gitstatuz", "gitstatuz")
        self._recent_paths = load_recent_paths(
            self._settings.value(SETTINGS_RECENT_PATHS_KEY, []),
            limit=MAX_RECENT_PATHS,
        )
        self._show_untracked = _coerce_bool(self._settings.value(SETTINGS_SHOW_UNTRACKED_KEY, True), True)
        self._show_ignored = _coerce_bool(self._settings.value(SETTINGS_SHOW_IGNORED_KEY, True), True)
        self._thread_pool = QThreadPool.globalInstance()
        self._git_adapter = GitAdapter(str(self.repo_root), history_limit=history_limit)
        self._diff_launcher = DiffLauncher(str(self.repo_root), winmerge_path=winmerge_path)
        self._snapshot: RepoSnapshot | None = None
        self._file_status_by_path: dict[str, FileStatus] = {}
        self._active_workers: set[_FunctionWorker] = set()
        self._pending_history_path: str | None = None
        self._pending_diff_token = 0
        self._is_loading_snapshot = False
        self._history_context: HistoryContext = "repo"
        self._tree_depth_target = 1
        self._main_splitter: QSplitter | None = None
        self._right_splitter: QSplitter | None = None

        self._build_ui()
        self._bind_events()
        self._push_recent_path(str(self.repo_root))
        self.refresh_requested.emit()

    def _build_ui(self) -> None:
        self.setWindowTitle("GitStatuz")
        self.resize(1280, 780)
        self.setStyleSheet(
            """
            QMainWindow { background-color: #F4F7FA; }
            QTreeView, QTableView, QPlainTextEdit {
                background-color: #FFFFFF;
                alternate-background-color: #F0F3F7;
                border: 1px solid #D9E1EA;
            }
            QHeaderView::section {
                background-color: #E6EDF5;
                border: none;
                border-right: 1px solid #D0D8E2;
                padding: 5px;
                font-weight: 600;
            }
            QLabel#statusLabel { color: #4F5D6B; }
            """
        )

        root_widget = QWidget()
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.repo_label = QLabel(f"repo: {self.repo_root}")
        self.branch_label = QLabel("branch: -")
        self.counts_label = QLabel("staged 0 | unstaged 0 | untracked 0 | conflicted 0 | ignored 0")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")

        self.refresh_button = QPushButton("Refresh (F5)")
        self.expand_1_button = QPushButton("Expand +1")
        self.expand_2_button = QPushButton("Expand +2")
        self.collapse_1_button = QPushButton("Collapse -1")
        self.collapse_2_button = QPushButton("Collapse -2")
        self.show_untracked_checkbox = QCheckBox("Show untracked")
        self.show_untracked_checkbox.setChecked(self._show_untracked)
        self.show_ignored_checkbox = QCheckBox("Show ignored")
        self.show_ignored_checkbox.setChecked(self._show_ignored)

        top_bar.addWidget(self.repo_label, stretch=3)
        top_bar.addWidget(self.branch_label, stretch=3)
        top_bar.addWidget(self.counts_label, stretch=3)
        top_bar.addWidget(self.expand_1_button, stretch=0)
        top_bar.addWidget(self.expand_2_button, stretch=0)
        top_bar.addWidget(self.collapse_1_button, stretch=0)
        top_bar.addWidget(self.collapse_2_button, stretch=0)
        top_bar.addWidget(self.show_untracked_checkbox, stretch=0)
        top_bar.addWidget(self.show_ignored_checkbox, stretch=0)
        top_bar.addWidget(self.status_label, stretch=2)
        top_bar.addWidget(self.refresh_button, stretch=0)

        splitter = QSplitter()
        self._main_splitter = splitter
        self.tree_view = QTreeView()
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter = right_splitter
        self.history_view = QTableView()
        self.history_view.setAlternatingRowColors(True)
        self.history_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_view.verticalHeader().setVisible(False)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self.diff_view.setFont(mono_font)
        self._diff_highlighter = GitDiffHighlighter(self.diff_view.document())

        right_splitter.addWidget(self.history_view)
        right_splitter.addWidget(self.diff_view)
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)

        splitter.addWidget(self.tree_view)
        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self._history_model = HistoryTableModel()
        self.history_view.setModel(self._history_model)
        self.tree_view.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree_view.header().setStretchLastSection(False)
        self.history_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.history_view.horizontalHeader().setStretchLastSection(False)

        root_layout.addLayout(top_bar)
        root_layout.addWidget(splitter, stretch=1)

        self.setCentralWidget(root_widget)
        self._build_files_menu()
        self._restore_history_column_widths()
        self._restore_splitter_sizes()
        self._set_diff_text("Select a file to view diff or content.")

    def _bind_events(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        refresh_shortcut.activated.connect(self.refresh_requested.emit)
        self.tree_view.doubleClicked.connect(self._handle_tree_double_clicked)
        self.expand_1_button.clicked.connect(lambda: self._adjust_tree_depth(1))
        self.expand_2_button.clicked.connect(lambda: self._adjust_tree_depth(2))
        self.collapse_1_button.clicked.connect(lambda: self._adjust_tree_depth(-1))
        self.collapse_2_button.clicked.connect(lambda: self._adjust_tree_depth(-2))
        self.show_untracked_checkbox.toggled.connect(self._handle_show_untracked_toggled)
        self.show_ignored_checkbox.toggled.connect(self._handle_show_ignored_toggled)
        self.tree_view.header().sectionResized.connect(self._save_tree_column_widths)
        self.history_view.horizontalHeader().sectionResized.connect(self._save_history_column_widths)
        if self._main_splitter is not None:
            self._main_splitter.splitterMoved.connect(self._save_splitter_sizes)
        if self._right_splitter is not None:
            self._right_splitter.splitterMoved.connect(self._save_splitter_sizes)

        self.refresh_requested.connect(self.refresh)
        self.file_selected.connect(self._handle_file_selected)
        self.file_activated.connect(self._handle_file_activated)

    def _start_worker(
        self,
        fn: Callable[[], object],
        on_finished: Callable[[object], None],
        on_failed: Callable[[str], None],
    ) -> None:
        worker = _FunctionWorker(fn)
        self._active_workers.add(worker)

        def _safe_finished(result: object, current_worker: _FunctionWorker = worker) -> None:
            self._active_workers.discard(current_worker)
            try:
                on_finished(result)
            except Exception as exc:
                self.status_label.setText("Unexpected UI error")
                QMessageBox.critical(self, "GitStatuz runtime error", str(exc))

        def _safe_failed(message: str, current_worker: _FunctionWorker = worker) -> None:
            self._active_workers.discard(current_worker)
            try:
                on_failed(message)
            except Exception as exc:
                self.status_label.setText("Unexpected UI error")
                QMessageBox.critical(self, "GitStatuz runtime error", str(exc))

        worker.signals.finished.connect(_safe_finished)
        worker.signals.failed.connect(_safe_failed)
        self._thread_pool.start(worker)

    def refresh(self) -> None:
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
        self._is_loading_snapshot = False
        self.refresh_button.setEnabled(True)
        if not isinstance(result, RepoSnapshot):
            self._handle_snapshot_error("Unexpected snapshot result type.")
            return
        self._snapshot = result
        self._file_status_by_path = {status.repo_relpath: status for status in result.file_statuses}
        self._history_context = "repo"
        self.history_context_changed.emit("repo")

        self.branch_label.setText(
            "branch: "
            f"{result.branch_status.branch_name} | upstream: {result.branch_status.upstream or 'none'} | "
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
        self._is_loading_snapshot = False
        self.refresh_button.setEnabled(True)
        self.status_label.setText("Load failed")
        QMessageBox.critical(self, "GitStatuz error", message)

    def _show_repo_history(self) -> None:
        if self._snapshot is None:
            self._history_model.set_empty_message("No repository loaded.")
            return
        if not self._snapshot.has_commits:
            self._history_model.set_empty_message("Repository has no commits yet.")
            return
        self._history_model.set_commits(self._snapshot.repo_history)

    def _visible_file_statuses(self) -> list[FileStatus]:
        if self._snapshot is None:
            return []
        visible = self._snapshot.file_statuses
        if not self._show_untracked:
            visible = [status for status in visible if not status.is_untracked]
        if not self._show_ignored:
            visible = [status for status in visible if not status.is_ignored]
        return visible

    def _rebuild_tree_model(self) -> None:
        tree_model = build_tree_model(self._visible_file_statuses())
        self.tree_view.setModel(tree_model)
        self.tree_view.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree_view.header().setStretchLastSection(False)
        self._restore_tree_column_widths()
        self._apply_tree_depth()
        selection_model = self.tree_view.selectionModel()
        selection_model.selectionChanged.connect(self._handle_tree_selection_changed)

    def _is_tracked_unchanged(self, file_status: FileStatus) -> bool:
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

    def _handle_show_untracked_toggled(self, checked: bool) -> None:
        self._show_untracked = checked
        self._settings.setValue(SETTINGS_SHOW_UNTRACKED_KEY, checked)
        self._refresh_after_filter_toggle()

    def _handle_show_ignored_toggled(self, checked: bool) -> None:
        self._show_ignored = checked
        self._settings.setValue(SETTINGS_SHOW_IGNORED_KEY, checked)
        self._refresh_after_filter_toggle()

    def _refresh_after_filter_toggle(self) -> None:
        if self._snapshot is None:
            return
        self._rebuild_tree_model()
        if not self.tree_view.currentIndex().isValid():
            self._history_context = "repo"
            self.history_context_changed.emit("repo")
            self._show_repo_history()
            self._request_repo_diff()

    def _handle_tree_selection_changed(self, *_args: object) -> None:
        selected_indexes = self.tree_view.selectedIndexes()
        if not selected_indexes:
            return
        first_col = next((idx for idx in selected_indexes if idx.column() == 0), selected_indexes[0].siblingAtColumn(0))
        node_type = index_node_type(first_col)
        if node_type != "file":
            self._history_context = "repo"
            self.history_context_changed.emit("repo")
            self._show_repo_history()
            self._request_repo_diff()
            return

        repo_relpath = index_repo_relpath(first_col)
        if not repo_relpath:
            return
        self.file_selected.emit(repo_relpath)

    def _handle_tree_double_clicked(self, index: QModelIndex) -> None:
        node_type = index_node_type(index)
        if node_type != "file":
            return
        repo_relpath = index_repo_relpath(index)
        if repo_relpath:
            self.file_activated.emit(repo_relpath)

    def _handle_file_selected(self, repo_relpath: str) -> None:
        file_status = self._file_status_by_path.get(repo_relpath)
        if file_status is None:
            return

        self._history_context = f"file:{repo_relpath}"
        self.history_context_changed.emit(self._history_context)

        if file_status.is_untracked:
            self._pending_diff_token += 1
            self._history_model.set_empty_message("No commit history for untracked file.")
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
        self.status_label.setText("History load failed")
        self._history_model.set_empty_message("Failed to load history.")
        QMessageBox.warning(self, "GitStatuz history error", message)

    def _handle_file_activated(self, repo_relpath: str) -> None:
        file_status = self._file_status_by_path.get(repo_relpath)
        if file_status is None:
            return
        try:
            self._diff_launcher.open_for_file(file_status, self._git_adapter)
        except Exception as exc:
            QMessageBox.warning(self, "GitStatuz open/diff error", str(exc))

    def _set_diff_text(self, text: str) -> None:
        self.diff_view.setPlainText(truncate_preview_text(text))

    def _request_repo_diff(self) -> None:
        self._pending_diff_token += 1
        token = self._pending_diff_token
        self._set_diff_text("Loading repository diff...")
        self._start_worker(
            self._git_adapter.load_repo_diff,
            lambda result: self._handle_diff_loaded(token, result),
            lambda message: self._handle_diff_error(token, message),
        )

    def _request_file_diff(self, repo_relpath: str) -> None:
        self._pending_diff_token += 1
        token = self._pending_diff_token
        self._set_diff_text(f"Loading diff for {repo_relpath}...")
        self._start_worker(
            lambda: self._git_adapter.load_file_diff(repo_relpath),
            lambda result: self._handle_diff_loaded(token, result),
            lambda message: self._handle_diff_error(token, message),
        )

    def _request_file_content(self, repo_relpath: str) -> None:
        self._pending_diff_token += 1
        token = self._pending_diff_token
        self._set_diff_text(f"Loading content for {repo_relpath}...")
        self._start_worker(
            lambda: self._git_adapter.load_working_file_text(repo_relpath),
            lambda result: self._handle_diff_loaded(token, result),
            lambda message: self._handle_diff_error(token, message),
        )

    def _handle_diff_loaded(self, token: int, result: object) -> None:
        if token != self._pending_diff_token:
            return
        if not isinstance(result, str):
            self._handle_diff_error(token, "Unexpected diff result type.")
            return
        self._set_diff_text(result)
        self.status_label.setText("Ready")

    def _handle_diff_error(self, token: int, message: str) -> None:
        if token != self._pending_diff_token:
            return
        self.status_label.setText("Diff load failed")
        self._set_diff_text("Failed to load diff.")
        QMessageBox.warning(self, "GitStatuz diff error", message)

    def _build_files_menu(self) -> None:
        files_menu = self.menuBar().addMenu("Files")
        open_action = files_menu.addAction("Open Directory...")
        open_action.triggered.connect(self._prompt_open_directory_new_instance)
        self._recent_menu = files_menu.addMenu("Recents")
        self._rebuild_recent_menu()
        files_menu.addSeparator()
        exit_action = files_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence("Alt+X"))
        exit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        exit_action.triggered.connect(self.close)

    def _prompt_open_directory_new_instance(self) -> None:
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
                QMessageBox.warning(self, "Invalid repository", f"Not a git repo {normalized}")
                start_dir = normalized
                continue
            self._open_recent_in_new_instance(normalized)
            return

    def _is_git_repo_path(self, path: str) -> bool:
        try:
            resolve_repo_root(path)
        except GitCommandError:
            return False
        return True

    def _push_recent_path(self, path: str) -> None:
        self._recent_paths = update_recent_paths(self._recent_paths, path, limit=MAX_RECENT_PATHS)
        self._settings.setValue(SETTINGS_RECENT_PATHS_KEY, self._recent_paths)
        if hasattr(self, "_recent_menu"):
            self._rebuild_recent_menu()

    def _drop_recent_path(self, path: str) -> None:
        self._recent_paths = drop_recent_path(self._recent_paths, path)
        self._settings.setValue(SETTINGS_RECENT_PATHS_KEY, self._recent_paths)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        if not self._recent_paths:
            empty_action = self._recent_menu.addAction("No recent directories")
            empty_action.setEnabled(False)
            return

        for path in self._recent_paths:
            action = self._recent_menu.addAction(path)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, selected=path: self._open_recent_in_new_instance(selected))

    def _open_recent_in_new_instance(self, path: str) -> None:
        normalized = str(Path(path).resolve())
        if not Path(normalized).exists():
            QMessageBox.warning(self, "Recent directory missing", f"Directory not found:\n{normalized}")
            self._drop_recent_path(normalized)
            return

        self._push_recent_path(normalized)
        args = ["-m", "git_statuz", "-i", normalized, "--history-limit", str(self._history_limit)]
        if self._winmerge_path:
            args.extend(["--winmerge", self._winmerge_path])
        launched = QProcess.startDetached(sys.executable, args)
        if not launched:
            QMessageBox.warning(self, "Launch failed", f"Could not launch new instance for:\n{normalized}")

    def _restore_tree_column_widths(self) -> None:
        widths = _coerce_width_list(
            self._settings.value(SETTINGS_TREE_WIDTHS_KEY),
            expected_count=3,
            defaults=[560, 260, 280],
        )
        for index, width in enumerate(widths):
            self.tree_view.setColumnWidth(index, width)

    def _restore_history_column_widths(self) -> None:
        widths = _coerce_width_list(
            self._settings.value(SETTINGS_HISTORY_WIDTHS_KEY),
            expected_count=4,
            defaults=[110, 250, 180, 620],
        )
        for index, width in enumerate(widths):
            self.history_view.setColumnWidth(index, width)

    def _restore_splitter_sizes(self) -> None:
        if self._main_splitter is not None:
            main_sizes = _coerce_width_list(
                self._settings.value(SETTINGS_MAIN_SPLITTER_SIZES_KEY),
                expected_count=2,
                defaults=[520, 780],
            )
            self._main_splitter.setSizes(main_sizes)
        if self._right_splitter is not None:
            right_sizes = _coerce_width_list(
                self._settings.value(SETTINGS_RIGHT_SPLITTER_SIZES_KEY),
                expected_count=2,
                defaults=[420, 260],
            )
            self._right_splitter.setSizes(right_sizes)

    def _save_tree_column_widths(self, *_args: object) -> None:
        widths = [self.tree_view.columnWidth(index) for index in range(3)]
        self._settings.setValue(SETTINGS_TREE_WIDTHS_KEY, widths)

    def _save_history_column_widths(self, *_args: object) -> None:
        widths = [self.history_view.columnWidth(index) for index in range(4)]
        self._settings.setValue(SETTINGS_HISTORY_WIDTHS_KEY, widths)

    def _save_splitter_sizes(self, *_args: object) -> None:
        if self._main_splitter is not None:
            self._settings.setValue(SETTINGS_MAIN_SPLITTER_SIZES_KEY, self._main_splitter.sizes())
        if self._right_splitter is not None:
            self._settings.setValue(SETTINGS_RIGHT_SPLITTER_SIZES_KEY, self._right_splitter.sizes())

    def _max_tree_depth(self) -> int:
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
        max_depth = self._max_tree_depth()
        if max_depth < 0:
            return
        self._tree_depth_target = min(self._tree_depth_target, max_depth)
        self.tree_view.collapseAll()
        if self._tree_depth_target >= 0:
            self.tree_view.expandToDepth(self._tree_depth_target)

    def _adjust_tree_depth(self, delta: int) -> None:
        max_depth = self._max_tree_depth()
        if max_depth < 0:
            return
        self._tree_depth_target = max(-1, min(max_depth, self._tree_depth_target + delta))
        self._apply_tree_depth()

    def closeEvent(self, event: QCloseEvent) -> None:  # pragma: no cover - Qt event hook
        self._save_tree_column_widths()
        self._save_history_column_widths()
        self._save_splitter_sizes()
        self._settings.setValue(SETTINGS_SHOW_UNTRACKED_KEY, self._show_untracked)
        self._settings.setValue(SETTINGS_SHOW_IGNORED_KEY, self._show_ignored)
        self._settings.sync()
        super().closeEvent(event)
