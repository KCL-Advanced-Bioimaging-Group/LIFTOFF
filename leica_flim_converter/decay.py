"""Fast ROI decay accumulation over decoded Leica reduced-time-tag
rows.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

PRIMARY = {160, 168, 176}
ALL = PRIMARY | {184}


def native_period_bins(
    clock_period_s: float | None, laser_frequency_hz: float | None
) -> int:
    """Compute native period bins."""
    if clock_period_s and laser_frequency_hz:
        return max(1, round(1.0 / laser_frequency_hz / clock_period_s))
    return 4096


def output_bin(microtime: int, bins: int, period_bins: int) -> int:
    """Compute output bin."""
    return min(bins - 1, max(0, microtime * bins // period_bins))


# Retain the original positional ROI callback interface.
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def roi_histogram(
    rows: list[dict],
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    bins: int = 128,
    classes: set[int] = ALL,
    period_bins: int = 4096,
    row_to_y: Callable[[int], int] | None = None,
) -> tuple[np.ndarray, int]:
    """Accumulate a pixel/rectangular ROI without yielding events
    outside it.
    """
    histogram = np.zeros(bins, dtype=np.uint64)
    overflow_events = 0
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    map_y = row_to_y or (lambda row: row % height)
    for row in rows:
        y = map_y(int(row["line"]))
        if y < y0 or y > y1:
            continue
        x, index, tokens = (0, 0, row["tokens"])
        while index < len(tokens):
            token = tokens[index]
            if 129 <= token <= 159:
                x += token & 31
                index += 1
                continue
            if token not in ALL:
                index += 1
                continue
            marker = token
            index += 1
            arrival = event_index = 0
            selected = marker in classes and x0 <= x <= x1
            while index < len(tokens):
                token = tokens[index]
                if token < 128:
                    value = token
                    index += 1
                elif (
                    192 <= token <= 255
                    and index + 1 < len(tokens)
                    and (tokens[index + 1] < 128)
                ):
                    value = (token & 63) << 7 | tokens[index + 1]
                    index += 2
                else:
                    break
                arrival = value if event_index == 0 else arrival + value
                event_index += 1
                if selected:
                    histogram[output_bin(arrival, bins, period_bins)] += 1
                    overflow_events += int(arrival >= period_bins)
    return (histogram, overflow_events)
