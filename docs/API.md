# PyPMXVMD API Documentation

PyPMXVMD is a Python library for parsing and modifying MikuMikuDance (MMD) files.

**Version**: 2.7.1
**Python**: >= 3.8
**Acceleration**: Optional Cython fast path for parsing and binary I/O with automatic fallback.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Top-Level API](#top-level-api)
- [Data Models](#data-models)
  - [VMD Models](#vmd-models)
  - [PMX Models](#pmx-models)
  - [VPD Models](#vpd-models)
- [Parsers](#parsers)
- [Enums](#enums)
- [Examples](#examples)
- [Error Handling](#error-handling)
- [Compatibility](#compatibility)
- [License](#license)

---

## Quick Start

### Install

```bash
uv add pypmxvmd
```

### Basic Usage

```python
import pypmxvmd

# Auto-detect file type and load
motion = pypmxvmd.load("motion.vmd")

# Save
pypmxvmd.save(motion, "output.vmd")
```

---

## Top-Level API

PyPMXVMD provides concise top-level helpers for loading and saving files.

### Binary Files

#### `pypmxvmd.load(file_path, more_info=False, *, mode=None, implementation="auto", strict_eof=None, track_spans=False)`

Auto-detect the file type and load it.

**Args**:
- `file_path` (str | Path): File path
- `more_info` (bool): Whether to print detailed parsing info
- `mode`, `implementation`, `strict_eof`, `track_spans`: PMX-only options

**Returns**: `VmdMotion` | `PmxModel` | `PmxParseResult` | `VpdPose`

**Raises**: `ValueError` - Unsupported file type

```python
data = pypmxvmd.load("motion.vmd")
```

---

#### `pypmxvmd.save(data, file_path, *, mode=None)`

Auto-detect the data type and save it.

**Args**:
- `data`: `VmdMotion` | `PmxModel` | `VpdPose`
- `file_path` (str | Path): Output path
- `mode`: PMX-only output mode; defaults to `canonical`

```python
pypmxvmd.save(model, "output.pmx")
```

---

#### `pypmxvmd.load_vmd(file_path, more_info=False) -> VmdMotion`

Load a VMD motion file.

---

#### `pypmxvmd.save_vmd(motion, file_path)`

Save a VMD motion file.

---

#### `pypmxvmd.load_pmx(file_path, more_info=False, *, mode="strict", implementation="auto", strict_eof=None, track_spans=False)`

`mode="strict"` returns a complete `PmxModel` and always requires exact EOF.
`mode="partial"` returns `PmxParseResult`; set `strict_eof=True` if the caller
wants a result object only when it is complete. `implementation` accepts `auto`,
`python`, `fast`, or `cython`. `mode="document"` or `track_spans=True` returns a
source-backed `PmxDocument`; partial span tracking populates
`PmxParseResult.field_spans`.

PMX 2.0 is parsed through Spring 6DOF Joint. PMX 2.1 additionally supports QDEF,
Flip/Impulse Morph, all six Joint types, and the complete Soft Body record through
Anchor and Pin collections. Unknown enum values, invalid counts/references,
truncation, and trailing bytes fail closed.

```python
model = pypmxvmd.load_pmx("model.pmx")
result = pypmxvmd.load_pmx("model.pmx", mode="partial")
document = pypmxvmd.load_pmx("model.pmx", mode="document")
print(result.report.missing_sections)
```

---

#### `pypmxvmd.load_pmx_partial(file_path, more_info=False, implementation="auto", *, track_spans=False) -> PmxParseResult`

Explicitly load with `python`, `fast`, or `cython`. The result contains `model`
and an immutable `report` with loaded and missing sections, section byte spans,
final offset, file size and trailing byte count. Supported PMX 2.0/2.1 files can
both report `is_complete=True`. `auto` uses the bounds-checked Python Cursor.
Until the native ABI is completed, explicit `cython` returns the Cursor's
canonical semantic model; PMX 2.1 does not enter the incomplete native parser.
This legacy-compatible
helper is equivalent to `load_pmx(..., mode="partial")`. With
`track_spans=True`, `field_spans` contains the registered fixed-width fields and
`record_spans` contains exact existing Vertex, Face, Material, Bone, Morph,
Display Frame, Rigid Body, and Joint record ranges.

---

#### `pypmxvmd.load_pmx_document(file_path, more_info=False, *, implementation="auto", track_spans=True) -> PmxDocument`

Strict-load an immutable source snapshot, canonical model, parse report, section
evidence, fixed-width field spans, and exact existing Vertex/Face/Material/Bone/
Morph/Display Frame/Rigid Body/Joint record spans. The first
lossless stage registers selected directly mapped numeric, enum, index, flags, and
vector fields in existing Material, Bone, Rigid Body, and Joint records. Their
record spans support the W11a-W11d transactions; the additional record spans are
used as W12 source evidence. Soft Body records are not registered for editing.

```python
document = pypmxvmd.load_pmx_document("model.pmx")
span = document.span_for("bones[0].deform_layer")
document.model.bones[0].deform_layer = 2
pypmxvmd.save_pmx(document, "patched.pmx", mode="lossless_patch")
```

Lossless writing checks the model, exact `before` bytes, source bounds, fixed
length, non-overlap and registered field type before writing. It then strict-
reparses the patched bytes and compares the entire semantic model. A no-op write
returns the exact original bytes. Unsupported edits raise `PmxPatchError` before
the target is created or replaced.

---

#### `PmxDocument.edit_bones() -> PmxBoneEditor` / `pypmxvmd.edit_pmx_bones(document)`

Create an isolated transaction for editing existing PMX 2.0 Bone records. The
editor supports variable-length Japanese/English names, position, parent,
deform layer, rotatable/translatable/visible/enabled/after-physics flags, both
tail modes, rotation/translation/local inheritance, fixed and local axes,
external parent, and complete IK target/loop/angle/link/limit data.

```python
document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_bones()
editor.set_names(0, name_en="center")
editor.set_deform_layer(0, 2)  # PMXEditor "deform hierarchy"
editor.set_tail_bone(0, 1)     # or set_tail_offset(0, [0.0, 1.0, 0.0])
editor.set_ik(
    0,
    target_index=1,
    loop_count=40,
    angle_limit=0.5,  # radians
    links=[pypmxvmd.ik_link(1)],
)
result = editor.write_file("bone-edited.pmx")
print(result.changed_record_count)
```

Conditional flags and their payloads must be changed through the paired
`set_*`/`clear_*` methods. `encode()` returns a verified `PmxBoneEditResult`
without writing; `write_file()` verifies and atomically replaces the target.
Every transaction starts from a clean `PmxDocument`, rebuilds only changed Bone
records using the source encoding and Bone index width, validates the complete
model, strict-reparses the candidate bytes, and compares all model semantics.
Bone insertion, deletion, object replacement/reordering, and global index
renumbering are outside W11a and raise `PmxBoneEditError`.

---

#### `PmxDocument.edit_rigid_bodies() -> PmxRigidBodyEditor` / `pypmxvmd.edit_pmx_rigid_bodies(document)`

Create an isolated transaction for editing existing PMX 2.0 Rigid Body records.
The editor supports variable-length Japanese/English names, Bone references
including the `-1` sentinel, all sphere/box/capsule shapes, all three physics
modes, raw collision group/mask, size/position/rotation (rotation remains in
radians), and mass/move damping/rotation damping/repulsion/friction.

```python
from pypmxvmd.common.pmx import RigidBodyShape

document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_rigid_bodies()
editor.set_names(0, name_en="body")
editor.set_bone(0, -1)
editor.set_shape(0, RigidBodyShape.CAPSULE)
editor.set_collision(0, collision_group=3, collision_mask=0xFFF7)
editor.set_rotation(0, [0.0, 0.25, 0.0])  # radians
editor.set_physical_parameters(0, mass=1.5, friction=0.6)
result = editor.write_file("rigid-body-edited.pmx")
print(result.changed_record_count)
```

`encode()` returns a verified `PmxRigidBodyEditResult` without writing;
`write_file()` validates and atomically replaces the target. The transaction
uses the source encoding and Bone index width, rebuilds only changed Rigid Body
records, strict-reparses the complete output, and compares all model semantics.
Rigid Body insertion, deletion, object replacement/reordering, and global index
renumbering are outside W11b and raise `PmxRigidBodyEditError`; existing Joint
Rigid Body indices therefore retain their meaning.

---

#### `PmxDocument.edit_joints() -> PmxJointEditor` / `pypmxvmd.edit_pmx_joints(document)`

Create an isolated transaction for editing existing PMX 2.0 Spring 6DOF Joint
records. It supports variable-length Japanese/English names, the Joint type,
Rigid Body A/B references including the `-1` sentinel, position/rotation,
translation/rotation min/max limits, and translation/rotation springs. Rotation
values and rotation springs remain in the raw radians-based PMX representation.

```python
from pypmxvmd.common.pmx import JointType

document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_joints()
editor.set_names(0, name_en="spring joint")
editor.set_joint_type(0, JointType.SPRING6DOF)
editor.set_rigid_body_references(0, -1, 1)
editor.set_position_limits(0, [-1.0, -2.0, -3.0], [1.0, 2.0, 3.0])
editor.set_rotation_limits(0, [-0.5, -0.25, -0.1], [0.5, 0.25, 0.1])
editor.set_rotation_spring(0, [0.2, 0.3, 0.4])
result = editor.write_file("joint-edited.pmx")
print(result.changed_record_count)
```

`encode()` returns a verified `PmxJointEditResult`; `write_file()` validates and
atomically replaces the target. The transaction uses the source encoding and
Rigid Body index width, rebuilds only changed Joint records, strict-reparses the
complete output, and compares all model semantics. Limit setters require
component-wise `minimum <= maximum`. Direct model edits are also checked, but
unchanged inverted axes already present in legacy source files are preserved so
that unrelated Joint edits remain possible. Joint insertion, deletion, object
replacement/reordering, and PMX 2.1 Joint types are outside W11c and raise
`PmxJointEditError` or the existing unsupported-feature error.

---

#### `PmxDocument.edit_materials() -> PmxMaterialEditor` / `pypmxvmd.edit_pmx_materials(document)`

Create an isolated transaction for editing existing PMX 2.0 Material records.
The editor supports variable-length Japanese/English names and comments,
diffuse RGBA, specular RGB/strength, ambient RGB, all eight draw flags, edge
RGBA/size, Texture references, Sphere references and all four modes, separate or
shared Toon layouts, and raw face-index counts.

```python
from pypmxvmd.common.pmx import SphMode

document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_materials()
editor.set_names(0, name_en="skin")
editor.set_diffuse_color(0, [0.8, 0.6, 0.5, 1.0])
editor.sync_ambient_from_diffuse(0)  # explicit S3 command
editor.set_draw_flags(0, double_sided=True, edge_drawing=True)
editor.set_sphere_texture(0, -1, SphMode.DISABLED)
editor.set_shared_toon(0, 0)  # built-in toon01.bmp
result = editor.write_file("material-edited.pmx")
print(result.changed_record_count)
```

`set_texture()`, `set_sphere_texture()`, `set_separate_toon()`, and
`set_shared_toon()` keep the display paths synchronized with their serialized
indices and validate `-1` sentinels/ranges. `set_face_counts()` takes the complete
Material count sequence so every value remains a non-negative multiple of three
and the total still equals the model's face-index count. Ambient color is never
implicitly synchronized; only `sync_ambient_from_diffuse()` changes it.

`encode()` returns a verified `PmxMaterialEditResult`; `write_file()` validates
and atomically replaces the target. Only changed Material records are rebuilt
using the source encoding and Texture index width, then the complete output is
strict-reparsed and semantically compared. Material/texture-table insertion,
deletion, object replacement/reordering, and global renumbering are outside W11d
and raise `PmxMaterialEditError` or a validation error.

---

#### W12 collection editors: Vertex, Face, Morph, and Display Frame

The following factories create isolated collection-level transactions:

- `PmxDocument.edit_vertices()` / `pypmxvmd.edit_pmx_vertices(document)`
- `PmxDocument.edit_faces()` / `pypmxvmd.edit_pmx_faces(document)`
- `PmxDocument.edit_morphs()` / `pypmxvmd.edit_pmx_morphs(document)`
- `PmxDocument.edit_frames()` / `pypmxvmd.edit_pmx_frames(document)`

`PmxVertexEditor` edits geometry, Additional UV values, BDEF1/BDEF2/BDEF4/SDEF/
QDEF weights, SDEF vectors, edge scale, and Bone weight indices. Vertex insert,
delete, and reorder operations remap Face, Vertex/UV Morph, and Soft Body
Anchor/Pin references; deletion also removes dependent faces/items and updates
Material face counts.

`PmxFaceEditor` edits, inserts, deletes, and reorders triangles. Insert/delete
operations keep contiguous Material face ranges and `face_count` values in sync;
`remap_vertex_indices()` applies an explicit Vertex mapping. Reordering that
would interleave Material ranges is rejected.

`PmxMorphEditor` edits names, panels, and item collections for all PMX 2.0 Morph
types plus PMX 2.1 Flip/Impulse. Morph insert/delete/reorder remaps Group/Flip and
Display Frame references and removes references to an explicitly deleted Morph.

`PmxFrameEditor` edits names, item collections, and frame collections. Bone/Morph
items are validated after every transaction; no newly special frame may appear
after the first two positions.

```python
document = pypmxvmd.load_pmx_document("model.pmx")

vertices = document.edit_vertices()
vertices.set_edge_scale(0, 1.5)
vertices.write_file("vertex-edited.pmx")

faces = document.edit_faces()
faces.append_face([0, 2, 3], material_index=0)
faces.write_file("face-edited.pmx")
```

`encode()` returns the corresponding `Pmx*EditResult`; `write_file()` validates,
strict-reparses, semantically compares, and atomically replaces the target. A
no-op returns the exact source bytes. A changed W12 transaction uses canonical
whole-model encoding so index widths can grow safely; it preserves semantics
outside the declared edit, but does not promise source-byte or source-layout
equality. Invalid scope, reference, ordering, or field changes raise the matching
`PmxVertexEditError`, `PmxFaceEditError`, `PmxMorphEditError`, or
`PmxFrameEditError`. Soft Body record editing remains unsupported.

#### `pypmxvmd.edit_pmx(source, *, output_path=None) -> PmxEditTransaction`

Create one model-level transaction for composing operations that change several
PMX collections. `source` accepts a `PmxModel`, `PmxDocument`, or a PMX path.
All edits are made on a deep copy. Normal `with` exit validates the whole model,
canonical-encodes it, strict-reparses it, and atomically writes `output_path`;
an exception rolls back and leaves the target untouched. A path source cannot be
written back to itself.

```python
from pypmxvmd.common.pmx import MorphPanel

with pypmxvmd.edit_pmx("body.pmx", output_path="skirt.pmx") as tx:
    skirt_bone = tx.add_bone(name_jp="裙骨", parent_index=0)
    tx.paint_weights([120, 121, 122], skirt_bone, 0.8)
    tx.add_vertex_morph(
        name_jp="裙摆",
        offsets={120: [0.0, 0.15, 0.0]},
        panel=MorphPanel.OTHER,
        display_frame_index=1,
    )
    tx.merge_part("clothes.pmx")

result = tx.result
assert result is not None
```

`add_bone()`/`append_bone()` append a validated Bone and return its index.
`bone(index)` returns the transaction-local Bone so existing fields can be
modified inside the same `with` block; the final commit validates all conditional
fields and references together.
`set_weight()` accepts explicit BDEF1/BDEF2/BDEF4/SDEF/QDEF layouts; QDEF is
restricted to PMX 2.1. `paint_weights()`/`set_vertex_weights()` paint a target
bone over a vertex collection, preserving the strongest previous influence as
the complementary BDEF2 weight by default. `add_morph()` accepts a typed
`PmxMorph`; `add_vertex_morph()` is a vertex-offset convenience API and can add
the new morph to a Display Frame so PMXEditor can show it in the T panel.

`merge_part()` is atomic within the open transaction: a rejected part restores the
transaction-local model, even when the caller catches the exception. It remaps
Vertex, Texture, Material, Bone, Morph, Rigid Body, Joint,
Soft Body, Morph item, and Display Frame references. Bones are matched by
Japanese/English name; other records are appended. It returns the core applied
index mappings. Display Frames are included by default; pass `include_frames=False`
only when the part has no frames. Version upgrades, invalid references, or any
unsafe structure fail with `PmxTransactionError` instead of dropping data.

`remove_part()`/`remove_materials()` remove one or more material-defined parts, and
`replace_part()`/`replace()` apply removal followed by an atomic `merge_part()`:

```python
with pypmxvmd.edit_pmx("body.pmx", output_path="result.pmx") as tx:
    tx.replace_part(
        "new_clothes.pmx",
        material_names=["旧衣"],
        compact_vertices=True,
    )
```

PMX has no explicit part record, so the boundary is each Material's contiguous
face range. By default orphan vertices, bones, and textures are retained. With
`compact_vertices=True`, only vertices used exclusively by removed faces are
deleted and all affected references are renumbered; live Morph or Soft Body
references cause `PmxTransactionError` instead of being silently dropped. These
operations are canonical whole-model transactions, not source-byte-preserving edits.

---

#### `PmxModel.validate()` / `validate_pmx_model(model, *, limits=..., strict_eof=True)`

Validate PMX semantics without relying on `assert`. The centralized validator
checks PMX 2.0 weight layouts, conditional fields, cross-section references,
Bone parent/inherit cycles, finite numeric values, resource limits and parse
report counts/EOF. Failures raise `PmxValidationError` with stable `field`,
`expected` and `actual` attributes.

```python
from pypmxvmd.common.pmx import PmxLimits, validate_pmx_model

model.validate()  # default strict EOF when parse_report is present
validate_pmx_model(
    model,
    limits=PmxLimits(max_count=2_000_000),
    strict_eof=False,  # diagnostic partial model; report/trailing bytes remain visible
)
```

`strict_eof=False` does not mark a partial parse complete and does not discard
trailing bytes. PMX 2.1 QDEF, Flip/Impulse Morph, all Joint types, and Soft Body
records are included in the centralized semantic contract.

---

#### `pypmxvmd.save_pmx(model_or_document, file_path, *, mode="canonical")`

Validate and atomically save a canonical PMX 2.0/2.1 file. The writer covers all
version-required sections through Joint/Soft Body, selects the smallest valid
index widths, and preserves the model's texture list and index order. Invalid,
incomplete, unknown-feature, or cross-reference-invalid input fails before the
target is replaced.

Canonical output guarantees semantic round-trip stability, not source-byte or
source-layout equality. `PmxParser.write_file_partial()` remains an explicit,
lossy fixture helper and rejects collections it cannot encode.

`write_pmx()` is the equivalent explicit writer name. Pass a `PmxDocument` with
`mode="lossless_patch"` for audited fixed-field updates. `preserve_layout` remains
unsupported, and using lossless mode without a document raises
`UnsupportedPmxFeatureError`; unknown mode names raise `ValueError`. All failures
occur before replacing the target.

| Operation | Available now | Result |
|---|---|---|
| Read `strict` | Yes | Complete PMX 2.0 `PmxModel` or fail closed |
| Read `partial` | Yes | `PmxParseResult` with completeness report |
| Read `document` / spans | Yes (PMX 2.0/2.1) | `PmxDocument`, fixed fields, and eight record-span families |
| Write `canonical` | Yes | Atomic semantic PMX 2.0/2.1 output |
| Write fixed-field `lossless_patch` | Yes | Audited atomic source-byte patch |
| Edit existing Bone records | Yes (PMX 2.0) | Transactional variable-record replacement |
| Edit existing Rigid Body records | Yes (PMX 2.0) | Transactional variable-record replacement |
| Edit existing Joint records | Yes (PMX 2.0 Spring 6DOF) | Transactional variable-record replacement |
| Edit existing Material records | Yes (PMX 2.0) | Transactional variable-record replacement |
| Edit Vertex/Face/Morph/Display Frame collections | Yes | Canonical W12 transaction with reference remapping |
| Compose part/Bone/weight/Morph edits | Yes | Model-level `with` transaction and atomic canonical commit |
| Remove/replace material-defined parts | Yes | Face-range strategy with optional exclusive-vertex compaction |
| Write `preserve_layout` | No | Fail closed |

---

#### `pypmxvmd.load_vpd(file_path, more_info=False) -> VpdPose`

Load a VPD pose file.

---

#### `pypmxvmd.save_vpd(pose, file_path)`

Save a VPD pose file.

---

### Text Files

PyPMXVMD also supports structured text format for viewing and editing.

#### `pypmxvmd.load_vmd_text(file_path, more_info=False) -> VmdMotion`

Load a VMD motion from text.

---

#### `pypmxvmd.save_vmd_text(motion, file_path)`

Save a VMD motion as text.

---

#### `pypmxvmd.load_pmx_text(file_path, more_info=False) -> PmxModel`

Load a PMX model from text.

---

#### `pypmxvmd.save_pmx_text(model, file_path)`

Save a PMX model as text.

---

#### `pypmxvmd.load_vpd_text(file_path, more_info=False) -> VpdPose`

Load a VPD pose from text.

---

#### `pypmxvmd.save_vpd_text(pose, file_path)`

Save a VPD pose as text.

---

#### `pypmxvmd.load_text(file_path, more_info=False) -> VmdMotion | PmxModel | VpdPose`

Auto-detect the text format and load.

---

#### `pypmxvmd.save_text(data, file_path)`

Auto-detect the data type and save in the corresponding text format.

---

## Data Models

### VMD Models

VMD (Vocaloid Motion Data) stores motion and camera data.

#### `VmdMotion`

**Attributes**:

| Field | Type | Description |
|------|------|------|
| `header` | `VmdHeader` | File header |
| `bone_frames` | `List[VmdBoneFrame]` | Bone keyframes |
| `morph_frames` | `List[VmdMorphFrame]` | Morph keyframes |
| `camera_frames` | `List[VmdCameraFrame]` | Camera keyframes |
| `light_frames` | `List[VmdLightFrame]` | Light keyframes |
| `shadow_frames` | `List[VmdShadowFrame]` | Shadow keyframes |
| `ik_frames` | `List[VmdIkFrame]` | IK keyframes |

---

#### `VmdHeader`

| Field | Type | Description |
|------|------|------|
| `version` | `int` | VMD version (1=old, 2=new) |
| `model_name` | `str` | Model name |

---

#### `VmdBoneFrame`

| Field | Type | Description |
|------|------|------|
| `bone_name` | `str` | Bone name (max 15 bytes) |
| `frame_number` | `int` | Frame index |
| `position` | `List[float]` | Position [x, y, z] |
| `rotation` | `List[float]` | Euler rotation [x, y, z] (degrees) |
| `interpolation` | `List[int]` | Interpolation curve (16 values) |
| `physics_disabled` | `bool` | Physics flag |

---

#### `VmdMorphFrame`

| Field | Type | Description |
|------|------|------|
| `morph_name` | `str` | Morph name (max 15 bytes) |
| `frame_number` | `int` | Frame index |
| `weight` | `float` | Weight (0.0-1.0) |

---

#### `VmdCameraFrame`

| Field | Type | Description |
|------|------|------|
| `frame_number` | `int` | Frame index |
| `distance` | `float` | Distance to target |
| `position` | `List[float]` | Target position [x, y, z] |
| `rotation` | `List[float]` | Camera rotation [x, y, z] (degrees, converted from radians on read) |
| `interpolation` | `List[int]` | Interpolation curve (24 values) |
| `fov` | `int` | Field of view (1-180) |
| `perspective` | `bool` | Perspective flag |

---

#### `VmdLightFrame`

| Field | Type | Description |
|------|------|------|
| `frame_number` | `int` | Frame index |
| `color` | `List[float]` | Light color [r, g, b] |
| `position` | `List[float]` | Light position [x, y, z] |

---

#### `VmdShadowFrame`

| Field | Type | Description |
|------|------|------|
| `frame_number` | `int` | Frame index |
| `shadow_mode` | `ShadowMode` | Shadow mode |
| `distance` | `float` | Shadow distance |

---

#### `VmdIkFrame`

| Field | Type | Description |
|------|------|------|
| `frame_number` | `int` | Frame index |
| `display` | `bool` | Display flag |
| `ik_bones` | `List[VmdIkBone]` | IK bones |

---

#### `VmdIkBone`

| Field | Type | Description |
|------|------|------|
| `bone_name` | `str` | IK bone name (max 20 bytes) |
| `ik_enabled` | `bool` | IK enabled |

---

### PMX Models

PMX (Polygon Model eXtended) stores 3D model data.

The public reader populates every PMX 2.0 section through Joint and every PMX 2.1
section through Soft Body. Use `parse_report`/`is_complete` to distinguish a
complete load from an explicitly partial diagnostic result.

#### `PmxModel`

| Field | Type | Description |
|------|------|------|
| `header` | `PmxHeader` | File header |
| `vertices` | `List[PmxVertex]` | Vertices |
| `faces` | `List[List[int]]` | Face indices (triangles) |
| `textures` | `List[str]` | Texture paths |
| `materials` | `List[PmxMaterial]` | Materials |
| `bones` | `List[PmxBone]` | Bones |
| `morphs` | `List[PmxMorph]` | Morphs |
| `frames` | `List[PmxFrame]` | Display frames |
| `rigidbodies` | `List[PmxRigidBody]` | Rigid bodies |
| `joints` | `List[PmxJoint]` | Joints |
| `softbodies` | `List[PmxSoftBody]` | Soft bodies (PMX 2.1) |
| `parse_report` | `PmxParseReport | None` | Parse completeness evidence |
| `is_complete` | `bool` | Whether every required section reached EOF |
| `loaded_sections` | `frozenset[str]` | Sections actually loaded |

---

#### `PmxHeader`

| Field | Type | Description |
|------|------|------|
| `version` | `float` | PMX version (2.0 or 2.1) |
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `comment_jp` | `str` | Japanese comment |
| `comment_en` | `str` | English comment |
| `encoding` | `PmxTextEncoding` | UTF-16LE or UTF-8 layout flag |
| `additional_uv_count` | `int` | Additional UV count (0–4) |
| `*_index_size` | `int` | Six PMX index widths (1, 2 or 4 bytes) |
| `global_flags` | `bytes` | Canonical eight-byte global layout |
| `raw_global_flags` | `bytes` | Original eight bytes for audit |

---

#### `PmxVertex`

| Field | Type | Description |
|------|------|------|
| `position` | `List[float]` | Position [x, y, z] |
| `normal` | `List[float]` | Normal [x, y, z] |
| `uv` | `List[float]` | UV [u, v] |
| `additional_uvs` | `List[List[float]]` | Additional UVs |
| `weight_mode` | `WeightMode` | Weight mode |
| `weight` | `List[List]` | Weights [[bone_idx, weight], ...] |
| `sdef_c` | `List[float] \| None` | Raw SDEF C vector |
| `sdef_r0` | `List[float] \| None` | Raw SDEF R0 vector |
| `sdef_r1` | `List[float] \| None` | Raw SDEF R1 vector |
| `edge_scale` | `float` | Edge scale |

---

#### `PmxMaterial`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `diffuse_color` | `List[float]` | Diffuse [r, g, b, a] |
| `specular_color` | `List[float]` | Specular [r, g, b] |
| `specular_strength` | `float` | Specular strength |
| `ambient_color` | `List[float]` | Ambient [r, g, b] |
| `flags` | `MaterialFlags` | Material flags |
| `edge_color` | `List[float]` | Edge color [r, g, b, a] |
| `edge_size` | `float` | Edge size |
| `texture_path` | `str` | Texture path |
| `texture_index` | `int` | Raw texture table index |
| `sphere_path` | `str` | Sphere texture path |
| `sphere_texture_index` | `int` | Raw sphere texture index |
| `sphere_mode` | `SphMode` | Sphere mode |
| `toon_path` | `str` | Toon texture path |
| `toon_sharing` | `ToonSharing` | Separate or shared Toon layout |
| `toon_texture_index` | `int` | Raw texture/shared Toon index |
| `comment` | `str` | Comment |
| `face_count` | `int` | Face count |

---

#### `MaterialFlags`

| Field | Type | Description |
|------|------|------|
| `double_sided` | `bool` | Double sided |
| `ground_shadow` | `bool` | Ground shadow |
| `self_shadow_map` | `bool` | Self shadow map |
| `self_shadow` | `bool` | Self shadow |
| `edge_drawing` | `bool` | Edge drawing |
| `vertex_color` | `bool` | Vertex color |
| `point_drawing` | `bool` | Point drawing |
| `line_drawing` | `bool` | Line drawing |

---

#### `PmxBone`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `position` | `List[float]` | Position [x, y, z] |
| `parent_index` | `int` | Parent bone index (-1 for none) |
| `deform_layer` | `int` | Deform layer |
| `bone_flags` | `BoneFlags` | Bone flags |
| `tail` | `int | List[float]` | Tail (bone index or offset) |
| `tail_bone_index` | `int | None` | Typed tail target view |
| `tail_offset` | `List[float] | None` | Typed relative-tail view |
| `inherit_parent_index` | `int` | Inherit parent index |
| `inherit_ratio` | `float` | Inherit ratio |
| `fixed_axis` | `List[float]` | Fixed axis |
| `local_axis_x` | `List[float]` | Local X axis |
| `local_axis_z` | `List[float]` | Local Z axis |
| `external_parent_index` | `int` | External parent index |
| `ik_target_index` | `int` | IK target index |
| `ik_loop_count` | `int` | IK loop count |
| `ik_angle_limit` | `float` | IK angle limit |
| `ik_links` | `List[PmxBoneIkLink]` | IK links |

`BoneFlags` exposes all defined PMX 2.x bits. The `inherit_local` field represents
bit `0x0080`; `local_append` is its compatibility alias. Unknown bits remain in
the raw `value` for lossless semantic round-tripping.

---

#### `PmxMorph`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `panel` | `MorphPanel` | Panel |
| `morph_type` | `MorphType` | Morph type |
| `items` | `List` | Typed Group/Vertex/Bone/UV/Material/Flip/Impulse items |

Bone Morph rotations are stored as raw `[x, y, z, w]` quaternions. Material
Morph items retain multiply/add operation plus all diffuse, specular, ambient,
edge and texture tint factors. Flip items retain Morph index/weight; Impulse
items retain Rigid Body index, local flag, velocity, and torque.

---

#### `PmxRigidBody`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `bone_index` | `int` | Bone index |
| `group` | `int` | Collision group |
| `nocollide_groups` | `List[int]` | No-collide groups |
| `collision_group` | `int` | Raw group value (0–15) |
| `collision_mask` | `int` | Raw uint16 collision mask |
| `shape` | `RigidBodyShape` | Shape |
| `size` | `List[float]` | Size [x, y, z] |
| `position` | `List[float]` | Position [x, y, z] |
| `rotation` | `List[float]` | Rotation [x, y, z] |
| `physics_mode` | `RigidBodyPhysMode` | Physics mode |
| `mass` | `float` | Mass |
| `move_damping` | `float` | Move damping |
| `rotation_damping` | `float` | Rotation damping |
| `repulsion` | `float` | Repulsion |
| `friction` | `float` | Friction |

---

#### `PmxJoint`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `joint_type` | `JointType` | Joint type |
| `rigidbody1_index` | `int` | Rigid body 1 index |
| `rigidbody2_index` | `int` | Rigid body 2 index |
| `rigid_body_a_index` | `int` | Clear alias for rigid body 1 |
| `rigid_body_b_index` | `int` | Clear alias for rigid body 2 |
| `position` | `List[float]` | Position |
| `rotation` | `List[float]` | Rotation |
| `position_min` | `List[float]` | Position min |
| `position_max` | `List[float]` | Position max |
| `rotation_min` | `List[float]` | Rotation min |
| `rotation_max` | `List[float]` | Rotation max |
| `position_spring` | `List[float]` | Position spring |
| `rotation_spring` | `List[float]` | Rotation spring |

---

#### `PmxSoftBody`

PMX 2.1 Soft Body records expose names, `shape`, Material reference, collision
group/mask, `flags`, B-link distance, cluster count, mass, margin, aerodynamics
model, and typed `config`, `cluster`, `iteration`, and `material` coefficient
records. `anchors` contains `PmxSoftBodyAnchor` objects; `pin_vertex_indices`
contains unsigned Vertex references. All nested counts, enum/flag values,
finite float32 values, and Material/Rigid Body/Vertex references are validated.

---

### VPD Models

VPD (Vocaloid Pose Data) stores a single-frame pose.

#### `VpdPose`

| Field | Type | Description |
|------|------|------|
| `model_name` | `str` | Model name |
| `bone_poses` | `List[VpdBonePose]` | Bone poses |
| `morph_poses` | `List[VpdMorphPose]` | Morph poses |

---

#### `VpdBonePose`

| Field | Type | Description |
|------|------|------|
| `bone_name` | `str` | Bone name |
| `position` | `List[float]` | Position [x, y, z] |
| `rotation` | `List[float]` | Quaternion [x, y, z, w] |

---

#### `VpdMorphPose`

| Field | Type | Description |
|------|------|------|
| `morph_name` | `str` | Morph name |
| `weight` | `float` | Weight (0.0-1.0) |

---

## Parsers

Use parser classes for more control. When available, they automatically use Cython fast paths.

### `VmdParser`

```python
from pypmxvmd.common.parsers.vmd_parser import VmdParser

parser = VmdParser(progress_callback=lambda p: print(f"{p*100:.1f}%"))
motion = parser.parse_file("motion.vmd", more_info=True)
parser.write_file(motion, "output.vmd")
```

### `PmxParser`

```python
from pypmxvmd.common.parsers.pmx_parser import PmxParser

parser = PmxParser(progress_callback=lambda p: print(f"{p*100:.1f}%"))
model = parser.parse_file("model.pmx", more_info=True)
parser.write_file(model, "output.pmx")
```

### `VpdParser`

```python
from pypmxvmd.common.parsers.vpd_parser import VpdParser

parser = VpdParser(progress_callback=lambda p: print(f"{p*100:.1f}%"))
pose = parser.parse_file("pose.vpd", more_info=True)
parser.write_file(pose, "output.vpd")
```

---

## Enums

### VMD

#### `ShadowMode`

| Value | Description |
|----|------|
| `OFF` (0) | Off |
| `MODE1` (1) | Mode 1 |
| `MODE2` (2) | Mode 2 |

---

### PMX

#### `WeightMode`

| Value | Description |
|----|------|
| `BDEF1` (0) | Single bone |
| `BDEF2` (1) | Two bones |
| `BDEF4` (2) | Four bones |
| `SDEF` (3) | Sphere deformation |
| `QDEF` (4) | Quaternion deformation |

---

#### `SphMode`

| Value | Description |
|----|------|
| `DISABLED` (0) | Disabled |
| `MULTIPLY` (1) | Multiply |
| `ADDITIVE` (2) | Additive |
| `SUBTEX` (3) | Sub texture |

---

#### `MorphType`

| Value | Description |
|----|------|
| `GROUP` (0) | Group |
| `VERTEX` (1) | Vertex |
| `BONE` (2) | Bone |
| `UV` (3) | UV |
| `EXTENDED_UV1` (4) | Extended UV1 |
| `EXTENDED_UV2` (5) | Extended UV2 |
| `EXTENDED_UV3` (6) | Extended UV3 |
| `EXTENDED_UV4` (7) | Extended UV4 |
| `MATERIAL` (8) | Material |
| `FLIP` (9) | Flip |
| `IMPULSE` (10) | Impulse |

---

#### `MorphPanel`

| Value | Description |
|----|------|
| `HIDDEN` (0) | Hidden |
| `EYEBROW` (1) | Eyebrow |
| `EYE` (2) | Eye |
| `MOUTH` (3) | Mouth |
| `OTHER` (4) | Other |

---

#### `RigidBodyShape`

| Value | Description |
|----|------|
| `SPHERE` (0) | Sphere |
| `BOX` (1) | Box |
| `CAPSULE` (2) | Capsule |

---

#### `RigidBodyPhysMode`

| Value | Description |
|----|------|
| `BONE` (0) | Follow bone |
| `PHYSICS` (1) | Physics |
| `PHYSICS_BONE` (2) | Physics + follow bone |

---

#### `JointType`

| Value | Description |
|----|------|
| `SPRING6DOF` (0) | 6DOF spring |
| `SIX_DOF` (1) | 6DOF |
| `POINT_TO_POINT` (2) | Point-to-point |
| `CONE_TWIST` (3) | Cone twist |
| `SLIDER` (4) | Slider |
| `HINGE` (5) | Hinge |

---

#### `SoftBodyShape`, `SoftBodyFlags`, `SoftBodyAeroModel`

- Shapes: `TRI_MESH` (0), `ROPE` (1).
- Flags: `B_LINK` (1), `CLUSTER` (2), `LINK_CROSS` (4); other bits are rejected.
- Aerodynamics: `V_POINT` (0), `V_TWO_SIDED` (1), `V_ONE_SIDED` (2),
  `F_TWO_SIDED` (3), `F_ONE_SIDED` (4).

---

## Examples

### Example 1: Read VMD motion and inspect

```python
import pypmxvmd

motion = pypmxvmd.load_vmd("dance.vmd", more_info=True)
print(f"Version: {motion.header.version}")
print(f"Model: {motion.header.model_name}")
print(f"Bone frames: {motion.get_bone_frame_count()}")
print(f"Morph frames: {motion.get_morph_frame_count()}")

for frame in motion.bone_frames[:5]:
    print(frame.bone_name, frame.frame_number, frame.position)
```

### Example 2: Build and validate an in-memory PMX model

```python
import pypmxvmd
from pypmxvmd.common.models.pmx import PmxModel, PmxHeader, PmxVertex, PmxMaterial

model = PmxModel()
model.header = PmxHeader(version=2.0, name_jp="Triangle", name_en="Triangle")
model.vertices = [
    PmxVertex(position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0], uv=[0.0, 0.0]),
    PmxVertex(position=[1.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0], uv=[1.0, 0.0]),
    PmxVertex(position=[0.5, 1.0, 0.0], normal=[0.0, 0.0, 1.0], uv=[0.5, 1.0]),
]
model.faces = [[0, 1, 2]]
model.materials = [
    PmxMaterial(name_jp="Material", name_en="Material", diffuse_color=[0.8, 0.8, 0.8, 1.0], face_count=3)
]

model.validate()
# Complete PMX output is intentionally unavailable until the canonical writer ships.
```

### Example 3: Modify VMD motion

```python
import pypmxvmd

motion = pypmxvmd.load_vmd("original.vmd")

for frame in motion.bone_frames:
    frame.position[1] += 10.0

for frame in motion.morph_frames:
    frame.weight *= 0.5

pypmxvmd.save_vmd(motion, "modified.vmd")
```

### Example 4: Convert VPD pose to VMD motion

```python
import pypmxvmd
from pypmxvmd.common.models.vmd import VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame

pose = pypmxvmd.load_vpd("pose.vpd")

motion = VmdMotion()
motion.header = VmdHeader(version=2, model_name=pose.model_name)

for bone_pose in pose.bone_poses:
    frame = VmdBoneFrame(
        bone_name=bone_pose.bone_name,
        frame_number=0,
        position=bone_pose.position,
        rotation=[0.0, 0.0, 0.0]
    )
    motion.bone_frames.append(frame)

for morph_pose in pose.morph_poses:
    frame = VmdMorphFrame(
        morph_name=morph_pose.morph_name,
        frame_number=0,
        weight=morph_pose.weight
    )
    motion.morph_frames.append(frame)

pypmxvmd.save_vmd(motion, "pose_as_motion.vmd")
```

### Example 5: Validate data

```python
import pypmxvmd

model = pypmxvmd.load_pmx("model.pmx")

try:
    model.validate()
    print("Model validation passed")
except pypmxvmd.PmxValidationError as e:
    print(f"Validation failed: {e}")
```

---

## Error Handling

PyPMXVMD uses standard Python exceptions:

| Exception | Description |
|----------|------|
| `FileNotFoundError` | File not found |
| `ValueError` | Invalid format or data |
| `IncompletePmxError` | A complete PMX read was requested but mandatory sections or EOF were not reached |
| `IncompletePmxWriterError` | The explicit legacy partial PMX writer would discard unsupported sections |
| `PmxValidationError` | A semantic model field failed validation; exposes `field`, `expected` and `actual` |
| `PmxPatchError` | A lossless patch failed path/type/range/before/reparse/semantic checks |
| `PmxBoneEditError` | A transactional Bone edit violated its field, layout, reference, or collection safety contract |
| `PmxVertexEditError` | A Vertex transaction violated its field, reference-remapping, or scope contract |
| `PmxFaceEditError` | A Face transaction violated topology or Material-range constraints |
| `PmxMorphEditError` | A Morph transaction violated item, type, reference, or scope constraints |
| `PmxFrameEditError` | A Display Frame transaction violated item references or special-frame constraints |
| `PmxTransactionError` | A composed model transaction failed validation, remapping, strict reparse, or atomic commit |
| `UnsupportedPmxFeatureError` | A recognized PMX version/mode is not implemented; exposes `feature` and `available` |
| `IOError` | I/O error |

```python
import pypmxvmd

try:
    model = pypmxvmd.load_pmx("missing.pmx")
except FileNotFoundError:
    print("File not found")
except ValueError as e:
    print(f"Format error: {e}")
```

---

## Compatibility

- **VMD**: Supports v1 and v2
- **PMX**: Supports 2.0 and 2.1
- **VPD**: Supports standard VPD text format
- **Encoding**: VMD uses Shift-JIS, PMX supports UTF-16LE/UTF-8, VPD uses Shift-JIS

---

## License

MIT License
