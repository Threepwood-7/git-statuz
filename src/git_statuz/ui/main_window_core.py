"""Core widgets and worker plumbing for the GitStatuz main window."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from threep_commons.settings import QSettingsValueStore

from ..constants import APP_IDENTITY
from ..git_adapter import GitAdapter
from ..services.diff_launcher import DiffLauncher
from .diff_highlighter import GitDiffHighlighter
from .history_model import HistoryTableModel
from .recent_paths import MAX_RECENT_PATHS, SETTINGS_RECENT_PATHS_KEY, load_recent_paths

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtCore import QModelIndex

    from ..models import FileStatus, HistoryContext, RepoSnapshot

SETTINGS_TREE_WIDTHS_KEY = "ui/tree_column_widths"
SETTINGS_HISTORY_WIDTHS_KEY = "ui/history_column_widths"
SETTINGS_MAIN_SPLITTER_SIZES_KEY = "ui/main_splitter_sizes"
SETTINGS_RIGHT_SPLITTER_SIZES_KEY = "ui/right_splitter_sizes"
SETTINGS_SHOW_MODIFIED_KEY = "ui/show_modified"
SETTINGS_SHOW_STAGED_KEY = "ui/show_staged"
SETTINGS_SHOW_CONFLICTED_KEY = "ui/show_conflicted"
SETTINGS_SHOW_DELETED_KEY = "ui/show_deleted"
SETTINGS_SHOW_RENAMED_KEY = "ui/show_renamed"
SETTINGS_SHOW_UNTRACKED_KEY = "ui/show_untracked"
SETTINGS_SHOW_IGNORED_KEY = "ui/show_ignored"
SETTINGS_SHOW_UNCHANGED_KEY = "ui/show_unchanged"
STATUS_FILTER_ORDER = (
    "modified",
    "staged",
    "conflicted",
    "deleted",
    "renamed",
    "untracked",
    "ignored",
    "unchanged",
)
STATUS_FILTER_SETTINGS_KEYS = {
    "modified": SETTINGS_SHOW_MODIFIED_KEY,
    "staged": SETTINGS_SHOW_STAGED_KEY,
    "conflicted": SETTINGS_SHOW_CONFLICTED_KEY,
    "deleted": SETTINGS_SHOW_DELETED_KEY,
    "renamed": SETTINGS_SHOW_RENAMED_KEY,
    "untracked": SETTINGS_SHOW_UNTRACKED_KEY,
    "ignored": SETTINGS_SHOW_IGNORED_KEY,
    "unchanged": SETTINGS_SHOW_UNCHANGED_KEY,
}
PREVIEW_MAX_CHARS = 512 * 1024


def coerce_width_list(
    raw_value: object,
    expected_count: int,
    defaults: list[int],
) -> list[int]:
    """Normalize persisted splitter or column widths."""
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


def coerce_bool(raw_value: object, default: bool) -> bool:
    """Normalize a persisted boolean-like value."""
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
    """Truncate very large preview payloads to a safe display size."""
    safe_text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    if len(safe_text) <= max_chars:
        return safe_text

    suffix = f"\n\n[Preview truncated at {max_chars} characters]"
    head_len = max_chars - len(suffix)
    if head_len <= 0:
        return safe_text[:max_chars]
    return safe_text[:head_len] + suffix


class WorkerSignals(QObject):
    """Signals emitted by background function workers."""

    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    """Run one callable on the Qt thread pool and surface its result."""

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        """Execute the wrapped callable and emit success or failure."""
        try:
            result = self.fn()
        except Exception as exc:  # pragma: no cover - Qt worker branch
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)


class MainWindowCore(QMainWindow):
    """Main-window base class that owns widgets and worker wiring."""

    refresh_requested = Signal()
    file_selected = Signal(str)
    file_activated = Signal(str)
    history_context_changed = Signal(str)

    def __init__(
        self,
        repo_root: str,
        winmerge_path: str | None = None,
        history_limit: int = 30,
        settings: QSettingsValueStore | None = None,
    ) -> None:
        super().__init__()
        self.repo_root = Path(repo_root)
        self._history_limit = history_limit
        self._winmerge_path = winmerge_path
        self._settings = settings or QSettingsValueStore.from_identity(APP_IDENTITY)
        self._recent_paths = load_recent_paths(
            self._settings.value(SETTINGS_RECENT_PATHS_KEY, []),
            limit=MAX_RECENT_PATHS,
        )
        self._status_filter_enabled: dict[str, bool]
        self._status_filter_enabled = self._load_status_filter_settings()
        self._status_filter_checkboxes: dict[str, QCheckBox] = {}
        self._thread_pool = QThreadPool.globalInstance()
        self._git_adapter = GitAdapter(str(self.repo_root), history_limit=history_limit)
        self._diff_launcher = DiffLauncher(
            str(self.repo_root),
            winmerge_path=winmerge_path,
        )
        self._snapshot: RepoSnapshot | None = None
        self._file_status_by_path: dict[str, FileStatus] = {}
        self._active_workers: set[FunctionWorker] = set()
        self._pending_history_path: str | None = None
        self._pending_diff_token: int
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

    def _load_status_filter_settings(self) -> dict[str, bool]: ...

    def _push_recent_path(self, path: str) -> None: ...

    def _create_status_filter_checkbox(self, tag: str, label: str) -> QCheckBox: ...

    def _build_file_menu(self) -> None: ...

    def _build_view_menu(self) -> None: ...

    def _build_help_menu(self) -> None: ...

    def _restore_history_column_widths(self) -> None: ...

    def _restore_splitter_sizes(self) -> None: ...

    def _set_diff_text(self, text: str) -> None: ...

    def _handle_tree_double_clicked(self, index: QModelIndex) -> None: ...

    def _adjust_tree_depth(self, delta: int) -> None: ...

    def _make_status_filter_toggle_handler(
        self, tag: str
    ) -> Callable[[bool], None]: ...

    def _save_tree_column_widths(self, *_args: object) -> None: ...

    def _save_history_column_widths(self, *_args: object) -> None: ...

    def _save_splitter_sizes(self, *_args: object) -> None: ...

    def refresh(self) -> None: ...

    def _handle_file_selected(self, repo_relpath: str) -> None: ...

    def _handle_file_activated(self, repo_relpath: str) -> None: ...

    def _build_ui(self) -> None:
        """Build all widgets, splitters, menus, and restore persisted UI state."""
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
        self.counts_label = QLabel(
            "staged 0 | unstaged 0 | untracked 0 | conflicted 0 | ignored 0"
        )
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")

        self.refresh_button = QPushButton("Refresh (F5)")
        self.expand_1_button = QPushButton("Expand +1")
        self.expand_2_button = QPushButton("Expand +2")
        self.collapse_1_button = QPushButton("Collapse -1")
        self.collapse_2_button = QPushButton("Collapse -2")

        top_bar.addWidget(self.repo_label, stretch=3)
        top_bar.addWidget(self.branch_label, stretch=3)
        top_bar.addWidget(self.counts_label, stretch=3)
        top_bar.addWidget(self.expand_1_button, stretch=0)
        top_bar.addWidget(self.expand_2_button, stretch=0)
        top_bar.addWidget(self.collapse_1_button, stretch=0)
        top_bar.addWidget(self.collapse_2_button, stretch=0)
        top_bar.addWidget(self.status_label, stretch=2)
        top_bar.addWidget(self.refresh_button, stretch=0)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("filters:"), stretch=0)
        self.show_modified_checkbox = self._create_status_filter_checkbox(
            "modified",
            "Show modified",
        )
        self.show_staged_checkbox = self._create_status_filter_checkbox(
            "staged",
            "Show staged",
        )
        self.show_conflicted_checkbox = self._create_status_filter_checkbox(
            "conflicted",
            "Show conflicted",
        )
        self.show_deleted_checkbox = self._create_status_filter_checkbox(
            "deleted",
            "Show deleted",
        )
        self.show_renamed_checkbox = self._create_status_filter_checkbox(
            "renamed",
            "Show renamed",
        )
        self.show_untracked_checkbox = self._create_status_filter_checkbox(
            "untracked",
            "Show untracked",
        )
        self.show_ignored_checkbox = self._create_status_filter_checkbox(
            "ignored",
            "Show ignored",
        )
        self.show_unchanged_checkbox = self._create_status_filter_checkbox(
            "unchanged",
            "Show unchanged",
        )
        filter_row.addWidget(self.show_modified_checkbox, stretch=0)
        filter_row.addWidget(self.show_staged_checkbox, stretch=0)
        filter_row.addWidget(self.show_conflicted_checkbox, stretch=0)
        filter_row.addWidget(self.show_deleted_checkbox, stretch=0)
        filter_row.addWidget(self.show_renamed_checkbox, stretch=0)
        filter_row.addWidget(self.show_untracked_checkbox, stretch=0)
        filter_row.addWidget(self.show_ignored_checkbox, stretch=0)
        filter_row.addWidget(self.show_unchanged_checkbox, stretch=0)
        filter_row.addStretch(1)

        splitter = QSplitter()
        self._main_splitter = splitter
        self.tree_view = QTreeView()
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter = right_splitter
        self.history_view = QTableView()
        self.history_view.setAlternatingRowColors(True)
        self.history_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.history_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
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
        self.history_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.history_view.horizontalHeader().setStretchLastSection(False)

        root_layout.addLayout(top_bar)
        root_layout.addLayout(filter_row)
        root_layout.addWidget(splitter, stretch=1)

        self.setCentralWidget(root_widget)
        self._build_file_menu()
        self._build_view_menu()
        self._build_help_menu()
        self._restore_history_column_widths()
        self._restore_splitter_sizes()
        self._set_diff_text("Select a file to view diff or content.")

    def _bind_events(self) -> None:
        """Connect widget signals to the window event handlers."""
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.tree_view.doubleClicked.connect(self._handle_tree_double_clicked)
        self.expand_1_button.clicked.connect(lambda: self._adjust_tree_depth(1))
        self.expand_2_button.clicked.connect(lambda: self._adjust_tree_depth(2))
        self.collapse_1_button.clicked.connect(lambda: self._adjust_tree_depth(-1))
        self.collapse_2_button.clicked.connect(lambda: self._adjust_tree_depth(-2))
        for tag, checkbox in self._status_filter_checkboxes.items():
            checkbox.toggled.connect(self._make_status_filter_toggle_handler(tag))
        self.tree_view.header().sectionResized.connect(self._save_tree_column_widths)
        self.history_view.horizontalHeader().sectionResized.connect(
            self._save_history_column_widths
        )
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
        """Run one callable on the thread pool and marshal its result back safely."""
        worker = FunctionWorker(fn)
        self._active_workers.add(worker)

        def _safe_finished(
            result: object,
            current_worker: FunctionWorker = worker,
        ) -> None:
            self._active_workers.discard(current_worker)
            try:
                on_finished(result)
            except Exception as exc:
                self.status_label.setText("Unexpected UI error")
                QMessageBox.critical(self, "GitStatuz runtime error", str(exc))

        def _safe_failed(
            message: str,
            current_worker: FunctionWorker = worker,
        ) -> None:
            self._active_workers.discard(current_worker)
            try:
                on_failed(message)
            except Exception as exc:
                self.status_label.setText("Unexpected UI error")
                QMessageBox.critical(self, "GitStatuz runtime error", str(exc))

        worker.signals.finished.connect(_safe_finished)
        worker.signals.failed.connect(_safe_failed)
        self._thread_pool.start(worker)
