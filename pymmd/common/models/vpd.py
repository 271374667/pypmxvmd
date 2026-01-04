"""
PyMMD VPD数据模型

定义VPD(Vocaloid Pose Data)格式的数据结构。
VPD是纯文本格式，用于存储单帧姿势数据。
"""

from typing import List, Optional, Any
from pymmd.common.models.base import BaseModel, is_valid_vector


class VpdBonePose(BaseModel):
    """VPD骨骼姿势数据"""
    
    def __init__(self,
                 bone_name: str = "",
                 position: List[float] = None,
                 rotation: List[float] = None):
        """初始化VPD骨骼姿势
        
        Args:
            bone_name: 骨骼名称 (日文)
            position: 位置 [x, y, z]
            rotation: 旋转四元数 [x, y, z, w]
        """
        super().__init__()
        self.bone_name = bone_name
        self.position = position or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0, 1.0]
    
    def to_list(self) -> List[Any]:
        return [self.bone_name, self.position, self.rotation]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.bone_name, str)
        assert is_valid_vector(3, self.position)
        assert is_valid_vector(4, self.rotation)


class VpdMorphPose(BaseModel):
    """VPD变形姿势数据"""
    
    def __init__(self,
                 morph_name: str = "",
                 weight: float = 0.0):
        """初始化VPD变形姿势
        
        Args:
            morph_name: 变形名称 (日文)
            weight: 权重值 (0.0-1.0)
        """
        super().__init__()
        self.morph_name = morph_name
        self.weight = weight
    
    def to_list(self) -> List[Any]:
        return [self.morph_name, self.weight]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.morph_name, str)
        assert isinstance(self.weight, (int, float))
        assert 0.0 <= self.weight <= 1.0


class VpdPose(BaseModel):
    """VPD姿势主类
    
    包含VPD姿势的所有数据，提供统一的访问接口。
    """
    
    def __init__(self,
                 model_name: str = "",
                 bone_poses: List[VpdBonePose] = None,
                 morph_poses: List[VpdMorphPose] = None):
        """初始化VPD姿势
        
        Args:
            model_name: 模型名称
            bone_poses: 骨骼姿势列表
            morph_poses: 变形姿势列表
        """
        super().__init__()
        self.model_name = model_name
        self.bone_poses = bone_poses or []
        self.morph_poses = morph_poses or []
    
    def to_list(self) -> List[Any]:
        return [self.model_name, len(self.bone_poses), len(self.morph_poses)]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.model_name, str)
        assert isinstance(self.bone_poses, list)
        assert isinstance(self.morph_poses, list)
        
        # 验证骨骼姿势
        for bone_pose in self.bone_poses:
            assert isinstance(bone_pose, VpdBonePose)
            bone_pose.validate(self.bone_poses)
            
        # 验证变形姿势
        for morph_pose in self.morph_poses:
            assert isinstance(morph_pose, VpdMorphPose)
            morph_pose.validate(self.morph_poses)
    
    def get_bone_count(self) -> int:
        """获取骨骼姿势数量"""
        return len(self.bone_poses)
    
    def get_morph_count(self) -> int:
        """获取变形姿势数量"""
        return len(self.morph_poses)