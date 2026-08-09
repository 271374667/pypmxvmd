"""Complete PMX 2.0 semantic validator behavior."""

import math
import subprocess
import sys

import pytest

from pypmxvmd.common.models.pmx import (
    MorphType,
    PmxBone,
    PmxBoneIkLink,
    PmxFrame,
    PmxFrameItem,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemGroup,
    PmxMorphItemMaterial,
    PmxMorphItemVertex,
    PmxRigidBody,
    PmxVertex,
    ToonSharing,
    WeightMode,
)
from pypmxvmd.common.pmx import (
    PmxLimits,
    PmxValidationError,
    PmxValidator,
    validate_pmx_model,
)
from pypmxvmd.common.pmx.report import (
    PMX_20_REQUIRED_SECTIONS,
    PmxParseReport,
    PmxSectionReport,
)


def _valid_model() -> PmxModel:
    model = PmxModel()
    model.header.version = 2.0
    model.header.additional_uv_count = 0
    model.textures = ["tex/base.png", "toon/custom.bmp"]
    model.bones = [
        PmxBone(name_jp="root", parent_index=-1),
        PmxBone(name_jp="child", parent_index=0),
    ]
    model.vertices = [
        PmxVertex(weight_mode=WeightMode.BDEF1, weight=[[0, 1.0]]),
        PmxVertex(
            weight_mode=WeightMode.BDEF2,
            weight=[[0, 0.25], [1, 0.75]],
        ),
        PmxVertex(
            weight_mode=WeightMode.BDEF4,
            weight=[[0, 0.4], [1, 0.3], [0, 0.2], [1, 0.1]],
        ),
        PmxVertex(
            weight_mode=WeightMode.SDEF,
            weight=[[0, 0.5], [1, 0.5]],
            sdef_c=[0.0, 0.0, 0.0],
            sdef_r0=[0.0, 0.0, 0.0],
            sdef_r1=[0.0, 0.0, 0.0],
        ),
    ]
    model.faces = [[0, 1, 2]]
    model.materials = [
        PmxMaterial(
            face_count=3,
            texture_index=0,
            sphere_texture_index=-1,
            toon_sharing=ToonSharing.SEPARATE,
            toon_texture_index=1,
        )
    ]
    model.morphs = [
        PmxMorph(
            name_jp="vertex",
            morph_type=MorphType.VERTEX,
            items=[PmxMorphItemVertex(vertex_index=0)],
        ),
        PmxMorph(
            name_jp="bone",
            morph_type=MorphType.BONE,
            items=[PmxMorphItemBone(bone_index=1)],
        ),
        PmxMorph(
            name_jp="material",
            morph_type=MorphType.MATERIAL,
            items=[PmxMorphItemMaterial(material_index=-1)],
        ),
        PmxMorph(
            name_jp="group",
            morph_type=MorphType.GROUP,
            items=[PmxMorphItemGroup(morph_index=0, value=0.5)],
        ),
    ]
    model.frames = [
        PmxFrame(
            name_jp="Root",
            is_special=True,
            items=[
                PmxFrameItem(is_morph=False, index=0),
                PmxFrameItem(is_morph=True, index=0),
            ],
        )
    ]
    model.rigidbodies = [
        PmxRigidBody(name_jp="body-a", bone_index=0),
        PmxRigidBody(name_jp="body-b", bone_index=-1),
    ]
    model.joints = [PmxJoint(rigidbody1_index=0, rigidbody2_index=1)]
    return model


def _complete_report(model: PmxModel) -> PmxParseReport:
    counts = {
        "header": 1,
        "vertices": len(model.vertices),
        "faces": len(model.faces),
        "textures": len(model.textures),
        "materials": len(model.materials),
        "bones": len(model.bones),
        "morphs": len(model.morphs),
        "display_frames": len(model.frames),
        "rigid_bodies": len(model.rigidbodies),
        "joints": len(model.joints),
    }
    sections = tuple(
        PmxSectionReport(name, index, index + 1, counts[name])
        for index, name in enumerate(PMX_20_REQUIRED_SECTIONS)
    )
    return PmxParseReport(
        implementation="test",
        version=2.0,
        file_size=len(sections),
        final_offset=len(sections),
        sections=sections,
    )


def test_complete_valid_model_passes_validator():
    model = _valid_model()

    assert model.validate()
    assert validate_pmx_model(model)
    assert PmxValidator().validate(model)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (
            lambda model: setattr(model.header, "additional_uv_count", "0"),
            "header.additional_uv_count",
        ),
        (
            lambda model: setattr(model.rigidbodies[0], "collision_group", "0"),
            "rigid_bodies[0].collision_group",
        ),
    ],
)
def test_wrong_primitive_types_still_raise_field_aware_errors(mutate, field):
    model = _valid_model()
    mutate(model)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == field


@pytest.mark.parametrize(
    ("mode", "weight", "field"),
    [
        (WeightMode.BDEF1, [], "vertices[0].weight"),
        (WeightMode.BDEF2, [[0, 1.0]], "vertices[0].weight"),
        (
            WeightMode.BDEF4,
            [[0, 0.5], [1, 0.3], [0, 0.2]],
            "vertices[0].weight",
        ),
        (WeightMode.SDEF, [[0, 1.0]], "vertices[0].weight"),
    ],
)
def test_weight_mode_requires_exact_record_shape(mode, weight, field):
    model = _valid_model()
    vertex = model.vertices[0]
    vertex.weight_mode = mode
    vertex.weight = weight
    if mode == WeightMode.SDEF:
        vertex.sdef_c = vertex.sdef_r0 = vertex.sdef_r1 = [0.0, 0.0, 0.0]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == field


@pytest.mark.parametrize("invalid_index", [-2, 2])
def test_vertex_weight_bone_reference_has_indexed_path(invalid_index):
    model = _valid_model()
    model.vertices[0].weight[0][0] = invalid_index

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "vertices[0].weight[0].bone_index"


def test_bdef2_complement_weights_must_be_consistent():
    model = _valid_model()
    model.vertices[1].weight[1][1] = 0.5

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "vertices[1].weight"


def test_bdef4_weight_sum_is_not_required_by_the_pmx_spec():
    model = _valid_model()
    model.vertices[2].weight = [
        [0, 0.9],
        [1, 0.8],
        [0, 0.7],
        [1, 0.6],
    ]

    assert model.validate()


def test_qdef_is_rejected_for_pmx20():
    model = _valid_model()
    model.vertices[0].weight_mode = WeightMode.QDEF
    model.vertices[0].weight = [[0, 0.25], [1, 0.25], [0, 0.25], [1, 0.25]]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "vertices[0].weight_mode"


def test_additional_uv_count_must_match_header():
    model = _valid_model()
    model.vertices[0].additional_uvs = [[0.0, 0.0, 0.0, 0.0]]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "vertices[0].additional_uvs"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("texture_index", 2),
        ("sphere_texture_index", -2),
        ("toon_texture_index", 2),
    ],
)
def test_material_texture_references_are_validated(field, value):
    model = _valid_model()
    setattr(model.materials[0], field, value)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == f"materials[0].{field}"


@pytest.mark.parametrize(
    ("configure", "field"),
    [
        (
            lambda model: setattr(model.bones[1], "parent_index", 1),
            "bones[1].parent_index",
        ),
        (
            lambda model: setattr(model.bones[1], "tail_bone_index", 1),
            "bones[1].tail",
        ),
        (
            lambda model: _set_inherit(model.bones[1], 1),
            "bones[1].inherit_parent_index",
        ),
        (
            lambda model: _set_ik(model.bones[1], target=1, link=0),
            "bones[1].ik_target_index",
        ),
        (
            lambda model: _set_ik(model.bones[1], target=0, link=1),
            "bones[1].ik_links[0].bone_index",
        ),
    ],
)
def test_bone_self_references_are_rejected(configure, field):
    model = _valid_model()
    configure(model)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == field
    assert caught.value.expected == "non-self reference or -1 sentinel"


def _set_inherit(bone: PmxBone, parent: int) -> None:
    bone.bone_flags.inherit_rot = True
    bone.inherit_parent_index = parent
    bone.inherit_ratio = 0.5


def _set_ik(bone: PmxBone, *, target: int, link: int) -> None:
    bone.bone_flags.ik = True
    bone.ik_target_index = target
    bone.ik_loop_count = 1
    bone.ik_angle_limit = 0.5
    bone.ik_links = [PmxBoneIkLink(bone_index=link)]


def test_inherit_cycle_has_actionable_origin_path():
    model = _valid_model()
    _set_inherit(model.bones[0], 1)
    _set_inherit(model.bones[1], 0)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "bones[0].inherit_parent_index"
    assert caught.value.expected == "acyclic inherit chain"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inherit_parent_index", 0),
        ("inherit_ratio", 0.5),
        ("fixed_axis", [1.0, 0.0, 0.0]),
        ("local_axis_x", [1.0, 0.0, 0.0]),
        ("external_parent_index", 10),
        ("ik_target_index", 0),
    ],
)
def test_inactive_bone_payload_is_rejected(field, value):
    model = _valid_model()
    setattr(model.bones[0], field, value)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == f"bones[0].{field}"


def test_inactive_ik_links_are_rejected():
    model = _valid_model()
    model.bones[0].ik_links = [PmxBoneIkLink(bone_index=1)]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "bones[0].ik_links"


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (
            lambda model: setattr(model.morphs[0].items[0], "vertex_index", 4),
            "morphs[0].items[0].vertex_index",
        ),
        (
            lambda model: setattr(model.morphs[1].items[0], "bone_index", 2),
            "morphs[1].items[0].bone_index",
        ),
        (
            lambda model: setattr(model.morphs[2].items[0], "material_index", -2),
            "morphs[2].items[0].material_index",
        ),
        (
            lambda model: setattr(model.morphs[3].items[0], "morph_index", 4),
            "morphs[3].items[0].morph_index",
        ),
        (
            lambda model: setattr(model.frames[0].items[0], "index", 2),
            "display_frames[0].items[0].index",
        ),
        (
            lambda model: setattr(model.frames[0].items[1], "index", 4),
            "display_frames[0].items[1].index",
        ),
        (
            lambda model: setattr(model.rigidbodies[0], "bone_index", 2),
            "rigid_bodies[0].bone_index",
        ),
        (
            lambda model: setattr(model.joints[0], "rigidbody2_index", 2),
            "joints[0].rigidbody2_index",
        ),
    ],
)
def test_cross_section_reference_paths(mutate, field):
    model = _valid_model()
    mutate(model)

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == field


def test_nested_record_error_is_prefixed_with_collection_index():
    model = _valid_model()
    model.joints[0].position[1] = math.inf

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "joints[0].position[1]"


def test_model_resource_limits_cover_outer_and_nested_counts():
    model = _valid_model()

    with pytest.raises(PmxValidationError) as caught:
        validate_pmx_model(model, limits=PmxLimits(max_count=1))

    assert caught.value.field == "vertices"

    model = _valid_model()
    model.morphs[0].items.extend(
        [PmxMorphItemVertex(vertex_index=1), PmxMorphItemVertex(vertex_index=2)]
    )
    with pytest.raises(PmxValidationError) as caught:
        validate_pmx_model(model, limits=PmxLimits(max_count=4))

    assert caught.value.field == "morphs"


def test_model_string_byte_limit_uses_header_encoding():
    model = _valid_model()
    model.header.name_jp = "界界"

    with pytest.raises(PmxValidationError) as caught:
        validate_pmx_model(model, limits=PmxLimits(max_string_bytes=3))

    assert caught.value.field == "header.name_jp"


def test_model_string_byte_limit_covers_material_texture_paths():
    model = _valid_model()
    model.materials[0].texture_path = "x" * 17

    with pytest.raises(PmxValidationError) as caught:
        validate_pmx_model(model, limits=PmxLimits(max_string_bytes=32))

    assert caught.value.field == "materials[0].texture_path"


def test_parse_report_source_size_respects_validation_limit():
    model = _valid_model()
    model.parse_report = _complete_report(model)

    with pytest.raises(PmxValidationError) as caught:
        validate_pmx_model(model, limits=PmxLimits(max_source_bytes=9))

    assert caught.value.field == "parse_report.file_size"


def test_parse_report_counts_and_strict_eof_are_validated():
    model = _valid_model()
    model.parse_report = _complete_report(model)
    assert model.validate()

    sections = list(model.parse_report.sections)
    original = sections[1]
    sections[1] = PmxSectionReport(
        original.name,
        original.start_offset,
        original.end_offset,
        original.record_count + 1,
    )
    model.parse_report = PmxParseReport(
        implementation="test",
        version=2.0,
        file_size=10,
        final_offset=10,
        sections=tuple(sections),
    )

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "parse_report.sections[vertices].record_count"


def test_lenient_validation_retains_explicit_incomplete_report():
    model = _valid_model()
    report = _complete_report(model)
    model.parse_report = PmxParseReport(
        implementation=report.implementation,
        version=report.version,
        file_size=report.file_size + 1,
        final_offset=report.final_offset,
        sections=report.sections,
    )

    with pytest.raises(PmxValidationError) as caught:
        model.validate()
    assert caught.value.field == "parse_report.is_complete"

    assert validate_pmx_model(model, strict_eof=False)
    assert model.parse_report.trailing_bytes == 1


def test_validation_is_not_removed_by_python_optimization():
    script = """
from pypmxvmd.common.models.pmx import PmxModel, PmxBone
from pypmxvmd.common.pmx import PmxValidationError
model = PmxModel()
model.header.version = 2.0
model.bones = [PmxBone(parent_index=0)]
try:
    model.validate()
except PmxValidationError as error:
    print(error.field)
    raise SystemExit(0)
raise SystemExit(2)
"""

    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bones[0].parent_index"
