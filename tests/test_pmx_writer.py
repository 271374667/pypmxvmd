"""Correctness tests for the PMX writer."""

import struct

import pytest

from pypmxvmd.common.parsers.pmx_parser import PmxParser


def test_pmx_writer_roundtrip(tmp_path, sample_pmx_model):
    parser = PmxParser()
    path = tmp_path / "model.pmx"

    parser.write_file(sample_pmx_model, path)

    data = path.read_bytes()
    assert data[:4] == b"PMX "
    assert struct.unpack("<f", data[4:8])[0] == pytest.approx(2.0)

    loaded = parser.parse_file(path)
    assert loaded.header.name_jp == sample_pmx_model.header.name_jp
    assert loaded.header.name_en == sample_pmx_model.header.name_en
    assert loaded.faces == sample_pmx_model.faces
    assert len(loaded.vertices) == len(sample_pmx_model.vertices)
    for actual, expected in zip(loaded.vertices, sample_pmx_model.vertices):
        assert actual.position == pytest.approx(expected.position)
        assert actual.normal == pytest.approx(expected.normal)
        assert actual.uv == pytest.approx(expected.uv)
    assert loaded.materials[0].name_jp == "材質"
    assert loaded.materials[0].diffuse_color == pytest.approx([0.8, 0.7, 0.6, 1.0])
    assert loaded.materials[0].face_count == 3
