"""Semantic and real-corpus PMX 2.0 canonical round-trip tests."""

import hashlib

import pytest

from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxHeader,
    PmxMaterial,
    PmxModel,
    PmxVertex,
    WeightMode,
)
from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.pmx import PmxTextEncoding, PmxWriter
from tests.test_corpus_parsers import corpus_cases


def _weight_model() -> PmxModel:
    model = PmxModel()
    model.header = PmxHeader(
        version=2.0,
        name_jp="ウェイト",
        name_en="Weights",
        encoding=PmxTextEncoding.UTF8,
        additional_uv_count=2,
    )
    model.bones = [PmxBone(name_jp=f"骨{index}") for index in range(4)]
    additional_uvs = [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]
    model.vertices = [
        PmxVertex(
            position=[0.0, 0.0, 0.0],
            additional_uvs=additional_uvs,
            weight_mode=WeightMode.BDEF1,
            weight=[[0, 1.0]],
        ),
        PmxVertex(
            position=[1.0, 0.0, 0.0],
            additional_uvs=additional_uvs,
            weight_mode=WeightMode.BDEF2,
            weight=[[0, 0.25], [1, 0.75]],
        ),
        PmxVertex(
            position=[0.0, 1.0, 0.0],
            additional_uvs=additional_uvs,
            weight_mode=WeightMode.BDEF4,
            weight=[(0, 0.4), (1, 0.3), (2, 0.2), (3, 0.1)],
        ),
        PmxVertex(
            position=[0.0, 0.0, 1.0],
            additional_uvs=additional_uvs,
            weight_mode=WeightMode.SDEF,
            weight=[[0, 0.6], [1, 0.4]],
            sdef_c=[1.0, 2.0, 3.0],
            sdef_r0=[4.0, 5.0, 6.0],
            sdef_r1=[7.0, 8.0, 9.0],
        ),
    ]
    model.faces = [[0, 1, 2]]
    model.textures = ["base.png", "sphere.sph", "toon.bmp"]
    model.materials = [
        PmxMaterial(
            name_jp="材質",
            texture_path="base.png",
            texture_index=0,
            sphere_path="sphere.sph",
            sphere_texture_index=1,
            toon_path="toon.bmp",
            toon_texture_index=2,
            face_count=3,
        )
    ]
    return model


def _apply_canonical_layout(model: PmxModel, writer: PmxWriter) -> None:
    layout = writer.layout_for(model)
    header = model.header
    header.vertex_index_size = layout.vertex
    header.texture_index_size = layout.texture
    header.material_index_size = layout.material
    header.bone_index_size = layout.bone
    header.morph_index_size = layout.morph
    header.rigid_body_index_size = layout.rigid_body
    header.raw_global_flags = layout.as_global_flags(
        int(header.encoding), header.additional_uv_count
    )


def _sha256(path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_all_vertex_weight_modes_roundtrip_semantically(tmp_path, assert_model_equal):
    model = _weight_model()
    writer = PmxWriter()
    path = tmp_path / "weights.pmx"

    writer.write_file(model, path)
    loaded = PmxParser().parse_file(path)

    _apply_canonical_layout(model, writer)
    assert_model_equal(loaded, model)
    assert loaded.is_complete


def test_write_parse_write_is_canonically_stable(tmp_path):
    model = _weight_model()
    writer = PmxWriter()
    first_path = tmp_path / "first.pmx"
    second_path = tmp_path / "second.pmx"

    writer.write_file(model, first_path)
    loaded = PmxParser().parse_file(first_path)
    writer.write_file(loaded, second_path)

    assert second_path.read_bytes() == first_path.read_bytes()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_pmx_corpus_roundtrips_without_touching_sources(
    pmx_path, tmp_path, assert_model_equal
):
    before_hash = _sha256(pmx_path)
    model = PmxParser().parse_file(pmx_path)
    writer = PmxWriter()
    output_path = tmp_path / pmx_path.name

    writer.write_file(model, output_path)
    loaded = PmxParser().parse_file(output_path)

    _apply_canonical_layout(model, writer)
    assert_model_equal(loaded, model)
    assert loaded.is_complete
    assert _sha256(pmx_path) == before_hash
