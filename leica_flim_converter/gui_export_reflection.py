"""Shared explicit reflection exclusion controls for export dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .dataset import DatasetInfo
from .reflection_export import ReflectionWindow, reflection_window

_FILTER_LABEL = "Filter reflection photons where applicable"


class ExportReflectionSelection(QWidget):
    """Separate export exclusion from the preview checkbox."""

    def __init__(self, windows: tuple[ReflectionWindow, ...]) -> None:
        super().__init__()
        self.available = windows
        self._matching_windows: tuple[ReflectionWindow, ...] = ()
        self.checkbox = QCheckBox()
        self.checkbox.setAccessibleName(_FILTER_LABEL)
        self.setFocusProxy(self.checkbox)
        self.checkbox.setObjectName("exportFilterReflectionPhotonsCheckBox")
        self.checkbox.setToolTip(
            "Apply saved reflection boundaries after Event selection. "
            "Outputs without boundaries skip reflection filtering."
        )
        self.checkbox.setEnabled(False)
        self.status = QLabel("No reflection peak identified.")
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status)

    @property
    def windows(self) -> tuple[ReflectionWindow, ...]:
        """Snapshot only an explicitly selected export filter."""
        return self._matching_windows if self.checkbox.isChecked() else ()

    def update_targets(
        self, targets: list[tuple[DatasetInfo, int | None]]
    ) -> None:
        """Offer filtering for outputs with matching bounds."""
        matches = [
            window
            for dataset, plane in targets
            if (window := reflection_window(self.available, dataset, plane))
            is not None
        ]
        matching = set(matches)
        self._matching_windows = tuple(
            window for window in self.available if window in matching
        )
        self.checkbox.setEnabled(bool(matches))
        self.status.setText(
            "No reflection peak identified."
            if not self.available
            else "Select outputs with reflection boundaries defined."
            if not targets
            else "No selected outputs have saved reflection boundaries."
            if not matches
            else f"Saved reflection boundaries for {len(matches)} of "
            f"{len(targets)} selected outputs."
        )


def add_export_filter_rows(
    layout: QVBoxLayout,
    event_flags: QWidget,
    reflection: ExportReflectionSelection,
) -> None:
    """Align both filters without gaps from other settings labels."""
    filters = QFormLayout()
    filters.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    filters.addRow("Event selection", event_flags)
    filters.addRow(_FILTER_LABEL, reflection)
    layout.addLayout(filters)
