"""Typed data models shared across the GitStatuz application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HistoryContext = Literal["repo"] | str


@dataclass(slots=True, frozen=True)
class BranchStatus:
    """Branch state reported by Git for the current repository HEAD."""

    branch_name: str
    is_detached: bool
    upstream: str | None
    ahead: int
    behind: int


@dataclass(slots=True, frozen=True)
class FileStatus:
    """Normalized working-tree status for one repository-relative file."""

    repo_relpath: str
    is_tracked: bool
    is_untracked: bool
    is_ignored: bool
    is_staged: bool
    is_unstaged: bool
    is_conflicted: bool
    is_deleted: bool
    is_renamed: bool
    last_modified_iso: str | None = None


@dataclass(slots=True, frozen=True)
class CommitEntry:
    """One condensed commit-log row used in the history table."""

    short_sha: str
    author: str
    date_iso: str
    subject: str


@dataclass(slots=True, frozen=True)
class StatusCounts:
    """Aggregate counts derived from the current repository snapshot."""

    staged: int
    unstaged: int
    untracked: int
    conflicted: int
    ignored: int


@dataclass(slots=True, frozen=True)
class RepoSnapshot:
    """Complete repository snapshot used to refresh the main window state."""

    branch_status: BranchStatus
    file_statuses: list[FileStatus]
    counts: StatusCounts
    repo_history: list[CommitEntry]
    has_commits: bool
