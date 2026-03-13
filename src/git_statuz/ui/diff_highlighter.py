"""Syntax highlighting helpers for Git diff and preview text."""

from __future__ import annotations

from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)


class GitDiffHighlighter(QSyntaxHighlighter):
    """Apply lightweight color formatting to Git diff previews."""

    def __init__(self, parent: QTextDocument) -> None:
        super().__init__(parent)
        self._format_header = QTextCharFormat()
        self._format_header.setForeground(QColor("#1F3A5F"))
        self._format_header.setFontWeight(QFont.Weight.Bold)

        self._format_hunk = QTextCharFormat()
        self._format_hunk.setForeground(QColor("#7A4E0F"))
        self._format_hunk.setFontWeight(QFont.Weight.Bold)

        self._format_added = QTextCharFormat()
        self._format_added.setForeground(QColor("#1E8449"))
        self._format_added.setBackground(QColor("#E9F7EF"))

        self._format_removed = QTextCharFormat()
        self._format_removed.setForeground(QColor("#C0392B"))
        self._format_removed.setBackground(QColor("#FDEDEC"))

        self._format_meta = QTextCharFormat()
        self._format_meta.setForeground(QColor("#2471A3"))

    def highlightBlock(self, text: str) -> None:
        if (
            text.startswith("+++ ")
            or text.startswith("--- ")
            or text.startswith("diff --git ")
            or text.startswith("index ")
        ):
            self.setFormat(0, len(text), self._format_header)
            return
        if text.startswith("@@"):
            self.setFormat(0, len(text), self._format_hunk)
            return
        if text.startswith("+") and not text.startswith("+++ "):
            self.setFormat(0, len(text), self._format_added)
            return
        if text.startswith("-") and not text.startswith("--- "):
            self.setFormat(0, len(text), self._format_removed)
            return
        if text.startswith("### ") or text.startswith("Binary files "):
            self.setFormat(0, len(text), self._format_meta)
