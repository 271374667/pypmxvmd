"""PyMMD VMD解析器 - 完全基于Nuthouse01原实现

完全复刻Nuthouse01的VMD解析和保存逻辑，保持数据顺序和处理流程一致。
"""

import math
import struct
from pathlib import Path
from typing import List, Optional, Union, Callable

from pymmd.common.models.vmd import (
    VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame, VmdCameraFrame,
    VmdLightFrame, VmdShadowFrame, VmdIkFrame, VmdIkBone, ShadowMode
)
from pymmd.common.io.binary_io import BinaryIOHandler


class VmdParserNuthouse:
    """VMD文件解析器 - Nuthouse01风格
    
    完全复刻原Nuthouse01实现的解析和排序逻辑
    """
    
    # 排序控制 - 完全复刻原项目设置
    GUARANTEE_FRAMES_SORTED = True
    APPEND_SIGNATURE = True
    SIGNATURE = "Nuthouse01"
    
    # 格式定义 - 完全匹配原项目
    FMT_NUMBER = "I"
    FMT_BONEFRAME_NO_INTERPCURVE = "I 7f"
    FMT_BONEFRAME_INTERPCURVE = "bb bb 12b xbb 45x"
    FMT_BONEFRAME_INTERPCURVE_ONELINE = "16b"
    FMT_MORPHFRAME = "I f"
    FMT_CAMFRAME = "I 7f 24b I ?"
    FMT_LIGHTFRAME = "I 3f 3f"
    FMT_SHADOWFRAME = "I b f"
    FMT_IKDISPFRAME = "I ? I"
    FMT_IKFRAME = "?"
    
    def __init__(self, progress_callback: Optional[Callable[[float], None]] = None):
        """初始化VMD解析器"""
        self._io_handler = BinaryIOHandler("shift_jis")
        self._progress_callback = progress_callback
        self._current_pos = 0
        self._total_size = 0
    
    def _quaternion_to_euler(self, quat: List[float]) -> List[float]:
        """四元数转欧拉角 - 完全复刻Nuthouse01算法"""
        w, x, y, z = quat
        
        # pitch (y-axis rotation)
        sinr_cosp = 2 * ((w * y) + (x * z))
        cosr_cosp = 1 - (2 * ((x ** 2) + (y ** 2)))
        pitch = -math.atan2(sinr_cosp, cosr_cosp)
        
        # yaw (z-axis rotation)
        siny_cosp = 2 * ((-w * z) - (x * y))
        cosy_cosp = 1 - (2 * ((x ** 2) + (z ** 2)))
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        # roll (x-axis rotation)
        sinp = 2 * ((z * y) - (w * x))
        if sinp >= 1.0:
            roll = -math.pi / 2  # use 90 degrees if out of range
        elif sinp <= -1.0:
            roll = math.pi / 2
        else:
            roll = -math.asin(sinp)
        
        # fixing the x rotation, part 1
        if x ** 2 > 0.5 or w < 0:
            if x < 0:
                roll = -math.pi - roll
            else:
                roll = math.pi * math.copysign(1, w) - roll
        
        # fixing the x rotation, part 2
        if roll > (math.pi / 2):
            roll = math.pi - roll
        elif roll < -(math.pi / 2):
            roll = -math.pi - roll
        
        roll = math.degrees(roll)
        pitch = math.degrees(pitch)
        yaw = math.degrees(yaw)
        
        return [roll, pitch, yaw]
    
    def _euler_to_quaternion(self, euler: List[float]) -> List[float]:
        """欧拉角转四元数 - 完全复刻Nuthouse01算法"""
        # angles are in degrees, must convert to radians
        roll, pitch, yaw = euler
        roll = math.radians(roll)
        pitch = math.radians(pitch)
        yaw = math.radians(yaw)
        
        # roll (X), pitch (Y), yaw (Z)
        sx = math.sin(roll * 0.5)
        sy = math.sin(pitch * 0.5)
        sz = math.sin(yaw * 0.5)
        cx = math.cos(roll * 0.5)
        cy = math.cos(pitch * 0.5)
        cz = math.cos(yaw * 0.5)
        
        w = (cz * cy * cx) + (sz * sy * sx)
        x = (cz * cy * sx) + (sz * sy * cx)
        y = (sz * cy * sx) - (cz * sy * cx)
        z = (cz * sy * sx) - (sz * cy * cx)
        
        return [w, x, y, z]
    
    def parse_file(self, file_path: Union[str, Path], more_info: bool = False) -> VmdMotion:
        """解析VMD文件 - 完全复刻原实现流程"""
        file_path = Path(file_path)
        if more_info:
            print(f"Begin reading VMD file '{file_path.name}'")
        
        # 读取文件数据
        data = self._io_handler.read_file(file_path)
        self._total_size = len(data)
        self._current_pos = 0
        
        if more_info:
            print(f"...total size = {len(data)} bytes")
            print(f"Begin parsing VMD file '{file_path.name}'")
        
        # 重置读取位置
        self._io_handler._position = 0
        
        try:
            # 按原项目顺序解析各个部分
            header = self._parse_vmd_header(data, more_info)
            bone_frames = self._parse_vmd_boneframe(data, more_info)
            morph_frames = self._parse_vmd_morphframe(data, more_info)
            camera_frames = self._parse_vmd_camframe(data, more_info)
            light_frames = self._parse_vmd_lightframe(data, more_info)
            shadow_frames = self._parse_vmd_shadowframe(data, more_info)
            ik_frames = self._parse_vmd_ikdispframe(data, more_info)
            
            # 创建VMD对象
            vmd_motion = VmdMotion()
            vmd_motion.header = header
            vmd_motion.bone_frames = bone_frames
            vmd_motion.morph_frames = morph_frames
            vmd_motion.camera_frames = camera_frames
            vmd_motion.light_frames = light_frames
            vmd_motion.shadow_frames = shadow_frames
            vmd_motion.ik_frames = ik_frames
            
            # 检查剩余字节
            bytes_remain = len(data) - self._io_handler._position
            if bytes_remain != 0:
                leftover = data[self._io_handler._position:]
                if leftover == self.SIGNATURE.encode("shift_jis"):
                    if more_info:
                        print("...note: this VMD file was previously modified with this tool!")
                else:
                    if more_info:
                        print(f"Warning: finished parsing but {bytes_remain} bytes are left over at the tail!")
            
            if more_info:
                print(f"Done parsing VMD file '{file_path.name}'")
            
            # 应用原项目的排序逻辑
            if self.GUARANTEE_FRAMES_SORTED:
                # 骨骼和变形帧：首先按名称排序，然后按帧号排序
                vmd_motion.bone_frames.sort(key=lambda x: x.frame_number)
                vmd_motion.bone_frames.sort(key=lambda x: x.bone_name)
                vmd_motion.morph_frames.sort(key=lambda x: x.frame_number)
                vmd_motion.morph_frames.sort(key=lambda x: x.morph_name)
                # 其他帧类型只按帧号排序
                vmd_motion.camera_frames.sort(key=lambda x: x.frame_number)
                vmd_motion.light_frames.sort(key=lambda x: x.frame_number)
                vmd_motion.shadow_frames.sort(key=lambda x: x.frame_number)
                vmd_motion.ik_frames.sort(key=lambda x: x.frame_number)
            
            return vmd_motion
            
        except Exception as e:
            raise ValueError(f"VMD文件解析失败: {e}") from e
    
    def _parse_vmd_header(self, data: bytearray, more_info: bool) -> VmdHeader:
        """解析VMD文件头 - 完全复刻原实现"""
        # 读取前30字节的头部字符串
        header_str = self._io_handler.read_string(data, 30, null_terminated=False)
        
        # 检查头部字符串，去除空格填充
        if header_str.startswith("Vocaloid Motion Data 0002"):
            version = 2
            name_length = 20
        elif header_str.startswith("Vocaloid Motion Data file"):
            version = 1  
            name_length = 10
        else:
            raise RuntimeError(f"ERR: found unsupported file version identifier string, '{header_str}'")
        
        # 读取模型名称
        model_name = self._io_handler.read_string(data, name_length)
        
        if more_info:
            print(f"...model name   = JP:'{model_name}'")
        
        return VmdHeader(version=version, model_name=model_name)
    
    def _parse_vmd_boneframe(self, data: bytearray, more_info: bool) -> List[VmdBoneFrame]:
        """解析骨骼帧 - 完全复刻原实现"""
        bone_frames = []
        
        # 检查是否有足够数据读取帧数
        if (len(data) - self._io_handler._position) < struct.calcsize(self.FMT_NUMBER):
            if more_info:
                print("Warning: expected boneframe_ct field but file ended unexpectedly! Assuming 0 boneframes and continuing...")
            return bone_frames
        
        # 读取骨骼帧数量
        frame_count = self._io_handler.unpack_data(self.FMT_NUMBER, data)[0]
        if more_info:
            print(f"...# of boneframes          = {frame_count}")
        
        for i in range(frame_count):
            try:
                # 读取骨骼名称
                bone_name = self._io_handler.read_string(data, 15)
                
                # 读取基础数据（位置和四元数旋转）
                frame_data = self._io_handler.unpack_data(self.FMT_BONEFRAME_NO_INTERPCURVE, data)
                frame_num, xp, yp, zp, xrot_q, yrot_q, zrot_q, wrot_q = frame_data
                
                # 读取插值数据
                interp_data = self._io_handler.unpack_data(self.FMT_BONEFRAME_INTERPCURVE, data)
                (x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay,
                 x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by,
                 z_ax, r_ax) = interp_data
                
                # 四元数转欧拉角 - 使用原项目算法
                euler_rot = self._quaternion_to_euler([wrot_q, xrot_q, yrot_q, zrot_q])
                
                # 解析物理开关
                if (phys1, phys2) == (z_ax, r_ax):
                    physics_disabled = False
                elif (phys1, phys2) == (0, 0):
                    physics_disabled = False
                elif (phys1, phys2) == (99, 15):
                    physics_disabled = True
                else:
                    if more_info:
                        print("Warning: found unusual values where I expected to find physics enable/disable! Assuming this means physics off")
                        print(bone_name, "f=", str(frame_num), "(phys1,phys2)=", str((phys1, phys2)))
                    physics_disabled = True
                
                # 构建插值数据 - 按原项目的顺序
                interpolation = [
                    x_ax, x_ay, x_bx, x_by,
                    y_ax, y_ay, y_bx, y_by,
                    z_ax, z_ay, z_bx, z_by,
                    r_ax, r_ay, r_bx, r_by
                ]
                
                bone_frame = VmdBoneFrame(
                    bone_name=bone_name,
                    frame_number=frame_num,
                    position=[xp, yp, zp],
                    rotation=euler_rot,
                    interpolation=interpolation,
                    physics_disabled=physics_disabled
                )
                
                bone_frames.append(bone_frame)
                
            except Exception as e:
                print(f"frame={i}, totalframes={frame_count}, section=boneframe")
                print("Err: something went wrong while parsing, file is probably corrupt/malformed")
                raise
        
        return bone_frames
    
    def _parse_vmd_morphframe(self, data: bytearray, more_info: bool) -> List[VmdMorphFrame]:
        """解析变形帧 - 完全复刻原实现"""
        morph_frames = []
        
        if (len(data) - self._io_handler._position) < struct.calcsize(self.FMT_NUMBER):
            if more_info:
                print("Warning: expected morphframe_ct field but file ended unexpectedly! Assuming 0 morphframes and continuing...")
            return morph_frames
        
        frame_count = self._io_handler.unpack_data(self.FMT_NUMBER, data)[0]
        if more_info:
            print(f"...# of morphframes         = {frame_count}")
        
        for i in range(frame_count):
            try:
                morph_name = self._io_handler.read_string(data, 15)
                frame_num, weight = self._io_handler.unpack_data(self.FMT_MORPHFRAME, data)
                
                morph_frame = VmdMorphFrame(
                    morph_name=morph_name,
                    frame_number=frame_num,
                    weight=weight
                )
                
                morph_frames.append(morph_frame)
                
            except Exception as e:
                print(f"frame={i}, totalframes={frame_count}, section=morphframe")
                print("Err: something went wrong while parsing, file is probably corrupt/malformed")
                raise
        
        return morph_frames
    
    def _parse_vmd_camframe(self, data: bytearray, more_info: bool) -> List[VmdCameraFrame]:
        """解析相机帧 - 完全复刻原实现"""
        camera_frames = []
        
        if (len(data) - self._io_handler._position) < struct.calcsize(self.FMT_NUMBER):
            if more_info:
                print("Warning: expected camframe_ct field but file ended unexpectedly! Assuming 0 camframes and continuing...")
            return camera_frames
        
        frame_count = self._io_handler.unpack_data(self.FMT_NUMBER, data)[0]
        if more_info:
            print(f"...# of camframes           = {frame_count}")
        
        for i in range(frame_count):
            try:
                cam_data = self._io_handler.unpack_data(self.FMT_CAMFRAME, data)
                (frame_num, distance, xp, yp, zp, xr, yr, zr,
                 x_ax, x_bx, x_ay, x_by, y_ax, y_bx, y_ay, y_by,
                 z_ax, z_bx, z_ay, z_by, r_ax, r_bx, r_ay, r_by,
                 dist_ax, dist_bx, dist_ay, dist_by, ang_ax, ang_bx, ang_ay, ang_by,
                 fov, perspective) = cam_data
                
                # 弧度转度数
                rotation = [math.degrees(xr), math.degrees(yr), math.degrees(zr)]
                
                # 构建插值数据 - 按原项目的顺序
                interpolation = [
                    x_ax, x_ay, x_bx, x_by,
                    y_ax, y_ay, y_bx, y_by,
                    z_ax, z_ay, z_bx, z_by,
                    r_ax, r_ay, r_bx, r_by,
                    dist_ax, dist_ay, dist_bx, dist_by,
                    ang_ax, ang_ay, ang_bx, ang_by
                ]
                
                camera_frame = VmdCameraFrame(
                    frame_number=frame_num,
                    distance=distance,
                    position=[xp, yp, zp],
                    rotation=rotation,
                    interpolation=interpolation,
                    fov=fov,
                    perspective=bool(perspective)
                )
                
                camera_frames.append(camera_frame)
                
            except Exception as e:
                print(f"frame={i}, totalframes={frame_count}, section=camframe")
                print("Err: something went wrong while parsing, file is probably corrupt/malformed")
                raise
        
        return camera_frames
    
    def _parse_vmd_lightframe(self, data: bytearray, more_info: bool) -> List[VmdLightFrame]:
        """解析光源帧 - 完全复刻原实现"""
        light_frames = []
        
        if (len(data) - self._io_handler._position) < struct.calcsize(self.FMT_NUMBER):
            if more_info:
                print("Warning: expected lightframe_ct field but file ended unexpectedly! Assuming 0 lightframes and continuing...")
            return light_frames
        
        frame_count = self._io_handler.unpack_data(self.FMT_NUMBER, data)[0]
        if more_info:
            print(f"...# of lightframes         = {frame_count}")
        
        for i in range(frame_count):
            try:
                frame_num, r, g, b, x, y, z = self._io_handler.unpack_data(self.FMT_LIGHTFRAME, data)
                
                light_frame = VmdLightFrame(
                    frame_number=frame_num,
                    color=[r, g, b],
                    position=[x, y, z]
                )
                
                light_frames.append(light_frame)
                
            except Exception as e:
                print(f"frame={i}, totalframes={frame_count}, section=lightframe")
                print("Err: something went wrong while parsing, file is probably corrupt/malformed")
                raise
        
        return light_frames
    
    def _parse_vmd_shadowframe(self, data: bytearray, more_info: bool) -> List[VmdShadowFrame]:
        """解析阴影帧 - 完全复刻原实现"""
        shadow_frames = []
        
        if (len(data) - self._io_handler._position) < struct.calcsize(self.FMT_NUMBER):
            if more_info:
                print("Warning: expected shadowframe_ct field but file ended unexpectedly! Assuming 0 shadowframes and continuing...")
            return shadow_frames
        
        frame_count = self._io_handler.unpack_data(self.FMT_NUMBER, data)[0]
        if more_info:
            print(f"...# of shadowframes        = {frame_count}")
        
        for i in range(frame_count):
            try:
                frame_num, mode, value = self._io_handler.unpack_data(self.FMT_SHADOWFRAME, data)
                
                # 原项目的阴影值转换逻辑
                value = round(10000 - (value * 100000))
                shadow_mode = ShadowMode(mode)
                
                shadow_frame = VmdShadowFrame(
                    frame_number=frame_num,
                    shadow_mode=shadow_mode,
                    distance=value
                )
                
                shadow_frames.append(shadow_frame)
                
            except Exception as e:
                print(f"frame={i}, totalframes={frame_count}, section=shadowframe")
                print("Err: something went wrong while parsing, file is probably corrupt/malformed")
                raise
        
        return shadow_frames
    
    def _parse_vmd_ikdispframe(self, data: bytearray, more_info: bool) -> List[VmdIkFrame]:
        """解析IK显示帧 - 完全复刻原实现"""
        ik_frames = []
        
        if (len(data) - self._io_handler._position) < struct.calcsize(self.FMT_NUMBER):
            if more_info:
                print("Warning: expected ikdispframe_ct field but file ended unexpectedly! Assuming 0 ikdispframes and continuing...")
            return ik_frames
        
        frame_count = self._io_handler.unpack_data(self.FMT_NUMBER, data)[0]
        if more_info:
            print(f"...# of ik/disp frames      = {frame_count}")
        
        for i in range(frame_count):
            try:
                frame_num, display, num_bones = self._io_handler.unpack_data(self.FMT_IKDISPFRAME, data)
                
                ik_bones = []
                for j in range(num_bones):
                    bone_name = self._io_handler.read_string(data, 20)
                    enabled = self._io_handler.unpack_data(self.FMT_IKFRAME, data)[0]
                    
                    ik_bone = VmdIkBone(
                        bone_name=bone_name,
                        ik_enabled=enabled
                    )
                    ik_bones.append(ik_bone)
                
                ik_frame = VmdIkFrame(
                    frame_number=frame_num,
                    display=bool(display),
                    ik_bones=ik_bones
                )
                
                ik_frames.append(ik_frame)
                
            except Exception as e:
                print(f"frame={i}, totalframes={frame_count}, section=ikdispframe")
                print("Err: something went wrong while parsing, file is probably corrupt/malformed")
                raise
        
        return ik_frames
    
    # ===== 文本解析和导出功能 - 完全复刻原项目 =====
    
    def parse_text_file(self, file_path: Union[str, Path], more_info: bool = False) -> VmdMotion:
        """解析VMD文本文件 - 完全复刻原项目逻辑"""
        file_path = Path(file_path)
        if more_info:
            print(f"Begin reading VMD-as-text file '{file_path.name}'")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip().split('\t') if '\t' in line else [line.strip()]
                    for line in f.readlines() if line.strip()]
        
        if more_info:
            print(f"...total size   = {len(lines)} lines")
            print(f"Begin parsing VMD-as-text file '{file_path.name}'")
        
        line_idx = 0
        
        try:
            # 按原项目顺序解析
            header = self._read_vmdtext_header(lines, line_idx)
            line_idx += 2
            
            bone_frames, line_idx = self._read_vmdtext_boneframe(lines, line_idx, more_info)
            morph_frames, line_idx = self._read_vmdtext_morphframe(lines, line_idx, more_info)
            camera_frames, line_idx = self._read_vmdtext_camframe(lines, line_idx, more_info)
            light_frames, line_idx = self._read_vmdtext_lightframe(lines, line_idx, more_info)
            shadow_frames, line_idx = self._read_vmdtext_shadowframe(lines, line_idx, more_info)
            ik_frames, line_idx = self._read_vmdtext_ikdispframe(lines, line_idx, more_info)
            
        except (ValueError, IndexError) as e:
            raise ValueError(f"VMD文本文件解析失败在第{line_idx + 1}行: {e}")
        
        if line_idx != len(lines):
            if more_info:
                print("Warning: there are unsupported trailing lines on the end of the file", line_idx, len(lines))
        
        if more_info:
            print(f"Done parsing VMD-as-text file '{file_path.name}'")
        
        # 创建VMD对象
        vmd_motion = VmdMotion()
        vmd_motion.header = header
        vmd_motion.bone_frames = bone_frames
        vmd_motion.morph_frames = morph_frames
        vmd_motion.camera_frames = camera_frames
        vmd_motion.light_frames = light_frames
        vmd_motion.shadow_frames = shadow_frames
        vmd_motion.ik_frames = ik_frames
        
        return vmd_motion
    
    def write_text_file(self, motion: VmdMotion, file_path: Union[str, Path]) -> None:
        """将VMD运动数据导出为文本文件 - 完全复刻原项目逻辑"""
        file_path = Path(file_path)
        print(f"Begin formatting VMD-as-text file '{file_path.name}'")
        
        rawlist = self._format_nicelist_as_rawlist(motion)
        
        print(f"Begin writing VMD-as-text file '{file_path.name}'")
        print(f"...total size   = {len(rawlist)} lines")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            for line in rawlist:
                if isinstance(line, list):
                    f.write('\t'.join(str(item) for item in line) + '\n')
                else:
                    f.write(str(line) + '\n')
        
        print(f"Done writing VMD-as-text file '{file_path.name}'")
    
    def _read_vmdtext_header(self, lines: List[List[str]], start_idx: int) -> VmdHeader:
        """读取文本文件头部 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "version:":
            raise ValueError("缺少版本信息")
        version = int(lines[start_idx][1])
        
        if start_idx + 1 >= len(lines) or len(lines[start_idx + 1]) != 2 or lines[start_idx + 1][0] != "modelname:":
            raise ValueError("缺少模型名称")
        model_name = lines[start_idx + 1][1]
        
        return VmdHeader(version=version, model_name=model_name)
    
    def _read_vmdtext_boneframe(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """读取骨骼帧数据 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "boneframe_ct:":
            raise ValueError("缺少骨骼帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"...# of boneframes          = {frame_count}")
        
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
                if len(row) < 25:
                    raise ValueError(f"骨骼帧格式错误，期望至少25个字段，得到{len(row)}个")
                
                # 文本格式直接使用欧拉角（度数）
                frame = VmdBoneFrame(
                    bone_name=row[0],
                    frame_number=int(row[1]),
                    position=[float(row[2]), float(row[3]), float(row[4])],
                    rotation=[float(row[5]), float(row[6]), float(row[7])],
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
    
    def _read_vmdtext_morphframe(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """读取变形帧数据 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "morphframe_ct:":
            raise ValueError("缺少变形帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"...# of morphframes         = {frame_count}")
        
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
    
    def _read_vmdtext_camframe(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """读取相机帧数据 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "camframe_ct:":
            raise ValueError("缺少相机帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"...# of camframes           = {frame_count}")
        
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
                    fov=int(row[8]),
                    perspective=bool(int(row[9])),
                    interpolation=[int(r) for r in row[10:34]]
                )
                camera_frames.append(frame)
                line_idx += 1
        
        return camera_frames, line_idx
    
    def _read_vmdtext_lightframe(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """读取光源帧数据 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "lightframe_ct:":
            raise ValueError("缺少光源帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"...# of lightframes         = {frame_count}")
        
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
    
    def _read_vmdtext_shadowframe(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """读取阴影帧数据 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "shadowframe_ct:":
            raise ValueError("缺少阴影帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"...# of shadowframes        = {frame_count}")
        
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
                    shadow_mode=ShadowMode(int(row[1])),
                    distance=float(row[2])
                )
                shadow_frames.append(frame)
                line_idx += 1
        
        return shadow_frames, line_idx
    
    def _read_vmdtext_ikdispframe(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """读取IK帧数据 - 复刻原项目"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "ik/dispframe_ct:":
            raise ValueError("缺少IK帧计数")
        
        frame_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"...# of ik/disp frames      = {frame_count}")
        
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
    
    def _format_nicelist_as_rawlist(self, vmd: VmdMotion) -> List[List]:
        """格式化为原项目文本格式 - 完全复刻原项目"""
        rawlist = []
        
        # 头部
        rawlist.append(["version:", vmd.header.version])
        rawlist.append(["modelname:", vmd.header.model_name])
        
        # 骨骼帧
        bone_frame_ct = len(vmd.bone_frames)
        rawlist.append(["boneframe_ct:", bone_frame_ct])
        if bone_frame_ct != 0:
            # 键名行 - 完全匹配原项目
            keys = ["bone_name", "frame_num", "Xpos", "Ypos", "Zpos", "Xrot", "Yrot", "Zrot", "phys_disable",
                   "interp_x_ax", "interp_x_ay", "interp_x_bx", "interp_x_by", 
                   "interp_y_ax", "interp_y_ay", "interp_y_bx", "interp_y_by", 
                   "interp_z_ax", "interp_z_ay", "interp_z_bx", "interp_z_by", 
                   "interp_r_ax", "interp_r_ay", "interp_r_bx", "interp_r_by"]
            rawlist.append(keys)
            
            for frame in vmd.bone_frames:
                row = [frame.bone_name, frame.frame_number] + \
                      frame.position + frame.rotation + \
                      [int(frame.physics_disabled)] + frame.interpolation
                rawlist.append(row)
        
        # 变形帧
        morph_frame_ct = len(vmd.morph_frames)
        rawlist.append(["morphframe_ct:", morph_frame_ct])
        if morph_frame_ct != 0:
            rawlist.append(["morph_name", "frame_num", "value"])
            for frame in vmd.morph_frames:
                row = [frame.morph_name, frame.frame_number, frame.weight]
                rawlist.append(row)
        
        # 相机帧
        cam_frame_ct = len(vmd.camera_frames)
        rawlist.append(["camframe_ct:", cam_frame_ct])
        if cam_frame_ct != 0:
            keys = ["frame_num", "target_dist", "Xpos", "Ypos", "Zpos", "Xrot", "Yrot", "Zrot", "FOV", "perspective"] + \
                   ["interp_x_ax", "interp_x_ay", "interp_x_bx", "interp_x_by",
                    "interp_y_ax", "interp_y_ay", "interp_y_bx", "interp_y_by",
                    "interp_z_ax", "interp_z_ay", "interp_z_bx", "interp_z_by",
                    "interp_r_ax", "interp_r_ay", "interp_r_bx", "interp_r_by",
                    "interp_dist_ax", "interp_dist_ay", "interp_dist_bx", "interp_dist_by",
                    "interp_fov_ax", "interp_fov_ay", "interp_fov_bx", "interp_fov_by"]
            rawlist.append(keys)
            
            for frame in vmd.camera_frames:
                row = [frame.frame_number, frame.distance] + frame.position + frame.rotation + \
                      [frame.fov, int(frame.perspective)] + frame.interpolation
                rawlist.append(row)
        
        # 光源帧
        light_frame_ct = len(vmd.light_frames)
        rawlist.append(["lightframe_ct:", light_frame_ct])
        if light_frame_ct != 0:
            rawlist.append(["frame_num", "red", "green", "blue", "x_dir", "y_dir", "z_dir"])
            for frame in vmd.light_frames:
                row = [frame.frame_number] + frame.color + frame.position
                rawlist.append(row)
        
        # 阴影帧
        shadow_frame_ct = len(vmd.shadow_frames)
        rawlist.append(["shadowframe_ct:", shadow_frame_ct])
        if shadow_frame_ct != 0:
            rawlist.append(["frame_num", "mode", "shadowrange"])
            for frame in vmd.shadow_frames:
                row = [frame.frame_number, frame.shadow_mode.value, frame.distance]
                rawlist.append(row)
        
        # IK显示帧
        ik_frame_ct = len(vmd.ik_frames)
        rawlist.append(["ik/dispframe_ct:", ik_frame_ct])
        if ik_frame_ct != 0:
            rawlist.append(["frame_num", "display_model", "{ik_name", "ik_enable}"])
            for frame in vmd.ik_frames:
                row = [frame.frame_number, int(frame.display)]
                for ik_bone in frame.ik_bones:
                    row.extend([ik_bone.bone_name, int(ik_bone.ik_enabled)])
                rawlist.append(row)
        
        return rawlist
    
    # ===== VMD二进制保存功能 - 完全复刻原项目 =====
    
    def write_file(self, vmd_motion: VmdMotion, file_path: Union[str, Path]) -> None:
        """写入VMD文件 - 完全复刻原项目逻辑"""
        file_path = Path(file_path)
        print(f"Begin encoding VMD file '{file_path.name}'")
        
        # 验证数据
        vmd_motion.validate()
        
        # 应用原项目的排序逻辑
        if self.GUARANTEE_FRAMES_SORTED:
            # 复制以避免修改原始数据
            vmd_copy = VmdMotion()
            vmd_copy.header = vmd_motion.header
            vmd_copy.bone_frames = vmd_motion.bone_frames.copy()
            vmd_copy.morph_frames = vmd_motion.morph_frames.copy()
            vmd_copy.camera_frames = vmd_motion.camera_frames.copy()
            vmd_copy.light_frames = vmd_motion.light_frames.copy()
            vmd_copy.shadow_frames = vmd_motion.shadow_frames.copy()
            vmd_copy.ik_frames = vmd_motion.ik_frames.copy()
            
            # 骨骼和变形帧：首先按名称排序，然后按帧号排序
            vmd_copy.bone_frames.sort(key=lambda x: x.frame_number)
            vmd_copy.bone_frames.sort(key=lambda x: x.bone_name)
            vmd_copy.morph_frames.sort(key=lambda x: x.frame_number)
            vmd_copy.morph_frames.sort(key=lambda x: x.morph_name)
            # 其他帧类型只按帧号排序
            vmd_copy.camera_frames.sort(key=lambda x: x.frame_number)
            vmd_copy.light_frames.sort(key=lambda x: x.frame_number)
            vmd_copy.shadow_frames.sort(key=lambda x: x.frame_number)
            vmd_copy.ik_frames.sort(key=lambda x: x.frame_number)
            
            vmd_motion = vmd_copy
        
        # 构建二进制数据
        output_bytes = bytearray()
        
        # 按原项目顺序编码各部分
        output_bytes += self._encode_vmd_header(vmd_motion.header)
        output_bytes += self._encode_vmd_boneframe(vmd_motion.bone_frames)
        output_bytes += self._encode_vmd_morphframe(vmd_motion.morph_frames)
        output_bytes += self._encode_vmd_camframe(vmd_motion.camera_frames)
        output_bytes += self._encode_vmd_lightframe(vmd_motion.light_frames)
        output_bytes += self._encode_vmd_shadowframe(vmd_motion.shadow_frames)
        output_bytes += self._encode_vmd_ikdispframe(vmd_motion.ik_frames)
        
        # 添加原项目的签名
        if self.APPEND_SIGNATURE:
            output_bytes += self.SIGNATURE.encode("shift_jis")
        
        print(f"Begin writing VMD file '{file_path.name}'")
        print(f"...total size   = {len(output_bytes)} bytes")
        
        # 写入文件
        self._io_handler.write_file(file_path, bytes(output_bytes))
        
        print(f"Done writing VMD file '{file_path.name}'")
    
    def _encode_vmd_header(self, header: VmdHeader) -> bytearray:
        """编码VMD头部 - 复刻原项目"""
        output = bytearray()
        
        if header.version == 2:
            header_str = "Vocaloid Motion Data 0002"
            name_length = 20
        else:
            header_str = "Vocaloid Motion Data file"  
            name_length = 10
        
        # 写入30字节头部字符串
        output += self._io_handler.write_string(header_str, 30, False)
        # 写入模型名称
        output += self._io_handler.write_string(header.model_name, name_length)
        
        return output
    
    def _encode_vmd_boneframe(self, bone_frames: List[VmdBoneFrame]) -> bytearray:
        """编码骨骼帧 - 复刻原项目"""
        output = bytearray()
        
        # 写入帧数
        output += self._io_handler.pack_data(self.FMT_NUMBER, len(bone_frames))
        
        for frame in bone_frames:
            # 骨骼名称
            output += self._io_handler.write_string(frame.bone_name, 15)
            
            # 欧拉角转四元数 - 使用原项目算法
            quat = self._euler_to_quaternion(frame.rotation)
            w, x, y, z = quat
            # 重新排序为XYZW格式存储
            quat_xyzw = [x, y, z, w]
            
            # 基础数据：帧号 + 位置 + 四元数
            frame_data = [frame.frame_number] + frame.position + quat_xyzw
            output += self._io_handler.pack_data(self.FMT_BONEFRAME_NO_INTERPCURVE, *frame_data)
            
            # 插值数据处理 - 复刻原项目的复杂逻辑
            interp = frame.interpolation if frame.interpolation else [20, 20, 107, 107] * 4
            
            # 解构插值数据
            x_ax, x_ay, x_bx, x_by = interp[0:4]
            y_ax, y_ay, y_bx, y_by = interp[4:8]
            z_ax, z_ay, z_bx, z_by = interp[8:12]
            r_ax, r_ay, r_bx, r_by = interp[12:16]
            
            # 重新排列插值数据为一行格式
            interp_list = [x_ax, y_ax, z_ax, r_ax, x_ay, y_ay, z_ay, r_ay, 
                          x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by]
            
            # 打包一行插值数据
            interp_packed = self._io_handler.pack_data(self.FMT_BONEFRAME_INTERPCURVE_ONELINE, *interp_list)
            
            # 复刻原项目的"复制和偏移"逻辑来重建4行结构
            final_interp = bytearray(interp_packed)
            final_interp += interp_packed[1:] + bytes(1)  # 第2行
            final_interp += interp_packed[2:] + bytes(2)  # 第3行  
            final_interp += interp_packed[3:] + bytes(3)  # 第4行
            
            # 用物理开关数据覆盖奇怪的字节
            if frame.physics_disabled:
                final_interp[2] = 99
                final_interp[3] = 15
            else:
                final_interp[2] = 0
                final_interp[3] = 0
            
            output += final_interp
        
        return output
    
    def _encode_vmd_morphframe(self, morph_frames: List[VmdMorphFrame]) -> bytearray:
        """编码变形帧 - 复刻原项目"""
        output = bytearray()
        
        output += self._io_handler.pack_data(self.FMT_NUMBER, len(morph_frames))
        
        for frame in morph_frames:
            output += self._io_handler.write_string(frame.morph_name, 15)
            output += self._io_handler.pack_data(self.FMT_MORPHFRAME, frame.frame_number, frame.weight)
        
        return output
    
    def _encode_vmd_camframe(self, camera_frames: List[VmdCameraFrame]) -> bytearray:
        """编码相机帧 - 复刻原项目"""
        output = bytearray()
        
        output += self._io_handler.pack_data(self.FMT_NUMBER, len(camera_frames))
        
        for frame in camera_frames:
            # 度转弧度
            xyz_rads = [math.radians(r) for r in frame.rotation]
            
            # 解构插值数据为具体字段
            interp = frame.interpolation if frame.interpolation else [20, 107, 20, 107] * 6
            x_ax, x_ay, x_bx, x_by = interp[0:4]
            y_ax, y_ay, y_bx, y_by = interp[4:8]
            z_ax, z_ay, z_bx, z_by = interp[8:12]
            r_ax, r_ay, r_bx, r_by = interp[12:16]
            dist_ax, dist_ay, dist_bx, dist_by = interp[16:20]
            fov_ax, fov_ay, fov_bx, fov_by = interp[20:24]
            
            # 按原项目的特定顺序重新排列
            interp_ordered = [x_ax, x_bx, x_ay, x_by,
                             y_ax, y_bx, y_ay, y_by,
                             z_ax, z_bx, z_ay, z_by,
                             r_ax, r_bx, r_ay, r_by,
                             dist_ax, dist_bx, dist_ay, dist_by,
                             fov_ax, fov_bx, fov_ay, fov_by]
            
            # 构建完整的数据包
            cam_data = ([frame.frame_number, frame.distance] + 
                       frame.position + xyz_rads + 
                       interp_ordered + [frame.fov, int(frame.perspective)])
            
            output += self._io_handler.pack_data(self.FMT_CAMFRAME, *cam_data)
        
        return output
    
    def _encode_vmd_lightframe(self, light_frames: List[VmdLightFrame]) -> bytearray:
        """编码光源帧 - 复刻原项目"""
        output = bytearray()
        
        output += self._io_handler.pack_data(self.FMT_NUMBER, len(light_frames))
        
        for frame in light_frames:
            light_data = [frame.frame_number] + frame.color + frame.position
            output += self._io_handler.pack_data(self.FMT_LIGHTFRAME, *light_data)
        
        return output
    
    def _encode_vmd_shadowframe(self, shadow_frames: List[VmdShadowFrame]) -> bytearray:
        """编码阴影帧 - 复刻原项目"""
        output = bytearray()
        
        output += self._io_handler.pack_data(self.FMT_NUMBER, len(shadow_frames))
        
        for frame in shadow_frames:
            # 原项目的阴影值转换逻辑（反向）
            value = (10000 - frame.distance) / 100000
            shadow_data = [frame.frame_number, frame.shadow_mode.value, value]
            output += self._io_handler.pack_data(self.FMT_SHADOWFRAME, *shadow_data)
        
        return output
    
    def _encode_vmd_ikdispframe(self, ik_frames: List[VmdIkFrame]) -> bytearray:
        """编码IK显示帧 - 复刻原项目"""
        output = bytearray()
        
        output += self._io_handler.pack_data(self.FMT_NUMBER, len(ik_frames))
        
        for frame in ik_frames:
            # 主IK帧数据
            ik_data = [frame.frame_number, int(frame.display), len(frame.ik_bones)]
            output += self._io_handler.pack_data(self.FMT_IKDISPFRAME, *ik_data)
            
            # 每个IK骨骼数据
            for ik_bone in frame.ik_bones:
                output += self._io_handler.write_string(ik_bone.bone_name, 20)
                output += self._io_handler.pack_data(self.FMT_IKFRAME, int(ik_bone.ik_enabled))
        
        return output