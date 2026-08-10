"""Compatibility and fail-closed mode tests for the PMX public API."""

import inspect

import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import PmxFrame, PmxRigidBody, PmxSoftBody
from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.pmx import PmxDocument, PmxParseResult, UnsupportedPmxFeatureError
from tests.test_pmx_integrity import _minimal_complete_pmx21_bytes


def _saved_pmx20(tmp_path, model):
    path = tmp_path / "model.pmx"
    pypmxvmd.save_pmx(model, path)
    return path


def test_legacy_positional_parameters_remain_compatible(tmp_path, sample_pmx_model):
    path = _saved_pmx20(tmp_path, sample_pmx_model)

    model = pypmxvmd.load_pmx(path, False)
    result = pypmxvmd.load_pmx_partial(path, False, "fast")
    parser_model = PmxParser().parse_file(path, False)

    assert isinstance(model, pypmxvmd.PmxModel)
    assert isinstance(result, PmxParseResult)
    assert isinstance(parser_model, pypmxvmd.PmxModel)


@pytest.mark.parametrize(
    ("function", "positional_names", "keyword_only_names"),
    [
        (
            pypmxvmd.load_pmx,
            ("file_path", "more_info"),
            ("mode", "implementation", "strict_eof", "track_spans"),
        ),
        (pypmxvmd.save_pmx, ("model", "file_path"), ("mode",)),
        (pypmxvmd.write_pmx, ("model", "file_path"), ("mode",)),
    ],
)
def test_new_mode_parameters_do_not_consume_legacy_positions(
    function, positional_names, keyword_only_names
):
    parameters = inspect.signature(function).parameters

    assert tuple(parameters)[: len(positional_names)] == positional_names
    for name in positional_names:
        assert parameters[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in keyword_only_names:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_strict_and_partial_modes_have_distinct_return_contracts(
    tmp_path, sample_pmx_model
):
    path = _saved_pmx20(tmp_path, sample_pmx_model)

    strict = pypmxvmd.load_pmx(path, mode="strict", implementation="python")
    partial = pypmxvmd.load_pmx(path, mode="partial", implementation="fast")
    auto_partial = pypmxvmd.load(path, mode="partial")

    assert isinstance(strict, pypmxvmd.PmxModel)
    assert isinstance(partial, PmxParseResult)
    assert partial.report.is_complete
    assert isinstance(auto_partial, PmxParseResult)


def test_strict_mode_cannot_disable_eof_contract(tmp_path, sample_pmx_model):
    path = _saved_pmx20(tmp_path, sample_pmx_model)

    with pytest.raises(ValueError, match="requires strict_eof=True"):
        pypmxvmd.load_pmx(path, mode="strict", strict_eof=False)
    with pytest.raises(ValueError, match="always strict"):
        PmxParser().parse_file(path, strict_eof=False)


def test_partial_mode_can_require_complete_pmx21_eof(tmp_path):
    path = tmp_path / "minimal-21.pmx"
    path.write_bytes(_minimal_complete_pmx21_bytes())

    result = pypmxvmd.load_pmx(path, mode="partial")
    assert isinstance(result, PmxParseResult)
    assert result.report.is_complete

    strict_result = pypmxvmd.load_pmx(path, mode="partial", strict_eof=True)
    assert isinstance(strict_result, PmxParseResult)
    assert strict_result.report.is_complete


@pytest.mark.parametrize("mode", ["preserve_layout", "lossless_patch"])
def test_unimplemented_write_modes_preserve_existing_target(
    tmp_path, sample_pmx_model, mode
):
    path = tmp_path / "existing.pmx"
    path.write_bytes(b"original")

    with pytest.raises(UnsupportedPmxFeatureError) as caught:
        pypmxvmd.save_pmx(sample_pmx_model, path, mode=mode)

    assert mode in caught.value.feature
    assert path.read_bytes() == b"original"


def test_document_and_span_modes_have_explicit_return_contracts(
    tmp_path, sample_pmx_model
):
    path = _saved_pmx20(tmp_path, sample_pmx_model)

    assert isinstance(pypmxvmd.load_pmx(path, mode="document"), PmxDocument)
    assert isinstance(pypmxvmd.load_pmx(path, track_spans=True), PmxDocument)
    assert pypmxvmd.load_pmx_partial(path, track_spans=True).field_spans
    assert isinstance(pypmxvmd.load_pmx_document(path), PmxDocument)


@pytest.mark.parametrize("mode", ["unknown", "", 3])
def test_unknown_read_modes_are_rejected(tmp_path, sample_pmx_model, mode):
    path = _saved_pmx20(tmp_path, sample_pmx_model)

    with pytest.raises(ValueError, match="PMX read mode|Unknown PMX read mode"):
        pypmxvmd.load_pmx(path, mode=mode)


@pytest.mark.parametrize("mode", ["unknown", "", 3])
def test_unknown_write_modes_are_rejected(tmp_path, sample_pmx_model, mode):
    path = tmp_path / "unknown.pmx"

    with pytest.raises(ValueError, match="PMX write mode|Unknown PMX write mode"):
        pypmxvmd.save_pmx(sample_pmx_model, path, mode=mode)
    assert not path.exists()


def test_write_pmx_alias_and_auto_save_forward_canonical_mode(
    tmp_path, sample_pmx_model
):
    direct_path = tmp_path / "direct.pmx"
    auto_path = tmp_path / "auto.pmx"

    pypmxvmd.write_pmx(sample_pmx_model, direct_path, mode="canonical")
    pypmxvmd.save(sample_pmx_model, auto_path, mode="canonical")

    assert pypmxvmd.load_pmx(direct_path).is_complete
    assert pypmxvmd.load_pmx(auto_path).is_complete


def test_pmx_options_are_not_silently_ignored_for_other_formats(
    tmp_path, sample_vmd_motion
):
    path = tmp_path / "motion.vmd"
    pypmxvmd.save_vmd(sample_vmd_motion, path)

    with pytest.raises(ValueError, match="PMX mode options"):
        pypmxvmd.load(path, mode="strict")
    with pytest.raises(ValueError, match="PMX write mode"):
        pypmxvmd.save(sample_vmd_motion, path, mode="canonical")


def test_legacy_model_collection_aliases_remain_live():
    model = pypmxvmd.PmxModel()
    frames = [PmxFrame(name_jp="表示")]
    rigid_bodies = [PmxRigidBody(name_jp="剛体")]
    soft_bodies = [PmxSoftBody()]

    model.display_frames = frames
    model.rigid_bodies = rigid_bodies
    model.soft_bodies = soft_bodies

    assert model.frames is frames
    assert model.rigidbodies is rigid_bodies
    assert model.softbodies is soft_bodies


def test_mode_specific_exception_types_are_public():
    assert issubclass(pypmxvmd.IncompletePmxError, ValueError)
    assert issubclass(pypmxvmd.PmxValidationError, ValueError)
    assert issubclass(pypmxvmd.UnsupportedPmxFeatureError, ValueError)
