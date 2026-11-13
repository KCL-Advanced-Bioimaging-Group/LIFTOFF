"""Maintained desktop component: workspace preview."""

from __future__ import annotations

from abc import abstractmethod
from time import perf_counter

import numpy as np

from .dataset import DatasetInfo
from .gui_helpers import _histogram_values_2, _normalized_error_2
from .gui_models import ChannelPanel, Roi, connect_signal
from .gui_workers import DecodeWorker
from .gui_workspace_state import WorkspaceState
from .histogram_core import HistogramCube
from .mosaic_views import tile_view
from .native_decoder import native_decoder_info


class WorkspacePreview(WorkspaceState):
    """Preview workers, selection transitions, and explicit failures."""

    def start_selected_preview(self, linear_plane: int | None) -> None:
        """Start selected preview."""
        if (
            self.selected is None
            or self.decode_worker is not None
            or self.export_worker is not None
            or (self.scan_worker is not None)
            or self._closing
        ):
            return
        self.current_plane = linear_plane
        label = (
            self.selected.plane_label(linear_plane)
            if linear_plane is not None
            else "summed overview"
        )
        self.image_title.setText(f"Photon image: {label}")
        self.histogram.set_histogram(summary=f"Decoding {label}")
        self.image.clear_image()
        self._busy(True)
        self.cancel_button.setEnabled(True)
        self.block_list.setEnabled(False)
        self.plane_controls.setEnabled(False)
        self.decode_started = perf_counter()
        self.timer.start(100)
        info = native_decoder_info()
        self.backend_label.setText(
            (
                "Decoder: LMSRAW native"
                if info.get("rawAvailable")
                else "Decoder: LMSRAW stream (1 thread)"
            )
            if self.selected.storage_format == "lmsraw"
            else "Decoder: native"
            if info["available"]
            else "Decoder: Python fallback"
        )
        self.decode_worker = DecodeWorker(
            self.selected,
            self.thread_spin.value(),
            linear_plane,
            self.event_flags.mask(),
        )
        connect_signal(self.decode_worker.status, self._decode_status)
        connect_signal(self.decode_worker.completed, self._decode_complete)
        self.decode_worker.start()

    def start_channel_preview(self, linear_plane):
        """Start channel preview."""
        group = self.current_channel_group()
        if not group:
            self.clear_pair_preview()
            return None
        mosaic = any(item.mosaic is not None for item in group)
        if mosaic:
            group = tuple(
                tile_view(item, index)
                for item in group
                for index in range(item.stage_count)
            )
        all_channels_decode = (
            len(group) > 1
            and (
                mosaic or self._selected_channel_mode_2() == "__all_channels__"
            )
            and (self._multichannel_sequence is None)
        )
        if (
            self._pending_active_roi_restore is None
            and self._multichannel_sequence is None
            and getattr(self, "_multichannel_channel_panels", None)
            and (self._selected_channel_mode_2() == "__all_channels__")
        ):
            self._pending_active_roi_restore = (
                self._capture_active_roi_snapshot_2()
            )
        if all_channels_decode:
            self._clear_transient_image_rois_2()
        if group:
            signature = (
                tuple(item.key for item in group),
                linear_plane,
                int(self.event_flags.mask()),
            )
            if signature != self._channel_valid_signature:
                self._channel_valid_counts = {}
                self._channel_valid_signature = signature
            self._apply_group_details_2()
        if all_channels_decode:
            first = group[0]
            self._multichannel_sequence = {
                "group": tuple(group),
                "queue": list(group[1:]),
                "current": first,
                "linear_plane": linear_plane,
                "panels": [],
            }
            self.selected = first
            self.current_plane = linear_plane
            self._main_window__show_dataset_2(first)
            self._apply_group_details_2()
        return self.start_selected_preview(linear_plane)

    def _set_decode_failure_details_2(self, error):
        reason = _normalized_error_2(error)
        failed = getattr(self, "selected", None)
        failed_key = getattr(failed, "key", None)
        if failed_key is not None:
            self._channel_valid_counts.pop(failed_key, None)
        group = self.current_channel_group()
        if not group and failed is not None:
            group = (failed,)
        fields = getattr(self, "fields", {})
        failure_values = {
            "Histogram cube": "Not loaded",
            "Decoder": f"Failed: {reason}",
            "Decode time": "Not available",
        }
        for name, value in failure_values.items():
            label = fields.get(name)
            if label is None:
                continue
            label.setText(value)
            label.setToolTip(reason)
            if name == "Decoder":
                label.setWordWrap(True)
        photons = fields.get("Photons")
        if photons is not None and group:
            valid_counts = getattr(self, "_channel_valid_counts", {})
            lines = []
            for position, dataset in enumerate(group, 1):
                valid = valid_counts.get(dataset.key)
                if valid is not None:
                    state = f"{f'{int(valid):,}'} valid counts"
                elif dataset.key == failed_key:
                    state = "decode failed"
                else:
                    state = "not decoded"
                lines.append(
                    "Channel "
                    f"{position:d}"
                    ": "
                    f"{state!s}"
                    " / "
                    f"{dataset.raw_photon_label}"
                )
            photons.setText("\n".join(lines))
            photons.setToolTip(reason)
        self._decode_failure_detail = reason
        self._decode_failure_dataset_key = failed_key

    def _capture_channel_panel_2(
        self, dataset: DatasetInfo, cube: HistogramCube
    ) -> ChannelPanel:
        if (
            dataset.mosaic is not None
            and int(cube.counts.max(initial=0)) <= 65535
        ):
            cube.counts = cube.counts.astype(np.uint16)
            cube.output_bits = 16
        image = getattr(self.image, "image", None)
        image_copy = image.copy() if image is not None else None
        return {
            "dataset": dataset,
            "image": image_copy,
            "values": _histogram_values_2(cube, dataset),
            "events": int(getattr(cube, "events", 0)),
            "backend": str(getattr(cube, "backend", "unknown")),
            "elapsed": float(getattr(cube, "elapsed_seconds", 0.0)),
            "nbytes": (np.asarray(cube.counts).nbytes),
            "dtype": str(np.asarray(cube.counts).dtype),
            "period_bins": int(getattr(cube, "period_bins", 0)),
            "cube": cube,
        }

    def accept_preview_result(self, cube, error: str) -> None:
        """Accept preview result."""
        self.timer.stop()
        self.cancel_button.setEnabled(False)
        self.block_list.setEnabled(True)
        self.plane_controls.setEnabled(True)
        self._busy(False)
        self.decode_worker = None
        if self._closing:
            return
        if error:
            if self.selected:
                self.decode_failures[self.selected.key] = error
            self.status_label.setText(error)
            self.progress.setValue(0)
            return
        self.cube = cube
        self.image.set_counts(cube.intensity)
        self.progress.setValue(100)
        self.backend_label.setText(f"Decoder: {cube.backend}")
        if self.selected:
            self.decode_failures.pop(self.selected.key, None)
        self.fields["Histogram cube"].setText(
            f"{cube.counts.nbytes / 1048576:.1f} MB, uint{cube.output_bits}"
        )
        self.fields["Histogram cube"].setToolTip(
            f"Arrival window excludes {cube.overflow_events:,} "
            "selected photons; "
            "the same window policy is used for calibrated exports."
        )
        self.fields["Decoder"].setText(cube.backend)
        self.fields["Threads"].setText(str(cube.thread_count))
        self.fields["Decode time"].setText(f"{cube.elapsed_seconds:.3f} s")
        residual = (
            f" | intensity difference {cube.event_difference:+,}"
            if cube.event_difference not in (None, 0)
            else ""
        )
        self.status_label.setText(
            "Ready: "
            f"{cube.events:,}"
            " photons | "
            f"{cube.backend}"
            " decoder | "
            f"{cube.elapsed_seconds:.3f}"
            " s"
            f"{residual}"
            + (
                f" | {cube.overflow_events:,} outside arrival window"
                if cube.overflow_events
                else ""
            )
        )
        self.histogram.set_histogram(
            summary="Move over the image or drag an ROI"
        )

    def restore_filter_regions(self, cube, error):
        """Restore filter regions."""
        pending = getattr(self, "_leica_filter_roi_restore", None)
        self._leica_filter_roi_restore = None
        self.accept_preview_result(cube, error)
        if pending is None or cube is None or error:
            return
        regions, active = pending
        self.image.rois = list(regions)
        self.image.drag_start = None
        self.image.drag_current = None
        self.image.update()
        if active in regions:
            self.show_roi(*active)
        elif len(regions) == 1:
            self.show_roi(*regions[0])

    def restore_active_regions(self, cube, error):
        """Restore active regions."""
        pending = getattr(self, "_leica_multi_roi_restore", None)
        self._leica_multi_roi_restore = None
        self.restore_filter_regions(cube, error)
        if cube is None or error or self.cube is None:
            return
        self.image.ensure_interaction_state()
        if pending is not None:
            self.image.rois = [roi for roi, _color in pending]
            self.image.roi_colors = [color for _roi, color in pending]
            self.image.activated_rois = set(range(len(pending)))
            self.image.drag_start = None
            self.image.drag_current = None
        else:
            self.image.activated_rois.clear()
            self.image.ensure_roi_colors()
        self._leica_active_roi = None
        self._main_window__refresh_roi_histogram_3()

    def refresh_completed_preview(self, cube, error):
        """Refresh completed preview."""
        self.restore_active_regions(cube, error)
        if cube is not None and (not error) and (self.cube is not None):
            self._main_window__refresh_roi_histogram_5()

    def complete_channel_preview(self, cube, error):
        """Complete channel preview."""
        sequence = self._multichannel_sequence
        current = sequence.get("current") if sequence else None
        if sequence is not None:
            self._clear_transient_image_rois_2()
            self._leica_multi_roi_restore = None
            self._leica_filter_roi_restore = None
        self.refresh_completed_preview(cube, error)
        if sequence is None:
            if (
                cube is not None
                and (not error)
                and (self.selected is not None)
            ):
                self._channel_valid_counts[self.selected.key] = int(
                    cube.events
                )
                snapshot = self._pending_active_roi_restore
                self._pending_active_roi_restore = None
                if self._restore_active_roi_snapshot_2(snapshot):
                    self._refresh_roi_histogram()
                self.reflection_filter.restore_preview()
            elif error:
                self._pending_active_roi_restore = None
            self._apply_group_details_2()
            return
        if cube is None or error:
            self._multichannel_sequence = None
            self.histogram.multichannel_panels = None
            self._multichannel_channel_panels = None
            self.image.multichannel_mirror_layout = []
            self.image.multichannel_combined_rois = False
            self._pending_active_roi_restore = None
            self._apply_group_details_2()
            return
        if current is None:
            raise RuntimeError("Channel sequence has no current dataset")
        self._channel_valid_counts[current.key] = int(cube.events)
        sequence["panels"].append(self._capture_channel_panel_2(current, cube))
        self.cube = None
        if sequence["queue"]:
            following = sequence["queue"].pop(0)
            sequence["current"] = following
            self.selected = following
            self.current_plane = sequence["linear_plane"]
            self._main_window__show_dataset_2(following)
            self._apply_group_details_2()
            self.start_selected_preview(sequence["linear_plane"])
            return
        panels = list(sequence["panels"])
        group = sequence["group"]
        self._multichannel_sequence = None
        self._multichannel_channel_panels = None
        self.selected = group[0]
        self._render_all_channels_2(panels)
        self.reflection_filter.restore_preview()

    def complete_preview(self, cube, error):
        """Complete preview."""
        self.complete_channel_preview(cube, error)
        if error:
            self._set_decode_failure_details_2(error)

    def _main_window__event_flags_changed_7(self, mask):
        if (
            self.selected is None
            or self.decode_worker is not None
            or self.export_worker is not None
        ):
            return
        if self.cube is not None and self.cube.event_flag_mask == mask:
            return
        self.cube = None
        self._start_decode(self.current_plane)

    def _main_window__event_flags_changed_6(self, mask):
        regions: list[Roi] = [
            (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
            for roi in self.image.rois
        ]
        active = getattr(self, "_leica_active_roi", None)
        if active not in regions:
            active = None
        self._leica_filter_roi_restore = (regions, active) if regions else None
        self._main_window__event_flags_changed_7(mask)
        if self.decode_worker is None:
            self._leica_filter_roi_restore = None

    def _main_window__event_flags_changed_5(self, mask):
        self._leica_multi_roi_restore = self._active_snapshot_2()
        self._leica_active_roi = None
        self._main_window__event_flags_changed_6(mask)
        if self.decode_worker is None:
            self._leica_multi_roi_restore = None

    def _main_window__plane_changed_7(self, index: int) -> None:
        if (
            index < 0
            or self.selected is None
            or self.decode_worker is not None
        ):
            return
        linear_plane = self.plane_combo.itemData(index)
        if linear_plane == self.current_plane and self.cube is not None:
            return
        self.cube = None
        self._start_decode(linear_plane)

    def _main_window__plane_changed_6(self, index):
        if self.cube is not None:
            regions: list[Roi] = [
                (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
                for roi in self.image.rois
            ]
            active = getattr(self, "_leica_active_roi", None)
            if active not in regions:
                active = None
            self._leica_filter_roi_restore = (
                (regions, active) if regions else None
            )
        self._main_window__plane_changed_7(index)
        if self.decode_worker is None:
            self._leica_filter_roi_restore = None

    def _main_window__plane_changed_5(self, index):
        self._leica_multi_roi_restore = (
            self._active_snapshot_2() if self.cube is not None else None
        )
        self._leica_active_roi = None
        self._main_window__plane_changed_6(index)
        if self.decode_worker is None:
            self._leica_multi_roi_restore = None

    @abstractmethod
    def _components_ready(self) -> bool:
        """Require the final Qt workspace to combine all components."""
        raise NotImplementedError
