"""Unit tests for the bounds-checked PMX binary cursor."""

import struct

import pytest

from pypmxvmd.common.pmx import PmxCursor, PmxFormatError, PmxLimits


@pytest.mark.parametrize("size", [1, 2, 4])
def test_read_index_preserves_signedness_and_little_endian(size):
    signed_payload = (-1).to_bytes(size, "little", signed=True)
    unsigned_payload = (2 ** (size * 8) - 1).to_bytes(size, "little", signed=False)
    cursor = PmxCursor(signed_payload + unsigned_payload, section="indices")

    assert cursor.read_index(size, signed=True) == -1
    assert cursor.read_index(size, signed=False) == 2 ** (size * 8) - 1
    assert cursor.remaining == 0


def test_unpack_is_little_endian_and_rejects_other_prefixes():
    cursor = PmxCursor(b"\x34\x12", section="layout")

    assert cursor.unpack("H") == (0x1234,)

    with pytest.raises(PmxFormatError, match="little-endian") as caught:
        PmxCursor(b"\x00\x00", section="layout").unpack(">H")

    assert caught.value.section == "layout"
    assert caught.value.offset == 0


def test_read_exact_failure_does_not_advance_and_has_context():
    cursor = PmxCursor(b"abc", section="vertices")
    cursor.read_exact(2)

    with pytest.raises(PmxFormatError, match="only 1 remain") as caught:
        cursor.read_exact(2)

    assert cursor.position == 2
    assert caught.value.section == "vertices"
    assert caught.value.offset == 2


@pytest.mark.parametrize("size", [-1, 3])
def test_invalid_read_or_index_size_is_rejected(size):
    cursor = PmxCursor(b"\x00" * 4, section="indices")

    operation = cursor.read_exact if size == -1 else cursor.read_index
    with pytest.raises(PmxFormatError) as caught:
        operation(size)

    assert caught.value.section == "indices"
    assert caught.value.offset == 0


@pytest.mark.parametrize("position", [-1, 4])
def test_position_must_stay_inside_source(position):
    cursor = PmxCursor(b"abc", section="header")

    with pytest.raises(PmxFormatError, match="outside"):
        cursor.set_position(position)

    assert cursor.position == 0


def test_read_count_rejects_negative_and_excessive_values():
    negative = PmxCursor(struct.pack("<i", -1), section="bones")
    with pytest.raises(PmxFormatError, match="Negative PMX bone count") as caught:
        negative.read_count("bone count")
    assert caught.value.offset == 0

    limited = PmxCursor(
        struct.pack("<i", 3),
        section="bones",
        limits=PmxLimits(max_count=2),
    )
    with pytest.raises(PmxFormatError, match="exceeds limit 2"):
        limited.read_count("bone count")


def test_read_string_enforces_length_limit_and_strict_decoding():
    too_long = PmxCursor(
        struct.pack("<i", 4) + b"text",
        section="header",
        limits=PmxLimits(max_string_bytes=3),
    )
    with pytest.raises(PmxFormatError, match="string byte length 4"):
        too_long.read_string("utf-8")

    invalid = PmxCursor(
        struct.pack("<i", 1) + b"\xff",
        section="header",
    )
    with pytest.raises(PmxFormatError, match="Invalid PMX utf-8 string"):
        invalid.read_string("utf-8")


def test_source_size_limit_is_checked_before_reading():
    with pytest.raises(PmxFormatError, match="max_source_bytes=3") as caught:
        PmxCursor(b"abcd", limits=PmxLimits(max_source_bytes=3))

    assert caught.value.section == "header"
    assert caught.value.offset == 0


def test_span_records_success_and_failure_boundaries():
    cursor = PmxCursor(b"abcdef", section="root")

    with cursor.span("header"):
        cursor.read_exact(2)

    with pytest.raises(PmxFormatError):
        with cursor.span("vertices"):
            cursor.read_exact(3)
            cursor.read_exact(2)

    assert [
        (span.name, span.start_offset, span.end_offset) for span in cursor.spans
    ] == [
        ("header", 0, 2),
        ("vertices", 2, 5),
    ]
    assert cursor.section == "root"


def test_limits_require_positive_values():
    with pytest.raises(ValueError, match="max_patch_count"):
        PmxLimits(max_patch_count=0)
