"""Size dataset rows to keep wrapped acquisition metadata visible."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate


class DatasetItemDelegate(QStyledItemDelegate):
    """Let narrow thumbnail rows grow with their metadata text."""

    def __init__(self, view: QListWidget) -> None:
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):  # noqa: N802
        """Measure wrapped text using the available viewport width."""
        if index.data(Qt.ItemDataRole.UserRole) is None:
            return super().sizeHint(option, index)
        width = self.view.viewport().width() - 12
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            width -= self.view.iconSize().width() + 6
        bounds = QFontMetrics(self.view.font()).boundingRect(
            0,
            0,
            max(40, width),
            0,
            Qt.TextFlag.TextWordWrap,
            str(index.data(Qt.ItemDataRole.DisplayRole)),
        )
        return QSize(
            self.view.viewport().width(), max(98, bounds.height() + 12)
        )
