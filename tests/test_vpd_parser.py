"""VPD parser and model validation tests."""

import pytest

from pypmxvmd.common.models.vpd import VpdBonePose, VpdMorphPose, VpdPose
from pypmxvmd.common.parsers.vpd_parser import VpdParser


def test_vpd_roundtrip_preserves_supported_fields(tmp_path, sample_vpd_pose):
    parser = VpdParser()
    path = tmp_path / "pose.vpd"
    parser.write_file(sample_vpd_pose, path)

    loaded = parser.parse_file(path)

    assert loaded.model_name == "TestModel"
    assert loaded.bone_poses[0].bone_name == "センター"
    assert loaded.bone_poses[0].position == pytest.approx([0.0, 10.0, 0.0])
    assert loaded.bone_poses[0].rotation == pytest.approx([0.1, 0.2, 0.3, 0.9])
    assert loaded.morph_poses[0].morph_name == "笑い"
    assert loaded.morph_poses[0].weight == pytest.approx(0.8)


def test_vpd_model_validation_accepts_japanese_names():
    pose = VpdPose(
        model_name="初音ミク",
        bone_poses=[
            VpdBonePose(
                bone_name="全ての親",
                position=[0.0, 0.0, 0.0],
                rotation=[0.0, 0.0, 0.0, 1.0],
            )
        ],
        morph_poses=[VpdMorphPose(morph_name="まばたき", weight=1.0)],
    )

    pose.validate()
