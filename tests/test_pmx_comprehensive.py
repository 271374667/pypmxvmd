#!/usr/bin/env python3
"""PMX解析器全面测试"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pymmd.common.parsers.pmx_parser import PmxParser
from pymmd.common.models.pmx import PmxModel, PmxHeader, PmxVertex, PmxMaterial


def create_detailed_pmx_model():
    """创建一个详细的测试PMX模型"""
    
    # 创建头部
    header = PmxHeader(
        version=2.0,
        name_jp="詳細テストモデル",
        name_en="DetailedTestModel",
        comment_jp="これは全面的なテスト用のモデルです。\n複数の頂点と材質を含みます。",
        comment_en="This is a comprehensive test model.\nContains multiple vertices and materials."
    )
    
    # 创建多个顶点 - 构建一个简单的四角形
    vertices = [
        # 第一个三角形
        PmxVertex(
            position=[0.0, 0.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[0.0, 0.0]
        ),
        PmxVertex(
            position=[2.0, 0.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[1.0, 0.0]
        ),
        PmxVertex(
            position=[1.0, 2.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[0.5, 1.0]
        ),
        # 第二个三角形
        PmxVertex(
            position=[2.0, 0.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[1.0, 0.0]
        ),
        PmxVertex(
            position=[3.0, 2.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[1.0, 1.0]
        ),
        PmxVertex(
            position=[1.0, 2.0, 0.0],
            normal=[0.0, 1.0, 0.0],
            uv=[0.5, 1.0]
        )
    ]
    
    # 创建面
    faces = [
        [0, 1, 2],  # 第一个三角面
        [3, 4, 5]   # 第二个三角面
    ]
    
    # 创建多个材质
    materials = [
        PmxMaterial(
            name_jp="基本材質",
            name_en="Basic Material",
            diffuse_color=[0.8, 0.8, 0.8, 1.0],
            specular_color=[0.3, 0.3, 0.3],
            specular_strength=5.0,
            ambient_color=[0.2, 0.2, 0.2],
            texture_path="basic_texture.png",
            face_count=3  # 第一个面的3个顶点
        ),
        PmxMaterial(
            name_jp="特殊材質",
            name_en="Special Material",
            diffuse_color=[1.0, 0.5, 0.5, 0.9],
            specular_color=[0.5, 0.1, 0.1],
            specular_strength=10.0,
            ambient_color=[0.3, 0.1, 0.1],
            texture_path="special_texture.png",
            face_count=3  # 第二个面的3个顶点
        )
    ]
    
    # 创建完整模型
    model = PmxModel()
    model.header = header
    model.vertices = vertices
    model.faces = faces
    model.materials = materials
    
    return model


def test_pmx_comprehensive():
    """全面测试PMX解析器"""
    print("=== PMX解析器全面测试 ===")
    
    try:
        # 创建详细测试模型
        print("创建详细测试PMX模型...")
        model = create_detailed_pmx_model()
        
        # 验证模型
        print("验证模型数据...")
        model.validate()
        
        print("模型详细信息:")
        print(f"  版本: {model.header.version}")
        print(f"  日文名称: {model.header.name_jp}")
        print(f"  英文名称: {model.header.name_en}")
        print(f"  顶点数: {len(model.vertices)}")
        print(f"  面数: {len(model.faces)}")
        print(f"  材质数: {len(model.materials)}")
        
        # 显示顶点详情
        print("\n顶点详情:")
        for i, vertex in enumerate(model.vertices):
            print(f"  顶点{i}: 位置{vertex.position}, UV{vertex.uv}")
        
        # 显示材质详情
        print("\n材质详情:")
        for i, material in enumerate(model.materials):
            print(f"  材质{i}: {material.name_jp}")
            print(f"    漫反射: {material.diffuse_color}")
            print(f"    纹理: {material.texture_path}")
            print(f"    面数: {material.face_count}")
        
        # 创建解析器
        parser = PmxParser()
        
        # 测试写入
        output_file = Path(__file__).parent / "test_detailed.pmx"
        print(f"\n测试写入到: {output_file}")
        
        parser.write_file(model, output_file)
        
        print("PMX写入成功")
        
        # 验证文件是否创建
        if output_file.exists():
            file_size = output_file.stat().st_size
            print(f"输出文件大小: {file_size}字节")
            
            # 简单格式验证 - 检查PMX魔术字符串
            with open(output_file, 'rb') as f:
                magic = f.read(4)
                if magic == b'PMX ':
                    print("文件格式验证通过: 正确的PMX魔术字符串")
                    
                    version = f.read(4)
                    import struct
                    version_float = struct.unpack('<f', version)[0]
                    print(f"文件版本: {version_float}")
                else:
                    print(f"警告: 无效的魔术字符串: {magic}")
        else:
            print("错误: 输出文件未创建")
            return False
        
        # 尝试创建更大的模型来测试索引大小
        print("\n测试大型模型索引处理...")
        large_model = create_large_pmx_model()
        
        large_output_file = Path(__file__).parent / "test_large.pmx"
        parser.write_file(large_model, large_output_file)
        
        if large_output_file.exists():
            large_size = large_output_file.stat().st_size
            print(f"大型模型文件大小: {large_size}字节")
        
        # 清理测试文件
        output_file.unlink()
        large_output_file.unlink()
        
        print("PMX全面测试完成")
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_large_pmx_model():
    """创建一个大型模型来测试索引大小"""
    model = PmxModel()
    
    # 创建简单头部
    model.header = PmxHeader(
        version=2.0,
        name_jp="大型テストモデル",
        name_en="LargeTestModel"
    )
    
    # 创建大量顶点 (超过256个以测试索引大小)
    vertices = []
    faces = []
    
    # 创建一个网格
    grid_size = 20  # 20x20 = 400个顶点
    for x in range(grid_size):
        for y in range(grid_size):
            vertices.append(PmxVertex(
                position=[float(x), float(y), 0.0],
                normal=[0.0, 0.0, 1.0],
                uv=[x / grid_size, y / grid_size]
            ))
    
    # 创建面（每个小方格分成2个三角形）
    for x in range(grid_size - 1):
        for y in range(grid_size - 1):
            # 计算四个顶点的索引
            v0 = x * grid_size + y
            v1 = (x + 1) * grid_size + y
            v2 = x * grid_size + (y + 1)
            v3 = (x + 1) * grid_size + (y + 1)
            
            # 两个三角形
            faces.append([v0, v1, v2])
            faces.append([v1, v3, v2])
    
    # 创建一个材质覆盖所有面
    materials = [PmxMaterial(
        name_jp="网格材质",
        name_en="Grid Material",
        diffuse_color=[0.7, 0.7, 0.7, 1.0],
        face_count=len(faces) * 3  # 总顶点数
    )]
    
    model.vertices = vertices
    model.faces = faces
    model.materials = materials
    
    return model


if __name__ == "__main__":
    success = test_pmx_comprehensive()
    exit(0 if success else 1)