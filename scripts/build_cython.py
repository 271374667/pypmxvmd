#!/usr/bin/env python3
"""
Cython模块编译脚本

直接运行即可编译所有Cython模块:
    python scripts/build_cython.py

编译后的模块可直接导入使用:
    from pypmxvmd.common.io._fast_binary import FastBinaryReader
    from pypmxvmd.common.parsers._fast_vmd import parse_vmd_cython
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython
"""

import os
import sys
from pathlib import Path

# 确保从项目根目录运行
SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent
os.chdir(ROOT_DIR)
sys.path.insert(0, str(ROOT_DIR))

from setuptools import setup, Extension
from Cython.Build import cythonize


def build_cython_modules():
    """编译所有Cython模块"""
    print("=" * 60)
    print("PyPMXVMD Cython模块编译")
    print("=" * 60)
    print(f"项目根目录: {ROOT_DIR}")
    print()

    # Cython扩展模块列表
    extensions = [
        Extension(
            "pypmxvmd.common.io._fast_binary",
            sources=["pypmxvmd/common/io/_fast_binary.pyx"],
            language="c",
        ),
        Extension(
            "pypmxvmd.common.parsers._fast_vmd",
            sources=["pypmxvmd/common/parsers/_fast_vmd.pyx"],
            language="c",
        ),
        Extension(
            "pypmxvmd.common.parsers._fast_pmx",
            sources=["pypmxvmd/common/parsers/_fast_pmx.pyx"],
            language="c",
        ),
    ]

    # 编译选项
    compiler_directives = {
        'language_level': 3,
        'boundscheck': False,
        'wraparound': False,
        'cdivision': True,
        'initializedcheck': False,
        'nonecheck': False,
    }

    # Windows特定设置
    if sys.platform == 'win32':
        for ext in extensions:
            ext.define_macros = [('_CRT_SECURE_NO_WARNINGS', None)]

    # 保存原始sys.argv
    original_argv = sys.argv.copy()

    try:
        # 设置编译参数 - 直接inplace编译
        sys.argv = [sys.argv[0], 'build_ext', '--inplace']

        setup(
            name="pypmxvmd_cython",
            ext_modules=cythonize(
                extensions,
                compiler_directives=compiler_directives,
                annotate=False,  # 不生成HTML注释文件
            ),
            zip_safe=False,
            script_args=['build_ext', '--inplace'],
        )

        print()
        print("=" * 60)
        print("编译完成!")
        print("=" * 60)

        # 验证编译结果
        verify_compilation()

    except Exception as e:
        print(f"\n编译失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # 恢复原始sys.argv
        sys.argv = original_argv

    return 0


def verify_compilation():
    """验证编译结果"""
    print("\n验证编译结果:")

    modules = [
        ("pypmxvmd.common.io._fast_binary", "FastBinaryReader"),
        ("pypmxvmd.common.parsers._fast_vmd", "parse_vmd_cython"),
        ("pypmxvmd.common.parsers._fast_pmx", "parse_pmx_cython"),
    ]

    all_ok = True
    for module_name, symbol in modules:
        try:
            module = __import__(module_name, fromlist=[symbol])
            if hasattr(module, symbol):
                print(f"  ✅ {module_name}")
            else:
                print(f"  ❌ {module_name} (缺少 {symbol})")
                all_ok = False
        except ImportError as e:
            print(f"  ❌ {module_name} ({e})")
            all_ok = False

    if all_ok:
        print("\n所有Cython模块编译成功!")
    else:
        print("\n部分模块编译失败，请检查错误信息。")


if __name__ == "__main__":
    sys.exit(build_cython_modules())
