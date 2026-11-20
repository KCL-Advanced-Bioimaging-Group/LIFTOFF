"""Display recorded selected and actual detector repetition rates."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dataset import DatasetInfo


def repetition_rate_text(dataset: DatasetInfo) -> str:
    """Keep missing nominal settings explicit."""
    selected = dataset.selected_rate_metadata.get("value")
    selected_text = (
        f"{selected:g} MHz" if selected is not None else "Unavailable"
    )
    actual = dataset.laser_frequency_hz
    actual_text = (
        f"{actual / 1e6:g} MHz"
        if actual is not None and math.isfinite(actual) and actual > 0
        else "Unavailable"
    )
    return f"{selected_text} (selected) / {actual_text} (actual)"
