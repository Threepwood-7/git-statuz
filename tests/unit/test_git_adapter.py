from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import threep_commons.subprocess_helpers as subprocess_helpers_module

from git_statuz import git_adapter as git_adapter_module
from git_statuz.git_adapter import (
    GitAdapter,
    parse_commit_log,
    parse_status_porcelain_v2,
)
from tests.conftest import commit_file, init_repo, run_git

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_repo_root_uses_create_no_window_on_windows(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}
    creation_flag = 0x08000000

    def fake_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=b"C:\\repos\\demo\n",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess_helpers_module.sys, "platform", "win32")
    monkeypatch.setattr(
        subprocess_helpers_module.subprocess,
        "CREATE_NO_WINDOW",
        creation_flag,
        raising=False,
    )
    monkeypatch.setattr(git_adapter_module.subprocess, "run", fake_run)

    resolved = git_adapter_module.resolve_repo_root("C:/repos/demo")

    assert resolved == "C:\\repos\\demo"
    assert captured_kwargs["creationflags"] == creation_flag


def test_run_git_uses_create_no_window_on_windows(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}
    creation_flag = 0x08000000

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(subprocess_helpers_module.sys, "platform", "win32")
    monkeypatch.setattr(
        subprocess_helpers_module.subprocess,
        "CREATE_NO_WINDOW",
        creation_flag,
        raising=False,
    )
    monkeypatch.setattr(git_adapter_module.subprocess, "run", fake_run)

    adapter = GitAdapter("C:/repos/demo", history_limit=30)
    adapter._run_git(["status"], text=True, check=False)

    assert captured_kwargs["creationflags"] == creation_flag


def test_run_git_does_not_set_creationflags_off_windows(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(subprocess_helpers_module.sys, "platform", "linux")
    monkeypatch.setattr(
        subprocess_helpers_module.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    monkeypatch.setattr(git_adapter_module.subprocess, "run", fake_run)

    adapter = GitAdapter("/tmp/demo", history_limit=30)
    adapter._run_git(["status"], text=True, check=False)

    assert "creationflags" not in captured_kwargs


def test_parse_status_porcelain_v2_covers_core_states() -> None:
    records = [
        "# branch.head main",
        "# branch.upstream origin/main",
        "# branch.ab +3 -2",
        "1 M. N... 100644 100644 100644 aaaaaaa bbbbbbb src/staged.txt",
        "1 .M N... 100644 100644 100644 aaaaaaa bbbbbbb src/unstaged.txt",
        "1 MM N... 100644 100644 100644 aaaaaaa bbbbbbb src/both.txt",
        "1 D. N... 100644 100644 100644 aaaaaaa bbbbbbb src/deleted.txt",
        "2 R. N... 100644 100644 100644 aaaaaaa bbbbbbb R100 src/new_name.txt",
        "src/old_name.txt",
        "u UU N... 100644 100644 100644 100644 aaaaaaa bbbbbbb ccccccc src/conflict.txt",
        "? src/untracked.txt",
        "! src/ignored.log",
    ]
    payload = ("\x00".join(records) + "\x00").encode("utf-8")

    branch, statuses = parse_status_porcelain_v2(payload)
    by_path = {item.repo_relpath: item for item in statuses}

    assert branch.branch_name == "main"
    assert branch.upstream == "origin/main"
    assert branch.ahead == 3
    assert branch.behind == 2

    assert by_path["src/staged.txt"].is_staged is True
    assert by_path["src/staged.txt"].is_unstaged is False

    assert by_path["src/unstaged.txt"].is_staged is False
    assert by_path["src/unstaged.txt"].is_unstaged is True

    assert by_path["src/both.txt"].is_staged is True
    assert by_path["src/both.txt"].is_unstaged is True

    assert by_path["src/deleted.txt"].is_deleted is True
    assert by_path["src/new_name.txt"].is_renamed is True
    assert by_path["src/conflict.txt"].is_conflicted is True
    assert by_path["src/untracked.txt"].is_untracked is True
    assert by_path["src/ignored.log"].is_ignored is True


def test_parse_status_detached_head() -> None:
    records = [
        "# branch.head (detached)",
        "1 .M N... 100644 100644 100644 aaaaaaa bbbbbbb file.txt",
    ]
    payload = ("\x00".join(records) + "\x00").encode("utf-8")
    branch, _ = parse_status_porcelain_v2(payload)
    assert branch.branch_name == "DETACHED"
    assert branch.is_detached is True


def test_parse_commit_log() -> None:
    payload = "\n".join(
        [
            "abc1234\x1fAlice\x1f2026-01-01T10:00:00+00:00\x1fInitial commit",
            "def5678\x1fBob\x1f2026-01-02T12:00:00+00:00\x1fUpdate README",
        ]
    )
    commits = parse_commit_log(payload)
    assert len(commits) == 2
    assert commits[0].short_sha == "abc1234"
    assert commits[1].subject == "Update README"


def test_load_snapshot_includes_tracked_unchanged_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_file(repo, "changed.txt", "hello\n", "init changed")
    commit_file(repo, "stable.txt", "stay\n", "init stable")
    (repo / "changed.txt").write_text("updated\n", encoding="utf-8")

    adapter = GitAdapter(str(repo), history_limit=30)
    snapshot = adapter.load_snapshot()
    by_path = {item.repo_relpath: item for item in snapshot.file_statuses}

    assert "changed.txt" in by_path
    assert "stable.txt" in by_path
    assert by_path["changed.txt"].is_unstaged is True
    assert by_path["stable.txt"].is_tracked is True
    assert by_path["stable.txt"].is_staged is False
    assert by_path["stable.txt"].is_unstaged is False
    assert by_path["changed.txt"].last_modified_iso is not None
    assert by_path["stable.txt"].last_modified_iso is not None
    assert len(by_path["changed.txt"].last_modified_iso) == 19
    assert len(by_path["stable.txt"].last_modified_iso) == 19
    assert by_path["changed.txt"].last_modified_iso[4] == "-"
    assert by_path["changed.txt"].last_modified_iso[7] == "-"
    assert by_path["changed.txt"].last_modified_iso[10] == " "
    assert by_path["changed.txt"].last_modified_iso[13] == ":"
    assert by_path["changed.txt"].last_modified_iso[16] == ":"


def test_load_file_diff_includes_unstaged_and_staged_sections(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_file(repo, "a.txt", "one\n", "init")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    run_git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("three\n", encoding="utf-8")

    adapter = GitAdapter(str(repo), history_limit=30)
    diff_text = adapter.load_file_diff("a.txt")

    assert "### Working Tree (unstaged)" in diff_text
    assert "### Index (staged)" in diff_text
    assert "diff --git a/a.txt b/a.txt" in diff_text


def test_load_repo_diff_empty_message_when_clean(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_file(repo, "a.txt", "one\n", "init")
    adapter = GitAdapter(str(repo), history_limit=30)
    assert adapter.load_repo_diff() == "No working tree/index diff."


def test_load_working_file_text_for_text_and_binary(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_file(repo, "a.txt", "one\n", "init")
    (repo / "new.txt").write_text("hello\n", encoding="utf-8")
    (repo / "binary.bin").write_bytes(b"\x00\x01\x02")

    adapter = GitAdapter(str(repo), history_limit=30)
    assert "hello" in adapter.load_working_file_text("new.txt")
    binary_preview = adapter.load_working_file_text("binary.bin")
    assert binary_preview.startswith("Binary file preview (hex):")
    assert "000102" in binary_preview


def test_load_working_file_text_truncates_to_limit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    long_content = "A" * 50
    commit_file(repo, "a.txt", "one\n", "init")
    (repo / "long.txt").write_text(long_content, encoding="utf-8")

    adapter = GitAdapter(str(repo), history_limit=30)
    preview = adapter.load_working_file_text("long.txt", max_preview_chars=20)
    assert preview.startswith("A" * 20)
    assert "Preview truncated at 20 bytes" in preview
