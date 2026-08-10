import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxFrame,
    PmxHeader,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemGroup,
    PmxMorphItemImpulse,
    PmxMorphItemMaterial,
    PmxMorphItemVertex,
    PmxRigidBody,
    PmxSoftBody,
    PmxSoftBodyAnchor,
    PmxVertex,
)
from pypmxvmd.common.pmx import MorphPanel, MorphType, WeightMode


def _model(name: str, offset: float = 0.0) -> PmxModel:
    model = PmxModel()
    model.header = PmxHeader(
        version=2.1,
        name_jp=name,
        name_en=name,
        encoding=1,
        additional_uv_count=0,
    )
    model.bones = [PmxBone(name_jp="センター", name_en="center")]
    model.vertices = [
        PmxVertex(position=[offset, 0.0, 0.0], weight=[[0, 1.0]]),
        PmxVertex(position=[offset + 1.0, 0.0, 0.0], weight=[[0, 1.0]]),
        PmxVertex(position=[offset, 1.0, 0.0], weight=[[0, 1.0]]),
    ]
    model.faces = [[0, 1, 2]]
    model.materials = [PmxMaterial(name_jp=name, face_count=3)]
    model.frames = [PmxFrame(name_jp="表情", is_special=True)]
    return model


def _two_material_model() -> PmxModel:
    model = _model("two-materials")
    model.vertices.extend(
        [
            PmxVertex(position=[4.0, 0.0, 0.0], weight=[[0, 1.0]]),
            PmxVertex(position=[5.0, 0.0, 0.0], weight=[[0, 1.0]]),
            PmxVertex(position=[4.0, 1.0, 0.0], weight=[[0, 1.0]]),
        ]
    )
    model.faces.append([3, 4, 5])
    model.materials[0].face_count = 3
    model.materials.append(
        PmxMaterial(name_jp="旧衣", name_en="old clothes", face_count=3)
    )
    return model


def test_transaction_rolls_back_without_touching_target(tmp_path):
    target = tmp_path / "target.pmx"
    target.write_bytes(b"unchanged")
    model = _model("base")

    with pytest.raises(RuntimeError):
        with pypmxvmd.edit_pmx(model, output_path=target) as transaction:
            transaction.add_bone(name_jp="撤销")
            raise RuntimeError("abort")

    assert target.read_bytes() == b"unchanged"
    assert len(model.bones) == 1


def test_transaction_explicit_rollback_closes_without_committing(tmp_path):
    target = tmp_path / "rolled-back.pmx"
    with pypmxvmd.edit_pmx(_model("base"), output_path=target) as transaction:
        transaction.add_bone(name_jp="撤销")
        transaction.rollback()

    assert transaction.rolled_back
    assert transaction.result is None
    assert not target.exists()


def test_transaction_validation_failure_rolls_back_without_touching_target(tmp_path):
    target = tmp_path / "invalid.pmx"
    target.write_bytes(b"unchanged")

    with pytest.raises(pypmxvmd.PmxTransactionError, match="parent_index"):
        with pypmxvmd.edit_pmx(_model("base"), output_path=target) as transaction:
            transaction.add_bone(name_jp="invalid", parent_index=999)

    assert transaction.rolled_back
    assert transaction.result is None
    assert target.read_bytes() == b"unchanged"


def test_transaction_adds_bone_paints_weights_and_adds_visible_morph(tmp_path):
    target = tmp_path / "edited.pmx"
    with pypmxvmd.edit_pmx(_model("base"), output_path=target) as transaction:
        bone_index = transaction.add_bone(
            name_jp="裙骨", name_en="skirt", parent_index=0
        )
        transaction.paint_weights([0, 1], bone_index, 0.8)
        morph_index = transaction.add_vertex_morph(
            name_jp="裙摆",
            name_en="skirt hem",
            offsets={0: [0.0, 0.2, 0.0]},
            panel=MorphPanel.OTHER,
            display_frame_index=0,
        )
        assert morph_index == 0

    result = pypmxvmd.load_pmx(target)
    assert result.bones[bone_index].name_jp == "裙骨"
    assert result.vertices[0].weight_mode is WeightMode.BDEF2
    assert result.vertices[0].weight[0][0] == bone_index
    assert result.vertices[0].weight[0][1] == pytest.approx(0.8)
    assert result.vertices[0].weight[1] == [0, pytest.approx(0.2)]
    assert result.morphs[0].panel is MorphPanel.OTHER
    assert result.morphs[0].items[0].vertex_index == 0
    assert result.frames[0].items[0].is_morph
    assert result.frames[0].items[0].index == morph_index


def test_transaction_exposes_existing_bone_for_validated_modification():
    with pypmxvmd.edit_pmx(_model("base")) as transaction:
        bone = transaction.bone(0)
        bone.name_jp = "センター改"
        bone.position = [1.0, 2.0, 3.0]

    assert transaction.result is not None
    assert transaction.result.model.bones[0].name_jp == "センター改"
    assert transaction.result.model.bones[0].position == pytest.approx([1.0, 2.0, 3.0])


def test_transaction_explicit_weight_layouts_are_supported():
    model = _model("weights")
    with pypmxvmd.edit_pmx(model) as transaction:
        transaction.add_bone(name_jp="第二骨")
        transaction.set_weight(
            0,
            WeightMode.BDEF4,
            [[0, 0.4], [1, 0.3], [-1, 0.2], [-1, 0.1]],
        )
        transaction.set_weight(
            1,
            WeightMode.SDEF,
            [[0, 0.25], [1, 0.75]],
            sdef_c=[0, 0, 0],
            sdef_r0=[1, 0, 0],
            sdef_r1=[0, 1, 0],
        )

    assert transaction.result is not None
    assert transaction.result.model.vertices[0].weight_mode is WeightMode.BDEF4
    assert transaction.result.model.vertices[1].weight_mode is WeightMode.SDEF


def test_transaction_merges_part_and_remaps_cross_section_indices():
    target = _model("target")
    part = _model("clothes", 5.0)
    part.bones.append(PmxBone(name_jp="裙骨", parent_index=0))
    part.vertices[0].weight = [[1, 1.0]]
    part.morphs = [
        PmxMorph(
            name_jp="布料",
            panel=MorphPanel.OTHER,
            morph_type=MorphType.VERTEX,
            items=[PmxMorphItemVertex(0, [0.0, 0.1, 0.0])],
        ),
        PmxMorph(
            name_jp="布料组",
            panel=MorphPanel.OTHER,
            morph_type=MorphType.GROUP,
            items=[PmxMorphItemGroup(0, 0.5)],
        ),
    ]

    with pypmxvmd.edit_pmx(target) as transaction:
        mappings = transaction.merge_part(part)

    merged = transaction.result.model
    assert mappings["bones"] == {0: 0, 1: 1}
    assert mappings["vertices"] == {0: 3, 1: 4, 2: 5}
    assert merged.faces[-1] == [3, 4, 5]
    assert merged.vertices[3].weight == [[1, 1.0]]
    assert merged.morphs[0].items[0].vertex_index == 3
    assert merged.morphs[1].items[0].morph_index == 0


def test_transaction_merge_remaps_physics_and_soft_body_references():
    target = _model("target")
    target.rigidbodies = [PmxRigidBody(name_jp="既存", bone_index=0)]
    target.morphs = [
        PmxMorph(name_jp="既存表情", items=[PmxMorphItemVertex(0, [0.0, 0.0, 0.1])])
    ]
    part = _model("part", 3.0)
    part.rigidbodies = [PmxRigidBody(name_jp="布物理", bone_index=0)]
    part.joints = [PmxJoint(name_jp="布Joint", rigidbody1_index=0, rigidbody2_index=0)]
    part.morphs = [
        PmxMorph(
            name_jp="布Impulse",
            panel=MorphPanel.OTHER,
            morph_type=MorphType.IMPULSE,
            items=[PmxMorphItemImpulse(0, velocity=[0.1, 0.0, 0.0])],
        )
    ]
    part.softbodies = [
        PmxSoftBody(
            name_jp="布SoftBody",
            material_index=0,
            anchors=[PmxSoftBodyAnchor(rigidbody_index=0, vertex_index=0)],
            pin_vertex_indices=[1],
        )
    ]

    with pypmxvmd.edit_pmx(target) as transaction:
        mappings = transaction.merge_part(part)

    merged = transaction.result.model
    assert mappings["rigid_bodies"] == {0: 1}
    assert merged.rigidbodies[1].bone_index == 0
    assert merged.joints[0].rigidbody1_index == 1
    assert merged.morphs[1].items[0].rigidbody_index == 1
    assert merged.softbodies[0].material_index == 1
    assert merged.softbodies[0].anchors[0].rigidbody_index == 1
    assert merged.softbodies[0].anchors[0].vertex_index == 3
    assert merged.softbodies[0].pin_vertex_indices == [4]


def test_transaction_rejects_source_overwrite(tmp_path):
    source = tmp_path / "source.pmx"
    pypmxvmd.save_pmx(_model("source"), source)
    with pytest.raises(pypmxvmd.PmxTransactionError, match="overwrite"):
        with pypmxvmd.edit_pmx(source, output_path=source):
            pass


def test_rejected_part_merge_does_not_mutate_transaction_model():
    target = _model("target")
    part = _model("part", 3.0)

    with pypmxvmd.edit_pmx(target) as transaction:
        with pytest.raises(pypmxvmd.PmxTransactionError, match="Display Frames"):
            transaction.merge_part(part, include_frames=False)
        assert len(transaction.model.vertices) == len(target.vertices)
        assert len(transaction.model.materials) == len(target.materials)


def test_caught_part_merge_failure_restores_transaction_model():
    target = _model("target")
    part = _model("part", 3.0)

    with pypmxvmd.edit_pmx(target) as transaction:
        try:
            transaction.merge_part(part, include_frames=False)
        except pypmxvmd.PmxTransactionError:
            pass
        assert len(transaction.model.vertices) == len(target.vertices)
        assert len(transaction.model.bones) == len(target.bones)


def test_remove_part_by_material_name_compacts_exclusive_vertices():
    model = _two_material_model()

    with pypmxvmd.edit_pmx(model) as transaction:
        mapping = transaction.remove_part(
            material_names=["旧衣"], compact_vertices=True
        )

    assert transaction.result is not None
    result = transaction.result.model
    assert len(result.materials) == 1
    assert len(result.faces) == 1
    assert len(result.vertices) == 3
    assert mapping["materials"] == {0: 0}
    assert mapping["faces"] == {0: 0}
    assert mapping["removed_materials"] == {1: -1}


def test_remove_part_rejects_live_material_morph_reference_without_mutation():
    model = _two_material_model()
    model.morphs = [
        PmxMorph(
            name_jp="旧衣材质",
            morph_type=MorphType.MATERIAL,
            items=[PmxMorphItemMaterial(material_index=1)],
        )
    ]

    with pypmxvmd.edit_pmx(model) as transaction:
        with pytest.raises(pypmxvmd.PmxTransactionError, match="Material"):
            transaction.remove_part([1])
        assert len(transaction.model.materials) == 2
        assert len(transaction.model.faces) == 2


def test_replace_part_removes_selected_material_range_then_merges_replacement():
    target = _two_material_model()
    replacement = _model("replacement", 10.0)

    with pypmxvmd.edit_pmx(target) as transaction:
        result = transaction.replace_part(
            replacement,
            material_names=["旧衣"],
            compact_vertices=True,
        )

    assert transaction.result is not None
    merged = transaction.result.model
    assert len(merged.materials) == 2
    assert len(merged.faces) == 2
    assert len(merged.vertices) == 6
    assert result["removed"]["removed_materials"] == {1: -1}
    assert result["merged"]["vertices"] == {0: 3, 1: 4, 2: 5}
