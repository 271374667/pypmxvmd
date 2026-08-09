"""
PyPMXVMD PMX数据模型

定义PMX(Polygon Model eXtended)格式的所有数据结构。
包含模型头信息、顶点、面、材质、骨骼、变形、刚体、关节等。
"""

from typing import TYPE_CHECKING, Any, List, Optional, Union

from pypmxvmd.common.models.base import BaseModel, is_valid_vector
from pypmxvmd.common.pmx.errors import PmxValidationError
from pypmxvmd.common.pmx.types import (
    JointType,
    MorphMaterialOperation,
    MorphPanel,
    MorphType,
    PmxIndexSize,
    PmxTextEncoding,
    RigidBodyPhysMode,
    RigidBodyShape,
    SphMode,
    ToonSharing,
    WeightMode,
)

if TYPE_CHECKING:
    from pypmxvmd.common.pmx.report import PmxParseReport


class PmxRecord(BaseModel):
    """Concrete PMX record base with field-aware validation failures."""

    def to_list(self) -> List[Any]:
        return [value for name, value in self.__dict__.items() if name != "_validated"]

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        return None

    def validate(self, parent_list: Optional[List] = None) -> bool:
        self._validate_data(parent_list)
        self._validated = True
        return True

    @staticmethod
    def _require(condition: bool, field: str, expected: str, actual: object) -> None:
        if not condition:
            raise PmxValidationError(field, expected, actual)


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
            if not 0 <= flags <= 0xFF:
                raise ValueError("材质标志整数必须在0..255范围内")
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
                    self.value |= 1 << i
        else:
            raise TypeError("flags必须是列表、整数或None")

    def _set_flag(self, index: int, enabled: bool) -> None:
        self._flags[index] = bool(enabled)
        if enabled:
            self.value |= 1 << index
        else:
            self.value &= ~(1 << index)

    @property
    def double_sided(self) -> bool:
        """双面显示"""
        return self._flags[0]

    @double_sided.setter
    def double_sided(self, value: bool) -> None:
        self._set_flag(0, value)

    @property
    def ground_shadow(self) -> bool:
        """地面阴影"""
        return self._flags[1]

    @ground_shadow.setter
    def ground_shadow(self, value: bool) -> None:
        self._set_flag(1, value)

    @property
    def self_shadow_map(self) -> bool:
        """自阴影贴图"""
        return self._flags[2]

    @self_shadow_map.setter
    def self_shadow_map(self, value: bool) -> None:
        self._set_flag(2, value)

    @property
    def self_shadow(self) -> bool:
        """自阴影"""
        return self._flags[3]

    @self_shadow.setter
    def self_shadow(self, value: bool) -> None:
        self._set_flag(3, value)

    @property
    def edge_drawing(self) -> bool:
        """边缘绘制"""
        return self._flags[4]

    @edge_drawing.setter
    def edge_drawing(self, value: bool) -> None:
        self._set_flag(4, value)

    @property
    def vertex_color(self) -> bool:
        """顶点色"""
        return self._flags[5]

    @vertex_color.setter
    def vertex_color(self, value: bool) -> None:
        self._set_flag(5, value)

    @property
    def point_drawing(self) -> bool:
        """点绘制"""
        return self._flags[6]

    @point_drawing.setter
    def point_drawing(self, value: bool) -> None:
        self._set_flag(6, value)

    @property
    def line_drawing(self) -> bool:
        """线绘制"""
        return self._flags[7]

    @line_drawing.setter
    def line_drawing(self, value: bool) -> None:
        self._set_flag(7, value)

    def to_list(self) -> List[bool]:
        """转换为列表格式"""
        return self._flags.copy()

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, MaterialFlags):
            return False
        return self._flags == other._flags


class PmxHeader(PmxRecord):
    """PMX header including the complete eight-byte global layout."""

    def __init__(
        self,
        version: float = 2.1,
        name_jp: str = "",
        name_en: str = "",
        comment_jp: str = "",
        comment_en: str = "",
        *,
        encoding: PmxTextEncoding = PmxTextEncoding.UTF16_LE,
        additional_uv_count: int = 0,
        vertex_index_size: int = 1,
        texture_index_size: int = 1,
        material_index_size: int = 1,
        bone_index_size: int = 1,
        morph_index_size: int = 1,
        rigid_body_index_size: int = 1,
        global_flags: bytes = b"",
    ) -> None:
        super().__init__()
        self.version = version
        self.name_jp = name_jp
        self.name_en = name_en
        self.comment_jp = comment_jp
        self.comment_en = comment_en
        self.encoding = PmxTextEncoding(encoding)
        self.additional_uv_count = additional_uv_count
        self.vertex_index_size = vertex_index_size
        self.texture_index_size = texture_index_size
        self.material_index_size = material_index_size
        self.bone_index_size = bone_index_size
        self.morph_index_size = morph_index_size
        self.rigid_body_index_size = rigid_body_index_size
        self.raw_global_flags = global_flags or bytes(
            (
                int(self.encoding),
                additional_uv_count,
                vertex_index_size,
                texture_index_size,
                material_index_size,
                bone_index_size,
                morph_index_size,
                rigid_body_index_size,
            )
        )

    def to_list(self) -> List[Any]:
        return [
            self.version,
            self.name_jp,
            self.name_en,
            self.comment_jp,
            self.comment_en,
            self.encoding,
            self.additional_uv_count,
            self.vertex_index_size,
            self.texture_index_size,
            self.material_index_size,
            self.bone_index_size,
            self.morph_index_size,
            self.rigid_body_index_size,
            self.global_flags,
            self.raw_global_flags,
        ]

    @property
    def text_encoding(self) -> str:
        return "utf-8" if self.encoding == PmxTextEncoding.UTF8 else "utf-16le"

    @property
    def index_sizes(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.vertex_index_size,
            self.texture_index_size,
            self.material_index_size,
            self.bone_index_size,
            self.morph_index_size,
            self.rigid_body_index_size,
        )

    @property
    def global_flags(self) -> bytes:
        """Canonical global flags derived from the editable layout fields."""
        return bytes(
            (
                int(self.encoding),
                self.additional_uv_count,
                *self.index_sizes,
            )
        )

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            self.version in (2.0, 2.1), "header.version", "2.0 or 2.1", self.version
        )
        for name in ("name_jp", "name_en", "comment_jp", "comment_en"):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"header.{name}", "str", value)
        self._require(
            isinstance(self.encoding, PmxTextEncoding),
            "header.encoding",
            "PmxTextEncoding",
            self.encoding,
        )
        self._require(
            0 <= self.additional_uv_count <= 4,
            "header.additional_uv_count",
            "integer in 0..4",
            self.additional_uv_count,
        )
        for name, size in zip(
            (
                "vertex_index_size",
                "texture_index_size",
                "material_index_size",
                "bone_index_size",
                "morph_index_size",
                "rigid_body_index_size",
            ),
            self.index_sizes,
        ):
            self._require(size in (1, 2, 4), f"header.{name}", "1, 2, or 4", size)
        self._require(
            isinstance(self.raw_global_flags, bytes)
            and len(self.raw_global_flags) == 8,
            "header.raw_global_flags",
            "exactly 8 bytes",
            self.raw_global_flags,
        )


class PmxVertex(PmxRecord):
    """PMX顶点数据"""

    def __init__(
        self,
        position: Optional[List[float]] = None,
        normal: Optional[List[float]] = None,
        uv: Optional[List[float]] = None,
        additional_uvs: Optional[List[List[float]]] = None,
        weight_mode: WeightMode = WeightMode.BDEF1,
        weight: Optional[List[List[Union[int, float]]]] = None,
        edge_scale: float = 1.0,
        sdef_c: Optional[List[float]] = None,
        sdef_r0: Optional[List[float]] = None,
        sdef_r1: Optional[List[float]] = None,
    ) -> None:
        """初始化PMX顶点

        Args:
            position: 顶点位置 [x, y, z]
            normal: 法线向量 [x, y, z]
            uv: UV坐标 [u, v]
            additional_uvs: 额外UV坐标列表
            weight_mode: 权重模式
            weight: 权重数据 [[bone_idx, weight_value], ...]
            edge_scale: 边缘缩放
            sdef_c: SDEF C vector
            sdef_r0: SDEF R0 vector
            sdef_r1: SDEF R1 vector
        """
        super().__init__()
        self.position = position or [0.0, 0.0, 0.0]
        self.normal = normal or [0.0, 1.0, 0.0]
        self.uv = uv or [0.0, 0.0]
        self.additional_uvs = additional_uvs or []
        self.weight_mode = weight_mode
        self.weight = [[-1, 1.0]] if weight is None else weight
        self.edge_scale = edge_scale
        self.sdef_c = sdef_c
        self.sdef_r0 = sdef_r0
        self.sdef_r1 = sdef_r1

    def to_list(self) -> List[Any]:
        return [
            self.position,
            self.normal,
            self.uv,
            self.additional_uvs,
            self.weight_mode,
            self.weight,
            self.edge_scale,
            self.sdef_c,
            self.sdef_r0,
            self.sdef_r1,
        ]

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            is_valid_vector(3, self.position), "vertex.position", "vec3", self.position
        )
        self._require(
            is_valid_vector(3, self.normal), "vertex.normal", "vec3", self.normal
        )
        self._require(is_valid_vector(2, self.uv), "vertex.uv", "vec2", self.uv)
        self._require(
            isinstance(self.additional_uvs, list) and len(self.additional_uvs) <= 4,
            "vertex.additional_uvs",
            "0..4 vec4 values",
            self.additional_uvs,
        )
        for index, additional_uv in enumerate(self.additional_uvs):
            self._require(
                is_valid_vector(4, additional_uv),
                f"vertex.additional_uvs[{index}]",
                "vec4",
                additional_uv,
            )
        self._require(
            isinstance(self.weight_mode, WeightMode),
            "vertex.weight_mode",
            "WeightMode",
            self.weight_mode,
        )
        self._require(
            isinstance(self.weight, list), "vertex.weight", "list", self.weight
        )
        self._require(
            isinstance(self.edge_scale, (int, float)),
            "vertex.edge_scale",
            "number",
            self.edge_scale,
        )
        if self.weight_mode == WeightMode.SDEF:
            for name in ("sdef_c", "sdef_r0", "sdef_r1"):
                value = getattr(self, name)
                self._require(
                    is_valid_vector(3, value),
                    f"vertex.{name}",
                    "SDEF vec3",
                    value,
                )
        else:
            self._require(
                self.sdef_c is None and self.sdef_r0 is None and self.sdef_r1 is None,
                "vertex.sdef",
                "None outside SDEF mode",
                (self.sdef_c, self.sdef_r0, self.sdef_r1),
            )


class PmxMaterial(PmxRecord):
    """PMX材质数据"""

    def __init__(
        self,
        name_jp: str = "",
        name_en: str = "",
        diffuse_color: Optional[List[float]] = None,
        specular_color: Optional[List[float]] = None,
        specular_strength: float = 1.0,
        ambient_color: Optional[List[float]] = None,
        flags: Optional[MaterialFlags] = None,
        edge_color: Optional[List[float]] = None,
        edge_size: float = 1.0,
        texture_path: str = "",
        sphere_path: str = "",
        sphere_mode: SphMode = SphMode.DISABLED,
        toon_path: str = "",
        comment: str = "",
        face_count: int = 0,
        *,
        texture_index: int = -1,
        sphere_texture_index: int = -1,
        toon_sharing: ToonSharing = ToonSharing.SEPARATE,
        toon_texture_index: int = -1,
    ) -> None:
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
        self.texture_index = texture_index
        self.sphere_path = sphere_path
        self.sphere_texture_index = sphere_texture_index
        self.sphere_mode = sphere_mode
        self.toon_path = toon_path
        self.toon_sharing = ToonSharing(toon_sharing)
        self.toon_texture_index = toon_texture_index
        self.comment = comment
        self.face_count = face_count

    def to_list(self) -> List[Any]:
        return [
            self.name_jp,
            self.name_en,
            self.diffuse_color,
            self.specular_color,
            self.specular_strength,
            self.ambient_color,
            self.flags.to_list(),
            self.edge_color,
            self.edge_size,
            self.texture_path,
            self.texture_index,
            self.sphere_path,
            self.sphere_texture_index,
            self.sphere_mode,
            self.toon_path,
            self.toon_sharing,
            self.toon_texture_index,
            self.comment,
            self.face_count,
        ]

    @property
    def face_vertex_count(self) -> int:
        """Raw PMX face-vertex count covered by this material."""
        return self.face_count

    @face_vertex_count.setter
    def face_vertex_count(self, value: int) -> None:
        self.face_count = value

    @property
    def triangle_count(self) -> int:
        return self.face_count // 3

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        for name in (
            "name_jp",
            "name_en",
            "texture_path",
            "sphere_path",
            "toon_path",
            "comment",
        ):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"material.{name}", "str", value)
        for name, length in (
            ("diffuse_color", 4),
            ("specular_color", 3),
            ("ambient_color", 3),
            ("edge_color", 4),
        ):
            value = getattr(self, name)
            self._require(
                is_valid_vector(length, value),
                f"material.{name}",
                f"{length} numeric values",
                value,
            )
        for name in ("specular_strength", "edge_size"):
            value = getattr(self, name)
            self._require(
                isinstance(value, (int, float)),
                f"material.{name}",
                "number",
                value,
            )
        self._require(
            isinstance(self.flags, MaterialFlags),
            "material.flags",
            "MaterialFlags",
            self.flags,
        )
        self._require(
            isinstance(self.sphere_mode, SphMode),
            "material.sphere_mode",
            "SphMode",
            self.sphere_mode,
        )
        self._require(
            isinstance(self.toon_sharing, ToonSharing),
            "material.toon_sharing",
            "ToonSharing",
            self.toon_sharing,
        )
        for name in ("texture_index", "sphere_texture_index", "toon_texture_index"):
            value = getattr(self, name)
            self._require(isinstance(value, int), f"material.{name}", "int", value)
        self._require(
            isinstance(self.face_count, int)
            and self.face_count >= 0
            and self.face_count % 3 == 0,
            "material.face_count",
            "non-negative multiple of 3",
            self.face_count,
        )
        if self.toon_sharing == ToonSharing.SHARED:
            self._require(
                0 <= self.toon_texture_index <= 9,
                "material.toon_texture_index",
                "shared Toon index in 0..9",
                self.toon_texture_index,
            )


class BoneFlags:
    """All PMX 2.0 bone flag bits with compatibility spellings."""

    _KNOWN_MASK = 0x3FBF

    def __init__(
        self,
        tail_usebonelink: bool = False,
        rotateable: bool = True,
        translateable: bool = False,
        visible: bool = True,
        enabled: bool = True,
        ik: bool = False,
        inherit_local: bool = False,
        inherit_rot: bool = False,
        inherit_trans: bool = False,
        has_fixedaxis: bool = False,
        has_localaxis: bool = False,
        deform_after_phys: bool = False,
        has_external_parent: bool = False,
        *,
        value: Optional[int] = None,
    ):
        self._unknown_bits = 0
        if value is not None:
            if not 0 <= value <= 0xFFFF:
                raise ValueError("bone flags must fit in uint16")
            tail_usebonelink = bool(value & 0x0001)
            rotateable = bool(value & 0x0002)
            translateable = bool(value & 0x0004)
            visible = bool(value & 0x0008)
            enabled = bool(value & 0x0010)
            ik = bool(value & 0x0020)
            inherit_local = bool(value & 0x0080)
            inherit_rot = bool(value & 0x0100)
            inherit_trans = bool(value & 0x0200)
            has_fixedaxis = bool(value & 0x0400)
            has_localaxis = bool(value & 0x0800)
            deform_after_phys = bool(value & 0x1000)
            has_external_parent = bool(value & 0x2000)
            self._unknown_bits = value & ~self._KNOWN_MASK
        self.tail_usebonelink = tail_usebonelink
        self.rotateable = rotateable
        self.translateable = translateable
        self.visible = visible
        self.enabled = enabled
        self.ik = ik
        self.inherit_local = inherit_local
        self.inherit_rot = inherit_rot
        self.inherit_trans = inherit_trans
        self.has_fixedaxis = has_fixedaxis
        self.has_localaxis = has_localaxis
        self.deform_after_phys = deform_after_phys
        self.has_external_parent = has_external_parent

    @property
    def value(self) -> int:
        result = self._unknown_bits
        for enabled, bit in (
            (self.tail_usebonelink, 0x0001),
            (self.rotateable, 0x0002),
            (self.translateable, 0x0004),
            (self.visible, 0x0008),
            (self.enabled, 0x0010),
            (self.ik, 0x0020),
            (self.inherit_local, 0x0080),
            (self.inherit_rot, 0x0100),
            (self.inherit_trans, 0x0200),
            (self.has_fixedaxis, 0x0400),
            (self.has_localaxis, 0x0800),
            (self.deform_after_phys, 0x1000),
            (self.has_external_parent, 0x2000),
        ):
            if enabled:
                result |= bit
        return result

    @property
    def rotatable(self) -> bool:
        return self.rotateable

    @rotatable.setter
    def rotatable(self, value: bool) -> None:
        self.rotateable = bool(value)

    @property
    def translatable(self) -> bool:
        return self.translateable

    @translatable.setter
    def translatable(self, value: bool) -> None:
        self.translateable = bool(value)

    @property
    def local_append(self) -> bool:
        """Compatibility name for PMX flag ``0x0080`` (local grant)."""
        return self.inherit_local

    @local_append.setter
    def local_append(self, value: bool) -> None:
        self.inherit_local = bool(value)

    def to_list(self) -> List[bool]:
        return [
            self.tail_usebonelink,
            self.rotateable,
            self.translateable,
            self.visible,
            self.enabled,
            self.ik,
            self.inherit_local,
            self.inherit_rot,
            self.inherit_trans,
            self.has_fixedaxis,
            self.has_localaxis,
            self.deform_after_phys,
            self.has_external_parent,
        ]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BoneFlags) and self.value == other.value


class PmxBoneIkLink(PmxRecord):
    """PMX骨骼IK链接"""

    def __init__(
        self,
        bone_index: int = 0,
        limit_min: Optional[List[float]] = None,
        limit_max: Optional[List[float]] = None,
        *,
        has_limits: Optional[bool] = None,
    ) -> None:
        super().__init__()
        self.bone_index = bone_index
        self.limit_min = limit_min
        self.limit_max = limit_max

        inferred = limit_min is not None or limit_max is not None
        self.has_limits = inferred if has_limits is None else has_limits
        if self.has_limits:
            self.limit_min = limit_min or [0.0, 0.0, 0.0]
            self.limit_max = limit_max or [0.0, 0.0, 0.0]

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.bone_index, int),
            "bone.ik_link.bone_index",
            "int",
            self.bone_index,
        )
        self._require(
            isinstance(self.has_limits, bool),
            "bone.ik_link.has_limits",
            "bool",
            self.has_limits,
        )
        if self.has_limits:
            self._require(
                is_valid_vector(3, self.limit_min),
                "bone.ik_link.limit_min",
                "3 radians",
                self.limit_min,
            )
            self._require(
                is_valid_vector(3, self.limit_max),
                "bone.ik_link.limit_max",
                "3 radians",
                self.limit_max,
            )
        else:
            self._require(
                self.limit_min is None and self.limit_max is None,
                "bone.ik_link.limits",
                "None when has_limits=False",
                (self.limit_min, self.limit_max),
            )


class PmxBone(PmxRecord):
    """PMX骨骼"""

    def __init__(
        self,
        name_jp: str = "",
        name_en: str = "",
        position: Optional[List[float]] = None,
        parent_index: int = -1,
        deform_layer: int = 0,
        bone_flags: Optional[BoneFlags] = None,
        tail: Optional[Union[int, List[float]]] = None,
        inherit_parent_index: Optional[int] = None,
        inherit_ratio: Optional[float] = None,
        fixed_axis: Optional[List[float]] = None,
        local_axis_x: Optional[List[float]] = None,
        local_axis_z: Optional[List[float]] = None,
        external_parent_index: Optional[int] = None,
        ik_target_index: Optional[int] = None,
        ik_loop_count: Optional[int] = None,
        ik_angle_limit: Optional[float] = None,
        ik_links: Optional[List[PmxBoneIkLink]] = None,
    ) -> None:
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.position = position or [0.0, 0.0, 0.0]
        self.parent_index = parent_index
        self.deform_layer = deform_layer
        self.bone_flags = bone_flags or BoneFlags()
        self.tail = (
            (-1 if self.bone_flags.tail_usebonelink else [0.0, 0.0, 0.0])
            if tail is None
            else tail
        )
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

    @property
    def tail_bone_index(self) -> Optional[int]:
        return (
            self.tail
            if self.bone_flags.tail_usebonelink and isinstance(self.tail, int)
            else None
        )

    @tail_bone_index.setter
    def tail_bone_index(self, value: int) -> None:
        self.bone_flags.tail_usebonelink = True
        self.tail = value

    @property
    def tail_offset(self) -> Optional[List[float]]:
        return (
            self.tail
            if not self.bone_flags.tail_usebonelink and isinstance(self.tail, list)
            else None
        )

    @tail_offset.setter
    def tail_offset(self, value: List[float]) -> None:
        self.bone_flags.tail_usebonelink = False
        self.tail = value

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        for name in ("name_jp", "name_en"):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"bone.{name}", "str", value)
        self._require(
            is_valid_vector(3, self.position),
            "bone.position",
            "3 numeric values",
            self.position,
        )
        self._require(
            isinstance(self.parent_index, int),
            "bone.parent_index",
            "int",
            self.parent_index,
        )
        self._require(
            isinstance(self.deform_layer, int) and self.deform_layer >= 0,
            "bone.deform_layer",
            "non-negative int",
            self.deform_layer,
        )
        self._require(
            isinstance(self.bone_flags, BoneFlags),
            "bone.bone_flags",
            "BoneFlags",
            self.bone_flags,
        )

        if self.bone_flags.tail_usebonelink:
            self._require(
                isinstance(self.tail, int), "bone.tail", "bone index", self.tail
            )
        else:
            self._require(
                is_valid_vector(3, self.tail), "bone.tail", "relative vec3", self.tail
            )

        if self.bone_flags.inherit_rot or self.bone_flags.inherit_trans:
            self._require(
                isinstance(self.inherit_parent_index, int),
                "bone.inherit_parent_index",
                "int",
                self.inherit_parent_index,
            )
            self._require(
                isinstance(self.inherit_ratio, (int, float)),
                "bone.inherit_ratio",
                "number",
                self.inherit_ratio,
            )
        if self.bone_flags.has_fixedaxis:
            self._require(
                is_valid_vector(3, self.fixed_axis),
                "bone.fixed_axis",
                "vec3",
                self.fixed_axis,
            )
        if self.bone_flags.has_localaxis:
            self._require(
                is_valid_vector(3, self.local_axis_x),
                "bone.local_axis_x",
                "vec3",
                self.local_axis_x,
            )
            self._require(
                is_valid_vector(3, self.local_axis_z),
                "bone.local_axis_z",
                "vec3",
                self.local_axis_z,
            )
        if self.bone_flags.has_external_parent:
            self._require(
                isinstance(self.external_parent_index, int),
                "bone.external_parent_index",
                "int",
                self.external_parent_index,
            )
        if self.bone_flags.ik:
            self._require(
                isinstance(self.ik_target_index, int),
                "bone.ik_target_index",
                "int",
                self.ik_target_index,
            )
            self._require(
                isinstance(self.ik_loop_count, int) and self.ik_loop_count >= 0,
                "bone.ik_loop_count",
                "non-negative int",
                self.ik_loop_count,
            )
            self._require(
                isinstance(self.ik_angle_limit, (int, float)),
                "bone.ik_angle_limit",
                "radians",
                self.ik_angle_limit,
            )
            for link in self.ik_links:
                self._require(
                    isinstance(link, PmxBoneIkLink),
                    "bone.ik_links",
                    "PmxBoneIkLink items",
                    link,
                )
                link.validate(self.ik_links)


class PmxMorphItemGroup(PmxRecord):
    """PMX组变形项目"""

    def __init__(self, morph_index: int = 0, value: float = 0.0) -> None:
        super().__init__()
        self.morph_index = morph_index
        self.value = value

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.morph_index, int),
            "morph.group.morph_index",
            "int",
            self.morph_index,
        )
        self._require(
            isinstance(self.value, (int, float)),
            "morph.group.value",
            "number",
            self.value,
        )


class PmxMorphItemVertex(PmxRecord):
    """PMX顶点变形项目"""

    def __init__(
        self, vertex_index: int = 0, offset: Optional[List[float]] = None
    ) -> None:
        super().__init__()
        self.vertex_index = vertex_index
        self.offset = offset or [0.0, 0.0, 0.0]

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.vertex_index, int),
            "morph.vertex.vertex_index",
            "int",
            self.vertex_index,
        )
        self._require(
            is_valid_vector(3, self.offset),
            "morph.vertex.offset",
            "vec3",
            self.offset,
        )


class PmxMorphItemBone(PmxRecord):
    """PMX骨骼变形项目"""

    def __init__(
        self,
        bone_index: int = 0,
        translation: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
    ) -> None:
        super().__init__()
        self.bone_index = bone_index
        self.translation = translation or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0, 1.0]

    @property
    def rotation_quaternion(self) -> List[float]:
        """Raw PMX quaternion in ``x, y, z, w`` order."""
        return self.rotation

    @rotation_quaternion.setter
    def rotation_quaternion(self, value: List[float]) -> None:
        self.rotation = value

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.bone_index, int),
            "morph.bone.bone_index",
            "int",
            self.bone_index,
        )
        self._require(
            is_valid_vector(3, self.translation),
            "morph.bone.translation",
            "vec3",
            self.translation,
        )
        self._require(
            is_valid_vector(4, self.rotation),
            "morph.bone.rotation",
            "quaternion vec4 (x, y, z, w)",
            self.rotation,
        )


class PmxMorphItemUv(PmxRecord):
    """PMX UV or additional-UV morph item."""

    def __init__(
        self, vertex_index: int = 0, offset: Optional[List[float]] = None
    ) -> None:
        super().__init__()
        self.vertex_index = vertex_index
        self.offset = offset or [0.0, 0.0, 0.0, 0.0]

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.vertex_index, int),
            "morph.uv.vertex_index",
            "int",
            self.vertex_index,
        )
        self._require(
            is_valid_vector(4, self.offset),
            "morph.uv.offset",
            "vec4",
            self.offset,
        )


class PmxMorphItemMaterial(PmxRecord):
    """PMX 2.0 material morph item with every raw factor."""

    def __init__(
        self,
        material_index: int = -1,
        operation: MorphMaterialOperation = MorphMaterialOperation.MULTIPLY,
        diffuse_color: Optional[List[float]] = None,
        specular_color: Optional[List[float]] = None,
        specular_strength: Optional[float] = None,
        ambient_color: Optional[List[float]] = None,
        edge_color: Optional[List[float]] = None,
        edge_size: Optional[float] = None,
        texture_tint: Optional[List[float]] = None,
        sphere_tint: Optional[List[float]] = None,
        toon_tint: Optional[List[float]] = None,
    ) -> None:
        super().__init__()
        self.material_index = material_index
        self.operation = MorphMaterialOperation(operation)
        neutral = 1.0 if self.operation == MorphMaterialOperation.MULTIPLY else 0.0
        self.diffuse_color = diffuse_color or [neutral] * 4
        self.specular_color = specular_color or [neutral] * 3
        self.specular_strength = (
            neutral if specular_strength is None else specular_strength
        )
        self.ambient_color = ambient_color or [neutral] * 3
        self.edge_color = edge_color or [neutral] * 4
        self.edge_size = neutral if edge_size is None else edge_size
        self.texture_tint = texture_tint or [neutral] * 4
        self.sphere_tint = sphere_tint or [neutral] * 4
        self.toon_tint = toon_tint or [neutral] * 4

    @property
    def is_add(self) -> bool:
        return self.operation == MorphMaterialOperation.ADD

    @is_add.setter
    def is_add(self, value: bool) -> None:
        self.operation = (
            MorphMaterialOperation.ADD if value else MorphMaterialOperation.MULTIPLY
        )

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.material_index, int),
            "morph.material.material_index",
            "int",
            self.material_index,
        )
        self._require(
            isinstance(self.operation, MorphMaterialOperation),
            "morph.material.operation",
            "MorphMaterialOperation",
            self.operation,
        )
        for name, size in (
            ("diffuse_color", 4),
            ("specular_color", 3),
            ("ambient_color", 3),
            ("edge_color", 4),
            ("texture_tint", 4),
            ("sphere_tint", 4),
            ("toon_tint", 4),
        ):
            value = getattr(self, name)
            self._require(
                is_valid_vector(size, value),
                f"morph.material.{name}",
                f"vec{size}",
                value,
            )
        for name in ("specular_strength", "edge_size"):
            value = getattr(self, name)
            self._require(
                isinstance(value, (int, float)),
                f"morph.material.{name}",
                "number",
                value,
            )


class PmxMorph(PmxRecord):
    """PMX变形"""

    def __init__(
        self,
        name_jp: str = "",
        name_en: str = "",
        panel: MorphPanel = MorphPanel.OTHER,
        morph_type: MorphType = MorphType.VERTEX,
        items: Optional[List[Any]] = None,
    ) -> None:
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.panel = MorphPanel(panel)
        self.morph_type = MorphType(morph_type)
        self.items = items or []

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        for name in ("name_jp", "name_en"):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"morph.{name}", "str", value)
        self._require(
            isinstance(self.panel, MorphPanel),
            "morph.panel",
            "MorphPanel",
            self.panel,
        )
        self._require(
            isinstance(self.morph_type, MorphType),
            "morph.morph_type",
            "MorphType",
            self.morph_type,
        )
        expected_item_types = {
            MorphType.GROUP: PmxMorphItemGroup,
            MorphType.VERTEX: PmxMorphItemVertex,
            MorphType.BONE: PmxMorphItemBone,
            MorphType.UV: PmxMorphItemUv,
            MorphType.EXTENDED_UV1: PmxMorphItemUv,
            MorphType.EXTENDED_UV2: PmxMorphItemUv,
            MorphType.EXTENDED_UV3: PmxMorphItemUv,
            MorphType.EXTENDED_UV4: PmxMorphItemUv,
            MorphType.MATERIAL: PmxMorphItemMaterial,
        }
        expected_type = expected_item_types.get(self.morph_type)
        self._require(
            expected_type is not None,
            "morph.morph_type",
            "PMX 2.0 morph type",
            self.morph_type,
        )
        for item in self.items:
            self._require(
                isinstance(item, expected_type),
                "morph.items",
                expected_type.__name__,
                item,
            )
            item.validate(self.items)


class PmxFrameItem(PmxRecord):
    """PMX框架项目"""

    def __init__(self, is_morph: bool = False, index: int = 0) -> None:
        super().__init__()
        self.is_morph = is_morph
        self.index = index

    @property
    def bone_index(self) -> Optional[int]:
        return None if self.is_morph else self.index

    @bone_index.setter
    def bone_index(self, value: int) -> None:
        self.is_morph = False
        self.index = value

    @property
    def morph_index(self) -> Optional[int]:
        return self.index if self.is_morph else None

    @morph_index.setter
    def morph_index(self, value: int) -> None:
        self.is_morph = True
        self.index = value

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        self._require(
            isinstance(self.is_morph, bool),
            "display_frame.item.is_morph",
            "bool",
            self.is_morph,
        )
        self._require(
            isinstance(self.index, int),
            "display_frame.item.index",
            "int",
            self.index,
        )


class PmxFrame(PmxRecord):
    """PMX显示框架"""

    def __init__(
        self,
        name_jp: str = "",
        name_en: str = "",
        is_special: bool = False,
        items: Optional[List[PmxFrameItem]] = None,
    ) -> None:
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.is_special = is_special
        self.items = items or []

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        for name in ("name_jp", "name_en"):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"display_frame.{name}", "str", value)
        self._require(
            isinstance(self.is_special, bool),
            "display_frame.is_special",
            "bool",
            self.is_special,
        )
        for item in self.items:
            self._require(
                isinstance(item, PmxFrameItem),
                "display_frame.items",
                "PmxFrameItem",
                item,
            )
            item.validate(self.items)


class PmxRigidBody(PmxRecord):
    """PMX刚体"""

    def __init__(
        self,
        name_jp: str = "",
        name_en: str = "",
        bone_index: int = 0,
        group: int = 1,
        nocollide_groups: Optional[List[int]] = None,
        shape: RigidBodyShape = RigidBodyShape.SPHERE,
        size: Optional[List[float]] = None,
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        physics_mode: RigidBodyPhysMode = RigidBodyPhysMode.PHYSICS,
        mass: float = 1.0,
        move_damping: float = 0.5,
        rotation_damping: float = 0.5,
        repulsion: float = 0.0,
        friction: float = 0.5,
        *,
        collision_group: Optional[int] = None,
        collision_mask: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.bone_index = bone_index
        self._collision_group = (
            group - 1 if collision_group is None else collision_group
        )
        if collision_mask is None:
            collision_mask = 0xFFFF
            for excluded_group in nocollide_groups or []:
                if 1 <= excluded_group <= 16:
                    collision_mask &= ~(1 << (excluded_group - 1))
        self._collision_mask = collision_mask
        self.shape = RigidBodyShape(shape)
        self.size = size or [1.0, 1.0, 1.0]
        self.position = position or [0.0, 0.0, 0.0]
        self.rotation = rotation or [0.0, 0.0, 0.0]
        self.physics_mode = RigidBodyPhysMode(physics_mode)
        self.mass = mass
        self.move_damping = move_damping
        self.rotation_damping = rotation_damping
        self.repulsion = repulsion
        self.friction = friction

    @property
    def collision_group(self) -> int:
        """Raw PMX collision group in the 0..15 range."""
        return self._collision_group

    @collision_group.setter
    def collision_group(self, value: int) -> None:
        self._collision_group = value

    @property
    def collision_mask(self) -> int:
        """Raw uint16 PMX collision mask; set bits are enabled collisions."""
        return self._collision_mask

    @collision_mask.setter
    def collision_mask(self, value: int) -> None:
        self._collision_mask = value

    @property
    def group(self) -> int:
        """Compatibility view using PMXEditor-style groups 1..16."""
        return self._collision_group + 1

    @group.setter
    def group(self, value: int) -> None:
        self._collision_group = value - 1

    @property
    def nocollide_groups(self) -> List[int]:
        return [
            group + 1 for group in range(16) if not self._collision_mask & (1 << group)
        ]

    @nocollide_groups.setter
    def nocollide_groups(self, groups: List[int]) -> None:
        mask = 0xFFFF
        for group in groups:
            if not 1 <= group <= 16:
                raise PmxValidationError(
                    "rigid_body.nocollide_groups", "values in 1..16", groups
                )
            mask &= ~(1 << (group - 1))
        self._collision_mask = mask

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        for name in ("name_jp", "name_en"):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"rigid_body.{name}", "str", value)
        self._require(
            isinstance(self.bone_index, int),
            "rigid_body.bone_index",
            "int",
            self.bone_index,
        )
        self._require(
            0 <= self.collision_group <= 15,
            "rigid_body.collision_group",
            "0..15",
            self.collision_group,
        )
        self._require(
            0 <= self.collision_mask <= 0xFFFF,
            "rigid_body.collision_mask",
            "uint16",
            self.collision_mask,
        )
        self._require(
            isinstance(self.shape, RigidBodyShape),
            "rigid_body.shape",
            "RigidBodyShape",
            self.shape,
        )
        self._require(
            isinstance(self.physics_mode, RigidBodyPhysMode),
            "rigid_body.physics_mode",
            "RigidBodyPhysMode",
            self.physics_mode,
        )
        for name in ("size", "position", "rotation"):
            value = getattr(self, name)
            self._require(
                is_valid_vector(3, value),
                f"rigid_body.{name}",
                "3 numeric values",
                value,
            )
        for name in (
            "mass",
            "move_damping",
            "rotation_damping",
            "repulsion",
            "friction",
        ):
            value = getattr(self, name)
            self._require(
                isinstance(value, (int, float)), f"rigid_body.{name}", "number", value
            )
        self._require(self.mass >= 0, "rigid_body.mass", "non-negative", self.mass)


class PmxJoint(PmxRecord):
    """PMX关节"""

    def __init__(
        self,
        name_jp: str = "",
        name_en: str = "",
        joint_type: JointType = JointType.SPRING6DOF,
        rigidbody1_index: int = 0,
        rigidbody2_index: int = 0,
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        position_min: Optional[List[float]] = None,
        position_max: Optional[List[float]] = None,
        rotation_min: Optional[List[float]] = None,
        rotation_max: Optional[List[float]] = None,
        position_spring: Optional[List[float]] = None,
        rotation_spring: Optional[List[float]] = None,
    ) -> None:
        super().__init__()
        self.name_jp = name_jp
        self.name_en = name_en
        self.joint_type = JointType(joint_type)
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

    @property
    def rigid_body_a_index(self) -> int:
        return self.rigidbody1_index

    @rigid_body_a_index.setter
    def rigid_body_a_index(self, value: int) -> None:
        self.rigidbody1_index = value

    @property
    def rigid_body_b_index(self) -> int:
        return self.rigidbody2_index

    @rigid_body_b_index.setter
    def rigid_body_b_index(self, value: int) -> None:
        self.rigidbody2_index = value

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        for name in ("name_jp", "name_en"):
            value = getattr(self, name)
            self._require(isinstance(value, str), f"joint.{name}", "str", value)
        self._require(
            isinstance(self.joint_type, JointType),
            "joint.joint_type",
            "JointType",
            self.joint_type,
        )
        for name in ("rigidbody1_index", "rigidbody2_index"):
            value = getattr(self, name)
            self._require(isinstance(value, int), f"joint.{name}", "int", value)
        for name in (
            "position",
            "rotation",
            "position_min",
            "position_max",
            "rotation_min",
            "rotation_max",
            "position_spring",
            "rotation_spring",
        ):
            value = getattr(self, name)
            self._require(
                is_valid_vector(3, value), f"joint.{name}", "3 numeric values", value
            )


class PmxSoftBody(PmxRecord):
    """PMX软体"""

    def __init__(self) -> None:
        super().__init__()
        # 简化实现，PMX v2.1功能较少使用
        pass


class PmxModel(PmxRecord):
    """PMX模型主类

    包含PMX模型的所有数据，提供统一的访问接口。
    """

    def __init__(self) -> None:
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
        self.parse_report: Optional["PmxParseReport"] = None

    def to_list(self) -> List[Any]:
        return [
            self.header.to_list(),
            len(self.vertices),
            len(self.faces),
            len(self.textures),
            len(self.materials),
            len(self.bones),
            len(self.morphs),
            len(self.frames),
            len(self.rigidbodies),
            len(self.joints),
            len(self.softbodies),
        ]

    @property
    def display_frames(self) -> List[PmxFrame]:
        return self.frames

    @display_frames.setter
    def display_frames(self, value: List[PmxFrame]) -> None:
        self.frames = value

    @property
    def rigid_bodies(self) -> List[PmxRigidBody]:
        return self.rigidbodies

    @rigid_bodies.setter
    def rigid_bodies(self, value: List[PmxRigidBody]) -> None:
        self.rigidbodies = value

    @property
    def soft_bodies(self) -> List[PmxSoftBody]:
        return self.softbodies

    @soft_bodies.setter
    def soft_bodies(self, value: List[PmxSoftBody]) -> None:
        self.softbodies = value

    @property
    def is_complete(self) -> bool:
        return self.parse_report is not None and self.parse_report.is_complete

    @property
    def loaded_sections(self) -> frozenset[str]:
        if self.parse_report is None:
            return frozenset()
        return self.parse_report.loaded_sections

    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        from pypmxvmd.common.pmx.validator import validate_pmx_model

        validate_pmx_model(self)

    def get_vertex_count(self) -> int:
        """获取顶点数量"""
        return len(self.vertices)

    def get_face_count(self) -> int:
        """获取面数量"""
        return len(self.faces)

    def get_material_count(self) -> int:
        """获取材质数量"""
        return len(self.materials)
