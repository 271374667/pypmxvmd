"""PMX completeness reports and fail-closed public read behavior."""

import struct

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import (
    IncompletePmxError,
    PmxFormatError,
    PmxLimits,
)
from pypmxvmd.common.pmx.report import PMX_20_REQUIRED_SECTIONS
from pypmxvmd.common.parsers.pmx_parser import PmxParser, _CYTHON_AVAILABLE


def _pmx_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _minimal_complete_pmx20_bytes() -> bytes:
    """Build a structurally complete PMX 2.0 with every section empty."""
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    data.extend(bytes((8, 1, 0, 1, 1, 1, 1, 1, 1)))
    for value in ("最小", "Minimal", "", ""):
        data.extend(_pmx_string(value))

    # Vertices, face indices, textures, materials, bones, morphs,
    # display frames, rigid bodies and joints.
    for _ in range(9):
        data.extend(struct.pack("<I", 0))
    return bytes(data)


def test_partial_parse_reports_loaded_sections_and_trailing_bytes(tmp_path):
    path = tmp_path / "minimal-complete.pmx"
    path.write_bytes(_minimal_complete_pmx20_bytes())

    result = PmxParser().parse_file_partial(path, implementation="fast")

    assert result.report.implementation == "fast"
    assert result.report.loaded_sections == frozenset(
        {"header", "vertices", "faces", "textures", "materials"}
    )
    assert result.report.missing_sections == PMX_20_REQUIRED_SECTIONS[5:]
    assert result.report.final_offset < result.report.file_size
    assert result.report.trailing_bytes == 5 * 4
    assert not result.report.is_complete
    assert result.model.parse_report is result.report
    assert result.model.loaded_sections == result.report.loaded_sections
    assert not result.model.is_complete
    assert [section.name for section in result.report.sections] == [
        "header",
        "vertices",
        "faces",
        "textures",
        "materials",
    ]


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
def test_each_partial_implementation_reports_the_same_boundary(
    tmp_path, implementation
):
    path = tmp_path / f"minimal-{implementation}.pmx"
    path.write_bytes(_minimal_complete_pmx20_bytes())

    report = PmxParser().parse_file_partial(path, implementation=implementation).report

    assert report.implementation == implementation
    assert report.final_offset == report.file_size - 20
    assert report.missing_sections == (
        "bones",
        "morphs",
        "display_frames",
        "rigid_bodies",
        "joints",
    )


def test_complete_read_fails_closed_with_actionable_report(tmp_path):
    path = tmp_path / "minimal-complete.pmx"
    path.write_bytes(_minimal_complete_pmx20_bytes())

    with pytest.raises(IncompletePmxError) as caught:
        PmxParser().parse_file(path)

    report = caught.value.report
    assert report.final_offset == report.file_size - 20
    assert report.trailing_bytes == 20
    assert report.missing_sections[0] == "bones"
    assert "offset=" in str(caught.value)
    assert "missing_sections=" in str(caught.value)


def test_public_partial_api_returns_model_and_report(tmp_path):
    path = tmp_path / "minimal-complete.pmx"
    path.write_bytes(_minimal_complete_pmx20_bytes())

    result = pypmxvmd.load_pmx_partial(path, implementation="fast")

    assert result.model.header.name_en == "Minimal"
    assert result.report.trailing_bytes == 20
    assert not result.report.is_complete


def test_auto_uses_bounds_checked_cursor_implementation(tmp_path):
    path = tmp_path / "minimal-auto.pmx"
    path.write_bytes(_minimal_complete_pmx20_bytes())

    result = PmxParser().parse_file_partial(path)

    assert result.report.implementation == "fast"


def test_negative_and_excessive_section_counts_fail_before_iteration(tmp_path):
    source = bytearray(_minimal_complete_pmx20_bytes())
    vertex_count_offset = len(source) - 9 * 4

    negative_path = tmp_path / "negative-count.pmx"
    negative = source.copy()
    negative[vertex_count_offset : vertex_count_offset + 4] = struct.pack("<i", -1)
    negative_path.write_bytes(negative)

    with pytest.raises(PmxFormatError, match="Negative PMX vertex count") as caught:
        PmxParser().parse_file_partial(negative_path)
    assert caught.value.section == "vertices"
    assert caught.value.offset == vertex_count_offset
    assert caught.value.report is not None
    assert caught.value.report.failed_section == "vertices"

    excessive_path = tmp_path / "excessive-count.pmx"
    excessive = source.copy()
    excessive[vertex_count_offset : vertex_count_offset + 4] = struct.pack("<i", 3)
    excessive_path.write_bytes(excessive)

    with pytest.raises(PmxFormatError, match="exceeds limit 2"):
        PmxParser(limits=PmxLimits(max_count=2)).parse_file_partial(excessive_path)


def test_invalid_header_index_width_has_exact_offset(tmp_path):
    source = bytearray(_minimal_complete_pmx20_bytes())
    source[11] = 3  # Vertex index byte width.
    path = tmp_path / "invalid-index-width.pmx"
    path.write_bytes(source)

    with pytest.raises(PmxFormatError, match="vertex index size 3") as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "header"
    assert caught.value.offset == 11


@pytest.mark.parametrize(
    ("mutation", "message", "offset"),
    [
        (
            lambda source: source.__setitem__(slice(0, 4), b"BAD!"),
            "Invalid PMX magic",
            0,
        ),
        (
            lambda source: source.__setitem__(slice(4, 8), struct.pack("<f", 3.0)),
            "Unsupported PMX version 3.0",
            4,
        ),
        (
            lambda source: source.__setitem__(8, 7),
            "global flag count 7",
            8,
        ),
        (
            lambda source: source.__setitem__(9, 2),
            "text encoding flag 2",
            9,
        ),
    ],
)
def test_invalid_header_fields_fail_with_exact_offsets(
    tmp_path, mutation, message, offset
):
    source = bytearray(_minimal_complete_pmx20_bytes())
    mutation(source)
    path = tmp_path / f"invalid-header-{offset}.pmx"
    path.write_bytes(source)

    with pytest.raises(PmxFormatError, match=message) as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "header"
    assert caught.value.offset == offset


def test_unknown_partial_implementation_is_rejected(tmp_path):
    path = tmp_path / "minimal-complete.pmx"
    path.write_bytes(_minimal_complete_pmx20_bytes())

    with pytest.raises(ValueError, match="Unknown PMX implementation"):
        PmxParser().parse_file_partial(path, implementation="unknown")
