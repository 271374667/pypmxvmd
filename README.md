# PyPMXVMD

![pypmxvmd](https://socialify.git.ci/271374667/pypmxvmd/image?description=1&font=Inter&language=1&name=1&owner=1&theme=Auto)

[English API](docs/API.md) | [中文 API](docs/API_CN.md)

Python MikuMikuDance File Parser Library

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.7.1-orange.svg)](https://github.com/pypmxvmd/pypmxvmd)

PyPMXVMD is a Python library for parsing and modifying MikuMikuDance (MMD) files, supporting the following formats:

- **VMD** (Vocaloid Motion Data) - Motion/animation data
- **PMX** (Polygon Model eXtended) - 3D model data
- **VPD** (Vocaloid Pose Data) - Pose data

## Features

- Full support for reading and writing VMD, PMX, and VPD files
- Conversion between binary and text formats
- Object-oriented API design, easy to use
- Complete type annotation support
- Optional Cython acceleration for core parsing and binary I/O (VMD/PMX, binary read/write)
- No external dependencies (core functionality)
- Supports Python 3.8+

## Installation

```bash
# Install from PyPI
pip install pypmxvmd

# Install from source
git clone https://github.com/pypmxvmd/pypmxvmd.git
cd pypmxvmd
pip install -e .

# Install development dependencies
pip install -e ".[dev]"
```

### Optional: Build Cython Accelerators

The core parsing path supports Cython-accelerated modules for VMD/PMX and binary I/O.
In typical workloads, the Cython implementation is ~3.7x faster on average than the previous implementation.
Prebuilt wheels are provided for Windows (cp38-cp313). Other platforms or versions compile locally.
If the compiled modules are not available, the library automatically falls back to pure Python.

```bash
pip install cython
python scripts/build_cython.py
```

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
pmx_parser.write_file(model, "output.pmx")

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
| `save_pmx(model, path)` | Save PMX file |
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
    validators/               # Validation helpers
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
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_vmd_parser.py -v

# Run coverage test
pytest tests/ --cov=pypmxvmd --cov-report=html
```

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Code formatting
black pypmxvmd/
isort pypmxvmd/

# Type checking
mypy pypmxvmd/

# Code linting
flake8 pypmxvmd/
```

## Changelog

### v2.7.1
- Updated core parsers and binary I/O with Cython fast paths
- Added/expanded Windows wheel builds (cp38-cp313)
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
