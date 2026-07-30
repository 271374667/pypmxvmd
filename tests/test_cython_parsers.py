"""Correctness, integrity, and trend tests for native Cython modules."""

import time
from pathlib import Path

import pytest

try:
    from pypmxvmd.common.io._fast_binary import FastBinaryReader
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython
    from pypmxvmd.common.parsers._fast_vmd import parse_vmd_cython

    CYTHON_AVAILABLE = True
except ImportError:
    FastBinaryReader = None
    parse_pmx_cython = None
    parse_vmd_cython = None
    CYTHON_AVAILABLE = False

from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser


pytestmark = [
    pytest.mark.cython,
    pytest.mark.skipif(
        not CYTHON_AVAILABLE,
        reason="Cython modules not compiled; run uv sync --group dev",
    ),
]

DATA_DIR = Path(__file__).parent / "data"


class TestFastBinaryReader:
    def test_read_bytes_and_remaining(self):
        reader = FastBinaryReader(b"\x01\x02\x03\x04\x05")

        assert reader.read_bytes(3) == b"\x01\x02\x03"
        assert reader.get_remaining() == 2
        assert reader.get_position() == 3

    def test_set_position(self):
        reader = FastBinaryReader(b"abcdef")

        reader.set_position(4)

        assert reader.get_position() == 4
        assert reader.read_bytes(2) == b"ef"

    def test_out_of_bounds_read_fails(self):
        reader = FastBinaryReader(b"\x01")

        with pytest.raises(ValueError):
            reader.read_bytes(2)

    @pytest.mark.parametrize(
        ("method", "args"),
        [
            ("read_byte", ()),
            ("read_sbyte", ()),
            ("read_ushort", ()),
            ("read_short", ()),
            ("read_uint", ()),
            ("read_int", ()),
            ("read_float", ()),
            ("read_float3", ()),
            ("read_float4", ()),
            ("read_bytes", (1,)),
            ("read_string_fixed", (1,)),
            ("read_string_variable", ()),
            ("read_index", (1,)),
        ],
    )
    def test_truncated_primitive_read_fails(self, method, args):
        reader = FastBinaryReader(b"")

        with pytest.raises(ValueError):
            getattr(reader, method)(*args)

    @pytest.mark.parametrize("position", [-1, 4])
    def test_invalid_position_fails(self, position):
        reader = FastBinaryReader(b"abc")

        with pytest.raises(ValueError):
            reader.set_position(position)

    def test_invalid_counts_fail_without_moving_position(self):
        reader = FastBinaryReader(b"abc")

        with pytest.raises(ValueError):
            reader.read_bytes(-1)
        with pytest.raises(ValueError):
            reader.read_string_fixed(-1)
        with pytest.raises(ValueError):
            reader.skip(-1)

        assert reader.get_position() == 0

    def test_truncated_variable_string_fails_without_moving_position(self):
        reader = FastBinaryReader(b"\x02\x00\x00\x00x")

        with pytest.raises(ValueError):
            reader.read_string_variable()

        assert reader.get_position() == 0

    def test_signed_byte_index_advances_position(self):
        reader = FastBinaryReader(b"\xff\x02")

        assert reader.read_index(1, signed=True) == -1
        assert reader.get_position() == 1
        assert reader.read_index(1, signed=False) == 2
        assert reader.get_position() == 2

    @pytest.mark.parametrize("size", [-1, 0, 3, 5])
    def test_invalid_index_size_fails(self, size):
        reader = FastBinaryReader(b"\x00\x00\x00\x00")

        with pytest.raises(ValueError):
            reader.read_index(size)


def test_synthetic_vmd_matches_standard(
    sample_vmd_file, assert_model_equal
):
    standard = VmdParser()._parse_file_python(sample_vmd_file)
    cython = parse_vmd_cython(sample_vmd_file.read_bytes(), False)

    assert_model_equal(cython, standard, "vmd")


def test_synthetic_pmx_matches_standard(
    sample_pmx_file, assert_model_equal
):
    standard = PmxParser()._parse_file_python(sample_pmx_file)
    cython = parse_pmx_cython(sample_pmx_file.read_bytes(), False)

    assert_model_equal(cython, standard, "pmx")


def test_native_modules_and_symbols_are_available():
    import pypmxvmd.common.io._fast_binary as fast_binary
    import pypmxvmd.common.parsers._fast_pmx as fast_pmx
    import pypmxvmd.common.parsers._fast_vmd as fast_vmd

    modules = (
        (fast_binary, "FastBinaryReader"),
        (fast_pmx, "parse_pmx_cython"),
        (fast_vmd, "parse_vmd_cython"),
    )
    for module, symbol in modules:
        assert Path(module.__file__).suffix.lower() in {".pyd", ".so"}
        assert hasattr(module, symbol)


def largest_corpus_case(directory, suffix):
    files = list((DATA_DIR / directory).rglob(f"*.{suffix}"))
    if not files:
        return pytest.param(
            None,
            id=f"no-{suffix}-benchmark",
            marks=pytest.mark.skip(
                reason=f"optional local {suffix.upper()} corpus not found"
            ),
        )
    path = max(files, key=lambda item: item.stat().st_size)
    return pytest.param(path, id=path.stem)


@pytest.mark.benchmark
@pytest.mark.corpus
@pytest.mark.parametrize(
    "vmd_path",
    [largest_corpus_case("test_vmds", "vmd")],
)
def test_vmd_cython_benchmark_trend(vmd_path):
    parser = VmdParser()
    start = time.perf_counter()
    parser._parse_file_python(vmd_path)
    python_time = time.perf_counter() - start
    start = time.perf_counter()
    parse_vmd_cython(vmd_path.read_bytes(), False)
    cython_time = time.perf_counter() - start

    assert python_time >= 0.0
    assert cython_time >= 0.0
    print(f"VMD trend: Python={python_time:.4f}s Cython={cython_time:.4f}s")


@pytest.mark.benchmark
@pytest.mark.corpus
@pytest.mark.parametrize(
    "pmx_path",
    [largest_corpus_case("test_models", "pmx")],
)
def test_pmx_cython_benchmark_trend(pmx_path):
    parser = PmxParser()
    start = time.perf_counter()
    parser._parse_file_python(pmx_path)
    python_time = time.perf_counter() - start
    start = time.perf_counter()
    parse_pmx_cython(pmx_path.read_bytes(), False)
    cython_time = time.perf_counter() - start

    assert python_time >= 0.0
    assert cython_time >= 0.0
    print(f"PMX trend: Python={python_time:.4f}s Cython={cython_time:.4f}s")
