#!/usr/bin/env python3
"""PyPMXVMD文本处理功能测试"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

import pypmxvmd


def create_test_vmd_data():
    """创建测试VMD数据"""
    from pypmxvmd.common.models.vmd import VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame
    
    # 创建VMD运动对象
    vmd_motion = VmdMotion()
    
    # 设置头部信息
    vmd_motion.header = VmdHeader(version=2, model_name="TestModel")
    
    # 设置骨骼帧
    vmd_motion.bone_frames = [
        VmdBoneFrame(
            bone_name="センター",
            frame_number=0,
            position=[0.0, 10.0, 0.0],
            rotation=[0.0, 0.0, 0.0],  # 欧拉角格式
            physics_disabled=False,
            interpolation=[20, 20, 0, 0, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107, 107, 107]
        )
    ]
    
    # 设置变形帧
    vmd_motion.morph_frames = [
        VmdMorphFrame(
            morph_name="あ",
            frame_number=0,
            weight=0.5
        )
    ]
    
    return vmd_motion


def create_test_pmx_data():
    """创建测试PMX数据"""
    from pypmxvmd.common.models.pmx import PmxModel, PmxHeader, PmxVertex, PmxMaterial
    
    header = PmxHeader(
        version=2.0,
        name_jp="テストモデル",
        name_en="TestModel",
        comment_jp="テスト用モデル",
        comment_en="Test Model"
    )
    
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
    
    faces = [[0, 1, 2]]
    
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
    
    model = PmxModel()
    model.header = header
    model.vertices = vertices
    model.faces = faces
    model.materials = materials
    
    return model


def create_test_vpd_data():
    """创建测试VPD数据"""
    from pypmxvmd.common.models.vpd import VpdPose, VpdBonePose, VpdMorphPose
    
    bone_poses = [
        VpdBonePose(
            bone_name="センター",
            position=[0.0, 10.0, 0.0],
            rotation=[0.1, 0.2, 0.3, 0.9]
        )
    ]
    
    morph_poses = [
        VpdMorphPose(
            morph_name="笑い",
            weight=0.8
        )
    ]
    
    return VpdPose(
        model_name="TestModel",
        bone_poses=bone_poses,
        morph_poses=morph_poses
    )


def test_text_processing():
    """测试文本处理功能"""
    print("=== PyPMXVMD文本处理功能测试 ===")
    print(f"PyPMXVMD版本: {pypmxvmd.__version__}")
    
    success_count = 0
    total_tests = 0
    
    # 测试1: VMD文本处理
    try:
        print("\n--- 测试VMD文本处理 ---")
        total_tests += 1
        
        # 创建测试数据
        original_vmd = create_test_vmd_data()
        
        # 导出为文本
        vmd_text_file = Path(__file__).parent / "test_vmd.txt"
        pypmxvmd.save_vmd_text(original_vmd, vmd_text_file)
        print(f"VMD文本导出成功")
        
        # 从文本加载
        loaded_vmd = pypmxvmd.load_vmd_text(vmd_text_file)
        print(f"VMD文本加载成功: 版本={loaded_vmd.header.version}, 模型={loaded_vmd.header.model_name}")
        print(f"骨骼帧: {len(loaded_vmd.bone_frames)}, 变形帧: {len(loaded_vmd.morph_frames)}")
        
        # 验证数据一致性
        if (loaded_vmd.header.model_name == original_vmd.header.model_name and
            len(loaded_vmd.bone_frames) == len(original_vmd.bone_frames) and
            len(loaded_vmd.morph_frames) == len(original_vmd.morph_frames)):
            print("VMD文本处理测试通过")
            success_count += 1
        
        # 清理
        vmd_text_file.unlink()
        
    except Exception as e:
        print(f"VMD文本处理测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试2: PMX文本处理
    try:
        print("\n--- 测试PMX文本处理 ---")
        total_tests += 1
        
        # 创建测试数据
        original_pmx = create_test_pmx_data()
        
        # 导出为文本
        pmx_text_file = Path(__file__).parent / "test_pmx.txt"
        pypmxvmd.save_pmx_text(original_pmx, pmx_text_file)
        print(f"PMX文本导出成功")
        
        # 从文本加载
        loaded_pmx = pypmxvmd.load_pmx_text(pmx_text_file)
        print(f"PMX文本加载成功: 版本={loaded_pmx.header.version}")
        print(f"顶点: {len(loaded_pmx.vertices)}, 面: {len(loaded_pmx.faces)}, 材质: {len(loaded_pmx.materials)}")
        
        # 验证数据一致性
        if (len(loaded_pmx.vertices) == len(original_pmx.vertices) and
            len(loaded_pmx.faces) == len(original_pmx.faces) and
            len(loaded_pmx.materials) == len(original_pmx.materials)):
            print("PMX文本处理测试通过")
            success_count += 1
        
        # 清理
        pmx_text_file.unlink()
        
    except Exception as e:
        print(f"PMX文本处理测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试3: VPD文本处理
    try:
        print("\n--- 测试VPD文本处理 ---")
        total_tests += 1
        
        # 创建测试数据
        original_vpd = create_test_vpd_data()
        
        # 导出为结构化文本
        vpd_text_file = Path(__file__).parent / "test_vpd.txt"
        pypmxvmd.save_vpd_text(original_vpd, vpd_text_file)
        print(f"VPD文本导出成功")
        
        # 从文本加载
        loaded_vpd = pypmxvmd.load_vpd_text(vpd_text_file)
        print(f"VPD文本加载成功: 模型={loaded_vpd.model_name}")
        print(f"骨骼姿势: {len(loaded_vpd.bone_poses)}, 变形姿势: {len(loaded_vpd.morph_poses)}")
        
        # 验证数据一致性
        if (loaded_vpd.model_name == original_vpd.model_name and
            len(loaded_vpd.bone_poses) == len(original_vpd.bone_poses) and
            len(loaded_vpd.morph_poses) == len(original_vpd.morph_poses)):
            print("VPD文本处理测试通过")
            success_count += 1
        
        # 清理
        vpd_text_file.unlink()
        
    except Exception as e:
        print(f"VPD文本处理测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试4: 自动检测文本功能
    try:
        print("\n--- 测试自动检测文本功能 ---")
        total_tests += 1
        
        # 创建VMD文本文件
        vmd_data = create_test_vmd_data()
        auto_test_file = Path(__file__).parent / "auto_test.txt"
        pypmxvmd.save_text(vmd_data, auto_test_file)
        
        # 自动检测并加载
        auto_loaded = pypmxvmd.load_text(auto_test_file)
        print(f"自动检测加载: {type(auto_loaded).__name__}")
        
        if isinstance(auto_loaded, pypmxvmd.VmdMotion) and auto_loaded.header.model_name == vmd_data.header.model_name:
            print("自动检测文本功能测试通过")
            success_count += 1
        
        # 清理
        auto_test_file.unlink()
        
    except Exception as e:
        print(f"自动检测文本功能测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试5: API可用性验证
    try:
        print("\n--- 测试API可用性 ---")
        total_tests += 1
        
        # 检查所有文本处理函数是否可用
        text_functions = [
            'load_vmd_text', 'save_vmd_text',
            'load_pmx_text', 'save_pmx_text', 
            'load_vpd_text', 'save_vpd_text',
            'load_text', 'save_text'
        ]
        
        all_available = True
        for func_name in text_functions:
            if not hasattr(pypmxvmd, func_name):
                print(f"函数 {func_name} 不可用")
                all_available = False
        
        if all_available:
            print("所有文本处理API可用")
            success_count += 1
        
    except Exception as e:
        print(f"API可用性测试失败: {e}")
    
    # 测试结果
    print(f"\n=== 测试结果 ===")
    print(f"通过: {success_count}/{total_tests}")
    
    if success_count == total_tests:
        print("所有文本处理功能测试通过！")
    else:
        print("部分测试失败")
        assert False, f"文本处理功能测试失败: 通过 {success_count}/{total_tests}"


if __name__ == "__main__":
    success = test_text_processing()
    exit(0 if success else 1)