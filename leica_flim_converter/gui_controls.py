"""Maintained desktop component: controls."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .event_flags import (
    COMPRESSED_MODES,
    PRIMARY_EVENT_FLAGS,
    RAW_MODES,
    SELECTION_NAMES,
    normalize_selection,
)
from .gui_models import connect_signal


class EventFlagSelector(QWidget):
    """Expose the same three scientific modes for both source
    grammars.
    """

    selection_busy: bool
    buttons: QButtonGroup
    selection_label: QLabel
    changed = Signal(int)

    def __init__(
        self, mask=PRIMARY_EVENT_FLAGS, parent=None, *, vertical=False
    ):
        super().__init__(parent)
        self._lmsraw_mode = int(mask) in RAW_MODES
        self.selection_busy = False
        self.checks = {}
        self.preset_buttons = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        row = QWidget(self)
        controls = QVBoxLayout(row) if vertical else QHBoxLayout(row)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4 if vertical else 8)
        self.buttons = QButtonGroup(self)
        self.raw_all, self.raw_first, self.raw_standard = (
            QRadioButton(label, self) for label in SELECTION_NAMES
        )
        self.raw_single = self.raw_standard
        for index, button in enumerate(
            (self.raw_all, self.raw_first, self.raw_standard)
        ):
            self.buttons.addButton(button, index)
            controls.addWidget(button)
        if not vertical:
            controls.addStretch()
        layout.addWidget(row)
        self.selection_label = QLabel(self)
        self.selection_label.setWordWrap(True)
        self.selection_label.setMinimumHeight(0)
        self.selection_label.setMaximumHeight(0)
        self.selection_label.hide()
        layout.addWidget(self.selection_label)
        connect_signal(self.buttons.idClicked, self._emit_change)
        self.set_mask(mask, emit=False)

    def mask(self):
        """Return the selected population in the active storage
        grammar.
        """
        index = max(0, self.buttons.checkedId())
        return (RAW_MODES if self._lmsraw_mode else COMPRESSED_MODES)[index]

    def set_mask(self, mask, *, emit=False):
        """Select the equivalent population without changing its
        meaning.
        """
        value = normalize_selection(
            mask, "lmsraw" if self._lmsraw_mode else "compressed"
        )
        modes = RAW_MODES if self._lmsraw_mode else COMPRESSED_MODES
        self.buttons.button(modes.index(value)).setChecked(True)
        self.selection_label.clear()
        if emit:
            self.changed.emit(value)

    def _emit_change(self, *_args):
        value = self.mask()
        self.selection_label.clear()
        self.changed.emit(value)

    def set_applicable(self, applicable):
        """Keep the shared selector visible during worker
        transitions.
        """
        del applicable
        window = self.window()
        selected = getattr(window, "selected", None)
        datasets = getattr(window, "datasets", ())
        self._lmsraw_mode = (
            selected.storage_format == "lmsraw"
            if selected is not None
            else bool(datasets)
            and all(item.storage_format == "lmsraw" for item in datasets)
        )
        for button in (self.raw_all, self.raw_first, self.raw_standard):
            button.setEnabled(
                not self.selection_busy
                and (not getattr(window, "_closing", False))
            )
        self.selection_label.clear()
