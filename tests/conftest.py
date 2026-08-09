"""Shared pytest fixtures for deterministic synthetic PMX/VMD/VPD data."""

from enum import Enum
from pathlib import Path

import pytest

from pypmxvmd.common.models.base import BaseModel
from pypmxvmd.common.models.pmx import PmxHeader, PmxMaterial, PmxModel, PmxVertex
from pypmxvmd.common.models.vmd import (
    VmdBoneFrame,
    VmdHeader,
    VmdMorphFrame,
    VmdMotion,
)
from pypmxvmd.common.models.vpd import VpdBonePose, VpdMorphPose, VpdPose
from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser


TEST_DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def test_data_dir():
    """Return the root for optional local test data."""
    return TEST_DATA_DIR


@pytest.fixture(scope="session")
def test_models_dir():
    """Return the local real-world PMX corpus directory."""
    return TEST_DATA_DIR / "test_models"


@pytest.fixture(scope="session")
def test_vmds_dir():
    """Return the local real-world VMD corpus directory."""
    return TEST_DATA_DIR / "test_vmds"


@pytest.fixture
def sample_pmx_model():
    """Build a minimal PMX 2.0 model with one material and one face."""
    model = PmxModel()
    model.header = PmxHeader(
        version=2.0,
        name_jp="テストモデル",
        name_en="TestModel",
        comment_jp="合成テスト",
        comment_en="Synthetic test",
    )
    model.vertices = [
        PmxVertex(position=[0.0, 0.0, 0.0], uv=[0.0, 0.0]),
        PmxVertex(position=[1.0, 0.0, 0.0], uv=[1.0, 0.0]),
        PmxVertex(position=[0.0, 1.0, 0.0], uv=[0.0, 1.0]),
    ]
    model.faces = [[0, 1, 2]]
    model.materials = [
        PmxMaterial(
            name_jp="材質",
            name_en="Material",
            diffuse_color=[0.8, 0.7, 0.6, 1.0],
            specular_color=[0.2, 0.2, 0.2],
            specular_strength=4.0,
            ambient_color=[0.1, 0.1, 0.1],
            face_count=3,
        )
    ]
    return model


@pytest.fixture
def sample_pmx_file(tmp_path, sample_pmx_model):
    """Write the synthetic PMX model to an isolated path."""
    path = tmp_path / "sample.pmx"
    PmxParser().write_file_partial(sample_pmx_model, path)
    return path


@pytest.fixture
def sample_vmd_file(tmp_path, sample_vmd_motion):
    """Write the synthetic VMD motion to an isolated path."""
    path = tmp_path / "sample.vmd"
    VmdParser().write_file(sample_vmd_motion, path)
    return path


@pytest.fixture
def sample_vmd_motion():
    """Build a small VMD motion with bone and morph sections."""
    motion = VmdMotion()
    motion.header = VmdHeader(version=2, model_name="TestModel")
    motion.bone_frames = [
        VmdBoneFrame(
            bone_name="センター",
            frame_number=12,
            position=[1.0, 2.0, 3.0],
            rotation=[0.0, 0.0, 0.0],
        )
    ]
    motion.morph_frames = [
        VmdMorphFrame(morph_name="笑い", frame_number=18, weight=0.75)
    ]
    return motion


@pytest.fixture
def sample_vpd_pose():
    """Build a small VPD pose with Japanese bone and morph names."""
    return VpdPose(
        model_name="TestModel",
        bone_poses=[
            VpdBonePose(
                bone_name="センター",
                position=[0.0, 10.0, 0.0],
                rotation=[0.1, 0.2, 0.3, 0.9],
            )
        ],
        morph_poses=[VpdMorphPose(morph_name="笑い", weight=0.8)],
    )


def _assert_semantic_equal(actual, expected, path="root"):
    """Recursively compare every model field with an actionable failure path."""
    if isinstance(expected, Enum):
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
        assert type(actual) is type(expected), f"{path}: enum types differ"
        return

    if isinstance(expected, bool):
        assert type(actual) is bool, f"{path}: expected bool, got {type(actual).__name__}"
        assert actual is expected, f"{path}: {actual!r} != {expected!r}"
        return

    if isinstance(expected, int):
        assert type(actual) is int, f"{path}: expected int, got {type(actual).__name__}"
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
        return

    if isinstance(expected, float):
        assert isinstance(actual, (int, float)), (
            f"{path}: expected numeric value, got {type(actual).__name__}"
        )
        assert actual == pytest.approx(expected, abs=1e-6), (
            f"{path}: {actual!r} != {expected!r}"
        )
        return

    if isinstance(expected, (str, bytes, type(None))):
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
        return

    if isinstance(expected, (list, tuple)):
        assert type(actual) is type(expected), (
            f"{path}: expected {type(expected).__name__}, "
            f"got {type(actual).__name__}"
        )
        assert len(actual) == len(expected), (
            f"{path}: length {len(actual)} != {len(expected)}"
        )
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            _assert_semantic_equal(actual_item, expected_item, f"{path}[{index}]")
        return

    if isinstance(expected, dict):
        assert type(actual) is dict, f"{path}: expected dict"
        assert actual.keys() == expected.keys(), f"{path}: dictionary keys differ"
        for key in expected:
            _assert_semantic_equal(actual[key], expected[key], f"{path}[{key!r}]")
        return

    if isinstance(expected, BaseModel) or hasattr(expected, "__dict__"):
        assert type(actual) is type(expected), (
            f"{path}: {type(actual).__name__} != {type(expected).__name__}"
        )
        expected_fields = {
            key: value
            for key, value in vars(expected).items()
            if key not in {"_validated", "parse_report"}
        }
        actual_fields = {
            key: value
            for key, value in vars(actual).items()
            if key not in {"_validated", "parse_report"}
        }
        assert actual_fields.keys() == expected_fields.keys(), (
            f"{path}: model fields differ: "
            f"{actual_fields.keys()} != {expected_fields.keys()}"
        )
        for key in expected_fields:
            _assert_semantic_equal(
                actual_fields[key],
                expected_fields[key],
                f"{path}.{key}",
            )
        return

    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


@pytest.fixture
def assert_model_equal():
    """Return the centralized field-level model comparator."""
    return _assert_semantic_equal
