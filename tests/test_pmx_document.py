"""Source-backed PMX document loading and no-op preservation tests."""

import hashlib

import pytest

import pypmxvmd
from pypmxvmd.common.pmx import PmxDocument, PmxPatchError
from tests.test_corpus_parsers import corpus_cases
from tests.test_pmx_integrity import _minimal_complete_pmx21_bytes
from tests.test_pmx_sections_reader import _pmx20_all_sections


def _source_path(tmp_path):
    path = tmp_path / "source.pmx"
    path.write_bytes(_pmx20_all_sections(2)[0])
    return path


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_document_retains_exact_source_model_report_and_fixed_field_spans(tmp_path):
    path = _source_path(tmp_path)

    document = pypmxvmd.load_pmx_document(path, implementation="python")

    assert isinstance(document, PmxDocument)
    assert document.source_bytes == path.read_bytes()
    assert document.model.is_complete
    assert document.report.is_complete
    assert document.loaded_sections == document.report.loaded_sections
    assert document.trailing_bytes == 0
    assert document.field_spans
    assert len({span.field_path for span in document.field_spans}) == len(
        document.field_spans
    )
    assert all(
        left.end_offset <= right.start_offset
        for left, right in zip(document.field_spans, document.field_spans[1:])
    )
    assert str(document.span_for("bones[0].position").field_path) == (
        "bones[0].position"
    )
    with pytest.raises(AttributeError):
        document.source_bytes = b"replacement"


def test_document_modes_and_parser_span_tracking_are_public(tmp_path):
    path = _source_path(tmp_path)

    explicit = pypmxvmd.load_pmx(path, mode="document")
    tracked = pypmxvmd.load_pmx(path, track_spans=True)
    partial = pypmxvmd.load_pmx_partial(path, track_spans=True)
    auto = pypmxvmd.load(path, track_spans=True)

    assert isinstance(explicit, PmxDocument)
    assert isinstance(tracked, PmxDocument)
    assert isinstance(auto, PmxDocument)
    assert partial.report.is_complete
    assert partial.field_spans
    assert partial.field_spans == explicit.field_spans


def test_noop_lossless_writes_are_byte_identical(tmp_path):
    source = _source_path(tmp_path)
    document = pypmxvmd.load_pmx_document(source)
    direct = tmp_path / "direct.pmx"
    automatic = tmp_path / "automatic.pmx"

    assert document.build_patches() == ()
    assert document.encode_lossless() is document.source_bytes
    pypmxvmd.save_pmx(document, direct, mode="lossless_patch")
    pypmxvmd.save(document, automatic)

    assert direct.read_bytes() == source.read_bytes()
    assert automatic.read_bytes() == source.read_bytes()


def test_document_lossless_write_rejects_source_path(tmp_path):
    source = _source_path(tmp_path)
    before = source.read_bytes()
    document = pypmxvmd.load_pmx_document(source)

    with pytest.raises(PmxPatchError, match="cannot overwrite its source"):
        pypmxvmd.save_pmx(document, source, mode="lossless_patch")

    assert source.read_bytes() == before


def test_document_supports_complete_pmx21_and_noop_lossless_bytes(tmp_path):
    source = tmp_path / "complete-21.pmx"
    source.write_bytes(_minimal_complete_pmx21_bytes())

    document = pypmxvmd.load_pmx_document(source)

    assert document.model.is_complete
    assert document.model.softbodies == []
    assert document.encode_lossless() == source.read_bytes()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_real_corpus_noop_lossless_writes_only_to_tmp_and_preserves_sources(
    pmx_path, tmp_path
):
    before_hash = _sha256(pmx_path)
    document = pypmxvmd.load_pmx_document(pmx_path)
    output = tmp_path / pmx_path.name

    pypmxvmd.save_pmx(document, output, mode="lossless_patch")

    assert output.read_bytes() == document.source_bytes
    assert _sha256(pmx_path) == before_hash
