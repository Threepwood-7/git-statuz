from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

from threep_commons.subprocess_helpers import windows_no_window_run_kwargs

from .models import BranchStatus, CommitEntry, FileStatus, RepoSnapshot, StatusCounts

if TYPE_CHECKING:
    from collections.abc import Sequence


class GitCommandError(RuntimeError):
    """Raised when a git command fails."""


def _no_window_run_options() -> tuple[Any | None, int]:
    run_kwargs = windows_no_window_run_kwargs()
    startupinfo = run_kwargs.get("startupinfo")
    raw_creationflags = run_kwargs.get("creationflags", 0)
    creationflags = raw_creationflags if isinstance(raw_creationflags, int) else 0
    return startupinfo, creationflags


def resolve_repo_root(path: str | Path) -> str:
    path_str = str(path)
    startupinfo, creationflags = _no_window_run_options()
    proc: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "-C", path_str, "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise GitCommandError(
            stderr or f"Unable to resolve git repository root for: {path_str}"
        )
    return proc.stdout.decode("utf-8", "replace").strip()


def _is_staged(xy: str) -> bool:
    return len(xy) >= 2 and xy[0] != "."


def _is_unstaged(xy: str) -> bool:
    return len(xy) >= 2 and xy[1] != "."


def _is_conflicted_xy(xy: str) -> bool:
    if len(xy) < 2:
        return False
    conflict_pairs = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    return "U" in xy or xy in conflict_pairs


def _make_tracked_file_status(
    repo_relpath: str, xy: str, renamed: bool = False, conflicted: bool = False
) -> FileStatus:
    merged_conflicted = conflicted or _is_conflicted_xy(xy)
    return FileStatus(
        repo_relpath=repo_relpath,
        is_tracked=True,
        is_untracked=False,
        is_ignored=False,
        is_staged=_is_staged(xy),
        is_unstaged=_is_unstaged(xy),
        is_conflicted=merged_conflicted,
        is_deleted="D" in xy,
        is_renamed=renamed or "R" in xy,
    )


def parse_status_porcelain_v2(  # noqa: C901 - parser mirrors git porcelain v2 state handling
    payload: bytes,
) -> tuple[BranchStatus, list[FileStatus]]:
    branch_name = "UNKNOWN"
    is_detached = False
    upstream: str | None = None
    ahead = 0
    behind = 0
    file_statuses: list[FileStatus] = []

    entries = payload.split(b"\x00")
    i = 0
    while i < len(entries):
        raw_entry = entries[i]
        i += 1
        if not raw_entry:
            continue

        entry = raw_entry.decode("utf-8", "surrogateescape")
        if entry.startswith("# "):
            if entry.startswith("# branch.head "):
                branch_value = entry[len("# branch.head ") :]
                if branch_value == "(detached)":
                    branch_name = "DETACHED"
                    is_detached = True
                else:
                    branch_name = branch_value
                    is_detached = False
            elif entry.startswith("# branch.upstream "):
                upstream = entry[len("# branch.upstream ") :]
            elif entry.startswith("# branch.ab "):
                suffix = entry[len("# branch.ab ") :]
                parts = suffix.split(" ")
                if len(parts) == 2:
                    try:
                        ahead = int(parts[0].lstrip("+"))
                        behind = int(parts[1].lstrip("-"))
                    except ValueError:
                        ahead = 0
                        behind = 0
            continue

        record_type = entry[:1]
        if record_type == "1":
            parts = entry.split(" ", 8)
            if len(parts) < 9:
                continue
            xy = parts[1]
            path = parts[8]
            file_statuses.append(_make_tracked_file_status(path, xy))
        elif record_type == "2":
            parts = entry.split(" ", 9)
            if len(parts) < 10:
                continue
            xy = parts[1]
            path = parts[9]
            # Renamed/copied records in -z format have the original path in the next entry.
            if i < len(entries):
                i += 1
            file_statuses.append(_make_tracked_file_status(path, xy, renamed=True))
        elif record_type == "u":
            parts = entry.split(" ", 10)
            if len(parts) < 11:
                continue
            xy = parts[1]
            path = parts[10]
            file_statuses.append(_make_tracked_file_status(path, xy, conflicted=True))
        elif record_type == "?":
            path = entry[2:] if entry.startswith("? ") else entry[1:].lstrip()
            file_statuses.append(
                FileStatus(
                    repo_relpath=path,
                    is_tracked=False,
                    is_untracked=True,
                    is_ignored=False,
                    is_staged=False,
                    is_unstaged=False,
                    is_conflicted=False,
                    is_deleted=False,
                    is_renamed=False,
                )
            )
        elif record_type == "!":
            path = entry[2:] if entry.startswith("! ") else entry[1:].lstrip()
            file_statuses.append(
                FileStatus(
                    repo_relpath=path,
                    is_tracked=False,
                    is_untracked=False,
                    is_ignored=True,
                    is_staged=False,
                    is_unstaged=False,
                    is_conflicted=False,
                    is_deleted=False,
                    is_renamed=False,
                )
            )

    branch_status = BranchStatus(
        branch_name=branch_name,
        is_detached=is_detached,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
    )
    return branch_status, file_statuses


def parse_commit_log(payload: str) -> list[CommitEntry]:
    commits: list[CommitEntry] = []
    for raw_line in payload.splitlines():
        if not raw_line:
            continue
        parts = raw_line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        short_sha, author, date_iso, subject = parts
        commits.append(
            CommitEntry(
                short_sha=short_sha,
                author=author,
                date_iso=date_iso,
                subject=subject,
            )
        )
    return commits


def _compose_diff_output(
    unstaged_patch: str, staged_patch: str, empty_message: str
) -> str:
    sections: list[str] = []
    if unstaged_patch.strip():
        sections.append(f"### Working Tree (unstaged)\n{unstaged_patch.rstrip()}")
    if staged_patch.strip():
        sections.append(f"### Index (staged)\n{staged_patch.rstrip()}")
    if not sections:
        return empty_message
    return "\n\n".join(sections) + "\n"


class GitAdapter:
    def __init__(self, repo_root: str, history_limit: int = 30) -> None:
        self.repo_root = repo_root
        self.history_limit = history_limit

    def _working_tree_last_modified_sql_timestamp(
        self, repo_relpath: str
    ) -> str | None:
        file_path = Path(self.repo_root) / repo_relpath
        if not file_path.is_file():
            return None
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            return None
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    @overload
    def _run_git(
        self,
        args: Sequence[str],
        *,
        text: Literal[True] = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...

    @overload
    def _run_git(
        self,
        args: Sequence[str],
        *,
        text: Literal[False],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]: ...

    def _run_git(
        self,
        args: Sequence[str],
        *,
        text: bool = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
        startupinfo, creationflags = _no_window_run_options()
        if text:
            text_proc = subprocess.run(
                ["git", "-C", self.repo_root, *args],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            if check and text_proc.returncode != 0:
                raise GitCommandError(
                    text_proc.stderr.strip() or f"git command failed: {' '.join(args)}"
                )
            return text_proc

        bytes_proc = subprocess.run(
            ["git", "-C", self.repo_root, *args],
            capture_output=True,
            check=False,
            text=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        if check and bytes_proc.returncode != 0:
            raise GitCommandError(
                bytes_proc.stderr.decode("utf-8", "replace").strip()
                or f"git command failed: {' '.join(args)}"
            )
        return bytes_proc

    def has_head(self) -> bool:
        proc = self._run_git(["rev-parse", "--verify", "HEAD"], text=True, check=False)
        return proc.returncode == 0

    def load_snapshot(self) -> RepoSnapshot:
        status_proc = self._run_git(
            ["status", "--porcelain=v2", "--branch", "-z", "--ignored=matching"],
            text=False,
        )
        assert isinstance(status_proc.stdout, bytes)
        branch_status, file_statuses = parse_status_porcelain_v2(status_proc.stdout)

        status_by_path = {item.repo_relpath: item for item in file_statuses}
        for tracked_path in self.load_tracked_paths():
            if tracked_path in status_by_path:
                continue
            status_by_path[tracked_path] = FileStatus(
                repo_relpath=tracked_path,
                is_tracked=True,
                is_untracked=False,
                is_ignored=False,
                is_staged=False,
                is_unstaged=False,
                is_conflicted=False,
                is_deleted=False,
                is_renamed=False,
            )
        file_statuses = [
            replace(
                item,
                last_modified_iso=self._working_tree_last_modified_sql_timestamp(
                    item.repo_relpath
                ),
            )
            for item in status_by_path.values()
        ]

        counts = StatusCounts(
            staged=sum(1 for f in file_statuses if f.is_staged and not f.is_conflicted),
            unstaged=sum(
                1 for f in file_statuses if f.is_unstaged and not f.is_conflicted
            ),
            untracked=sum(1 for f in file_statuses if f.is_untracked),
            conflicted=sum(1 for f in file_statuses if f.is_conflicted),
            ignored=sum(1 for f in file_statuses if f.is_ignored),
        )

        has_commits = self.has_head()
        repo_history = self.load_repo_history() if has_commits else []
        return RepoSnapshot(
            branch_status=branch_status,
            file_statuses=file_statuses,
            counts=counts,
            repo_history=repo_history,
            has_commits=has_commits,
        )

    def load_tracked_paths(self) -> list[str]:
        proc = self._run_git(["ls-files", "-z"], text=False)
        assert isinstance(proc.stdout, bytes)
        return [
            segment.decode("utf-8", "surrogateescape")
            for segment in proc.stdout.split(b"\x00")
            if segment
        ]

    def load_repo_history(self) -> list[CommitEntry]:
        proc = self._run_git(
            [
                "log",
                "-n",
                str(self.history_limit),
                "--date=iso-strict",
                "--pretty=format:%h%x1f%an%x1f%ad%x1f%s",
                "HEAD",
            ],
            text=True,
        )
        assert isinstance(proc.stdout, str)
        return parse_commit_log(proc.stdout)

    def load_file_history(self, repo_relpath: str) -> list[CommitEntry]:
        if not self.has_head():
            return []
        proc = self._run_git(
            [
                "log",
                "-n",
                str(self.history_limit),
                "--follow",
                "--date=iso-strict",
                "--pretty=format:%h%x1f%an%x1f%ad%x1f%s",
                "--",
                repo_relpath,
            ],
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        assert isinstance(proc.stdout, str)
        return parse_commit_log(proc.stdout)

    def get_head_file_bytes(self, repo_relpath: str) -> bytes:
        proc = self._run_git(["show", f"HEAD:{repo_relpath}"], text=False)
        assert isinstance(proc.stdout, bytes)
        return proc.stdout

    def load_repo_diff(self) -> str:
        has_head = self.has_head()
        unstaged_proc = self._run_git(
            ["diff", "--patch", "--no-color"], text=True, check=False
        )
        staged_args = ["diff", "--cached", "--patch", "--no-color"]
        if not has_head:
            staged_args.insert(1, "--root")
        staged_proc = self._run_git(staged_args, text=True, check=False)

        assert isinstance(unstaged_proc.stdout, str)
        assert isinstance(staged_proc.stdout, str)
        return _compose_diff_output(
            unstaged_patch=unstaged_proc.stdout,
            staged_patch=staged_proc.stdout,
            empty_message="No working tree/index diff.",
        )

    def load_file_diff(self, repo_relpath: str) -> str:
        has_head = self.has_head()
        unstaged_args = ["diff", "--patch", "--no-color", "--", repo_relpath]
        unstaged_proc = self._run_git(unstaged_args, text=True, check=False)

        staged_args = ["diff", "--cached", "--patch", "--no-color"]
        if not has_head:
            staged_args.insert(1, "--root")
        staged_args.extend(["--", repo_relpath])
        staged_proc = self._run_git(staged_args, text=True, check=False)

        assert isinstance(unstaged_proc.stdout, str)
        assert isinstance(staged_proc.stdout, str)
        return _compose_diff_output(
            unstaged_patch=unstaged_proc.stdout,
            staged_patch=staged_proc.stdout,
            empty_message="No diff for selected file.",
        )

    def load_working_file_text(
        self, repo_relpath: str, max_preview_chars: int = 512 * 1024
    ) -> str:
        file_path = Path(self.repo_root) / repo_relpath
        if not file_path.exists():
            return "File does not exist in working tree."
        if file_path.is_dir():
            return "Directory preview is not supported."

        sniff_size = 65_536
        max_text_bytes = max_preview_chars
        max_binary_bytes = max(1, max_preview_chars // 2)

        with file_path.open("rb") as handle:
            sample = handle.read(sniff_size)
            is_binary = b"\x00" in sample
            handle.seek(0)

            if is_binary:
                payload = handle.read(max_binary_bytes + 1)
                truncated = len(payload) > max_binary_bytes
                if truncated:
                    payload = payload[:max_binary_bytes]
                hex_body = payload.hex()
                preview = f"Binary file preview (hex):\n{hex_body}"
                if truncated:
                    preview = f"{preview}\n\n[Preview truncated at {max_binary_bytes} bytes before hex conversion]"
                return preview

            payload = handle.read(max_text_bytes + 1)
            truncated = len(payload) > max_text_bytes
            if truncated:
                payload = payload[:max_text_bytes]
            text = payload.decode("utf-8", "replace")
            if truncated:
                text = f"{text}\n\n[Preview truncated at {max_text_bytes} bytes]"
            return text
