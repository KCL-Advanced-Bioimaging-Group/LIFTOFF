"""Regress direct native bounds and unsafe XML metadata rejection."""

# Exercise the C ABI without the Python catalog's earlier guard.
# pylint: disable=protected-access

import ctypes
import struct
import xml.etree.ElementTree as ET

import pytest

import lif_flim_forensics as lif
from leica_flim_converter.native_decoder import _load_library
from leica_xml import parse_xml, reject_xml_declarations
from tests.compressed_fixture import _container

DECLARATIONS = (
    "<!DOCTYPE LMSDataContainerHeader>",
    '<!DOCTYPE LMSDataContainerHeader [<!ENTITY value "control">]>',
    '<!DOCTYPE LMSDataContainerHeader SYSTEM "file:///must-not-be-read">',
    "<!DOCTYPE LMSDataContainerHeader [<!ENTITY % e SYSTEM "
    '"https://invalid.example/entity">%e;]>',
)


@pytest.mark.parametrize("declaration", DECLARATIONS)
def test_xml_declarations_rejected(declaration: str) -> None:
    """Reject small controls before expansion, files or networking."""
    xml = declaration + "<LMSDataContainerHeader/>"
    with pytest.raises(ET.ParseError, match="DTDs and entity"):
        parse_xml(xml)


@pytest.mark.parametrize("encoding", ["utf-16le", "utf-16be"])
@pytest.mark.parametrize("declaration", DECLARATIONS)
def test_lif_header_declarations_rejected(
    declaration: str, encoding: str
) -> None:
    """Validate the complete header before regex fragment extraction."""
    xml = (
        declaration + "<LMSDataContainerHeader></LMSDataContainerHeader>"
    ).encode(encoding)
    container = bytes(12) + xml
    with pytest.raises(ET.ParseError, match="DTDs and entity"):
        lif.parse_lif_header(container)


def test_ordinary_xml_and_literal_declarations() -> None:
    """Keep namespaces, escapes and literal CDATA/comments intact."""
    root = parse_xml(
        '<root xmlns="urn:leica"><!-- <!DOCTYPE ignored> -->'
        "<text><![CDATA[<!ENTITY literal>]]></text>"
        '<value name="A &amp; B">&#945;</value></root>'
    )
    assert root.findtext("{urn:leica}text") == "<!ENTITY literal>"
    value = root.find("{urn:leica}value")
    assert value is not None
    assert value.text == "α" and value.get("name") == "A & B"
    # Cataloging tolerates historical Leica syntax; reject declarations
    # without changing that compatibility into full XML validation.
    reject_xml_declarations('<Element Name="A & B">')


def test_xml_metadata_size_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the size boundary without allocating large metadata."""
    monkeypatch.setattr("leica_xml.MAX_XML_CHARACTERS", 4)
    assert parse_xml("<r/>").tag == "r"
    with pytest.raises(ET.ParseError, match="size limit"):
        parse_xml("<root/>")


@pytest.mark.parametrize("expected_rows", [5, 2**32, 2**38, 2**64 - 1])
def test_native_row_allocation_guard(expected_rows: int) -> None:
    """Reject dishonest headers through the native entry point."""
    block = bytearray(_container([b"\xa8\x01", b"\xa8\x02"]))
    struct.pack_into("<Q", block, 40, expected_rows)
    library = _load_library()
    buffer = (ctypes.c_uint8 * len(block)).from_buffer(block)
    handle = ctypes.c_void_p()
    rows = ctypes.c_uint32()
    error = ctypes.create_string_buffer(512)
    status = library.leica_prepare_block(
        buffer,
        len(block),
        ctypes.byref(handle),
        ctypes.byref(rows),
        error,
        len(error),
    )
    try:
        assert status != 0 and not handle.value
        assert b"row count exceeds descriptor capacity" in error.value
    finally:
        if handle.value:
            library.leica_release_block(handle)


def test_native_valid_rows_after_rejection() -> None:
    """Rejection leaves the library usable for the next valid block."""
    block = _container([b"\xa8\x01", b"\xa8\x02"])
    library = _load_library()
    buffer = (ctypes.c_uint8 * len(block)).from_buffer_copy(block)
    handle = ctypes.c_void_p()
    rows = ctypes.c_uint32()
    error = ctypes.create_string_buffer(512)
    assert (
        library.leica_prepare_block(
            buffer,
            len(block),
            ctypes.byref(handle),
            ctypes.byref(rows),
            error,
            len(error),
        )
        == 0
    ), error.value
    try:
        assert handle.value and rows.value == 2
    finally:
        library.leica_release_block(handle)
