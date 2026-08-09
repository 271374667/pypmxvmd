"""Field-level parity tests for standard, fast, and Cython parsers."""

from pathlib import Path

import pytest

from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser

try:
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython
    from pypmxvmd.common.parsers._fast_vmd import parse_vmd_cython

    CYTHON_AVAILABLE = True
except ImportError:
    parse_pmx_cython = None
    parse_vmd_cython = None
    CYTHON_AVAILABLE = False


DATA_DIR = Path(__file__).parent / "data"


def corpus_cases(directory, suffix):
    files = sorted((DATA_DIR / directory).rglob(f"*.{suffix}"))
    if not files:
        return [
            pytest.param(
                None,
                id=f"no-{suffix}-corpus",
                marks=pytest.mark.skip(
                    reason=f"optional local {suffix.upper()} corpus not found"
                ),
            )
        ]
    return [
        pytest.param(
            path,
            id=str(path.relative_to(DATA_DIR)).replace("\\", "/"),
        )
        for path in files
    ]


PMX_CASES = corpus_cases("test_models", "pmx")
VMD_CASES = corpus_cases("test_vmds", "vmd")


@pytest.mark.corpus
@pytest.mark.slow
class TestPmxParserParity:
    @pytest.mark.parametrize("pmx_path", PMX_CASES)
    def test_standard_vs_fast(self, pmx_path, assert_model_equal):
        parser = PmxParser()
        standard = parser._parse_file_python(pmx_path)
        fast = parser.parse_file_fast(pmx_path)

        assert_model_equal(fast, standard, "pmx")

    @pytest.mark.cython
    @pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
    @pytest.mark.parametrize("pmx_path", PMX_CASES)
    def test_standard_vs_cython(self, pmx_path, assert_model_equal):
        standard = PmxParser()._parse_file_python(pmx_path)
        cython = parse_pmx_cython(pmx_path.read_bytes(), False)

        assert_model_equal(cython, standard, "pmx")

    @pytest.mark.parametrize("pmx_path", PMX_CASES)
    def test_explicit_partial_path_matches_standard(
        self, pmx_path, assert_model_equal
    ):
        parser = PmxParser()
        standard = parser._parse_file_python(pmx_path)
        partial = parser.parse_file_partial(pmx_path)

        assert_model_equal(partial.model, standard, "pmx")
        assert not partial.report.is_complete
        assert partial.report.missing_sections[0] == "bones"


@pytest.mark.corpus
@pytest.mark.slow
class TestVmdParserParity:
    @pytest.mark.parametrize("vmd_path", VMD_CASES)
    def test_standard_vs_fast(self, vmd_path, assert_model_equal):
        parser = VmdParser()
        standard = parser._parse_file_python(vmd_path)
        fast = parser.parse_file_fast(vmd_path)

        assert_model_equal(fast, standard, "vmd")

    @pytest.mark.cython
    @pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
    @pytest.mark.parametrize("vmd_path", VMD_CASES)
    def test_standard_vs_cython(self, vmd_path, assert_model_equal):
        standard = VmdParser()._parse_file_python(vmd_path)
        cython = parse_vmd_cython(vmd_path.read_bytes(), False)

        assert_model_equal(cython, standard, "vmd")

    @pytest.mark.parametrize("vmd_path", VMD_CASES)
    def test_default_path_matches_standard(self, vmd_path, assert_model_equal):
        parser = VmdParser()
        standard = parser._parse_file_python(vmd_path)
        default = parser.parse_file(vmd_path)

        assert_model_equal(default, standard, "vmd")


def test_cython_availability_flags_agree():
    from pypmxvmd.common.parsers import pmx_parser, vmd_parser

    assert isinstance(pmx_parser._CYTHON_AVAILABLE, bool)
    assert isinstance(vmd_parser._CYTHON_AVAILABLE, bool)
    assert pmx_parser._CYTHON_AVAILABLE == vmd_parser._CYTHON_AVAILABLE
