"""Transactional W11a editing of existing PMX Bone records."""

import hashlib

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import PmxValidationError
from tests.test_corpus_parsers import corpus_cases
from tests.test_pmx_bone_reader import _pmx20_with_bones


def _document(tmp_path, index_size=2):
    path = tmp_path / f"bones-{index_size}.pmx"
    path.write_bytes(_pmx20_with_bones(index_size)[0])
    return path, pypmxvmd.load_pmx_document(path)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_document_tracks_exact_complete_bone_record_spans(tmp_path):
    _, document = _document(tmp_path)
    first = document.record_span_for("bones[0]")
    second = document.record_span_for("bones[1]")

    assert document.record_spans == (first, second)
    assert first.start_offset < first.end_offset == second.start_offset
    assert second.end_offset <= len(document.source_bytes)
    assert (
        "センター".encode("utf-8")
        in document.source_bytes[first.start_offset : first.end_offset]
    )
    assert (
        "足ＩＫ".encode("utf-8")
        in document.source_bytes[second.start_offset : second.end_offset]
    )


def test_noop_bone_transaction_is_byte_identical(tmp_path):
    _, document = _document(tmp_path)

    result = document.edit_bones().encode()

    assert result.output_bytes is document.source_bytes
    assert result.patches == ()
    assert result.changed_record_count == 0


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_name_position_deform_layer_and_basic_flags_replace_only_one_record(
    tmp_path, index_size
):
    _, document = _document(tmp_path, index_size)
    original = document.record_span_for("bones[0]")
    editor = document.edit_bones()
    editor.set_names(0, name_jp="新しいセンター", name_en="New Center")
    editor.set_position(0, [1.0, 8.0, 2.0])
    editor.set_deform_layer(0, 7)
    editor.set_basic_flags(
        0,
        rotatable=False,
        translatable=True,
        visible=False,
        enabled=False,
        deform_after_physics=True,
    )

    result = editor.encode()
    patch = result.patches[0]
    bone = result.model.bones[0]

    assert result.changed_record_count == 1
    assert patch.offset == original.start_offset
    assert len(patch.after) != len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original.end_offset :]
    )
    assert bone.name_jp == "新しいセンター"
    assert bone.name_en == "New Center"
    assert bone.position == pytest.approx([1.0, 8.0, 2.0])
    assert bone.deform_layer == 7
    assert not bone.bone_flags.rotatable
    assert bone.bone_flags.translatable
    assert bone.bone_flags.deform_after_phys


def test_enable_every_conditional_bone_payload_and_ik_limits(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_bones()
    editor.set_tail_bone(0, 1)
    editor.set_inherit(
        0,
        -1,
        0.25,
        rotation=True,
        translation=True,
        local=True,
    )
    editor.set_fixed_axis(0, [1.0, 0.0, 0.0])
    editor.set_local_axes(0, [1.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    editor.set_external_parent(0, 4321)
    editor.set_ik(
        0,
        target_index=1,
        loop_count=12,
        angle_limit=0.75,
        links=[
            pypmxvmd.ik_link(1),
            pypmxvmd.ik_link(
                1,
                limit_min=[-0.5, -0.25, -0.125],
                limit_max=[0.5, 0.25, 0.125],
            ),
        ],
    )

    result = editor.encode()
    bone = result.model.bones[0]

    assert bone.tail_bone_index == 1
    assert bone.bone_flags.inherit_rot
    assert bone.bone_flags.inherit_trans
    assert bone.bone_flags.inherit_local
    assert bone.inherit_parent_index == -1
    assert bone.inherit_ratio == pytest.approx(0.25)
    assert bone.fixed_axis == pytest.approx([1.0, 0.0, 0.0])
    assert bone.local_axis_x == pytest.approx([1.0, 0.0, 0.0])
    assert bone.local_axis_z == pytest.approx([0.0, 0.0, 1.0])
    assert bone.external_parent_index == 4321
    assert bone.ik_target_index == 1
    assert bone.ik_loop_count == 12
    assert bone.ik_angle_limit == pytest.approx(0.75)
    assert len(bone.ik_links) == 2
    assert not bone.ik_links[0].has_limits
    assert bone.ik_links[1].has_limits


def test_clear_every_conditional_payload_and_switch_to_relative_tail(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_bones()
    editor.set_tail_offset(1, [0.0, -1.0, 0.5])
    editor.clear_inherit(1)
    editor.clear_fixed_axis(1)
    editor.clear_local_axes(1)
    editor.clear_external_parent(1)
    editor.clear_ik(1)

    result = editor.encode()
    bone = result.model.bones[1]

    assert bone.tail_offset == pytest.approx([0.0, -1.0, 0.5])
    assert bone.inherit_parent_index is None
    assert bone.inherit_ratio is None
    assert bone.fixed_axis is None
    assert bone.local_axis_x is None
    assert bone.local_axis_z is None
    assert bone.external_parent_index is None
    assert bone.ik_target_index is None
    assert bone.ik_loop_count is None
    assert bone.ik_angle_limit is None
    assert bone.ik_links == []


def test_transaction_can_replace_multiple_existing_bones_atomically(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_bones()
    editor.set_deform_layer(0, 3)
    editor.set_deform_layer(1, 5)

    result = editor.encode()

    assert result.changed_record_count == 2
    assert [patch.description for patch in result.patches] == [
        "replace bones[0] record",
        "replace bones[1] record",
    ]
    assert [bone.deform_layer for bone in result.model.bones] == [3, 5]


@pytest.mark.parametrize(
    "invalid_edit",
    [
        lambda editor: editor.set_parent(0, 1),
        lambda editor: editor.set_inherit(0, 1, 0.5),
        lambda editor: editor.set_tail_bone(0, 99),
        lambda editor: editor.set_deform_layer(0, -1),
    ],
)
def test_invalid_reference_cycle_and_layer_preserve_existing_target(
    tmp_path, invalid_edit
):
    _, document = _document(tmp_path)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")
    editor = document.edit_bones()
    invalid_edit(editor)

    with pytest.raises(PmxValidationError):
        editor.write_file(target)

    assert target.read_bytes() == b"keep"
    assert document.model.bones[0].parent_index == -1


def test_invalid_ik_limit_pair_and_argument_types_fail_closed(tmp_path):
    _, document = _document(tmp_path)

    with pytest.raises(pypmxvmd.PmxBoneEditError, match="both"):
        pypmxvmd.ik_link(1, limit_min=[-1.0, 0.0, 0.0])
    with pytest.raises(pypmxvmd.PmxBoneEditError, match="must not exceed"):
        pypmxvmd.ik_link(
            1,
            limit_min=[0.5, 0.0, 0.0],
            limit_max=[-0.5, 0.0, 0.0],
        )
    with pytest.raises(pypmxvmd.PmxBoneEditError, match="bool"):
        document.edit_bones().set_basic_flags(0, visible=1)
    with pytest.raises(pypmxvmd.PmxBoneEditError, match="3 values"):
        document.edit_bones().set_position(0, [1.0, 2.0])

    invalid_link = pypmxvmd.ik_link(1)
    invalid_link.has_limits = True
    editor = document.edit_bones().set_ik(0, 1, 4, 0.5, [invalid_link])
    with pytest.raises(PmxValidationError):
        editor.encode()

    unordered_link = pypmxvmd.ik_link(
        1,
        limit_min=[-0.5, 0.0, 0.0],
        limit_max=[0.5, 0.0, 0.0],
    )
    unordered_link.limit_min[0] = 1.0
    editor = document.edit_bones().set_ik(0, 1, 4, 0.5, [unordered_link])
    with pytest.raises(PmxValidationError, match="limit_min <= limit_max"):
        editor.encode()


def test_non_bone_edits_and_bone_collection_reorder_are_rejected(tmp_path):
    _, document = _document(tmp_path)
    non_bone = document.edit_bones()
    non_bone.model.header.name_jp = "not a Bone edit"

    with pytest.raises(pypmxvmd.PmxBoneEditError, match="non-Bone"):
        non_bone.encode()

    reordered = document.edit_bones()
    reordered.model.bones.reverse()
    with pytest.raises(pypmxvmd.PmxBoneEditError, match="reorder"):
        reordered.encode()


def test_bone_editor_requires_a_clean_document_and_keeps_source_model_isolated(
    tmp_path,
):
    _, document = _document(tmp_path)
    editor = document.edit_bones().set_deform_layer(0, 9)

    assert document.model.bones[0].deform_layer == 2
    assert editor.model.bones[0].deform_layer == 9

    document.model.bones[0].deform_layer = 4
    with pytest.raises(pypmxvmd.PmxBoneEditError, match="unmodified"):
        document.edit_bones()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_bone_edit_writes_only_to_tmp_and_preserves_source(
    pmx_path, tmp_path
):
    before_hash = _sha256(pmx_path)
    document = pypmxvmd.load_pmx_document(pmx_path)
    original_layer = document.model.bones[0].deform_layer
    original_name_en = document.model.bones[0].name_en
    edited_name_en = f"{original_name_en} W11a"
    editor = document.edit_bones()
    editor.set_names(0, name_en=edited_name_en)
    editor.set_deform_layer(0, original_layer + 1)
    output = tmp_path / pmx_path.name

    result = editor.write_file(output)
    reparsed = pypmxvmd.load_pmx(output)
    patch = result.patches[0]
    original_span = document.record_span_for("bones[0]")

    assert result.changed_record_count == 1
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original_span.end_offset :]
    )
    assert reparsed.bones[0].name_en == edited_name_en
    assert reparsed.bones[0].deform_layer == original_layer + 1
    assert reparsed.is_complete
    assert _sha256(pmx_path) == before_hash
