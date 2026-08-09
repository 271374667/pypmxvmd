"""Malformed PMX bytes remain bounded and never produce output artifacts."""

import struct

import pytest

from pypmxvmd.common.pmx import PmxFormatError, PmxLimits
from pypmxvmd.common.parsers.pmx_parser import PmxParser


def _pmx_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<i", len(encoded)) + encoded


def _empty_pmx20() -> tuple[bytes, list[int]]:
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    data.extend(bytes((8, 1, 0, 1, 1, 1, 1, 1, 1)))
    for value in ("malformed", "malformed", "", ""):
        data.extend(_pmx_string(value))

    count_offsets = []
    for _ in range(9):
        count_offsets.append(len(data))
        data.extend(struct.pack("<i", 0))
    return bytes(data), count_offsets


def test_truncated_joint_count_has_section_and_offset_without_output(tmp_path):
    source, count_offsets = _empty_pmx20()
    input_path = tmp_path / "truncated-joint.pmx"
    output_path = tmp_path / "must-not-exist.pmx"
    input_path.write_bytes(source[:-1])

    with pytest.raises(PmxFormatError) as caught:
        PmxParser().parse_file_partial(input_path)

    assert caught.value.section == "joints"
    assert caught.value.offset == count_offsets[-1]
    assert caught.value.report is not None
    assert caught.value.report.failed_section == "joints"
    assert not output_path.exists()


def test_nested_morph_count_limit_fails_before_record_iteration(tmp_path):
    source, count_offsets = _empty_pmx20()
    malformed = bytearray(source)
    malformed[count_offsets[5] : count_offsets[5] + 4] = struct.pack("<i", 2)
    path = tmp_path / "oversized-morph-count.pmx"
    path.write_bytes(malformed)

    with pytest.raises(PmxFormatError, match="exceeds limit 1") as caught:
        PmxParser(limits=PmxLimits(max_count=1)).parse_file_partial(path)

    assert caught.value.section == "morphs"
    assert caught.value.offset == count_offsets[5]


def test_negative_frame_count_fails_at_exact_field(tmp_path):
    source, count_offsets = _empty_pmx20()
    malformed = bytearray(source)
    malformed[count_offsets[6] : count_offsets[6] + 4] = struct.pack("<i", -1)
    path = tmp_path / "negative-frame-count.pmx"
    path.write_bytes(malformed)

    with pytest.raises(
        PmxFormatError, match="Negative PMX display frame count"
    ) as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "display_frames"
    assert caught.value.offset == count_offsets[6]
