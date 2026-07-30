"""Synthetic tests for VMD binary and text parser entry points."""

import pytest

from pypmxvmd.common.parsers.vmd_parser import VmdParser


def test_vmd_binary_parser_roundtrip(tmp_path, sample_vmd_motion):
    parser = VmdParser()
    path = tmp_path / "motion.vmd"
    parser.write_file(sample_vmd_motion, path)

    loaded = parser.parse_file(path)

    assert loaded.header.to_list() == [2, "TestModel"]
    assert loaded.bone_frames[0].bone_name == "センター"
    assert loaded.bone_frames[0].frame_number == 12
    assert loaded.bone_frames[0].position == pytest.approx([1.0, 2.0, 3.0])
    assert loaded.morph_frames[0].morph_name == "笑い"
    assert loaded.morph_frames[0].weight == pytest.approx(0.75)


def test_vmd_text_parser_roundtrip(tmp_path, sample_vmd_motion):
    parser = VmdParser()
    path = tmp_path / "motion.txt"
    parser.write_text_file(sample_vmd_motion, path)

    loaded = parser.parse_text_file(path)

    assert loaded.header.to_list() == [2, "TestModel"]
    assert loaded.bone_frames[0].to_list() == sample_vmd_motion.bone_frames[0].to_list()
    assert loaded.morph_frames[0].morph_name == "笑い"
    assert loaded.morph_frames[0].weight == pytest.approx(0.75)
