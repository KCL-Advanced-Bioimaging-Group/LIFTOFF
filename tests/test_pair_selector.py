"""User checkbox interactions and arbitrary pair selections."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidgetItem,
)
from pytestqt.qtbot import QtBot

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui_pair_selector import (
    RecordedPairSelector,
    view_option_fields,
)
from tests.sequence_fixture import mixed_lif


def click_checkbox(
    tree: RecordedPairSelector,
    item: QTreeWidgetItem,
    column: int,
    qtbot: QtBot,
) -> None:
    """Use the native checkbox geometry, including disabled rows."""
    tree.scrollToItem(item)
    qtbot.wait(10)
    index = tree.indexFromItem(item, column)
    option = QStyleOptionViewItem()
    delegate = tree.itemDelegate()
    assert isinstance(delegate, QStyledItemDelegate)
    delegate.initStyleOption(option, index)
    view_option_fields(option).rect = tree.visualRect(index)
    rectangle = tree.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree
    )
    QTest.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rectangle.center(),
    )


def test_enabled_choices_and_expansion(tmp_path: Path, qtbot: QtBot) -> None:
    """Disabled emissions reject clicks; expansion preserves choices."""
    datasets = scan_lif(mixed_lif(tmp_path / "mixed.lif"))
    tree = RecordedPairSelector()
    qtbot.addWidget(tree)
    tree.resize(390, 230)
    tree.set_datasets(datasets)
    tree.show()
    assert tree.selected_datasets() == tuple(datasets[:2])
    for sequence in (0, 1):
        parent = tree.excitation_items[sequence]
        first_emission = tree.emission_items[datasets[sequence * 2].key]
        assert first_emission is parent
        assert (
            tree.visualRect(tree.indexFromItem(parent, 0)).center().y()
            == tree.visualRect(tree.indexFromItem(first_emission, 1))
            .center()
            .y()
        )
    first_inactive = tree.emission_items[datasets[2].key]
    assert not tree.emission_enabled(datasets[2].key)
    click_checkbox(tree, first_inactive, 1, qtbot)
    assert tree.selected_datasets() == tuple(datasets[:2])
    tree.setCurrentItem(first_inactive, 1)
    assert tree.currentIndex() == tree.indexFromItem(first_inactive, 1)
    QTest.keyClick(tree, Qt.Key.Key_Space)
    assert first_inactive.checkState(1) == Qt.CheckState.Checked
    assert tree.selected_datasets() == tuple(datasets[:2])
    inactive = tree.emission_items[datasets[3].key]
    click_checkbox(tree, inactive, 1, qtbot)
    assert inactive.checkState(1) == Qt.CheckState.Checked
    assert tree.selected_datasets() == tuple(datasets[:2])
    click_checkbox(tree, tree.excitation_items[1], 0, qtbot)
    assert tree.selected_datasets() == tuple(datasets)
    assert inactive.flags() & Qt.ItemFlag.ItemIsEnabled
    assert tree.emission_enabled(datasets[2].key)
    click_checkbox(tree, tree.emission_items[datasets[1].key], 1, qtbot)
    click_checkbox(tree, tree.emission_items[datasets[2].key], 1, qtbot)
    assert tree.excitation_items[1].checkState(0) == Qt.CheckState.Checked
    assert tree.selected_datasets() == (datasets[0], datasets[3])
    expanded_height = tree.height()
    tree.excitation_items[0].setExpanded(False)
    assert tree.height() < expanded_height
    assert tree.selected_datasets() == (datasets[0], datasets[3])
    tree.set_datasets(datasets, preserve=True)
    assert not tree.excitation_items[0].isExpanded()
    assert tree.selected_datasets() == (datasets[0], datasets[3])
    click_checkbox(tree, tree.excitation_items[1], 0, qtbot)
    assert tree.selected_datasets() == (datasets[0],)
    assert (
        not tree.emission_items[datasets[3].key].flags()
        & Qt.ItemFlag.ItemIsEnabled
    )
    click_checkbox(tree, tree.excitation_items[1], 0, qtbot)
    assert tree.selected_datasets() == (datasets[0], datasets[3])
    tree.set_selection(())
    assert not tree.selected_datasets()


def test_simultaneous_wavelengths_remain_one_setting(
    raw_dataset: DatasetInfo, qtbot: QtBot
) -> None:
    """Keep simultaneous lasers together as one recorded setting."""
    tree = RecordedPairSelector()
    qtbot.addWidget(tree)
    dataset = replace(
        raw_dataset,
        excitation_wavelengths_nm=(488, 561),
        excitation_sources=("WLL", "WLL"),
    )
    tree.set_datasets([dataset])
    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert item is not None
    assert item.text(0) == "488 nm (WLL) / 561 nm (WLL)"
    assert tree.selected_datasets() == (dataset,)
    assert tree.emission_items[dataset.key] is item
    assert item.childCount() == 0
    tree.show()
    qtbot.wait(1)
    assert tree.viewport().height() == tree.visualItemRect(item).height()
