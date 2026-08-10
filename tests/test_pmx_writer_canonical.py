"""Canonical PMX 2.0/2.1 writer layout and safety tests."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from pypmxvmd.common.models.pmx import PmxModel
from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.pmx import PmxIndexLayout, PmxLimits, PmxValidationError, PmxWriter
from tests.test_pmx_bone_reader import _pmx20_with_bones
from tests.test_pmx_sections_reader import _pmx20_all_sections
from tests.test_pmx_vertex_reader import _pmx20_sdef_vertex


def _write_source(tmp_path: Path, name: str, source: bytes) -> Path:
    path = tmp_path / f"{name}-source.pmx"
    path.write_bytes(source)
    return path


@pytest.mark.parametrize(
    ("name", "source_factory"),
    [
        ("all-sections", lambda: _pmx20_all_sections(1)[0]),
        ("all-bone-flags", lambda: _pmx20_with_bones(1)[0]),
        ("sdef-uv4", lambda: _pmx20_sdef_vertex(4, 1)),
    ],
)
def test_writer_matches_independently_built_binary_fixtures(
    tmp_path, name, source_factory
):
    source = source_factory()
    source_path = _write_source(tmp_path, name, source)
    model = PmxParser().parse_file(source_path)

    encoded = PmxWriter().encode(model)

    assert encoded == source


@pytest.mark.parametrize(
    ("domain", "count", "expected"),
    [
        ("vertex", 256, 1),
        ("vertex", 257, 2),
        ("vertex", 65_536, 2),
        ("vertex", 65_537, 4),
        ("bone", 128, 1),
        ("bone", 129, 2),
        ("bone", 32_768, 2),
        ("bone", 32_769, 4),
    ],
)
def test_canonical_layout_uses_signed_and_unsigned_capacities(domain, count, expected):
    collections = {
        "vertices": (),
        "textures": (),
        "materials": (),
        "bones": (),
        "morphs": (),
        "rigidbodies": (),
    }
    attribute = "vertices" if domain == "vertex" else "bones"
    collections[attribute] = range(count)
    model = SimpleNamespace(**collections)

    layout = PmxIndexLayout.from_model(model)

    assert getattr(layout, domain) == expected


def test_canonical_writer_normalizes_layout_without_mutating_input(tmp_path):
    source, _ = _pmx20_all_sections(4)
    source_path = _write_source(tmp_path, "wide-layout", source)
    model = PmxParser().parse_file(source_path)
    original_sizes = model.header.index_sizes
    original_raw_flags = model.header.raw_global_flags

    encoded = PmxWriter().encode(model)
    output_path = tmp_path / "canonical.pmx"
    output_path.write_bytes(encoded)
    loaded = PmxParser().parse_file(output_path)

    assert original_sizes == (4, 4, 4, 4, 4, 4)
    assert model.header.index_sizes == original_sizes
    assert model.header.raw_global_flags == original_raw_flags
    assert loaded.header.index_sizes == (1, 1, 1, 1, 1, 1)
    assert PmxWriter().encode(loaded) == encoded


def test_canonical_writer_preserves_texture_order_and_duplicates(sample_pmx_model):
    sample_pmx_model.textures = ["dup.png", "middle.png", "dup.png"]
    material = sample_pmx_model.materials[0]
    material.texture_index = 2
    material.texture_path = "dup.png"
    material.sphere_texture_index = 1
    material.sphere_path = "middle.png"
    material.toon_texture_index = 0
    material.toon_path = "dup.png"

    encoded = PmxWriter().encode(sample_pmx_model)

    assert encoded.count("dup.png".encode("utf-16le")) == 2


def test_writer_enforces_encoded_source_size_limit_before_file_creation(
    tmp_path,
):
    model = PmxModel()
    model.header.version = 2.0
    path = tmp_path / "too-large.pmx"

    with pytest.raises(PmxValidationError) as caught:
        PmxWriter(limits=PmxLimits(max_source_bytes=10)).write_file(model, path)

    assert caught.value.field == "encoded_size"
    assert not path.exists()
