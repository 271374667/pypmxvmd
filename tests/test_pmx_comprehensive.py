"""PMX writer checks for index-width transitions."""

import pytest

from pypmxvmd.common.models.pmx import PmxHeader, PmxMaterial, PmxModel, PmxVertex
from pypmxvmd.common.parsers.pmx_parser import PmxParser


def create_large_pmx_model(grid_size=20):
    """Create enough vertices to require indexes greater than 255."""
    model = PmxModel()
    model.header = PmxHeader(
        version=2.0,
        name_jp="大型テストモデル",
        name_en="LargeTestModel",
    )
    model.vertices = [
        PmxVertex(
            position=[float(x), float(y), 0.0],
            normal=[0.0, 0.0, 1.0],
            uv=[x / grid_size, y / grid_size],
        )
        for x in range(grid_size)
        for y in range(grid_size)
    ]
    for x in range(grid_size - 1):
        for y in range(grid_size - 1):
            v0 = x * grid_size + y
            v1 = (x + 1) * grid_size + y
            v2 = x * grid_size + y + 1
            v3 = (x + 1) * grid_size + y + 1
            model.faces.extend(([v0, v1, v2], [v1, v3, v2]))
    model.materials = [
        PmxMaterial(
            name_jp="網格材質",
            name_en="Grid Material",
            diffuse_color=[0.7, 0.7, 0.7, 1.0],
            face_count=len(model.faces) * 3,
        )
    ]
    return model


def test_large_vertex_indexes_roundtrip(tmp_path):
    model = create_large_pmx_model()
    path = tmp_path / "large.pmx"

    PmxParser().write_file_partial(model, path)
    loaded = PmxParser().parse_file_partial(
        path, implementation="fast"
    ).model

    assert len(model.vertices) == 400
    assert max(index for face in model.faces for index in face) > 255
    assert len(loaded.vertices) == len(model.vertices)
    assert loaded.faces == model.faces
    assert loaded.materials[0].face_count == len(model.faces) * 3
    assert loaded.vertices[-1].position == pytest.approx(model.vertices[-1].position)
