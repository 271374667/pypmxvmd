#!/usr/bin/env python3
"""VMD解析器全面测试"""

import sys
import struct
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pypmxvmd.common.parsers.vmd_parser import VmdParser
from pypmxvmd.common.models.vmd import VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame


def create_comprehensive_vmd_data():
    """创建一个包含所有类型数据的完整VMD测试文件"""
    data = bytearray()
    
    # VMD版本2的完整头部结构
    # - "Vocaloid Motion Data " (21字节)
    magic = b"Vocaloid Motion Data "
    data.extend(magic)
    
    # - "0002" (4字节)
    version = b"0002"
    data.extend(version)
    
    # - 5字节填充
    data.extend(b'\x00' * 5)
    
    # - 模型名称 (20字节)
    model_name = "TestModel初音ミク"
    model_name_bytes = model_name.encode('shift_jis')
    # 填充到20字节
    if len(model_name_bytes) < 20:
        model_name_bytes += b'\x00' * (20 - len(model_name_bytes))
    else:
        model_name_bytes = model_name_bytes[:20]
    data.extend(model_name_bytes)
    
    # 骨骼关键帧数据
    # 骨骼帧数量
    bone_frame_count = 2
    data.extend(struct.pack("<I", bone_frame_count))
    
    # 第一个骨骼帧 - 全体の親
    bone_name = "全ての親"
    bone_name_bytes = bone_name.encode('shift_jis')
    bone_name_bytes += b'\x00' * (15 - len(bone_name_bytes))
    data.extend(bone_name_bytes[:15])
    
    # 基础数据：帧号、位置、旋转四元数
    frame_num = 0
    pos_x, pos_y, pos_z = 0.0, 10.0, 0.0
    quat_x, quat_y, quat_z, quat_w = 0.1, 0.2, 0.3, 0.9
    
    data.extend(struct.pack("<I7f", frame_num, pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w))
    
    # 插值曲线数据（64字节）
    # x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay, x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by, z_ax, r_ax
    interp_data = struct.pack("<bbbb12b", 20, 20, 0, 0, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107, 107, 107)
    interp_data += b'\x00' * (64 - len(interp_data))  # 填充到64字节
    data.extend(interp_data)
    
    # 第二个骨骼帧 - センター
    bone_name = "センター"
    bone_name_bytes = bone_name.encode('shift_jis')
    bone_name_bytes += b'\x00' * (15 - len(bone_name_bytes))
    data.extend(bone_name_bytes[:15])
    
    frame_num = 30
    pos_x, pos_y, pos_z = 1.0, 0.0, -1.0
    quat_x, quat_y, quat_z, quat_w = 0.0, 0.0, 0.0, 1.0
    
    data.extend(struct.pack("<I7f", frame_num, pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w))
    data.extend(interp_data)  # 使用相同的插值数据
    
    # 变形关键帧数据
    morph_frame_count = 2
    data.extend(struct.pack("<I", morph_frame_count))
    
    # 第一个变形帧 - あ
    morph_name = "あ"
    morph_name_bytes = morph_name.encode('shift_jis')
    morph_name_bytes += b'\x00' * (15 - len(morph_name_bytes))
    data.extend(morph_name_bytes[:15])
    
    frame_num = 0
    weight = 0.5
    data.extend(struct.pack("<If", frame_num, weight))
    
    # 第二个变形帧 - まばたき
    morph_name = "まばたき"
    morph_name_bytes = morph_name.encode('shift_jis')
    morph_name_bytes += b'\x00' * (15 - len(morph_name_bytes))
    data.extend(morph_name_bytes[:15])
    
    frame_num = 15
    weight = 1.0
    data.extend(struct.pack("<If", frame_num, weight))
    
    # 相机关键帧数据 (简化为0个帧)
    data.extend(struct.pack("<I", 0))
    
    # 光源关键帧数据 (简化为0个帧)
    data.extend(struct.pack("<I", 0))
    
    # 阴影关键帧数据 (简化为0个帧)
    data.extend(struct.pack("<I", 0))
    
    # IK关键帧数据 (简化为0个帧)
    data.extend(struct.pack("<I", 0))
    
    return data


def test_vmd_comprehensive():
    """全面测试VMD解析器"""
    print("=== VMD解析器全面测试 ===")
    
    # 创建测试数据
    print("创建综合测试VMD数据...")
    test_data = create_comprehensive_vmd_data()
    
    # 保存测试文件
    test_file = Path(__file__).parent / "comprehensive_test.vmd"
    with open(test_file, 'wb') as f:
        f.write(test_data)
    
    print(f"测试文件大小: {len(test_data)}字节")
    
    # 创建解析器
    parser = VmdParser()
    
    try:
        # 测试解析
        print("开始解析测试...")
        motion = parser.parse_file(test_file, more_info=True)
        
        print("=== 解析结果验证 ===")
        print(f"版本: {motion.header.version}")
        print(f"模型名称: '{motion.header.model_name}'")
        print(f"骨骼帧数量: {len(motion.bone_frames)}")
        print(f"变形帧数量: {len(motion.morph_frames)}")
        
        # 验证骨骼帧数据
        print("\n骨骼帧详细信息:")
        for i, frame in enumerate(motion.bone_frames):
            print(f"  帧{i}: {frame.bone_name}")
            print(f"    帧号: {frame.frame_number}")
            print(f"    位置: {frame.position}")
            print(f"    旋转: {frame.rotation}")
            print(f"    物理禁用: {frame.physics_disabled}")
            print(f"    插值: {len(frame.interpolation)}个参数")
        
        # 验证变形帧数据
        print("\n变形帧详细信息:")
        for i, frame in enumerate(motion.morph_frames):
            print(f"  帧{i}: {frame.morph_name}")
            print(f"    帧号: {frame.frame_number}")
            print(f"    权重: {frame.weight}")
        
        # 测试写入
        output_file = Path(__file__).parent / "test_output_comprehensive.vmd"
        print(f"\n测试写入到: {output_file}")
        parser.write_file(motion, output_file)
        
        # 验证读写一致性
        print("测试读写一致性...")
        motion2 = parser.parse_file(output_file, more_info=False)
        
        # 比较关键数据
        consistency_check = (
            motion.header.version == motion2.header.version and
            motion.header.model_name == motion2.header.model_name and
            len(motion.bone_frames) == len(motion2.bone_frames) and
            len(motion.morph_frames) == len(motion2.morph_frames)
        )
        
        if consistency_check:
            print("读写一致性测试通过")
        else:
            print("读写一致性测试失败")
            
        # 详细比较第一个骨骼帧
        if motion.bone_frames and motion2.bone_frames:
            frame1 = motion.bone_frames[0]
            frame2 = motion2.bone_frames[0]
            
            name_match = frame1.bone_name == frame2.bone_name
            pos_match = abs(frame1.position[0] - frame2.position[0]) < 0.001
            print(f"第一个骨骼帧对比 - 名称匹配: {name_match}, 位置匹配: {pos_match}")
        
        # 清理测试文件
        test_file.unlink()
        output_file.unlink()
        
        print("VMD全面测试完成")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 清理测试文件
        if test_file.exists():
            test_file.unlink()
        assert False, f"测试失败: {e}"


if __name__ == "__main__":
    success = test_vmd_comprehensive()
    exit(0 if success else 1)