"""Regression tests for little-endian VMD struct layouts."""

import struct

import pytest

from pypmxvmd.common.parsers.vmd_parser import VmdParser


@pytest.mark.parametrize(
    ("native_format", "portable_format", "native_size", "portable_size"),
    [
        ("I b f", "<I b f", 12, 9),
        ("I ? I", "<I ? I", 12, 9),
    ],
)
def test_little_endian_formats_do_not_use_native_padding(
    native_format, portable_format, native_size, portable_size
):
    assert struct.calcsize(native_format) == native_size
    assert struct.calcsize(portable_format) == portable_size


@pytest.mark.parametrize(
    ("attribute", "expected_format", "expected_size"),
    [
        ("_FMT_MORPHFRAME", "<I f", 8),
        ("_FMT_SHADOWFRAME", "<I b f", 9),
        ("_FMT_IKDISPFRAME", "<I ? I", 9),
    ],
)
def test_parser_uses_portable_struct_formats(attribute, expected_format, expected_size):
    parser_format = getattr(VmdParser, attribute)

    assert parser_format == expected_format
    assert struct.calcsize(parser_format) == expected_size
