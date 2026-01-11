#!/usr/bin/env python3
"""PyPMXVMD快速集成测试"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

import pypmxvmd


def test_quick_integration():
    """快速测试PyPMXVMD核心API功能"""
    print("=== PyPMXVMD快速集成测试 ===")
    print(f"PyPMXVMD版本: {pypmxvmd.__version__}")
    
    success_count = 0
    total_tests = 0
    
    # 测试1: 基本API导入
    try:
        print("\n--- 测试API导入 ---")
        total_tests += 1
        
        # 检查所有主要函数是否可导入
        functions = ['load_vmd', 'save_vmd', 'load_pmx', 'save_pmx', 
                    'load_vpd', 'save_vpd', 'load', 'save']
        
        all_imported = True
        for func_name in functions:
            if not hasattr(pypmxvmd, func_name):
                print(f"函数 {func_name} 导入失败")
                all_imported = False
        
        if all_imported:
            print("所有API函数导入成功")
            success_count += 1
        
    except Exception as e:
        print(f"API导入测试失败: {e}")
    
    # 测试2: VPD API（最简单的格式）
    try:
        print("\n--- 测试VPD API ---")
        total_tests += 1
        
        # 创建简单的VPD内容
        vpd_content = """Vocaloid Pose Data file

TestModel.osm;
1;

Bone0{センター
  0.000000,0.000000,0.000000;
  0.000000,0.000000,0.000000,1.000000;
}

"""
        
        vpd_file = Path(__file__).parent / "quick_test.vpd"
        with open(vpd_file, 'w', encoding='shift_jis') as f:
            f.write(vpd_content)
        
        # 测试加载和保存
        pose = pypmxvmd.load_vpd(vpd_file)
        output_vpd = Path(__file__).parent / "quick_output.vpd"
        pypmxvmd.save_vpd(pose, output_vpd)
        
        # 验证
        pose2 = pypmxvmd.load_vpd(output_vpd)
        if pose.model_name == pose2.model_name:
            print("VPD API测试通过")
            success_count += 1
        
        # 清理
        vpd_file.unlink()
        output_vpd.unlink()
        
    except Exception as e:
        print(f"VPD API测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试3: 自动检测功能
    try:
        print("\n--- 测试自动检测 ---")
        total_tests += 1
        
        # 创建测试文件
        vpd_content = """Vocaloid Pose Data file

Auto.osm;
0;

"""
        auto_file = Path(__file__).parent / "auto_detect.vpd"
        with open(auto_file, 'w', encoding='shift_jis') as f:
            f.write(vpd_content)
        
        # 测试自动检测加载
        data = pypmxvmd.load(auto_file)
        print(f"自动检测结果: {type(data).__name__}")
        
        if hasattr(data, 'model_name'):
            print("自动检测API测试通过")
            success_count += 1
        
        # 清理
        auto_file.unlink()
        
    except Exception as e:
        print(f"自动检测测试失败: {e}")
    
    # 测试结果
    print(f"\n=== 测试结果 ===")
    print(f"通过: {success_count}/{total_tests}")
    
    if success_count == total_tests:
        print("所有快速集成测试通过！")
    else:
        print("部分测试失败")
        assert False, f"快速集成测试失败: 通过 {success_count}/{total_tests}"


if __name__ == "__main__":
    success = test_quick_integration()
    exit(0 if success else 1)