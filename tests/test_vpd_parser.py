#!/usr/bin/env python3
"""VPD解析器测试脚本"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pymmd.common.parsers.vpd_parser import VpdParser
from pymmd.common.models.vpd import VpdPose, VpdBonePose, VpdMorphPose


def create_test_vpd_file():
    """创建一个测试用的VPD文件"""
    test_vpd_path = Path(__file__).parent / "test_pose.vpd"
    
    vpd_content = """Vocaloid Pose Data file

TestModel.osm;
2;

Bone0{全ての親
  0.000000,0.000000,0.000000;
  0.000000,0.000000,0.000000,1.000000;
}

Bone1{センター
  0.000000,10.000000,0.000000;
  0.100000,0.200000,0.300000,0.900000;
}

Morph0{あ
  0.500;
}

Morph1{まばたき
  1.000;
}

"""
    
    with open(test_vpd_path, 'w', encoding='shift_jis') as f:
        f.write(vpd_content)
    
    return test_vpd_path


def test_vpd_parsing():
    """测试VPD解析功能"""
    print("=== VPD解析器测试 ===")
    
    # 创建测试文件
    print("创建测试VPD文件...")
    test_file = create_test_vpd_file()
    
    # 创建解析器
    parser = VpdParser()
    
    try:
        # 测试解析
        print("开始解析测试...")
        pose = parser.parse_file(test_file, more_info=True)
        
        print(f"解析成功！")
        print(f"模型名称: '{pose.model_name}'")
        print(f"骨骼数量: {len(pose.bone_poses)}")
        print(f"变形数量: {len(pose.morph_poses)}")
        
        # 显示骨骼信息
        for i, bone in enumerate(pose.bone_poses):
            print(f"骨骼{i}: {bone.bone_name}, 位置: {bone.position}, 旋转: {bone.rotation}")
        
        # 显示变形信息
        for i, morph in enumerate(pose.morph_poses):
            print(f"变形{i}: {morph.morph_name}, 权重: {morph.weight}")
        
        # 测试写入
        output_file = Path(__file__).parent / "test_output.vpd"
        print(f"测试写入到: {output_file}")
        parser.write_file(pose, output_file)
        
        # 测试读写一致性
        print("测试读写一致性...")
        pose2 = parser.parse_file(output_file, more_info=False)
        
        if (pose.model_name == pose2.model_name and 
            len(pose.bone_poses) == len(pose2.bone_poses) and
            len(pose.morph_poses) == len(pose2.morph_poses)):
            print("读写一致性测试通过")
        else:
            print("读写一致性测试失败")
        
        # 清理测试文件
        test_file.unlink()
        output_file.unlink()
        
        print("VPD解析器测试完成")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 清理测试文件
        if test_file.exists():
            test_file.unlink()


def test_vpd_creation():
    """测试VPD对象创建和验证"""
    print("\n=== VPD对象创建测试 ===")
    
    try:
        # 创建骨骼姿势
        bone_pose = VpdBonePose(
            bone_name="センター",
            position=[0.0, 10.0, 0.0],
            rotation=[0.1, 0.2, 0.3, 0.9]
        )
        
        # 创建变形姿势
        morph_pose = VpdMorphPose(
            morph_name="笑い",
            weight=0.8
        )
        
        # 创建完整姿势
        pose = VpdPose(
            model_name="TestModel",
            bone_poses=[bone_pose],
            morph_poses=[morph_pose]
        )
        
        # 验证数据
        pose.validate()
        print("VPD对象创建和验证成功")
        
        print(f"模型: {pose.model_name}")
        print(f"骨骼: {bone_pose.bone_name} at {bone_pose.position}")
        print(f"变形: {morph_pose.morph_name} = {morph_pose.weight}")
        
    except Exception as e:
        print(f"VPD对象创建测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_vpd_parsing()
    test_vpd_creation()