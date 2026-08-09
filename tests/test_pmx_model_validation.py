"""Actionable validation failures for priority PMX model records."""

import pytest

from pypmxvmd.common.models.pmx import (
    BoneFlags,
    PmxBone,
    PmxHeader,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxRigidBody,
    ToonSharing,
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
