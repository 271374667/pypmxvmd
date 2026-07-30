"""Integration tests for the public binary API."""

import pytest

import pypmxvmd


PUBLIC_FUNCTIONS = (
    "load_vmd",
    "save_vmd",
    "load_pmx",
    "save_pmx",
    "load_vpd",
    "save_vpd",
    "load",
    "save",
)


def test_public_binary_api_is_exported():
    for name in PUBLIC_FUNCTIONS:
        assert callable(getattr(pypmxvmd, name))


def test_vmd_public_api_roundtrip(tmp_path, sample_vmd_motion):
    path = tmp_path / "motion.vmd"
    pypmxvmd.save_vmd(sample_vmd_motion, path)

    loaded = pypmxvmd.load_vmd(path)

    assert loaded.header.version == 2
    assert loaded.header.model_name == "TestModel"
    assert loaded.bone_frames[0].bone_name == "センター"
    assert loaded.bone_frames[0].frame_number == 12
    assert loaded.bone_frames[0].position == pytest.approx([1.0, 2.0, 3.0])
    assert loaded.morph_frames[0].morph_name == "笑い"
    assert loaded.morph_frames[0].weight == pytest.approx(0.75)


def test_pmx_public_api_roundtrip(tmp_path, sample_pmx_model):
    path = tmp_path / "model.pmx"
    pypmxvmd.save_pmx(sample_pmx_model, path)

    loaded = pypmxvmd.load_pmx(path)

    assert loaded.header.version == pytest.approx(2.0)
    assert loaded.header.name_jp == "テストモデル"
    assert len(loaded.vertices) == len(sample_pmx_model.vertices)
    for actual, expected in zip(loaded.vertices, sample_pmx_model.vertices):
        assert actual.position == pytest.approx(expected.position)
    assert loaded.faces == [[0, 1, 2]]
    assert loaded.materials[0].name_jp == "材質"
    assert loaded.materials[0].face_count == 3


def test_vpd_public_api_roundtrip(tmp_path, sample_vpd_pose):
    path = tmp_path / "pose.vpd"
    pypmxvmd.save_vpd(sample_vpd_pose, path)

    loaded = pypmxvmd.load_vpd(path)

    assert loaded.model_name == "TestModel"
    assert loaded.bone_poses[0].bone_name == "センター"
    assert loaded.bone_poses[0].position == pytest.approx([0.0, 10.0, 0.0])
    assert loaded.bone_poses[0].rotation == pytest.approx([0.1, 0.2, 0.3, 0.9])
    assert loaded.morph_poses[0].morph_name == "笑い"
    assert loaded.morph_poses[0].weight == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("fixture_name", "suffix", "expected_type"),
    [
        ("sample_vmd_motion", ".vmd", pypmxvmd.VmdMotion),
        ("sample_pmx_model", ".pmx", pypmxvmd.PmxModel),
        ("sample_vpd_pose", ".vpd", pypmxvmd.VpdPose),
    ],
)
def test_auto_save_and_load(
    request, tmp_path, fixture_name, suffix, expected_type
):
    value = request.getfixturevalue(fixture_name)
    path = tmp_path / f"auto{suffix}"

    pypmxvmd.save(value, path)
    loaded = pypmxvmd.load(path)

    assert isinstance(loaded, expected_type)
