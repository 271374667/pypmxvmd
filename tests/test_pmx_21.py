"""PMX 2.1 fixed-byte, semantic, malformed-input, and round-trip tests."""

from __future__ import annotations

import copy
import math
import struct

import pytest

from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxHeader,
    PmxJoint,
    PmxModel,
    PmxMorph,
    PmxMorphItemFlip,
    PmxMorphItemImpulse,
    PmxRigidBody,
    PmxSoftBody,
    PmxSoftBodyAnchor,
    PmxVertex,
)
from pypmxvmd.common.parsers.pmx_parser import _CYTHON_AVAILABLE, PmxParser
from pypmxvmd.common.pmx import (
    PMX_21_REQUIRED_SECTIONS,
    JointType,
    MorphType,
    PmxFormatError,
    PmxValidationError,
    PmxWriter,
    SoftBodyAeroModel,
    SoftBodyFlags,
    SoftBodyShape,
    WeightMode,
)
from tests.fixtures.pmx_builder import (
    build_pmx20_qdef_fixture,
    build_pmx21_fixture,
    pack_index,
)


def _write(tmp_path, name: str, payload: bytes):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


@pytest.mark.parametrize("encoding", [0, 1])
@pytest.mark.parametrize("index_size", [1, 2, 4])
@pytest.mark.parametrize("implementation", ["python", "fast"])
def test_pmx21_all_new_records_parse_to_eof(
    tmp_path, encoding, index_size, implementation
):
    payload, _ = build_pmx21_fixture(encoding=encoding, index_size=index_size)
    result = PmxParser().parse_file_partial(
        _write(
            tmp_path,
            f"pmx21-{encoding}-{index_size}-{implementation}.pmx",
            payload,
        ),
        implementation=implementation,
    )
    model = result.model

    assert result.report.is_complete
    assert result.report.final_offset == len(payload)
    assert tuple(section.name for section in result.report.sections) == (
        PMX_21_REQUIRED_SECTIONS
    )
    assert model.vertices[0].weight_mode == WeightMode.QDEF
    assert model.materials[0].flags.value == 0xE0

    flip = model.morphs[1].items[0]
    assert isinstance(flip, PmxMorphItemFlip)
    assert flip.morph_index == 0
    assert flip.value == pytest.approx(0.75)
    impulse = model.morphs[2].items[0]
    assert isinstance(impulse, PmxMorphItemImpulse)
    assert impulse.rigidbody_index == 0
    assert impulse.is_local is True
    assert impulse.velocity == pytest.approx([1.0, 2.0, 3.0])
    assert impulse.torque == pytest.approx([4.0, 5.0, 6.0])

    assert [joint.joint_type for joint in model.joints] == list(JointType)
    soft_body = model.softbodies[0]
    assert soft_body.shape == SoftBodyShape.TRI_MESH
    assert soft_body.flags == (
        SoftBodyFlags.B_LINK | SoftBodyFlags.CLUSTER | SoftBodyFlags.LINK_CROSS
    )
    assert soft_body.aero_model == SoftBodyAeroModel.F_ONE_SIDED
    assert soft_body.config.anchor_hardness == pytest.approx(1.2)
    assert soft_body.cluster.soft_soft_impulse_split == pytest.approx(1.8)
    assert soft_body.iteration.cluster == 5
    assert soft_body.material.volume_stiffness == pytest.approx(0.8)
    assert soft_body.anchors == [PmxSoftBodyAnchor(0, 0, True)]
    assert soft_body.pin_vertex_indices == [0]
    assert model.validate()


@pytest.mark.skipif(not _CYTHON_AVAILABLE, reason="Cython PMX parser is not built")
def test_pmx21_cython_selector_returns_safe_cursor_model(tmp_path):
    payload, _ = build_pmx21_fixture()
    result = PmxParser().parse_file_partial(
        _write(tmp_path, "pmx21-cython-selector.pmx", payload),
        implementation="cython",
    )

    assert result.report.implementation == "cython"
    assert result.report.is_complete
    assert len(result.model.softbodies) == 1


@pytest.mark.parametrize("encoding", [0, 1])
def test_writer_matches_independent_pmx21_fixed_bytes(tmp_path, encoding):
    payload, _ = build_pmx21_fixture(encoding=encoding, index_size=1)
    model = PmxParser().parse_file(_write(tmp_path, "source.pmx", payload))

    assert PmxWriter().encode(model) == payload


@pytest.mark.parametrize("index_size", [2, 4])
def test_wide_index_pmx21_roundtrips_semantically(
    tmp_path, index_size, assert_model_equal
):
    payload, _ = build_pmx21_fixture(index_size=index_size)
    source = PmxParser().parse_file(_write(tmp_path, "wide.pmx", payload))
    writer = PmxWriter()
    encoded = writer.encode(source)
    loaded = PmxParser().parse_file(_write(tmp_path, "canonical.pmx", encoded))

    expected = copy.deepcopy(source)
    layout = writer.layout_for(expected)
    expected.header.vertex_index_size = layout.vertex
    expected.header.texture_index_size = layout.texture
    expected.header.material_index_size = layout.material
    expected.header.bone_index_size = layout.bone
    expected.header.morph_index_size = layout.morph
    expected.header.rigid_body_index_size = layout.rigid_body
    expected.header.raw_global_flags = layout.as_global_flags(
        int(expected.header.encoding), expected.header.additional_uv_count
    )
    assert_model_equal(loaded, expected)
    assert writer.encode(loaded) == encoded


@pytest.mark.parametrize("shape", list(SoftBodyShape))
@pytest.mark.parametrize("aero_model", list(SoftBodyAeroModel))
def test_all_soft_body_shape_and_aerodynamics_enums_parse(tmp_path, shape, aero_model):
    payload, _ = build_pmx21_fixture(soft_shape=int(shape), aero_model=int(aero_model))
    model = PmxParser().parse_file(_write(tmp_path, "soft-enums.pmx", payload))

    assert model.softbodies[0].shape == shape
    assert model.softbodies[0].aero_model == aero_model


def test_empty_anchor_and_pin_lists_and_false_near_mode_parse(tmp_path):
    empty_payload, _ = build_pmx21_fixture(
        soft_flags=0,
        impulse_local=0,
        include_anchor=False,
        include_pin=False,
    )
    empty = PmxParser().parse_file(_write(tmp_path, "soft-empty.pmx", empty_payload))
    assert empty.morphs[2].items[0].is_local is False
    assert empty.softbodies[0].flags == SoftBodyFlags.NONE
    assert empty.softbodies[0].anchors == []
    assert empty.softbodies[0].pin_vertex_indices == []

    near_payload, _ = build_pmx21_fixture(near_mode=0)
    near = PmxParser().parse_file(_write(tmp_path, "soft-near-off.pmx", near_payload))
    assert near.softbodies[0].anchors[0].near_mode is False


def test_qdef_is_rejected_at_the_pmx20_record_offset(tmp_path):
    payload, offset = build_pmx20_qdef_fixture()
    with pytest.raises(PmxFormatError, match="QDEF requires PMX 2.1") as caught:
        PmxParser().parse_file_partial(_write(tmp_path, "pmx20-qdef.pmx", payload))

    assert caught.value.section == "vertices"
    assert caught.value.offset == offset


@pytest.mark.parametrize(
    ("offset_name", "replacement", "message", "section"),
    [
        ("flip_type", b"\x0b", "morph type 11", "morphs"),
        ("impulse_local", b"\x02", "local flag 2", "morphs"),
        ("joint_type_5", b"\x06", "joint type 6", "joints"),
        ("soft_shape", b"\x02", "soft-body shape 2", "soft_bodies"),
        ("soft_flags", b"\x08", "soft-body flags 0x08", "soft_bodies"),
        (
            "soft_aero_model",
            struct.pack("<i", 5),
            "aerodynamics model 5",
            "soft_bodies",
        ),
        ("soft_anchor_near", b"\x02", "near mode 2", "soft_bodies"),
        ("soft_anchor_count", struct.pack("<i", -1), "anchor count", "soft_bodies"),
        ("soft_pin_count", struct.pack("<i", -1), "pin count", "soft_bodies"),
        (
            "soft_b_link_distance",
            struct.pack("<i", -1),
            "B-link distance",
            "soft_bodies",
        ),
        (
            "soft_cluster_count",
            struct.pack("<i", -1),
            "cluster count",
            "soft_bodies",
        ),
        (
            "soft_iteration_velocity",
            struct.pack("<i", -1),
            "velocity iteration count",
            "soft_bodies",
        ),
    ],
)
def test_invalid_pmx21_values_fail_with_section_and_exact_offset(
    tmp_path, offset_name, replacement, message, section
):
    payload, offsets = build_pmx21_fixture()
    source = bytearray(payload)
    offset = offsets[offset_name]
    source[offset : offset + len(replacement)] = replacement

    with pytest.raises(PmxFormatError, match=message) as caught:
        PmxParser().parse_file_partial(_write(tmp_path, "invalid.pmx", source))

    assert caught.value.section == section
    assert caught.value.offset == offset


def test_truncated_soft_body_reports_soft_body_section(tmp_path):
    payload, offsets = build_pmx21_fixture()
    truncated = payload[: offsets["soft_material_linear"] + 11]

    with pytest.raises(PmxFormatError, match="Truncated PMX data") as caught:
        PmxParser().parse_file_partial(
            _write(tmp_path, "truncated-soft.pmx", truncated)
        )

    assert caught.value.section == "soft_bodies"
    assert caught.value.report is not None
    assert caught.value.report.failed_section == "soft_bodies"


@pytest.mark.parametrize(
    ("offset_name", "field", "signed"),
    [
        ("flip_morph_index", "morphs[1].items[0].morph_index", True),
        ("impulse_rigidbody_index", "morphs[2].items[0].rigidbody_index", True),
        ("soft_material_index", "soft_bodies[0].material_index", True),
        ("soft_anchor_rigidbody", "soft_bodies[0].anchors[0].rigidbody_index", True),
        ("soft_anchor_vertex", "soft_bodies[0].anchors[0].vertex_index", False),
        ("soft_pin_vertex", "soft_bodies[0].pin_vertex_indices[0]", False),
    ],
)
@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_pmx21_cross_references_are_centrally_validated(
    tmp_path, offset_name, field, signed, index_size
):
    payload, offsets = build_pmx21_fixture(index_size=index_size)
    source = bytearray(payload)
    offset = offsets[offset_name]
    source[offset : offset + index_size] = pack_index(3, index_size, signed=signed)
    model = PmxParser().parse_file(_write(tmp_path, "bad-reference.pmx", source))

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == field


def test_soft_body_float_must_be_finite(tmp_path):
    payload, offsets = build_pmx21_fixture()
    source = bytearray(payload)
    offset = offsets["soft_config_vcf"]
    source[offset : offset + 4] = struct.pack("<f", math.nan)
    model = PmxParser().parse_file(_write(tmp_path, "nan-soft.pmx", source))

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "soft_bodies[0].config.velocity_correction"


def test_invalid_soft_body_fails_before_writer_creates_target(tmp_path):
    payload, _ = build_pmx21_fixture()
    model = PmxParser().parse_file(_write(tmp_path, "source.pmx", payload))
    model.softbodies[0].config.velocity_correction = math.nan
    target = tmp_path / "invalid-soft-body.pmx"

    with pytest.raises(PmxValidationError) as caught:
        PmxWriter().write_file(model, target)

    assert caught.value.field == "soft_bodies[0].config.velocity_correction"
    assert not target.exists()


@pytest.mark.parametrize(
    ("configure", "field"),
    [
        (
            lambda model: model.vertices.append(
                PmxVertex(weight_mode=WeightMode.QDEF, weight=[[0, 0.25]] * 4)
            ),
            "vertices[0].weight_mode",
        ),
        (
            lambda model: model.morphs.extend(
                [
                    PmxMorph(morph_type=MorphType.VERTEX),
                    PmxMorph(
                        morph_type=MorphType.FLIP,
                        items=[PmxMorphItemFlip(0, 1.0)],
                    ),
                ]
            ),
            "morphs[1].morph_type",
        ),
        (
            lambda model: model.morphs.append(
                PmxMorph(
                    morph_type=MorphType.IMPULSE,
                    items=[PmxMorphItemImpulse(0, False)],
                )
            ),
            "morphs[0].morph_type",
        ),
        (
            lambda model: model.joints.append(
                PmxJoint(
                    joint_type=JointType.SIX_DOF,
                    rigidbody1_index=-1,
                    rigidbody2_index=-1,
                )
            ),
            "joints[0].joint_type",
        ),
        (lambda model: model.softbodies.append(PmxSoftBody()), "soft_bodies"),
    ],
)
def test_pmx21_only_records_are_rejected_by_pmx20_validator(configure, field):
    model = PmxModel()
    model.header = PmxHeader(version=2.0)
    model.bones = [PmxBone()]
    model.rigidbodies = [PmxRigidBody(bone_index=0)]
    configure(model)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == field
