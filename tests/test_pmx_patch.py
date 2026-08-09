"""Fixed-width PMX lossless patch safety and semantic whitelist tests."""

from copy import deepcopy

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import BinaryPatch, PmxPatchError
from tests.test_pmx_sections_reader import _pmx20_all_sections


def _document(tmp_path):
    path = tmp_path / "source.pmx"
    path.write_bytes(_pmx20_all_sections(2)[0])
    return pypmxvmd.load_pmx_document(path)


def _changed_offsets(before, after):
    return {
        index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]
    }


@pytest.mark.parametrize(
    ("field_path", "edit"),
    [
        (
            "materials[0].specular_strength",
            lambda model: setattr(model.materials[0], "specular_strength", 8.5),
        ),
        (
            "bones[0].deform_layer",
            lambda model: setattr(model.bones[0], "deform_layer", 2),
        ),
        (
            "rigidbodies[0].mass",
            lambda model: setattr(model.rigidbodies[0], "mass", 1.25),
        ),
        (
            "joints[0].position",
            lambda model: setattr(model.joints[0], "position", [2.0, 3.0, 4.0]),
        ),
    ],
)
def test_single_field_patch_changes_only_registered_span_and_strict_reparses(
    tmp_path, field_path, edit
):
    document = _document(tmp_path)
    edit(document.model)

    patches = document.build_patches()
    encoded = document.encode_lossless()
    span = document.span_for(field_path)
    changed = _changed_offsets(document.source_bytes, encoded)
    output = tmp_path / "patched.pmx"
    output.write_bytes(encoded)
    reparsed = pypmxvmd.load_pmx(output)

    assert len(patches) == 1
    assert patches[0].offset == span.start_offset
    assert (
        patches[0].before == document.source_bytes[span.start_offset : span.end_offset]
    )
    assert changed
    assert changed <= set(range(span.start_offset, span.end_offset))
    assert reparsed.is_complete


def test_make_patch_enforces_registered_path_and_declared_value_type(tmp_path):
    document = _document(tmp_path)

    patch = document.make_patch("bones[0].deform_layer", 3)

    assert patch.description == "set bones[0].deform_layer"
    with pytest.raises(PmxPatchError, match="Unknown or variable-length"):
        document.make_patch("bones[0].name_jp", "renamed")
    with pytest.raises(PmxPatchError, match="requires an integer"):
        document.make_patch("bones[0].deform_layer", "three")


def test_before_mismatch_fails_before_target_replacement(tmp_path):
    document = _document(tmp_path)
    valid = document.make_patch("bones[0].deform_layer", 3)
    invalid = BinaryPatch(valid.offset, b"\xff" * len(valid.before), valid.after)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")

    with pytest.raises(PmxPatchError, match="before bytes"):
        document.apply_patches([invalid])

    assert target.read_bytes() == b"keep"


def test_overlap_out_of_bounds_and_length_change_fail_closed(tmp_path):
    document = _document(tmp_path)
    patch = document.make_patch("bones[0].deform_layer", 3)

    with pytest.raises(PmxPatchError, match="overlap"):
        document.apply_patches([patch, patch])
    with pytest.raises(PmxPatchError, match="outside"):
        document.apply_patches([BinaryPatch(len(document.source_bytes), b"x", b"y")])
    with pytest.raises(PmxPatchError, match="preserve field byte length"):
        document.apply_patches(
            [BinaryPatch(patch.offset, patch.before, patch.after + b"x")]
        )


def test_unregistered_range_and_strict_reparse_failure_fail_closed(tmp_path):
    document = _document(tmp_path)
    target = tmp_path / "must-not-exist.pmx"
    joint_type = document.span_for("joints[0].joint_type")

    with pytest.raises(PmxPatchError, match="not a registered"):
        document.apply_patches([BinaryPatch(0, b"P", b"Q")])
    with pytest.raises(PmxPatchError, match="failed strict reparse"):
        document.apply_patches(
            [
                BinaryPatch(
                    joint_type.start_offset,
                    document.source_bytes[
                        joint_type.start_offset : joint_type.end_offset
                    ],
                    b"\xff",
                )
            ]
        )

    assert not target.exists()


def test_variable_length_and_unregistered_model_edits_are_rejected(tmp_path):
    document = _document(tmp_path)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")
    document.model.bones[0].name_jp = "a different encoded length"

    with pytest.raises(PmxPatchError, match="not registered"):
        pypmxvmd.save_pmx(document, target, mode="lossless_patch")

    assert target.read_bytes() == b"keep"


def test_fixed_patch_plus_unregistered_semantic_change_is_rejected(tmp_path):
    document = _document(tmp_path)
    original = deepcopy(document.model)
    document.model.bones[0].deform_layer = 2
    document.model.materials[0].comment = "untracked"

    with pytest.raises(PmxPatchError, match="semantics differ"):
        document.encode_lossless()

    assert original.bones[0].deform_layer == 0
