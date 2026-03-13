"""Public main window entry point for the GitStatuz application."""

from __future__ import annotations

from .main_window_core import truncate_preview_text
from .main_window_shell import MainWindowShellMixin
from .recent_paths import update_recent_paths

__all__ = ["MainWindow", "truncate_preview_text", "update_recent_paths"]


class MainWindow(MainWindowShellMixin):
    """Top-level application window for Git status and history browsing."""
