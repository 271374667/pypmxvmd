"""PyPMXVMD VMD解析器

负责解析和写入VMD格式文件。
支持VMD 1.0和2.0格式的完整解析和写入。
基于Nuthouse01的原始实现进行重构。
"""

import math
import struct
from pathlib import Path
from typing import List, Optional, Union, Callable

from pypmxvmd.common.models.vmd import (
    VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame, VmdCameraFrame,
    VmdLightFrame, VmdShadowFrame, VmdIkFrame, VmdIkBone
)
from pypmxvmd.common.io.binary_io import BinaryIOHandler


class VmdParser:
    """VMD文件解析器
    
    负责VMD文件的读取和写入操作。
    支持完整的VMD格式解析，包括骨骼帧、变形帧、相机帧等。
    """
    
    # VMD格式字符串定义（使用小端格式）
    _FMT_NUMBER = "<I"
    _FMT_BONEFRAME_NO_INTERP = "<I 7f"
    _FMT_BONEFRAME_INTERP = "<bb bb 12b xbb 45x"
    _FMT_BONEFRAME_INTERP_ONELINE = "<16b"
    _FMT_MORPHFRAME = "<I f"
    _FMT_CAMFRAME = "<I 7f 24b I ?"
    _FMT_LIGHTFRAME = "<I 3f 3f"
    _FMT_SHADOWFRAME = "<I b f"
    _FMT_IKDISPFRAME = "<I ? I"
    _FMT_IKFRAME = "<?"
    
    def __init__(self, progress_callback: Optional[Callable[[float], None]] = None):
        """初始化VMD解析器
        
        Args:
            progress_callback: 进度回调函数，接受0.0-1.0的进度值
        """
        self._io_handler = BinaryIOHandler("shift_jis")
        self._progress_callback = progress_callback
        self._current_pos = 0
        self._total_size = 0
        
    def _report_progress(self, message: str = "") -> None:
        """报告解析进度"""
        if self._progress_callback and self._total_size > 0:
            progress = min(1.0, self._current_pos / self._total_size)
            self._progress_callback(progress)
            
    def _quaternion_to_euler(self, quat: List[float]) -> List[float]:
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
        
    def _euler_to_quaternion(self, euler: List[float]) -> List[float]:
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
                  more_info: bool = False) -> VmdMotion:
        """解析VMD文件

        Args:
            file_path: VMD文件路径
            more_info: 是否显示详细信息

        Returns:
            解析后的VMD动作对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        file_path = Path(file_path)
        print(f"开始解析VMD文件: {file_path}")

        # 读取文件数据
        data = self._io_handler.read_file(file_path)
        self._total_size = len(data)
        self._current_pos = 0

        vmd_motion = VmdMotion()

        try:
            # 解析文件头
            vmd_motion.header = self._parse_header(data, more_info)

            # 解析各个数据段
            vmd_motion.bone_frames = self._parse_bone_frames(data, more_info)
            vmd_motion.morph_frames = self._parse_morph_frames(data, more_info)
            vmd_motion.camera_frames = self._parse_camera_frames(data, more_info)
            vmd_motion.light_frames = self._parse_light_frames(data, more_info)
            vmd_motion.shadow_frames = self._parse_shadow_frames(data, more_info)
            vmd_motion.ik_frames = self._parse_ik_frames(data, more_info)

            print(f"VMD解析完成: {len(vmd_motion.bone_frames)}个骨骼帧, "
                  f"{len(vmd_motion.morph_frames)}个变形帧, "
                  f"{len(vmd_motion.camera_frames)}个相机帧")

            return vmd_motion

        except Exception as e:
            raise ValueError(f"VMD文件解析失败: {e}") from e

    def parse_file_fast(self, file_path: Union[str, Path],
                       more_info: bool = False) -> VmdMotion:
        """快速解析VMD文件（性能优化版本）

        使用内部缓冲区和偏移量追踪，避免O(n)的切片删除操作。
        对于大型VMD文件，性能提升显著。

        Args:
            file_path: VMD文件路径
            more_info: 是否显示详细信息

        Returns:
            解析后的VMD动作对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        file_path = Path(file_path)
        if more_info:
            print(f"开始快速解析VMD文件: {file_path}")

        # 使用快速读取方法
        self._io_handler.read_file_fast(file_path)
        self._total_size = self._io_handler.get_total_size()
        self._current_pos = 0

        vmd_motion = VmdMotion()

        try:
            # 解析文件头
            vmd_motion.header = self._parse_header_fast(more_info)

            # 解析各个数据段
            vmd_motion.bone_frames = self._parse_bone_frames_fast(more_info)
            vmd_motion.morph_frames = self._parse_morph_frames_fast(more_info)
            vmd_motion.camera_frames = self._parse_camera_frames_fast(more_info)
            vmd_motion.light_frames = self._parse_light_frames_fast(more_info)
            vmd_motion.shadow_frames = self._parse_shadow_frames_fast(more_info)
            vmd_motion.ik_frames = self._parse_ik_frames_fast(more_info)

            if more_info:
                print(f"VMD快速解析完成: {len(vmd_motion.bone_frames)}个骨骼帧, "
                      f"{len(vmd_motion.morph_frames)}个变形帧, "
                      f"{len(vmd_motion.camera_frames)}个相机帧")

            return vmd_motion

        except Exception as e:
            raise ValueError(f"VMD文件快速解析失败: {e}") from e
    
    def _parse_header(self, data: bytearray, more_info: bool) -> VmdHeader:
        """解析VMD文件头"""
        # VMD头部格式：
        # - "Vocaloid Motion Data " (21字节，包含空格)
        # - 版本字符串 ("0002" 或 "file", 4字节)
        # - 5字节填充
        # - 模型名称 (10或20字节，取决于版本)
        
        # 读取魔术字符串 "Vocaloid Motion Data " (21字节)
        magic_str = self._io_handler.read_string(data, 21, null_terminated=False)
        if magic_str != "Vocaloid Motion Data ":
            raise ValueError(f"无效的VMD魔术字符串: '{magic_str}'")
        
        # 读取版本字符串 (4字节)
        version_str = self._io_handler.read_string(data, 4, null_terminated=False)
        
        if version_str == "0002":
            version = 2
            name_length = 20
        elif version_str == "file":
            version = 1
            name_length = 10
        else:
            raise ValueError(f"不支持的VMD版本标识: '{version_str}'")
        
        # 跳过5字节填充
        padding = data[:5]
        del data[:5]
        self._current_pos = self._io_handler.get_position() + 5
        
        # 读取模型名称
        model_name = self._io_handler.read_string(data, name_length)
        
        if more_info:
            print(f"VMD版本: {version}, 模型名称: '{model_name}'")
        
        self._current_pos = self._io_handler.get_position()
        self._report_progress("解析文件头")
        
        return VmdHeader(version=version, model_name=model_name)
    
    def _parse_bone_frames(self, data: bytearray, more_info: bool) -> List[VmdBoneFrame]:
        """解析骨骼关键帧"""
        if len(data) < 4:
            print("警告: 文件意外结束，假设骨骼帧数为0")
            return []
            
        frame_count = self._io_handler.unpack_data(self._FMT_NUMBER, data)[0]
        bone_frames = []
        
        if more_info:
            print(f"解析 {frame_count} 个骨骼关键帧...")
        
        for i in range(frame_count):
            try:
                # 读取骨骼名称
                bone_name = self._io_handler.read_string(data, 15)
                
                # 读取基础数据
                frame_data = self._io_handler.unpack_data(self._FMT_BONEFRAME_NO_INTERP, data)
                frame_num, px, py, pz, qx, qy, qz, qw = frame_data
                
                # 读取插值曲线数据
                interp_data = self._io_handler.unpack_data(self._FMT_BONEFRAME_INTERP, data)
                x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay, \
                x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by, z_ax, r_ax = interp_data
                
                # 四元数转欧拉角
                euler_rotation = self._quaternion_to_euler([qw, qx, qy, qz])
                
                # 检测物理开关状态
                if (phys1, phys2) == (z_ax, r_ax):
                    physics_disabled = False
                elif (phys1, phys2) == (0, 0):
                    physics_disabled = False
                elif (phys1, phys2) == (99, 15):
                    physics_disabled = True
                else:
                    physics_disabled = True
                
                # 构建插值数据
                interpolation = [
                    x_ax, x_ay, x_bx, x_by,  # X轴插值
                    y_ax, y_ay, y_bx, y_by,  # Y轴插值
                    z_ax, z_ay, z_bx, z_by,  # Z轴插值
                    r_ax, r_ay, r_bx, r_by   # 旋转插值
                ]
                
                bone_frame = VmdBoneFrame(
                    bone_name=bone_name,
                    frame_number=frame_num,
                    position=[px, py, pz],
                    rotation=euler_rotation,
                    interpolation=interpolation,
                    physics_disabled=physics_disabled
                )
                
                bone_frames.append(bone_frame)
                
                if i % 1000 == 0:
                    self._current_pos = self._io_handler.get_position()
                    self._report_progress(f"解析骨骼帧 {i}/{frame_count}")
                    
            except Exception as e:
                raise ValueError(f"解析第{i}个骨骼帧失败: {e}") from e
        
        return bone_frames
    
    def _parse_morph_frames(self, data: bytearray, more_info: bool) -> List[VmdMorphFrame]:
        """解析变形关键帧"""
        if len(data) < 4:
            print("警告: 文件意外结束，假设变形帧数为0")
            return []
            
        frame_count = self._io_handler.unpack_data(self._FMT_NUMBER, data)[0]
        morph_frames = []
        
        if more_info:
            print(f"解析 {frame_count} 个变形关键帧...")
        
        for i in range(frame_count):
            try:
                morph_name = self._io_handler.read_string(data, 15)
                frame_num, weight = self._io_handler.unpack_data(self._FMT_MORPHFRAME, data)
                
                morph_frame = VmdMorphFrame(
                    morph_name=morph_name,
                    frame_number=frame_num,
                    weight=weight
                )
                
                morph_frames.append(morph_frame)
                
                if i % 1000 == 0:
                    self._current_pos = self._io_handler.get_position()
                    self._report_progress(f"解析变形帧 {i}/{frame_count}")
                    
            except Exception as e:
                raise ValueError(f"解析第{i}个变形帧失败: {e}") from e
        
        return morph_frames
    
    def _parse_camera_frames(self, data: bytearray, more_info: bool) -> List[VmdCameraFrame]:
        """解析相机关键帧"""
        if len(data) < 4:
            print("警告: 文件意外结束，假设相机帧数为0")
            return []
            
        frame_count = self._io_handler.unpack_data(self._FMT_NUMBER, data)[0]
        camera_frames = []
        
        if more_info:
            print(f"解析 {frame_count} 个相机关键帧...")
        
        for i in range(frame_count):
            try:
                cam_data = self._io_handler.unpack_data(self._FMT_CAMFRAME, data)
                (
                    frame_num, distance, px, py, pz, rx, ry, rz,
                    x_ax, x_bx, x_ay, x_by, y_ax, y_bx, y_ay, y_by,
                    z_ax, z_bx, z_ay, z_by, r_ax, r_bx, r_ay, r_by,
                    dist_ax, dist_bx, dist_ay, dist_by, 
                    fov_ax, fov_bx, fov_ay, fov_by,
                    fov, perspective
                ) = cam_data
                
                # 弧度转度
                rotation = [math.degrees(rx), math.degrees(ry), math.degrees(rz)]
                
                # 构建插值数据
                interpolation = [
                    x_ax, x_ay, x_bx, x_by,      # X轴
                    y_ax, y_ay, y_bx, y_by,      # Y轴  
                    z_ax, z_ay, z_bx, z_by,      # Z轴
                    r_ax, r_ay, r_bx, r_by,      # 旋转
                    dist_ax, dist_ay, dist_bx, dist_by,  # 距离
                    fov_ax, fov_ay, fov_bx, fov_by       # FOV
                ]
                
                camera_frame = VmdCameraFrame(
                    frame_number=frame_num,
                    distance=distance,
                    position=[px, py, pz],
                    rotation=rotation,
                    interpolation=interpolation,
                    fov=fov,
                    perspective=bool(perspective)
                )
                
                camera_frames.append(camera_frame)
                
            except Exception as e:
                raise ValueError(f"解析第{i}个相机帧失败: {e}") from e
        
        return camera_frames
    
    def _parse_light_frames(self, data: bytearray, more_info: bool) -> List[VmdLightFrame]:
        """解析光源关键帧"""
        if len(data) < 4:
            print("警告: 文件意外结束，假设光源帧数为0")
            return []
            
        frame_count = self._io_handler.unpack_data(self._FMT_NUMBER, data)[0]
        light_frames = []
        
        if more_info:
            print(f"解析 {frame_count} 个光源关键帧...")
        
        for i in range(frame_count):
            try:
                frame_num, r, g, b, x, y, z = self._io_handler.unpack_data(self._FMT_LIGHTFRAME, data)
                
                light_frame = VmdLightFrame(
                    frame_number=frame_num,
                    color=[r, g, b],
                    position=[x, y, z]
                )
                
                light_frames.append(light_frame)
                
            except Exception as e:
                raise ValueError(f"解析第{i}个光源帧失败: {e}") from e
        
        return light_frames
    
    def _parse_shadow_frames(self, data: bytearray, more_info: bool) -> List[VmdShadowFrame]:
        """解析阴影关键帧"""
        if len(data) < 4:
            print("警告: 文件意外结束，假设阴影帧数为0")
            return []
            
        frame_count = self._io_handler.unpack_data(self._FMT_NUMBER, data)[0]
        shadow_frames = []
        
        if more_info:
            print(f"解析 {frame_count} 个阴影关键帧...")
        
        for i in range(frame_count):
            try:
                frame_num, mode, distance = self._io_handler.unpack_data(self._FMT_SHADOWFRAME, data)
                
                shadow_frame = VmdShadowFrame(
                    frame_number=frame_num,
                    shadow_mode=mode,
                    distance=distance
                )
                
                shadow_frames.append(shadow_frame)
                
            except Exception as e:
                raise ValueError(f"解析第{i}个阴影帧失败: {e}") from e
        
        return shadow_frames
    
    def _parse_ik_frames(self, data: bytearray, more_info: bool) -> List[VmdIkFrame]:
        """解析IK显示关键帧"""
        if len(data) < 4:
            print("警告: 文件意外结束，假设IK帧数为0")
            return []
            
        frame_count = self._io_handler.unpack_data(self._FMT_NUMBER, data)[0]
        ik_frames = []
        
        if more_info:
            print(f"解析 {frame_count} 个IK关键帧...")
        
        for i in range(frame_count):
            try:
                frame_num, display, ik_count = self._io_handler.unpack_data(self._FMT_IKDISPFRAME, data)
                
                ik_bones = []
                for j in range(ik_count):
                    bone_name = self._io_handler.read_string(data, 20)
                    ik_enabled = bool(self._io_handler.unpack_data(self._FMT_IKFRAME, data)[0])
                    
                    ik_bone = VmdIkBone(
                        bone_name=bone_name,
                        ik_enabled=ik_enabled
                    )
                    ik_bones.append(ik_bone)
                
                ik_frame = VmdIkFrame(
                    frame_number=frame_num,
                    display=bool(display),
                    ik_bones=ik_bones
                )
                
                ik_frames.append(ik_frame)

            except Exception as e:
                raise ValueError(f"解析第{i}个IK帧失败: {e}") from e

        return ik_frames

    # ===== 快速解析方法（性能优化版本） =====

    def _parse_header_fast(self, more_info: bool) -> VmdHeader:
        """快速解析VMD文件头（使用内部缓冲区）"""
        # 读取魔术字符串 "Vocaloid Motion Data " (21字节)
        magic_str = self._io_handler.read_string_from_buffer(21, null_terminated=False)
        if magic_str != "Vocaloid Motion Data ":
            raise ValueError(f"无效的VMD魔术字符串: '{magic_str}'")

        # 读取版本字符串 (4字节)
        version_str = self._io_handler.read_string_from_buffer(4, null_terminated=False)

        if version_str == "0002":
            version = 2
            name_length = 20
        elif version_str == "file":
            version = 1
            name_length = 10
        else:
            raise ValueError(f"不支持的VMD版本标识: '{version_str}'")

        # 跳过5字节填充
        self._io_handler.skip_bytes(5)

        # 读取模型名称
        model_name = self._io_handler.read_string_from_buffer(name_length)

        if more_info:
            print(f"VMD版本: {version}, 模型名称: '{model_name}'")

        self._current_pos = self._io_handler.get_position()
        self._report_progress("解析文件头")

        return VmdHeader(version=version, model_name=model_name)

    def _parse_bone_frames_fast(self, more_info: bool) -> List[VmdBoneFrame]:
        """快速解析骨骼关键帧（使用内部缓冲区）"""
        if self._io_handler.get_remaining_size() < 4:
            if more_info:
                print("警告: 文件意外结束，假设骨骼帧数为0")
            return []

        frame_count = self._io_handler.unpack_from_buffer(self._FMT_NUMBER)[0]
        bone_frames = []

        if more_info:
            print(f"解析 {frame_count} 个骨骼关键帧...")

        for i in range(frame_count):
            try:
                # 读取骨骼名称
                bone_name = self._io_handler.read_string_from_buffer(15)

                # 读取基础数据
                frame_data = self._io_handler.unpack_from_buffer(self._FMT_BONEFRAME_NO_INTERP)
                frame_num, px, py, pz, qx, qy, qz, qw = frame_data

                # 读取插值曲线数据
                interp_data = self._io_handler.unpack_from_buffer(self._FMT_BONEFRAME_INTERP)
                x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay, \
                x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by, z_ax, r_ax = interp_data

                # 四元数转欧拉角
                euler_rotation = self._quaternion_to_euler([qw, qx, qy, qz])

                # 检测物理开关状态
                if (phys1, phys2) == (z_ax, r_ax):
                    physics_disabled = False
                elif (phys1, phys2) == (0, 0):
                    physics_disabled = False
                elif (phys1, phys2) == (99, 15):
                    physics_disabled = True
                else:
                    physics_disabled = True

                # 构建插值数据
                interpolation = [
                    x_ax, x_ay, x_bx, x_by,  # X轴插值
                    y_ax, y_ay, y_bx, y_by,  # Y轴插值
                    z_ax, z_ay, z_bx, z_by,  # Z轴插值
                    r_ax, r_ay, r_bx, r_by   # 旋转插值
                ]

                bone_frame = VmdBoneFrame(
                    bone_name=bone_name,
                    frame_number=frame_num,
                    position=[px, py, pz],
                    rotation=euler_rotation,
                    interpolation=interpolation,
                    physics_disabled=physics_disabled
                )

                bone_frames.append(bone_frame)

                if i % 1000 == 0:
                    self._current_pos = self._io_handler.get_position()
                    self._report_progress(f"解析骨骼帧 {i}/{frame_count}")

            except Exception as e:
                raise ValueError(f"解析第{i}个骨骼帧失败: {e}") from e

        return bone_frames

    def _parse_morph_frames_fast(self, more_info: bool) -> List[VmdMorphFrame]:
        """快速解析变形关键帧（使用内部缓冲区）"""
        if self._io_handler.get_remaining_size() < 4:
            if more_info:
                print("警告: 文件意外结束，假设变形帧数为0")
            return []

        frame_count = self._io_handler.unpack_from_buffer(self._FMT_NUMBER)[0]
        morph_frames = []

        if more_info:
            print(f"解析 {frame_count} 个变形关键帧...")

        for i in range(frame_count):
            try:
                morph_name = self._io_handler.read_string_from_buffer(15)
                frame_num, weight = self._io_handler.unpack_from_buffer(self._FMT_MORPHFRAME)

                morph_frame = VmdMorphFrame(
                    morph_name=morph_name,
                    frame_number=frame_num,
                    weight=weight
                )

                morph_frames.append(morph_frame)

                if i % 1000 == 0:
                    self._current_pos = self._io_handler.get_position()
                    self._report_progress(f"解析变形帧 {i}/{frame_count}")

            except Exception as e:
                raise ValueError(f"解析第{i}个变形帧失败: {e}") from e

        return morph_frames

    def _parse_camera_frames_fast(self, more_info: bool) -> List[VmdCameraFrame]:
        """快速解析相机关键帧（使用内部缓冲区）"""
        if self._io_handler.get_remaining_size() < 4:
            if more_info:
                print("警告: 文件意外结束，假设相机帧数为0")
            return []

        frame_count = self._io_handler.unpack_from_buffer(self._FMT_NUMBER)[0]
        camera_frames = []

        if more_info:
            print(f"解析 {frame_count} 个相机关键帧...")

        for i in range(frame_count):
            try:
                cam_data = self._io_handler.unpack_from_buffer(self._FMT_CAMFRAME)
                (
                    frame_num, distance, px, py, pz, rx, ry, rz,
                    x_ax, x_bx, x_ay, x_by, y_ax, y_bx, y_ay, y_by,
                    z_ax, z_bx, z_ay, z_by, r_ax, r_bx, r_ay, r_by,
                    dist_ax, dist_bx, dist_ay, dist_by,
                    fov_ax, fov_bx, fov_ay, fov_by,
                    fov, perspective
                ) = cam_data

                # 弧度转度
                rotation = [math.degrees(rx), math.degrees(ry), math.degrees(rz)]

                # 构建插值数据
                interpolation = [
                    x_ax, x_ay, x_bx, x_by,      # X轴
                    y_ax, y_ay, y_bx, y_by,      # Y轴
                    z_ax, z_ay, z_bx, z_by,      # Z轴
                    r_ax, r_ay, r_bx, r_by,      # 旋转
                    dist_ax, dist_ay, dist_bx, dist_by,  # 距离
                    fov_ax, fov_ay, fov_bx, fov_by       # FOV
                ]

                camera_frame = VmdCameraFrame(
                    frame_number=frame_num,
                    distance=distance,
                    position=[px, py, pz],
                    rotation=rotation,
                    interpolation=interpolation,
                    fov=fov,
                    perspective=bool(perspective)
                )

                camera_frames.append(camera_frame)

            except Exception as e:
                raise ValueError(f"解析第{i}个相机帧失败: {e}") from e

        return camera_frames

    def _parse_light_frames_fast(self, more_info: bool) -> List[VmdLightFrame]:
        """快速解析光源关键帧（使用内部缓冲区）"""
        if self._io_handler.get_remaining_size() < 4:
            if more_info:
                print("警告: 文件意外结束，假设光源帧数为0")
            return []

        frame_count = self._io_handler.unpack_from_buffer(self._FMT_NUMBER)[0]
        light_frames = []

        if more_info:
            print(f"解析 {frame_count} 个光源关键帧...")

        for i in range(frame_count):
            try:
                frame_num, r, g, b, x, y, z = self._io_handler.unpack_from_buffer(self._FMT_LIGHTFRAME)

                light_frame = VmdLightFrame(
                    frame_number=frame_num,
                    color=[r, g, b],
                    position=[x, y, z]
                )

                light_frames.append(light_frame)

            except Exception as e:
                raise ValueError(f"解析第{i}个光源帧失败: {e}") from e

        return light_frames

    def _parse_shadow_frames_fast(self, more_info: bool) -> List[VmdShadowFrame]:
        """快速解析阴影关键帧（使用内部缓冲区）"""
        if self._io_handler.get_remaining_size() < 4:
            if more_info:
                print("警告: 文件意外结束，假设阴影帧数为0")
            return []

        frame_count = self._io_handler.unpack_from_buffer(self._FMT_NUMBER)[0]
        shadow_frames = []

        if more_info:
            print(f"解析 {frame_count} 个阴影关键帧...")

        for i in range(frame_count):
            try:
                frame_num, mode, distance = self._io_handler.unpack_from_buffer(self._FMT_SHADOWFRAME)

                shadow_frame = VmdShadowFrame(
                    frame_number=frame_num,
                    shadow_mode=mode,
                    distance=distance
                )

                shadow_frames.append(shadow_frame)

            except Exception as e:
                raise ValueError(f"解析第{i}个阴影帧失败: {e}") from e

        return shadow_frames

    def _parse_ik_frames_fast(self, more_info: bool) -> List[VmdIkFrame]:
        """快速解析IK显示关键帧（使用内部缓冲区）"""
        if self._io_handler.get_remaining_size() < 4:
            if more_info:
                print("警告: 文件意外结束，假设IK帧数为0")
            return []

        frame_count = self._io_handler.unpack_from_buffer(self._FMT_NUMBER)[0]
        ik_frames = []

        if more_info:
            print(f"解析 {frame_count} 个IK关键帧...")

        for i in range(frame_count):
            try:
                frame_num, display, ik_count = self._io_handler.unpack_from_buffer(self._FMT_IKDISPFRAME)

                ik_bones = []
                for j in range(ik_count):
                    bone_name = self._io_handler.read_string_from_buffer(20)
                    ik_enabled = bool(self._io_handler.unpack_from_buffer(self._FMT_IKFRAME)[0])

                    ik_bone = VmdIkBone(
                        bone_name=bone_name,
                        ik_enabled=ik_enabled
                    )
                    ik_bones.append(ik_bone)

                ik_frame = VmdIkFrame(
                    frame_number=frame_num,
                    display=bool(display),
                    ik_bones=ik_bones
                )

                ik_frames.append(ik_frame)

            except Exception as e:
                raise ValueError(f"解析第{i}个IK帧失败: {e}") from e

        return ik_frames

    def write_file(self, vmd_motion: VmdMotion, 
                  file_path: Union[str, Path]) -> None:
        """写入VMD文件
        
        Args:
            vmd_motion: VMD动作对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        print(f"开始写入VMD文件: {file_path}")
        
        # 验证数据
        vmd_motion.validate()
        
        # 构建二进制数据
        binary_data = bytearray()
        
        # 编码文件头
        binary_data.extend(self._encode_header(vmd_motion.header))
        
        # 编码各数据段
        binary_data.extend(self._encode_bone_frames(vmd_motion.bone_frames))
        binary_data.extend(self._encode_morph_frames(vmd_motion.morph_frames))
        binary_data.extend(self._encode_camera_frames(vmd_motion.camera_frames))
        binary_data.extend(self._encode_light_frames(vmd_motion.light_frames))
        binary_data.extend(self._encode_shadow_frames(vmd_motion.shadow_frames))
        binary_data.extend(self._encode_ik_frames(vmd_motion.ik_frames))
        
        # 写入文件
        self._io_handler.write_file(file_path, bytes(binary_data))
        
        print("VMD文件写入完成")
    
    def _encode_header(self, header: VmdHeader) -> bytes:
        """编码文件头"""
        data = bytearray()
        
        # 魔术字符串 "Vocaloid Motion Data " (21字节)
        data.extend(self._io_handler.write_string("Vocaloid Motion Data ", 21, False))
        
        # 版本标识和相关参数
        if header.version == 2:
            version_str = "0002"
            name_length = 20
        else:
            version_str = "file"
            name_length = 10
        
        # 版本字符串 (4字节)
        data.extend(self._io_handler.write_string(version_str, 4, False))
        
        # 5字节填充
        data.extend(b'\x00' * 5)
        
        # 模型名称
        data.extend(self._io_handler.write_string(header.model_name, name_length))
        
        return bytes(data)
    
    def _encode_bone_frames(self, bone_frames: List[VmdBoneFrame]) -> bytes:
        """编码骨骼关键帧"""
        data = bytearray()
        
        # 写入帧数
        data.extend(self._io_handler.pack_data(self._FMT_NUMBER, len(bone_frames)))
        
        for frame in bone_frames:
            # 骨骼名称
            data.extend(self._io_handler.write_string(frame.bone_name, 15))
            
            # 转换欧拉角为四元数
            quat = self._euler_to_quaternion(frame.rotation)
            qw, qx, qy, qz = quat
            
            # 基础数据
            frame_data = (
                frame.frame_number,
                frame.position[0], frame.position[1], frame.position[2],
                qx, qy, qz, qw
            )
            data.extend(self._io_handler.pack_data(self._FMT_BONEFRAME_NO_INTERP, *frame_data))
            
            # 插值数据（简化处理）
            interp = frame.interpolation if frame.interpolation else [20, 20, 107, 107] * 4
            
            # 构建插值曲线数据
            x_ax, x_ay, x_bx, x_by = interp[0:4]
            y_ax, y_ay, y_bx, y_by = interp[4:8]
            z_ax, z_ay, z_bx, z_by = interp[8:12]
            r_ax, r_ay, r_bx, r_by = interp[12:16]
            
            # 物理标志
            if frame.physics_disabled:
                phys1, phys2 = 99, 15
            else:
                phys1, phys2 = z_ax, r_ax
            
            interp_data = (
                x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay,
                x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by,
                z_ax, r_ax
            )
            data.extend(self._io_handler.pack_data(self._FMT_BONEFRAME_INTERP, *interp_data))
        
        return bytes(data)
    
    def _encode_morph_frames(self, morph_frames: List[VmdMorphFrame]) -> bytes:
        """编码变形关键帧"""
        data = bytearray()
        
        data.extend(self._io_handler.pack_data(self._FMT_NUMBER, len(morph_frames)))
        
        for frame in morph_frames:
            data.extend(self._io_handler.write_string(frame.morph_name, 15))
            data.extend(self._io_handler.pack_data(self._FMT_MORPHFRAME, 
                                                 frame.frame_number, frame.weight))
        
        return bytes(data)
    
    def _encode_camera_frames(self, camera_frames: List[VmdCameraFrame]) -> bytes:
        """编码相机关键帧"""
        data = bytearray()
        
        data.extend(self._io_handler.pack_data(self._FMT_NUMBER, len(camera_frames)))
        
        for frame in camera_frames:
            # 度转弧度
            rx = math.radians(frame.rotation[0])
            ry = math.radians(frame.rotation[1])
            rz = math.radians(frame.rotation[2])
            
            # 插值数据（简化处理）
            interp = frame.interpolation if frame.interpolation else [20, 107, 20, 107] * 6
            
            cam_data = (
                frame.frame_number, frame.distance,
                frame.position[0], frame.position[1], frame.position[2],
                rx, ry, rz,
                *interp,  # 24个插值参数
                frame.fov, int(frame.perspective)
            )
            
            data.extend(self._io_handler.pack_data(self._FMT_CAMFRAME, *cam_data))
        
        return bytes(data)
    
    def _encode_light_frames(self, light_frames: List[VmdLightFrame]) -> bytes:
        """编码光源关键帧"""
        data = bytearray()
        
        data.extend(self._io_handler.pack_data(self._FMT_NUMBER, len(light_frames)))
        
        for frame in light_frames:
            light_data = (
                frame.frame_number,
                frame.color[0], frame.color[1], frame.color[2],
                frame.position[0], frame.position[1], frame.position[2]
            )
            data.extend(self._io_handler.pack_data(self._FMT_LIGHTFRAME, *light_data))
        
        return bytes(data)
    
    def _encode_shadow_frames(self, shadow_frames: List[VmdShadowFrame]) -> bytes:
        """编码阴影关键帧"""
        data = bytearray()
        
        data.extend(self._io_handler.pack_data(self._FMT_NUMBER, len(shadow_frames)))
        
        for frame in shadow_frames:
            shadow_data = (frame.frame_number, frame.shadow_mode, frame.distance)
            data.extend(self._io_handler.pack_data(self._FMT_SHADOWFRAME, *shadow_data))
        
        return bytes(data)
    
    def _encode_ik_frames(self, ik_frames: List[VmdIkFrame]) -> bytes:
        """编码IK关键帧"""
        data = bytearray()
        
        data.extend(self._io_handler.pack_data(self._FMT_NUMBER, len(ik_frames)))
        
        for frame in ik_frames:
            data.extend(self._io_handler.pack_data(self._FMT_IKDISPFRAME,
                                                 frame.frame_number, 
                                                 int(frame.display),
                                                 len(frame.ik_bones)))
            
            for ik_bone in frame.ik_bones:
                data.extend(self._io_handler.write_string(ik_bone.bone_name, 20))
                data.extend(self._io_handler.pack_data(self._FMT_IKFRAME, 
                                                     int(ik_bone.ik_enabled)))
        
        return bytes(data)
    
    # ===== 文本解析和导出功能 =====
    
    def parse_text_file(self, file_path: Union[str, Path], more_info: bool = False) -> VmdMotion:
        """解析VMD文本文件
        
        Args:
            file_path: 文本文件路径
            more_info: 是否显示详细信息
            
        Returns:
            解析后的VMD运动对象
            
        Raises:
            ValueError: 文件格式错误
            FileNotFoundError: 文件不存在
        """
        file_path = Path(file_path)
        if more_info:
            print(f"开始解析VMD文本文件: {file_path}")
            
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip().split('\t') if '\t' in line else [line.strip()] 
                    for line in f.readlines() if line.strip()]
        
        if more_info:
            print(f"文本文件总行数: {len(lines)}")
            
        line_idx = 0
        
        try:
            # 解析头部
            header = self._parse_text_header(lines, line_idx)
            line_idx += 2
            
            # 解析骨骼帧
            bone_frames, line_idx = self._parse_text_bone_frames(lines, line_idx, more_info)
            
            # 解析变形帧
            morph_frames, line_idx = self._parse_text_morph_frames(lines, line_idx, more_info)
            
            # 解析相机帧
            camera_frames, line_idx = self._parse_text_camera_frames(lines, line_idx, more_info)
            
            # 解析光源帧
            light_frames, line_idx = self._parse_text_light_frames(lines, line_idx, more_info)
            
            # 解析阴影帧
            shadow_frames, line_idx = self._parse_text_shadow_frames(lines, line_idx, more_info)
            
            # 解析IK帧
            ik_frames, line_idx = self._parse_text_ik_frames(lines, line_idx, more_info)
            
        except (ValueError, IndexError) as e:
            raise ValueError(f"VMD文本文件解析失败在第{line_idx + 1}行: {e}")
        
        if more_info:
            print(f"VMD文本解析完成")
        
        # 创建VMD运动对象并设置属性
        motion = VmdMotion()
        motion.header = header
        motion.bone_frames = bone_frames
        motion.morph_frames = morph_frames
        motion.camera_frames = camera_frames
        motion.light_frames = light_frames
        motion.shadow_frames = shadow_frames
        motion.ik_frames = ik_frames
        
        return motion
    
    def write_text_file(self, motion: VmdMotion, file_path: Union[str, Path]) -> None:
        """将VMD运动数据导出为文本文件
        
        Args:
            motion: VMD运动对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        print(f"开始写入VMD文本文件: {file_path}")
        
        lines = []
        
        # 写入头部
        lines.extend(self._format_text_header(motion.header))
        
        # 写入骨骼帧
        lines.extend(self._format_text_bone_frames(motion.bone_frames))
        
        # 写入变形帧
        lines.extend(self._format_text_morph_frames(motion.morph_frames))
        
        # 写入相机帧
        lines.extend(self._format_text_camera_frames(motion.camera_frames))
        
        # 写入光源帧
        lines.extend(self._format_text_light_frames(motion.light_frames))
        
        # 写入阴影帧
        lines.extend(self._format_text_shadow_frames(motion.shadow_frames))
        
        # 写入IK帧
        lines.extend(self._format_text_ik_frames(motion.ik_frames))
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"VMD文本文件写入完成，总行数: {len(lines)}")
    
    def _parse_text_header(self, lines: List[List[str]], start_idx: int) -> VmdHeader:
        """解析文本文件头部"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "version:":
            raise ValueError("缺少版本信息")
        version = lines[start_idx][1]
        
        if start_idx + 1 >= len(lines) or len(lines[start_idx + 1]) != 2 or lines[start_idx + 1][0] != "modelname:":
            raise ValueError("缺少模型名称")
        model_name = lines[start_idx + 1][1]
        
        return VmdHeader(version=version, model_name=model_name)
    
    def _parse_text_bone_frames(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析骨骼帧数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "boneframe_ct:":
            raise ValueError("缺少骨骼帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"骨骼帧数量: {frame_count}")
        
        bone_frames = []
        if frame_count > 0:
            # 跳过键名行
            if line_idx >= len(lines):
                raise ValueError("骨骼帧数据不完整")
            line_idx += 1
            
            for i in range(frame_count):
                if line_idx >= len(lines):
                    raise ValueError(f"骨骼帧数据不完整，期望{frame_count}帧，只找到{i}帧")
                
                row = lines[line_idx]
                if len(row) < 25:  # 最少25个字段
                    raise ValueError(f"骨骼帧格式错误，期望至少25个字段，得到{len(row)}个")
                
                # 文本格式使用欧拉角（度数），直接使用
                euler_angles = [float(row[5]), float(row[6]), float(row[7])]
                
                frame = VmdBoneFrame(
                    bone_name=row[0],
                    frame_number=int(row[1]),
                    position=[float(row[2]), float(row[3]), float(row[4])],
                    rotation=euler_angles,
                    physics_disabled=bool(int(row[8])),
                    interpolation=[
                        int(row[9]), int(row[10]), int(row[11]), int(row[12]),   # x
                        int(row[13]), int(row[14]), int(row[15]), int(row[16]),  # y
                        int(row[17]), int(row[18]), int(row[19]), int(row[20]),  # z
                        int(row[21]), int(row[22]), int(row[23]), int(row[24])   # r
                    ]
                )
                bone_frames.append(frame)
                line_idx += 1
        
        return bone_frames, line_idx
    
    def _parse_text_morph_frames(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析变形帧数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "morphframe_ct:":
            raise ValueError("缺少变形帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"变形帧数量: {frame_count}")
        
        morph_frames = []
        if frame_count > 0:
            # 跳过键名行
            line_idx += 1
            
            for i in range(frame_count):
                if line_idx >= len(lines):
                    raise ValueError(f"变形帧数据不完整")
                
                row = lines[line_idx]
                if len(row) != 3:
                    raise ValueError(f"变形帧格式错误，期望3个字段，得到{len(row)}个")
                
                frame = VmdMorphFrame(
                    morph_name=row[0],
                    frame_number=int(row[1]),
                    weight=float(row[2])
                )
                morph_frames.append(frame)
                line_idx += 1
        
        return morph_frames, line_idx
    
    def _parse_text_camera_frames(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析相机帧数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "camframe_ct:":
            raise ValueError("缺少相机帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"相机帧数量: {frame_count}")
        
        camera_frames = []
        if frame_count > 0:
            # 跳过键名行
            line_idx += 1
            
            for i in range(frame_count):
                if line_idx >= len(lines):
                    raise ValueError(f"相机帧数据不完整")
                
                row = lines[line_idx]
                if len(row) < 34:
                    raise ValueError(f"相机帧格式错误，期望至少34个字段，得到{len(row)}个")
                
                frame = VmdCameraFrame(
                    frame_number=int(row[0]),
                    distance=float(row[1]),
                    position=[float(row[2]), float(row[3]), float(row[4])],
                    rotation=[float(row[5]), float(row[6]), float(row[7])],
                    fov=float(row[8]),
                    perspective=bool(int(row[9])),
                    interpolation=[int(r) for r in row[10:34]]
                )
                camera_frames.append(frame)
                line_idx += 1
        
        return camera_frames, line_idx
    
    def _parse_text_light_frames(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析光源帧数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "lightframe_ct:":
            raise ValueError("缺少光源帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"光源帧数量: {frame_count}")
        
        light_frames = []
        if frame_count > 0:
            # 跳过键名行
            line_idx += 1
            
            for i in range(frame_count):
                if line_idx >= len(lines):
                    raise ValueError(f"光源帧数据不完整")
                
                row = lines[line_idx]
                if len(row) != 7:
                    raise ValueError(f"光源帧格式错误，期望7个字段，得到{len(row)}个")
                
                frame = VmdLightFrame(
                    frame_number=int(row[0]),
                    color=[float(row[1]), float(row[2]), float(row[3])],
                    position=[float(row[4]), float(row[5]), float(row[6])]
                )
                light_frames.append(frame)
                line_idx += 1
        
        return light_frames, line_idx
    
    def _parse_text_shadow_frames(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析阴影帧数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "shadowframe_ct:":
            raise ValueError("缺少阴影帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"阴影帧数量: {frame_count}")
        
        shadow_frames = []
        if frame_count > 0:
            # 跳过键名行
            line_idx += 1
            
            for i in range(frame_count):
                if line_idx >= len(lines):
                    raise ValueError(f"阴影帧数据不完整")
                
                row = lines[line_idx]
                if len(row) != 3:
                    raise ValueError(f"阴影帧格式错误，期望3个字段，得到{len(row)}个")
                
                frame = VmdShadowFrame(
                    frame_number=int(row[0]),
                    shadow_mode=int(row[1]),
                    distance=float(row[2])
                )
                shadow_frames.append(frame)
                line_idx += 1
        
        return shadow_frames, line_idx
    
    def _parse_text_ik_frames(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析IK帧数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "ik/dispframe_ct:":
            raise ValueError("缺少IK帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"IK帧数量: {frame_count}")
        
        ik_frames = []
        if frame_count > 0:
            # 跳过键名行
            line_idx += 1
            
            for i in range(frame_count):
                if line_idx >= len(lines):
                    raise ValueError(f"IK帧数据不完整")
                
                row = lines[line_idx]
                if len(row) < 2 or len(row) % 2 != 0:
                    raise ValueError(f"IK帧格式错误，需要偶数个字段且至少2个字段")
                
                ik_bones = []
                for j in range(2, len(row), 2):
                    ik_bone = VmdIkBone(
                        bone_name=row[j],
                        ik_enabled=bool(int(row[j + 1]))
                    )
                    ik_bones.append(ik_bone)
                
                frame = VmdIkFrame(
                    frame_number=int(row[0]),
                    display=bool(int(row[1])),
                    ik_bones=ik_bones
                )
                ik_frames.append(frame)
                line_idx += 1
        
        return ik_frames, line_idx
    
    def _format_text_header(self, header: VmdHeader) -> List[str]:
        """格式化头部为文本"""
        return [
            f"version:\t{header.version}",
            f"modelname:\t{header.model_name}"
        ]
    
    def _format_text_bone_frames(self, bone_frames: List[VmdBoneFrame]) -> List[str]:
        """格式化骨骼帧为文本"""
        lines = [f"boneframe_ct:\t{len(bone_frames)}"]
        
        if bone_frames:
            # 键名行
            keys = ["bone_name", "frame_num", "Xpos", "Ypos", "Zpos", "Xrot", "Yrot", "Zrot", "phys_disable",
                   "interp_x_ax", "interp_x_ay", "interp_x_bx", "interp_x_by", 
                   "interp_y_ax", "interp_y_ay", "interp_y_bx", "interp_y_by", 
                   "interp_z_ax", "interp_z_ay", "interp_z_bx", "interp_z_by", 
                   "interp_r_ax", "interp_r_ay", "interp_r_bx", "interp_r_by"]
            lines.append('\t'.join(keys))
            
            for frame in bone_frames:
                # VMD骨骼帧应该统一使用3元素欧拉角格式（度数）
                if len(frame.rotation) != 3:
                    raise ValueError(f"Invalid rotation format: expected 3 Euler angles, got {len(frame.rotation)} elements")
                
                # 直接使用存储的欧拉角（已经是度数格式）
                euler_angles = frame.rotation
                
                row = [
                    frame.bone_name,
                    str(frame.frame_number),
                    f"{frame.position[0]:.6f}",
                    f"{frame.position[1]:.6f}",
                    f"{frame.position[2]:.6f}",
                    f"{euler_angles[0]:.6f}",
                    f"{euler_angles[1]:.6f}",
                    f"{euler_angles[2]:.6f}",
                    str(int(frame.physics_disabled))
                ]
                
                # 添加插值参数
                for interp_val in frame.interpolation:
                    row.append(str(interp_val))
                
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_morph_frames(self, morph_frames: List[VmdMorphFrame]) -> List[str]:
        """格式化变形帧为文本"""
        lines = [f"morphframe_ct:\t{len(morph_frames)}"]
        
        if morph_frames:
            lines.append('\t'.join(["morph_name", "frame_num", "value"]))
            
            for frame in morph_frames:
                row = [frame.morph_name, str(frame.frame_number), f"{frame.weight:.6f}"]
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_camera_frames(self, camera_frames: List[VmdCameraFrame]) -> List[str]:
        """格式化相机帧为文本"""
        lines = [f"camframe_ct:\t{len(camera_frames)}"]
        
        if camera_frames:
            keys = ["frame_num", "target_dist", "Xpos", "Ypos", "Zpos", "Xrot", "Yrot", "Zrot", "FOV", "perspective"] + \
                   ["interp_x_ax", "interp_x_ay", "interp_x_bx", "interp_x_by",
                    "interp_y_ax", "interp_y_ay", "interp_y_bx", "interp_y_by",
                    "interp_z_ax", "interp_z_ay", "interp_z_bx", "interp_z_by",
                    "interp_r_ax", "interp_r_ay", "interp_r_bx", "interp_r_by",
                    "interp_dist_ax", "interp_dist_ay", "interp_dist_bx", "interp_dist_by",
                    "interp_fov_ax", "interp_fov_ay", "interp_fov_bx", "interp_fov_by"]
            lines.append('\t'.join(keys))
            
            for frame in camera_frames:
                row = [
                    str(frame.frame_number),
                    f"{frame.distance:.6f}",
                    f"{frame.position[0]:.6f}",
                    f"{frame.position[1]:.6f}",
                    f"{frame.position[2]:.6f}",
                    f"{frame.rotation[0]:.6f}",
                    f"{frame.rotation[1]:.6f}",
                    f"{frame.rotation[2]:.6f}",
                    f"{frame.fov:.6f}",
                    str(int(frame.perspective))
                ]
                
                # 添加插值参数
                for interp_val in frame.interpolation:
                    row.append(str(interp_val))
                
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_light_frames(self, light_frames: List[VmdLightFrame]) -> List[str]:
        """格式化光源帧为文本"""
        lines = [f"lightframe_ct:\t{len(light_frames)}"]
        
        if light_frames:
            lines.append('\t'.join(["frame_num", "red", "green", "blue", "x_dir", "y_dir", "z_dir"]))
            
            for frame in light_frames:
                row = [
                    str(frame.frame_number),
                    f"{frame.color[0]:.6f}",
                    f"{frame.color[1]:.6f}",
                    f"{frame.color[2]:.6f}",
                    f"{frame.position[0]:.6f}",
                    f"{frame.position[1]:.6f}",
                    f"{frame.position[2]:.6f}"
                ]
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_shadow_frames(self, shadow_frames: List[VmdShadowFrame]) -> List[str]:
        """格式化阴影帧为文本"""
        lines = [f"shadowframe_ct:\t{len(shadow_frames)}"]
        
        if shadow_frames:
            lines.append('\t'.join(["frame_num", "mode", "shadowrange"]))
            
            for frame in shadow_frames:
                row = [str(frame.frame_number), str(frame.shadow_mode), f"{frame.distance:.6f}"]
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_ik_frames(self, ik_frames: List[VmdIkFrame]) -> List[str]:
        """格式化IK帧为文本"""
        lines = [f"ik/dispframe_ct:\t{len(ik_frames)}"]
        
        if ik_frames:
            lines.append('\t'.join(["frame_num", "display_model", "{ik_name", "ik_enable}"]))
            
            for frame in ik_frames:
                row = [str(frame.frame_number), str(int(frame.display))]
                
                for ik_bone in frame.ik_bones:
                    row.append(ik_bone.bone_name)
                    row.append(str(int(ik_bone.ik_enabled)))
                
                lines.append('\t'.join(row))
        
        return lines