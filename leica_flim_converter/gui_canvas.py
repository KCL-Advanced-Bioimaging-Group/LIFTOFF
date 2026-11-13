"""Maintained desktop component: canvas."""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QFrame, QWidget

from .gui_helpers import _roi_key_3
from .gui_intensity_contrast import IntensityContrast
from .gui_intensity_levels import render_intensity
from .gui_models import Roi
from .gui_mosaic import mirror_rectangles


def image_from_counts(intensity: np.ndarray) -> QImage:
    """Render intensity with the preview's usual percentile contrast."""
    low, high = np.percentile(intensity, (0, 99.8))
    return render_intensity(intensity, float(low), float(high))


# The Qt event overrides and published canvas controls share one widget.
# pylint: disable-next=too-many-public-methods
class ImageCanvas(QWidget):
    """Represent image canvas."""

    def ensure_interaction_state(self):
        """Ensure interaction state."""
        if not hasattr(self, "view_zoom"):
            self.view_zoom = 1.0
            self.view_center_x = 0.5
            self.view_center_y = 0.5
            self.interaction_tool = None
            self.pan_drag_position = None
            self.pan_start_center = None
            self.roi_colors = []
            self.activated_rois = set()

    def _initialize_image_canvas(self) -> None:
        """Initialize image canvas."""
        super().__init__()
        self._last_combined_source_outlines = []
        self.roi_number_snapshot = []
        self.next_roi_number = 1
        self._last_roi_delete_result = ""
        self._last_deleted_roi_index = None
        self.setMinimumSize(440, 440)
        self.setMouseTracking(True)
        self._pixel_hover_active = False
        self.image = None
        self.contrast = IntensityContrast(self)
        self.shape = (0, 0)
        self.image_rect = QRectF()
        self.drag_start = None
        self.drag_current = None
        self.rois = []
        self.setToolTip(
            "Drag to add ROIs. Hovering inside one ROI shows its "
            "combined decay; overlapping ROI areas are reported as"
            " ambiguous."
        )

    def _image_canvas_set_counts_3(self, intensity: np.ndarray) -> None:
        self.shape = intensity.shape
        self.contrast.set_intensities([intensity])
        self.clear_roi()
        self.update()

    def _image_canvas_clear_image_3(self) -> None:
        self.image = None
        self.contrast.set_intensities([])
        self.shape = (0, 0)
        self.clear_roi()
        self.update()

    def reset_image_view(self):
        """Reset image view."""
        self.ensure_interaction_state()
        self.view_zoom = 1.0
        self.view_center_x = 0.5
        self.view_center_y = 0.5
        self.pan_drag_position = None
        self.pan_start_center = None
        self.update()

    def _image_canvas_clear_roi_3(self):
        self.ensure_interaction_state()
        self.rois.clear()
        self.roi_colors.clear()
        self.activated_rois.clear()
        self.drag_start = None
        self.drag_current = None
        self.update()

    def mirrored_roi_rectangles(self, roi):
        """Mirror ROI geometry across matching detector views."""
        return mirror_rectangles(
            list(getattr(self, "multichannel_mirror_layout", ()) or ()), roi
        )

    def _paint_mirrored_active_rois_2(self, event, previous_paint):
        previous_paint(self, event)
        rois = list(getattr(self, "rois", ()) or ())
        active = [
            index
            for index in sorted(
                getattr(self, "activated_rois", set()) or set()
            )
            if 0 <= index < len(rois)
        ]
        self.last_mirrored_roi_layout = []
        self._last_combined_source_outlines = []
        if (
            not active
            or len(getattr(self, "multichannel_mirror_layout", ()) or ()) < 2
        ):
            return
        combined = bool(getattr(self, "multichannel_combined_rois", False))
        colors = list(getattr(self, "roi_colors", ()) or ())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setFont(QFont("Arial", 8, QFont.Weight.DemiBold))
        metrics = painter.fontMetrics()
        background = QColor(0, 0, 0, 77)
        number_method = getattr(self, "_roi_number_for_index", None)
        label_rect_method = getattr(self, "_numbered_roi_label_rect", None)
        for index in active:
            source_index, mirrors = self.mirrored_roi_rectangles(rois[index])
            color = (
                QColor("#d97706")
                if combined
                else QColor(colors[index])
                if index < len(colors)
                else QColor("#38bdf8")
            )
            number = (
                number_method(index) if callable(number_method) else index + 1
            )
            if combined:
                source_rect = self._display_roi(rois[index])
                painter.setPen(QPen(color, 2.2))
                if source_rect is None:
                    continue
                painter.drawRect(source_rect)
                self._last_combined_source_outlines.append(
                    {
                        "roiIndex": index,
                        "number": number if number is not None else index + 1,
                        "sourcePanel": source_index,
                        "color": color.name(),
                    }
                )
            for target_index, mirror_roi in mirrors:
                display_rect = self._display_roi(mirror_roi)
                if display_rect is None:
                    continue
                painter.setPen(QPen(color, 2.2))
                painter.drawRect(display_rect)
                text = str(number if number is not None else index + 1)
                label_width = max(
                    14.0, float(metrics.horizontalAdvance(text) + 6)
                )
                label_height = max(14.0, float(metrics.height() + 2))
                if callable(label_rect_method):
                    label_rect = label_rect_method(
                        display_rect, label_width, label_height
                    )
                elif (
                    display_rect.width() < label_width
                    or display_rect.height() < label_height
                ):
                    label_rect = QRectF(
                        display_rect.left(),
                        display_rect.top() - label_height,
                        label_width,
                        label_height,
                    )
                else:
                    label_rect = QRectF(
                        display_rect.left(),
                        display_rect.top(),
                        label_width,
                        label_height,
                    )
                painter.fillRect(label_rect, background)
                painter.setPen(QColor("white"))
                painter.drawText(
                    label_rect, Qt.AlignmentFlag.AlignCenter, text
                )
                self.last_mirrored_roi_layout.append(
                    {
                        "roiIndex": index,
                        "number": number if number is not None else index + 1,
                        "sourcePanel": source_index,
                        "targetPanel": target_index,
                        "color": color.name(),
                        "combined": combined,
                        "imageRect": [float(value) for value in mirror_roi],
                        "displayRect": [
                            float(display_rect.left()),
                            float(display_rect.top()),
                            float(display_rect.right()),
                            float(display_rect.bottom()),
                        ],
                    }
                )
        painter.end()

    def ensure_roi_numbers(self):
        """Ensure roi numbers."""
        rois = list(getattr(self, "rois", ()))
        keys = [_roi_key_3(roi) for roi in rois]
        old_snapshot = list(getattr(self, "roi_number_snapshot", ()))
        old_pools = {}
        for key, number in old_snapshot:
            old_pools.setdefault(key, []).append(number)
        numbers = []
        for key in keys:
            pool = old_pools.get(key, [])
            numbers.append(pool.pop(0) if pool else None)
        next_number = int(getattr(self, "next_roi_number", 1))
        assigned = [number for number in numbers if number is not None]
        if assigned:
            next_number = max(next_number, max(assigned) + 1)
        for index in sorted(getattr(self, "activated_rois", set())):
            if 0 <= index < len(numbers) and numbers[index] is None:
                numbers[index] = next_number
                next_number += 1
        self.roi_number_snapshot = list(zip(keys, numbers, strict=False))
        self.next_roi_number = next_number
        return numbers

    def _image_canvas__numbered_roi_label_rect_2(
        self, roi_rect, label_width, label_height
    ):
        if roi_rect.width() < label_width or roi_rect.height() < label_height:
            return QRectF(
                float(roi_rect.left()),
                float(roi_rect.top()) - label_height,
                label_width,
                label_height,
            )
        return QRectF(
            float(roi_rect.left()),
            float(roi_rect.top()),
            label_width,
            label_height,
        )

    def _base_image_rect_2(self):
        if (
            self.image is None
            or self.image.width() <= 0
            or self.image.height() <= 0
        ):
            return QRectF()
        scale = min(
            self.width() / self.image.width(),
            self.height() / self.image.height(),
        )
        width = self.image.width() * scale
        height = self.image.height() * scale
        return QRectF(
            (self.width() - width) / 2,
            (self.height() - height) / 2,
            width,
            height,
        )

    def _clamp_view_2(self):
        self.view_zoom = min(16.0, max(1.0, float(self.view_zoom)))
        half = 0.5 / self.view_zoom
        self.view_center_x = min(
            1.0 - half, max(half, float(self.view_center_x))
        )
        self.view_center_y = min(
            1.0 - half, max(half, float(self.view_center_y))
        )

    def _source_rect_2(self):
        if self.image is None:
            return QRectF()
        self._clamp_view_2()
        width = self.image.width() / self.view_zoom
        height = self.image.height() / self.view_zoom
        return QRectF(
            self.view_center_x * self.image.width() - width / 2,
            self.view_center_y * self.image.height() - height / 2,
            width,
            height,
        )

    def _image_canvas__display_roi_2(self, roi):
        if self.image is None:
            return None
        base, source = (self._base_image_rect_2(), self._source_rect_2())
        x0, y0, x1, y1 = roi
        return QRectF(
            base.left() + (x0 - source.left()) / source.width() * base.width(),
            base.top() + (y0 - source.top()) / source.height() * base.height(),
            max(3.0, (x1 - x0 + 1) / source.width() * base.width()),
            max(3.0, (y1 - y0 + 1) / source.height() * base.height()),
        )

    def _image_canvas__pixel_2(self, position):
        if self.image is None:
            return None
        base = self._base_image_rect_2()
        point = QtCore.QPointF(position)
        if not base.contains(point):
            return None
        source = self._source_rect_2()
        x = int(
            source.left()
            + (point.x() - base.left())
            / max(1e-12, base.width())
            * source.width()
        )
        y = int(
            source.top()
            + (point.y() - base.top())
            / max(1e-12, base.height())
            * source.height()
        )
        return (
            min(self.image.width() - 1, max(0, x)),
            min(self.image.height() - 1, max(0, y)),
        )

    def _image_canvas__drag_roi_2(self):
        if self.drag_start is None or self.drag_current is None:
            return None
        a, b = (
            self._image_canvas__pixel_2(self.drag_start),
            self._image_canvas__pixel_2(self.drag_current),
        )
        if a is None or b is None:
            return None
        return (
            min(a[0], b[0]),
            min(a[1], b[1]),
            max(a[0], b[0]),
            max(a[1], b[1]),
        )

    def ensure_roi_colors(self):
        """Ensure roi colors."""
        while len(self.roi_colors) < len(self.rois):
            self.roi_colors.append(
                QColor(
                    (
                        "#00A6FB",
                        "#FF8C42",
                        "#76C442",
                        "#D94FFF",
                        "#F6C945",
                        "#FF5A5F",
                        "#7B61FF",
                        "#00BFA6",
                        "#E76FAD",
                        "#63C7FF",
                        "#A3D65C",
                        "#FFB35C",
                    )[
                        len(self.roi_colors)
                        % len(
                            (
                                "#00A6FB",
                                "#FF8C42",
                                "#76C442",
                                "#D94FFF",
                                "#F6C945",
                                "#FF5A5F",
                                "#7B61FF",
                                "#00BFA6",
                                "#E76FAD",
                                "#63C7FF",
                                "#A3D65C",
                                "#FFB35C",
                            )
                        )
                    ]
                )
            )
        if len(self.roi_colors) > len(self.rois):
            del self.roi_colors[len(self.rois) :]

    def _image_canvas_paint_event_5(self, _event):
        self.ensure_interaction_state()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#090b0d"))
        if self.image is None:
            return
        base, source = (self._base_image_rect_2(), self._source_rect_2())
        self.image_rect = base
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(base, self.image, source)
        painter.save()
        painter.setClipRect(base)
        self.ensure_roi_colors()
        regions: list[tuple[int | None, Roi]] = list(enumerate(self.rois))
        pending = self._image_canvas__drag_roi_2()
        if pending is not None:
            regions.append((None, pending))
        main = self.window()
        combine = bool(
            getattr(main, "combine_rois_checkbox", None)
            and main.combine_rois_checkbox.isChecked()
        )
        for index, roi in regions:
            displayed = self._image_canvas__display_roi_2(roi)
            if displayed is None or not displayed.intersects(base):
                continue
            active = index is not None and index in self.activated_rois
            color_text = (
                "#D28A00"
                if active and combine
                else self.roi_colors[index]
                if index is not None
                else (
                    "#00A6FB",
                    "#FF8C42",
                    "#76C442",
                    "#D94FFF",
                    "#F6C945",
                    "#FF5A5F",
                    "#7B61FF",
                    "#00BFA6",
                    "#E76FAD",
                    "#63C7FF",
                    "#A3D65C",
                    "#FFB35C",
                )[
                    len(self.rois)
                    % len(
                        (
                            "#00A6FB",
                            "#FF8C42",
                            "#76C442",
                            "#D94FFF",
                            "#F6C945",
                            "#FF5A5F",
                            "#7B61FF",
                            "#00BFA6",
                            "#E76FAD",
                            "#63C7FF",
                            "#A3D65C",
                            "#FFB35C",
                        )
                    )
                ]
            )
            color = QColor(color_text)
            fill = QColor(color)
            fill.setAlpha(58 if active else 25)
            painter.fillRect(displayed, fill)
            pen = QPen(color, 3.0 if active else 1.5)
            if not active and index is not None:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(displayed)
        painter.restore()

    def _image_canvas_paint_event_4(self, event):
        self._image_canvas_paint_event_5(event)
        rois = list(getattr(self, "rois", ()))
        active = sorted(
            index
            for index in getattr(self, "activated_rois", set())
            if 0 <= index < len(rois)
        )
        if not active or getattr(self, "image", None) is None:
            return
        numbers = self.ensure_roi_numbers()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Arial", 8, QFont.Weight.DemiBold))
        metrics = painter.fontMetrics()
        background = QColor(0, 0, 0, 77)
        for index in active:
            roi_rect = self._display_roi(rois[index])
            number = numbers[index]
            if number is None:
                continue
            text = str(number)
            label_width = max(14.0, float(metrics.horizontalAdvance(text) + 6))
            label_height = max(14.0, float(metrics.height() + 2))
            label_rect = self._image_canvas__numbered_roi_label_rect_2(
                roi_rect, label_width, label_height
            )
            painter.fillRect(label_rect, background)
            painter.setPen(QColor("white"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

    def update_interaction_cursor(self, shift=False, dragging=False):
        """Update interaction cursor."""
        tool = self.interaction_tool
        if dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif shift or tool == "pan":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif tool == "zoom_in" and hasattr(self, "zoom_in_cursor"):
            self.setCursor(self.zoom_in_cursor)
        elif tool == "zoom_out" and hasattr(self, "zoom_out_cursor"):
            self.setCursor(self.zoom_out_cursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _delete_inactive_roi_at_2(self, event, previous_mouse_press):
        if event.button() != Qt.MouseButton.RightButton:
            previous_mouse_press(self, event)
            return
        pixel = self._pixel(event.position())
        if pixel is None:
            event.ignore()
            return
        hits = list(self._roi_indices_at(*pixel))
        active = set(getattr(self, "activated_rois", set()) or set())
        delete_index = next(
            (index for index in reversed(hits) if index not in active), None
        )
        if delete_index is None:
            self._last_roi_delete_result = (
                "active-protected" if hits else "no-roi"
            )
            event.accept()
            return
        self.rois.pop(delete_index)
        if delete_index < len(self.roi_colors):
            self.roi_colors.pop(delete_index)
        self.activated_rois = {
            index - 1 if index > delete_index else index
            for index in active
            if index != delete_index
        }
        self.drag_start = None
        self.drag_current = None
        self._last_roi_delete_result = "deleted"
        self._last_deleted_roi_index = delete_index
        self.roi_selected.emit(0, 0, 0, 0)
        self.update()
        event.accept()

    def _notify_selection_2(self):
        main = self.window()
        if hasattr(main, "_refresh_roi_histogram"):
            refresh = getattr(main, "_refresh_roi_histogram", None)
            if callable(refresh):
                refresh()
        self.update()

    def _image_canvas__roi_indices_at_2(self, x, y):
        return [
            index
            for index, (x0, y0, x1, y1) in enumerate(self.rois)
            if x0 <= x <= x1 and y0 <= y <= y1
        ]

    def _image_canvas__toggle_rois_at_2(self, x, y):
        hits = self._image_canvas__roi_indices_at_2(x, y)
        if not hits:
            return False
        if all(index in self.activated_rois for index in hits):
            self.activated_rois.difference_update(hits)
        else:
            self.activated_rois.update(hits)
        self._notify_selection_2()
        return True

    def _image_canvas__zoom_at_2(self, position, factor):
        if self.image is None:
            return
        base, old_source = (self._base_image_rect_2(), self._source_rect_2())
        point = QtCore.QPointF(position)
        if base.contains(point):
            u = (point.x() - base.left()) / max(1e-12, base.width())
            v = (point.y() - base.top()) / max(1e-12, base.height())
        else:
            u = v = 0.5
        target_x = (
            old_source.left() + u * old_source.width()
        ) / self.image.width()
        target_y = (
            old_source.top() + v * old_source.height()
        ) / self.image.height()
        new_zoom = min(16.0, max(1.0, self.view_zoom * factor))
        self.view_zoom = new_zoom
        self.view_center_x = target_x + (0.5 - u) / new_zoom
        self.view_center_y = target_y + (0.5 - v) / new_zoom
        self._clamp_view_2()
        self.update()

    def _image_canvas_mouse_press_event_3(self, event):
        self.ensure_interaction_state()
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position()
        pixel = self._image_canvas__pixel_2(point)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if pixel is not None:
                self._image_canvas__toggle_rois_at_2(*pixel)
            event.accept()
            return
        if (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            or self.interaction_tool == "pan"
        ):
            self.pan_drag_position = QtCore.QPointF(point)
            self.pan_start_center = (self.view_center_x, self.view_center_y)
            self.update_interaction_cursor(dragging=True)
            event.accept()
            return
        if self.interaction_tool == "zoom_in":
            self._image_canvas__zoom_at_2(point, 1.5)
            event.accept()
            return
        if self.interaction_tool == "zoom_out":
            self._image_canvas__zoom_at_2(point, 1 / 1.5)
            event.accept()
            return
        if pixel is not None:
            self.drag_start = point.toPoint()
            self.drag_current = point.toPoint()
            self.update()
            event.accept()
        else:
            event.ignore()

    def position_navigation_toolbar(self, event):
        """Position navigation toolbar."""
        QWidget.resizeEvent(self, event)
        toolbar = getattr(self, "navigation_toolbar", None)
        if toolbar is not None:
            toolbar.adjustSize()
            toolbar.move(max(6, self.width() - toolbar.width() - 8), 8)
            toolbar.raise_()

    last_mirrored_roi_layout: list[dict]
    multichannel_combined_rois: bool
    multichannel_header_layout: list[dict]
    multichannel_mirror_layout: list[dict]
    navigation_toolbar: QFrame
    zoom_in_cursor: QCursor
    zoom_out_cursor: QCursor
    next_roi_number: int
    activated_rois: set[int]
    drag_current: QPoint | None
    drag_start: QPoint | None
    image: QImage | None
    image_rect: QRectF
    interaction_tool: str | None
    pan_drag_position: QtCore.QPointF | None
    pan_start_center: tuple[float, float] | None
    roi_colors: list[QColor]
    rois: list[tuple[int | float, int | float, int | float, int | float]]
    shape: tuple[int, int]
    view_center_x: float
    view_center_y: float
    view_zoom: float
    hovered = Signal(int, int)
    hover_ended = Signal()
    roi_selected = Signal(int, int, int, int)

    def __init__(self):
        self._initialize_image_canvas()
        self.ensure_interaction_state()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(
            "Mouse wheel or magnifying-glass tools: zoom. "
            "Shift+drag or hand tool: pan. Drag: draw an inactive "
            "ROI. Ctrl+left-click an ROI: activate or deactivate "
            "it."
        )

    def set_counts(self, intensity):
        """Compute set counts."""
        self.ensure_interaction_state()
        self._image_canvas_set_counts_3(intensity)

    def clear_image(self):
        """Compute clear image."""
        self._image_canvas_clear_image_3()
        self.reset_image_view()

    def clear_roi(self):
        """Compute clear roi."""
        self._image_canvas_clear_roi_3()
        self.roi_number_snapshot = []
        self.next_roi_number = 1

    def paintEvent(self, event):  # noqa: N802
        """Compute paint event."""
        self._paint_mirrored_active_rois_2(
            event, ImageCanvas._image_canvas_paint_event_4
        )

    def _pixel(self, position):
        if self.image is None:
            return None
        base = self._base_image_rect_2()
        point = QtCore.QPointF(position)
        if not base.contains(point):
            return None
        source = self._source_rect_2()
        x = int(
            source.left()
            + (point.x() - base.left())
            / max(1e-12, base.width())
            * source.width()
        )
        y = int(
            source.top()
            + (point.y() - base.top())
            / max(1e-12, base.height())
            * source.height()
        )
        return (
            min(self.image.width() - 1, max(0, x)),
            min(self.image.height() - 1, max(0, y)),
        )

    def _drag_roi(self):
        if self.drag_start is None or self.drag_current is None:
            return None
        a, b = (
            self._image_canvas__pixel_2(self.drag_start),
            self._image_canvas__pixel_2(self.drag_current),
        )
        if a is None or b is None:
            return None
        return (
            min(a[0], b[0]),
            min(a[1], b[1]),
            max(a[0], b[0]),
            max(a[1], b[1]),
        )

    def _display_roi(self, roi):
        if self.image is None:
            return None
        base, source = (self._base_image_rect_2(), self._source_rect_2())
        x0, y0, x1, y1 = roi
        return QRectF(
            base.left() + (x0 - source.left()) / source.width() * base.width(),
            base.top() + (y0 - source.top()) / source.height() * base.height(),
            max(3.0, (x1 - x0 + 1) / source.width() * base.width()),
            max(3.0, (y1 - y0 + 1) / source.height() * base.height()),
        )

    def rois_at(self, x: int, y: int) -> list[Roi]:
        """Return every ROI containing a pixel, preserving drawing
        order.
        """
        return [
            roi
            for roi in self.rois
            if roi[0] <= x <= roi[2] and roi[1] <= y <= roi[3]
        ]

    def mouseMoveEvent(self, event):  # noqa: N802
        """Compute mouse move event."""
        self.ensure_interaction_state()
        if (
            self.pan_drag_position is not None
            and self.pan_start_center is not None
        ):
            self._end_pixel_hover()
            base = self._base_image_rect_2()
            if base.width() > 0 and base.height() > 0:
                delta = event.position() - self.pan_drag_position
                self.view_center_x = (
                    self.pan_start_center[0]
                    - delta.x() / base.width() / self.view_zoom
                )
                self.view_center_y = (
                    self.pan_start_center[1]
                    - delta.y() / base.height() / self.view_zoom
                )
                self._clamp_view_2()
                self.update()
            event.accept()
            return
        if self.drag_start is not None:
            self._end_pixel_hover()
            self.drag_current = event.position().toPoint()
            self.update()
            event.accept()
            return
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.update_interaction_cursor(shift=shift)
        pixel = self._image_canvas__pixel_2(event.position())
        if (
            pixel is not None
            and (not shift)
            and (self.interaction_tool is None)
        ):
            self._pixel_hover_active = True
            self.hovered.emit(*pixel)
        else:
            self._end_pixel_hover()

    def _end_pixel_hover(self):
        if self._pixel_hover_active:
            self._pixel_hover_active = False
            self.hover_ended.emit()

    def mousePressEvent(self, event):  # noqa: N802
        """Compute mouse press event."""
        return self._delete_inactive_roi_at_2(
            event, ImageCanvas._image_canvas_mouse_press_event_3
        )

    def mouseReleaseEvent(self, event):  # noqa: N802
        """Compute mouse release event."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self.pan_drag_position is not None:
            self.pan_drag_position = None
            self.pan_start_center = None
            self.update_interaction_cursor(
                shift=bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
            )
            event.accept()
            return
        if self.drag_start is not None:
            self.drag_current = event.position().toPoint()
            roi = self._image_canvas__drag_roi_2()
            self.drag_start = None
            self.drag_current = None
            if roi is not None and (roi[0] != roi[2] or roi[1] != roi[3]):
                self.rois.append(roi)
                self.ensure_roi_colors()
            self.update()
            event.accept()
            return
        event.accept()

    def _roi_indices_at(self, x, y):
        return [
            index
            for index, (x0, y0, x1, y1) in enumerate(self.rois)
            if x0 <= x <= x1 and y0 <= y <= y1
        ]

    def _toggle_rois_at(self, x, y):
        hits = self._image_canvas__roi_indices_at_2(x, y)
        if not hits:
            return False
        if all(index in self.activated_rois for index in hits):
            self.activated_rois.difference_update(hits)
        else:
            self.activated_rois.update(hits)
        self._notify_selection_2()
        return True

    def _zoom_at(self, position, factor):
        if self.image is None:
            return
        base, old_source = (self._base_image_rect_2(), self._source_rect_2())
        point = QtCore.QPointF(position)
        if base.contains(point):
            u = (point.x() - base.left()) / max(1e-12, base.width())
            v = (point.y() - base.top()) / max(1e-12, base.height())
        else:
            u = v = 0.5
        target_x = (
            old_source.left() + u * old_source.width()
        ) / self.image.width()
        target_y = (
            old_source.top() + v * old_source.height()
        ) / self.image.height()
        new_zoom = min(16.0, max(1.0, self.view_zoom * factor))
        self.view_zoom = new_zoom
        self.view_center_x = target_x + (0.5 - u) / new_zoom
        self.view_center_y = target_y + (0.5 - v) / new_zoom
        self._clamp_view_2()
        self.update()

    def reset_view(self):
        """Compute reset view."""
        self.ensure_interaction_state()
        self.view_zoom = 1.0
        self.view_center_x = 0.5
        self.view_center_y = 0.5
        self.pan_drag_position = None
        self.pan_start_center = None
        self.update()

    def wheelEvent(self, event):  # noqa: N802
        """Compute wheel event."""
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._image_canvas__zoom_at_2(event.position(), 1.25**steps)
            event.accept()
        else:
            event.ignore()

    def leaveEvent(self, event):  # noqa: N802
        """Compute leave event."""
        self.update_interaction_cursor()
        self._end_pixel_hover()
        QWidget.leaveEvent(self, event)

    def resizeEvent(self, event):  # noqa: N802
        """Compute resize event."""
        QWidget.resizeEvent(self, event)
        toolbar = getattr(self, "navigation_toolbar", None)
        if toolbar is not None:
            toolbar.adjustSize()
            toolbar.move(max(6, self.width() - toolbar.width() - 8), 8)
            toolbar.raise_()

    def keyPressEvent(self, event):  # noqa: N802
        """Compute key press event."""
        if event.key() == Qt.Key.Key_Shift:
            self.update_interaction_cursor(shift=True)
        QWidget.keyPressEvent(self, event)

    def keyReleaseEvent(self, event):  # noqa: N802
        """Compute key release event."""
        if event.key() == Qt.Key.Key_Shift:
            self.update_interaction_cursor()
        QWidget.keyReleaseEvent(self, event)

    def _roi_number_for_index(self, index):
        numbers = self.ensure_roi_numbers()
        if 0 <= index < len(numbers):
            return numbers[index]
        return None

    def _numbered_roi_label_rect(self, roi_rect, label_width, label_height):
        if roi_rect.width() < label_width or roi_rect.height() < label_height:
            return QRectF(
                float(roi_rect.left()),
                float(roi_rect.top()) - label_height,
                label_width,
                label_height,
            )
        return QRectF(
            float(roi_rect.left()),
            float(roi_rect.top()),
            label_width,
            label_height,
        )
