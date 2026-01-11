"""性能基准测试 - 比较标准解析、快速解析和NumPy优化解析的性能差异"""

import time
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from pypmxvmd.common.parsers.vmd_parser import VmdParser
from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.fast_parsers import FastPmxParser, FastVmdParser, quaternions_to_euler


def benchmark_pmx_parser(pmx_file: str, iterations: int = 5):
    """基准测试PMX解析器"""
    print(f"\n{'='*60}")
    print(f"PMX 解析器基准测试: {Path(pmx_file).name}")
    print(f"{'='*60}")

    parser = PmxParser()

    # 测试标准解析
    print("\n[1. 标准解析 parse_file()]")
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        result = parser.parse_file(pmx_file, more_info=False)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  迭代 {i+1}: {elapsed:.4f}s")

    avg_standard = sum(times) / len(times)
    print(f"  平均时间: {avg_standard:.4f}s")
    print(f"  顶点: {len(result.vertices)}, 面: {len(result.faces)}, 材质: {len(result.materials)}")

    # 测试快速解析
    print("\n[2. 快速解析 parse_file_fast()]")
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        result = parser.parse_file_fast(pmx_file, more_info=False)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  迭代 {i+1}: {elapsed:.4f}s")

    avg_fast = sum(times) / len(times)
    print(f"  平均时间: {avg_fast:.4f}s")

    # 测试NumPy优化解析
    print("\n[3. NumPy优化解析 FastPmxParser]")
    fast_parser = FastPmxParser()
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        result = fast_parser.parse_file(pmx_file)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  迭代 {i+1}: {elapsed:.4f}s")

    avg_numpy = sum(times) / len(times)
    print(f"  平均时间: {avg_numpy:.4f}s")
    print(f"  顶点: {len(result.positions)}, 面: {len(result.face_indices)}")

    # 计算加速比
    print(f"\n[性能对比]")
    print(f"  标准解析:     {avg_standard:.4f}s (基准)")
    print(f"  快速解析:     {avg_fast:.4f}s ({avg_standard/avg_fast:.2f}x)")
    print(f"  NumPy优化:    {avg_numpy:.4f}s ({avg_standard/avg_numpy:.2f}x)")

    return avg_standard, avg_fast, avg_numpy


def benchmark_vmd_parser(vmd_file: str, iterations: int = 5):
    """基准测试VMD解析器"""
    print(f"\n{'='*60}")
    print(f"VMD 解析器基准测试: {Path(vmd_file).name}")
    print(f"{'='*60}")

    parser = VmdParser()

    # 测试标准解析
    print("\n[1. 标准解析 parse_file()]")
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        result = parser.parse_file(vmd_file, more_info=False)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  迭代 {i+1}: {elapsed:.4f}s")

    avg_standard = sum(times) / len(times)
    print(f"  平均时间: {avg_standard:.4f}s")
    print(f"  骨骼帧: {len(result.bone_frames)}, 变形帧: {len(result.morph_frames)}")

    # 测试快速解析
    print("\n[2. 快速解析 parse_file_fast()]")
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        result = parser.parse_file_fast(vmd_file, more_info=False)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  迭代 {i+1}: {elapsed:.4f}s")

    avg_fast = sum(times) / len(times)
    print(f"  平均时间: {avg_fast:.4f}s")

    # 测试NumPy优化解析
    print("\n[3. NumPy优化解析 FastVmdParser]")
    fast_parser = FastVmdParser()
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        result = fast_parser.parse_file(vmd_file)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  迭代 {i+1}: {elapsed:.4f}s")

    avg_numpy = sum(times) / len(times)
    print(f"  平均时间: {avg_numpy:.4f}s")
    print(f"  骨骼帧: {len(result.bone_names)}, 变形帧: {len(result.morph_names)}")

    # 测试四元数转换
    print("\n[4. NumPy向量化四元数转换]")
    start = time.perf_counter()
    euler_angles = quaternions_to_euler(result.bone_rotations)
    elapsed = time.perf_counter() - start
    print(f"  {len(euler_angles)}个四元数转换: {elapsed:.4f}s")

    # 计算加速比
    print(f"\n[性能对比]")
    print(f"  标准解析:     {avg_standard:.4f}s (基准)")
    print(f"  快速解析:     {avg_fast:.4f}s ({avg_standard/avg_fast:.2f}x)")
    print(f"  NumPy优化:    {avg_numpy:.4f}s ({avg_standard/avg_numpy:.2f}x)")

    return avg_standard, avg_fast, avg_numpy


def main():
    print("PyPMXVMD 解析器性能基准测试")
    print("=" * 60)

    # TDA Miku PMX测试
    pmx_file = Path(__file__).parent / "data" / "【Vtuber】TDA Miku" / "【Vtuber】TDA Miku.pmx"

    if pmx_file.exists():
        benchmark_pmx_parser(str(pmx_file))
    else:
        print(f"PMX测试文件不存在: {pmx_file}")

    # 查找VMD文件进行测试
    vmd_files = list(Path(__file__).parent.glob("data/**/*.vmd"))
    if vmd_files:
        # 选择最大的VMD文件进行测试
        vmd_file = max(vmd_files, key=lambda f: f.stat().st_size)
        benchmark_vmd_parser(str(vmd_file))
    else:
        print("\n没有找到VMD测试文件")

    # 总结
    print("\n" + "=" * 60)
    print("基准测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
