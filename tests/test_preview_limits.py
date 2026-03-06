from __future__ import annotations

from git_statuz.ui.main_window import truncate_preview_text


def test_truncate_preview_text_limits_length_and_marks_truncation() -> None:
    source = "x" * 100
    result = truncate_preview_text(source, max_chars=64)
    assert len(result) <= 64
    assert "Preview truncated at 64 characters" in result


def test_truncate_preview_text_passthrough() -> None:
    source = "short"
    assert truncate_preview_text(source, max_chars=32) == source
