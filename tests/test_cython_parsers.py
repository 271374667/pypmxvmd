#!/usr/bin/env python3
"""
Cython解析器测试

测试Cython优化模块的功能正确性、性能和兼容性。
"""

import sys
import time
from pathlib import Path

import pytest

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 检查Cython模块是否可用
try:
    from pypmxvmd.common.parsers._fast_vmd import parse_vmd_cython
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython
    from pypmxvmd.common.io._fast_binary import FastBinaryReader
    CYTHON_AVAILABLE = True
except ImportError:
    CYTHON_AVAILABLE = False
    parse_vmd_cython = None
    parse_pmx_cython = None
    FastBinaryReader = None

from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser


# 如果Cython不可用，跳过所有测试
pytestmark = pytest.mark.skipif(
    not CYTHON_AVAILABLE,
    reason="Cython modules not compiled. Run 'python scripts/build_cython.py' to compile."
)


class TestFastBinaryReader:
    """测试FastBinaryReader Cython模块"""

    def test_reader_creation(self):
        """测试FastBinaryReader创建"""
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        reader = FastBinaryReader(data)
        assert reader is not None

    def test_read_bytes(self):
        """测试读取字节"""
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        reader = FastBinaryReader(data)
        result = reader.read_bytes(4)
        assert result == b"\x01\x02\x03\x04"

    def test_read_uint(self):
        """测试读取无符号整数"""
        # Little-endian uint32: 0x04030201 = 67305985
        data = b"\x01\x02\x03\x04"
        reader = FastBinaryReader(data)
        result = reader.read_uint()
        assert result == 67305985

    def test_read_float(self):
        """测试读取浮点数"""
        import struct
        value = 3.14159
        data = struct.pack("<f", value)
        reader = FastBinaryReader(data)
        result = reader.read_float()
        assert abs(result - value) < 1e-5

    def test_position_tracking(self):
        """测试位置跟踪"""
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        reader = FastBinaryReader(data)
        assert reader.get_position() == 0
        reader.read_bytes(4)
        assert reader.get_position() == 4
        reader.read_bytes(2)
        assert reader.get_position() == 6

    def test_skip(self):
        """测试跳过字节"""
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        reader = FastBinaryReader(data)
        reader.skip(3)
        assert reader.get_position() == 3
        result = reader.read_bytes(1)
        assert result == b"\x04"

    def test_get_remaining(self):
        """测试剩余大小计算"""
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        reader = FastBinaryReader(data)
        assert reader.get_remaining() == 8
        reader.read_bytes(3)
        assert reader.get_remaining() == 5


class TestCythonVmdParser:
    """测试Cython VMD解析器"""

    def test_parse_vmd_cython_function(self, test_data_dir):
        """测试parse_vmd_cython函数直接调用"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        vmd_file = vmd_files[0]
        with open(vmd_file, 'rb') as f:
            data = f.read()

        result = parse_vmd_cython(data, False)
        assert result is not None
        assert result.header is not None

    def test_cython_vs_python_vmd(self, test_data_dir):
        """比较Cython和Python解析结果"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        parser = VmdParser()
        vmd_file = vmd_files[0]

        # Python解析
        python_result = parser._parse_file_python(vmd_file)

        # Cython解析
        cython_result = parser.parse_file_cython(vmd_file)

        # 比较基本属性
        assert python_result.header.version == cython_result.header.version
        assert python_result.header.model_name == cython_result.header.model_name
        assert len(python_result.bone_frames) == len(cython_result.bone_frames)
        assert len(python_result.morph_frames) == len(cython_result.morph_frames)

    def test_cython_vmd_performance(self, test_data_dir):
        """测试Cython VMD解析性能"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        parser = VmdParser()
        vmd_file = max(vmd_files, key=lambda f: f.stat().st_size)

        # Python解析时间
        start = time.perf_counter()
        parser._parse_file_python(vmd_file)
        python_time = time.perf_counter() - start

        # Cython解析时间
        start = time.perf_counter()
        parser.parse_file_cython(vmd_file)
        cython_time = time.perf_counter() - start

        # Cython应该更快（至少不比Python慢太多）
        speedup = python_time / cython_time if cython_time > 0 else float('inf')
        print(f"\nVMD Performance: Python={python_time:.4f}s, Cython={cython_time:.4f}s, Speedup={speedup:.2f}x")
        # 允许小幅度波动，但Cython不应该比Python慢超过20%
        assert cython_time <= python_time * 1.2, f"Cython slower than expected: {speedup:.2f}x"


class TestCythonPmxParser:
    """测试Cython PMX解析器"""

    def test_parse_pmx_cython_function(self, test_data_dir):
        """测试parse_pmx_cython函数直接调用"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        pmx_file = pmx_files[0]
        with open(pmx_file, 'rb') as f:
            data = f.read()

        result = parse_pmx_cython(data, False)
        assert result is not None
        assert result.header is not None

    def test_cython_vs_python_pmx(self, test_data_dir):
        """比较Cython和Python解析结果"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        parser = PmxParser()
        pmx_file = pmx_files[0]

        # Python解析
        python_result = parser._parse_file_python(pmx_file)

        # Cython解析
        cython_result = parser.parse_file_cython(pmx_file)

        # 比较基本属性
        assert python_result.header.version == cython_result.header.version
        assert python_result.header.name_jp == cython_result.header.name_jp
        assert len(python_result.vertices) == len(cython_result.vertices)
        assert len(python_result.faces) == len(cython_result.faces)
        assert len(python_result.materials) == len(cython_result.materials)

    def test_cython_pmx_performance(self, test_data_dir):
        """测试Cython PMX解析性能"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        parser = PmxParser()
        pmx_file = max(pmx_files, key=lambda f: f.stat().st_size)

        # Python解析时间
        start = time.perf_counter()
        parser._parse_file_python(pmx_file)
        python_time = time.perf_counter() - start

        # Cython解析时间
        start = time.perf_counter()
        parser.parse_file_cython(pmx_file)
        cython_time = time.perf_counter() - start

        # Cython应该更快
        speedup = python_time / cython_time if cython_time > 0 else float('inf')
        print(f"\nPMX Performance: Python={python_time:.4f}s, Cython={cython_time:.4f}s, Speedup={speedup:.2f}x")
        assert cython_time <= python_time * 1.2, f"Cython slower than expected: {speedup:.2f}x"


class TestDefaultParserBehavior:
    """测试默认解析器行为（自动选择Cython）"""

    def test_vmd_default_uses_cython(self, test_data_dir):
        """验证VMD默认使用Cython解析"""
        from pypmxvmd.common.parsers import vmd_parser
        assert vmd_parser._CYTHON_AVAILABLE is True

    def test_pmx_default_uses_cython(self, test_data_dir):
        """验证PMX默认使用Cython解析"""
        from pypmxvmd.common.parsers import pmx_parser
        assert pmx_parser._CYTHON_AVAILABLE is True

    def test_vmd_parse_file_works(self, test_data_dir):
        """测试VMD parse_file正常工作"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        parser = VmdParser()
        result = parser.parse_file(vmd_files[0])

        assert result is not None
        assert result.header is not None
        # 默认应该使用Cython，结果应该有效

    def test_pmx_parse_file_works(self, test_data_dir):
        """测试PMX parse_file正常工作"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        parser = PmxParser()
        result = parser.parse_file(pmx_files[0])

        assert result is not None
        assert result.header is not None
        assert len(result.vertices) > 0


class TestCythonModuleIntegrity:
    """测试Cython模块完整性"""

    def test_all_cython_modules_available(self):
        """验证所有Cython模块都可用"""
        from pypmxvmd.common.io._fast_binary import FastBinaryReader
        from pypmxvmd.common.parsers._fast_vmd import parse_vmd_cython
        from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython

        assert FastBinaryReader is not None
        assert parse_vmd_cython is not None
        assert parse_pmx_cython is not None

    def test_cython_module_attributes(self):
        """测试Cython模块属性"""
        import pypmxvmd.common.io._fast_binary as fast_binary
        import pypmxvmd.common.parsers._fast_vmd as fast_vmd
        import pypmxvmd.common.parsers._fast_pmx as fast_pmx

        # 验证模块有__file__属性（已编译的.pyd文件）
        assert hasattr(fast_binary, '__file__')
        assert hasattr(fast_vmd, '__file__')
        assert hasattr(fast_pmx, '__file__')

        # 验证文件扩展名是.pyd (Windows) 或 .so (Unix)
        for mod in [fast_binary, fast_vmd, fast_pmx]:
            ext = Path(mod.__file__).suffix
            assert ext in ['.pyd', '.so'], f"Unexpected extension: {ext}"


def main():
    """命令行模式运行测试"""
    print("=" * 60)
    print("Cython Parser Test Suite")
    print("=" * 60)

    if not CYTHON_AVAILABLE:
        print("\n[ERROR] Cython modules not available!")
        print("Run 'python scripts/build_cython.py' to compile Cython modules.")
        return 1

    print("\nCython modules detected:")
    print(f"  - FastBinaryReader: {FastBinaryReader}")
    print(f"  - parse_vmd_cython: {parse_vmd_cython}")
    print(f"  - parse_pmx_cython: {parse_pmx_cython}")

    # 查找测试文件
    test_dir = Path(__file__).parent / "data"
    pmx_files = list(test_dir.rglob("*.pmx"))
    vmd_files = list(test_dir.rglob("*.vmd"))

    print(f"\nTest files found:")
    print(f"  - PMX files: {len(pmx_files)}")
    print(f"  - VMD files: {len(vmd_files)}")

    all_passed = True

    # 测试FastBinaryReader
    print("\n" + "-" * 40)
    print("Testing FastBinaryReader")
    print("-" * 40)
    try:
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        reader = FastBinaryReader(data)
        result = reader.read_bytes(4)
        assert result == b"\x01\x02\x03\x04"
        print("  [PASS] FastBinaryReader works correctly")
    except Exception as e:
        print(f"  [FAIL] FastBinaryReader error: {e}")
        all_passed = False

    # 测试VMD Cython解析
    if vmd_files:
        print("\n" + "-" * 40)
        print("Testing VMD Cython Parser")
        print("-" * 40)
        try:
            parser = VmdParser()
            vmd_file = vmd_files[0]

            start = time.perf_counter()
            result = parser.parse_file_cython(vmd_file)
            elapsed = time.perf_counter() - start

            print(f"  [PASS] Parsed {vmd_file.name} in {elapsed:.4f}s")
            print(f"         Bone frames: {len(result.bone_frames)}")
            print(f"         Morph frames: {len(result.morph_frames)}")
        except Exception as e:
            print(f"  [FAIL] VMD Cython parse error: {e}")
            all_passed = False

    # 测试PMX Cython解析
    if pmx_files:
        print("\n" + "-" * 40)
        print("Testing PMX Cython Parser")
        print("-" * 40)
        try:
            parser = PmxParser()
            pmx_file = pmx_files[0]

            start = time.perf_counter()
            result = parser.parse_file_cython(pmx_file)
            elapsed = time.perf_counter() - start

            print(f"  [PASS] Parsed {pmx_file.name} in {elapsed:.4f}s")
            print(f"         Vertices: {len(result.vertices)}")
            print(f"         Faces: {len(result.faces)}")
            print(f"         Materials: {len(result.materials)}")
        except Exception as e:
            print(f"  [FAIL] PMX Cython parse error: {e}")
            all_passed = False

    # 总结
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    if all_passed:
        print("[PASS] All Cython tests passed!")
        return 0
    else:
        print("[FAIL] Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
