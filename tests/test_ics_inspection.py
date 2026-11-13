"""Independent reading of scanner and Interrogator ICS axis orders."""

import gzip
from itertools import permutations

import numpy as np
import pytest

from leica_flim_converter.export_inspection import read_ics


@pytest.mark.parametrize("order", list(permutations(("x", "y", "t"))))
@pytest.mark.parametrize("compression", ["gzip", "uncompressed"])
def test_ics_axis_permutations(tmp_path, order, compression):
    """Recover every count from independent nonsquare arrays."""
    canonical = np.arange(60, dtype="<u2").reshape(5, 3, 4)
    dimensions = {"t": 5, "y": 3, "x": 4}
    axes = ("t", "y", "x")
    storage = canonical.transpose(*(axes.index(a) for a in reversed(order)))
    payload = storage.tobytes()
    if compression == "gzip":
        payload = gzip.compress(payload)
    header = (
        "ics_version\t2.0\nlayout\torder\tbits\t"
        + "\t".join(order)
        + "\nlayout\tsizes\t16\t"
        + "\t".join(str(dimensions[axis]) for axis in order)
        + f"\nrepresentation\tcompression\t{compression}\nend\n"
    )
    path = tmp_path / "independent.ics"
    path.write_bytes(header.encode("ascii") + payload)
    np.testing.assert_array_equal(read_ics(path).counts, canonical)
