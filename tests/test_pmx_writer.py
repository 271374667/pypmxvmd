#!/usr/bin/env python3
"""PMX写入器测试脚本"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pymmd.common.parsers.pmx_parser import PmxParser
from pymmd.common.models.pmx import PmxModel, PmxHeader, PmxVertex, PmxMaterial


def create_test_pmx_model():
    """创建一个简单的测试PMX模型"""
    
    # 创建头部
    header = PmxHeader(
        version=2.0,
        name_jp="テストモデル",
        name_en="TestModel",
        comment_jp="テスト用のシンプルなモデル",
        comment_en="Simple test model"
    )
    
    # 创建顶点
    vertices = [
        PmxVertex(
            position=[0.0, 0.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[0.0, 0.0]
        ),
        PmxVertex(
            position=[1.0, 0.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[1.0, 0.0]
        ),
        PmxVertex(
            position=[0.5, 1.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[0.5, 1.0]
        )
    ]
    
    # 创建面
    faces = [[0, 1, 2]]  # 一个三角面
    
    # 创建材质
    materials = [
        PmxMaterial(
            name_jp="デフォルト材質",
            name_en="Default Material",
            diffuse_color=[0.8, 0.8, 0.8, 1.0],
            specular_color=[0.5, 0.5, 0.5],
            specular_strength=5.0,
            ambient_color=[0.2, 0.2, 0.2],
            texture_path="",
            face_count=3
        )
    ]
    
    # 创建完整模型
    model = PmxModel()
    model.header = header
    model.vertices = vertices
    model.faces = faces
    model.materials = materials
    
    return model


def test_pmx_writer():
    """测试PMX写入功能"""
    print("=== PMX写入器测试 ===")
    
    try:
        # 创建测试模型
        print("创建测试PMX模型...")
        model = create_test_pmx_model()
        
        # 验证模型
        print("验证模型数据...")
        model.validate()
        print(f"模型包含: {len(model.vertices)}个顶点, {len(model.faces)}个面, {len(model.materials)}个材质")
        
        # 创建解析器
        parser = PmxParser()
        
        # 测试写入
        output_file = Path(__file__).parent / "test_output.pmx"
        print(f"测试写入到: {output_file}")
        
        parser.write_file(model, output_file)
        
        print("PMX写入测试完成")
        
        # 验证文件是否创建
        if output_file.exists():
            print(f"输出文件大小: {output_file.stat().st_size}字节")
        else:
            print("警告: 输出文件未创建")
        
        # 清理测试文件
        if output_file.exists():
            output_file.unlink()
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_pmx_writer()