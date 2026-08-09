"""Actionable validation failures for priority PMX model records."""

import pytest

from pypmxvmd.common.models.pmx import (
    BoneFlags,
    MorphType,
    PmxBone,
    PmxFrame,
    PmxFrameItem,
    PmxHeader,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemVertex,
    PmxRigidBody,
    PmxVertex,
    ToonSharing,
    WeightMode,
)
from pypmxvmd.common.pmx import PmxValidationError


@pytest.mark.parametrize(
    ("header", "field"),
    [
        (PmxHeader(version=2.0, additional_uv_count=5), "header.additional_uv_count"),
        (PmxHeader(version=2.0, bone_index_size=3), "header.bone_index_size"),
    ],
)
def test_header_validation_names_the_invalid_field(header, field):
    with pytest.raises(PmxValidationError) as caught:
        header.validate()

    assert caught.value.field == field
    assert "expected" in str(caught.value)


def test_shared_toon_index_is_validated():
    material = PmxMaterial(
        toon_sharing=ToonSharing.SHARED,
        toon_texture_index=10,
    )

    with pytest.raises(PmxValidationError) as caught:
        material.validate()

    assert caught.value.field == "material.toon_texture_index"


def test_bone_tail_representation_must_match_flag():
    bone = PmxBone(bone_flags=BoneFlags(tail_usebonelink=True), tail=[0.0, 1.0, 0.0])

    with pytest.raises(PmxValidationError) as caught:
        bone.validate()

    assert caught.value.field == "bone.tail"


def test_model_rejects_bone_parent_cycle():
    model = PmxModel()
    model.bones = [PmxBone(parent_index=1), PmxBone(parent_index=0)]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "bones[0].parent_index"
    assert caught.value.expected == "acyclic parent chain"


def test_model_validates_rigid_body_and_joint_references():
    model = PmxModel()
    model.rigidbodies = [PmxRigidBody(bone_index=-1)]
    model.joints = [PmxJoint(rigidbody1_index=0, rigidbody2_index=1)]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "joints[0].rigidbody2_index"


def test_model_validates_material_face_vertex_total():
    model = PmxModel()
    model.vertices = []
    model.faces = []
    model.materials = [PmxMaterial(face_count=3)]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "materials.face_count"


def test_sdef_vertex_requires_all_three_raw_vectors():
    vertex = PmxVertex(weight_mode=WeightMode.SDEF)

    with pytest.raises(PmxValidationError) as caught:
        vertex.validate()

    assert caught.value.field == "vertex.sdef_c"


def test_morph_item_type_must_match_declared_morph_type():
    morph = PmxMorph(
        morph_type=MorphType.VERTEX,
        items=[PmxMorphItemBone()],
    )

    with pytest.raises(PmxValidationError) as caught:
        morph.validate()

    assert caught.value.field == "morph.items"


def test_display_frame_reference_uses_target_collection():
    model = PmxModel()
    model.morphs = [
        PmxMorph(
            morph_type=MorphType.VERTEX,
            items=[PmxMorphItemVertex(vertex_index=0)],
        )
    ]
    model.vertices = [PmxVertex()]
    model.frames = [PmxFrame(items=[PmxFrameItem(is_morph=True, index=1)])]

    with pytest.raises(PmxValidationError) as caught:
        model.validate()

    assert caught.value.field == "display_frames[0].items[0].index"
