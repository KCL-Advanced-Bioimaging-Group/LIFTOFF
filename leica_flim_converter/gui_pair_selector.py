"""Expandable excitation/emission choices for recorded pairs."""

from collections.abc import Iterable
from typing import Protocol, cast, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from .dataset import DatasetInfo
from .gui_models import connect_signal


# Passive binding contract; native C++ field names must be preserved.
# pylint: disable-next=too-few-public-methods
class _ViewOptionFields(Protocol):
    """Type the C++ fields missing from generated PySide stubs."""

    features: QStyleOptionViewItem.ViewItemFeature
    textElideMode: Qt.TextElideMode  # noqa: N815
    rect: QRect
    widget: QWidget | None
    state: QStyle.StateFlag


def view_option_fields(option: QStyleOptionViewItem) -> _ViewOptionFields:
    """Access mutable fields of the native style option."""
    return cast(_ViewOptionFields, option)


def _emission_disabled(index: QModelIndex | QPersistentModelIndex) -> bool:
    """Resolve emission availability from the excitation checkbox."""
    if index.column() != 1:
        return False
    root = index.parent() if index.parent().isValid() else index
    state = root.sibling(root.row(), 0).data(Qt.ItemDataRole.CheckStateRole)
    return state not in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)


class PairItemDelegate(QStyledItemDelegate):
    """Wrap scientific labels without hiding detector text."""

    @override
    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        /,
    ) -> QSize:
        parent = self.parent()
        if not isinstance(parent, QTreeWidget):
            return super().sizeHint(option, index)
        available = parent.columnWidth(index.column()) - 30
        if index.column() == 0:
            available -= parent.indentation()
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        bounds = QFontMetrics(parent.font()).boundingRect(
            QRect(0, 0, max(32, available), 10000),
            Qt.TextFlag.TextWordWrap,
            text,
        )
        return QSize(max(32, available), max(22, bounds.height() + 8))

    @override
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        /,
    ) -> None:
        wrapped = QStyleOptionViewItem(option)
        self.initStyleOption(wrapped, index)
        fields = view_option_fields(wrapped)
        fields.features |= QStyleOptionViewItem.ViewItemFeature.WrapText
        fields.textElideMode = Qt.TextElideMode.ElideNone
        if _emission_disabled(index):
            fields.state &= ~QStyle.StateFlag.State_Enabled
        widget = fields.widget
        if widget is not None:
            widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem, wrapped, painter, widget
            )
        else:
            super().paint(painter, wrapped, index)

    @override
    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        /,
    ) -> bool:
        """Reject interaction with an inactive emission cell."""
        if _emission_disabled(index):
            return True
        return super().editorEvent(event, model, option, index)


class RecordedPairSelector(QTreeWidget):
    """Select emissions under independently enabled excitations."""

    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recordedPairSelector")
        self.setColumnCount(2)
        self.setHeaderLabels(["Excitation", "Emission"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setUniformRowHeights(False)
        self.setItemDelegate(PairItemDelegate(self))
        self.setIndentation(14)
        self.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(0, 135)
        self.setToolTip(
            "Check excitation settings, then choose their emission channels. "
            "Selected pairs are displayed side by side."
        )
        self.datasets: tuple[DatasetInfo, ...] = ()
        self.excitation_items: dict[int, QTreeWidgetItem] = {}
        self.emission_items: dict[str, QTreeWidgetItem] = {}
        connect_signal(self.itemChanged, self._item_changed)
        connect_signal(self.itemExpanded, self._resize_height)
        connect_signal(self.itemCollapsed, self._resize_height)
        connect_signal(self.header().sectionResized, self._resize_height)

    def set_datasets(
        self, datasets: Iterable[DatasetInfo], preserve: bool = False
    ) -> None:
        """Populate sequences and preserve acquisition choices."""
        checked = (
            {
                index: item.checkState(0)
                for index, item in self.excitation_items.items()
            }
            if preserve
            else {}
        )
        emissions = (
            {
                key: item.checkState(1)
                for key, item in self.emission_items.items()
            }
            if preserve
            else {}
        )
        expanded = (
            {
                index: item.isExpanded()
                for index, item in self.excitation_items.items()
            }
            if preserve
            else {}
        )
        self.blockSignals(True)
        self.clear()
        self.datasets = tuple(datasets)
        self.excitation_items = {}
        self.emission_items = {}
        for dataset in self.datasets:
            sequence = dataset.sequence_index
            parent = self.excitation_items.get(sequence)
            if parent is None:
                parent = QTreeWidgetItem([dataset.excitation_label, ""])
                parent.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                )
                parent.setToolTip(0, dataset.sequence_label)
                self.addTopLevelItem(parent)
                default = (
                    Qt.CheckState.Checked
                    if not self.excitation_items
                    else Qt.CheckState.Unchecked
                )
                parent.setCheckState(0, checked.get(sequence, default))
                parent.setExpanded(expanded.get(sequence, True))
                self.excitation_items[sequence] = parent
            # Align the first emission with its excitation; additional
            # emissions retain child rows and an expansion arrow.
            emission = (
                parent if not parent.text(1) else QTreeWidgetItem(parent)
            )
            emission.setText(
                1,
                f"{dataset.emission_filter_band} "
                f"({dataset.detector_name or 'Unknown detector'})",
            )
            emission.setToolTip(
                1, f"Ex. {dataset.excitation_label} / Em. {emission.text(1)}"
            )
            emission.setCheckState(
                1, emissions.get(dataset.key, Qt.CheckState.Checked)
            )
            self.emission_items[dataset.key] = emission
            self._sync_emissions(parent)
        self.blockSignals(False)
        self.setVisible(bool(self.datasets))
        self._resize_height()

    @staticmethod
    def _sync_emissions(parent: QTreeWidgetItem) -> None:
        enabled = parent.checkState(0) == Qt.CheckState.Checked
        flags = (
            Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemNeverHasChildren
        )
        if enabled:
            flags |= Qt.ItemFlag.ItemIsEnabled
        for index in range(parent.childCount()):
            parent.child(index).setFlags(flags)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is None and column == 0:
            self.blockSignals(True)
            self._sync_emissions(item)
            self.blockSignals(False)
        self.selection_changed.emit()

    def selected_datasets(self) -> tuple[DatasetInfo, ...]:
        """Return only recorded pairs whose two choices are checked."""
        return tuple(
            dataset
            for dataset in self.datasets
            if self.excitation_items[dataset.sequence_index].checkState(0)
            == Qt.CheckState.Checked
            and self.emission_items[dataset.key].checkState(1)
            == Qt.CheckState.Checked
        )

    def emission_enabled(self, key: str) -> bool:
        """Report whether an emission cell can be selected."""
        item = self.emission_items[key]
        return self.isEnabled() and not _emission_disabled(
            self.indexFromItem(item, 1)
        )

    def set_selection(self, keys: Iterable[str]) -> None:
        """Apply a group of pair choices in one selection transition."""
        selected = set(keys)
        self.blockSignals(True)
        for sequence, parent in self.excitation_items.items():
            active = any(
                dataset.key in selected
                for dataset in self.datasets
                if dataset.sequence_index == sequence
            )
            parent.setCheckState(
                0, Qt.CheckState.Checked if active else Qt.CheckState.Unchecked
            )
            if active:
                for dataset in self.datasets:
                    if dataset.sequence_index == sequence:
                        self.emission_items[dataset.key].setCheckState(
                            1,
                            Qt.CheckState.Checked
                            if dataset.key in selected
                            else Qt.CheckState.Unchecked,
                        )
            self._sync_emissions(parent)
        self.blockSignals(False)
        self.selection_changed.emit()

    def _resize_height(self, *_args) -> None:
        items = []
        for parent in self.excitation_items.values():
            items.append(parent)
            if parent.isExpanded():
                items.extend(
                    parent.child(index) for index in range(parent.childCount())
                )
        self.doItemsLayout()
        content_height = sum(
            self.visualItemRect(item).height() for item in items
        )
        target = min(
            260,
            self.header().height() + content_height + 2 * self.frameWidth(),
        )
        if self.height() != target:
            self.setFixedHeight(target)
