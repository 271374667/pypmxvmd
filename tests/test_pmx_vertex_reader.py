"""Lossless PMX additional-UV and SDEF vertex reader coverage."""

import struct

import pytest

from pypmxvmd.common.models.pmx import WeightMode
from pypmxvmd.common.parsers.pmx_parser import PmxParser, _CYTHON_AVAILABLE


def _pmx_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<i", len(encoded)) + encoded


def _bone_index(value: int, size: int) -> bytes:
    return struct.pack({1: "<b", 2: "<h", 4: "<i"}[size], value)


def _pmx20_sdef_vertex(additional_uv_count: int, bone_index_size: int) -> bytes:
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    data.extend(bytes((8, 1, additional_uv_count, 1, 1, 1, bone_index_size, 1, 1)))
    for value in ("SDEF", "SDEF", "", ""):
        data.extend(_pmx_string(value))

    data.extend(struct.pack("<i", 1))
    data.extend(struct.pack("<3f3f2f", 1.0, 2.0, 3.0, 0.0, 1.0, 0.0, 0.25, 0.75))
    for uv_index in range(additional_uv_count):
        base = float(uv_index * 4 + 1)
        data.extend(struct.pack("<4f", base, base + 1, base + 2, base + 3))
    data.extend(struct.pack("<B", int(WeightMode.SDEF)))
    data.extend(_bone_index(0, bone_index_size))
    data.extend(_bone_index(0, bone_index_size))
    data.extend(struct.pack("<f", 0.25))
    data.extend(struct.pack("<3f", 1.0, 2.0, 3.0))
    data.extend(struct.pack("<3f", 4.0, 5.0, 6.0))
    data.extend(struct.pack("<3f", 7.0, 8.0, 9.0))
    data.extend(struct.pack("<f", 1.5))

    # Faces, textures and materials.
    data.extend(struct.pack("<3i", 0, 0, 0))

    # One bone referenced by the SDEF weights.
    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("センター"))
    data.extend(_pmx_string("Center"))
    data.extend(struct.pack("<3f", 0.0, 0.0, 0.0))
    data.extend(_bone_index(-1, bone_index_size))
    data.extend(struct.pack("<iH3f", 0, 0x001A, 0.0, 1.0, 0.0))

    # Morphs, display frames, rigid bodies and joints.
    data.extend(struct.pack("<4i", 0, 0, 0, 0))
    return bytes(data)


@pytest.mark.parametrize("additional_uv_count", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("bone_index_size", [1, 2, 4])
def test_sdef_vertex_preserves_additional_uv_and_raw_vectors(
    tmp_path, additional_uv_count, bone_index_size
):
    path = tmp_path / f"sdef-uv{additional_uv_count}-bone{bone_index_size}.pmx"
    path.write_bytes(_pmx20_sdef_vertex(additional_uv_count, bone_index_size))

    model = PmxParser().parse_file(path)
    vertex = model.vertices[0]

    assert vertex.weight_mode == WeightMode.SDEF
    assert vertex.weight[0] == pytest.approx([0, 0.25])
    assert vertex.weight[1] == pytest.approx([0, 0.75])
    assert len(vertex.additional_uvs) == additional_uv_count
    for uv_index, additional_uv in enumerate(vertex.additional_uvs):
        base = float(uv_index * 4 + 1)
        assert additional_uv == pytest.approx([base, base + 1, base + 2, base + 3])
    assert vertex.sdef_c == pytest.approx([1.0, 2.0, 3.0])
    assert vertex.sdef_r0 == pytest.approx([4.0, 5.0, 6.0])
    assert vertex.sdef_r1 == pytest.approx([7.0, 8.0, 9.0])
    assert vertex.edge_scale == pytest.approx(1.5)
    assert model.validate()


@pytest.mark.parametrize(
    "implementation",
    [
        "python",
        "fast",
        pytest.param(
            "cython",
            marks=pytest.mark.skipif(
                not _CYTHON_AVAILABLE,
                reason="Cython PMX parser is not available",
            ),
        ),
    ],
)
def test_public_implementations_share_lossless_vertex_model(tmp_path, implementation):
    path = tmp_path / f"sdef-{implementation}.pmx"
    path.write_bytes(_pmx20_sdef_vertex(4, 2))

    result = PmxParser().parse_file_partial(path, implementation=implementation)

    assert result.report.is_complete
    assert len(result.model.vertices[0].additional_uvs) == 4
    assert result.model.vertices[0].sdef_c == pytest.approx([1.0, 2.0, 3.0])
