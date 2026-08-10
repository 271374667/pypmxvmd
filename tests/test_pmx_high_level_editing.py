import hashlib

import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxFrame,
    PmxFrameItem,
    PmxHeader,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemFlip,
    PmxMorphItemGroup,
    PmxMorphItemUv,
    PmxMorphItemVertex,
    PmxVertex,
)
from pypmxvmd.common.pmx import (
    MorphPanel,
    MorphType,
    PmxFaceEditError,
    PmxFrameEditError,
    PmxVertexEditError,
    WeightMode,
)
from tests.test_corpus_parsers import corpus_cases


def _model(version=2.1):
    model = PmxModel()
    model.header = PmxHeader(
        version=version,
        name_jp="高層編集",
        name_en="High-level editing",
        encoding=1,
        additional_uv_count=1,
    )
    model.bones = [
        PmxBone(name_jp="骨0", parent_index=-1),
        PmxBone(name_jp="骨1", parent_index=0),
    ]
    model.vertices = [
        PmxVertex(
            position=[float(index), 0.0, 0.0],
            additional_uvs=[[float(index), 0.0, 0.0, 1.0]],
            weight=[[index % 2, 1.0]],
        )
        for index in range(4)
    ]
    model.faces = [[0, 1, 2], [1, 2, 3]]
    model.materials = [
        PmxMaterial(name_jp="材質0", face_count=3),
        PmxMaterial(name_jp="材質1", face_count=3),
    ]
    model.morphs = [
        PmxMorph(
            name_jp="頂点",
            morph_type=MorphType.VERTEX,
            items=[PmxMorphItemVertex(3, [0.1, 0.0, 0.0])],
        ),
        PmxMorph(
            name_jp="UV",
            morph_type=MorphType.UV,
            items=[PmxMorphItemUv(1, [0.1, 0.0, 0.0, 0.0])],
        ),
        PmxMorph(
            name_jp="組",
            morph_type=MorphType.GROUP,
            items=[PmxMorphItemGroup(0, 0.5)],
        ),
    ]
    model.frames = [
        PmxFrame(
            name_jp="Root",
            is_special=True,
            items=[PmxFrameItem(is_morph=False, index=0)],
        ),
        PmxFrame(
            name_jp="表情",
            is_special=True,
            items=[PmxFrameItem(is_morph=True, index=0)],
        ),
        PmxFrame(
            name_jp="通常",
            items=[PmxFrameItem(is_morph=True, index=2)],
        ),
    ]
    return model


def _document(tmp_path, version=2.1):
    path = tmp_path / "high-level.pmx"
    pypmxvmd.save_pmx(_model(version), path)
    return pypmxvmd.load_pmx_document(path)


def test_document_tracks_w12_record_spans_and_public_factories(tmp_path):
    document = _document(tmp_path)

    assert document.record_span_for("vertices[0]").start_offset > 0
    assert document.record_span_for("faces[1]").end_offset > 0
    assert document.record_span_for("morphs[0]").end_offset > 0
    assert document.record_span_for("display_frames[0]").end_offset > 0
    assert isinstance(document.edit_vertices(), pypmxvmd.PmxVertexEditor)
    assert isinstance(pypmxvmd.edit_pmx_faces(document), pypmxvmd.PmxFaceEditor)
    assert isinstance(pypmxvmd.edit_pmx_morphs(document), pypmxvmd.PmxMorphEditor)
    assert isinstance(pypmxvmd.edit_pmx_frames(document), pypmxvmd.PmxFrameEditor)


def test_noop_w12_transactions_are_byte_identical(tmp_path):
    document = _document(tmp_path)

    for editor in (
        document.edit_vertices(),
        document.edit_faces(),
        document.edit_morphs(),
        document.edit_frames(),
    ):
        result = editor.encode()
        assert result.output_bytes is document.source_bytes
        assert result.patches == ()
        assert result.changed_record_count == 0


@pytest.mark.parametrize(
    ("mode", "weights", "sdef"),
    [
        (WeightMode.BDEF1, [[0, 1.0]], None),
        (WeightMode.BDEF2, [[0, 0.25], [1, 0.75]], None),
        (
            WeightMode.BDEF4,
            [[0, 0.4], [1, 0.3], [0, 0.2], [1, 0.1]],
            None,
        ),
        (
            WeightMode.SDEF,
            [[0, 0.25], [1, 0.75]],
            ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]),
        ),
        (
            WeightMode.QDEF,
            [[0, 0.4], [1, 0.3], [0, 0.2], [1, 0.1]],
            None,
        ),
    ],
)
def test_vertex_weight_modes_additional_uv_and_edge_round_trip(
    tmp_path, mode, weights, sdef
):
    document = _document(tmp_path)
    editor = document.edit_vertices()
    kwargs = {}
    if sdef is not None:
        kwargs = {"sdef_c": sdef[0], "sdef_r0": sdef[1], "sdef_r1": sdef[2]}
    editor.set_weight(0, mode, weights, **kwargs)
    editor.set_additional_uvs(0, [[0.5, 0.6, 0.7, 0.8]])
    editor.set_geometry(0, position=[1.0, 2.0, 3.0], uv=[0.25, 0.75])
    editor.set_edge_scale(0, 2.5)

    result = editor.encode()
    vertex = result.model.vertices[0]

    assert vertex.weight_mode is mode
    assert vertex.additional_uvs[0] == pytest.approx([0.5, 0.6, 0.7, 0.8])
    assert vertex.position == pytest.approx([1.0, 2.0, 3.0])
    assert vertex.edge_scale == pytest.approx(2.5)


def test_vertex_insert_reorder_delete_remaps_all_vertex_references(tmp_path):
    document = _document(tmp_path)
    editor = document.edit_vertices()
    editor.insert_vertex(
        1,
        PmxVertex(additional_uvs=[[0.0, 0.0, 0.0, 0.0]], weight=[[0, 1.0]]),
    )
    inserted = editor.encode().model

    assert inserted.faces == [[0, 2, 3], [2, 3, 4]]
    assert inserted.morphs[0].items[0].vertex_index == 4
    assert inserted.morphs[1].items[0].vertex_index == 2

    editor = pypmxvmd.load_pmx_document(
        _write_result(tmp_path, inserted)
    ).edit_vertices()
    editor.delete_vertex(2)
    deleted = editor.encode().model

    assert deleted.faces == []
    assert [material.face_count for material in deleted.materials] == [0, 0]
    assert deleted.morphs[1].items == []
    assert deleted.morphs[0].items[0].vertex_index == 3


def _write_result(tmp_path, model):
    path = tmp_path / "transaction-result.pmx"
    pypmxvmd.save_pmx(model, path)
    return path


def test_face_topology_updates_material_ranges_and_rejects_cross_range_reorder(
    tmp_path,
):
    document = _document(tmp_path)
    editor = document.edit_faces()
    editor.append_face([0, 2, 3], material_index=0)
    editor.delete_face(0)
    editor.remap_vertex_indices({0: 3, 3: 0})
    result = editor.encode()

    assert result.model.faces == [[3, 2, 0], [1, 2, 0]]
    assert [material.face_count for material in result.model.materials] == [3, 3]

    editor = document.edit_faces()
    with pytest.raises(PmxFaceEditError, match="cannot interleave"):
        editor.reorder_faces([1, 0])


def test_morph_collection_and_item_edits_remap_group_and_frame_references(tmp_path):
    document = _document(tmp_path)
    editor = document.edit_morphs()
    editor.insert_morph(
        0,
        PmxMorph(
            name_jp="Flip",
            panel=MorphPanel.OTHER,
            morph_type=MorphType.FLIP,
            items=[PmxMorphItemFlip(1, 0.75)],
        ),
    )
    editor.append_item(1, PmxMorphItemVertex(0, [0.0, 0.1, 0.0]))
    inserted = editor.encode().model

    assert inserted.morphs[0].items[0].morph_index == 1
    assert inserted.morphs[3].items[0].morph_index == 1
    assert inserted.frames[1].items[0].index == 1
    assert inserted.frames[2].items[0].index == 3

    document = pypmxvmd.load_pmx_document(_write_result(tmp_path, inserted))
    deleted = document.edit_morphs().delete_morph(1).encode().model

    assert deleted.morphs[0].items == []
    assert deleted.frames[1].items == []
    assert deleted.frames[2].items[0].index == 2


def test_display_frame_items_names_order_and_special_constraints(tmp_path):
    document = _document(tmp_path)
    editor = document.edit_frames()
    editor.set_names(2, name_jp="編集枠", name_en="Edited")
    editor.append_item(2, PmxFrameItem(is_morph=False, index=1))
    editor.reorder_items(2, [1, 0])
    editor.append_frame(PmxFrame(name_jp="追加"))
    result = editor.encode()

    assert result.model.frames[2].name_jp == "編集枠"
    assert result.model.frames[2].items[0].bone_index == 1
    assert result.model.frames[3].name_jp == "追加"

    editor = document.edit_frames()
    with pytest.raises(PmxFrameEditError, match="first two"):
        editor.set_special(2, True)


def test_w12_transactions_reject_non_target_direct_edits(tmp_path):
    document = _document(tmp_path)
    editor = document.edit_vertices()
    editor.set_edge_scale(0, 2.0)
    editor.model.bones[0].name_jp = "unsupported"

    with pytest.raises(PmxVertexEditError, match="Unsupported non-W12 edit"):
        editor.encode()

    face_editor = document.edit_faces()
    face_editor.set_face(0, [0, 2, 1])
    face_editor.model.materials[0].name_en = "unsupported"
    with pytest.raises(PmxFaceEditError, match="cross-section edit"):
        face_editor.encode()

    morph_editor = document.edit_morphs()
    morph_editor.set_names(0, name_en="allowed")
    morph_editor.model.frames[0].name_en = "unsupported"
    with pytest.raises(pypmxvmd.PmxMorphEditError, match="cross-section edit"):
        morph_editor.encode()


@pytest.mark.corpus
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_w12_edits_use_only_temp_outputs_and_preserve_source(
    tmp_path, pmx_path
):
    before = hashlib.sha256(pmx_path.read_bytes()).hexdigest()
    document = pypmxvmd.load_pmx_document(pmx_path)
    assert document.model.vertices
    assert document.model.faces
    assert document.model.morphs
    assert document.model.frames

    vertex_editor = document.edit_vertices()
    vertex_editor.set_edge_scale(
        0, vertex_editor.vertex(0).edge_scale + 0.125
    ).write_file(tmp_path / "vertex.pmx")

    face_document = pypmxvmd.load_pmx_document(tmp_path / "vertex.pmx")
    face = face_document.model.faces[0]
    face_document.edit_faces().set_face(0, [face[0], face[2], face[1]]).write_file(
        tmp_path / "face.pmx"
    )

    morph_document = pypmxvmd.load_pmx_document(tmp_path / "face.pmx")
    morph_editor = morph_document.edit_morphs()
    morph_editor.set_names(
        0, name_en=f"{morph_editor.morph(0).name_en} W12"
    ).write_file(tmp_path / "morph.pmx")

    frame_document = pypmxvmd.load_pmx_document(tmp_path / "morph.pmx")
    frame_editor = frame_document.edit_frames()
    frame_editor.set_names(
        0, name_en=f"{frame_editor.frame(0).name_en} W12"
    ).write_file(tmp_path / "frame.pmx")

    final_model = pypmxvmd.load_pmx(tmp_path / "frame.pmx")
    assert final_model.vertices[0].edge_scale == pytest.approx(
        document.model.vertices[0].edge_scale + 0.125
    )
    assert final_model.faces[0] == [
        document.model.faces[0][0],
        document.model.faces[0][2],
        document.model.faces[0][1],
    ]
    assert final_model.morphs[0].name_en.endswith(" W12")
    assert final_model.frames[0].name_en.endswith(" W12")
    assert hashlib.sha256(pmx_path.read_bytes()).hexdigest() == before
