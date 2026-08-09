"""Transactional W11d editing of existing PMX 2.0 Material records."""

import hashlib
import struct

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import PmxValidationError, SphMode, ToonSharing
from tests.test_corpus_parsers import corpus_cases
from tests.test_pmx_sections_reader import _index, _pmx_string


def _material_record(
    index_size,
    *,
    name,
    texture_index,
    sphere_texture_index,
    sphere_mode,
    toon_sharing,
    toon_texture_index,
    comment,
    face_count,
):
    data = bytearray()
    data.extend(_pmx_string(name))
    data.extend(_pmx_string(f"{name} EN"))
    data.extend(struct.pack("<4f", 0.8, 0.7, 0.6, 1.0))
    data.extend(struct.pack("<3ff3f", 0.1, 0.2, 0.3, 4.0, 0.2, 0.2, 0.2))
    data.extend(struct.pack("<B4ff", 0x15, 0.0, 0.0, 0.0, 1.0, 1.0))
    data.extend(_index(texture_index, index_size))
    data.extend(_index(sphere_texture_index, index_size))
    data.extend(struct.pack("<BB", sphere_mode, toon_sharing))
    if toon_sharing == int(ToonSharing.SEPARATE):
        data.extend(_index(toon_texture_index, index_size))
    else:
        data.extend(struct.pack("<B", toon_texture_index))
    data.extend(_pmx_string(comment))
    data.extend(struct.pack("<i", face_count))
    return bytes(data)


def _pmx20_with_two_materials(index_size=2):
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    data.extend(bytes((8, 1, 0, *([index_size] * 6))))
    for value in ("材質編集", "Material editing", "", ""):
        data.extend(_pmx_string(value))

    data.extend(struct.pack("<i", 3))
    for vertex_index in range(3):
        data.extend(
            struct.pack(
                "<3f3f2f",
                float(vertex_index),
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
            )
        )
        data.extend(struct.pack("<B", 0))
        data.extend(_index(0, index_size))
        data.extend(struct.pack("<f", 1.0))

    data.extend(struct.pack("<i", 3))
    for vertex_index in range(3):
        data.extend(_index(vertex_index, index_size, signed=False))

    data.extend(struct.pack("<i", 2))
    data.extend(_pmx_string("diffuse.png"))
    data.extend(_pmx_string("sphere.spa"))

    data.extend(struct.pack("<i", 2))
    data.extend(
        _material_record(
            index_size,
            name="材質0",
            texture_index=0,
            sphere_texture_index=1,
            sphere_mode=int(SphMode.MULTIPLY),
            toon_sharing=int(ToonSharing.SEPARATE),
            toon_texture_index=0,
            comment="first",
            face_count=3,
        )
    )
    data.extend(
        _material_record(
            index_size,
            name="材質1",
            texture_index=-1,
            sphere_texture_index=-1,
            sphere_mode=int(SphMode.DISABLED),
            toon_sharing=int(ToonSharing.SHARED),
            toon_texture_index=1,
            comment="second",
            face_count=0,
        )
    )

    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("センター"))
    data.extend(_pmx_string("Center"))
    data.extend(struct.pack("<3f", 0.0, 1.0, 0.0))
    data.extend(_index(-1, index_size))
    data.extend(struct.pack("<iH3f", 0, 0x001A, 0.0, 1.0, 0.0))

    data.extend(struct.pack("<i", 0))  # Morphs.
    data.extend(struct.pack("<i", 0))  # Display frames.
    data.extend(struct.pack("<i", 0))  # Rigid bodies.
    data.extend(struct.pack("<i", 0))  # Joints.
    return bytes(data)


def _document(tmp_path, index_size=2):
    path = tmp_path / f"materials-{index_size}.pmx"
    path.write_bytes(_pmx20_with_two_materials(index_size))
    return path, pypmxvmd.load_pmx_document(path)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_document_tracks_exact_complete_material_record_spans(tmp_path):
    _, document = _document(tmp_path)
    first = document.record_span_for("materials[0]")
    second = document.record_span_for("materials[1]")
    first_bone = document.record_span_for("bones[0]")

    assert first in document.record_spans
    assert second in document.record_spans
    assert first.start_offset < first.end_offset == second.start_offset
    assert second.end_offset < first_bone.start_offset
    assert (
        "材質0".encode("utf-8")
        in document.source_bytes[first.start_offset : first.end_offset]
    )


def test_noop_material_transaction_is_byte_identical(tmp_path):
    _, document = _document(tmp_path)

    result = document.edit_materials().encode()

    assert result.output_bytes is document.source_bytes
    assert result.patches == ()
    assert result.changed_record_count == 0


def test_material_editor_and_factory_are_public(tmp_path):
    _, document = _document(tmp_path)

    direct = pypmxvmd.edit_pmx_materials(document)

    assert isinstance(direct, pypmxvmd.PmxMaterialEditor)
    assert isinstance(direct.encode(), pypmxvmd.PmxMaterialEditResult)


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_variable_strings_and_texture_indices_replace_only_one_record(
    tmp_path, index_size
):
    _, document = _document(tmp_path, index_size)
    original = document.record_span_for("materials[0]")
    editor = document.edit_materials()
    editor.set_names(0, name_jp="長い材質名", name_en="Long material name")
    editor.set_comment(0, "long material comment")
    editor.set_texture(0, -1)
    editor.set_sphere_texture(0, 0, SphMode.ADDITIVE)
    editor.set_separate_toon(0, 1)

    result = editor.encode()
    patch = result.patches[0]
    material = result.model.materials[0]

    assert result.changed_record_count == 1
    assert patch.offset == original.start_offset
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original.end_offset :]
    )
    assert material.name_jp == "長い材質名"
    assert material.comment == "long material comment"
    assert material.texture_index == -1
    assert material.texture_path == ""
    assert material.sphere_texture_index == 0
    assert material.sphere_path == "diffuse.png"
    assert material.sphere_mode is SphMode.ADDITIVE
    assert material.toon_texture_index == 1
    assert material.toon_path == "sphere.spa"
    assert result.model.materials[1].name_jp == document.model.materials[1].name_jp


def test_colors_draw_flags_edge_and_comment_round_trip(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_materials()
    editor.set_diffuse_color(0, [0.1, 0.2, 0.3, 0.4])
    editor.set_specular(0, color=[0.5, 0.6, 0.7], strength=8.0)
    editor.set_ambient_color(0, [0.8, 0.9, 1.0])
    editor.set_draw_flags(
        0,
        double_sided=True,
        ground_shadow=True,
        self_shadow_map=False,
        self_shadow=True,
        edge_drawing=True,
        vertex_color=True,
        point_drawing=False,
        line_drawing=True,
    )
    editor.set_edge(0, color=[0.9, 0.8, 0.7, 0.6], size=2.5)
    editor.set_comment(0, "all fields")

    material = editor.encode().model.materials[0]

    assert material.diffuse_color == pytest.approx([0.1, 0.2, 0.3, 0.4])
    assert material.specular_color == pytest.approx([0.5, 0.6, 0.7])
    assert material.specular_strength == pytest.approx(8.0)
    assert material.ambient_color == pytest.approx([0.8, 0.9, 1.0])
    assert material.flags.value == 0xBB
    assert material.edge_color == pytest.approx([0.9, 0.8, 0.7, 0.6])
    assert material.edge_size == pytest.approx(2.5)
    assert material.comment == "all fields"


@pytest.mark.parametrize("sphere_mode", list(SphMode))
def test_all_sphere_modes_round_trip(tmp_path, sphere_mode):
    _, document = _document(tmp_path)

    material = (
        document.edit_materials()
        .set_sphere_texture(0, 1, sphere_mode)
        .encode()
        .model.materials[0]
    )

    assert material.sphere_mode is sphere_mode
    assert material.sphere_texture_index == 1
    assert material.sphere_path == "sphere.spa"


@pytest.mark.parametrize("toon_index", range(10))
def test_all_shared_toon_indices_round_trip(tmp_path, toon_index):
    _, document = _document(tmp_path)

    material = (
        document.edit_materials()
        .set_shared_toon(0, toon_index)
        .encode()
        .model.materials[0]
    )

    assert material.toon_sharing is ToonSharing.SHARED
    assert material.toon_texture_index == toon_index
    assert material.toon_path == f"toon{toon_index + 1:02d}.bmp"


def test_all_texture_reference_sentinels_round_trip(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_materials()
    editor.set_texture(0, -1)
    editor.set_sphere_texture(0, -1, SphMode.DISABLED)
    editor.set_separate_toon(0, -1)

    material = editor.encode().model.materials[0]

    assert material.texture_index == -1
    assert material.texture_path == ""
    assert material.sphere_texture_index == -1
    assert material.sphere_path == ""
    assert material.toon_texture_index == -1
    assert material.toon_path == ""


def test_sync_ambient_from_diffuse_is_explicit_only(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_materials().set_diffuse_color(0, [0.3, 0.4, 0.5, 0.6])

    unsynced = editor.encode().model.materials[0]
    assert unsynced.ambient_color == pytest.approx([0.2, 0.2, 0.2])

    editor.sync_ambient_from_diffuse(0)
    synced = editor.encode().model.materials[0]
    assert synced.ambient_color == pytest.approx([0.3, 0.4, 0.5])


def test_both_toon_layout_transitions_round_trip(tmp_path):
    _, document = _document(tmp_path, 4)
    editor = document.edit_materials()
    editor.set_shared_toon(0, 9)
    editor.set_separate_toon(1, 0)

    result = editor.encode()
    first, second = result.model.materials

    assert result.changed_record_count == 2
    assert first.toon_sharing is ToonSharing.SHARED
    assert first.toon_texture_index == 9
    assert first.toon_path == "toon10.bmp"
    assert second.toon_sharing is ToonSharing.SEPARATE
    assert second.toon_texture_index == 0
    assert second.toon_path == "diffuse.png"


def test_face_counts_are_updated_as_one_validated_collection(tmp_path):
    _, document = _document(tmp_path)

    result = document.edit_materials().set_face_counts([0, 3]).encode()

    assert result.changed_record_count == 2
    assert [material.face_count for material in result.model.materials] == [0, 3]


@pytest.mark.parametrize(
    "invalid_edit",
    [
        lambda editor: setattr(editor.model.materials[0], "texture_index", 99),
        lambda editor: setattr(editor.model.materials[0], "sphere_mode", 99),
        lambda editor: setattr(editor.model.materials[0], "toon_sharing", 99),
        lambda editor: setattr(editor.model.materials[0], "flags", "invalid"),
        lambda editor: editor.model.materials[0].diffuse_color.__setitem__(
            0, float("nan")
        ),
        lambda editor: setattr(editor.model.materials[0], "edge_size", 1e100),
        lambda editor: setattr(editor.model.materials[0], "face_count", 6),
        lambda editor: setattr(editor.model.materials[0], "texture_path", "stale"),
    ],
)
def test_invalid_reference_enum_flags_numbers_counts_and_paths_preserve_target(
    tmp_path, invalid_edit
):
    _, document = _document(tmp_path)
    target = tmp_path / "existing.pmx"
    target.write_bytes(b"keep")
    editor = document.edit_materials()
    invalid_edit(editor)

    with pytest.raises(PmxValidationError):
        editor.write_file(target)

    assert target.read_bytes() == b"keep"


def test_invalid_argument_types_ranges_and_face_counts_fail_closed(tmp_path):
    _, document = _document(tmp_path)

    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="4 values"):
        document.edit_materials().set_diffuse_color(0, [1.0, 1.0, 1.0])
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="at least one"):
        document.edit_materials().set_specular(0)
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="finite"):
        document.edit_materials().set_edge(0, size=float("nan"))
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="bool"):
        document.edit_materials().set_draw_flags(0, double_sided=1)
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="texture_index"):
        document.edit_materials().set_texture(0, 99)
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="sphere_mode"):
        document.edit_materials().set_sphere_texture(0, 0, 4)
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="0..9"):
        document.edit_materials().set_shared_toon(0, 10)
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="2 values"):
        document.edit_materials().set_face_counts([3])
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="multiple of 3"):
        document.edit_materials().set_face_counts([1, 2])
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="sum to 3"):
        document.edit_materials().set_face_counts([3, 3])


def test_non_material_edits_and_material_collection_changes_are_rejected(tmp_path):
    _, document = _document(tmp_path)
    non_material = document.edit_materials()
    non_material.model.bones[0].name_en = "not a Material edit"

    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="non-Material"):
        non_material.encode()

    reordered = document.edit_materials()
    reordered.model.materials.reverse()
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="reorder"):
        reordered.encode()

    replaced = document.edit_materials()
    replaced.model.materials[0] = replaced.model.materials[1]
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="replace"):
        replaced.encode()

    deleted = document.edit_materials()
    deleted.model.materials.pop()
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="insert or delete"):
        deleted.encode()


def test_material_editor_requires_clean_document_and_isolates_source_model(tmp_path):
    _, document = _document(tmp_path)
    editor = document.edit_materials().set_comment(0, "edited")

    assert document.model.materials[0].comment == "first"
    assert editor.model.materials[0].comment == "edited"

    document.model.materials[0].specular_strength = 9.0
    with pytest.raises(pypmxvmd.PmxMaterialEditError, match="unmodified"):
        document.edit_materials()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_material_edit_writes_only_to_tmp_and_preserves_source(
    pmx_path, tmp_path
):
    before_hash = _sha256(pmx_path)
    document = pypmxvmd.load_pmx_document(pmx_path)
    assert document.model.materials, f"required Material corpus is empty: {pmx_path}"
    original_name_en = document.model.materials[0].name_en
    original_comment = document.model.materials[0].comment
    editor = document.edit_materials()
    editor.set_names(0, name_en=f"{original_name_en} W11d")
    editor.set_comment(0, f"{original_comment} W11d")
    output = tmp_path / pmx_path.name

    result = editor.write_file(output)
    reparsed = pypmxvmd.load_pmx(output)
    patch = result.patches[0]
    original_span = document.record_span_for("materials[0]")

    assert result.changed_record_count == 1
    assert len(patch.after) > len(patch.before)
    assert result.output_bytes[: patch.offset] == document.source_bytes[: patch.offset]
    assert result.output_bytes[patch.offset + len(patch.after) :] == (
        document.source_bytes[original_span.end_offset :]
    )
    assert reparsed.materials[0].name_en == f"{original_name_en} W11d"
    assert reparsed.materials[0].comment == f"{original_comment} W11d"
    assert reparsed.is_complete
    assert _sha256(pmx_path) == before_hash
