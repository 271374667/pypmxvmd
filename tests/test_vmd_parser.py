#!/usr/bin/env python3
"""VMD解析器测试脚本"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pypmxvmd.common.parsers.vmd_parser import VmdParser


def test_vmd_parser():
    """测试VMD解析器"""
    parser = VmdParser()
    
    # 查找项目中的VMD文件进行测试
    project_root = Path(__file__).parent
    vmd_files = list(project_root.glob("**/*.vmd"))
    
    if not vmd_files:
        print("未找到VMD文件进行测试")
        return
    
    for vmd_file in vmd_files[:1]:  # 只测试第一个文件
        print(f"测试VMD文件: {vmd_file}")
        try:
            result = parser.parse_file(vmd_file, more_info=True)
            print(f"解析成功！版本: {result.header.version}, 模型: {result.header.model_name}")
        except Exception as e:
            print(f"解析失败: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    test_vmd_parser()