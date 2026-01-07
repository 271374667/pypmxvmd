"""
PyPMXVMD PMX数据模型

定义PMX(Polygon Model eXtended)格式的所有数据结构。
包含模型头信息、顶点、面、材质、骨骼、变形、刚体、关节等。
"""

import enum
from typing import List, Optional, Set, Union, Any
from pypmxvmd.common.models.base import BaseModel, is_valid_vector, is_valid_flag


class WeightMode(enum.IntEnum):
    """顶点权重模式枚举"""
    BDEF1 = 0  # 单骨骼变形
    BDEF2 = 1  # 双骨骼变形  
    BDEF4 = 2  # 四骨骼变形
    SDEF = 3   # 球面变形
    QDEF = 4   # 四元数变形


class SphMode(enum.IntEnum):
    """球面纹理模式枚举"""
    DISABLED = 0  # 禁用
    MULTIPLY = 1  # 乘算
    ADDITIVE = 2  # 加算
    SUBTEX = 3    # 子纹理


class MorphType(enum.IntEnum):
    """变形类型枚举"""
    GROUP = 0     # 组变形
    VERTEX = 1    # 顶点变形
    BONE = 2      # 骨骼变形
    UV = 3        # UV变形
    EXTENDED_UV1 = 4  # 扩展UV1变形
    EXTENDED_UV2 = 5  # 扩展UV2变形  
    EXTENDED_UV3 = 6  # 扩展UV3变形
    EXTENDED_UV4 = 7  # 扩展UV4变形
    MATERIAL = 8  # 材质变形
    FLIP = 9      # 翻转变形
    IMPULSE = 10  # 冲击变形


class MorphPanel(enum.IntEnum):
    """变形面板枚举"""
    HIDDEN = 0    # 隐藏
    EYEBROW = 1   # 眉毛 (左下)
    EYE = 2       # 眼睛 (左上)
    MOUTH = 3     # 嘴巴 (右上)  
    OTHER = 4     # 其他 (右下)


class RigidBodyShape(enum.IntEnum):
    """刚体形状枚举"""
    SPHERE = 0    # 球体
    BOX = 1       # 盒子
    CAPSULE = 2   # 胶囊


class RigidBodyPhysMode(enum.IntEnum):
    """刚体物理模式枚举"""
    BONE = 0         # 骨骼跟随
    PHYSICS = 1      # 物理演算
    PHYSICS_BONE = 2 # 物理演算+骨骼追随


class JointType(enum.IntEnum):
    """关节类型枚举"""
    SPRING6DOF = 0  # 6DOF弹簧关节


class MaterialFlags:
    """材质标志位类
    
    管理材质的各种渲染标志，使用属性访问替代列表索引。
    """
    
    def __init__(self, flags: Optional[Union[List[bool], int]] = None):
        """初始化材质标志位
        
        Args:
            flags: 8个布尔值的列表或整数标志位，如果未提供则使用默认值
        """
        if flags is None:
            self._flags = [False] * 8
            self.value = 0
        elif isinstance(flags, int):
            self.value = flags
            self._flags = []
            for i in range(8):
                self._flags.append(bool(flags & (1 << i)))
        elif isinstance(flags, list):
            if len(flags) != 8:
                raise ValueError("材质标志位必须包含8个布尔值")
            self._flags = flags.copy()
            self.value = 0
            for i, flag in enumerate(self._flags):
                if flag:
                    self.value |= (1 << i)
        else:
            raise TypeError("flags必须是列表、整数或None")
    
    @property
    def double_sided(self) -> bool:
        """双面显示"""
        return self._flags[0]
    
    @double_sided.setter
    def double_sided(self, value: bool) -> None:
        self._flags[0] = bool(value)
    
    @property
    def ground_shadow(self) -> bool:
        """地面阴影"""
        return self._flags[1]
    
    @ground_shadow.setter  
    def ground_shadow(self, value: bool) -> None:
        self._flags[1] = bool(value)
    
    @property
    def self_shadow_map(self) -> bool:
        """自阴影贴图"""
        return self._flags[2]
        
    @self_shadow_map.setter
    def self_shadow_map(self, value: bool) -> None:
        self._flags[2] = bool(value)
    
    @property
    def self_shadow(self) -> bool:
        """自阴影"""
        return self._flags[3]
        
    @self_shadow.setter
    def self_shadow(self, value: bool) -> None:
        self._flags[3] = bool(value)
    
    @property
    def edge_drawing(self) -> bool:
        """边缘绘制"""
        return self._flags[4]
        
    @edge_drawing.setter
    def edge_drawing(self, value: bool) -> None:
        self._flags[4] = bool(value)
    
    @property
    def vertex_color(self) -> bool:
        """顶点色"""
        return self._flags[5]
        
    @vertex_color.setter
    def vertex_color(self, value: bool) -> None:
        self._flags[5] = bool(value)
        
    @property
    def point_drawing(self) -> bool:
        """点绘制"""
        return self._flags[6]
        
    @point_drawing.setter
    def point_drawing(self, value: bool) -> None:
        self._flags[6] = bool(value)
        
    @property
    def line_drawing(self) -> bool:
        """线绘制"""
        return self._flags[7]
        
    @line_drawing.setter
    def line_drawing(self, value: bool) -> None:
        self._flags[7] = bool(value)
    
    def to_list(self) -> List[bool]:
        """转换为列表格式"""
        return self._flags.copy()
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, MaterialFlags):
            return False
        return self._flags == other._flags


class PmxHeader(BaseModel):
    """PMX文件头信息"""
    
    def __init__(self, 
                 version: float = 2.1,
                 name_jp: str = "",
                 name_en: str = "", 
                 comment_jp: str = "",
                 comment_en: str = ""):
        """初始化PMX头信息
        
        Args:
            version: PMX版本号
            name_jp: 日文名称
            name_en: 英文名称
            comment_jp: 日文注释
            comment_en: 英文注释
        """
        super().__init__()
        self.version = version
        self.name_jp = name_jp
        self.name_en = name_en
        self.comment_jp = comment_jp
        self.comment_en = comment_en
    
    def to_list(self) -> List[Any]:
        return [self.version, self.name_jp, self.name_en, 
                self.comment_jp, self.comment_en]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.version, (int, float))
        assert isinstance(self.name_jp, str)
        assert isinstance(self.name_en, str)
        assert isinstance(self.comment_jp, str)  
        assert isinstance(self.comment_en, str)


class PmxVertex(BaseModel):
    """PMX顶点数据"""
    
    def __init__(self,
                 position: List[float] = None,
                 normal: List[float] = None, 
                 uv: List[float] = None,
                 additional_uvs: List[List[float]] = None,
                 weight_mode: WeightMode = WeightMode.BDEF1,
                 weight: List[List[Union[int, float]]] = None,
                 edge_scale: float = 1.0):
        """初始化PMX顶点
        
        Args:
            position: 顶点位置 [x, y, z]
            normal: 法线向量 [x, y, z]  
            uv: UV坐标 [u, v]
            additional_uvs: 额外UV坐标列表
            weight_mode: 权重模式
            weight: 权重数据 [[bone_idx, weight_value], ...]
            edge_scale: 边缘缩放
        """
        super().__init__()
        self.position = position or [0.0, 0.0, 0.0]
        self.normal = normal or [0.0, 1.0, 0.0]
        self.uv = uv or [0.0, 0.0]
        self.additional_uvs = additional_uvs or []
        self.weight_mode = weight_mode
        self.weight = weight or []
        self.edge_scale = edge_scale
    
    def to_list(self) -> List[Any]:
        return [self.position, self.normal, self.uv, self.additional_uvs,
                self.weight_mode, self.weight, self.edge_scale]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert is_valid_vector(3, self.position)
        assert is_valid_vector(3, self.normal) 
        assert is_valid_vector(2, self.uv)
        assert isinstance(self.additional_uvs, list)
        assert isinstance(self.weight_mode, WeightMode)
        assert isinstance(self.weight, list)
        assert isinstance(self.edge_scale, (int, float))


class PmxMaterial(BaseModel):
    """PMX材质数据"""
    
    def __init__(self,
                 name_jp: str = "",
                 name_en: str = "",
                 diffuse_color: List[float] = None,
                 specular_color: List[float] = None,
                 specular_strength: float = 1.0,
                 ambient_color: List[float] = None,
                 flags: MaterialFlags = None,
                 edge_color: List[float] = None,
                 edge_size: float = 1.0,
                 texture_path: str = "",
                 sphere_path: str = "",
                 sphere_mode: SphMode = SphMode.DISABLED,
                 toon_path: str = "",
                 comment: str = "",
                 face_count: int = 0):
        """初始化PMX材质
        
        Args:
            name_jp: 日文名称
            name_en: 英文名称
            diffuse_color: 漫反射色 [r, g, b, a]
            specular_color: 镜面反射色 [r, g, b]
            specular_strength: 镜面反射强度
            ambient_color: 环境光色 [r, g, b]
            flags: 材质标志位
            edge_color: 边缘颜色 [r, g, b, a]
            edge_size: 边缘大小
            texture_path: 纹理路径
            sphere_path: 球面纹理路径
            sphere_mode: 球面纹理模式
            toon_path: 卡通渲染纹理路径
            comment: 注释
            face_count: 面数
        """
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.diffuse_color = diffuse_color or [1.0, 1.0, 1.0, 1.0]
        self.specular_color = specular_color or [1.0, 1.0, 1.0]
        self.specular_strength = specular_strength
        self.ambient_color = ambient_color or [0.5, 0.5, 0.5]
        self.flags = flags or MaterialFlags()
        self.edge_color = edge_color or [0.0, 0.0, 0.0, 1.0]
        self.edge_size = edge_size
        self.texture_path = texture_path
        self.sphere_path = sphere_path
        self.sphere_mode = sphere_mode
        self.toon_path = toon_path
        self.comment = comment
        self.face_count = face_count
    
    def to_list(self) -> List[Any]:
        return [self.name_jp, self.name_en, self.diffuse_color,
                self.specular_color, self.specular_strength, self.ambient_color,
                self.flags.to_list(), self.edge_color, self.edge_size,
                self.texture_path, self.sphere_path, self.sphere_mode,
                self.toon_path, self.comment, self.face_count]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        assert isinstance(self.name_jp, str)
        assert isinstance(self.name_en, str)
        assert is_valid_vector(4, self.diffuse_color)
        assert is_valid_vector(3, self.specular_color)
        assert isinstance(self.specular_strength, (int, float))
        assert is_valid_vector(3, self.ambient_color)
        assert isinstance(self.flags, MaterialFlags)
        assert is_valid_vector(4, self.edge_color)
        assert isinstance(self.edge_size, (int, float))
        assert isinstance(self.texture_path, str)
        assert isinstance(self.sphere_path, str)
        assert isinstance(self.sphere_mode, SphMode)
        assert isinstance(self.toon_path, str)
        assert isinstance(self.comment, str)
        assert isinstance(self.face_count, int)


class BoneFlags:
    """骨骼标志位类"""
    
    def __init__(self, 
                 tail_usebonelink: bool = False,
                 rotateable: bool = True,
                 translateable: bool = False,
                 visible: bool = True,
                 enabled: bool = True,
                 ik: bool = False,
                 inherit_rot: bool = False,
                 inherit_trans: bool = False,
                 has_fixedaxis: bool = False,
                 has_localaxis: bool = False,
                 deform_after_phys: bool = False,
                 has_external_parent: bool = False):
        self.tail_usebonelink = tail_usebonelink
        self.rotateable = rotateable
        self.translateable = translateable
        self.visible = visible
        self.enabled = enabled
        self.ik = ik
        self.inherit_rot = inherit_rot
        self.inherit_trans = inherit_trans
        self.has_fixedaxis = has_fixedaxis
        self.has_localaxis = has_localaxis
        self.deform_after_phys = deform_after_phys
        self.has_external_parent = has_external_parent


class PmxBoneIkLink(BaseModel):
    """PMX骨骼IK链接"""
    
    def __init__(self, bone_index: int = 0, limit_min: List[float] = None, limit_max: List[float] = None):
        super().__init__()
        self.bone_index = bone_index
        self.limit_min = limit_min
        self.limit_max = limit_max


class PmxBone(BaseModel):
    """PMX骨骼"""
    
    def __init__(self, 
                 name_jp: str = "",
                 name_en: str = "",
                 position: List[float] = None,
                 parent_index: int = -1,
                 deform_layer: int = 0,
                 bone_flags: BoneFlags = None,
                 tail: Union[int, List[float]] = None,
                 inherit_parent_index: int = None,
                 inherit_ratio: float = None,
                 fixed_axis: List[float] = None,
                 local_axis_x: List[float] = None,
                 local_axis_z: List[float] = None,
                 external_parent_index: int = None,
                 ik_target_index: int = None,
                 ik_loop_count: int = None,
                 ik_angle_limit: float = None,
                 ik_links: List[PmxBoneIkLink] = None):
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.position = position or [0.0, 0.0, 0.0]
        self.parent_index = parent_index
        self.deform_layer = deform_layer
        self.bone_flags = bone_flags or BoneFlags()
        self.tail = tail
        self.inherit_parent_index = inherit_parent_index
        self.inherit_ratio = inherit_ratio
        self.fixed_axis = fixed_axis
        self.local_axis_x = local_axis_x
        self.local_axis_z = local_axis_z
        self.external_parent_index = external_parent_index
        self.ik_target_index = ik_target_index
        self.ik_loop_count = ik_loop_count
        self.ik_angle_limit = ik_angle_limit
        self.ik_links = ik_links or []


class PmxMorphItemGroup(BaseModel):
    """PMX组变形项目"""
    
    def __init__(self, morph_index: int = 0, value: float = 0.0):
        super().__init__()
        self.morph_index = morph_index
        self.value = value


class PmxMorphItemVertex(BaseModel):
    """PMX顶点变形项目"""
    
    def __init__(self, vertex_index: int = 0, offset: List[float] = None):
        super().__init__()
        self.vertex_index = vertex_index
        self.offset = offset or [0.0, 0.0, 0.0]


class PmxMorphItemBone(BaseModel):
    """PMX骨骼变形项目"""
    
    def __init__(self, bone_index: int = 0, translation: List[float] = None, rotation: List[float] = None):
        super().__init__()
        self.bone_index = bone_index
        self.translation = translation or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0]


class PmxMorph(BaseModel):
    """PMX变形"""
    
    def __init__(self, 
                 name_jp: str = "",
                 name_en: str = "",
                 panel: MorphPanel = MorphPanel.OTHER,
                 morph_type: MorphType = MorphType.VERTEX,
                 items: List = None):
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.panel = panel
        self.morph_type = morph_type
        self.items = items or []


class PmxFrameItem(BaseModel):
    """PMX框架项目"""
    
    def __init__(self, is_morph: bool = False, index: int = 0):
        super().__init__()
        self.is_morph = is_morph
        self.index = index


class PmxFrame(BaseModel):
    """PMX显示框架"""
    
    def __init__(self, 
                 name_jp: str = "",
                 name_en: str = "",
                 is_special: bool = False,
                 items: List[PmxFrameItem] = None):
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.is_special = is_special
        self.items = items or []


class PmxRigidBody(BaseModel):
    """PMX刚体"""
    
    def __init__(self, 
                 name_jp: str = "",
                 name_en: str = "",
                 bone_index: int = 0,
                 group: int = 1,
                 nocollide_groups: List[int] = None,
                 shape: RigidBodyShape = RigidBodyShape.SPHERE,
                 size: List[float] = None,
                 position: List[float] = None,
                 rotation: List[float] = None,
                 physics_mode: RigidBodyPhysMode = RigidBodyPhysMode.PHYSICS,
                 mass: float = 1.0,
                 move_damping: float = 0.5,
                 rotation_damping: float = 0.5,
                 repulsion: float = 0.0,
                 friction: float = 0.5):
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.bone_index = bone_index
        self.group = group
        self.nocollide_groups = nocollide_groups or []
        self.shape = shape
        self.size = size or [1.0, 1.0, 1.0]
        self.position = position or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0]
        self.physics_mode = physics_mode
        self.mass = mass
        self.move_damping = move_damping
        self.rotation_damping = rotation_damping
        self.repulsion = repulsion
        self.friction = friction


class PmxJoint(BaseModel):
    """PMX关节"""
    
    def __init__(self, 
                 name_jp: str = "",
                 name_en: str = "",
                 joint_type: JointType = JointType.SPRING6DOF,
                 rigidbody1_index: int = 0,
                 rigidbody2_index: int = 0,
                 position: List[float] = None,
                 rotation: List[float] = None,
                 position_min: List[float] = None,
                 position_max: List[float] = None,
                 rotation_min: List[float] = None,
                 rotation_max: List[float] = None,
                 position_spring: List[float] = None,
                 rotation_spring: List[float] = None):
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.joint_type = joint_type
        self.rigidbody1_index = rigidbody1_index
        self.rigidbody2_index = rigidbody2_index
        self.position = position or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0]
        self.position_min = position_min or [0.0, 0.0, 0.0]
        self.position_max = position_max or [0.0, 0.0, 0.0]
        self.rotation_min = rotation_min or [0.0, 0.0, 0.0]
        self.rotation_max = rotation_max or [0.0, 0.0, 0.0]
        self.position_spring = position_spring or [0.0, 0.0, 0.0]
        self.rotation_spring = rotation_spring or [0.0, 0.0, 0.0]


class PmxSoftBody(BaseModel):
    """PMX软体"""
    
    def __init__(self):
        super().__init__()
        # 简化实现，PMX v2.1功能较少使用
        pass


class PmxModel(BaseModel):
    """PMX模型主类
    
    包含PMX模型的所有数据，提供统一的访问接口。
    """
    
    def __init__(self):
        """初始化空的PMX模型"""
        super().__init__()
        self.header = PmxHeader()
        self.vertices: List[PmxVertex] = []
        self.faces: List[List[int]] = []  # 面索引列表，每个面包含3个顶点索引
        self.textures: List[str] = []  # 纹理路径列表
        self.materials: List[PmxMaterial] = []
        self.bones: List[PmxBone] = []
        self.morphs: List[PmxMorph] = []
        self.frames: List[PmxFrame] = []
        self.rigidbodies: List[PmxRigidBody] = []
        self.joints: List[PmxJoint] = []
        self.softbodies: List[PmxSoftBody] = []
    
    def to_list(self) -> List[Any]:
        return [self.header.to_list(), len(self.vertices), len(self.faces),
                len(self.materials), len(self.bones), len(self.morphs),
                len(self.display_frames), len(self.rigid_bodies), 
                len(self.joints), len(self.soft_bodies)]
    
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        # 验证头信息
        self.header.validate()
        
        # 验证各个组件列表
        for vertex in self.vertices:
            vertex.validate(self.vertices)
            
        for material in self.materials:
            material.validate(self.materials)
            
        # 验证面索引的有效性
        vertex_count = len(self.vertices)
        for i, face in enumerate(self.faces):
            assert isinstance(face, list) and len(face) == 3
            for vertex_idx in face:
                assert isinstance(vertex_idx, int)
                assert 0 <= vertex_idx < vertex_count
    
    def get_vertex_count(self) -> int:
        """获取顶点数量"""
        return len(self.vertices)
    
    def get_face_count(self) -> int:
        """获取面数量"""  
        return len(self.faces)
    
    def get_material_count(self) -> int:
        """获取材质数量"""
        return len(self.materials)