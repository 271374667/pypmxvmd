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
pip install pypmxvmd
```

### Basic Usage

```python
import pypmxvmd

# Auto-detect file type and load
model = pypmxvmd.load("model.pmx")

# Save
pypmxvmd.save(model, "output.pmx")
```

---

## Top-Level API

PyPMXVMD provides concise top-level helpers for loading and saving files.

### Binary Files

#### `pypmxvmd.load(file_path, more_info=False)`

Auto-detect the file type and load it.

**Args**:
- `file_path` (str | Path): File path
- `more_info` (bool): Whether to print detailed parsing info

**Returns**: `VmdMotion` | `PmxModel` | `VpdPose`

**Raises**: `ValueError` - Unsupported file type

```python
data = pypmxvmd.load("motion.vmd")
```

---

#### `pypmxvmd.save(data, file_path)`

Auto-detect the data type and save it.

**Args**:
- `data`: `VmdMotion` | `PmxModel` | `VpdPose`
- `file_path` (str | Path): Output path

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

#### `pypmxvmd.load_pmx(file_path, more_info=False) -> PmxModel`

Load a PMX model file.

---

#### `pypmxvmd.save_pmx(model, file_path)`

Save a PMX model file.

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

---

#### `PmxHeader`

| Field | Type | Description |
|------|------|------|
| `version` | `float` | PMX version (2.0 or 2.1) |
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `comment_jp` | `str` | Japanese comment |
| `comment_en` | `str` | English comment |

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
| `sphere_path` | `str` | Sphere texture path |
| `sphere_mode` | `SphMode` | Sphere mode |
| `toon_path` | `str` | Toon texture path |
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

---

#### `PmxMorph`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `panel` | `MorphPanel` | Panel |
| `morph_type` | `MorphType` | Morph type |
| `items` | `List` | Items |

---

#### `PmxRigidBody`

| Field | Type | Description |
|------|------|------|
| `name_jp` | `str` | Japanese name |
| `name_en` | `str` | English name |
| `bone_index` | `int` | Bone index |
| `group` | `int` | Collision group |
| `nocollide_groups` | `List[int]` | No-collide groups |
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
| `position` | `List[float]` | Position |
| `rotation` | `List[float]` | Rotation |
| `position_min` | `List[float]` | Position min |
| `position_max` | `List[float]` | Position max |
| `rotation_min` | `List[float]` | Rotation min |
| `rotation_max` | `List[float]` | Rotation max |
| `position_spring` | `List[float]` | Position spring |
| `rotation_spring` | `List[float]` | Rotation spring |

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

### Example 2: Create a simple PMX model

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

pypmxvmd.save_pmx(model, "triangle.pmx")
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
except AssertionError as e:
    print(f"Validation failed: {e}")
```

---

## Error Handling

PyPMXVMD uses standard Python exceptions:

| Exception | Description |
|----------|------|
| `FileNotFoundError` | File not found |
| `ValueError` | Invalid format or data |
| `IOError` | I/O error |
| `AssertionError` | Validation failure |

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
