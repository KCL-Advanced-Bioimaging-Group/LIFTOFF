"""Shared explicit reflection exclusion controls for export dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .dataset import DatasetInfo
from .reflection_export import ReflectionWindow, reflection_window

_FILTER_LABEL = "Filter reflection photons where applicable"
_NO_PEAKS = "No reflection peaks identified."


class ExportReflectionSelection(QWidget):
    """Separate export exclusion from the preview checkbox."""

    def __init__(
        self, windows: tuple[ReflectionWindow, ...], *, event_format=False
    ) -> None:
        super().__init__()
        self.available = windows
        self.event_format = event_format
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
        self.status = QLabel(_NO_PEAKS)
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        status_row = QHBoxLayout()
        status_row.addWidget(self.checkbox)
        status_row.addWidget(self.status, 1)
        layout.addLayout(status_row)
        explanation = QLabel(
            "PTU excludes actual reflection events in every mode. "
            "It does not export missing, interpolated or simulated counts."
            if event_format
            else "Filtered ICS uses each saved treatment and simulation "
            "seed. Metadata identifies synthetic bins and their method."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

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
            _NO_PEAKS
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
