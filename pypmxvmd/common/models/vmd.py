"""
PyPMXVMD VMD数据模型

定义VMD(Vocaloid Motion Data)格式的所有数据结构。
包含动作头信息、骨骼关键帧、变形关键帧、相机关键帧等。
"""

import enum
from typing import List, Optional, Any
from pypmxvmd.common.models.base import BaseModel, is_valid_vector


class ShadowMode(enum.IntEnum):
    """阴影模式枚举"""
    OFF = 0    # 关闭
    MODE1 = 1  # 模式1
    MODE2 = 2  # 模式2


class VmdHeader(BaseModel):
    """VMD文件头信息"""
    
    def __init__(self, 
                 version: int = 2,
                 model_name: str = ""):
        """初始化VMD头信息
        
        Args:
            version: VMD版本 (1=旧版本, 2=新版本)
            model_name: 模型名称 (日文)
        """
        super().__init__()
        self.version = version
        self.model_name = model_name
    
    def to_list(self) -> List[Any]:
        return [self.version, self.model_name]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.version, int)
        assert self.version in (1, 2)
        assert isinstance(self.model_name, str)


class VmdBoneFrame(BaseModel):
    """VMD骨骼关键帧"""
    
    def __init__(self,
                 bone_name: str = "",
                 frame_number: int = 0,
                 position: List[float] = None,
                 rotation: List[float] = None,
                 interpolation: List[int] = None,
                 physics_disabled: bool = False):
        """初始化VMD骨骼关键帧
        
        Args:
            bone_name: 骨骼名称 (日文)
            frame_number: 帧号
            position: 位置 [x, y, z]
            rotation: 旋转欧拉角 [x, y, z] (度数)
            interpolation: 插值曲线数据 (64字节)
            physics_disabled: 是否禁用物理
        """
        super().__init__()
        self.bone_name = bone_name
        self.frame_number = frame_number
        self.position = position or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0]
        self.interpolation = interpolation or ([20, 20, 107, 107] * 4)
        self.physics_disabled = physics_disabled
    
    def to_list(self) -> List[Any]:
        return [self.bone_name, self.frame_number, self.position,
                self.rotation, self.interpolation, self.physics_disabled]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.bone_name, str)
        assert len(self.bone_name.encode('shift_jis', errors='ignore')) <= 15
        assert isinstance(self.frame_number, int)
        assert self.frame_number >= 0
        assert is_valid_vector(3, self.position)
        # 旋转数据使用3个欧拉角（度数格式）
        assert isinstance(self.rotation, list)
        assert len(self.rotation) == 3
        assert all(isinstance(x, (int, float)) for x in self.rotation)
        assert isinstance(self.interpolation, list)
        assert len(self.interpolation) == 16  # 插值数据简化为16个值
        assert isinstance(self.physics_disabled, bool)


class VmdMorphFrame(BaseModel):
    """VMD变形关键帧"""
    
    def __init__(self,
                 morph_name: str = "",
                 frame_number: int = 0,
                 weight: float = 0.0):
        """初始化VMD变形关键帧
        
        Args:
            morph_name: 变形名称 (日文)
            frame_number: 帧号
            weight: 权重值 (0.0-1.0)
        """
        super().__init__()
        self.morph_name = morph_name
        self.frame_number = frame_number
        self.weight = weight
    
    def to_list(self) -> List[Any]:
        return [self.morph_name, self.frame_number, self.weight]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.morph_name, str)
        assert len(self.morph_name.encode('shift_jis', errors='ignore')) <= 15
        assert isinstance(self.frame_number, int)
        assert self.frame_number >= 0
        assert isinstance(self.weight, (int, float))
        assert 0.0 <= self.weight <= 1.0


class VmdCameraFrame(BaseModel):
    """VMD相机关键帧"""
    
    def __init__(self,
                 frame_number: int = 0,
                 distance: float = 45.0,
                 position: List[float] = None,
                 rotation: List[float] = None,
                 interpolation: List[int] = None,
                 fov: int = 30,
                 perspective: bool = True):
        """初始化VMD相机关键帧
        
        Args:
            frame_number: 帧号
            distance: 到目标的距离
            position: 目标位置 [x, y, z]
            rotation: 相机旋转 [x, y, z] (弧度)
            interpolation: 插值曲线数据 (24字节)
            fov: 视野角度
            perspective: 是否透视投影
        """
        super().__init__()
        self.frame_number = frame_number
        self.distance = distance
        self.position = position or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0]
        self.interpolation = interpolation or ([20, 107, 20, 107] * 6)
        self.fov = fov
        self.perspective = perspective
    
    def to_list(self) -> List[Any]:
        return [self.frame_number, self.distance, self.position,
                self.rotation, self.interpolation, self.fov, self.perspective]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.frame_number, int)
        assert self.frame_number >= 0
        assert isinstance(self.distance, (int, float))
        assert is_valid_vector(3, self.position)
        assert is_valid_vector(3, self.rotation)
        assert isinstance(self.interpolation, list)
        assert len(self.interpolation) == 24
        assert isinstance(self.fov, int)
        assert 1 <= self.fov <= 180
        assert isinstance(self.perspective, bool)


class VmdLightFrame(BaseModel):
    """VMD光照关键帧"""
    
    def __init__(self,
                 frame_number: int = 0,
                 color: List[float] = None,
                 position: List[float] = None):
        """初始化VMD光照关键帧
        
        Args:
            frame_number: 帧号
            color: 光照颜色 [r, g, b]
            position: 光照位置 [x, y, z]
        """
        super().__init__()
        self.frame_number = frame_number
        self.color = color or [0.6, 0.6, 0.6]
        self.position = position or [-0.5, -1.0, 0.5]
    
    def to_list(self) -> List[Any]:
        return [self.frame_number, self.color, self.position]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.frame_number, int)
        assert self.frame_number >= 0
        assert is_valid_vector(3, self.color)
        assert all(0.0 <= c <= 1.0 for c in self.color)
        assert is_valid_vector(3, self.position)


class VmdShadowFrame(BaseModel):
    """VMD阴影关键帧"""
    
    def __init__(self,
                 frame_number: int = 0,
                 shadow_mode: ShadowMode = ShadowMode.MODE1,
                 distance: float = 8875.0):
        """初始化VMD阴影关键帧
        
        Args:
            frame_number: 帧号
            shadow_mode: 阴影模式
            distance: 阴影距离
        """
        super().__init__()
        self.frame_number = frame_number
        self.shadow_mode = shadow_mode
        self.distance = distance
    
    def to_list(self) -> List[Any]:
        return [self.frame_number, self.shadow_mode, self.distance]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.frame_number, int)
        assert self.frame_number >= 0
        assert isinstance(self.shadow_mode, ShadowMode)
        assert isinstance(self.distance, (int, float))


class VmdIkBone(BaseModel):
    """VMD IK骨骼信息"""
    
    def __init__(self,
                 bone_name: str = "",
                 ik_enabled: bool = True):
        """初始化VMD IK骨骼信息
        
        Args:
            bone_name: IK骨骼名称 (日文)
            ik_enabled: 是否启用IK
        """
        super().__init__()
        self.bone_name = bone_name
        self.ik_enabled = ik_enabled
    
    def to_list(self) -> List[Any]:
        return [self.bone_name, self.ik_enabled]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.bone_name, str)
        assert len(self.bone_name.encode('shift_jis', errors='ignore')) <= 20
        assert isinstance(self.ik_enabled, bool)


class VmdIkFrame(BaseModel):
    """VMD IK显示关键帧"""
    
    def __init__(self,
                 frame_number: int = 0,
                 display: bool = True,
                 ik_bones: List[VmdIkBone] = None):
        """初始化VMD IK显示关键帧
        
        Args:
            frame_number: 帧号
            display: 是否显示模型
            ik_bones: IK骨骼列表
        """
        super().__init__()
        self.frame_number = frame_number
        self.display = display
        self.ik_bones = ik_bones or []
    
    def to_list(self) -> List[Any]:
        return [self.frame_number, self.display, 
                [ik_bone.to_list() for ik_bone in self.ik_bones]]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.frame_number, int)
        assert self.frame_number >= 0
        assert isinstance(self.display, bool)
        assert isinstance(self.ik_bones, list)
        for ik_bone in self.ik_bones:
            assert isinstance(ik_bone, VmdIkBone)
            ik_bone.validate()


class VmdMotion(BaseModel):
    """VMD动作主类
    
    包含VMD动作的所有数据，提供统一的访问接口。
    """
    
    def __init__(self):
        """初始化空的VMD动作"""
        super().__init__()
        self.header = VmdHeader()
        self.bone_frames: List[VmdBoneFrame] = []
        self.morph_frames: List[VmdMorphFrame] = []
        self.camera_frames: List[VmdCameraFrame] = []
        self.light_frames: List[VmdLightFrame] = []
        self.shadow_frames: List[VmdShadowFrame] = []
        self.ik_frames: List[VmdIkFrame] = []
    
    def to_list(self) -> List[Any]:
        return [self.header.to_list(), len(self.bone_frames), len(self.morph_frames),
                len(self.camera_frames), len(self.light_frames), 
                len(self.shadow_frames), len(self.ik_frames)]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        # 验证头信息
        self.header.validate()
        
        # 验证各个关键帧列表
        for bone_frame in self.bone_frames:
            bone_frame.validate(self.bone_frames)
            
        for morph_frame in self.morph_frames:
            morph_frame.validate(self.morph_frames)
            
        for camera_frame in self.camera_frames:
            camera_frame.validate(self.camera_frames)
            
        for light_frame in self.light_frames:
            light_frame.validate(self.light_frames)
            
        for shadow_frame in self.shadow_frames:
            shadow_frame.validate(self.shadow_frames)
            
        for ik_frame in self.ik_frames:
            ik_frame.validate(self.ik_frames)
    
    def get_bone_frame_count(self) -> int:
        """获取骨骼关键帧数量"""
        return len(self.bone_frames)
    
    def get_morph_frame_count(self) -> int:
        """获取变形关键帧数量"""
        return len(self.morph_frames)
    
    def get_total_frame_count(self) -> int:
        """获取总关键帧数量"""
        return (len(self.bone_frames) + len(self.morph_frames) + 
                len(self.camera_frames) + len(self.light_frames) +
                len(self.shadow_frames) + len(self.ik_frames))
    
    def is_camera_motion(self) -> bool:
        """判断是否为相机动作"""
        return (self.header.model_name == "カメラ・照明" or 
                len(self.camera_frames) > 0 or len(self.light_frames) > 0)