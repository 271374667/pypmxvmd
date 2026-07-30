"""Focused smoke tests for public API dispatch errors."""

import pytest

import pypmxvmd


def test_load_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "model.obj"
    path.write_text("not an MMD file", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file type: \\.obj"):
        pypmxvmd.load(path)


def test_save_rejects_unsupported_object(tmp_path):
    with pytest.raises(ValueError, match="Unsupported data type"):
        pypmxvmd.save(object(), tmp_path / "output.vmd")


def test_auto_detects_minimal_vpd(tmp_path):
    path = tmp_path / "auto.vpd"
    path.write_text(
        "Vocaloid Pose Data file\n\nAuto.osm;\n0;\n",
        encoding="shift_jis",
    )

    loaded = pypmxvmd.load(path)

    assert isinstance(loaded, pypmxvmd.VpdPose)
    assert loaded.model_name == "Auto"
