from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from .git_adapter import GitCommandError, resolve_repo_root
from .ui.main_window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitstatuz",
        description="PySide viewer for Git status and history.",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        default=None,
        help="Path inside a Git working tree. Defaults to current directory.",
    )
    parser.add_argument(
        "--winmerge",
        dest="winmerge_path",
        default=None,
        help="Optional explicit path to WinMergeU executable.",
    )
    parser.add_argument(
        "--history-limit",
        dest="history_limit",
        type=int,
        default=30,
        help="History rows to load for repo and file views (default: 30).",
    )
    return parser


def resolve_input_repo(input_path: str | None) -> str:
    target = input_path or os.getcwd()
    return resolve_repo_root(target)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        repo_root = resolve_input_repo(args.input_path)
    except GitCommandError as exc:
        parser.exit(status=2, message=f"error: {exc}\n")

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("gitstatuz")
    app.setApplicationName("gitstatuz")
    window = MainWindow(
        repo_root=repo_root,
        winmerge_path=args.winmerge_path,
        history_limit=args.history_limit,
    )
    window.showMaximized()
    return app.exec()
