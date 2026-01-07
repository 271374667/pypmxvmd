#!/usr/bin/env python3
"""VMD解析器对比测试脚本

此脚本对比三个项目的VMD解析能力:
1. mmd_scripting - 原始有bug的版本
2. pymmd - 修复后的版本
3. pypmxvmd - 重构后的版本（应该也已修复）
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_format_strings():
    """测试Bug 2: 结构体对齐错误"""
    print("\n" + "="*80)
    print("Bug 2 测试: 结构体格式字符串对齐")
    print("="*80)

    import struct

    # Bug 2的问题：缺少 < 前缀导致使用原生对齐，会添加填充字节

    # 错误的格式（无<前缀）- 原始mmd_scripting版本
    fmt_shadowframe_buggy = "I b f"
    fmt_ikdispframe_buggy = "I ? I"

    # 正确的格式（有<前缀）- 修复后的pymmd和pypmxvmd版本
    fmt_shadowframe_fixed = "<I b f"
    fmt_ikdispframe_fixed = "<I ? I"

    buggy_shadow_size = struct.calcsize(fmt_shadowframe_buggy)
    fixed_shadow_size = struct.calcsize(fmt_shadowframe_fixed)
    buggy_ik_size = struct.calcsize(fmt_ikdispframe_buggy)
    fixed_ik_size = struct.calcsize(fmt_ikdispframe_fixed)

    print(f"\n[+] 结构体大小对比:")
    print(f"   阴影帧 (Shadow Frame):")
    print(f"      有bug版本 '{fmt_shadowframe_buggy}': {buggy_shadow_size} 字节")
    print(f"      修复版本 '{fmt_shadowframe_fixed}': {fixed_shadow_size} 字节")
    print(f"      差异: {buggy_shadow_size - fixed_shadow_size} 字节")

    print(f"\n   IK帧 (IK Disp Frame):")
    print(f"      有bug版本 '{fmt_ikdispframe_buggy}': {buggy_ik_size} 字节")
    print(f"      修复版本 '{fmt_ikdispframe_fixed}': {fixed_ik_size} 字节")
    print(f"      差异: {buggy_ik_size - fixed_ik_size} 字节")

    # 验证修复是否正确
    if buggy_shadow_size == 12 and fixed_shadow_size == 9:
        print(f"\n[OK] 阴影帧修复正确: 从12字节（有填充）修复为9字节（无填充）")
    else:
        print(f"\n[!] 警告: 阴影帧大小不符合预期")

    if buggy_ik_size == 12 and fixed_ik_size == 9:
        print(f"[OK] IK帧修复正确: 从12字节（有填充）修复为9字节（无填充）")
    else:
        print(f"[!] 警告: IK帧大小不符合预期")


def check_parser_format_strings():
    """检查各个解析器的格式字符串定义"""
    print("\n" + "="*80)
    print("解析器格式字符串检查")
    print("="*80)

    # 检查pypmxvmd解析器
    try:
        from pypmxvmd.common.parsers.vmd_parser import VmdParser
        parser = VmdParser()

        print(f"\n[+] pypmxvmd 解析器:")
        print(f"   _FMT_SHADOWFRAME = {repr(parser._FMT_SHADOWFRAME)}")
        print(f"   _FMT_IKDISPFRAME = {repr(parser._FMT_IKDISPFRAME)}")
        print(f"   _FMT_MORPHFRAME = {repr(parser._FMT_MORPHFRAME)}")

        has_prefix = (
            parser._FMT_SHADOWFRAME.startswith('<') and
            parser._FMT_IKDISPFRAME.startswith('<') and
            parser._FMT_MORPHFRAME.startswith('<')
        )

        if has_prefix:
            print(f"   [OK] 所有格式字符串都有 '<' 前缀 - Bug已修复")
        else:
            print(f"   [FAIL] 某些格式字符串缺少 '<' 前缀 - Bug仍存在")

    except Exception as e:
        print(f"   [ERROR] 无法加载pypmxvmd解析器: {e}")

    # 检查pymmd解析器
    try:
        from pymmd.common.parsers.vmd_parser import VmdParser as PyMMDParser
        parser = PyMMDParser()

        print(f"\n[+] pymmd 解析器:")
        print(f"   _FMT_SHADOWFRAME = {repr(parser._FMT_SHADOWFRAME)}")
        print(f"   _FMT_IKDISPFRAME = {repr(parser._FMT_IKDISPFRAME)}")
        print(f"   _FMT_MORPHFRAME = {repr(parser._FMT_MORPHFRAME)}")

        has_prefix = (
            parser._FMT_SHADOWFRAME.startswith('<') and
            parser._FMT_IKDISPFRAME.startswith('<') and
            parser._FMT_MORPHFRAME.startswith('<')
        )

        if has_prefix:
            print(f"   [OK] 所有格式字符串都有 '<' 前缀 - Bug已修复")
        else:
            print(f"   [FAIL] 某些格式字符串缺少 '<' 前缀 - Bug仍存在")

    except Exception as e:
        print(f"   [ERROR] 无法加载pymmd解析器: {e}")


def test_bug_description():
    """显示bug的详细说明"""
    print("\n" + "="*80)
    print("VMD解析器Bug说明")
    print("="*80)

    print("""
[BUG 1] 位置跟踪错误 (Position Tracking Error)
   问题位置: 多个解析函数的长度检查
   错误代码: if (len(data) - self._io_handler._position) < struct.calcsize(...)
   修复代码: if len(data) < struct.calcsize(...)

   影响: 由于data在读取时会被消费（del data[:size]），len(data)已经是剩余长度，
        再减去_position会导致负值，使解析器完全跳过morph/camera/light/shadow/IK帧。

[BUG 2] 结构体对齐错误 (Struct Alignment Error)
   问题位置: 格式字符串定义（lines 30-39）
   错误代码: FMT_SHADOWFRAME = "I b f"    # 12字节（有填充）
             FMT_IKDISPFRAME = "I ? I"    # 12字节（有填充）
   修复代码: FMT_SHADOWFRAME = "<I b f"   # 9字节（无填充）
             FMT_IKDISPFRAME = "<I ? I"   # 9字节（无填充）

   影响: 缺少 < 前缀导致struct使用原生对齐并添加填充字节，使shadow帧和IK帧
        多消费3字节，导致后续数据解析错误。
""")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("VMD解析器Bug修复验证测试")
    print("="*80)

    # 显示bug说明
    test_bug_description()

    # 测试格式字符串大小
    test_format_strings()

    # 检查解析器的格式字符串
    check_parser_format_strings()

    print("\n" + "="*80)
    print("测试完成")
    print("="*80)
