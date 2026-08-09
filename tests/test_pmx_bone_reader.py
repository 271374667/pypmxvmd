"""PMX 2.x Bone-section reader coverage."""

import struct

import pytest

from pypmxvmd.common.pmx import PmxFormatError
from pypmxvmd.common.parsers.pmx_parser import PmxParser, _CYTHON_AVAILABLE


def _pmx_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<i", len(encoded)) + encoded


def _bone_index(value: int, size: int) -> bytes:
    return struct.pack({1: "<b", 2: "<h", 4: "<i"}[size], value)


def _pmx20_with_bones(bone_index_size: int) -> tuple[bytes, dict[str, int]]:
    """Build two bones covering every conditional PMX 2.x Bone field."""
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    data.extend(bytes((8, 1, 0, 1, 1, 1, bone_index_size, 1, 1)))
    for value in ("骨骼测试", "Bone test", "", ""):
        data.extend(_pmx_string(value))

    # Vertices, face indices, textures and materials.
    data.extend(struct.pack("<4i", 0, 0, 0, 0))

    offsets = {"bone_count": len(data)}
    data.extend(struct.pack("<i", 2))

    # An offset-tail root bone verifies the PMXEditor “relative” tail mode.
    data.extend(_pmx_string("センター"))
    data.extend(_pmx_string("Center"))
    data.extend(struct.pack("<3f", 0.0, 9.0, 0.0))
    data.extend(_bone_index(-1, bone_index_size))
    data.extend(struct.pack("<iH", 2, 0x001A))
    data.extend(struct.pack("<3f", 0.0, 1.0, 0.0))

    # All defined flags, including local append (0x0080), plus two IK links.
    all_flags = 0x3FBF
    data.extend(_pmx_string("足ＩＫ"))
    data.extend(_pmx_string("Leg IK"))
    data.extend(struct.pack("<3f", 1.0, 2.0, 3.0))
    data.extend(_bone_index(0, bone_index_size))
    data.extend(struct.pack("<iH", 4, all_flags))
    data.extend(_bone_index(0, bone_index_size))  # Bone-link tail mode.
    data.extend(_bone_index(0, bone_index_size))
    data.extend(struct.pack("<f", 0.5))
    data.extend(struct.pack("<3f", 1.0, 0.0, 0.0))
    data.extend(struct.pack("<3f3f", 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    data.extend(struct.pack("<i", 1234))
    data.extend(_bone_index(0, bone_index_size))
    data.extend(struct.pack("<if", 40, 0.25))
    offsets["ik_link_count"] = len(data)
    data.extend(struct.pack("<i", 2))

    data.extend(_bone_index(0, bone_index_size))
    offsets["first_link_flag"] = len(data)
    data.extend(struct.pack("<B", 0))

    data.extend(_bone_index(0, bone_index_size))
    offsets["second_link_flag"] = len(data)
    data.extend(struct.pack("<B", 1))
    offsets["second_link_limits"] = len(data)
    data.extend(struct.pack("<3f", -0.5, -0.25, -0.125))
    data.extend(struct.pack("<3f", 0.5, 0.25, 0.125))

    # Morphs, display frames, rigid bodies and joints remain for later stages.
    data.extend(struct.pack("<4i", 0, 0, 0, 0))
    return bytes(data), offsets


@pytest.mark.parametrize("bone_index_size", [1, 2, 4])
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
def test_bone_reader_preserves_every_conditional_field(
    tmp_path, bone_index_size, implementation
):
    payload, _ = _pmx20_with_bones(bone_index_size)
    path = tmp_path / f"bones-index-{bone_index_size}.pmx"
    path.write_bytes(payload)

    result = PmxParser().parse_file_partial(path, implementation=implementation)

    assert result.report.missing_sections == ()
    assert result.report.trailing_bytes == 0
    bone_section = next(
        section for section in result.report.sections if section.name == "bones"
    )
    assert bone_section.record_count == 2
    assert result.report.is_complete

    root, ik_bone = result.model.bones
    assert root.name_jp == "センター"
    assert root.deform_layer == 2
    assert root.parent_index == -1
    assert root.tail_offset == pytest.approx([0.0, 1.0, 0.0])

    assert ik_bone.name_en == "Leg IK"
    assert ik_bone.position == pytest.approx([1.0, 2.0, 3.0])
    assert ik_bone.parent_index == 0
    assert ik_bone.deform_layer == 4
    assert ik_bone.tail_bone_index == 0
    assert ik_bone.bone_flags.value == 0x3FBF
    assert ik_bone.bone_flags.inherit_local
    assert ik_bone.bone_flags.local_append
    assert ik_bone.inherit_parent_index == 0
    assert ik_bone.inherit_ratio == pytest.approx(0.5)
    assert ik_bone.fixed_axis == pytest.approx([1.0, 0.0, 0.0])
    assert ik_bone.local_axis_x == pytest.approx([1.0, 0.0, 0.0])
    assert ik_bone.local_axis_z == pytest.approx([0.0, 0.0, 1.0])
    assert ik_bone.external_parent_index == 1234
    assert ik_bone.ik_target_index == 0
    assert ik_bone.ik_loop_count == 40
    assert ik_bone.ik_angle_limit == pytest.approx(0.25)

    no_limits, limited = ik_bone.ik_links
    assert not no_limits.has_limits
    assert no_limits.limit_min is None
    assert no_limits.limit_max is None
    assert limited.has_limits
    assert limited.limit_min == pytest.approx([-0.5, -0.25, -0.125])
    assert limited.limit_max == pytest.approx([0.5, 0.25, 0.125])
    assert result.model.validate()


def test_bone_reader_rejects_negative_bone_count_in_bone_section(tmp_path):
    payload, offsets = _pmx20_with_bones(1)
    source = bytearray(payload)
    source[offsets["bone_count"] : offsets["bone_count"] + 4] = struct.pack("<i", -1)
    path = tmp_path / "negative-bone-count.pmx"
    path.write_bytes(source)

    with pytest.raises(PmxFormatError, match="Negative PMX bone count") as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "bones"
    assert caught.value.offset == offsets["bone_count"]
    assert caught.value.report is not None
    assert caught.value.report.failed_section == "bones"


def test_bone_reader_rejects_negative_ik_link_count(tmp_path):
    payload, offsets = _pmx20_with_bones(2)
    source = bytearray(payload)
    source[offsets["ik_link_count"] : offsets["ik_link_count"] + 4] = struct.pack(
        "<i", -1
    )
    path = tmp_path / "negative-ik-link-count.pmx"
    path.write_bytes(source)

    with pytest.raises(PmxFormatError, match="Negative PMX IK link count") as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "bones"
    assert caught.value.offset == offsets["ik_link_count"]


def test_bone_reader_rejects_non_boolean_ik_limit_flag(tmp_path):
    payload, offsets = _pmx20_with_bones(4)
    source = bytearray(payload)
    source[offsets["second_link_flag"]] = 2
    path = tmp_path / "invalid-ik-limit-flag.pmx"
    path.write_bytes(source)

    with pytest.raises(
        PmxFormatError, match="Invalid PMX IK link angle-limit flag 2"
    ) as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "bones"
    assert caught.value.offset == offsets["second_link_flag"]


def test_bone_reader_reports_truncated_conditional_payload(tmp_path):
    payload, offsets = _pmx20_with_bones(1)
    path = tmp_path / "truncated-ik-limits.pmx"
    path.write_bytes(payload[: offsets["second_link_limits"] + 7])

    with pytest.raises(PmxFormatError, match="Truncated PMX data") as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "bones"
    assert caught.value.report is not None
    assert caught.value.report.failed_section == "bones"
