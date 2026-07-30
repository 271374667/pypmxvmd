"""Round-trip tests for the public structured-text API."""

import pytest

import pypmxvmd


TEXT_FUNCTIONS = (
    "load_vmd_text",
    "save_vmd_text",
    "load_pmx_text",
    "save_pmx_text",
    "load_vpd_text",
    "save_vpd_text",
    "load_text",
    "save_text",
)


def test_public_text_api_is_exported():
    for name in TEXT_FUNCTIONS:
        assert callable(getattr(pypmxvmd, name))


def test_vmd_text_roundtrip(tmp_path, sample_vmd_motion):
    path = tmp_path / "motion.txt"
    pypmxvmd.save_vmd_text(sample_vmd_motion, path)

    loaded = pypmxvmd.load_vmd_text(path)

    assert loaded.header.to_list() == sample_vmd_motion.header.to_list()
    assert loaded.bone_frames[0].bone_name == "センター"
    assert loaded.bone_frames[0].frame_number == 12
    assert loaded.bone_frames[0].position == pytest.approx([1.0, 2.0, 3.0])
    assert loaded.morph_frames[0].morph_name == "笑い"
    assert loaded.morph_frames[0].weight == pytest.approx(0.75)


def test_pmx_text_roundtrip(tmp_path, sample_pmx_model):
    path = tmp_path / "model.txt"
    pypmxvmd.save_pmx_text(sample_pmx_model, path)

    loaded = pypmxvmd.load_pmx_text(path)

    assert loaded.header.to_list() == sample_pmx_model.header.to_list()
    assert len(loaded.vertices) == len(sample_pmx_model.vertices)
    for actual, expected in zip(loaded.vertices, sample_pmx_model.vertices):
        assert actual.position == pytest.approx(expected.position)
    assert loaded.faces == sample_pmx_model.faces
    assert loaded.materials[0].name_jp == "材質"
    assert loaded.materials[0].face_count == 3


def test_vpd_text_roundtrip(tmp_path, sample_vpd_pose):
    path = tmp_path / "pose.txt"
    pypmxvmd.save_vpd_text(sample_vpd_pose, path)

    loaded = pypmxvmd.load_vpd_text(path)

    assert loaded.model_name == sample_vpd_pose.model_name
    assert loaded.bone_poses[0].bone_name == "センター"
    assert loaded.bone_poses[0].position == pytest.approx([0.0, 10.0, 0.0])
    assert loaded.bone_poses[0].rotation == pytest.approx([0.1, 0.2, 0.3, 0.9])
    assert loaded.morph_poses[0].morph_name == "笑い"
    assert loaded.morph_poses[0].weight == pytest.approx(0.8)


def test_auto_text_roundtrip(tmp_path, sample_vmd_motion):
    path = tmp_path / "auto.txt"
    pypmxvmd.save_text(sample_vmd_motion, path)

    loaded = pypmxvmd.load_text(path)

    assert isinstance(loaded, pypmxvmd.VmdMotion)
    assert loaded.header.model_name == "TestModel"


def test_save_text_rejects_unsupported_object(tmp_path):
    with pytest.raises(ValueError, match="Unsupported data type"):
        pypmxvmd.save_text(object(), tmp_path / "output.txt")
