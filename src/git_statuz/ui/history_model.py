from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QStandardItem, QStandardItemModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models import CommitEntry


class HistoryTableModel(QStandardItemModel):
    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalHeaderLabels(["SHA", "Date", "Author", "Subject"])

    def set_commits(self, commits: Sequence[CommitEntry]) -> None:
        self.removeRows(0, self.rowCount())
        for entry in commits:
            self.appendRow(
                [
                    QStandardItem(entry.short_sha),
                    QStandardItem(entry.date_iso),
                    QStandardItem(entry.author),
                    QStandardItem(entry.subject),
                ]
            )

    def set_empty_message(self, message: str) -> None:
        self.removeRows(0, self.rowCount())
        self.appendRow(
            [
                QStandardItem(""),
                QStandardItem(""),
                QStandardItem(""),
                QStandardItem(message),
            ]
        )

