"""Maintained desktop component: workspace rois."""

from __future__ import annotations

from abc import abstractmethod

import numpy as np
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMessageBox

from .gui_helpers import (
    _composite_roi_fraction_2,
    _panel_roi_values_2,
    _roi_key_4,
)
from .gui_models import Roi, RoiSnapshot, RoiSnapshotItem
from .gui_mosaic import (
    mosaic_roi_extent,
    mosaic_roi_fractions,
    restore_mosaic_extent,
)
from .gui_workspace_state import WorkspaceState


class WorkspaceRois(WorkspaceState):
    """ROI activation, persistence, and unique-pixel histograms."""

    def show_channel_pixel(self, x, y):
        """Inspect corresponding pixels across channels and tiles."""
        panels = getattr(self, "_multichannel_channel_panels", None)
        if not panels:
            return False
        if self.decode_worker is not None or self._active_roi_indices_2():
            return True
        owner = next(
            (
                panel
                for panel in panels
                if panel["composite_x"]
                <= x
                < panel["composite_x"] + panel["dataset"].width
                and panel.get("composite_y", 0) + panel["header_height"]
                <= y
                < panel.get("composite_y", 0)
                + panel["header_height"]
                + panel["dataset"].height
            ),
            None,
        )
        if owner is None:
            self._refresh_all_channel_rois_2()
            return True
        local_x = int(x - owner["composite_x"])
        local_y = int(y - owner.get("composite_y", 0) - owner["header_height"])
        fraction_x = (local_x + 0.5) / owner["dataset"].width
        fraction_y = (local_y + 0.5) / owner["dataset"].height
        self.histogram.hovered_mosaic_tile = owner["dataset"].tile_index
        for source, rendered in zip(
            panels, self.histogram.multichannel_panels or (), strict=True
        ):
            values = (
                source["cube"].pixel(
                    min(
                        source["dataset"].width - 1,
                        int(fraction_x * source["dataset"].width),
                    ),
                    min(
                        source["dataset"].height - 1,
                        int(fraction_y * source["dataset"].height),
                    ),
                )
                if source["dataset"].tile_index == owner["dataset"].tile_index
                else np.zeros_like(source["values"])
            )
            rendered["series"] = [("Pixel", values, rendered["color"])]
        prefix = ""
        if owner["dataset"].mosaic is not None:
            tile = owner["dataset"].mosaic.tiles[owner["dataset"].tile_index]
            prefix = f"Tile {tile.row + 1}, {tile.column + 1}: "
        self.histogram.multichannel_scope = (
            f"{prefix}pixel ({local_x}, {local_y})"
        )
        self.histogram.numbered_roi_legend_visible = False
        self.histogram.update()
        return True

    def _active_roi_indices_2(self):
        rois = list(getattr(self.image, "rois", ()) or ())
        return [
            index
            for index in sorted(
                getattr(self.image, "activated_rois", set()) or set()
            )
            if 0 <= index < len(rois)
        ]

    def _update_roi_controls_2(self):
        self.histogram.update_mosaic_graph_controls()
        rois = list(getattr(self.image, "rois", ()) or ())
        active = self._active_roi_indices_2()
        multichannel_data = bool(
            getattr(self, "_multichannel_channel_panels", None)
        )
        has_histogram_data = (
            getattr(self, "cube", None) is not None or multichannel_data
        )
        if not active and self.combine_rois_checkbox.isChecked():
            self.combine_rois_checkbox.blockSignals(True)
            self.combine_rois_checkbox.setChecked(False)
            self.combine_rois_checkbox.blockSignals(False)
        self.combine_rois_checkbox.setEnabled(
            bool(active) and has_histogram_data
        )
        self.clear_roi_button.setEnabled(bool(rois))

    def _capture_active_roi_snapshot_2(self) -> RoiSnapshot | None:
        active = self._active_roi_indices_2()
        if not active or getattr(self.image, "image", None) is None:
            return None
        rois = list(self.image.rois)
        colors = list(getattr(self.image, "roi_colors", ()) or ())
        number_method = getattr(self.image, "_roi_number_for_index", None)
        panels = list(getattr(self, "_multichannel_channel_panels", ()) or ())
        items: list[RoiSnapshotItem] = []
        for index in active:
            tile_index = None
            source_index = None
            source_key = getattr(getattr(self, "selected", None), "key", None)
            if panels:
                source_index, _mirrors = self.image.mirrored_roi_rectangles(
                    rois[index]
                )
                fraction = _composite_roi_fraction_2(panels, rois[index])
                if source_index is not None and 0 <= source_index < len(
                    panels
                ):
                    source_key = panels[source_index]["dataset"].key
                    tile_index = panels[source_index]["dataset"].tile_index
            else:
                image = self.image.image
                if image is None:
                    return None
                width = float(image.width())
                height = float(image.height())
                x0, y0, x1, y1 = (float(value) for value in rois[index])
                left, right = sorted((x0, x1))
                top, bottom = sorted((y0, y1))
                fraction = (
                    min(1.0, max(0.0, left / width)),
                    min(1.0, max(0.0, top / height)),
                    min(1.0, max(0.0, right / width)),
                    min(1.0, max(0.0, bottom / height)),
                )
            if (
                fraction is None
                or fraction[2] <= fraction[0]
                or fraction[3] <= fraction[1]
            ):
                continue
            number = (
                number_method(index) if callable(number_method) else index + 1
            )
            items.append(
                {
                    "fraction": (
                        float(fraction[0]),
                        float(fraction[1]),
                        float(fraction[2]),
                        float(fraction[3]),
                    ),
                    "sourceKey": source_key,
                    "tileIndex": tile_index,
                    "color": QColor(colors[index])
                    if index < len(colors)
                    else QColor("#38bdf8"),
                    "number": int(number if number is not None else index + 1),
                }
            )
            if panels and tile_index is not None and source_index is not None:
                items[-1]["mosaicExtent"] = mosaic_roi_extent(
                    panels[source_index], rois[index]
                )
        if not items:
            return None
        return {
            "items": items,
            "nextNumber": max(
                int(getattr(self.image, "next_roi_number", 1)),
                max(item["number"] for item in items) + 1,
            ),
        }

    def _ask_retain_channel_rois_2(self):
        answer = QMessageBox.question(
            self,
            "Retain active ROIs?",
            (
                "Do you want to retain the current active ROIs when "
                "switching channels?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _clear_transient_image_rois_2(self):
        """Prevent composite-space ROIs reaching a newly decoded channel
        cube.
        """
        self.image.rois = []
        self.image.roi_colors = []
        self.image.activated_rois = set()
        self.image.drag_start = None
        self.image.drag_current = None
        self.image.roi_number_snapshot = []
        self.image.update()

    def _restore_active_roi_snapshot_2(self, snapshot):
        if (
            not snapshot
            or not snapshot.get("items")
            or getattr(self.image, "image", None) is None
        ):
            return False
        panels = list(getattr(self, "_multichannel_channel_panels", ()) or ())
        layout = list(
            getattr(self.image, "multichannel_mirror_layout", ()) or ()
        )
        restored: list[Roi] = []
        colors = []
        numbers = []
        for item in snapshot["items"]:
            left, top, right, bottom = item["fraction"]
            if panels and layout:
                target_index = next(
                    (
                        index
                        for index, panel in enumerate(panels)
                        if panel["dataset"].key == item.get("sourceKey")
                    ),
                    next(
                        (
                            index
                            for index, panel in enumerate(panels)
                            if panel["dataset"].tile_index
                            == item.get("tileIndex")
                        ),
                        0,
                    ),
                )
                target = layout[min(target_index, len(layout) - 1)]
                roi = (
                    target["x"] + left * target["width"],
                    target["header"] + top * target["height"],
                    target["x"] + right * target["width"],
                    target["header"] + bottom * target["height"],
                )
                if (
                    "mosaicExtent" in item
                    and panels[target_index]["dataset"].mosaic is not None
                ):
                    roi = restore_mosaic_extent(
                        panels[target_index], item["mosaicExtent"]
                    )
            else:
                image = self.image.image
                if image is None:
                    return False
                width = image.width()
                height = image.height()
                x0 = max(0, min(max(0, width - 1), int(round(left * width))))
                y0 = max(0, min(max(0, height - 1), int(round(top * height))))
                x1 = max(x0 + 1, min(width, int(round(right * width))))
                y1 = max(y0 + 1, min(height, int(round(bottom * height))))
                roi = (x0, y0, x1, y1)
            restored.append(
                (float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3]))
                if panels and layout
                else (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
            )
            colors.append(QColor(item["color"]))
            numbers.append(int(item["number"]))
        self.image.rois = restored
        self.image.roi_colors = colors
        self.image.activated_rois = set(range(len(restored)))
        self.image.drag_start = None
        self.image.drag_current = None
        self.image.roi_number_snapshot = [
            (_roi_key_4(roi), number)
            for roi, number in zip(restored, numbers, strict=False)
        ]
        self.image.next_roi_number = max(
            int(snapshot.get("nextNumber", 1)), max(numbers, default=0) + 1
        )
        self.image.update()
        return True

    def _refresh_all_channel_rois_2(self):
        panels = list(getattr(self, "_multichannel_channel_panels", ()) or ())
        if not panels:
            return False
        active = self._active_roi_indices_2()
        rois = list(getattr(self.image, "rois", ()) or ())
        fractions = {
            index: _composite_roi_fraction_2(panels, rois[index])
            for index in active
        }
        fractions = {
            index: fraction
            for index, fraction in fractions.items()
            if fraction is not None
        }
        active = [index for index in active if index in fractions]
        combine = bool(active) and self.combine_rois_checkbox.isChecked()
        self.image.multichannel_combined_rois = combine
        colors = list(getattr(self.image, "roi_colors", ()) or ())
        histogram_panels = self.histogram.multichannel_panels
        self.histogram.hovered_mosaic_tile = None
        if histogram_panels is None:
            raise RuntimeError("Composite image has no histogram panels")
        for position, (source, rendered) in enumerate(
            zip(panels, histogram_panels, strict=False)
        ):
            panel_fractions = {
                index: (
                    mosaic_roi_fractions(panels, rois[index], source)
                    if source["dataset"].mosaic is not None
                    else [fractions[index]]
                )
                for index in active
            }
            channel_color = QColor(
                ("#1473b8", "#d97706", "#6f42c1", "#16856b")[
                    position
                    % len(("#1473b8", "#d97706", "#6f42c1", "#16856b"))
                ]
            )
            if not active:
                rendered["series"] = [
                    ("All pixels", source["values"], channel_color)
                ]
            elif combine:
                values = _panel_roi_values_2(
                    source,
                    [
                        fraction
                        for index in active
                        for fraction in panel_fractions[index]
                    ],
                    True,
                )
                rendered["series"] = [("All ROIs", values, QColor("#d97706"))]
            else:
                series = []
                for index in active:
                    number_method = getattr(
                        self.image, "_roi_number_for_index", None
                    )
                    number = (
                        number_method(index)
                        if callable(number_method)
                        else index + 1
                    )
                    color = (
                        QColor(colors[index])
                        if index < len(colors)
                        else channel_color
                    )
                    values = _panel_roi_values_2(
                        source, panel_fractions[index], False
                    )
                    series.append((str(number), values, color))
                rendered["series"] = series
        self.histogram.multichannel_scope = (
            "Activated ROIs" if active else "All Pixels"
        )
        self.histogram.numbered_roi_legend_visible = bool(active) and (
            not combine
        )
        self._update_roi_controls_2()
        self.histogram.update()
        self.image.update()
        return True

    def _bin_summary_2(self, photon_count):
        return (
            f"{int(photon_count):,}"
            " photons | "
            f"{self._bin_width_ps():.2f}"
            " ps/bin"
        )

    def _combined_roi_values_2(self, indices):
        cube = self.cube
        if cube is None:
            raise RuntimeError("No decoded cube for ROI analysis")
        counts = cube.counts
        height, width = counts.shape[:2]
        mask = np.zeros((height, width), dtype=np.bool_)
        for index in indices:
            x0, y0, x1, y1 = self.image.rois[index]
            x0, x1 = (max(0, x0), min(width - 1, x1))
            y0, y1 = (max(0, y0), min(height - 1, y1))
            if x0 <= x1 and y0 <= y1:
                mask[y0 : y1 + 1, x0 : x1 + 1] = True
        result = np.zeros(counts.shape[2], dtype=np.uint64)
        for y in range(height):
            xs = np.flatnonzero(mask[y])
            if xs.size:
                boundaries = np.flatnonzero(np.diff(xs) > 1)
                starts = np.r_[0, boundaries + 1]
                ends = np.r_[boundaries, xs.size - 1]
                for start, end in zip(starts, ends, strict=False):
                    result += counts[y, xs[start] : xs[end] + 1].sum(
                        axis=0, dtype=np.uint64
                    )
        return result

    def _main_window__refresh_roi_histogram_3(self, *_args):
        cube = self.cube
        if cube is None:
            raise RuntimeError("No decoded cube for ROI analysis")
        if self.cube is None:
            return
        self.image.ensure_interaction_state()
        self.image.ensure_roi_colors()
        active = sorted(
            index
            for index in self.image.activated_rois
            if 0 <= index < len(self.image.rois)
        )
        self.image.activated_rois = set(active)
        if not active:
            values = cube.counts.sum(axis=(0, 1), dtype=np.uint64)
            self.histogram.set_series(
                [("All pixels", values, "#1769AA")],
                title="Pixel arrival histogram — All pixels",
                summary=self._bin_summary_2(values.sum()),
            )
        elif self.combine_rois_checkbox.isChecked():
            values = self._combined_roi_values_2(active)
            self.histogram.set_series(
                [("Combined ROIs", values, "#D28A00")],
                title="Pixel arrival histogram — Combined activated ROIs",
                summary=self._bin_summary_2(values.sum()),
            )
        else:
            series = []
            for index in active:
                values = np.asarray(
                    self.cube.roi(
                        *(int(value) for value in self.image.rois[index])
                    ),
                    dtype=np.uint64,
                )
                series.append(
                    (
                        f"ROI {index + 1} ({int(values.sum()):,})",
                        values,
                        self.image.roi_colors[index],
                    )
                )
            self.histogram.set_series(
                series,
                title="Pixel arrival histogram — Activated ROIs",
                summary=(
                    f"{len(active)}"
                    " active ROI"
                    f"{('s' if len(active) != 1 else '')}"
                    " | "
                    f"{self._bin_width_ps():.2f}"
                    " ps/bin"
                ),
            )
        self.image.update()

    def _all_pixel_values_2(self, layout):
        cube = self.cube
        if cube is None:
            raise RuntimeError("No decoded cube for ROI analysis")
        axes = (1, 2) if layout == "time-first" else (0, 1)
        return cube.counts.sum(axis=axes, dtype=np.uint64)

    def _combined_values_2(self, active, layout):
        cube = self.cube
        if cube is None:
            raise RuntimeError("No decoded cube for ROI analysis")
        counts = cube.counts
        height, width = self.image.shape
        mask = np.zeros((height, width), dtype=np.bool_)
        for index in active:
            x0, y0, x1, y1 = self.image.rois[index]
            x0, x1 = (max(0, x0), min(width - 1, x1))
            y0, y1 = (max(0, y0), min(height - 1, y1))
            if x0 <= x1 and y0 <= y1:
                mask[y0 : y1 + 1, x0 : x1 + 1] = True
        bins = counts.shape[0] if layout == "time-first" else counts.shape[2]
        result = np.zeros(bins, dtype=np.uint64)
        for y in range(height):
            xs = np.flatnonzero(mask[y])
            if not xs.size:
                continue
            boundaries = np.flatnonzero(np.diff(xs) > 1)
            starts = np.r_[0, boundaries + 1]
            ends = np.r_[boundaries, xs.size - 1]
            for start, end in zip(starts, ends, strict=False):
                x0, x1 = (xs[start], xs[end] + 1)
                if layout == "time-first":
                    result += counts[:, y, x0:x1].sum(axis=1, dtype=np.uint64)
                else:
                    result += counts[y, x0:x1, :].sum(axis=0, dtype=np.uint64)
        return result

    def _cube_layout_2(self):
        cube = self.cube
        if cube is None:
            raise RuntimeError("No decoded cube for ROI analysis")
        counts = cube.counts
        if counts.ndim != 3:
            raise ValueError(
                f"Expected a 3-D histogram cube, got shape {counts.shape}"
            )
        height, width = self.image.shape
        if counts.shape[1:] == (height, width):
            return "time-first"
        if counts.shape[:2] == (height, width):
            return "time-last"
        raise ValueError(
            "Histogram cube shape "
            f"{counts.shape}"
            " does not match image shape "
            f"{(height, width)}"
        )

    def _summary_2(self, values):
        return (
            f"{int(values.sum()):,}"
            " photons | "
            f"{self._bin_width_ps():.2f}"
            " ps/bin"
        )

    def _main_window__refresh_roi_histogram_5(self, *_args):
        if self.cube is None:
            return
        active = sorted(
            index
            for index in self.image.activated_rois
            if 0 <= index < len(self.image.rois)
        )
        self.image.activated_rois = set(active)
        if active and (not self.combine_rois_checkbox.isChecked()):
            self._main_window__refresh_roi_histogram_3()
            return
        layout = self._cube_layout_2()
        if not active:
            values = self._all_pixel_values_2(layout)
            self.histogram.set_series(
                [("All pixels", values, "#1769AA")],
                title="Pixel arrival histogram — All pixels",
                summary=self._summary_2(values),
            )
        else:
            values = self._combined_values_2(active, layout)
            self.histogram.set_series(
                [("Combined ROIs", values, "#D28A00")],
                title="Pixel arrival histogram — Combined activated ROIs",
                summary=self._summary_2(values),
            )
        self.image.update()

    def _main_window_clear_roi_9(self) -> None:
        self.image.clear_roi()
        self.histogram.set_histogram(
            summary="Move over the image or drag an ROI",
            preserve_reflection=True,
        )

    def _main_window_clear_roi_8(self):
        self._main_window_clear_roi_9()
        self._leica_active_roi = None
        self._leica_filter_roi_restore = None

    def _main_window_clear_roi_7(self):
        self._main_window_clear_roi_8()
        self._leica_multi_roi_restore = None
        if self.cube is not None:
            self._main_window__refresh_roi_histogram_3()

    def _main_window_clear_roi_6(self):
        self._main_window_clear_roi_7()
        if self.cube is not None:
            self._refresh_roi_histogram()

    def _integerize_single_channel_rois_2(self):
        """Keep every ROI compatible with NumPy slice indexing in
        one-channel mode.
        """
        if getattr(self, "_multichannel_channel_panels", None):
            return
        image = getattr(self.image, "image", None)
        if image is None:
            return
        width = int(image.width())
        height = int(image.height())
        normalized: list[Roi] = []
        for roi in list(getattr(self.image, "rois", ()) or ()):
            x0, y0, x1, y1 = (float(value) for value in roi)
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            ix0 = max(0, min(max(0, width - 1), (round(left))))
            iy0 = max(0, min(max(0, height - 1), (round(top))))
            ix1 = max(ix0 + 1, min(width, (round(right))))
            iy1 = max(iy0 + 1, min(height, (round(bottom))))
            normalized.append((ix0, iy0, ix1, iy1))
        self.image.rois = normalized

    def _main_window__refresh_roi_histogram_7(self):
        self._main_window__refresh_roi_histogram_5()
        image = getattr(self, "image", None)
        histogram = getattr(self, "histogram", None)
        if image is None or histogram is None:
            return
        rois = list(getattr(image, "rois", ()))
        active = sorted(
            index
            for index in getattr(image, "activated_rois", set())
            if 0 <= index < len(rois)
        )
        numbers = image.ensure_roi_numbers()
        series = list(getattr(histogram, "series", ()))
        combine_widget = getattr(self, "combine_rois_checkbox", None)
        combined = bool(
            active and combine_widget and combine_widget.isChecked()
        )
        if combined and series:
            _label, values, color = series[0]
            histogram.series = [("All ROIs", values, color)]
        elif active and series:
            renamed = []
            for position, (_label, values, color) in enumerate(series):
                roi_index = (
                    active[position] if position < len(active) else position
                )
                number = (
                    numbers[roi_index] if roi_index < len(numbers) else None
                )
                renamed.append(
                    (
                        str(number if number is not None else position + 1),
                        values,
                        color,
                    )
                )
            histogram.series = renamed
        histogram.numbered_roi_legend_visible = bool(active and series)
        histogram.numbered_roi_legend_combined = combined
        histogram.update()
        image.update()

    def show_roi(self, _x0, _y0, _x1, _y1):
        """Compute show roi."""
        self._refresh_roi_histogram()

    def clear_roi(self):
        """Compute clear roi."""
        self._main_window_clear_roi_6()
        if getattr(self, "_multichannel_channel_panels", None):
            self._refresh_all_channel_rois_2()
        self._update_roi_controls_2()

    def _refresh_roi_histogram(self):
        if self._refresh_all_channel_rois_2():
            return
        self._integerize_single_channel_rois_2()
        try:
            self._main_window__refresh_roi_histogram_7()
            return
        finally:
            self._update_roi_controls_2()

    @abstractmethod
    def _components_ready(self) -> bool:
        """Require the final Qt workspace to combine all components."""
        raise NotImplementedError
