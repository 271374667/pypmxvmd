#!/usr/bin/env python3
"""
解析器优化验证测试

验证优化后的快速解析方法与原始方法产生相同的结果。
支持测试纯Python版本、快速解析版本和Cython优化版本。
"""

import sys
import time
from pathlib import Path

import pytest

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser

# 检查Cython模块是否可用
try:
    from pypmxvmd.common.parsers._fast_vmd import parse_vmd_cython
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython
    CYTHON_AVAILABLE = True
except ImportError:
    CYTHON_AVAILABLE = False


def compare_pmx_results(original, fast, tolerance=1e-6):
    """比较两个PMX解析结果是否相同"""
    errors = []

    # 比较header
    if original.header.version != fast.header.version:
        errors.append(f"Header version mismatch: {original.header.version} vs {fast.header.version}")
    if original.header.name_jp != fast.header.name_jp:
        errors.append(f"Header name_jp mismatch: '{original.header.name_jp}' vs '{fast.header.name_jp}'")
    if original.header.name_en != fast.header.name_en:
        errors.append(f"Header name_en mismatch: '{original.header.name_en}' vs '{fast.header.name_en}'")

    # 比较顶点数量
    if len(original.vertices) != len(fast.vertices):
        errors.append(f"Vertex count mismatch: {len(original.vertices)} vs {len(fast.vertices)}")
    else:
        # 抽样比较顶点
        sample_indices = [0, len(original.vertices)//4, len(original.vertices)//2,
                         3*len(original.vertices)//4, len(original.vertices)-1]
        for idx in sample_indices:
            if idx < len(original.vertices):
                ov = original.vertices[idx]
                fv = fast.vertices[idx]

                for i, (op, fp) in enumerate(zip(ov.position, fv.position)):
                    if abs(op - fp) > tolerance:
                        errors.append(f"Vertex {idx} position[{i}] mismatch: {op} vs {fp}")
                        break

                for i, (on, fn) in enumerate(zip(ov.normal, fv.normal)):
                    if abs(on - fn) > tolerance:
                        errors.append(f"Vertex {idx} normal[{i}] mismatch: {on} vs {fn}")
                        break

    # 比较面数量
    if len(original.faces) != len(fast.faces):
        errors.append(f"Face count mismatch: {len(original.faces)} vs {len(fast.faces)}")
    else:
        # 抽样比较面
        sample_indices = [0, len(original.faces)//2, len(original.faces)-1]
        for idx in sample_indices:
            if idx < len(original.faces):
                if original.faces[idx] != fast.faces[idx]:
                    errors.append(f"Face {idx} mismatch: {original.faces[idx]} vs {fast.faces[idx]}")

    # 比较材质数量
    if len(original.materials) != len(fast.materials):
        errors.append(f"Material count mismatch: {len(original.materials)} vs {len(fast.materials)}")
    else:
        for i, (om, fm) in enumerate(zip(original.materials, fast.materials)):
            if om.name_jp != fm.name_jp:
                errors.append(f"Material {i} name_jp mismatch: '{om.name_jp}' vs '{fm.name_jp}'")
            if om.face_count != fm.face_count:
                errors.append(f"Material {i} face_count mismatch: {om.face_count} vs {fm.face_count}")

    return errors


def compare_vmd_results(original, fast, tolerance=1e-6):
    """比较两个VMD解析结果是否相同"""
    errors = []

    # 比较header
    if original.header.version != fast.header.version:
        errors.append(f"Header version mismatch: {original.header.version} vs {fast.header.version}")
    if original.header.model_name != fast.header.model_name:
        errors.append(f"Header model_name mismatch: '{original.header.model_name}' vs '{fast.header.model_name}'")

    # 比较骨骼帧数量
    if len(original.bone_frames) != len(fast.bone_frames):
        errors.append(f"Bone frame count mismatch: {len(original.bone_frames)} vs {len(fast.bone_frames)}")
    else:
        # 抽样比较骨骼帧
        count = len(original.bone_frames)
        sample_indices = [0] if count > 0 else []
        if count > 1:
            sample_indices.extend([count//4, count//2, 3*count//4, count-1])
        sample_indices = list(set(idx for idx in sample_indices if 0 <= idx < count))

        for idx in sample_indices:
            ob = original.bone_frames[idx]
            fb = fast.bone_frames[idx]

            if ob.bone_name != fb.bone_name:
                errors.append(f"Bone frame {idx} name mismatch: '{ob.bone_name}' vs '{fb.bone_name}'")
            if ob.frame_number != fb.frame_number:
                errors.append(f"Bone frame {idx} frame_number mismatch: {ob.frame_number} vs {fb.frame_number}")

            for i, (op, fp) in enumerate(zip(ob.position, fb.position)):
                if abs(op - fp) > tolerance:
                    errors.append(f"Bone frame {idx} position[{i}] mismatch: {op} vs {fp}")
                    break

            for i, (orot, frot) in enumerate(zip(ob.rotation, fb.rotation)):
                if abs(orot - frot) > tolerance:
                    errors.append(f"Bone frame {idx} rotation[{i}] mismatch: {orot} vs {frot}")
                    break

    # 比较变形帧数量
    if len(original.morph_frames) != len(fast.morph_frames):
        errors.append(f"Morph frame count mismatch: {len(original.morph_frames)} vs {len(fast.morph_frames)}")
    else:
        count = len(original.morph_frames)
        sample_indices = [0] if count > 0 else []
        if count > 1:
            sample_indices.extend([count//2, count-1])
        sample_indices = list(set(idx for idx in sample_indices if 0 <= idx < count))

        for idx in sample_indices:
            om = original.morph_frames[idx]
            fm = fast.morph_frames[idx]

            if om.morph_name != fm.morph_name:
                errors.append(f"Morph frame {idx} name mismatch: '{om.morph_name}' vs '{fm.morph_name}'")
            if om.frame_number != fm.frame_number:
                errors.append(f"Morph frame {idx} frame_number mismatch: {om.frame_number} vs {fm.frame_number}")
            if abs(om.weight - fm.weight) > tolerance:
                errors.append(f"Morph frame {idx} weight mismatch: {om.weight} vs {fm.weight}")

    # 比较其他帧数量
    if len(original.camera_frames) != len(fast.camera_frames):
        errors.append(f"Camera frame count mismatch: {len(original.camera_frames)} vs {len(fast.camera_frames)}")

    if len(original.light_frames) != len(fast.light_frames):
        errors.append(f"Light frame count mismatch: {len(original.light_frames)} vs {len(fast.light_frames)}")

    if len(original.shadow_frames) != len(fast.shadow_frames):
        errors.append(f"Shadow frame count mismatch: {len(original.shadow_frames)} vs {len(fast.shadow_frames)}")

    if len(original.ik_frames) != len(fast.ik_frames):
        errors.append(f"IK frame count mismatch: {len(original.ik_frames)} vs {len(fast.ik_frames)}")

    return errors


class TestPmxParserOptimization:
    """PMX解析器优化正确性测试"""

    def test_python_vs_fast(self, test_data_dir):
        """测试纯Python版本与快速解析版本的一致性"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        parser = PmxParser()
        pmx_file = pmx_files[0]

        # 使用纯Python方法解析
        python_result = parser._parse_file_python(pmx_file)

        # 使用快速方法解析
        fast_result = parser.parse_file_fast(pmx_file)

        # 比较结果
        errors = compare_pmx_results(python_result, fast_result)
        assert not errors, f"Results mismatch:\n" + "\n".join(errors[:10])

    @pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
    def test_python_vs_cython(self, test_data_dir):
        """测试纯Python版本与Cython版本的一致性"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        parser = PmxParser()
        pmx_file = pmx_files[0]

        # 使用纯Python方法解析
        python_result = parser._parse_file_python(pmx_file)

        # 使用Cython方法解析
        cython_result = parser.parse_file_cython(pmx_file)

        # 比较结果
        errors = compare_pmx_results(python_result, cython_result)
        assert not errors, f"Results mismatch:\n" + "\n".join(errors[:10])

    def test_default_parse_method(self, test_data_dir):
        """测试默认的parse_file方法（应该自动选择最佳方法）"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        if not pmx_files:
            pytest.skip("No PMX test files found")

        parser = PmxParser()
        pmx_file = pmx_files[0]

        # 使用默认方法解析（应该使用Cython如果可用）
        result = parser.parse_file(pmx_file)

        # 验证结果有效
        assert result.header is not None
        assert len(result.vertices) > 0
        assert len(result.faces) > 0


class TestVmdParserOptimization:
    """VMD解析器优化正确性测试"""

    def test_python_vs_fast(self, test_data_dir):
        """测试纯Python版本与快速解析版本的一致性"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        parser = VmdParser()
        vmd_file = vmd_files[0]

        # 使用纯Python方法解析
        python_result = parser._parse_file_python(vmd_file)

        # 使用快速方法解析
        fast_result = parser.parse_file_fast(vmd_file)

        # 比较结果
        errors = compare_vmd_results(python_result, fast_result)
        assert not errors, f"Results mismatch:\n" + "\n".join(errors[:10])

    @pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
    def test_python_vs_cython(self, test_data_dir):
        """测试纯Python版本与Cython版本的一致性"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        parser = VmdParser()
        vmd_file = vmd_files[0]

        # 使用纯Python方法解析
        python_result = parser._parse_file_python(vmd_file)

        # 使用Cython方法解析
        cython_result = parser.parse_file_cython(vmd_file)

        # 比较结果
        errors = compare_vmd_results(python_result, cython_result)
        assert not errors, f"Results mismatch:\n" + "\n".join(errors[:10])

    def test_default_parse_method(self, test_data_dir):
        """测试默认的parse_file方法（应该自动选择最佳方法）"""
        vmd_files = list(test_data_dir.rglob("*.vmd"))
        if not vmd_files:
            pytest.skip("No VMD test files found")

        parser = VmdParser()
        vmd_file = vmd_files[0]

        # 使用默认方法解析（应该使用Cython如果可用）
        result = parser.parse_file(vmd_file)

        # 验证结果有效
        assert result.header is not None


class TestCythonAvailability:
    """测试Cython模块可用性检测"""

    def test_cython_detection(self):
        """测试Cython模块检测逻辑"""
        from pypmxvmd.common.parsers import vmd_parser, pmx_parser

        # 检测应该返回布尔值
        assert isinstance(vmd_parser._CYTHON_AVAILABLE, bool)
        assert isinstance(pmx_parser._CYTHON_AVAILABLE, bool)

        # 两个模块的检测结果应该一致
        assert vmd_parser._CYTHON_AVAILABLE == pmx_parser._CYTHON_AVAILABLE

    def test_fallback_behavior(self, test_data_dir):
        """测试Cython不可用时的回退行为"""
        pmx_files = list(test_data_dir.rglob("*.pmx"))
        vmd_files = list(test_data_dir.rglob("*.vmd"))

        pmx_parser = PmxParser()
        vmd_parser = VmdParser()

        # 即使Cython不可用，parse_file也应该正常工作
        if pmx_files:
            result = pmx_parser.parse_file(pmx_files[0])
            assert result is not None

        if vmd_files:
            result = vmd_parser.parse_file(vmd_files[0])
            assert result is not None


def main():
    """运行所有优化验证测试（命令行模式）"""
    print("=" * 60)
    print("PyPMXVMD Parser Optimization Validation Test")
    print("=" * 60)
    print(f"Cython available: {CYTHON_AVAILABLE}")
    print()

    # 查找测试文件
    test_dir = Path(__file__).parent
    pmx_files = list(test_dir.glob("**/*.pmx"))
    vmd_files = list(test_dir.glob("**/*.vmd"))

    all_passed = True

    # 测试PMX解析器
    if pmx_files:
        print("\n" + "=" * 60)
        print("Testing PMX Parser Optimization")
        print("=" * 60)

        parser = PmxParser()
        pmx_file = pmx_files[0]
        print(f"\nTesting file: {pmx_file.name}")

        try:
            # 纯Python解析
            start = time.perf_counter()
            python_result = parser._parse_file_python(pmx_file)
            python_time = time.perf_counter() - start

            # 快速解析
            start = time.perf_counter()
            fast_result = parser.parse_file_fast(pmx_file)
            fast_time = time.perf_counter() - start

            errors = compare_pmx_results(python_result, fast_result)

            if errors:
                print(f"  [FAIL] Python vs Fast: Results mismatch!")
                for error in errors[:5]:
                    print(f"     - {error}")
                all_passed = False
            else:
                speedup = python_time / fast_time if fast_time > 0 else float('inf')
                print(f"  [PASS] Python vs Fast")
                print(f"     Python: {python_time:.4f}s, Fast: {fast_time:.4f}s, Speedup: {speedup:.2f}x")

            # Cython解析
            if CYTHON_AVAILABLE:
                start = time.perf_counter()
                cython_result = parser.parse_file_cython(pmx_file)
                cython_time = time.perf_counter() - start

                errors = compare_pmx_results(python_result, cython_result)
                if errors:
                    print(f"  [FAIL] Python vs Cython: Results mismatch!")
                    all_passed = False
                else:
                    speedup = python_time / cython_time if cython_time > 0 else float('inf')
                    print(f"  [PASS] Python vs Cython")
                    print(f"     Python: {python_time:.4f}s, Cython: {cython_time:.4f}s, Speedup: {speedup:.2f}x")

        except Exception as e:
            print(f"  [FAIL] Test failed: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    else:
        print("No PMX test files found")

    # 测试VMD解析器
    if vmd_files:
        print("\n" + "=" * 60)
        print("Testing VMD Parser Optimization")
        print("=" * 60)

        parser = VmdParser()
        vmd_file = vmd_files[0]
        print(f"\nTesting file: {vmd_file.name}")

        try:
            # 纯Python解析
            start = time.perf_counter()
            python_result = parser._parse_file_python(vmd_file)
            python_time = time.perf_counter() - start

            # 快速解析
            start = time.perf_counter()
            fast_result = parser.parse_file_fast(vmd_file)
            fast_time = time.perf_counter() - start

            errors = compare_vmd_results(python_result, fast_result)

            if errors:
                print(f"  [FAIL] Python vs Fast: Results mismatch!")
                for error in errors[:5]:
                    print(f"     - {error}")
                all_passed = False
            else:
                speedup = python_time / fast_time if fast_time > 0 else float('inf')
                print(f"  [PASS] Python vs Fast")
                print(f"     Python: {python_time:.4f}s, Fast: {fast_time:.4f}s, Speedup: {speedup:.2f}x")

            # Cython解析
            if CYTHON_AVAILABLE:
                start = time.perf_counter()
                cython_result = parser.parse_file_cython(vmd_file)
                cython_time = time.perf_counter() - start

                errors = compare_vmd_results(python_result, cython_result)
                if errors:
                    print(f"  [FAIL] Python vs Cython: Results mismatch!")
                    all_passed = False
                else:
                    speedup = python_time / cython_time if cython_time > 0 else float('inf')
                    print(f"  [PASS] Python vs Cython")
                    print(f"     Python: {python_time:.4f}s, Cython: {cython_time:.4f}s, Speedup: {speedup:.2f}x")

        except Exception as e:
            print(f"  [FAIL] Test failed: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    else:
        print("No VMD test files found")

    # 总结
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    if all_passed:
        print("[PASS] All tests passed!")
        return 0
    else:
        print("[FAIL] Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
