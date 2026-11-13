"""Public LMSRAW histogram decoder interfaces."""

from __future__ import annotations

from collections.abc import Callable

from .event_flags import PRIMARY_EVENT_FLAGS
from .histogram_core import HistogramCube
from .raw_container import RawPreparedReader
from .raw_selection import decode_selected_raw


class RawPreparedDecoder(RawPreparedReader):
    """Established prepared-decoder API using shared photon
    selection.
    """

    def decode(
        self,
        bins: int = 128,
        linear_plane: int | None = None,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        threads: int | None = None,
        prefer_native: bool = True,
        event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    ) -> HistogramCube:
        """Decode with the photon selection shared by preview and
        exports.
        """
        return decode_selected_raw(
            self.dataset,
            bins=bins,
            linear_plane=linear_plane,
            progress=progress,
            cancelled=cancelled,
            threads=threads,
            prefer_native=prefer_native,
            prepared=self,
            event_flag_mask=event_flag_mask,
        )

    def decode_plane(
        self,
        linear_plane: int,
        bins: int = 128,
        threads: int | None = None,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    ) -> HistogramCube:
        """Decode one indexed plane with the selected photon
        semantics.
        """
        return self.decode(
            bins=bins,
            linear_plane=linear_plane,
            threads=threads,
            progress=progress,
            cancelled=cancelled,
            event_flag_mask=event_flag_mask,
        )


def decode_raw_histogram(
    dataset,
    bins: int = 128,
    linear_plane: int | None = None,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    threads: int | None = None,
    prefer_native: bool = True,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
) -> HistogramCube:
    """Compute decode raw histogram."""
    with RawPreparedDecoder(dataset) as decoder:
        return decoder.decode(
            bins=bins,
            linear_plane=linear_plane,
            progress=progress,
            cancelled=cancelled,
            threads=threads,
            prefer_native=prefer_native,
            event_flag_mask=event_flag_mask,
        )
