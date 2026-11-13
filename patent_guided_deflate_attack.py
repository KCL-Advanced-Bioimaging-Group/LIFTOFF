"""Patent-guided attack on Leica's grouped FLIM Deflate stream.

The Leica patent US20230344447 describes sorted arrival-time
differences, 8-bit class/photon/escape/pixel markers, and Deflate
entropy coding without LZ matches. This script parses Deflate at bit
level, recovers all valid leading blocks, scans for independently framed
streams, and compares decoded token statistics with the matched PTU
photon oracle.
"""

from __future__ import annotations

import struct
from collections import Counter
from pathlib import Path

import numpy as np

LENGTH_BASE = [
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    13,
    15,
    17,
    19,
    23,
    27,
    31,
    35,
    43,
    51,
    59,
    67,
    83,
    99,
    115,
    131,
    163,
    195,
    227,
    258,
]
LENGTH_EXTRA = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    1,
    1,
    1,
    1,
    2,
    2,
    2,
    2,
    3,
    3,
    3,
    3,
    4,
    4,
    4,
    4,
    5,
    5,
    5,
    5,
    0,
]
DIST_BASE = [
    1,
    2,
    3,
    4,
    5,
    7,
    9,
    13,
    17,
    25,
    33,
    49,
    65,
    97,
    129,
    193,
    257,
    385,
    513,
    769,
    1025,
    1537,
    2049,
    3073,
    4097,
    6145,
    8193,
    12289,
    16385,
    24577,
]
DIST_EXTRA = [
    0,
    0,
    0,
    0,
    1,
    1,
    2,
    2,
    3,
    3,
    4,
    4,
    5,
    5,
    6,
    6,
    7,
    7,
    8,
    8,
    9,
    9,
    10,
    10,
    11,
    11,
    12,
    12,
    13,
    13,
]
CODE_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]


class DeflateError(Exception):
    """Represent deflate error."""


class BitReader:
    """Represent bit reader."""

    def __init__(self, data: bytes, bitpos: int = 0, limit: int | None = None):
        self.data = data
        self.pos = bitpos
        self.limit = (
            len(data) * 8 if limit is None else min(limit, len(data) * 8)
        )

    def read(self, count: int) -> int:
        """Compute read."""
        if self.pos + count > self.limit:
            raise DeflateError("end of input")
        byte = self.pos >> 3
        shift = self.pos & 7
        needed = shift + count + 7 >> 3
        value = 0
        for index in range(needed):
            value |= self.data[byte + index] << index * 8
        value = value >> shift & (1 << count) - 1
        self.pos += count
        return value

    def peek(self, count: int) -> int:
        """Read up to ``count`` low-order stream bits without
        advancing.
        """
        available = min(count, self.limit - self.pos)
        if available <= 0:
            return 0
        byte = self.pos >> 3
        shift = self.pos & 7
        needed = shift + available + 7 >> 3
        value = 0
        for index in range(needed):
            value |= self.data[byte + index] << index * 8
        return value >> shift & (1 << available) - 1

    def align_byte(self) -> None:
        """Compute align byte."""
        self.pos = self.pos + 7 & ~7


def reverse_bits(value: int, width: int) -> int:
    """Compute reverse bits."""
    result = 0
    for _ in range(width):
        result = result << 1 | value & 1
        value >>= 1
    return result


def huffman(lengths: list[int], allow_empty: bool = False):
    """Compute huffman."""
    maximum = max(lengths, default=0)
    if maximum == 0:
        if allow_empty:
            return ({}, 0)
        raise DeflateError("empty Huffman alphabet")
    counts = [0] * (maximum + 1)
    for length in lengths:
        if length:
            counts[length] += 1
    code, next_code = (0, [0] * (maximum + 1))
    for bits in range(1, maximum + 1):
        code = code + counts[bits - 1] << 1
        next_code[bits] = code
    codes = []
    for symbol, length in enumerate(lengths):
        if length:
            canonical = next_code[length]
            next_code[length] += 1
            codes.append((reverse_bits(canonical, length), length, symbol))
    symbols = [-1] * (1 << maximum)
    widths = [0] * (1 << maximum)
    for code, length, symbol in codes:
        for index in range(code, 1 << maximum, 1 << length):
            symbols[index] = symbol
            widths[index] = length
    return ((symbols, widths), maximum)


def decode_symbol(reader: BitReader, table, maximum: int) -> int:
    """Compute decode symbol."""
    symbols, widths = table
    index = reader.peek(maximum)
    width = widths[index]
    if not width or reader.pos + width > reader.limit:
        raise DeflateError("invalid Huffman code")
    reader.pos += width
    return symbols[index]


def fixed_tables():
    """Compute fixed tables."""
    literal_lengths = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
    return (huffman(literal_lengths), huffman([5] * 32))


def dynamic_tables(reader: BitReader):
    """Compute dynamic tables."""
    hlit, hdist, hclen = (
        reader.read(5) + 257,
        reader.read(5) + 1,
        reader.read(4) + 4,
    )
    code_lengths = [0] * 19
    for symbol in CODE_ORDER[:hclen]:
        code_lengths[symbol] = reader.read(3)
    code_table, code_max = huffman(code_lengths)
    result = []
    while len(result) < hlit + hdist:
        symbol = decode_symbol(reader, code_table, code_max)
        if symbol <= 15:
            result.append(symbol)
        elif symbol == 16:
            if not result:
                raise DeflateError("repeat without previous code")
            result.extend([result[-1]] * (reader.read(2) + 3))
        elif symbol == 17:
            result.extend([0] * (reader.read(3) + 3))
        elif symbol == 18:
            result.extend([0] * (reader.read(7) + 11))
        if len(result) > hlit + hdist:
            raise DeflateError("code-length repeat overflow")
    return (
        huffman(result[:hlit]),
        huffman(result[hlit:], allow_empty=True),
        {
            "hlit": hlit,
            "hdist": hdist,
            "hclen": hclen,
            "literalCodeLengths": result[:hlit],
            "distanceCodeLengths": result[hlit:],
        },
    )


def _consume_deflate_symbols(
    reader: BitReader,
    output: bytearray,
    literal_table,
    distance_table,
    max_output: int,
) -> tuple[int, int, int]:
    """Expand a Huffman block, including overlapping back-references and
    bounds.
    """
    literals = matches = match_bytes = 0
    lit_map, lit_max = literal_table
    dist_map, dist_max = distance_table
    while True:
        symbol = decode_symbol(reader, lit_map, lit_max)
        if symbol < 256:
            output.append(symbol)
            literals += 1
            if len(output) > max_output:
                raise DeflateError("output limit")
        elif symbol == 256:
            break
        elif 257 <= symbol <= 285:
            index = symbol - 257
            length = LENGTH_BASE[index] + reader.read(LENGTH_EXTRA[index])
            if dist_max == 0:
                raise DeflateError(
                    "length symbol with empty distance alphabet"
                )
            distance_symbol = decode_symbol(reader, dist_map, dist_max)
            if distance_symbol >= len(DIST_BASE):
                raise DeflateError("reserved distance symbol")
            distance = DIST_BASE[distance_symbol] + reader.read(
                DIST_EXTRA[distance_symbol]
            )
            if distance > len(output):
                raise DeflateError("distance beyond output")
            for _ in range(length):
                output.append(output[-distance])
                if len(output) > max_output:
                    raise DeflateError("output limit")
            matches += 1
            match_bytes += length
        else:
            raise DeflateError("reserved literal/length symbol")
    return (literals, matches, match_bytes)


def parse_deflate(
    data: bytes,
    start_bit: int,
    limit_bit: int | None = None,
    initial_output: bytes = b"",
    max_blocks: int = 10000,
    max_output: int = 10000000,
) -> dict:
    """Compute parse deflate."""
    reader = BitReader(data, start_bit, limit_bit)
    output = bytearray(initial_output)
    blocks, error = ([], None)
    try:
        for _ in range(max_blocks):
            block_start = reader.pos
            final, block_type = (reader.read(1), reader.read(2))
            literals, matches, match_bytes = (0, 0, 0)
            dynamic = None
            if block_type == 0:
                reader.align_byte()
                length, inverse = (reader.read(16), reader.read(16))
                if length ^ 65535 != inverse:
                    raise DeflateError("invalid stored block lengths")
                for _ in range(length):
                    output.append(reader.read(8))
                    if len(output) > max_output:
                        raise DeflateError("output limit")
                literals = length
            elif block_type in (1, 2):
                if block_type == 1:
                    literal_table, distance_table = fixed_tables()
                else:
                    literal_table, distance_table, dynamic = dynamic_tables(
                        reader
                    )
                literals, matches, match_bytes = _consume_deflate_symbols(
                    reader, output, literal_table, distance_table, max_output
                )
            else:
                raise DeflateError("reserved block type")
            blocks.append(
                {
                    "startBit": block_start,
                    "endBit": reader.pos,
                    "final": final,
                    "type": block_type,
                    "literals": literals,
                    "matches": matches,
                    "matchBytes": match_bytes,
                    "outputBytes": len(output),
                    "dynamic": dynamic,
                }
            )
            if final:
                break
    except DeflateError as exc:
        error = {"bit": reader.pos, "message": str(exc)}
    return {
        "startBit": start_bit,
        "endBit": reader.pos,
        "blocks": blocks,
        "output": bytes(output[len(initial_output) :]),
        "error": error,
        "final": bool(blocks and blocks[-1]["final"] and (error is None)),
    }


def load_container_bytes(data: bytes):
    """Parse an extracted Leica FLIM Compressed MemBlock from memory."""
    header = struct.unpack_from("<8Q", data, 0)
    stream_start = int(header[1])
    stream = data[stream_start : stream_start + int(header[2])]
    table_start = stream_start + int(header[2])
    table = data[table_start : table_start + int(header[3])]
    values = np.frombuffer(table, dtype="<u4")
    lengths = np.asarray(
        [int(value) & 1073741823 for value in values], dtype=np.int64
    )
    flags = np.asarray(
        [int(value) >> 16 & 49152 for value in values], dtype=np.int64
    )
    return (header, stream, lengths, flags)


def load_container(path: Path):
    """Compute load container."""
    return load_container_bytes(path.read_bytes())


def _descriptor_header(
    reader: BitReader,
    start: int,
    group_lengths: np.ndarray,
    group_flags: np.ndarray,
) -> tuple:
    """Validate the zlib wrapper, dynamic alphabet and Leica control
    descriptors.
    """
    wrapper = bytes((reader.read(8), reader.read(8)))
    final, block_type = (reader.read(1), reader.read(2))
    if block_type != 2:
        raise DeflateError(f"expected dynamic Huffman block, got {block_type}")
    literal_table, _distance_table, dynamic = dynamic_tables(reader)
    header_bits = reader.pos - start - 16
    expected_header = int(group_lengths[1])
    if header_bits != expected_header:
        raise DeflateError(
            "dynamic header used "
            f"{header_bits}"
            ", descriptor says "
            f"{expected_header}"
        )
    if int(group_flags[0]) != 0 or int(group_flags[1]) != 49152:
        raise DeflateError("unexpected control descriptor flags")
    return (wrapper, final, literal_table, dynamic, header_bits)


def _descriptor_row(
    reader: BitReader,
    stream: bytes,
    bit_length: int,
    literal_table,
    line_number: int,
    group: int,
    relative: int,
) -> dict:
    """Decode one descriptor-bounded literal segment without crossing
    its boundary.
    """
    lit_map, lit_max = literal_table
    segment_start = reader.pos
    segment_end = segment_start + (bit_length)
    segment_reader = BitReader(stream, segment_start, segment_end)
    tokens, eob = (bytearray(), 0)
    while segment_reader.pos < segment_end:
        symbol = decode_symbol(segment_reader, lit_map, lit_max)
        if symbol < 256:
            tokens.append(symbol)
        elif symbol == 256:
            eob += 1
        else:
            raise DeflateError(f"row contains length symbol {symbol}")
    if segment_reader.pos != segment_end:
        raise DeflateError("row codeword crosses descriptor boundary")
    reader.pos = segment_end
    row = {
        "line": line_number,
        "group": group,
        "rel": relative - 2,
        "compressedBits": (bit_length),
        "tokens": bytes(tokens),
        "eob": eob,
    }
    return row


def decode_descriptor_rows(
    stream: bytes,
    lengths: np.ndarray,
    flags: np.ndarray,
    row_callback=None,
    keep_rows: bool = True,
    row_range: tuple[int, int] | None = None,
):
    """Compute decode descriptor rows."""
    rows, groups, errors = ([], [], [])
    cursor, base, group, line_number = (0, 0, 0, 0)
    while base < len(lengths):
        if int(flags[base]) != 0:
            raise ValueError(
                "Descriptor group "
                f"{group}"
                " starts with flag 0x"
                f"{int(flags[base]):04x}"
            )
        next_base = base + 1
        while next_base < len(lengths) and int(flags[next_base]) != 0:
            next_base += 1
        group_lengths = lengths[base:next_base]
        group_flags = flags[base:next_base]
        if len(group_lengths) < 3:
            raise ValueError(f"Descriptor group {group} has no row payload")
        start, end = (cursor, cursor + int(group_lengths.sum()))
        reader = BitReader(stream, start, end)
        try:
            header = _descriptor_header(
                reader, start, group_lengths, group_flags
            )
            group_output = 0
            for rel in range(2, len(group_lengths)):
                if row_range is not None and not (
                    row_range[0] <= line_number < sum(row_range)
                ):
                    reader.pos += int(group_lengths[rel])
                    line_number += 1
                    continue
                row = _descriptor_row(
                    reader,
                    stream,
                    int(group_lengths[rel]),
                    header[2],
                    line_number,
                    group,
                    rel,
                )
                group_output += len(row["tokens"])
                if row_callback is not None:
                    row_callback(row)
                if keep_rows:
                    rows.append(row)
                line_number += 1
            groups.append(
                {
                    "group": group,
                    "startBit": start,
                    "endBit": end,
                    "wrapper": header[0].hex(),
                    "final": header[1],
                    "headerBits": header[4],
                    "outputBytes": group_output,
                    "literalAlphabet": sum(
                        bool(value)
                        for value in header[3]["literalCodeLengths"]
                    ),
                    "distanceAlphabet": sum(
                        bool(value)
                        for value in header[3]["distanceCodeLengths"]
                    ),
                }
            )
        except DeflateError as exc:
            errors.append(
                {"group": group, "bit": reader.pos, "message": str(exc)}
            )
        cursor = end
        base = next_base
        group += 1
    return (rows, groups, errors, cursor)


def decode_event_classes(
    rows: list[dict], class_markers: set[int]
) -> list[dict]:
    """Decode pixel runs and sorted arrival-time deltas for selected
    classes.
    """
    return [
        {"line": line, "x": x, "dt": dt, "class": marker}
        for line, x, dt, marker in iter_event_tuples(rows, class_markers)
    ]


def iter_event_tuples(rows: list[dict], class_markers: set[int]):
    """Yield ``(line, x, microtime, class)`` without allocating event
    dicts.
    """
    for row in rows:
        x, index, tokens = (0, 0, row["tokens"])
        while index < len(tokens):
            token = tokens[index]
            if 129 <= token <= 159:
                x += token & 31
                index += 1
                continue
            if token not in class_markers:
                index += 1
                continue
            marker = token
            index += 1
            deltas = []
            while index < len(tokens):
                token = tokens[index]
                if token < 128:
                    deltas.append(token)
                    index += 1
                elif (
                    192 <= token <= 255
                    and index + 1 < len(tokens)
                    and (tokens[index + 1] < 128)
                ):
                    deltas.append((token & 63) << 7 | tokens[index + 1])
                    index += 2
                else:
                    break
            arrival = 0
            for event_index, delta in enumerate(deltas):
                arrival = delta if event_index == 0 else arrival + delta
                yield (row["line"], x, arrival, marker)


def event_multisets(events: list[dict], line_count: int) -> list[Counter]:
    """Compute event multisets."""
    result = [Counter() for _ in range(line_count)]
    for event in events:
        result[event["line"]][event["x"], event["dt"]] += 1
    return result


def zlib_headers(stream: bytes) -> list[int]:
    """Compute zlib headers."""
    result = []
    for offset in range(len(stream) - 1):
        cmf, flg = (stream[offset], stream[offset + 1])
        if cmf & 15 == 8 and cmf >> 4 <= 7 and (((cmf << 8) + flg) % 31 == 0):
            result.append(offset)
    return result


def parse_zlib_candidate(stream: bytes, offset: int) -> dict:
    """Compute parse zlib candidate."""
    if offset + 2 > len(stream):
        return {"offset": offset, "valid": False}
    cmf, flg = (stream[offset], stream[offset + 1])
    start = (offset + 2) * 8
    if flg & 32:
        start += 32
    parsed = parse_deflate(stream, start)
    return {
        "offset": offset,
        "cmf": cmf,
        "flg": flg,
        "deflateStartBit": start,
        "endBit": parsed["endBit"],
        "blockCount": len(parsed["blocks"]),
        "outputBytes": len(parsed["output"]),
        "final": parsed["final"],
        "error": parsed["error"],
        "blocks": parsed["blocks"],
        "output": parsed["output"],
    }


def token_metrics(data: bytes) -> dict:
    """Compute token metrics."""
    counts = Counter(data)
    high = sum(value >= 128 for value in data)
    low7 = Counter(value & 127 for value in data)
    return {
        "bytes": len(data),
        "unique": len(counts),
        "highBitFraction": high / len(data) if data else 0.0,
        "topBytes": [
            [(f"0x{value:02x}"), count]
            for value, count in counts.most_common(20)
        ],
        "topLow7": [[value, count] for value, count in low7.most_common(20)],
    }


def scan_literal_blocks(stream: bytes) -> list[dict]:
    """Find independently decodable dynamic-Huffman, literal-only
    blocks.
    """
    result = []
    total_bits = len(stream) * 8
    for bit in range(0, total_bits - 32):
        if stream[bit + 1 >> 3] >> (bit + 1 & 7) & 1 != 0:
            continue
        if stream[bit + 2 >> 3] >> (bit + 2 & 7) & 1 != 1:
            continue
        parsed = parse_deflate(stream, bit, max_blocks=1, max_output=20000)
        if not parsed["blocks"]:
            continue
        block = parsed["blocks"][0]
        output = parsed["output"]
        if block["type"] != 2 or block["matches"] != 0 or len(output) < 8:
            continue
        high_fraction = sum(value >= 128 for value in output) / len(output)
        if high_fraction < 0.7:
            continue
        result.append(
            {
                "startBit": bit,
                "endBit": block["endBit"],
                "compressedBits": block["endBit"] - bit,
                "outputBytes": len(output),
                "highBitFraction": high_fraction,
                "uniqueBytes": len(set(output)),
                "final": block["final"],
                "output": output,
            }
        )
    return result
