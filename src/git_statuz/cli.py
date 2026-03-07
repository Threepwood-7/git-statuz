from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication
from threep_commons.paths import configure_qsettings, resolve_app_data_dir

from .constants import APP_IDENTITY, SETTINGS_APP_NAME, SETTINGS_ORG_NAME
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
    parser.add_argument(
        "--config-dir",
        dest="config_dir",
        default=None,
        help="Override QSettings INI root directory (also via CONFIG_DIR).",
    )
    parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help="Override runtime data root directory (also via DATA_DIR).",
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

    configure_qsettings(APP_IDENTITY, config_dir_override=args.config_dir)
    if args.data_dir:
        os.environ["DATA_DIR"] = args.data_dir
    resolve_app_data_dir(APP_IDENTITY, override_dir=args.data_dir)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName(SETTINGS_ORG_NAME)
    app.setApplicationName(SETTINGS_APP_NAME)
    window = MainWindow(
        repo_root=repo_root,
        winmerge_path=args.winmerge_path,
        history_limit=args.history_limit,
    )
    window.showMaximized()
    return app.exec()
