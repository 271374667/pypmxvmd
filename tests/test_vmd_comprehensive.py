"""Parse a hand-encoded VMD containing bone and morph sections."""

import struct

import pytest

from pypmxvmd.common.parsers.vmd_parser import VmdParser


def _fixed_shift_jis(value, size):
    return value.encode("shift_jis")[:size].ljust(size, b"\x00")


def create_comprehensive_vmd_data():
    data = bytearray(
        b"Vocaloid Motion Data "
        + b"0002"
        + (b"\x00" * 5)
        + _fixed_shift_jis("TestModel初音ミク", 20)
    )
    interpolation = bytes([20, 20, 0, 0, 20, 20] + ([107] * 10) + ([0] * 48))

    data.extend(struct.pack("<I", 2))
    data.extend(_fixed_shift_jis("全ての親", 15))
    data.extend(struct.pack("<I7f", 0, 0.0, 10.0, 0.0, 0.1, 0.2, 0.3, 0.9))
    data.extend(interpolation)
    data.extend(_fixed_shift_jis("センター", 15))
    data.extend(struct.pack("<I7f", 30, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0))
    data.extend(interpolation)

    data.extend(struct.pack("<I", 2))
    data.extend(_fixed_shift_jis("あ", 15))
    data.extend(struct.pack("<If", 0, 0.5))
    data.extend(_fixed_shift_jis("まばたき", 15))
    data.extend(struct.pack("<If", 15, 1.0))

    data.extend(struct.pack("<IIII", 0, 0, 0, 0))
    return bytes(data)


def test_hand_encoded_vmd_roundtrip(tmp_path):
    source = tmp_path / "source.vmd"
    output = tmp_path / "output.vmd"
    source.write_bytes(create_comprehensive_vmd_data())
    parser = VmdParser()

    motion = parser.parse_file(source)

    assert motion.header.version == 2
    assert motion.header.model_name == "TestModel初音ミク"
    assert [frame.bone_name for frame in motion.bone_frames] == [
        "全ての親",
        "センター",
    ]
    assert [frame.frame_number for frame in motion.bone_frames] == [0, 30]
    assert motion.bone_frames[0].position == pytest.approx([0.0, 10.0, 0.0])
    assert [frame.morph_name for frame in motion.morph_frames] == ["あ", "まばたき"]
    assert [frame.weight for frame in motion.morph_frames] == pytest.approx([0.5, 1.0])
    assert not motion.camera_frames
    assert not motion.light_frames
    assert not motion.shadow_frames
    assert not motion.ik_frames

    parser.write_file(motion, output)
    loaded = parser.parse_file(output)

    assert loaded.header.to_list() == motion.header.to_list()
    assert [frame.bone_name for frame in loaded.bone_frames] == [
        frame.bone_name for frame in motion.bone_frames
    ]
    assert [frame.frame_number for frame in loaded.morph_frames] == [0, 15]
