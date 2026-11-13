"""Public API for the Leica LAS X compressed FLIM decoder."""

from importlib import import_module

from .catalog import DatasetInfo, IndexCancelled, scan_lif
from .histogram import HistogramCube, decode_histogram_cube
from .ics import build_decay_stack, write_ics
from .ics_export import IcsExportOptions, export_ics_blocks
from .native_decoder import decode_histogram_plane, native_decoder_info
from .ptu import parse_ptu
from .ptu_export import (
    PtuExportOptions,
    export_ptu_blocks,
    proposed_ptu_filenames,
)

__all__ = [
    "DatasetInfo",
    "IndexCancelled",
    "HistogramCube",
    "decode_histogram_cube",
    "native_decoder_info",
    "decode_histogram_plane",
    "build_decay_stack",
    "scan_lif",
    "write_ics",
    "IcsExportOptions",
    "export_ics_blocks",
    "parse_ptu",
    "PtuExportOptions",
    "proposed_ptu_filenames",
    "export_ptu_blocks",
]
_LEGACY_EXPORTS = {
    "DecodeResult": (".core", "DecodeResult"),
    "decode_file": (".core", "decode_file"),
    "convert_file": (".formats", "convert_file"),
    "write_bh_spc_fifo32": (".formats", "write_bh_spc_fifo32"),
    "write_csv": (".formats", "write_csv"),
    "write_npz": (".formats", "write_npz"),
    "write_ptu": (".formats", "write_ptu"),
    "export_datasets": (".fast_export", "export_datasets"),
}


def __getattr__(name: str):
    if name not in _LEGACY_EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _LEGACY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
