"""W10 legacy fixed-width patch bridge and dual-write contracts."""

import struct
from pathlib import Path

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import LegacyPatchRecord, PmxPatchError
from tests.test_corpus_parsers import corpus_cases
from tests.test_pmx_integrity import _minimal_complete_pmx21_bytes
from tests.test_pmx_sections_reader import _pmx20_all_sections


def _document(tmp_path: Path, *, index_size: int = 1):
    """Build a complete source with the requested signed index width.

    ``PmxWriter`` intentionally chooses the smallest canonical width, so a
    model header requesting 2/4-byte indexes is not sufficient to exercise
    the legacy adapter.  Start from the binary all-sections fixture and add a
    child bone directly, preserving the fixture's explicit width flags.
    """
    source = tmp_path / "source.pmx"
    payload, _ = _pmx20_all_sections(index_size)
    source.write_bytes(payload)
    base = pypmxvmd.load_pmx_document(source)
    bone_span = next(span for span in base.record_spans if span.name == "bones[0]")
    parent_span = base.span_for("bones[0].parent_index")
    child_record = bytearray(payload[bone_span.start_offset : bone_span.end_offset])
    relative_start = parent_span.start_offset - bone_span.start_offset
    relative_end = parent_span.end_offset - bone_span.start_offset
    child_record[relative_start:relative_end] = parent_span.encode(0)

    expanded = bytearray(payload)
    count_offset = bone_span.start_offset - 4
    expanded[count_offset : count_offset + 4] = struct.pack("<i", 2)
    expanded[bone_span.end_offset : bone_span.end_offset] = child_record
    source.write_bytes(expanded)
    return pypmxvmd.load_pmx_document(source)


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_arm_ik_parent_record_dual_write_matches_lossless(tmp_path, index_size):
    document = _document(tmp_path, index_size=index_size)
    assert document.model.header.bone_index_size == index_size
    assert document.span_for("bones[1].parent_index").size == index_size
    document.model.bones[1].parent_index = -1
    record = pypmxvmd.make_legacy_bone_parent_patch(document, 1, -1)

    audit = pypmxvmd.dual_write_legacy_patches(document, [record])

    assert audit.outputs_match
    assert audit.field_paths == ("bones[1].parent_index",)
    assert audit.legacy_bytes == audit.lossless_bytes
    assert audit.output_sha256 != audit.source_sha256
    assert audit.to_dict()["outputs_match"] is True


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_legacy_json_record_without_field_path_maps_by_exact_span(tmp_path, index_size):
    document = _document(tmp_path, index_size=index_size)
    document.model.bones[1].parent_index = -1
    record = pypmxvmd.make_legacy_bone_parent_patch(document, 1, -1)
    manifest_record = record.to_dict()

    adapted = pypmxvmd.adapt_legacy_patches(document, [manifest_record])

    assert len(adapted) == 1
    assert adapted[0].offset == record.offset
    assert adapted[0].before == record.before


def test_legacy_dual_write_requires_document_model_edit(tmp_path):
    document = _document(tmp_path)
    record = pypmxvmd.make_legacy_bone_parent_patch(document, 1, -1)

    with pytest.raises(PmxPatchError, match="encode_lossless"):
        pypmxvmd.dual_write_legacy_patches(document, [record])


def test_legacy_field_allowlist_rejects_other_registered_fields(tmp_path):
    document = _document(tmp_path)
    span = document.span_for("bones[1].deform_layer")
    record = LegacyPatchRecord(
        offset=span.start_offset,
        before=document.source_bytes[span.start_offset : span.end_offset],
        after=span.encode(2),
        field_path=str(span.field_path),
    )

    with pytest.raises(PmxPatchError, match="allowlist"):
        pypmxvmd.adapt_legacy_patches(document, [record])


def test_legacy_patch_checks_field_range_before_bytes_and_overlap(tmp_path):
    document = _document(tmp_path)
    valid = pypmxvmd.make_legacy_bone_parent_patch(document, 1, -1)

    with pytest.raises(PmxPatchError, match="offset/length"):
        pypmxvmd.adapt_legacy_patches(
            document,
            [
                LegacyPatchRecord(
                    offset=valid.offset + 1,
                    before=valid.before,
                    after=valid.after,
                    field_path=valid.field_path,
                )
            ],
        )
    with pytest.raises(PmxPatchError, match="before bytes"):
        pypmxvmd.adapt_legacy_patches(
            document,
            [
                LegacyPatchRecord(
                    offset=valid.offset,
                    before=b"\x7f" * len(valid.before),
                    after=valid.after,
                    field_path=valid.field_path,
                )
            ],
        )
    with pytest.raises(PmxPatchError, match="overlap"):
        pypmxvmd.adapt_legacy_patches(document, [valid, valid])


def test_legacy_patch_rejects_variable_length_and_unregistered_ranges(tmp_path):
    document = _document(tmp_path)
    with pytest.raises(ValueError, match="preserve byte length"):
        LegacyPatchRecord(offset=0, before=b"a", after=b"ab")
    with pytest.raises(PmxPatchError, match="not a registered"):
        pypmxvmd.adapt_legacy_patches(
            document,
            [LegacyPatchRecord(offset=0, before=b"P", after=b"Q")],
        )


def test_legacy_patch_rejects_pm21_before_mapping(tmp_path):
    source = tmp_path / "pmx21.pmx"
    source.write_bytes(_minimal_complete_pmx21_bytes())
    document = pypmxvmd.load_pmx_document(source)

    with pytest.raises(PmxPatchError, match="PMX versions 2.0"):
        pypmxvmd.adapt_legacy_patches(
            document,
            [LegacyPatchRecord(offset=0, before=b"PMX ", after=b"PMX ")],
        )


def test_legacy_patch_rejects_malformed_field_path_as_patch_error(tmp_path):
    document = _document(tmp_path)
    record = pypmxvmd.make_legacy_bone_parent_patch(document, 1, -1)
    malformed = LegacyPatchRecord(
        offset=record.offset,
        before=record.before,
        after=record.after,
        field_path="bones[-1].parent_index",
    )

    with pytest.raises(PmxPatchError, match="not a registered"):
        pypmxvmd.adapt_legacy_patches(document, [malformed])


def test_legacy_bone_parent_helper_rejects_negative_bone_index(tmp_path):
    document = _document(tmp_path)

    with pytest.raises(ValueError, match="cannot be negative"):
        pypmxvmd.make_legacy_bone_parent_patch(document, -1, -1)


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_parent_patch_dual_write_is_in_memory_only(pmx_path):
    """Exercise the bridge against each authorized local PMX source snapshot."""
    document = pypmxvmd.load_pmx_document(pmx_path)
    if document.model.header.version != 2.0:
        pytest.skip("legacy bridge is intentionally limited to PMX 2.0")

    candidate = next(
        (
            index
            for index, bone in enumerate(document.model.bones)
            if index > 0 and bone.parent_index >= 0
        ),
        None,
    )
    if candidate is None:
        pytest.skip("corpus has no parented bone suitable for a safe smoke patch")

    document.model.bones[candidate].parent_index = -1
    record = pypmxvmd.make_legacy_bone_parent_patch(document, candidate, -1)
    audit = pypmxvmd.dual_write_legacy_patches(document, [record])

    assert audit.outputs_match
    assert audit.output_sha256 != audit.source_sha256
    assert audit.field_paths == (f"bones[{candidate}].parent_index",)
