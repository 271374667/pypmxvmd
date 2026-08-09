"""Correctness tests for the PMX writer."""

import struct

import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import PmxBone
from pypmxvmd.common.parsers.pmx_parser import PmxParser


def test_pmx_writer_roundtrip(tmp_path, sample_pmx_model):
    parser = PmxParser()
    path = tmp_path / "model.pmx"

    parser.write_file_partial(sample_pmx_model, path)

    data = path.read_bytes()
    assert data[:4] == b"PMX "
    assert struct.unpack("<f", data[4:8])[0] == pytest.approx(2.0)

    loaded = parser.parse_file_partial(path, implementation="fast").model
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
    assert loaded.bones == []
    assert parser.last_parse_report is not None
    assert parser.last_parse_report.missing_sections == ()
    assert parser.last_parse_report.is_complete


def test_partial_writer_rejects_nonempty_bones_before_creating_target(
    tmp_path, sample_pmx_model
):
    sample_pmx_model.bones = [PmxBone()]
    path = tmp_path / "would-drop-bones.pmx"

    with pytest.raises(pypmxvmd.IncompletePmxWriterError):
        PmxParser().write_file_partial(sample_pmx_model, path)

    assert not path.exists()


def test_public_pmx_writer_fails_before_creating_output(tmp_path, sample_pmx_model):
    path = tmp_path / "must-not-exist.pmx"

    with pytest.raises(
        pypmxvmd.IncompletePmxWriterError,
        match="Complete PMX writing is not implemented",
    ):
        pypmxvmd.save_pmx(sample_pmx_model, path)

    assert not path.exists()
