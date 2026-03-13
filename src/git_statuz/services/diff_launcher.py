"""Helpers for opening files or launching external diff tools."""

from __future__ import annotations

import atexit
import contextlib
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from threep_commons.desktop import open_path_in_default_app
from threep_commons.executables import (
    find_first_available_executable,
    program_files_candidates,
)

if TYPE_CHECKING:
    from ..git_adapter import GitAdapter
    from ..models import FileStatus


def resolve_winmerge_path(preferred_path: str | None = None) -> str | None:
    """Resolve the preferred or discovered WinMerge executable path."""
    resolved = find_first_available_executable(
        preferred=preferred_path,
        command_names=("WinMergeU.exe", "WinMergeU"),
        candidate_paths=program_files_candidates(Path("WinMerge") / "WinMergeU.exe"),
    )
    return str(resolved) if resolved is not None else None


class DiffLauncher:
    """Open files in the default editor or launch WinMerge for comparisons."""

    def __init__(self, repo_root: str, winmerge_path: str | None = None) -> None:
        self.repo_root = Path(repo_root)
        self.winmerge_path = resolve_winmerge_path(winmerge_path)
        self._temp_files: list[str] = []
        atexit.register(self._cleanup_temp_files)

    def _cleanup_temp_files(self) -> None:
        for path in self._temp_files:
            with contextlib.suppress(OSError):
                Path(path).unlink(missing_ok=True)
        self._temp_files.clear()

    def _new_temp_file(self, payload: bytes, suffix: str) -> str:
        with tempfile.NamedTemporaryFile(
            prefix="gitstatuz_", suffix=suffix, delete=False
        ) as handle:
            handle.write(payload)
            tmp = handle.name
        self._temp_files.append(tmp)
        return tmp

    def _open_default_editor(self, file_path: Path) -> None:
        if not file_path.exists():
            raise RuntimeError(f"Working-tree file does not exist: {file_path}")
        if open_path_in_default_app(file_path):
            return
        raise RuntimeError("Unable to open default editor on this platform.")

    def open_for_file(self, file_status: FileStatus, git_adapter: GitAdapter) -> None:
        file_path = self.repo_root / file_status.repo_relpath
        suffix = Path(file_status.repo_relpath).suffix

        if file_status.is_untracked or file_status.is_ignored:
            self._open_default_editor(file_path)
            return

        if self.winmerge_path:
            left_payload = b""
            if git_adapter.has_head():
                try:
                    left_payload = git_adapter.get_head_file_bytes(
                        file_status.repo_relpath
                    )
                except Exception:
                    left_payload = b""
            left_path = self._new_temp_file(left_payload, suffix)

            if file_path.exists():
                right_path = str(file_path)
            else:
                right_path = self._new_temp_file(b"", suffix)

            subprocess.Popen([self.winmerge_path, left_path, right_path])
            return

        self._open_default_editor(file_path)
