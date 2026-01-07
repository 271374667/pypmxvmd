#!/usr/bin/env python3
"""PyPMXVMD API集成测试"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

import pypmxvmd


def test_api_integration():
    """测试PyPMXVMD核心API功能"""
    print("=== PyPMXVMD API集成测试 ===")
    print(f"PyPMXVMD版本: {pypmxvmd.__version__}")
    print(f"作者: {pypmxvmd.__author__}")
    
    success_count = 0
    total_tests = 0
    
    # 测试1: VMD API
    try:
        print("\n--- 测试VMD API ---")
        total_tests += 1
        
        # 使用现有的VMD测试数据创建功能
        test_data = create_test_vmd_data()
        vmd_file = Path(__file__).parent / "api_test.vmd"
        
        with open(vmd_file, 'wb') as f:
            f.write(test_data)
        
        # 测试加载
        motion = pypmxvmd.load_vmd(vmd_file)
        print(f"VMD加载成功: 版本={motion.header.version}, 模型={motion.header.model_name}")
        print(f"骨骼帧: {len(motion.bone_frames)}, 变形帧: {len(motion.morph_frames)}")
        
        # 测试保存
        output_vmd = Path(__file__).parent / "api_output.vmd"
        pypmxvmd.save_vmd(motion, output_vmd)
        
        # 验证读写一致性
        motion2 = pypmxvmd.load_vmd(output_vmd)
        if (motion.header.version == motion2.header.version and
            len(motion.bone_frames) == len(motion2.bone_frames)):
            print("VMD API测试通过")
            success_count += 1
        
        # 清理
        vmd_file.unlink()
        output_vmd.unlink()
        
    except Exception as e:
        print(f"VMD API测试失败: {e}")
    
    # 测试2: VPD API
    try:
        print("\n--- 测试VPD API ---")
        total_tests += 1
        
        # 创建测试VPD文件
        vpd_content = """Vocaloid Pose Data file

TestModel.osm;
1;

Bone0{センター
  0.000000,10.000000,0.000000;
  0.100000,0.200000,0.300000,0.900000;
}

"""
        vpd_file = Path(__file__).parent / "api_test.vpd"
        with open(vpd_file, 'w', encoding='shift_jis') as f:
            f.write(vpd_content)
        
        # 测试加载
        pose = pypmxvmd.load_vpd(vpd_file)
        print(f"VPD加载成功: 模型={pose.model_name}")
        print(f"骨骼姿势: {len(pose.bone_poses)}, 变形姿势: {len(pose.morph_poses)}")
        
        # 测试保存
        output_vpd = Path(__file__).parent / "api_output.vpd"
        pypmxvmd.save_vpd(pose, output_vpd)
        
        # 验证读写一致性
        pose2 = pypmxvmd.load_vpd(output_vpd)
        if (pose.model_name == pose2.model_name and
            len(pose.bone_poses) == len(pose2.bone_poses)):
            print("VPD API测试通过")
            success_count += 1
        
        # 清理
        vpd_file.unlink()
        output_vpd.unlink()
        
    except Exception as e:
        print(f"VPD API测试失败: {e}")
    
    # 测试3: PMX API（创建简单模型）
    try:
        print("\n--- 测试PMX API ---")
        total_tests += 1
        
        # 创建简单的PMX模型
        model = create_test_pmx_model()
        
        # 测试保存
        pmx_file = Path(__file__).parent / "api_test.pmx"
        pypmxvmd.save_pmx(model, pmx_file)
        
        # 测试加载
        model2 = pypmxvmd.load_pmx(pmx_file)
        print(f"PMX加载成功: 版本={model2.header.version}")
        print(f"顶点: {len(model2.vertices)}, 面: {len(model2.faces)}, 材质: {len(model2.materials)}")
        
        # 验证数据一致性
        if (len(model.vertices) == len(model2.vertices) and
            len(model.faces) == len(model2.faces)):
            print("PMX API测试通过")
            success_count += 1
        
        # 清理
        pmx_file.unlink()
        
    except Exception as e:
        print(f"PMX API测试失败: {e}")
    
    # 测试4: 自动检测API
    try:
        print("\n--- 测试自动检测API ---")
        total_tests += 1
        
        # 创建测试文件
        test_data = create_test_vmd_data()
        auto_test_file = Path(__file__).parent / "auto_test.vmd"
        
        with open(auto_test_file, 'wb') as f:
            f.write(test_data)
        
        # 测试自动加载
        data = pypmxvmd.load(auto_test_file)
        print(f"自动检测加载: {type(data).__name__}")
        
        # 测试自动保存
        auto_output = Path(__file__).parent / "auto_output.vmd"
        pypmxvmd.save(data, auto_output)
        
        if auto_output.exists():
            print("自动检测API测试通过")
            success_count += 1
        
        # 清理
        auto_test_file.unlink()
        auto_output.unlink()
        
    except Exception as e:
        print(f"自动检测API测试失败: {e}")
    
    # 测试结果
    print(f"\n=== 测试结果 ===")
    print(f"通过: {success_count}/{total_tests}")
    
    if success_count == total_tests:
        print("所有API集成测试通过！")
        return True
    else:
        print("部分测试失败")
        return False


def create_test_vmd_data():
    """创建测试VMD数据"""
    import struct
    
    data = bytearray()
    
    # VMD头部
    data.extend(b"Vocaloid Motion Data ")  # 21字节
    data.extend(b"0002")  # 4字节版本
    data.extend(b'\x00' * 5)  # 5字节填充
    
    # 模型名称（20字节）
    model_name = "TestModel"
    model_bytes = model_name.encode('shift_jis')
    model_bytes += b'\x00' * (20 - len(model_bytes))
    data.extend(model_bytes)
    
    # 1个骨骼帧
    data.extend(struct.pack("<I", 1))
    
    # 骨骼名称
    bone_name = "センター"
    bone_bytes = bone_name.encode('shift_jis')
    bone_bytes += b'\x00' * (15 - len(bone_bytes))
    data.extend(bone_bytes)
    
    # 帧数据
    data.extend(struct.pack("<I7f", 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    
    # 插值数据（64字节）
    data.extend(b'\x14\x14\x00\x00' + b'\x00' * 60)
    
    # 其他帧类型为0
    data.extend(struct.pack("<IIII", 0, 0, 0, 0))  # 变形、相机、光源、阴影
    
    return data


def create_test_pmx_model():
    """创建简单的测试PMX模型"""
    from pypmxvmd.common.models.pmx import PmxModel, PmxHeader, PmxVertex, PmxMaterial
    
    # 创建头部
    header = PmxHeader(
        version=2.0,
        name_jp="テストモデル",
        name_en="TestModel",
        comment_jp="テスト用モデル",
        comment_en="Test Model"
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
    faces = [[0, 1, 2]]
    
    # 创建材质
    materials = [
        PmxMaterial(
            name_jp="材質",
            name_en="Material",
            diffuse_color=[0.8, 0.8, 0.8, 1.0],
            specular_color=[0.0, 0.0, 0.0],
            specular_strength=0.0,
            ambient_color=[0.3, 0.3, 0.3],
            texture_path="",
            face_count=3
        )
    ]
    
    # 创建模型
    model = PmxModel()
    model.header = header
    model.vertices = vertices
    model.faces = faces
    model.materials = materials
    
    return model


if __name__ == "__main__":
    success = test_api_integration()
    exit(0 if success else 1)