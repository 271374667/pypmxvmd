#!/usr/bin/env python3
"""测试VMD头部解析"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pymmd.common.parsers.vmd_parser import VmdParser


def create_test_vmd_header():
    """创建一个测试用的VMD文件头"""
    # VMD版本2的头部结构：
    # - "Vocaloid Motion Data " (21字节)
    # - "0002" (4字节)
    # - 5字节填充
    # - 模型名称 (20字节)
    
    data = bytearray()
    
    # 魔术字符串
    magic = b"Vocaloid Motion Data "  # 21字节
    data.extend(magic)
    
    # 版本
    version = b"0002"  # 4字节
    data.extend(version)
    
    # 填充
    data.extend(b'\x00' * 5)
    
    # 模型名称 (测试名称，用shift_jis编码)
    model_name = "TestModel"
    model_name_bytes = model_name.encode('shift_jis')
    # 填充到20字节
    model_name_bytes += b'\x00' * (20 - len(model_name_bytes))
    data.extend(model_name_bytes)
    
    # 添加最小的骨骼帧数据 (4字节的0表示0个帧)
    data.extend(b'\x00\x00\x00\x00')
    
    return data


def test_vmd_header_parsing():
    """测试VMD头部解析"""
    print("创建测试VMD数据...")
    test_data = create_test_vmd_header()
    
    print(f"测试数据长度: {len(test_data)}字节")
    print(f"头部内容: {test_data[:30]}")
    
    # 创建解析器
    parser = VmdParser()
    
    try:
        print("开始解析头部...")
        
        # 直接调用头部解析方法
        data_copy = bytearray(test_data)
        header = parser._parse_header(data_copy, True)
        
        print(f"解析成功！")
        print(f"版本: {header.version}")
        print(f"模型名称: '{header.model_name}'")
        
    except Exception as e:
        print(f"解析失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_vmd_header_parsing()