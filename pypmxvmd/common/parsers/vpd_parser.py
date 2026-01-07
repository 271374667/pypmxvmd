"""
PyPMXVMD VPD解析器

负责解析和写入VPD格式文件。
VPD是纯文本格式，用于存储单帧姿势数据。
基于Nuthouse01的原始实现重构。
"""

import re
import math
from pathlib import Path
from typing import Union, Optional, Callable

from pypmxvmd.common.models.vpd import VpdPose, VpdBonePose, VpdMorphPose


class VpdParser:
    """VPD文件解析器
    
    负责VPD文件的读取和写入操作。
    支持完整的VPD格式解析和写入。
    """
    
    def __init__(self, progress_callback: Optional[Callable[[float], None]] = None):
        """初始化VPD解析器
        
        Args:
            progress_callback: 进度回调函数，接受0.0-1.0的进度值
        """
        self._progress_callback = progress_callback
        self._setup_regex_patterns()
    
    def _setup_regex_patterns(self) -> None:
        """设置正则表达式模式"""
        # 数字模式
        n = r"\s*([-0-9\.]+)\s*"
        
        # 各种格式的模式
        self._title_pattern = re.compile(r"(.*)\.osm;")
        self._bone_pattern = re.compile(r"Bone(\d+)\{(.*?)\s*(//.*)?$")
        self._morph_pattern = re.compile(r"Morph(\d+)\{(.*?)\s*(//.*)?$")
        self._close_pattern = re.compile(r"\s*\}")
        self._f1_pattern = re.compile(n + ";")
        self._f3_pattern = re.compile(n + "," + n + "," + n + ";")
        self._f4_pattern = re.compile(n + "," + n + "," + n + "," + n + ";")
    
    def _report_progress(self, progress: float, message: str = "") -> None:
        """报告解析进度"""
        if self._progress_callback:
            self._progress_callback(progress)
    
    def _quaternion_to_euler(self, quat: list) -> list:
        """四元数转换为欧拉角（度）
        
        Args:
            quat: 四元数 [w, x, y, z]
            
        Returns:
            欧拉角 [x_deg, y_deg, z_deg]
        """
        w, x, y, z = quat
        
        # Roll (x-axis rotation)
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        
        # Pitch (y-axis rotation)
        sinp = 2 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)
        else:
            pitch = math.asin(sinp)
            
        # Yaw (z-axis rotation)
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        # 转换为度并返回
        return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]
    
    def _euler_to_quaternion(self, euler: list) -> list:
        """欧拉角（度）转换为四元数
        
        Args:
            euler: 欧拉角 [x_deg, y_deg, z_deg]
            
        Returns:
            四元数 [w, x, y, z]
        """
        roll = math.radians(euler[0])
        pitch = math.radians(euler[1])
        yaw = math.radians(euler[2])
        
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)
        
        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy
        
        return [w, x, y, z]
    
    def parse_file(self, file_path: Union[str, Path], 
                  more_info: bool = False) -> VpdPose:
        """解析VPD文件
        
        Args:
            file_path: VPD文件路径
            more_info: 是否显示详细信息
            
        Returns:
            解析后的VPD姿势对象
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        file_path = Path(file_path)
        print(f"开始解析VPD文件: {file_path}")
        
        if not file_path.exists():
            raise FileNotFoundError(f"VPD文件不存在: {file_path}")
        
        try:
            # 读取文本文件（使用shift_jis编码）
            with open(file_path, 'r', encoding='shift_jis') as f:
                lines = [line.rstrip('\n\r') for line in f.readlines()]
            
            # 验证魔术头
            if not lines or lines[0] != "Vocaloid Pose Data file":
                raise ValueError("无效的VPD文件头，期望: 'Vocaloid Pose Data file'")
            
            # 移除头部
            lines.pop(0)
            
            # 解析文件内容
            pose = self._parse_lines(lines, more_info)
            
            print("VPD解析完成")
            return pose
            
        except UnicodeDecodeError:
            # 如果shift_jis解码失败，尝试其他编码
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = [line.rstrip('\n\r') for line in f.readlines()]
                pose = self._parse_lines(lines, more_info)
                print("VPD解析完成 (使用UTF-8编码)")
                return pose
            except Exception as e:
                raise ValueError(f"VPD文件编码错误: {e}")
        except Exception as e:
            raise ValueError(f"VPD文件解析失败: {e}") from e
    
    def _parse_lines(self, lines: list, more_info: bool) -> VpdPose:
        """解析VPD文件行内容"""
        # 状态机变量
        parse_state = 0  # 0=title, 10=numbones, 20-23=bone, 30-32=morph
        num_bones = 0
        
        # 临时变量
        temp_title = ""
        temp_name = ""
        temp_pos = []
        temp_rot = []
        temp_value = 0.0
        
        # 结果存储
        bone_poses = []
        morph_poses = []
        
        for line_idx, line in enumerate(lines):
            # 跳过空行和空白行
            if not line or line.isspace():
                continue
            
            try:
                if parse_state == 0:  # 解析模型标题
                    match = self._title_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到模型标题")
                    temp_title = match.group(1)
                    if more_info:
                        print(f"模型名称: '{temp_title}'")
                    parse_state = 10
                
                elif parse_state == 10:  # 解析骨骼数量
                    match = self._f1_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到骨骼数量")
                    num_bones = int(float(match.group(1)))
                    if more_info:
                        print(f"骨骼数量: {num_bones}")
                    parse_state = 30 if num_bones == 0 else 20
                
                elif parse_state == 20:  # 解析骨骼名称
                    match = self._bone_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到骨骼名称")
                    _, temp_name = match.group(1, 2)
                    parse_state = 21
                
                elif parse_state == 21:  # 解析骨骼位置
                    match = self._f3_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到骨骼位置")
                    temp_pos = [float(x) for x in match.group(1, 2, 3)]
                    parse_state = 22
                
                elif parse_state == 22:  # 解析骨骼旋转（四元数）
                    match = self._f4_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到骨骼旋转")
                    quat_xyzw = [float(x) for x in match.group(1, 2, 3, 4)]
                    # VPD格式存储为XYZW，转换为WXYZ
                    x, y, z, w = quat_xyzw
                    quat_wxyz = [w, x, y, z]
                    # 转换为欧拉角
                    temp_rot = self._quaternion_to_euler(quat_wxyz)
                    parse_state = 23
                
                elif parse_state == 23:  # 解析骨骼结束标记
                    match = self._close_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 骨骼项未正确关闭")
                    
                    # 创建骨骼姿势对象
                    bone_pose = VpdBonePose(
                        bone_name=temp_name,
                        position=temp_pos,
                        rotation=quat_xyzw  # 保存原始四元数XYZW格式
                    )
                    bone_poses.append(bone_pose)
                    
                    # 检查是否已解析完所有骨骼
                    if len(bone_poses) == num_bones:
                        parse_state = 30
                    else:
                        parse_state = 20
                
                elif parse_state == 30:  # 解析变形名称
                    match = self._morph_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到变形名称")
                    _, temp_name = match.group(1, 2)
                    parse_state = 31
                
                elif parse_state == 31:  # 解析变形值
                    match = self._f1_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 找不到变形值")
                    temp_value = float(match.group(1))
                    parse_state = 32
                
                elif parse_state == 32:  # 解析变形结束标记
                    match = self._close_pattern.match(line)
                    if not match:
                        raise ValueError(f"第{line_idx + 2}行: 变形项未正确关闭")
                    
                    # 创建变形姿势对象
                    morph_pose = VpdMorphPose(
                        morph_name=temp_name,
                        weight=temp_value
                    )
                    morph_poses.append(morph_pose)
                    parse_state = 30  # 继续解析变形
                
                else:
                    raise ValueError(f"解析状态错误: {parse_state}")
                
            except Exception as e:
                raise ValueError(f"第{line_idx + 2}行解析失败: {e}") from e
        
        # 检查结束状态
        if parse_state != 30:
            raise ValueError(f"文件意外结束，解析状态: {parse_state}")
        
        if more_info:
            print(f"变形数量: {len(morph_poses)}")
        
        # 创建并返回VPD姿势对象
        return VpdPose(
            model_name=temp_title,
            bone_poses=bone_poses,
            morph_poses=morph_poses
        )
    
    def write_file(self, vpd_pose: VpdPose, file_path: Union[str, Path]) -> None:
        """写入VPD文件
        
        Args:
            vpd_pose: VPD姿势对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        print(f"开始写入VPD文件: {file_path}")
        
        # 验证输入数据
        vpd_pose.validate()
        
        # 构建输出行
        lines = []
        
        # 添加文件头
        lines.append("Vocaloid Pose Data file")
        lines.append("")
        
        # 添加模型名称和骨骼数量
        lines.append(f"{vpd_pose.model_name}.osm;")
        lines.append(f"{len(vpd_pose.bone_poses)};")
        lines.append("")
        
        # 写入骨骼姿势
        for idx, bone_pose in enumerate(vpd_pose.bone_poses):
            # 转换欧拉角到四元数 (如果需要)
            if len(bone_pose.rotation) == 3:
                # 如果是欧拉角，转换为四元数
                quat_wxyz = self._euler_to_quaternion(bone_pose.rotation)
                w, x, y, z = quat_wxyz
                quat_xyzw = [x, y, z, w]
            else:
                # 如果已经是四元数XYZW格式
                quat_xyzw = bone_pose.rotation
            
            lines.append(f"Bone{idx}{{{bone_pose.bone_name}")
            lines.append(f"  {bone_pose.position[0]:.6f},{bone_pose.position[1]:.6f},{bone_pose.position[2]:.6f};")
            lines.append(f"  {quat_xyzw[0]:.6f},{quat_xyzw[1]:.6f},{quat_xyzw[2]:.6f},{quat_xyzw[3]:.6f};")
            lines.append("}")
            lines.append("")
        
        # 写入变形姿势
        for idx, morph_pose in enumerate(vpd_pose.morph_poses):
            weight_str = f"{morph_pose.weight:.3f}".rstrip("0").rstrip(".")
            if not weight_str or weight_str == "":
                weight_str = "0"
            
            lines.append(f"Morph{idx}{{{morph_pose.morph_name}")
            lines.append(f"  {weight_str};")
            lines.append("}")
            lines.append("")
        
        # 写入文件
        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='shift_jis') as f:
                for line in lines:
                    f.write(line + '\n')
            
        except UnicodeEncodeError:
            # 如果shift_jis编码失败，使用utf-8
            with open(file_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')
        
        except IOError as e:
            raise IOError(f"写入VPD文件失败: {file_path}, 错误: {e}")
        
        print("VPD文件写入完成")
    
    # ===== 结构化文本解析和导出功能 =====
    
    def parse_text_file(self, file_path: Union[str, Path], more_info: bool = False) -> VpdPose:
        """解析VPD结构化文本文件（制表符分隔格式）
        
        Args:
            file_path: 文本文件路径
            more_info: 是否显示详细信息
            
        Returns:
            解析后的VPD姿势对象
            
        Raises:
            ValueError: 文件格式错误
            FileNotFoundError: 文件不存在
        """
        file_path = Path(file_path)
        if more_info:
            print(f"开始解析VPD结构化文本文件: {file_path}")
        
        # 检查文件是否为原始VPD格式还是结构化文本格式
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
        
        # 如果是原始VPD格式，使用标准解析方法
        if first_line == "Vocaloid Pose Data file":
            return self.parse_file(file_path, more_info)
        
        # 否则解析为结构化文本格式
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip().split('\t') if '\t' in line else [line.strip()] 
                    for line in f.readlines() if line.strip()]
        
        if more_info:
            print(f"结构化文本文件总行数: {len(lines)}")
            
        line_idx = 0
        
        try:
            # 解析头部
            header_info, line_idx = self._parse_structured_header(lines, line_idx)
            
            # 解析骨骼姿势
            bone_poses, line_idx = self._parse_structured_bone_poses(lines, line_idx, more_info)
            
            # 解析变形姿势
            morph_poses, line_idx = self._parse_structured_morph_poses(lines, line_idx, more_info)
            
        except (ValueError, IndexError) as e:
            raise ValueError(f"VPD结构化文本文件解析失败在第{line_idx + 1}行: {e}")
        
        if more_info:
            print(f"VPD结构化文本解析完成")
        
        return VpdPose(
            model_name=header_info['model_name'],
            bone_poses=bone_poses,
            morph_poses=morph_poses
        )
    
    def write_text_file(self, vpd_pose: VpdPose, file_path: Union[str, Path]) -> None:
        """将VPD姿势数据导出为结构化文本文件（制表符分隔格式）
        
        Args:
            vpd_pose: VPD姿势对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        print(f"开始写入VPD结构化文本文件: {file_path}")
        
        lines = []
        
        # 写入头部
        lines.extend(self._format_structured_header(vpd_pose))
        
        # 写入骨骼姿势
        lines.extend(self._format_structured_bone_poses(vpd_pose.bone_poses))
        
        # 写入变形姿势
        lines.extend(self._format_structured_morph_poses(vpd_pose.morph_poses))
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"VPD结构化文本文件写入完成，总行数: {len(lines)}")
    
    def _parse_structured_header(self, lines: list, start_idx: int) -> tuple:
        """解析结构化文本头部"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "model_name:":
            raise ValueError("缺少模型名称")
        model_name = lines[start_idx][1]
        
        header_info = {
            'model_name': model_name
        }
        
        return header_info, start_idx + 1
    
    def _parse_structured_bone_poses(self, lines: list, start_idx: int, more_info: bool) -> tuple:
        """解析结构化骨骼姿势数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "bone_pose_count:":
            raise ValueError("缺少骨骼姿势计数")
        
        bone_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"骨骼姿势数量: {bone_count}")
        
        bone_poses = []
        if bone_count > 0:
            # 跳过键名行
            if line_idx >= len(lines):
                raise ValueError("骨骼姿势数据不完整")
            line_idx += 1
            
            for i in range(bone_count):
                if line_idx >= len(lines):
                    raise ValueError(f"骨骼姿势数据不完整，期望{bone_count}个姿势，只找到{i}个")
                
                row = lines[line_idx]
                if len(row) < 8:  # 骨骼名称 + 位置(3) + 旋转(4)
                    raise ValueError(f"骨骼姿势格式错误，期望至少8个字段，得到{len(row)}个")
                
                bone_pose = VpdBonePose(
                    bone_name=row[0],
                    position=[float(row[1]), float(row[2]), float(row[3])],
                    rotation=[float(row[4]), float(row[5]), float(row[6]), float(row[7])]
                )
                bone_poses.append(bone_pose)
                line_idx += 1
        
        return bone_poses, line_idx
    
    def _parse_structured_morph_poses(self, lines: list, start_idx: int, more_info: bool) -> tuple:
        """解析结构化变形姿势数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "morph_pose_count:":
            raise ValueError("缺少变形姿势计数")
        
        morph_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"变形姿势数量: {morph_count}")
        
        morph_poses = []
        if morph_count > 0:
            # 跳过键名行
            if line_idx >= len(lines):
                raise ValueError("变形姿势数据不完整")
            line_idx += 1
            
            for i in range(morph_count):
                if line_idx >= len(lines):
                    raise ValueError(f"变形姿势数据不完整，期望{morph_count}个姿势，只找到{i}个")
                
                row = lines[line_idx]
                if len(row) != 2:
                    raise ValueError(f"变形姿势格式错误，期望2个字段，得到{len(row)}个")
                
                morph_pose = VpdMorphPose(
                    morph_name=row[0],
                    weight=float(row[1])
                )
                morph_poses.append(morph_pose)
                line_idx += 1
        
        return morph_poses, line_idx
    
    def _format_structured_header(self, vpd_pose: VpdPose) -> list:
        """格式化头部为结构化文本"""
        return [
            f"model_name:\t{vpd_pose.model_name}"
        ]
    
    def _format_structured_bone_poses(self, bone_poses: list) -> list:
        """格式化骨骼姿势为结构化文本"""
        lines = [f"bone_pose_count:\t{len(bone_poses)}"]
        
        if bone_poses:
            # 键名行
            keys = ["bone_name", "pos_x", "pos_y", "pos_z", "quat_x", "quat_y", "quat_z", "quat_w"]
            lines.append('\t'.join(keys))
            
            for bone_pose in bone_poses:
                # 确保旋转是四元数格式
                if len(bone_pose.rotation) == 3:
                    # 如果是欧拉角，转换为四元数
                    quat_wxyz = self._euler_to_quaternion(bone_pose.rotation)
                    w, x, y, z = quat_wxyz
                    rotation = [x, y, z, w]  # XYZW格式
                else:
                    rotation = bone_pose.rotation
                
                row = [
                    bone_pose.bone_name,
                    f"{bone_pose.position[0]:.6f}",
                    f"{bone_pose.position[1]:.6f}",
                    f"{bone_pose.position[2]:.6f}",
                    f"{rotation[0]:.6f}",
                    f"{rotation[1]:.6f}",
                    f"{rotation[2]:.6f}",
                    f"{rotation[3]:.6f}"
                ]
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_structured_morph_poses(self, morph_poses: list) -> list:
        """格式化变形姿势为结构化文本"""
        lines = [f"morph_pose_count:\t{len(morph_poses)}"]
        
        if morph_poses:
            lines.append('\t'.join(["morph_name", "weight"]))
            
            for morph_pose in morph_poses:
                row = [morph_pose.morph_name, f"{morph_pose.weight:.6f}"]
                lines.append('\t'.join(row))
        
        return lines