"""Transactional W11c editing of existing PMX 2.0 Joint records."""

import hashlib
import struct

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import JointType, PmxValidationError
from tests.test_corpus_parsers import corpus_cases
from tests.test_pmx_sections_reader import _pmx20_all_sections, _pmx_string


def _pmx20_with_two_joints(index_size=2):
    payload, offsets = _pmx20_all_sections(index_size)
    encoded_name = _pmx_string("Joint")
    record_start = offsets["joint_type"] - (2 * len(encoded_name))
    count_offset = record_start - 4
    assert struct.unpack_from("<i", payload, count_offset)[0] == 1
    record = payload[record_start:]
    return payload[:count_offset] + struct.pack("<i", 2) + record + record


def _document(tmp_path, index_size=2):
    path = tmp_path / f"joints-{index_size}.pmx"
    path.write_bytes(_pmx20_with_two_joints(index_size))
    return path, pypmxvmd.load_pmx_document(path)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_document_tracks_exact_complete_joint_record_spans(tmp_path):
    _, document = _document(tmp_path)
    first = document.record_span_for("joints[0]")
    second = document.record_span_for("joints[1]")

    assert first in document.record_spans
    assert second in document.record_spans
    assert first.start_offset < first.end_offset == second.start_offset
    assert second.end_offset == len(document.source_bytes)
    assert b"Joint" in document.source_bytes[first.start_offset : first.end_offset]


def test_noop_joint_transaction_is_byte_identical(tmp_path):
    _, document = _document(tmp_path)

    result = document.edit_joints().encode()

    assert result.output_bytes is document.source_bytes
    assert result.patches == ()
    assert result.changed_record_count == 0


def test_joint_editor_and_factory_are_public(tmp_path):
    _, document = _document(tmp_path)

    direct = pypmxvmd.edit_pmx_joints(document)
    direct.set_joint_type(0, JointType.SPRING6DOF)

    assert isinstance(direct, pypmxvmd.PmxJointEditor)
    assert isinstance(direct.encode(), pypmxvmd.PmxJointEditResult)


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_variable_names_and_rigid_body_sentinels_replace_only_one_record(
    tmp_path, index_size
):
    _, document = _document(tmp_path, index_size)
    original = document.record_span_for("joints[0]")
    editor = document.edit_joints()
    editor.set_names(0, name_jp="長いジョイント名", name_en="Long Joint name")
    editor.set_rigid_body_references(0, -1, 1)

    result = editor.encode()
    patch = result.patches[0]
    joint = result.model.joints[0]

    assert result.changed_record_count == 1
    assert patch.offset == original.start_offset
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original.end_offset :]
    )
    assert joint.name_jp == "長いジョイント名"
    assert joint.name_en == "Long Joint name"
    assert joint.rigidbody1_index == -1
    assert joint.rigidbody2_index == 1
    assert result.model.joints[1].name_jp == document.model.joints[1].name_jp


def test_all_eight_vectors_round_trip_in_source_units_and_raw_radians(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_joints()
    editor.set_position(0, [1.25, 2.5, 3.75])
    editor.set_rotation(0, [-0.25, 0.5, 1.25])
    editor.set_position_limits(0, [-3.0, -2.0, -1.0], [3.0, 2.0, 1.0])
    editor.set_rotation_limits(0, [-0.3, -0.2, -0.1], [0.3, 0.2, 0.1])
    editor.set_position_spring(0, [4.0, 5.0, 6.0])
    editor.set_rotation_spring(0, [0.4, 0.5, 0.6])

    joint = editor.encode().model.joints[0]

    assert joint.position == pytest.approx([1.25, 2.5, 3.75])
    assert joint.rotation == pytest.approx([-0.25, 0.5, 1.25])
    assert joint.position_min == pytest.approx([-3.0, -2.0, -1.0])
    assert joint.position_max == pytest.approx([3.0, 2.0, 1.0])
    assert joint.rotation_min == pytest.approx([-0.3, -0.2, -0.1])
    assert joint.rotation_max == pytest.approx([0.3, 0.2, 0.1])
    assert joint.position_spring == pytest.approx([4.0, 5.0, 6.0])
    assert joint.rotation_spring == pytest.approx([0.4, 0.5, 0.6])


@pytest.mark.parametrize(
    "invalid_edit",
    [
        lambda editor: setattr(editor.model.joints[0], "rigidbody1_index", 99),
        lambda editor: setattr(editor.model.joints[0], "joint_type", 99),
        lambda editor: editor.model.joints[0].position.__setitem__(0, float("nan")),
        lambda editor: editor.model.joints[0].rotation.__setitem__(1, float("inf")),
        lambda editor: editor.model.joints[0].position_spring.__setitem__(2, 1e100),
    ],
)
def test_invalid_reference_enum_and_numbers_preserve_existing_target(
    tmp_path, invalid_edit
):
    _, document = _document(tmp_path)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")
    editor = document.edit_joints()
    invalid_edit(editor)

    with pytest.raises(PmxValidationError):
        editor.write_file(target)

    assert target.read_bytes() == b"keep"


@pytest.mark.parametrize(
    ("minimum_name", "maximum_name", "field_match"),
    [
        ("position_min", "position_max", "position_limits"),
        ("rotation_min", "rotation_max", "rotation_limits"),
    ],
)
def test_newly_inverted_limit_axis_preserves_existing_target(
    tmp_path, minimum_name, maximum_name, field_match
):
    _, document = _document(tmp_path)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")
    editor = document.edit_joints()
    minimum = getattr(editor.model.joints[0], minimum_name)
    maximum = getattr(editor.model.joints[0], maximum_name)
    minimum[0] = maximum[0] + 1.0

    with pytest.raises(PmxValidationError, match=field_match):
        editor.write_file(target)

    assert target.read_bytes() == b"keep"


def test_unchanged_legacy_inverted_limit_axis_is_preserved(tmp_path):
    path, document = _document(tmp_path)
    minimum_span = document.span_for("joints[0].position_min")
    source = bytearray(document.source_bytes)
    struct.pack_into(
        "<f",
        source,
        minimum_span.start_offset,
        document.model.joints[0].position_max[0] + 1.0,
    )
    path.write_bytes(source)
    legacy_document = pypmxvmd.load_pmx_document(path)

    result = legacy_document.edit_joints().set_names(0, name_en="legacy").encode()

    joint = result.model.joints[0]
    assert joint.position_min[0] > joint.position_max[0]
    assert joint.name_en == "legacy"


def test_invalid_argument_types_ranges_and_limit_pairs_fail_closed(tmp_path):
    _, document = _document(tmp_path)

    with pytest.raises(pypmxvmd.PmxJointEditError, match="joint_type"):
        document.edit_joints().set_joint_type(0, 1)
    with pytest.raises(pypmxvmd.PmxJointEditError, match="integer"):
        document.edit_joints().set_rigid_body_references(0, True, 1)
    with pytest.raises(pypmxvmd.PmxJointEditError, match="finite"):
        document.edit_joints().set_rotation(0, [0.0, float("nan"), 0.0])
    with pytest.raises(pypmxvmd.PmxJointEditError, match="3 values"):
        document.edit_joints().set_position_spring(0, [1.0, 2.0])
    with pytest.raises(pypmxvmd.PmxJointEditError, match="minimum <= maximum"):
        document.edit_joints().set_position_limits(0, [1.0, 0.0, 0.0], [0.0, 0.0, 0.0])


def test_non_joint_edits_and_joint_collection_changes_are_rejected(tmp_path):
    _, document = _document(tmp_path)
    non_joint = document.edit_joints()
    non_joint.model.rigidbodies[0].mass = 3.0

    with pytest.raises(pypmxvmd.PmxJointEditError, match="non-Joint"):
        non_joint.encode()

    reordered = document.edit_joints()
    reordered.model.joints.reverse()
    with pytest.raises(pypmxvmd.PmxJointEditError, match="reorder"):
        reordered.encode()

    replaced = document.edit_joints()
    replaced.model.joints[0] = replaced.model.joints[1]
    with pytest.raises(pypmxvmd.PmxJointEditError, match="replace"):
        replaced.encode()

    deleted = document.edit_joints()
    deleted.model.joints.pop()
    with pytest.raises(pypmxvmd.PmxJointEditError, match="insert or delete"):
        deleted.encode()


def test_joint_editor_requires_clean_document_and_isolates_source_model(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_joints().set_position(0, [9.0, 8.0, 7.0])

    assert document.model.joints[0].position == pytest.approx([1.0, 2.0, 3.0])
    assert editor.model.joints[0].position == pytest.approx([9.0, 8.0, 7.0])

    document.model.joints[0].position = [4.0, 5.0, 6.0]
    with pytest.raises(pypmxvmd.PmxJointEditError, match="unmodified"):
        document.edit_joints()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_joint_edit_writes_only_to_tmp_and_preserves_source(
    pmx_path, tmp_path
):
    before_hash = _sha256(pmx_path)
    document = pypmxvmd.load_pmx_document(pmx_path)
    assert document.model.joints, f"required Joint corpus is empty: {pmx_path}"
    original_name_en = document.model.joints[0].name_en
    edited_name_en = f"{original_name_en} W11c"
    editor = document.edit_joints()
    editor.set_names(0, name_en=edited_name_en)
    output = tmp_path / pmx_path.name

    result = editor.write_file(output)
    reparsed = pypmxvmd.load_pmx(output)
    patch = result.patches[0]
    original_span = document.record_span_for("joints[0]")

    assert result.changed_record_count == 1
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original_span.end_offset :]
    )
    assert reparsed.joints[0].name_en == edited_name_en
    assert reparsed.is_complete
    assert _sha256(pmx_path) == before_hash
