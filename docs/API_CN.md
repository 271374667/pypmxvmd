# PyPMXVMD API 文档

PyPMXVMD 是一个用于解析和修改 MikuMikuDance (MMD) 文件的 Python 库。

**版本**: 2.7.1
**Python要求**: >= 3.8
**加速**: 支持可选 Cython 快速解析与二进制 I/O，若不可用将自动回退到纯 Python 解析。

---

## 目录

- [快速开始](#快速开始)
- [顶层API](#顶层api)
- [数据模型](#数据模型)
  - [VMD模型](#vmd模型)
  - [PMX模型](#pmx模型)
  - [VPD模型](#vpd模型)
- [解析器](#解析器)
- [枚举类型](#枚举类型)
- [使用示例](#使用示例)

---

## 快速开始

### 安装

```bash
pip install pypmxvmd
```

### 基础用法

```python
import pypmxvmd

# 自动检测文件类型并加载
data = pypmxvmd.load("motion.vmd")

# 保存文件
pypmxvmd.save(data, "output.vmd")
```

---

## 顶层API

PyPMXVMD 提供了简洁的顶层函数，用于文件的加载和保存。

### 二进制文件操作

#### `pypmxvmd.load(file_path, more_info=False)`

自动检测文件类型并加载。

**参数**:
- `file_path` (str | Path): 文件路径
- `more_info` (bool): 是否显示详细解析信息

**返回**: `VmdMotion` | `PmxModel` | `VpdPose`

**异常**: `ValueError` - 不支持的文件类型

```python
data = pypmxvmd.load("model.pmx")
```

---

#### `pypmxvmd.save(data, file_path)`

自动检测数据类型并保存。

**参数**:
- `data`: `VmdMotion` | `PmxModel` | `VpdPose` 对象
- `file_path` (str | Path): 输出文件路径

```python
pypmxvmd.save(model, "output.pmx")
```

---

#### `pypmxvmd.load_vmd(file_path, more_info=False) -> VmdMotion`

加载VMD动作文件。

**参数**:
- `file_path` (str | Path): VMD文件路径
- `more_info` (bool): 是否显示详细解析信息

**返回**: `VmdMotion` 对象

```python
motion = pypmxvmd.load_vmd("dance.vmd")
print(f"骨骼帧数: {len(motion.bone_frames)}")
```

---

#### `pypmxvmd.save_vmd(motion, file_path)`

保存VMD动作文件。

**参数**:
- `motion` (VmdMotion): VMD动作对象
- `file_path` (str | Path): 输出文件路径

```python
pypmxvmd.save_vmd(motion, "output.vmd")
```

---

#### `pypmxvmd.load_pmx(file_path, more_info=False) -> PmxModel`

加载PMX模型文件。

**参数**:
- `file_path` (str | Path): PMX文件路径
- `more_info` (bool): 是否显示详细解析信息

**返回**: `PmxModel` 对象

```python
model = pypmxvmd.load_pmx("character.pmx")
print(f"顶点数: {len(model.vertices)}")
```

---

#### `pypmxvmd.save_pmx(model, file_path)`

保存PMX模型文件。

**参数**:
- `model` (PmxModel): PMX模型对象
- `file_path` (str | Path): 输出文件路径

```python
pypmxvmd.save_pmx(model, "output.pmx")
```

---

#### `pypmxvmd.load_vpd(file_path, more_info=False) -> VpdPose`

加载VPD姿势文件。

**参数**:
- `file_path` (str | Path): VPD文件路径
- `more_info` (bool): 是否显示详细解析信息

**返回**: `VpdPose` 对象

```python
pose = pypmxvmd.load_vpd("pose.vpd")
print(f"骨骼姿势数: {len(pose.bone_poses)}")
```

---

#### `pypmxvmd.save_vpd(pose, file_path)`

保存VPD姿势文件。

**参数**:
- `pose` (VpdPose): VPD姿势对象
- `file_path` (str | Path): 输出文件路径

```python
pypmxvmd.save_vpd(pose, "output.vpd")
```

---

### 文本文件操作

PyPMXVMD 还支持文本格式的读写，便于人工编辑和查看。

#### `pypmxvmd.load_vmd_text(file_path, more_info=False) -> VmdMotion`

从文本格式加载VMD动作。

#### `pypmxvmd.save_vmd_text(motion, file_path)`

将VMD动作保存为文本格式。

#### `pypmxvmd.load_pmx_text(file_path, more_info=False) -> PmxModel`

从文本格式加载PMX模型。

#### `pypmxvmd.save_pmx_text(model, file_path)`

将PMX模型保存为文本格式。

#### `pypmxvmd.load_vpd_text(file_path, more_info=False) -> VpdPose`

从文本格式加载VPD姿势。

#### `pypmxvmd.save_vpd_text(pose, file_path)`

将VPD姿势保存为文本格式。

---

#### `pypmxvmd.load_text(file_path, more_info=False) -> VmdMotion | PmxModel | VpdPose`

自动检测文本文件格式并加载。

**参数**:
- `file_path` (str | Path): 文本文件路径
- `more_info` (bool): 是否显示详细解析信息

**返回**: `VmdMotion` | `PmxModel` | `VpdPose`

---

#### `pypmxvmd.save_text(data, file_path)`

自动检测数据类型并保存为对应文本格式。

**参数**:
- `data`: `VmdMotion` | `PmxModel` | `VpdPose` 对象
- `file_path` (str | Path): 输出文本文件路径

---

## 数据模型

### VMD模型

VMD (Vocaloid Motion Data) 用于存储动作和相机数据。

#### `VmdMotion`

VMD动作主类，包含所有动作数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `header` | `VmdHeader` | 文件头信息 |
| `bone_frames` | `List[VmdBoneFrame]` | 骨骼关键帧列表 |
| `morph_frames` | `List[VmdMorphFrame]` | 变形关键帧列表 |
| `camera_frames` | `List[VmdCameraFrame]` | 相机关键帧列表 |
| `light_frames` | `List[VmdLightFrame]` | 光照关键帧列表 |
| `shadow_frames` | `List[VmdShadowFrame]` | 阴影关键帧列表 |
| `ik_frames` | `List[VmdIkFrame]` | IK显示关键帧列表 |

**方法**:

```python
motion.get_bone_frame_count() -> int      # 获取骨骼帧数
motion.get_morph_frame_count() -> int     # 获取变形帧数
motion.get_total_frame_count() -> int     # 获取总帧数
motion.is_camera_motion() -> bool         # 是否为相机动作
motion.validate()                         # 验证数据有效性
```

---

#### `VmdHeader`

VMD文件头信息。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `version` | `int` | VMD版本 (1=旧版, 2=新版) |
| `model_name` | `str` | 模型名称 (日文) |

```python
header = VmdHeader(version=2, model_name="TestModel")
```

---

#### `VmdBoneFrame`

骨骼关键帧。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `bone_name` | `str` | 骨骼名称 (日文，最大15字节) |
| `frame_number` | `int` | 帧号 (≥0) |
| `position` | `List[float]` | 位置 [x, y, z] |
| `rotation` | `List[float]` | 旋转欧拉角 [x, y, z] (度) |
| `interpolation` | `List[int]` | 插值曲线数据 (16个值) |
| `physics_disabled` | `bool` | 是否禁用物理 |

```python
frame = VmdBoneFrame(
    bone_name="センター",
    frame_number=0,
    position=[0.0, 10.0, 0.0],
    rotation=[0.0, 0.0, 0.0]
)
```

---

#### `VmdMorphFrame`

变形关键帧。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `morph_name` | `str` | 变形名称 (日文，最大15字节) |
| `frame_number` | `int` | 帧号 (≥0) |
| `weight` | `float` | 权重值 (0.0-1.0) |

```python
frame = VmdMorphFrame(
    morph_name="まばたき",
    frame_number=30,
    weight=1.0
)
```

---

#### `VmdCameraFrame`

相机关键帧。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `frame_number` | `int` | 帧号 |
| `distance` | `float` | 到目标的距离 |
| `position` | `List[float]` | 目标位置 [x, y, z] |
| `rotation` | `List[float]` | 相机旋转 [x, y, z] (度数，读取时由弧度转换) |
| `interpolation` | `List[int]` | 插值曲线数据 (24个值) |
| `fov` | `int` | 视野角度 (1-180) |
| `perspective` | `bool` | 是否透视投影 |

---

#### `VmdLightFrame`

光照关键帧。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `frame_number` | `int` | 帧号 |
| `color` | `List[float]` | 光照颜色 [r, g, b] (0.0-1.0) |
| `position` | `List[float]` | 光照位置 [x, y, z] |

---

#### `VmdShadowFrame`

阴影关键帧。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `frame_number` | `int` | 帧号 |
| `shadow_mode` | `ShadowMode` | 阴影模式 |
| `distance` | `float` | 阴影距离 |

---

#### `VmdIkFrame`

IK显示关键帧。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `frame_number` | `int` | 帧号 |
| `display` | `bool` | 是否显示模型 |
| `ik_bones` | `List[VmdIkBone]` | IK骨骼列表 |

---

#### `VmdIkBone`

IK骨骼信息。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `bone_name` | `str` | IK骨骼名称 (最大20字节) |
| `ik_enabled` | `bool` | 是否启用IK |

---

### PMX模型

PMX (Polygon Model eXtended) 用于存储3D模型数据。

#### `PmxModel`

PMX模型主类。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `header` | `PmxHeader` | 文件头信息 |
| `vertices` | `List[PmxVertex]` | 顶点列表 |
| `faces` | `List[List[int]]` | 面索引列表 (每面3个顶点索引) |
| `textures` | `List[str]` | 纹理路径列表 |
| `materials` | `List[PmxMaterial]` | 材质列表 |
| `bones` | `List[PmxBone]` | 骨骼列表 |
| `morphs` | `List[PmxMorph]` | 变形列表 |
| `frames` | `List[PmxFrame]` | 显示框架列表 |
| `rigidbodies` | `List[PmxRigidBody]` | 刚体列表 |
| `joints` | `List[PmxJoint]` | 关节列表 |
| `softbodies` | `List[PmxSoftBody]` | 软体列表 (PMX 2.1) |

**方法**:

```python
model.get_vertex_count() -> int      # 获取顶点数
model.get_face_count() -> int        # 获取面数
model.get_material_count() -> int    # 获取材质数
model.validate()                     # 验证数据有效性
```

---

#### `PmxHeader`

PMX文件头信息。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `version` | `float` | PMX版本号 (2.0 或 2.1) |
| `name_jp` | `str` | 日文名称 |
| `name_en` | `str` | 英文名称 |
| `comment_jp` | `str` | 日文注释 |
| `comment_en` | `str` | 英文注释 |

```python
header = PmxHeader(
    version=2.0,
    name_jp="テストモデル",
    name_en="TestModel",
    comment_jp="テスト用",
    comment_en="For testing"
)
```

---

#### `PmxVertex`

PMX顶点数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `position` | `List[float]` | 位置 [x, y, z] |
| `normal` | `List[float]` | 法线 [x, y, z] |
| `uv` | `List[float]` | UV坐标 [u, v] |
| `additional_uvs` | `List[List[float]]` | 额外UV列表 |
| `weight_mode` | `WeightMode` | 权重模式 |
| `weight` | `List[List]` | 权重数据 [[bone_idx, weight], ...] |
| `edge_scale` | `float` | 边缘缩放 |

```python
vertex = PmxVertex(
    position=[0.0, 1.0, 0.0],
    normal=[0.0, 1.0, 0.0],
    uv=[0.5, 0.5]
)
```

---

#### `PmxMaterial`

PMX材质数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `name_jp` | `str` | 日文名称 |
| `name_en` | `str` | 英文名称 |
| `diffuse_color` | `List[float]` | 漫反射色 [r, g, b, a] |
| `specular_color` | `List[float]` | 镜面反射色 [r, g, b] |
| `specular_strength` | `float` | 镜面反射强度 |
| `ambient_color` | `List[float]` | 环境光色 [r, g, b] |
| `flags` | `MaterialFlags` | 材质标志位 |
| `edge_color` | `List[float]` | 边缘颜色 [r, g, b, a] |
| `edge_size` | `float` | 边缘大小 |
| `texture_path` | `str` | 纹理路径 |
| `sphere_path` | `str` | 球面纹理路径 |
| `sphere_mode` | `SphMode` | 球面纹理模式 |
| `toon_path` | `str` | 卡通渲染纹理路径 |
| `comment` | `str` | 注释 |
| `face_count` | `int` | 面顶点数 |

```python
material = PmxMaterial(
    name_jp="材質",
    name_en="Material",
    diffuse_color=[0.8, 0.8, 0.8, 1.0],
    specular_color=[0.3, 0.3, 0.3],
    specular_strength=5.0,
    ambient_color=[0.2, 0.2, 0.2],
    face_count=3
)
```

---

#### `MaterialFlags`

材质标志位类。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `double_sided` | `bool` | 双面显示 |
| `ground_shadow` | `bool` | 地面阴影 |
| `self_shadow_map` | `bool` | 自阴影贴图 |
| `self_shadow` | `bool` | 自阴影 |
| `edge_drawing` | `bool` | 边缘绘制 |
| `vertex_color` | `bool` | 顶点色 |
| `point_drawing` | `bool` | 点绘制 |
| `line_drawing` | `bool` | 线绘制 |

```python
flags = MaterialFlags()
flags.double_sided = True
flags.edge_drawing = True
```

---

#### `PmxBone`

PMX骨骼数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `name_jp` | `str` | 日文名称 |
| `name_en` | `str` | 英文名称 |
| `position` | `List[float]` | 位置 [x, y, z] |
| `parent_index` | `int` | 父骨骼索引 (-1表示无父骨骼) |
| `deform_layer` | `int` | 变形层级 |
| `bone_flags` | `BoneFlags` | 骨骼标志位 |
| `tail` | `int \| List[float]` | 尾端 (骨骼索引或偏移量) |
| `inherit_parent_index` | `int` | 继承父索引 |
| `inherit_ratio` | `float` | 继承比率 |
| `fixed_axis` | `List[float]` | 固定轴 |
| `local_axis_x` | `List[float]` | 本地X轴 |
| `local_axis_z` | `List[float]` | 本地Z轴 |
| `external_parent_index` | `int` | 外部父索引 |
| `ik_target_index` | `int` | IK目标索引 |
| `ik_loop_count` | `int` | IK循环次数 |
| `ik_angle_limit` | `float` | IK角度限制 |
| `ik_links` | `List[PmxBoneIkLink]` | IK链接列表 |

---

#### `PmxMorph`

PMX变形数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `name_jp` | `str` | 日文名称 |
| `name_en` | `str` | 英文名称 |
| `panel` | `MorphPanel` | 面板位置 |
| `morph_type` | `MorphType` | 变形类型 |
| `items` | `List` | 变形项目列表 |

---

#### `PmxRigidBody`

PMX刚体数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `name_jp` | `str` | 日文名称 |
| `name_en` | `str` | 英文名称 |
| `bone_index` | `int` | 关联骨骼索引 |
| `group` | `int` | 碰撞组 |
| `nocollide_groups` | `List[int]` | 非碰撞组列表 |
| `shape` | `RigidBodyShape` | 形状类型 |
| `size` | `List[float]` | 尺寸 [x, y, z] |
| `position` | `List[float]` | 位置 [x, y, z] |
| `rotation` | `List[float]` | 旋转 [x, y, z] |
| `physics_mode` | `RigidBodyPhysMode` | 物理模式 |
| `mass` | `float` | 质量 |
| `move_damping` | `float` | 移动衰减 |
| `rotation_damping` | `float` | 旋转衰减 |
| `repulsion` | `float` | 反弹力 |
| `friction` | `float` | 摩擦力 |

---

#### `PmxJoint`

PMX关节数据。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `name_jp` | `str` | 日文名称 |
| `name_en` | `str` | 英文名称 |
| `joint_type` | `JointType` | 关节类型 |
| `rigidbody1_index` | `int` | 刚体1索引 |
| `rigidbody2_index` | `int` | 刚体2索引 |
| `position` | `List[float]` | 位置 |
| `rotation` | `List[float]` | 旋转 |
| `position_min` | `List[float]` | 位置最小值 |
| `position_max` | `List[float]` | 位置最大值 |
| `rotation_min` | `List[float]` | 旋转最小值 |
| `rotation_max` | `List[float]` | 旋转最大值 |
| `position_spring` | `List[float]` | 位置弹簧 |
| `rotation_spring` | `List[float]` | 旋转弹簧 |

---

### VPD模型

VPD (Vocaloid Pose Data) 用于存储单帧姿势数据。

#### `VpdPose`

VPD姿势主类。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `model_name` | `str` | 模型名称 |
| `bone_poses` | `List[VpdBonePose]` | 骨骼姿势列表 |
| `morph_poses` | `List[VpdMorphPose]` | 变形姿势列表 |

**方法**:

```python
pose.get_bone_count() -> int     # 获取骨骼姿势数
pose.get_morph_count() -> int    # 获取变形姿势数
pose.validate()                  # 验证数据有效性
```

---

#### `VpdBonePose`

VPD骨骼姿势。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `bone_name` | `str` | 骨骼名称 |
| `position` | `List[float]` | 位置 [x, y, z] |
| `rotation` | `List[float]` | 旋转四元数 [x, y, z, w] |

```python
bone_pose = VpdBonePose(
    bone_name="センター",
    position=[0.0, 10.0, 0.0],
    rotation=[0.0, 0.0, 0.0, 1.0]
)
```

---

#### `VpdMorphPose`

VPD变形姿势。

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `morph_name` | `str` | 变形名称 |
| `weight` | `float` | 权重值 (0.0-1.0) |

```python
morph_pose = VpdMorphPose(
    morph_name="笑顔",
    weight=0.8
)
```

---

## 解析器

如果需要更精细的控制，可以直接使用解析器类。

解析器会在可用时自动使用 Cython 快速路径，否则回退到纯 Python 实现。

### `VmdParser`

VMD文件解析器。

```python
from pypmxvmd.common.parsers.vmd_parser import VmdParser

parser = VmdParser(progress_callback=lambda p: print(f"{p*100:.1f}%"))
motion = parser.parse_file("motion.vmd", more_info=True)
parser.write_file(motion, "output.vmd")
```

### `PmxParser`

PMX文件解析器。

```python
from pypmxvmd.common.parsers.pmx_parser import PmxParser

parser = PmxParser(progress_callback=lambda p: print(f"{p*100:.1f}%"))
model = parser.parse_file("model.pmx", more_info=True)
parser.write_file(model, "output.pmx")
```

### `VpdParser`

VPD文件解析器。

```python
from pypmxvmd.common.parsers.vpd_parser import VpdParser

parser = VpdParser(progress_callback=lambda p: print(f"{p*100:.1f}%"))
pose = parser.parse_file("pose.vpd", more_info=True)
parser.write_file(pose, "output.vpd")
```

---

## 枚举类型

### VMD枚举

#### `ShadowMode`

阴影模式。

| 值 | 说明 |
|----|------|
| `OFF` (0) | 关闭 |
| `MODE1` (1) | 模式1 |
| `MODE2` (2) | 模式2 |

---

### PMX枚举

#### `WeightMode`

顶点权重模式。

| 值 | 说明 |
|----|------|
| `BDEF1` (0) | 单骨骼变形 |
| `BDEF2` (1) | 双骨骼变形 |
| `BDEF4` (2) | 四骨骼变形 |
| `SDEF` (3) | 球面变形 |
| `QDEF` (4) | 四元数变形 |

---

#### `SphMode`

球面纹理模式。

| 值 | 说明 |
|----|------|
| `DISABLED` (0) | 禁用 |
| `MULTIPLY` (1) | 乘算 |
| `ADDITIVE` (2) | 加算 |
| `SUBTEX` (3) | 子纹理 |

---

#### `MorphType`

变形类型。

| 值 | 说明 |
|----|------|
| `GROUP` (0) | 组变形 |
| `VERTEX` (1) | 顶点变形 |
| `BONE` (2) | 骨骼变形 |
| `UV` (3) | UV变形 |
| `EXTENDED_UV1` (4) | 扩展UV1变形 |
| `EXTENDED_UV2` (5) | 扩展UV2变形 |
| `EXTENDED_UV3` (6) | 扩展UV3变形 |
| `EXTENDED_UV4` (7) | 扩展UV4变形 |
| `MATERIAL` (8) | 材质变形 |
| `FLIP` (9) | 翻转变形 |
| `IMPULSE` (10) | 冲击变形 |

---

#### `MorphPanel`

变形面板位置。

| 值 | 说明 |
|----|------|
| `HIDDEN` (0) | 隐藏 |
| `EYEBROW` (1) | 眉毛 (左下) |
| `EYE` (2) | 眼睛 (左上) |
| `MOUTH` (3) | 嘴巴 (右上) |
| `OTHER` (4) | 其他 (右下) |

---

#### `RigidBodyShape`

刚体形状。

| 值 | 说明 |
|----|------|
| `SPHERE` (0) | 球体 |
| `BOX` (1) | 盒子 |
| `CAPSULE` (2) | 胶囊 |

---

#### `RigidBodyPhysMode`

刚体物理模式。

| 值 | 说明 |
|----|------|
| `BONE` (0) | 骨骼跟随 |
| `PHYSICS` (1) | 物理演算 |
| `PHYSICS_BONE` (2) | 物理演算+骨骼追随 |

---

#### `JointType`

关节类型。

| 值 | 说明 |
|----|------|
| `SPRING6DOF` (0) | 6DOF弹簧关节 |

---

## 使用示例

### 示例1: 读取VMD动作并获取信息

```python
import pypmxvmd

# 加载VMD文件
motion = pypmxvmd.load_vmd("dance.vmd", more_info=True)

# 获取基本信息
print(f"版本: {motion.header.version}")
print(f"模型名: {motion.header.model_name}")
print(f"骨骼帧数: {motion.get_bone_frame_count()}")
print(f"变形帧数: {motion.get_morph_frame_count()}")

# 遍历骨骼帧
for frame in motion.bone_frames[:5]:
    print(f"骨骼: {frame.bone_name}, 帧: {frame.frame_number}, 位置: {frame.position}")
```

### 示例2: 创建简单的PMX模型

```python
import pypmxvmd
from pypmxvmd.common.models.pmx import PmxModel, PmxHeader, PmxVertex, PmxMaterial

# 创建模型
model = PmxModel()

# 设置头信息
model.header = PmxHeader(
    version=2.0,
    name_jp="三角形",
    name_en="Triangle"
)

# 添加顶点
model.vertices = [
    PmxVertex(position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0], uv=[0.0, 0.0]),
    PmxVertex(position=[1.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0], uv=[1.0, 0.0]),
    PmxVertex(position=[0.5, 1.0, 0.0], normal=[0.0, 0.0, 1.0], uv=[0.5, 1.0]),
]

# 添加面
model.faces = [[0, 1, 2]]

# 添加材质
model.materials = [
    PmxMaterial(
        name_jp="材質",
        name_en="Material",
        diffuse_color=[0.8, 0.8, 0.8, 1.0],
        face_count=3
    )
]

# 保存
pypmxvmd.save_pmx(model, "triangle.pmx")
```

### 示例3: 修改VMD动作

```python
import pypmxvmd

# 加载动作
motion = pypmxvmd.load_vmd("original.vmd")

# 修改所有骨骼帧的位置 - 整体抬高10个单位
for frame in motion.bone_frames:
    frame.position[1] += 10.0

# 缩放所有变形权重为原来的50%
for frame in motion.morph_frames:
    frame.weight *= 0.5

# 保存修改后的动作
pypmxvmd.save_vmd(motion, "modified.vmd")
```

### 示例4: VPD姿势转VMD动作

```python
import pypmxvmd
from pypmxvmd.common.models.vmd import VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame

# 加载VPD姿势
pose = pypmxvmd.load_vpd("pose.vpd")

# 创建VMD动作
motion = VmdMotion()
motion.header = VmdHeader(version=2, model_name=pose.model_name)

# 转换骨骼姿势为骨骼帧
for bone_pose in pose.bone_poses:
    # 四元数转欧拉角 (简化处理)
    frame = VmdBoneFrame(
        bone_name=bone_pose.bone_name,
        frame_number=0,
        position=bone_pose.position,
        rotation=[0.0, 0.0, 0.0]  # 需要实际转换
    )
    motion.bone_frames.append(frame)

# 转换变形姿势为变形帧
for morph_pose in pose.morph_poses:
    frame = VmdMorphFrame(
        morph_name=morph_pose.morph_name,
        frame_number=0,
        weight=morph_pose.weight
    )
    motion.morph_frames.append(frame)

# 保存
pypmxvmd.save_vmd(motion, "pose_as_motion.vmd")
```

### 示例5: 数据验证

```python
import pypmxvmd

# 加载模型
model = pypmxvmd.load_pmx("model.pmx")

# 验证数据完整性
try:
    model.validate()
    print("模型数据验证通过")
except AssertionError as e:
    print(f"模型数据验证失败: {e}")
```

---

## 错误处理

PyPMXVMD 使用标准Python异常进行错误处理：

| 异常类型 | 说明 |
|----------|------|
| `FileNotFoundError` | 文件不存在 |
| `ValueError` | 文件格式无效或数据错误 |
| `IOError` | 文件读写错误 |
| `AssertionError` | 数据验证失败 |

```python
import pypmxvmd

try:
    model = pypmxvmd.load_pmx("nonexistent.pmx")
except FileNotFoundError:
    print("文件不存在")
except ValueError as e:
    print(f"文件格式错误: {e}")
```

---

## 兼容性说明

- **VMD**: 支持旧版(v1)和新版(v2)格式
- **PMX**: 支持2.0和2.1版本
- **VPD**: 支持标准VPD文本格式
- **编码**: VMD使用Shift-JIS，PMX支持UTF-16LE和UTF-8，VPD使用Shift-JIS

---

## 许可证

MIT License
