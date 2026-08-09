"""Transactional W11b editing of existing PMX Rigid Body records."""

import hashlib

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import PmxValidationError, RigidBodyPhysMode, RigidBodyShape
from tests.test_corpus_parsers import corpus_cases
from tests.test_pmx_sections_reader import _pmx20_all_sections


def _document(tmp_path, index_size=2):
    path = tmp_path / f"rigid-bodies-{index_size}.pmx"
    path.write_bytes(_pmx20_all_sections(index_size)[0])
    return path, pypmxvmd.load_pmx_document(path)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_document_tracks_exact_complete_rigid_body_record_spans(tmp_path):
    _, document = _document(tmp_path)
    spans = tuple(
        document.record_span_for(f"rigidbodies[{index}]") for index in range(3)
    )

    assert all(span in document.record_spans for span in spans)
    assert spans[0].start_offset < spans[0].end_offset == spans[1].start_offset
    assert spans[1].end_offset == spans[2].start_offset < spans[2].end_offset
    assert (
        "剛体0".encode("utf-8")
        in document.source_bytes[spans[0].start_offset : spans[0].end_offset]
    )


def test_noop_rigid_body_transaction_is_byte_identical(tmp_path):
    _, document = _document(tmp_path)

    result = document.edit_rigid_bodies().encode()

    assert result.output_bytes is document.source_bytes
    assert result.patches == ()
    assert result.changed_record_count == 0


def test_rigid_body_editor_and_factory_are_public(tmp_path):
    _, document = _document(tmp_path)

    direct = pypmxvmd.edit_pmx_rigid_bodies(document)

    assert isinstance(direct, pypmxvmd.PmxRigidBodyEditor)
    assert isinstance(direct.encode(), pypmxvmd.PmxRigidBodyEditResult)


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_variable_names_and_bone_index_sentinel_replace_only_one_record(
    tmp_path, index_size
):
    _, document = _document(tmp_path, index_size)
    original = document.record_span_for("rigidbodies[0]")
    original_joints = [
        (joint.rigidbody1_index, joint.rigidbody2_index)
        for joint in document.model.joints
    ]
    editor = document.edit_rigid_bodies()
    editor.set_names(0, name_jp="長い剛体名", name_en="Long rigid body name")
    editor.set_bone(0, -1)

    result = editor.encode()
    patch = result.patches[0]
    body = result.model.rigidbodies[0]

    assert result.changed_record_count == 1
    assert patch.offset == original.start_offset
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original.end_offset :]
    )
    assert body.name_jp == "長い剛体名"
    assert body.name_en == "Long rigid body name"
    assert body.bone_index == -1
    assert [
        (joint.rigidbody1_index, joint.rigidbody2_index)
        for joint in result.model.joints
    ] == original_joints


@pytest.mark.parametrize(
    ("shape", "physics_mode"),
    zip(RigidBodyShape, RigidBodyPhysMode),
)
def test_all_shapes_and_physics_modes_round_trip(tmp_path, shape, physics_mode):
    _, document = _document(tmp_path)
    body_index = (int(shape) + 1) % 3
    editor = document.edit_rigid_bodies()
    editor.set_shape(body_index, shape)
    editor.set_physics_mode(body_index, physics_mode)

    result = editor.encode()
    body = result.model.rigidbodies[body_index]

    assert result.changed_record_count == 1
    assert body.shape is shape
    assert body.physics_mode is physics_mode


@pytest.mark.parametrize("collision_group", range(16))
def test_all_collision_groups_and_mask_bits_round_trip(tmp_path, collision_group):
    _, document = _document(tmp_path)
    collision_mask = 0xFFFF ^ (1 << collision_group)
    editor = document.edit_rigid_bodies()
    editor.set_collision(
        1,
        collision_group=collision_group,
        collision_mask=collision_mask,
    )

    result = editor.encode()
    body = result.model.rigidbodies[1]

    assert result.changed_record_count == 1
    assert body.collision_group == collision_group
    assert body.collision_mask == collision_mask
    assert body.nocollide_groups == [collision_group + 1]


def test_pose_and_all_five_physical_parameters_preserve_raw_radians(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_rigid_bodies()
    editor.set_size(1, [1.25, 2.5, 3.75])
    editor.set_position(1, [-4.0, 5.5, 6.25])
    editor.set_rotation(1, [-0.25, 0.5, 1.25])
    editor.set_physical_parameters(
        1,
        mass=2.0,
        move_damping=0.1,
        rotation_damping=0.2,
        repulsion=0.3,
        friction=0.4,
    )

    body = editor.encode().model.rigidbodies[1]

    assert body.size == pytest.approx([1.25, 2.5, 3.75])
    assert body.position == pytest.approx([-4.0, 5.5, 6.25])
    assert body.rotation == pytest.approx([-0.25, 0.5, 1.25])
    assert body.mass == pytest.approx(2.0)
    assert body.move_damping == pytest.approx(0.1)
    assert body.rotation_damping == pytest.approx(0.2)
    assert body.repulsion == pytest.approx(0.3)
    assert body.friction == pytest.approx(0.4)


@pytest.mark.parametrize(
    "invalid_edit",
    [
        lambda editor: setattr(editor.model.rigidbodies[0], "bone_index", 99),
        lambda editor: setattr(editor.model.rigidbodies[0], "shape", 99),
        lambda editor: setattr(editor.model.rigidbodies[0], "physics_mode", 99),
        lambda editor: setattr(editor.model.rigidbodies[0], "collision_group", 16),
        lambda editor: setattr(editor.model.rigidbodies[0], "collision_mask", 0x10000),
        lambda editor: setattr(editor.model.rigidbodies[0], "mass", float("nan")),
        lambda editor: setattr(editor.model.rigidbodies[0], "mass", 1e100),
        lambda editor: setattr(editor.model.rigidbodies[0], "friction", float("inf")),
    ],
)
def test_invalid_reference_enum_group_mask_and_numbers_preserve_target(
    tmp_path, invalid_edit
):
    _, document = _document(tmp_path)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")
    editor = document.edit_rigid_bodies()
    invalid_edit(editor)

    with pytest.raises(PmxValidationError):
        editor.write_file(target)

    assert target.read_bytes() == b"keep"


def test_invalid_argument_types_and_ranges_fail_closed(tmp_path):
    _, document = _document(tmp_path)

    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="shape"):
        document.edit_rigid_bodies().set_shape(0, 99)
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="collision_group"):
        document.edit_rigid_bodies().set_collision(0, collision_group=-1)
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="collision_mask"):
        document.edit_rigid_bodies().set_collision(0, collision_mask=0x10000)
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="finite"):
        document.edit_rigid_bodies().set_physical_parameters(0, mass=float("nan"))
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="3 values"):
        document.edit_rigid_bodies().set_size(0, [1.0, 2.0])


def test_non_rigid_body_edits_and_collection_changes_are_rejected(tmp_path):
    _, document = _document(tmp_path)
    non_rigid_body = document.edit_rigid_bodies()
    non_rigid_body.model.header.name_jp = "not a Rigid Body edit"

    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="non-Rigid Body"):
        non_rigid_body.encode()

    reordered = document.edit_rigid_bodies()
    reordered.model.rigidbodies.reverse()
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="reorder"):
        reordered.encode()

    replaced = document.edit_rigid_bodies()
    replaced.model.rigidbodies[0] = replaced.model.rigidbodies[1]
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="replace"):
        replaced.encode()

    deleted = document.edit_rigid_bodies()
    deleted.model.rigidbodies.pop()
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="insert or delete"):
        deleted.encode()


def test_rigid_body_editor_requires_clean_document_and_isolates_source_model(
    tmp_path,
):
    _, document = _document(tmp_path)
    editor = document.edit_rigid_bodies().set_bone(0, -1)

    assert document.model.rigidbodies[0].bone_index == 0
    assert editor.model.rigidbodies[0].bone_index == -1

    document.model.rigidbodies[0].mass = 4.0
    with pytest.raises(pypmxvmd.PmxRigidBodyEditError, match="unmodified"):
        document.edit_rigid_bodies()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_rigid_body_edit_writes_only_to_tmp_and_preserves_source(
    pmx_path, tmp_path
):
    before_hash = _sha256(pmx_path)
    document = pypmxvmd.load_pmx_document(pmx_path)
    assert (
        document.model.rigidbodies
    ), f"required Rigid Body corpus is empty: {pmx_path}"
    original_name_en = document.model.rigidbodies[0].name_en
    edited_name_en = f"{original_name_en} W11b"
    editor = document.edit_rigid_bodies()
    editor.set_names(0, name_en=edited_name_en)
    output = tmp_path / pmx_path.name

    result = editor.write_file(output)
    reparsed = pypmxvmd.load_pmx(output)
    patch = result.patches[0]
    original_span = document.record_span_for("rigidbodies[0]")

    assert result.changed_record_count == 1
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original_span.end_offset :]
    )
    assert reparsed.rigidbodies[0].name_en == edited_name_en
    assert reparsed.is_complete
    assert _sha256(pmx_path) == before_hash
