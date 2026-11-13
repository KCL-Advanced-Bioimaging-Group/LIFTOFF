"""Concise details headings describe only displayed wavelengths."""

from dataclasses import replace

from PySide6.QtGui import QFont, QTextCursor, QTextDocument
from pytestqt.qtbot import QtBot

from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui_helpers import summary_heading


def test_entry_name_is_the_only_bold_text(
    raw_dataset: DatasetInfo, qtbot: QtBot
) -> None:
    """Keep names literal and omit detector, source and memory text."""
    del qtbot
    dataset = replace(
        raw_dataset,
        acquisition_name="IAHF <1> & control",
        excitation_wavelengths_nm=(735.0,),
        excitation_sources=("MP2",),
        emission_filter_band="440 - 500 nm",
        detector_name="HyD NDD 2",
    )
    text = summary_heading(dataset, (dataset,))
    document = QTextDocument()
    document.setHtml(text)
    name = dataset.acquisition_name or ""
    assert document.toPlainText() == (f"{name} | Ex. 735 nm / Em. 440-500 nm")
    assert text.startswith("<b>IAHF &lt;1&gt; &amp; control</b>")
    cursor = QTextCursor(document)
    cursor.setPosition(1)
    assert cursor.charFormat().fontWeight() == QFont.Weight.Bold
    cursor.setPosition(len(name) + 5)
    assert cursor.charFormat().fontWeight() == QFont.Weight.Normal


def test_multiple_displayed_wavelengths(raw_dataset: DatasetInfo) -> None:
    """Deduplicate tiles and group emissions under their excitation."""
    first = replace(
        raw_dataset,
        acquisition_name="IAHF",
        excitation_wavelengths_nm=(735.0,),
        emission_filter_band="440 - 500 nm",
    )
    second = replace(first, emission_filter_band="530 - 600 nm")
    third = replace(second, excitation_wavelengths_nm=(1040.0,))
    assert summary_heading(first, (first, second, first, third)) == (
        "<b>IAHF</b> | Ex. 735 nm / Em. 440-500 nm, 530-600 nm"
        " | Ex. 1040 nm / Em. 530-600 nm"
    )
    assert summary_heading(first, (second,)) == (
        "<b>IAHF</b> | Ex. 735 nm / Em. 530-600 nm"
    )
    assert summary_heading(first, ()) == "<b>IAHF</b>"


def test_wavelength_rounding_and_missing_metadata(
    raw_dataset: DatasetInfo,
) -> None:
    """Retain nominal wavelength policy without inventing settings."""
    mixed = replace(
        raw_dataset,
        acquisition_name=None,
        excitation_wavelengths_nm=(488.5, 560.6),
        excitation_sources=("WLL", "WLL"),
    )
    assert summary_heading(mixed, (mixed,)) == (
        "<b>synthetic</b> | Ex. 489 / 561 nm / Em. unavailable"
    )
    missing = replace(mixed, excitation_wavelengths_nm=())
    assert summary_heading(missing, (missing,)) == (
        "<b>synthetic</b> | Ex. unavailable / Em. unavailable"
    )
