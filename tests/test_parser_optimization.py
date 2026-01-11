#!/usr/bin/env python3
"""
解析器优化验证测试

验证优化后的快速解析方法与原始方法产生相同的结果。
"""

import sys
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser


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

    # 比较相机帧数量
    if len(original.camera_frames) != len(fast.camera_frames):
        errors.append(f"Camera frame count mismatch: {len(original.camera_frames)} vs {len(fast.camera_frames)}")

    # 比较光源帧数量
    if len(original.light_frames) != len(fast.light_frames):
        errors.append(f"Light frame count mismatch: {len(original.light_frames)} vs {len(fast.light_frames)}")

    # 比较阴影帧数量
    if len(original.shadow_frames) != len(fast.shadow_frames):
        errors.append(f"Shadow frame count mismatch: {len(original.shadow_frames)} vs {len(fast.shadow_frames)}")

    # 比较IK帧数量
    if len(original.ik_frames) != len(fast.ik_frames):
        errors.append(f"IK frame count mismatch: {len(original.ik_frames)} vs {len(fast.ik_frames)}")

    return errors


def test_pmx_parser_correctness():
    """测试PMX解析器优化后的正确性"""
    print("\n" + "="*60)
    print("测试PMX解析器优化正确性")
    print("="*60)

    # 查找测试PMX文件
    test_dir = Path(__file__).parent
    pmx_files = list(test_dir.glob("**/*.pmx"))

    if not pmx_files:
        print("警告: 未找到PMX测试文件，跳过PMX测试")
        return

    parser = PmxParser()
    all_passed = True

    for pmx_file in pmx_files:
        print(f"\n测试文件: {pmx_file.name}")

        try:
            # 使用原始方法解析
            start_time = time.perf_counter()
            original_result = parser.parse_file(pmx_file)
            original_time = time.perf_counter() - start_time

            # 使用快速方法解析
            start_time = time.perf_counter()
            fast_result = parser.parse_file_fast(pmx_file)
            fast_time = time.perf_counter() - start_time

            # 比较结果
            errors = compare_pmx_results(original_result, fast_result)

            if errors:
                print(f"  ❌ 结果不一致!")
                for error in errors[:5]:  # 只显示前5个错误
                    print(f"     - {error}")
                if len(errors) > 5:
                    print(f"     ... 还有 {len(errors)-5} 个错误")
                all_passed = False
            else:
                speedup = original_time / fast_time if fast_time > 0 else float('inf')
                print(f"  ✅ 结果一致")
                print(f"     原始方法: {original_time:.4f}s")
                print(f"     快速方法: {fast_time:.4f}s")
                print(f"     速度提升: {speedup:.2f}x")

        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    assert all_passed, "PMX解析器优化验证失败"


def test_vmd_parser_correctness():
    """测试VMD解析器优化后的正确性"""
    print("\n" + "="*60)
    print("测试VMD解析器优化正确性")
    print("="*60)

    # 查找测试VMD文件
    test_dir = Path(__file__).parent.parent  # 项目根目录
    vmd_files = list(test_dir.glob("**/*.vmd"))

    if not vmd_files:
        print("警告: 未找到VMD测试文件，跳过VMD测试")
        return

    parser = VmdParser()
    all_passed = True

    for vmd_file in vmd_files:
        print(f"\n测试文件: {vmd_file.name}")

        try:
            # 使用原始方法解析
            start_time = time.perf_counter()
            original_result = parser.parse_file(vmd_file)
            original_time = time.perf_counter() - start_time

            # 使用快速方法解析
            start_time = time.perf_counter()
            fast_result = parser.parse_file_fast(vmd_file)
            fast_time = time.perf_counter() - start_time

            # 比较结果
            errors = compare_vmd_results(original_result, fast_result)

            if errors:
                print(f"  ❌ 结果不一致!")
                for error in errors[:5]:  # 只显示前5个错误
                    print(f"     - {error}")
                if len(errors) > 5:
                    print(f"     ... 还有 {len(errors)-5} 个错误")
                all_passed = False
            else:
                speedup = original_time / fast_time if fast_time > 0 else float('inf')
                print(f"  ✅ 结果一致")
                print(f"     原始方法: {original_time:.4f}s")
                print(f"     快速方法: {fast_time:.4f}s")
                print(f"     速度提升: {speedup:.2f}x")
                print(f"     数据统计:")
                print(f"       骨骼帧: {len(fast_result.bone_frames)}")
                print(f"       变形帧: {len(fast_result.morph_frames)}")
                print(f"       相机帧: {len(fast_result.camera_frames)}")

        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    assert all_passed, "VMD解析器优化验证失败"


def main():
    """运行所有优化验证测试"""
    print("="*60)
    print("PyPMXVMD 解析器优化验证测试")
    print("="*60)

    pmx_passed = test_pmx_parser_correctness()
    vmd_passed = test_vmd_parser_correctness()

    print("\n" + "="*60)
    print("测试总结")
    print("="*60)

    if pmx_passed and vmd_passed:
        print("✅ 所有测试通过！优化后的解析器与原始解析器结果一致。")
        return 0
    else:
        print("❌ 部分测试失败，请检查上述错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
