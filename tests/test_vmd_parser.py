#!/usr/bin/env python3
"""VMD解析器测试脚本"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pypmxvmd.common.parsers.vmd_parser import VmdParser


def test_vmd_parser():
    """测试VMD解析器并输出为文本"""
    parser = VmdParser()

    # 查找项目中的VMD文件进行测试
    project_root = Path(__file__).parent
    vmd_files = list(project_root.glob("**/*.vmd"))

    if not vmd_files:
        print("未找到VMD文件进行测试")
        return

    for vmd_file in vmd_files[:1]:  # 只测试第一个文件
        print(f"\n{'='*60}")
        print(f"测试VMD文件: {vmd_file}")
        print(f"{'='*60}\n")

        try:
            # 解析VMD文件
            result = parser.parse_file(vmd_file, more_info=True)
            print(f"\n✅ 解析成功！")
            print(f"   版本: {result.header.version}")
            print(f"   模型: {result.header.model_name}")
            print(f"   骨骼帧数: {len(result.bone_frames)}")
            print(f"   变形帧数: {len(result.morph_frames)}")
            print(f"   相机帧数: {len(result.camera_frames)}")
            print(f"   光源帧数: {len(result.light_frames)}")
            print(f"   阴影帧数: {len(result.shadow_frames)}")
            print(f"   IK帧数: {len(result.ik_frames)}")

            # 输出为文本文件
            output_txt = vmd_file.with_suffix('.txt')
            parser.write_text_file(result, output_txt)
            print(f"\n📄 文本输出已保存至: {output_txt}")

            # 显示部分变形帧数据用于验证
            if result.morph_frames:
                print(f"\n🔍 前5个变形帧预览:")
                for i, morph in enumerate(result.morph_frames[:5]):
                    print(f"   [{i+1}] 帧{morph.frame_number}: {morph.morph_name} = {morph.weight:.6f}")
            else:
                print(f"\n⚠️  警告: 未找到变形帧数据！")

        except Exception as e:
            print(f"\n❌ 解析失败: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    test_vmd_parser()