"""Synthetic PMX models used by the high-level outfit API tests.

The fixture deliberately contains more cross-section references than the tiny
models used by the basic API tests.  It is not a sample model and must remain
safe to regenerate in memory only.
"""

from __future__ import annotations

from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxFrame,
    PmxFrameItem,
    PmxHeader,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemGroup,
    PmxMorphItemMaterial,
    PmxMorphItemUv,
    PmxMorphItemVertex,
    PmxRigidBody,
    PmxVertex,
)
from pypmxvmd.common.pmx.types import (
    MorphMaterialOperation,
    MorphType,
    PmxTextEncoding,
    RigidBodyPhysMode,
    RigidBodyShape,
    WeightMode,
)


def build_outfit_fixture(
    *,
    index_size: int = 1,
    include_morphs: bool = True,
    include_physics: bool = True,
    cloth_name: str = "服装",
) -> PmxModel:
    """Return a validated PMX 2.0 model with a three-material part layout.

    Material 0 is body, Material 1 is the removable clothing part, and
    Material 2 is a retained accessory.  Bone 1 and rigid body 0 are clothing
    exclusive; bone 0/body 1 are shared by retained faces and physics.
    """
    if index_size not in {1, 2, 4}:
        raise ValueError("index_size must be 1, 2, or 4")
    model = PmxModel()
    model.header = PmxHeader(
        version=2.0,
        name_jp="换装合成 fixture",
        name_en="Outfit fixture",
        comment_jp="synthetic",
        comment_en="synthetic",
        encoding=PmxTextEncoding.UTF8,
        additional_uv_count=4,
        vertex_index_size=index_size,
        texture_index_size=index_size,
        material_index_size=index_size,
        bone_index_size=index_size,
        morph_index_size=index_size,
        rigid_body_index_size=index_size,
    )
    positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (2.0, 0.0, 0.0),
        (3.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 0.0),
        (5.0, 0.0, 0.0),
        (4.0, 1.0, 0.0),
    ]
    weights = (
        (WeightMode.BDEF1, [[0, 1.0]], {}),
        (WeightMode.BDEF2, [[0, 0.5], [2, 0.5]], {}),
        (WeightMode.BDEF4, [[0, 0.25], [2, 0.25], [0, 0.25], [2, 0.25]], {}),
        (
            WeightMode.SDEF,
            [[1, 0.5], [0, 0.5]],
            {
                "sdef_c": [0.0, 0.0, 0.0],
                "sdef_r0": [0.1, 0.0, 0.0],
                "sdef_r1": [0.0, 0.1, 0.0],
            },
        ),
        (WeightMode.BDEF1, [[1, 1.0]], {}),
        (WeightMode.BDEF2, [[1, 0.5], [0, 0.5]], {}),
        (WeightMode.BDEF1, [[2, 1.0]], {}),
        (WeightMode.BDEF2, [[2, 0.5], [0, 0.5]], {}),
        (WeightMode.BDEF1, [[0, 1.0]], {}),
    )
    model.vertices = [
        PmxVertex(
            position=list(position),
            uv=[position[0] / 10.0, position[1] / 10.0],
            additional_uvs=[[0.0, 0.0, 0.0, 0.0] for _ in range(4)],
            weight_mode=mode,
            weight=weight,
            **extra,
        )
        for position, (mode, weight, extra) in zip(positions, weights)
    ]
    model.faces = [[0, 1, 2], [3, 4, 5], [6, 7, 8]]
    model.textures = ["body.png", "cloth.png", "accessory.png"]
    model.materials = [
        PmxMaterial(
            name_jp="身体",
            name_en="Body",
            texture_path="body.png",
            texture_index=0,
            face_count=3,
        ),
        PmxMaterial(
            name_jp=cloth_name,
            name_en="Cloth",
            texture_path="cloth.png",
            texture_index=1,
            face_count=3,
        ),
        PmxMaterial(
            name_jp="配件",
            name_en="Accessory",
            texture_path="accessory.png",
            texture_index=2,
            face_count=3,
        ),
    ]
    model.bones = [
        PmxBone(
            name_jp="中心",
            name_en="center",
            position=[0.0, 0.0, 0.0],
            parent_index=-1,
            tail=[0.0, 1.0, 0.0],
        ),
        PmxBone(
            name_jp="服装骨",
            name_en="cloth_bone",
            position=[2.0, 0.0, 0.0],
            parent_index=0,
            tail=[0.0, 1.0, 0.0],
        ),
        PmxBone(
            name_jp="共享骨",
            name_en="shared_bone",
            position=[4.0, 0.0, 0.0],
            parent_index=0,
            tail=[0.0, 1.0, 0.0],
        ),
    ]
    if include_morphs:
        model.morphs = [
            PmxMorph(
                name_jp="服装顶点",
                name_en="cloth_vertex",
                morph_type=MorphType.VERTEX,
                items=[PmxMorphItemVertex(3, [0.25, 0.0, 0.0])],
            ),
            PmxMorph(
                name_jp="服装UV",
                name_en="cloth_uv",
                morph_type=MorphType.UV,
                items=[PmxMorphItemUv(3, [0.1, 0.2, 0.0, 0.0])],
            ),
            PmxMorph(
                name_jp="服装UV1",
                name_en="cloth_uv1",
                morph_type=MorphType.EXTENDED_UV1,
                items=[PmxMorphItemUv(3, [0.0, 0.1, 0.0, 0.0])],
            ),
            PmxMorph(
                name_jp="服装UV2",
                name_en="cloth_uv2",
                morph_type=MorphType.EXTENDED_UV2,
                items=[PmxMorphItemUv(3, [0.0, 0.0, 0.1, 0.0])],
            ),
            PmxMorph(
                name_jp="服装UV3",
                name_en="cloth_uv3",
                morph_type=MorphType.EXTENDED_UV3,
                items=[PmxMorphItemUv(3, [0.0, 0.0, 0.0, 0.1])],
            ),
            PmxMorph(
                name_jp="服装UV4",
                name_en="cloth_uv4",
                morph_type=MorphType.EXTENDED_UV4,
                items=[PmxMorphItemUv(3, [0.1, 0.1, 0.1, 0.1])],
            ),
            PmxMorph(
                name_jp="服装材质",
                name_en="cloth_material",
                morph_type=MorphType.MATERIAL,
                items=[
                    PmxMorphItemMaterial(
                        1,
                        MorphMaterialOperation.ADD,
                        diffuse_color=[0.0, 0.0, 0.0, -0.25],
                    )
                ],
            ),
            PmxMorph(
                name_jp="服装骨骼",
                name_en="cloth_bone_morph",
                morph_type=MorphType.BONE,
                items=[PmxMorphItemBone(1, [0.0, 0.2, 0.0])],
            ),
            PmxMorph(
                name_jp="服装组合",
                name_en="cloth_group",
                morph_type=MorphType.GROUP,
                items=[PmxMorphItemGroup(0, 1.0), PmxMorphItemGroup(6, 1.0)],
            ),
        ]
        model.frames = [
            PmxFrame(
                name_jp="服装控制",
                name_en="Cloth controls",
                items=[PmxFrameItem(True, 8), PmxFrameItem(False, 1)],
            )
        ]
    if include_physics:
        model.rigidbodies = [
            PmxRigidBody(
                name_jp="服装刚体",
                name_en="Cloth body",
                bone_index=1,
                shape=RigidBodyShape.CAPSULE,
                physics_mode=RigidBodyPhysMode.PHYSICS,
            ),
            PmxRigidBody(
                name_jp="共享刚体",
                name_en="Shared body",
                bone_index=0,
                shape=RigidBodyShape.BOX,
                physics_mode=RigidBodyPhysMode.PHYSICS_BONE,
            ),
        ]
        model.joints = [
            PmxJoint(
                name_jp="服装关节",
                name_en="Cloth joint",
                rigidbody1_index=0,
                rigidbody2_index=1,
            ),
            PmxJoint(
                name_jp="共享关节",
                name_en="Shared joint",
                rigidbody1_index=1,
                rigidbody2_index=1,
            ),
        ]
    model.validate()
    return model
