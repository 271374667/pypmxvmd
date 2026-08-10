# PyPMXVMD

![pypmxvmd](https://socialify.git.ci/271374667/pypmxvmd/image?description=1&font=Inter&language=1&name=1&owner=1&theme=Auto)

[English API](docs/API.md) | [中文 API](docs/API_CN.md)

Python MikuMikuDance File Parser Library

[![Python Version](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.7.1-orange.svg)](https://github.com/271374667/pypmxvmd)

PyPMXVMD is a Python library for parsing and modifying MikuMikuDance (MMD) files, supporting the following formats:

- **VMD** (Vocaloid Motion Data) - Motion/animation data
- **PMX** (Polygon Model eXtended) - 3D model data
- **VPD** (Vocaloid Pose Data) - Pose data

## Features

- Complete PMX 2.0 reading and canonical writing through Spring 6DOF Joint
- PMX 2.1 QDEF, Flip/Impulse Morph, all six Joint types, and full Soft Body records
- Validating, atomic PMX 2.0/2.1 output with semantic round-trip coverage
- Conversion between binary and text formats
- Object-oriented API design, easy to use
- Complete type annotation support
- Optional Cython acceleration for core parsing and binary I/O; PMX currently uses the canonical Cursor model for complete public results
- No external dependencies (core functionality)
- Uses Python 3.11 as the supported development and release baseline

## Installation

```bash
# Add the released package to a uv project
uv add pypmxvmd

# Prepare a source checkout for development
git clone https://github.com/271374667/pypmxvmd.git
cd pypmxvmd
uv sync --group dev --python 3.11.12
```

### Optional: Build Cython Accelerators

The core parsing path supports Cython-accelerated modules for VMD/PMX and binary I/O.
`uv sync` builds the three native extensions through the project's setuptools backend.
The runtime automatically falls back to pure Python when compiled modules are unavailable.

```bash
uv run --python 3.11.12 --no-sync python scripts/build_cython.py
uv run --python 3.11.12 --no-sync pytest tests/test_cython_parsers.py -m "cython and not benchmark" -ra
```

Set `PYPMXVMD_BUILD_CYTHON=0` before `uv sync` when a pure-Python environment is
required explicitly.

## Quick Start

### Basic Usage

```python
import pypmxvmd

# Load VMD motion file
motion = pypmxvmd.load_vmd("motion.vmd")
print(f"Bone frames: {len(motion.bone_frames)}")
print(f"Morph frames: {len(motion.morph_frames)}")

# Modify and save
pypmxvmd.save_vmd(motion, "modified_motion.vmd")

# Load PMX model file
model = pypmxvmd.load_pmx("model.pmx")
print(f"Vertices: {len(model.vertices)}")
print(f"Materials: {len(model.materials)}")
pypmxvmd.save_pmx(model, "canonical-model.pmx")

# Load VPD pose file
pose = pypmxvmd.load_vpd("pose.vpd")
print(f"Bone poses: {len(pose.bone_poses)}")
```

### Automatic Format Detection

```python
import pypmxvmd

# Automatically detect file type and load
data = pypmxvmd.load("file.vmd")  # Returns VmdMotion
data = pypmxvmd.load("file.pmx")  # Returns PmxModel
data = pypmxvmd.load("file.vpd")  # Returns VpdPose

# Automatically detect data type and save
pypmxvmd.save(motion, "output.vmd")
pypmxvmd.save(model, "output.pmx")
pypmxvmd.save(pose, "output.vpd")
```

PMX 2.0/2.1 binary loading and canonical saving consume every version-required
section through Joint/Soft Body. Saving validates the full model before
atomically replacing the target;
canonical output chooses deterministic index widths and is semantically stable,
but is not promised to be byte-identical to the source. Semantic validation is
available through `PmxModel.validate()`. PMX 2.1 support covers QDEF,
Flip/Impulse Morphs, Spring 6DOF/6DOF/P2P/ConeTwist/Slider/Hinge Joint records,
and all Soft Body Config/Cluster/Iteration/Material/Anchor/Pin fields. This
evidence currently comes from independent synthetic fixed-byte fixtures; no
redistributable real PMX 2.1 corpus is claimed.

PMX binary modes are explicit and keyword-only, so existing positional calls
remain compatible:

```python
# Complete model or IncompletePmxError
model = pypmxvmd.load_pmx("model.pmx", mode="strict")

# Diagnostic model plus section/EOF evidence
result = pypmxvmd.load_pmx("model.pmx", mode="partial")

# Canonical PMX 2.0/2.1 output
pypmxvmd.write_pmx(model, "output.pmx", mode="canonical")

# Source-backed fixed-width editing
document = pypmxvmd.load_pmx_document("model.pmx")
document.model.bones[0].deform_layer = 1
pypmxvmd.write_pmx(document, "patched.pmx", mode="lossless_patch")

# Transactional editing of an existing Bone record, including variable layouts
document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_bones()
editor.set_deform_layer(0, 2)
editor.set_tail_offset(0, [0.0, 1.0, 0.0])
editor.write_file("bone-edited.pmx")

# Transactional editing of an existing Rigid Body record
editor = document.edit_rigid_bodies()
editor.set_bone(0, -1)  # legal no-Bone sentinel
editor.set_collision(0, collision_group=0, collision_mask=0xFFFE)
editor.set_physical_parameters(0, mass=1.0, friction=0.5)
editor.write_file("rigid-body-edited.pmx")

# Transactional editing of an existing PMX 2.0 Spring 6DOF Joint
editor = document.edit_joints()
editor.set_rigid_body_references(0, -1, 1)
editor.set_rotation_limits(0, [-0.5, -0.25, -0.1], [0.5, 0.25, 0.1])
editor.set_rotation_spring(0, [0.2, 0.3, 0.4])
editor.write_file("joint-edited.pmx")

# Transactional editing of an existing Material record
editor = document.edit_materials()
editor.set_diffuse_color(0, [0.8, 0.6, 0.5, 1.0])
editor.sync_ambient_from_diffuse(0)  # explicit; never happens on ordinary save
editor.set_shared_toon(0, 0)         # built-in toon01.bmp
editor.write_file("material-edited.pmx")
```

`document`/field-span reads and fixed-width `lossless_patch` writes are available
for selected directly mapped Material, Bone, Rigid Body, and Joint fields. Every patch is
range/before-byte checked, strict-reparsed, and compared against the edited model.
The Bone, Rigid Body, Joint, and Material transactions below can rebuild their
existing variable-length records. Other variable-length fields, record
insertion/deletion, global index renumbering, and PMX 2.1-specific high-level
editing remain unsupported; `preserve_layout` also remains unsupported.
Lossless mode never silently falls back to canonical output.

`PmxBoneEditor` additionally supports all PMX 2.0 fields of existing Bone
records: variable-length names, position/parent/deform layer, basic flags, both
tail modes, inheritance, fixed/local axes, external parent, and IK links/limits.
It rebuilds only changed Bone records, validates the complete model, strict-
reparses the result, and writes atomically. Bone insertion, deletion, replacement,
reordering, and global index renumbering remain unsupported and fail closed.

`PmxRigidBodyEditor` supports all fields of existing PMX 2.0 Rigid Body
records: variable-length names, Bone reference including `-1`, three shapes and
physics modes, raw collision group/mask, size/position/rotation in source units,
and all five physical parameters. It rebuilds only changed records and preserves
existing Joint index semantics. Rigid Body insertion, deletion, replacement, and
reordering remain unsupported and fail closed.

`PmxJointEditor` supports every field of existing PMX 2.0 Spring 6DOF Joint
records: variable-length names, the A/B Rigid Body references including `-1`,
position/rotation, translation/rotation min/max limits, and both spring vectors.
Rotation values remain raw radians. Limit setters require component-wise
`minimum <= maximum`; unchanged legacy source axes are preserved. Joint insertion,
deletion, replacement, reordering, and PMX 2.1 Joint types remain unsupported.

`PmxMaterialEditor` supports every serialized field of existing PMX 2.0
Material records: variable-length names/comments, colors, all eight draw flags,
edge settings, Texture/Sphere/Toon modes and references, and face-index counts.
Texture display paths remain derived from the serialized indices. Face counts
are updated as one validated collection, and ambient/diffuse synchronization is
an explicit command only. Material or texture-table insertion, deletion,
replacement, and reordering remain unsupported.

### Text Format Conversion

PyPMXVMD supports converting binary files to readable text format for viewing and editing:

```python
import pypmxvmd

# VMD -> Text
motion = pypmxvmd.load_vmd("motion.vmd")
pypmxvmd.save_vmd_text(motion, "motion.txt")

# Text -> VMD
motion = pypmxvmd.load_vmd_text("motion.txt")
pypmxvmd.save_vmd(motion, "motion.vmd")

# PMX -> Text
model = pypmxvmd.load_pmx("model.pmx")
pypmxvmd.save_pmx_text(model, "model.txt")

# VPD -> Text
pose = pypmxvmd.load_vpd("pose.vpd")
pypmxvmd.save_vpd_text(pose, "pose.txt")
```

### Using Parser Classes

If you need more control, you can use the parser classes directly:

```python
from pypmxvmd import VmdParser, PmxParser, VpdParser

# VMD Parser
vmd_parser = VmdParser()
motion = vmd_parser.parse_file("motion.vmd", more_info=True)
vmd_parser.write_file(motion, "output.vmd")

# PMX Parser
pmx_parser = PmxParser()
model = pmx_parser.parse_file("model.pmx", more_info=True)
pmx_parser.write_file(model, "canonical-model.pmx")

# VPD Parser
vpd_parser = VpdParser()
pose = vpd_parser.parse_file("pose.vpd", more_info=True)
vpd_parser.write_file(pose, "output.vpd")
```

## Data Structures

### VmdMotion (VMD Motion)

```python
class VmdMotion:
    header: VmdHeader           # File header information
    bone_frames: List[VmdBoneFrame]      # Bone keyframes
    morph_frames: List[VmdMorphFrame]    # Morph keyframes
    camera_frames: List[VmdCameraFrame]  # Camera keyframes
    light_frames: List[VmdLightFrame]    # Light keyframes
    shadow_frames: List[VmdShadowFrame]  # Shadow keyframes
    ik_frames: List[VmdIkFrame]          # IK keyframes
```

### PmxModel (PMX Model)

```python
class PmxModel:
    header: PmxHeader           # File header information
    vertices: List[PmxVertex]   # Vertex list
    faces: List[int]            # Face indices
    textures: List[str]         # Texture paths
    materials: List[PmxMaterial]  # Material list
    bones: List[PmxBone]        # Bone list
    morphs: List[PmxMorph]      # Morph list
    frames: List[PmxFrame]      # Display frames
    rigidbodies: List[PmxRigidBody]  # Rigidbody list
    joints: List[PmxJoint]      # Joint list
```

### VpdPose (VPD Pose)

```python
class VpdPose:
    model_name: str             # Model name
    bone_poses: List[VpdBonePose]   # Bone pose list
    morph_poses: List[VpdMorphPose] # Morph pose list
```

## API Reference

### Core Functions

| Function | Description |
|------|------|
| `load_vmd(path)` | Load VMD file |
| `save_vmd(motion, path)` | Save VMD file |
| `load_pmx(path)` | Load PMX file |
| `load_pmx(path, mode="partial")` | Load PMX with completeness evidence |
| `load_pmx_document(path)` | Load exact source bytes and fixed-field spans |
| `save_pmx(model, path)` | Save PMX file |
| `write_pmx(model, path, mode="canonical")` | Canonical PMX writer |
| `write_pmx(document, path, mode="lossless_patch")` | Audited fixed-field patch |
| `load_vpd(path)` | Load VPD file |
| `save_vpd(pose, path)` | Save VPD file |
| `load(path)` | Auto-detect and load |
| `save(data, path)` | Auto-detect and save |

### Text Format Functions

| Function | Description |
|------|------|
| `load_vmd_text(path)` | Load VMD from text |
| `save_vmd_text(motion, path)` | Save VMD as text |
| `load_pmx_text(path)` | Load PMX from text |
| `save_pmx_text(model, path)` | Save PMX as text |
| `load_vpd_text(path)` | Load VPD from text |
| `save_vpd_text(pose, path)` | Save VPD as text |
| `load_text(path)` | Auto-detect and load text |
| `save_text(data, path)` | Auto-detect and save text |

## Project Structure

```
pypmxvmd/                     # Main package
  __init__.py                 # Public API (load/save helpers)
  common/                     # Core implementation
    io/                       # Binary/text IO (+ Cython accel)
    models/                   # Data models (VMD/PMX/VPD)
    parsers/                  # Parsers (+ fast modules)
docs/                         # Documentation
  API.md                      # English API
  API_CN.md                   # 中文 API
scripts/                      # Build helpers
  build_cython.py
  build_wheels.py
tests/                        # Tests + fixtures
```


## Testing

```bash
# Run correctness tests, including a local corpus when present
uv run --python 3.11.12 --no-sync pytest -m "not benchmark" -ra

# Run the local PMX/VMD corpus only
uv run --python 3.11.12 --no-sync pytest -m corpus -ra

# Run coverage test
uv run --python 3.11.12 --no-sync pytest --cov=pypmxvmd --cov-report=html
```

## Development

```bash
# Resolve and install the locked development environment
uv sync --group dev --python 3.11.12

# Code formatting
uv run --python 3.11.12 --no-sync black --check pypmxvmd tests scripts
uv run --python 3.11.12 --no-sync isort --check-only pypmxvmd tests scripts

# Type checking
uv run --python 3.11.12 --no-sync mypy pypmxvmd

# Code linting
uv run --python 3.11.12 --no-sync flake8 pypmxvmd tests scripts

# Build sdist and the platform wheel
uv build
```

## Changelog

### v2.7.1
- Updated core parsers and binary I/O with Cython fast paths
- Restored the Windows CPython 3.11 native wheel build
- Improved text format auto-detection and test coverage

### v2.5.1
- Added optional Cython acceleration for core parsing and binary I/O
- Cython path averages ~3.7x faster than the previous implementation

### v2.0.0 (2024)
- Complete refactor to object-oriented architecture
- Added complete type annotations
- Support for text format export/import
- Improved error handling and validation
- Added progress callback support

### v1.x (Original)
- Based on Nuthouse01's original implementation
- Functional API

## Acknowledgments

This project is refactored from the original MMD scripting tools by [Nuthouse01](https://github.com/Nuthouse01/PMX-VMD-Scripting-Tools).

## License

MIT License - See [LICENSE](LICENSE) file for details

## Contributing

Issues and Pull Requests are welcome!

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Create a Pull Request
