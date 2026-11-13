"""Shared maintained test data built without historical executables."""

import struct
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import DatasetInfo


@pytest.fixture
def raw_dataset(tmp_path: Path) -> DatasetInfo:
    """Create two real indexed rows, including a rejected
    predecessor.
    """
    xml = (
        '<LMSDataContainerHeader><Element Name="Synthetic"><RawData><S'
        "equence><SequenceItem><Detectors><Detectors><Detector>0</Dete"
        "ctor><DeadTime>2e-10</DeadTime><DataType>PulseVersion2</DataT"
        "ype></Detectors></Detectors></SequenceItem></Sequence></RawDa"
        "ta></Element></LMSDataContainerHeader>"
    ).encode("utf-16le")
    header = struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
    rows = (
        np.array([4106, 11, 13, 4098, 40964, 40968, 3], dtype=">u2").tobytes(),
        np.array([5, 4104, 4108], dtype=">u2").tobytes(),
    )
    payload = b"".join(rows)
    table = struct.pack("<5Q", 1, 2, len(payload), 0, 0)
    table += struct.pack("<4Q", len(rows[0]), 0, len(payload), 0)
    source = tmp_path / "synthetic.lif"
    source.write_bytes(header + xml + payload + table)
    start = len(header) + len(xml)
    return DatasetInfo(
        source=source,
        memory_id="MemBlock_1",
        block_start=start,
        block_end=start + len(payload),
        compressed_bytes=len(payload),
        width=2,
        height=2,
        decoded_rows=2,
        intensity_memory_id=None,
        intensity_start=None,
        intensity_end=None,
        total_photons=None,
        thumbnail=None,
        pixel_size_x_m=1e-06,
        pixel_size_y_m=1e-06,
        clock_period_s=1e-10,
        laser_frequency_hz=625000000.0,
        acquisition_name="Synthetic",
        storage_format="lmsraw",
        line_offsets_start=start + len(payload),
        line_offsets_end=source.stat().st_size,
        plane_row_starts=(0,),
    )
