"""Field contracts for the PMX semantic model compatibility layer."""

import copy

from pypmxvmd.common.models.pmx import (
    BoneFlags,
    MaterialFlags,
    PmxBone,
    PmxBoneIkLink,
    PmxHeader,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxRigidBody,
    PmxTextEncoding,
    RigidBodyPhysMode,
    RigidBodyShape,
    ToonSharing,
)


def test_header_preserves_complete_global_layout_and_copy():
    flags = bytes((1, 4, 4, 2, 1, 4, 2, 1))
    header = PmxHeader(
        version=2.1,
        name_jp="モデル",
        encoding=PmxTextEncoding.UTF8,
        additional_uv_count=4,
        vertex_index_size=4,
        texture_index_size=2,
        material_index_size=1,
        bone_index_size=4,
        morph_index_size=2,
        rigid_body_index_size=1,
        global_flags=flags,
    )

    assert header.text_encoding == "utf-8"
    assert header.index_sizes == (4, 2, 1, 4, 2, 1)
    assert header.global_flags == flags
    assert header.validate()
    assert copy.deepcopy(header).to_list() == header.to_list()


def test_material_flags_mutation_keeps_raw_value_in_sync():
    flags = MaterialFlags(0)

    flags.double_sided = True
    flags.edge_drawing = True
    assert flags.value == 0x11

    flags.double_sided = False
    assert flags.value == 0x10
    assert flags.to_list()[4] is True


def test_material_preserves_indices_toon_layout_and_face_alias():
    material = PmxMaterial(
        texture_path="diffuse.png",
        texture_index=4,
        sphere_path="sphere.spa",
        sphere_texture_index=6,
        toon_path="toon10.bmp",
        toon_sharing=ToonSharing.SHARED,
        toon_texture_index=9,
        face_count=6,
    )

    assert material.texture_index == 4
    assert material.sphere_texture_index == 6
    assert material.toon_texture_index == 9
    assert material.triangle_count == 2

    material.face_vertex_count = 9
    assert material.face_count == 9
    assert material.validate()


def test_bone_flags_roundtrip_known_and_unknown_bits():
    original = 0x4047  # Unknown bit 14 plus tail, rotation and translation.
    flags = BoneFlags(value=original)

    assert flags.tail_usebonelink
    assert flags.rotatable
    assert flags.translatable
    assert flags.value == original

    flags.rotatable = False
    assert flags.value == original & ~0x0002


def test_bone_tail_modes_are_explicit_and_switchable():
    bone = PmxBone(tail=[0.0, 1.0, 0.0])

    assert bone.tail_offset == [0.0, 1.0, 0.0]
    assert bone.tail_bone_index is None

    bone.tail_bone_index = 3
    assert bone.bone_flags.tail_usebonelink
    assert bone.tail_bone_index == 3
    assert bone.tail_offset is None

    bone.tail_offset = [0.0, 2.0, 0.0]
    assert not bone.bone_flags.tail_usebonelink
    assert bone.validate()


def test_ik_link_keeps_zero_limits_as_present_values():
    link = PmxBoneIkLink(
        bone_index=1,
        limit_min=[0.0, 0.0, 0.0],
        limit_max=[0.0, 0.0, 0.0],
    )

    assert link.has_limits
    assert link.validate()


def test_rigid_body_exposes_raw_mask_and_legacy_group_views():
    body = PmxRigidBody(
        bone_index=-1,
        group=8,
        nocollide_groups=[1, 8, 16],
        shape=RigidBodyShape.CAPSULE,
        physics_mode=RigidBodyPhysMode.PHYSICS_BONE,
    )

    assert body.collision_group == 7
    assert body.group == 8
    assert body.nocollide_groups == [1, 8, 16]
    assert body.collision_mask == 0x7F7E

    body.collision_mask = 0xFFFF
    assert body.nocollide_groups == []
    assert body.validate()


def test_joint_and_model_compatibility_aliases_are_bidirectional():
    joint = PmxJoint(rigidbody1_index=2, rigidbody2_index=4)
    assert joint.rigid_body_a_index == 2
    assert joint.rigid_body_b_index == 4

    joint.rigid_body_a_index = 6
    joint.rigid_body_b_index = 8
    assert (joint.rigidbody1_index, joint.rigidbody2_index) == (6, 8)

    model = PmxModel()
    model.display_frames = []
    model.rigid_bodies = [PmxRigidBody(bone_index=-1)]
    model.soft_bodies = []
    assert model.frames is model.display_frames
    assert model.rigidbodies is model.rigid_bodies
    assert model.softbodies is model.soft_bodies
