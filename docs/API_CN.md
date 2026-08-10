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
uv add pypmxvmd
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

#### `pypmxvmd.load(file_path, more_info=False, *, mode=None, implementation="auto", strict_eof=None, track_spans=False)`

自动检测文件类型并加载。

**参数**:
- `file_path` (str | Path): 文件路径
- `more_info` (bool): 是否显示详细解析信息
- `mode`、`implementation`、`strict_eof`、`track_spans`: 仅用于 PMX

**返回**: `VmdMotion` | `PmxModel` | `PmxParseResult` | `VpdPose`

**异常**: `ValueError` - 不支持的文件类型

```python
data = pypmxvmd.load("model.pmx")
```

---

#### `pypmxvmd.save(data, file_path, *, mode=None)`

自动检测数据类型并保存。

**参数**:
- `data`: `VmdMotion` | `PmxModel` | `VpdPose` 对象
- `file_path` (str | Path): 输出文件路径
- `mode`: 仅用于 PMX，默认 `canonical`

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

#### `pypmxvmd.load_pmx(file_path, more_info=False, *, mode="strict", implementation="auto", strict_eof=None, track_spans=False)`

`mode="strict"` 返回完整 `PmxModel` 并固定要求精确 EOF；`mode="partial"` 返回
`PmxParseResult`，调用方可再设置 `strict_eof=True` 要求结果必须完整。`implementation`
可选 `auto`、`python`、`fast`、`cython`。`mode="document"` 或 `track_spans=True`
返回带源字节和字段 span 的 `PmxDocument`；partial 模式会填充
`PmxParseResult.field_spans`。

PMX 2.0 会完整解析到 Spring 6DOF Joint；PMX 2.1 进一步支持 QDEF、Flip/Impulse Morph、
六种 Joint 和包含 Anchor/Pin 集合的完整 Soft Body record。未知枚举、非法计数/引用、
截断和尾部字节均 fail closed。

**参数**:
- `file_path` (str | Path): PMX文件路径
- `more_info` (bool): 是否显示详细解析信息

**返回**: `PmxModel` 对象

```python
try:
    model = pypmxvmd.load_pmx("character.pmx")
except pypmxvmd.IncompletePmxError as error:
    print(error.report.missing_sections)

result = pypmxvmd.load_pmx("character.pmx", mode="partial")
document = pypmxvmd.load_pmx("character.pmx", mode="document")
```

---

#### `pypmxvmd.load_pmx_partial(file_path, more_info=False, implementation="auto", *, track_spans=False) -> PmxParseResult`

显式调用 `python`、`fast` 或 `cython` 读取能力。返回对象包含 `model` 和
不可变的 `report`；报告记录已加载/缺失 section、各 section 字节范围、最终偏移、文件
总长度和尾部未消费字节数。受支持的 PMX 2.0/2.1 均可返回 `is_complete=True`。`auto`
使用带边界与资源上限检查的 Python Cursor。原生 ABI 补全前，显式 `cython` 返回 Cursor
的 canonical 语义模型；PMX 2.1 不进入尚未完整的原生 parser。该兼容入口等价于
`load_pmx(..., mode="partial")`。
传入 `track_spans=True` 时，`field_spans` 保存已登记的定长字段，`record_spans`
保存现有 Vertex、Face、Material、Bone、Morph、Display Frame、Rigid Body 和 Joint
record 的精确字节范围。

---

#### `pypmxvmd.load_pmx_document(file_path, more_info=False, *, implementation="auto", track_spans=True) -> PmxDocument`

严格读取一次不可变源字节快照，并返回 canonical model、完整性报告、section 证据、字段
span 和现有 Vertex/Face/Material/Bone/Morph/Display Frame/Rigid Body/Joint record 的精确
span。Material、Bone、Rigid Body、Joint
record 中
可直接映射的部分定长数值、枚举、flags、索引和向量字段已登记；四类 record span
另用于下文 W11a-W11d 事务，新增的四类 span 作为 W12 源证据。Soft Body record
仍未登记高层编辑。

```python
document = pypmxvmd.load_pmx_document("model.pmx")
span = document.span_for("bones[0].deform_layer")
document.model.bones[0].deform_layer = 2
pypmxvmd.save_pmx(document, "patched.pmx", mode="lossless_patch")
```

lossless 写入会在落盘前验证模型、`before` 字节、边界、等长、不重叠和字段类型；随后严格
重读 patch 结果并比较整个语义模型。no-op 原样返回源字节。任何未登记修改均抛出
`PmxPatchError`，不会创建或替换目标文件。

---

#### `PmxDocument.edit_bones() -> PmxBoneEditor` / `pypmxvmd.edit_pmx_bones(document)`

创建一个隔离的 PMX 2.0 现有 Bone record 编辑事务。已支持日/英变长名称、
位置、亲骨骼、变形阶层（PMXEditor“表示先”）、旋转/移动/显示/操作/物理后 flags、
骨骼/相对两种尾端模式、旋转/移动/本地付与、固定轴、Local 轴、外部亲，以及
IK target/loop/angle/link/limit 全部条件字段。

```python
document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_bones()
editor.set_names(0, name_en="center")
editor.set_deform_layer(0, 2)
editor.set_tail_bone(0, 1)  # 或 set_tail_offset(0, [0.0, 1.0, 0.0])
editor.set_ik(
    0,
    target_index=1,
    loop_count=40,
    angle_limit=0.5,  # 弧度
    links=[pypmxvmd.ik_link(1)],
)
result = editor.write_file("bone-edited.pmx")
print(result.changed_record_count)
```

条件 flags 及其 payload 必须通过配对的 `set_*`/`clear_*` 方法修改。`encode()`
只返回已验证的 `PmxBoneEditResult`；`write_file()` 验证后原子替换目标。每个
事务从未修改的 `PmxDocument` 开始，使用源文件编码和 Bone index 宽度仅重建
变更记录，然后验证全模型、strict reparse 并比较全部语义。骨骼增删、对象替换/
重排和全局 index 重编号不在 W11a 范围，会抛出 `PmxBoneEditError`。

---

#### `PmxDocument.edit_rigid_bodies() -> PmxRigidBodyEditor` / `pypmxvmd.edit_pmx_rigid_bodies(document)`

创建一个隔离的 PMX 2.0 现有 Rigid Body record 编辑事务。已支持日/英变长名称、
关联 Bone（含合法 `-1` sentinel）、sphere/box/capsule 三形状、三种物理模式、原始
collision group/mask、size/position/rotation（旋转保持弧度），以及质量、移动阻尼、
旋转阻尼、反弹力和摩擦力。

```python
from pypmxvmd.common.pmx import RigidBodyShape

document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_rigid_bodies()
editor.set_names(0, name_en="body")
editor.set_bone(0, -1)
editor.set_shape(0, RigidBodyShape.CAPSULE)
editor.set_collision(0, collision_group=3, collision_mask=0xFFF7)
editor.set_rotation(0, [0.0, 0.25, 0.0])  # 弧度
editor.set_physical_parameters(0, mass=1.5, friction=0.6)
result = editor.write_file("rigid-body-edited.pmx")
print(result.changed_record_count)
```

`encode()` 只返回已验证的 `PmxRigidBodyEditResult`；`write_file()` 验证后原子替换
目标。事务使用源文件编码和 Bone index 宽度，仅重建变更的 Rigid Body record，随后
strict reparse 完整输出并比较全部模型语义。刚体增删、对象替换/重排和全局 index
重编号不在 W11b 范围，会抛出 `PmxRigidBodyEditError`，因此现有 Joint 刚体索引语义
保持不变。

---

#### `PmxDocument.edit_joints() -> PmxJointEditor` / `pypmxvmd.edit_pmx_joints(document)`

创建一个隔离的 PMX 2.0 Spring 6DOF Joint 现有记录编辑事务。已支持日/英变长名称、
Joint 类型、A/B 刚体引用（含合法 `-1` sentinel）、position/rotation、移动/旋转 min/max
和移动/旋转 spring。旋转与旋转弹簧始终保持 PMX 原始弧度表示。

```python
from pypmxvmd.common.pmx import JointType

document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_joints()
editor.set_names(0, name_en="spring joint")
editor.set_joint_type(0, JointType.SPRING6DOF)
editor.set_rigid_body_references(0, -1, 1)
editor.set_position_limits(0, [-1.0, -2.0, -3.0], [1.0, 2.0, 3.0])
editor.set_rotation_limits(0, [-0.5, -0.25, -0.1], [0.5, 0.25, 0.1])
editor.set_rotation_spring(0, [0.2, 0.3, 0.4])
result = editor.write_file("joint-edited.pmx")
print(result.changed_record_count)
```

`encode()` 返回已验证的 `PmxJointEditResult`；`write_file()` 验证后原子替换目标。
事务使用源文件编码和 Rigid Body index 宽度，只重建变更 Joint record，随后 strict
reparse 完整输出并比较全部模型语义。限位 setter 要求逐轴 `minimum <= maximum`；直接
修改 transaction model 也会检查新引入的倒置轴，但会保留源文件中未改动的历史倒置轴，
因此名称等无关编辑不会破坏既有模型。Joint 增删、对象替换/重排及 PMX 2.1 Joint 类型
不在 W11c 范围，会抛出 `PmxJointEditError` 或既有的未支持特性异常。

---

#### `PmxDocument.edit_materials() -> PmxMaterialEditor` / `pypmxvmd.edit_pmx_materials(document)`

创建一个隔离的 PMX 2.0 现有 Material record 编辑事务。已支持日/英变长名称与备注、
diffuse RGBA、specular RGB/strength、ambient RGB、八个描绘 flags、edge RGBA/size、
Texture 引用、Sphere 引用及四种模式、separate/shared Toon 条件布局和原始面索引数。

```python
from pypmxvmd.common.pmx import SphMode

document = pypmxvmd.load_pmx_document("model.pmx")
editor = document.edit_materials()
editor.set_names(0, name_en="skin")
editor.set_diffuse_color(0, [0.8, 0.6, 0.5, 1.0])
editor.sync_ambient_from_diffuse(0)  # 显式 S3 命令
editor.set_draw_flags(0, double_sided=True, edge_drawing=True)
editor.set_sphere_texture(0, -1, SphMode.DISABLED)
editor.set_shared_toon(0, 0)  # 内置 toon01.bmp
result = editor.write_file("material-edited.pmx")
print(result.changed_record_count)
```

`set_texture()`、`set_sphere_texture()`、`set_separate_toon()` 和
`set_shared_toon()` 会让显示路径与序列化索引同步，并检查 `-1` sentinel 和引用范围。
`set_face_counts()` 接收完整 Material count 序列，保证每项非负且为 3 的倍数、总和仍
等于模型面索引数。ambient 绝不隐式同步；只有 `sync_ambient_from_diffuse()` 会改变它。

`encode()` 返回已验证的 `PmxMaterialEditResult`；`write_file()` 验证后原子替换目标。
事务使用源文件编码和 Texture index 宽度，只重建变更的 Material record，再 strict
reparse 完整输出并比较全部模型语义。Material/纹理表增删、对象替换/重排和全局重编号
不在 W11d 范围，会抛出 `PmxMaterialEditError` 或验证异常。

---

#### W12 集合编辑：Vertex、Face、Morph、Display Frame

以下入口创建隔离的集合级事务：

- `PmxDocument.edit_vertices()` / `pypmxvmd.edit_pmx_vertices(document)`
- `PmxDocument.edit_faces()` / `pypmxvmd.edit_pmx_faces(document)`
- `PmxDocument.edit_morphs()` / `pypmxvmd.edit_pmx_morphs(document)`
- `PmxDocument.edit_frames()` / `pypmxvmd.edit_pmx_frames(document)`

`PmxVertexEditor` 支持几何、Additional UV、BDEF1/BDEF2/BDEF4/SDEF/QDEF、SDEF
三向量、edge scale 和权重 Bone index。Vertex 增删/重排会同步更新 Face、Vertex/UV
Morph、Soft Body Anchor/Pin 引用；删除还会移除依赖记录并同步 Material face count。

`PmxFaceEditor` 支持三角形修改、增删与重排。增删会维持连续 Material 面范围和
`face_count`；`remap_vertex_indices()` 可应用显式 Vertex 映射。会让 Material 范围
交错的重排会明确拒绝。

`PmxMorphEditor` 支持名称、panel 和全部 PMX 2.0 item 集合，以及 PMX 2.1
Flip/Impulse。Morph 增删/重排会更新 Group/Flip 和 Display Frame 引用；显式删除
Morph 时同时移除指向它的 item。

`PmxFrameEditor` 支持名称、item 集合和 frame 集合编辑。事务后统一验证 Bone/Morph
引用；不允许在前两个位置以外新建 special frame。

```python
document = pypmxvmd.load_pmx_document("model.pmx")

vertices = document.edit_vertices()
vertices.set_edge_scale(0, 1.5)
vertices.write_file("vertex-edited.pmx")

faces = document.edit_faces()
faces.append_face([0, 2, 3], material_index=0)
faces.write_file("face-edited.pmx")
```

`encode()` 返回对应的 `Pmx*EditResult`；`write_file()` 会集中验证、strict reparse、
比较全模型语义并原子替换目标。no-op 精确返回源字节；发生变更时 W12 使用 canonical
全模型编码，以便索引宽度安全增长，因此保证声明范围外的语义不变，但不承诺源字节或
源布局相等。非法字段、范围、引用或顺序分别抛出 `PmxVertexEditError`、
`PmxFaceEditError`、`PmxMorphEditError` 或 `PmxFrameEditError`。Soft Body record
高层编辑仍未支持。

#### `pypmxvmd.edit_pmx(source, *, output_path=None) -> PmxEditTransaction`

创建一个可组合的模型级 PMX 事务。`source` 可以是 `PmxModel`、`PmxDocument` 或
PMX 路径。事务进入时深拷贝模型；`with` 正常退出会集中验证、canonical 编码、strict
重解析并原子写入 `output_path`，块内异常会回滚且不创建或替换目标。路径输入禁止写回
同一个源文件。

```python
from pypmxvmd.common.pmx import MorphPanel

with pypmxvmd.edit_pmx("body.pmx", output_path="skirt.pmx") as tx:
    skirt_bone = tx.add_bone(name_jp="裙骨", parent_index=0)
    tx.paint_weights([120, 121, 122], skirt_bone, 0.8)
    tx.add_vertex_morph(
        name_jp="裙摆",
        offsets={120: [0.0, 0.15, 0.0]},
        panel=MorphPanel.OTHER,
        display_frame_index=1,
    )
    tx.merge_part("clothes.pmx")
```

`add_bone()`/`append_bone()` 追加骨骼并返回新索引；`bone(index)` 返回事务副本中的
既有骨骼，可在同一个 `with` 块内修改其字段，最终提交会统一验证条件字段与引用。
`set_weight()` 支持显式的
BDEF1/BDEF2/BDEF4/SDEF/QDEF 布局，QDEF 仅可用于 PMX 2.1；`paint_weights()` 和
`set_vertex_weights()` 面向顶点集合刷写骨骼权重，默认把原最强影响保留为 BDEF2 的
互补权重。`add_morph()` 接受类型化 `PmxMorph`，`add_vertex_morph()` 用顶点偏移便捷
创建表情，并可将 Morph item 加入 Display Frame，使其在 PMXEditor T 面板可见。

`merge_part()` 在打开的事务内也是原子的；即使调用方捕获异常，被拒绝的部件也不会
污染事务副本。它会维护 Vertex、Texture、Material、Bone、Morph、Rigid Body、Joint、
Soft Body、Morph item 和 Display Frame 的索引映射；骨骼按日文/英文名匹配，其余记录追加，
并返回核心索引映射。Display Frame 默认合并；只有确认部件没有 frame 时才应传
`include_frames=False`。版本不兼容、非法引用或无法安全合并的结构会抛出
`PmxTransactionError`，不会静默丢弃数据。

`remove_part()`/`remove_materials()` 删除按材质定义的一个或多个部件，
`replace_part()`/`replace()` 则先删除再原子执行 `merge_part()`：

```python
with pypmxvmd.edit_pmx("body.pmx", output_path="result.pmx") as tx:
    tx.replace_part(
        "new_clothes.pmx",
        material_names=["旧衣"],
        compact_vertices=True,
    )
```

PMX 没有显式的 Part 记录，因此边界采用每个 Material 连续的 face 范围。默认保留
孤立顶点、骨骼和纹理；指定 `compact_vertices=True` 时，只删除完全由被删 face 使用的
顶点并重编号受影响引用。如果 Morph 或 Soft Body 仍引用这些资源，会抛出
`PmxTransactionError`，不会静默丢失数据。这些操作使用 canonical 全模型事务，不保证源字节或布局无损。

---

#### `PmxModel.validate()` / `validate_pmx_model(model, *, limits=..., strict_eof=True)`

集中验证 PMX 语义且不依赖 `assert`。当前覆盖 PMX 2.0 权重布局、条件字段、跨 section
引用、Bone parent/inherit cycle、有限数值、资源上限以及 parse report 的 count/EOF
一致性。失败时抛出 `PmxValidationError`，并提供稳定的 `field`、`expected`、`actual`。

```python
from pypmxvmd.common.pmx import PmxLimits, validate_pmx_model

model.validate()  # 有 parse_report 时默认要求 strict EOF
validate_pmx_model(
    model,
    limits=PmxLimits(max_count=2_000_000),
    strict_eof=False,  # 仅诊断 partial 模型，报告和尾部字节仍保留
)
```

`strict_eof=False` 不会把 partial 结果标成完整，也不会丢弃 trailing bytes。PMX 2.1
QDEF、Flip/Impulse Morph、全部 Joint 和 Soft Body 已纳入集中语义验证契约。

---

#### `pypmxvmd.save_pmx(model_or_document, file_path, *, mode="canonical")`

验证并原子保存 canonical PMX 2.0/2.1 文件。writer 覆盖各版本要求的全部 section 至
Joint/Soft Body，自动选择可容纳模型的最小索引宽度，并保持纹理列表和索引顺序。无效、
不完整、未知 feature 或跨引用非法的输入会在替换目标文件前明确失败。

canonical 输出保证语义 round-trip 稳定，不承诺与源文件逐字节或原布局相同。
`PmxParser.write_file_partial()` 仍只是显式、有损的 fixture 工具，并拒绝它无法编码的集合。
`write_pmx()` 是等价的显式 writer 名称。传入 `PmxDocument` 并指定
`mode="lossless_patch"` 可执行经过审计的定长字段更新。`preserve_layout` 仍未支持；没有
document 却请求 lossless mode 时抛出 `UnsupportedPmxFeatureError`。未知模式名抛出
`ValueError`。所有失败均发生在替换目标文件之前。

**参数**:
- `model` (PmxModel): PMX模型对象
- `file_path` (str | Path): 输出文件路径

```python
pypmxvmd.save_pmx(model, "output.pmx")
```

| 操作 | 当前可用 | 结果 |
|---|---|---|
| 读取 `strict` | 是 | 完整 PMX 2.0 `PmxModel`，否则 fail closed |
| 读取 `partial` | 是 | 带完整性报告的 `PmxParseResult` |
| 读取 `document` / span | 是（PMX 2.0/2.1） | `PmxDocument`、定长字段和八类 record span |
| 写入 `canonical` | 是 | 原子生成语义稳定的 PMX 2.0/2.1 |
| 写入定长字段 `lossless_patch` | 是 | 经审计的原子源字节 patch |
| 编辑现有 Bone record | 是（PMX 2.0） | 事务化变长 record 替换 |
| 编辑现有 Rigid Body record | 是（PMX 2.0） | 事务化变长 record 替换 |
| 编辑现有 Joint record | 是（PMX 2.0 Spring 6DOF） | 事务化变长 record 替换 |
| 编辑现有 Material record | 是（PMX 2.0） | 事务化变长 record 替换 |
| 编辑 Vertex/Face/Morph/Display Frame 集合 | 是 | canonical W12 事务与引用重编号 |
| 组合部件/骨骼/权重/Morph 编辑 | 是 | 模型级 `with` 事务与原子 canonical 提交 |
| 删除/替换按材质定义的部件 | 是 | 按 face 范围删除，可选压缩独占顶点 |
| 写入 `preserve_layout` | 否 | fail closed |

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

公共 reader 已填充 PMX 2.0 至 Joint、PMX 2.1 至 Soft Body 的全部 section。必须通过
`parse_report`/`is_complete` 区分完整读取和显式 partial 诊断结果。

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
| `parse_report` | `PmxParseReport | None` | 解析完整性证据 |
| `is_complete` | `bool` | 是否加载全部必需 section 并到达 EOF |
| `loaded_sections` | `frozenset[str]` | 实际已加载 section |

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
| `encoding` | `PmxTextEncoding` | UTF-16LE/UTF-8 布局标志 |
| `additional_uv_count` | `int` | 附加 UV 数量 (0–4) |
| `*_index_size` | `int` | 六类 PMX 索引宽度 (1、2、4) |
| `global_flags` | `bytes` | 当前规范化 8 字节布局 |
| `raw_global_flags` | `bytes` | 原始 8 字节审计值 |

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
| `sdef_c` | `List[float] \| None` | 原始 SDEF C 向量 |
| `sdef_r0` | `List[float] \| None` | 原始 SDEF R0 向量 |
| `sdef_r1` | `List[float] \| None` | 原始 SDEF R1 向量 |
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
| `texture_index` | `int` | 原始纹理表索引 |
| `sphere_path` | `str` | 球面纹理路径 |
| `sphere_texture_index` | `int` | 原始球面纹理索引 |
| `sphere_mode` | `SphMode` | 球面纹理模式 |
| `toon_path` | `str` | 卡通渲染纹理路径 |
| `toon_sharing` | `ToonSharing` | 独立/共享 Toon 布局 |
| `toon_texture_index` | `int` | 原始纹理或共享 Toon 索引 |
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
| `tail_bone_index` | `int \| None` | “表示先：骨骼”的类型化视图 |
| `tail_offset` | `List[float] \| None` | “表示先：相对”的类型化视图 |
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

`BoneFlags` 暴露全部已定义的 PMX 2.x 位。其中 `inherit_local` 对应 `0x0080`
“本地付与”，`local_append` 是兼容别名；未定义位继续保留在原始 `value` 中。

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
| `items` | `List` | Group/Vertex/Bone/UV/Material/Flip/Impulse 类型化项目 |

Bone Morph 旋转以原始 `[x, y, z, w]` 四元数保存；Material Morph 保留乘算/加算操作以及
扩散、反射、环境、边缘和三类纹理系数。Flip 保留 Morph 索引/权重；Impulse 保留刚体
索引、local 标志、速度和扭矩。

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
| `collision_group` | `int` | PMX 原始 group (0–15) |
| `collision_mask` | `int` | PMX 原始 uint16 碰撞 mask |
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
| `rigid_body_a_index` | `int` | 刚体 A 清晰别名 |
| `rigid_body_b_index` | `int` | 刚体 B 清晰别名 |
| `position` | `List[float]` | 位置 |
| `rotation` | `List[float]` | 旋转 |
| `position_min` | `List[float]` | 位置最小值 |
| `position_max` | `List[float]` | 位置最大值 |
| `rotation_min` | `List[float]` | 旋转最小值 |
| `rotation_max` | `List[float]` | 旋转最大值 |
| `position_spring` | `List[float]` | 位置弹簧 |
| `rotation_spring` | `List[float]` | 旋转弹簧 |

---

#### `PmxSoftBody`

PMX 2.1 Soft Body 暴露名称、`shape`、材质引用、碰撞 group/mask、`flags`、B-link 距离、
cluster 数、质量、碰撞 margin、空气动力模型，以及类型化 `config`、`cluster`、`iteration`、
`material` 系数记录。`anchors` 保存 `PmxSoftBodyAnchor`，`pin_vertex_indices` 保存无符号
顶点引用。所有嵌套计数、枚举/flags、有限 float32 和材质/刚体/顶点引用均集中验证。

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
| `SIX_DOF` (1) | 6DOF |
| `POINT_TO_POINT` (2) | 点连接 |
| `CONE_TWIST` (3) | 圆锥扭转 |
| `SLIDER` (4) | 轴移动 |
| `HINGE` (5) | 铰链 |

---

#### `SoftBodyShape`、`SoftBodyFlags`、`SoftBodyAeroModel`

- 形状：`TRI_MESH` (0)、`ROPE` (1)。
- Flags：`B_LINK` (1)、`CLUSTER` (2)、`LINK_CROSS` (4)，其他位拒绝。
- 空气动力模型：`V_POINT` (0)、`V_TWO_SIDED` (1)、`V_ONE_SIDED` (2)、
  `F_TWO_SIDED` (3)、`F_ONE_SIDED` (4)。

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

### 示例2: 创建并验证内存中的简单 PMX 模型

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

# 当前可验证内存模型；canonical writer 完成前不会输出完整 PMX
model.validate()
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

# 显式加载当前支持的 section
model = pypmxvmd.load_pmx_partial("model.pmx").model

# 验证数据完整性
try:
    model.validate()
    print("模型数据验证通过")
except pypmxvmd.PmxValidationError as e:
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
| `IncompletePmxError` | 完整 PMX 读取尚未到达全部 section/EOF |
| `IncompletePmxWriterError` | 显式 legacy partial writer 会丢弃未支持 section，因而拒绝写入 |
| `PmxValidationError` | 字段验证失败，包含 `field`、`expected`、`actual` |
| `PmxPatchError` | lossless patch 的路径/类型/范围/before/重读/语义检查失败 |
| `PmxBoneEditError` | 骨骼编辑事务违反字段、布局、引用或集合安全契约 |
| `PmxVertexEditError` | Vertex 事务违反字段、引用重编号或编辑范围契约 |
| `PmxFaceEditError` | Face 事务违反拓扑或 Material 连续范围约束 |
| `PmxMorphEditError` | Morph 事务违反 item、类型、引用或编辑范围约束 |
| `PmxFrameEditError` | Display Frame 事务违反 item 引用或 special frame 约束 |
| `PmxTransactionError` | 组合模型事务在验证、重映射、strict 重解析或原子提交时失败 |
| `UnsupportedPmxFeatureError` | 已识别的 PMX 版本/模式尚未实现，包含 `feature`、`available` |

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
