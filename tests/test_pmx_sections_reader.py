"""PMX 2.0 Morph, Display Frame and physics reader coverage."""

import struct

import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import (
    MorphMaterialOperation,
    MorphType,
    PmxMorphItemBone,
    PmxMorphItemGroup,
    PmxMorphItemMaterial,
    PmxMorphItemUv,
    PmxMorphItemVertex,
    RigidBodyPhysMode,
    RigidBodyShape,
)
from pypmxvmd.common.pmx import IncompletePmxError, PmxFormatError
from pypmxvmd.common.pmx.report import PMX_20_REQUIRED_SECTIONS
from pypmxvmd.common.parsers.pmx_parser import PmxParser, _CYTHON_AVAILABLE


def _pmx_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<i", len(encoded)) + encoded


def _index(value: int, size: int, *, signed: bool = True) -> bytes:
    formats = {
        (1, True): "<b",
        (2, True): "<h",
        (4, True): "<i",
        (1, False): "<B",
        (2, False): "<H",
        (4, False): "<I",
    }
    return struct.pack(formats[(size, signed)], value)


def _morph_header(name: str, panel: int, morph_type: int) -> bytes:
    return (
        _pmx_string(name)
        + _pmx_string(name)
        + struct.pack("<BBi", panel, morph_type, 1)
    )


def _pmx20_all_sections(index_size: int = 2) -> tuple[bytes, dict[str, int]]:
    """Build every PMX 2.0 Morph type, a frame, three bodies and a joint."""
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    data.extend(bytes((8, 1, 0, *([index_size] * 6))))
    for value in ("全区块", "All sections", "", ""):
        data.extend(_pmx_string(value))

    # One BDEF1 vertex.
    data.extend(struct.pack("<i", 1))
    data.extend(struct.pack("<3f3f2f", 0.0, 1.0, 2.0, 0.0, 1.0, 0.0, 0.25, 0.75))
    data.extend(struct.pack("<B", 0))
    data.extend(_index(0, index_size))
    data.extend(struct.pack("<f", 1.0))

    data.extend(struct.pack("<i", 0))  # Face vertex-index count.
    data.extend(struct.pack("<i", 0))  # Texture count.

    # One material with no texture references and zero assigned faces.
    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("材質"))
    data.extend(_pmx_string("Material"))
    data.extend(struct.pack("<4f", 0.8, 0.7, 0.6, 1.0))
    data.extend(struct.pack("<3ff3f", 0.1, 0.2, 0.3, 4.0, 0.2, 0.2, 0.2))
    data.extend(struct.pack("<B4ff", 0, 0.0, 0.0, 0.0, 1.0, 1.0))
    data.extend(_index(-1, index_size))
    data.extend(_index(-1, index_size))
    data.extend(struct.pack("<BBB", 0, 1, 0))  # Sphere mode, shared Toon, toon01.
    data.extend(_pmx_string(""))
    data.extend(struct.pack("<i", 0))

    # One offset-tail bone.
    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("センター"))
    data.extend(_pmx_string("Center"))
    data.extend(struct.pack("<3f", 0.0, 1.0, 0.0))
    data.extend(_index(-1, index_size))
    data.extend(struct.pack("<iH3f", 0, 0x001A, 0.0, 1.0, 0.0))

    # Nine PMX 2.0 morphs: Vertex, Bone, UV, UV1..4, Material, Group.
    data.extend(struct.pack("<i", 9))

    data.extend(_morph_header("Vertex", 1, 1))
    data.extend(_index(0, index_size, signed=False))
    data.extend(struct.pack("<3f", 1.0, 2.0, 3.0))

    data.extend(_morph_header("Bone", 2, 2))
    data.extend(_index(0, index_size))
    data.extend(struct.pack("<3f4f", 4.0, 5.0, 6.0, 0.1, 0.2, 0.3, 0.9))

    for morph_type in range(3, 8):
        data.extend(_morph_header(f"UV{morph_type - 3}", 3, morph_type))
        data.extend(_index(0, index_size, signed=False))
        data.extend(
            struct.pack(
                "<4f",
                float(morph_type),
                float(morph_type + 1),
                float(morph_type + 2),
                float(morph_type + 3),
            )
        )

    data.extend(_morph_header("Material", 4, 8))
    data.extend(_index(0, index_size))
    offsets = {"material_operation": len(data)}
    data.extend(struct.pack("<B", 1))
    factors = [float(value) for value in range(1, 29)]
    data.extend(struct.pack("<4f", *factors[0:4]))
    data.extend(struct.pack("<3f", *factors[4:7]))
    data.extend(struct.pack("<f", factors[7]))
    data.extend(struct.pack("<3f", *factors[8:11]))
    data.extend(struct.pack("<4f", *factors[11:15]))
    data.extend(struct.pack("<f", factors[15]))
    data.extend(struct.pack("<4f", *factors[16:20]))
    data.extend(struct.pack("<4f", *factors[20:24]))
    data.extend(struct.pack("<4f", *factors[24:28]))

    offsets["group_morph_type"] = len(data) + len(_pmx_string("Group")) * 2 + 1
    data.extend(_morph_header("Group", 0, 0))
    data.extend(_index(0, index_size))
    data.extend(struct.pack("<f", 0.75))

    # One special display frame with one Bone and one Morph item.
    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("Root"))
    data.extend(_pmx_string("Root"))
    data.extend(struct.pack("<Bi", 1, 2))
    data.extend(struct.pack("<B", 0))
    data.extend(_index(0, index_size))
    offsets["frame_target"] = len(data)
    data.extend(struct.pack("<B", 1))
    data.extend(_index(0, index_size))

    # Sphere/static, box/dynamic and capsule/dynamic+bone bodies.
    data.extend(struct.pack("<i", 3))
    for body_index, (shape, mode, bone_index, group, mask) in enumerate(
        (
            (0, 0, 0, 0, 0xFFFE),
            (1, 1, -1, 7, 0x00FF),
            (2, 2, 0, 15, 0x8001),
        )
    ):
        data.extend(_pmx_string(f"剛体{body_index}"))
        data.extend(_pmx_string(f"Body {body_index}"))
        data.extend(_index(bone_index, index_size))
        if body_index == 0:
            offsets["rigid_group"] = len(data)
        data.extend(struct.pack("<BH", group, mask))
        if body_index == 0:
            offsets["rigid_shape"] = len(data)
        data.extend(struct.pack("<B", shape))
        data.extend(struct.pack("<3f", 1.0, 2.0, 3.0))
        data.extend(struct.pack("<3f", 4.0, 5.0, 6.0))
        data.extend(struct.pack("<3f", 0.1, 0.2, 0.3))
        data.extend(struct.pack("<5f", 0.5, 0.6, 0.7, 0.8, 0.9))
        if body_index == 0:
            offsets["rigid_mode"] = len(data)
        data.extend(struct.pack("<B", mode))

    # One Spring 6DOF joint with eight distinct vec3 fields.
    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("Joint"))
    data.extend(_pmx_string("Joint"))
    offsets["joint_type"] = len(data)
    data.extend(struct.pack("<B", 0))
    data.extend(_index(0, index_size))
    data.extend(_index(2, index_size))
    offsets["joint_vectors"] = len(data)
    for start in range(1, 25, 3):
        data.extend(
            struct.pack("<3f", float(start), float(start + 1), float(start + 2))
        )

    return bytes(data), offsets


@pytest.mark.parametrize("index_size", [1, 2, 4])
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
def test_all_pmx20_sections_parse_to_eof(tmp_path, index_size, implementation):
    payload, _ = _pmx20_all_sections(index_size)
    path = tmp_path / f"all-sections-{implementation}-{index_size}.pmx"
    path.write_bytes(payload)

    result = PmxParser().parse_file_partial(path, implementation=implementation)
    model = result.model

    assert result.report.is_complete
    assert result.report.final_offset == len(payload)
    assert result.report.missing_sections == ()
    assert tuple(section.name for section in result.report.sections) == (
        PMX_20_REQUIRED_SECTIONS
    )

    assert [morph.morph_type for morph in model.morphs] == [
        MorphType.VERTEX,
        MorphType.BONE,
        MorphType.UV,
        MorphType.EXTENDED_UV1,
        MorphType.EXTENDED_UV2,
        MorphType.EXTENDED_UV3,
        MorphType.EXTENDED_UV4,
        MorphType.MATERIAL,
        MorphType.GROUP,
    ]
    assert isinstance(model.morphs[0].items[0], PmxMorphItemVertex)
    bone_item = model.morphs[1].items[0]
    assert isinstance(bone_item, PmxMorphItemBone)
    assert bone_item.translation == pytest.approx([4.0, 5.0, 6.0])
    assert bone_item.rotation_quaternion == pytest.approx([0.1, 0.2, 0.3, 0.9])
    assert all(
        isinstance(model.morphs[index].items[0], PmxMorphItemUv)
        for index in range(2, 7)
    )
    material_item = model.morphs[7].items[0]
    assert isinstance(material_item, PmxMorphItemMaterial)
    assert material_item.operation == MorphMaterialOperation.ADD
    assert material_item.diffuse_color == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert material_item.toon_tint == pytest.approx([25.0, 26.0, 27.0, 28.0])
    group_item = model.morphs[8].items[0]
    assert isinstance(group_item, PmxMorphItemGroup)
    assert group_item.morph_index == 0
    assert group_item.value == pytest.approx(0.75)

    frame = model.frames[0]
    assert frame.is_special
    assert frame.items[0].bone_index == 0
    assert frame.items[0].morph_index is None
    assert frame.items[1].morph_index == 0

    assert [body.shape for body in model.rigidbodies] == list(RigidBodyShape)
    assert [body.physics_mode for body in model.rigidbodies] == list(RigidBodyPhysMode)
    assert model.rigidbodies[0].collision_group == 0
    assert model.rigidbodies[0].group == 1
    assert model.rigidbodies[0].collision_mask == 0xFFFE
    assert model.rigidbodies[0].nocollide_groups == [1]
    assert model.rigidbodies[0].rotation == pytest.approx([0.1, 0.2, 0.3])
    assert model.rigidbodies[1].bone_index == -1

    joint = model.joints[0]
    assert joint.rigid_body_a_index == 0
    assert joint.rigid_body_b_index == 2
    assert joint.position == pytest.approx([1.0, 2.0, 3.0])
    assert joint.rotation == pytest.approx([4.0, 5.0, 6.0])
    assert joint.rotation_spring == pytest.approx([22.0, 23.0, 24.0])
    assert model.validate()


@pytest.mark.parametrize(
    ("offset_name", "replacement", "message", "section"),
    [
        ("material_operation", 2, "material morph operation 2", "morphs"),
        ("frame_target", 2, "display-frame item target 2", "display_frames"),
        ("rigid_group", 16, "collision group 16", "rigid_bodies"),
        ("rigid_shape", 3, "rigid-body shape 3", "rigid_bodies"),
        ("rigid_mode", 3, "physics mode 3", "rigid_bodies"),
        ("joint_type", 1, "Unsupported PMX joint type 1", "joints"),
    ],
)
def test_late_section_enums_and_flags_fail_at_exact_offset(
    tmp_path, offset_name, replacement, message, section
):
    payload, offsets = _pmx20_all_sections()
    source = bytearray(payload)
    source[offsets[offset_name]] = replacement
    path = tmp_path / f"invalid-{offset_name}.pmx"
    path.write_bytes(source)

    with pytest.raises(PmxFormatError, match=message) as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == section
    assert caught.value.offset == offsets[offset_name]
    assert caught.value.report is not None
    assert caught.value.report.failed_section == section


def test_truncated_joint_vector_reports_joint_section(tmp_path):
    payload, offsets = _pmx20_all_sections()
    path = tmp_path / "truncated-joint.pmx"
    path.write_bytes(payload[: offsets["joint_vectors"] + 91])

    with pytest.raises(PmxFormatError, match="Truncated PMX data") as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "joints"
    assert caught.value.report is not None
    assert caught.value.report.failed_section == "joints"


def test_pmx21_stops_before_soft_body_and_complete_api_fails_closed(tmp_path):
    payload, _ = _pmx20_all_sections()
    source = bytearray(payload)
    source[4:8] = struct.pack("<f", 2.1)
    source.extend(struct.pack("<i", 0))
    path = tmp_path / "pmx21-soft-body-boundary.pmx"
    path.write_bytes(source)

    result = PmxParser().parse_file_partial(path)

    assert result.report.loaded_sections == frozenset(PMX_20_REQUIRED_SECTIONS)
    assert result.report.missing_sections == ("soft_bodies",)
    assert result.report.trailing_bytes == 4
    assert not result.report.is_complete
    with pytest.raises(IncompletePmxError):
        PmxParser().parse_file(path)


def test_public_load_pmx_returns_complete_valid_pmx20(tmp_path):
    payload, _ = _pmx20_all_sections()
    path = tmp_path / "public-complete-pmx20.pmx"
    path.write_bytes(payload)

    model = pypmxvmd.load_pmx(path)

    assert model.is_complete
    assert len(model.rigidbodies) == 3
    assert len(model.joints) == 1
    assert model.validate()


def test_pmx21_flip_morph_fails_closed_until_long_term_stage(tmp_path):
    payload, offsets = _pmx20_all_sections()
    source = bytearray(payload)
    source[4:8] = struct.pack("<f", 2.1)
    source[offsets["group_morph_type"]] = int(MorphType.FLIP)
    path = tmp_path / "unsupported-flip-morph.pmx"
    path.write_bytes(source)

    with pytest.raises(
        PmxFormatError, match="Unsupported PMX 2.1 morph type FLIP"
    ) as caught:
        PmxParser().parse_file_partial(path)

    assert caught.value.section == "morphs"
    assert caught.value.offset == offsets["group_morph_type"]
