# PMXEditor 功能支持调研与编辑优先级

> 调研日期：2026-07-30
>
> 状态：长期路线已确认；PMX 2.0 canonical 读写、validator、
> PmxDocument/lossless patch、W11a 骨骼和 W11b 刚体安全编辑已完成；下一步为 W11c Joint 编辑

本文以 PMXEditor 的材质、骨骼、刚体、Joint 和 SoftBody 页面为参照，定义
PyPMXVMD 未来“可编辑支持”的边界和交付顺序。格式完整性与二进制架构见
[PMX 支持改进计划](PMX支持改进计划.md)，重构工作包见
[PMX 完整支持重构执行计划](PMX完整支持重构执行计划.md)。

## 1. 结论

当前 PyPMXVMD **不具备全面且安全的 PMX 编辑能力**。

- 公共 `load_pmx()` 已完整读取 PMX 2.0 至 Spring 6DOF Joint/EOF；PMX 2.1 的
  Flip/Impulse、其他 Joint 与 Soft Body 仍明确失败。
- 公共 `save_pmx()` 已完整 canonical 写出 PMX 2.0 Header 至 Spring 6DOF Joint；旧
  serializer 只保留为受限 fixture 工具，不能用于用户模型。
- 活动 Python reader 已使用 little-endian、bounds-checked Cursor；备用 Nuthouse 的直接
  `struct` 格式也已消除 native alignment，但其 Morph/Soft Body/writer 仍不完整。
- PMX 2.0 的 Vertex/SDEF、Material、Bone/IK、全部 Morph、Display Frame、Rigid Body 和
  Spring 6DOF Joint 已完成 canonical 读写与集中验证。
- W11a/W11b 已公开现有 Bone/Rigid Body record 的事务化 S2 编辑；Joint、材质和
  Soft Body 页面仍未达到 S2。

因此当前不能承诺全面 PMXEditor 编辑；只有现有骨骼和刚体记录已达到本文定义的 S2。

| 页面/范围 | 当前读取 | 当前编辑结论 |
|---|---|---|
| 骨骼 | PMX 2.0 S0/S1 字段已 canonical 读写，含“表示先”和 IK | W11a 已达 S2；可重建现有 record，不可增删/重排骨骼 |
| 刚体 | 三形状、三模式、group/mask 与物理参数已 canonical 读写 | W11b 已达 S2；可重建现有 record，不可增删/重排刚体 |
| Joint | Spring 6DOF 全向量按原始弧度 canonical 读写 | 尚无事务化编辑 API，未达到 S2 |
| 材质 | 全序列化字段已读取 | “同步扩散-环境”仍是未来 S3 命令 |
| Soft Body/PMX 2.1 | 未实现，明确 fail closed | 长期计划 |

## 2. “支持”的四个层级

后续文档和代码使用以下定义，避免把“能显示”或“类里有字段”当成“能编辑”：

| 层级 | 名称 | 要求 |
|---|---|---|
| S0 | 结构遍历 | 严格消费 record、保持正确 offset，并保留 section bytes/span；不开放编辑。 |
| S1 | 语义读取 | 模型完整表达字段、enum 与引用，可通过 validator。 |
| S2 | 安全编辑 | `read -> modify -> write -> read` 后只出现白名单语义变化，其他 section 完整保留。 |
| S3 | 编辑器便捷操作 | 显式提供高层命令；读取或保存绝不隐式修改文件语义。 |

PMXEditor 的一个控件只有达到 S2 才能称为“可编辑”；例如一条“同步”按钮属于 S3，
它不是 PMX 文件里的额外字段。

## 3. 页面字段映射

### 3.1 骨骼：第一优先级

骨骼页面需要完整支持下列字段和操作：

| PMXEditor 控件 | PMX 语义字段 | 目标 |
|---|---|---|
| 骨骼名、英名 | `name_jp`、`name_en` | W11a S2 已完成，支持变长字符串 |
| 变形阶层、物理后 | `deform_layer`、`deform_after_phys` flag | W11a S2 已完成 |
| 位置 | `position[3]` | W11a S2 已完成 |
| 性能：旋转、移动、IK、显示、操作 | `rotateable`、`translateable`、`ik`、`visible`、`enabled` flags | W11a S2 已完成 |
| 亲骨骼 | `parent_index` | W11a S2 已完成，验证 cycle 与范围 |
| 表示先：骨骼 | `tail_usebonelink=True` + tail bone index | W11a S2/S3 已完成：`set_tail_bone()` |
| 表示先：相对 | `tail_usebonelink=False` + relative `vec3` | W11a S2/S3 已完成：`set_tail_offset()` |
| 付与旋转、付与移动、付与率、付与亲 | inherit flags、`inherit_parent_index`、`inherit_ratio` | W11a S2 已完成 |
| 轴限制 | fixed-axis flag、`fixed_axis` | W11a S2 已完成 |
| Local 轴 | local-axis flag、`local_axis_x`、`local_axis_z` | W11a S2 已完成 |
| 外部亲、亲 Key | external-parent flag、`external_parent_index` | W11a S2 已完成 |
| IK Target、Loop、单位角、Link、角度限制 | IK flag、target、loop、angle、links/limits | W11a S2 已完成，条件与引用集中验证 |

#### “表示先”能否修改

当前已能修改，并支持截图中的两种模式：

- **骨骼模式**：显示尾端引用另一个骨骼。文件中写入一个随 Header 指定宽度变化的 bone index。
- **相对模式**：显示尾端写为相对本骨位置的三个 `float32` 偏移量。

W11a 通过记录级 span 重编码整个 Bone record，因此能安全处理两种模式的
长度变化；输出后会 strict reparse 并比较全模型语义。当前仍限制为不增加、删除、
替换或重排骨骼对象；集合增删与全局 index 重编号另开子阶段。

### 3.2 刚体：第二优先级

刚体页面需要完整支持：

| PMXEditor 控件 | PMX 语义字段 | 目标 |
|---|---|---|
| 刚体名、英名 | `name_jp`、`name_en` | W11b S2 已完成，支持变长字符串 |
| 关联骨骼 | `bone_index`，包括合法的无骨骼 sentinel | W11b S2 已完成 |
| 刚体类型 | bone-follow / physics / physics+bone 的 mode enum | W11b S2 已完成 |
| 形状 | sphere / box / capsule enum | W11b S2 已完成 |
| 尺寸、位置、旋转 | `size`、`position`、`rotation` | W11b S2 已完成，旋转保留原始弧度 |
| group | 4-bit group 值 | W11b S2 已完成 |
| 非冲突 group | 16-bit collision mask，UI 的 16 个复选框 | W11b S2 已完成，保留原始 mask |
| 质量、移动阻尼、旋转阻尼、反发力、摩擦力 | 五个物理参数 | W11b S2 已完成 |

进入刚体编辑前，必须先完成骨骼引用验证。修改或删除骨骼时必须明确阻止、重绑定或同时
更新引用，不能留下悬空 `bone_index`。刚体阶段还必须保证现有 Joint 的刚体索引不被破坏。

W11b 通过 `PmxRigidBodyEditor` 在隔离副本中修改现有记录，并使用精确 record span
重建变长日/英名及全部刚体字段。事务在落盘前集中验证骨骼/Joint 引用，strict reparse
并比较全模型语义；刚体集合增删、对象替换/重排和全局 index 重编号仍 fail closed。

### 3.3 Joint：第三优先级

PMX 2.0 阶段先完整支持 Spring 6DOF Joint：

| PMXEditor 控件 | PMX 语义字段 | 目标 |
|---|---|---|
| Joint 名、英名 | `name_jp`、`name_en` | S2 |
| Joint 类型 | PMX 2.0 的 `SPRING6DOF` | S2 |
| 连接刚体 A/B | 两个 rigidbody index | S2 |
| 位置/旋转 | `position`、`rotation` | S2 |
| 移动限制与旋转限制 | min/max vectors | S2 |
| 移动弹簧、旋转弹簧 | spring vectors | S2 |
| “骨骼位置设定”等按钮 | 根据关联刚体/骨骼计算值的显式编辑命令 | S3，算法和异常条件必须单独定义 |

canonical reader/writer 已把 Joint 旋转、旋转限制和旋转弹簧按 PMX 原始
`float32`/弧度保存，不做角度转换。高层命令必须沿用这一契约，避免二次转换和精度漂移。
PMX 2.1 的其他 Joint 类型不混入本阶段，随 PMX 2.1 长期路线处理。

### 3.4 材质：第四优先级

材质页面需要支持全部序列化字段：

| PMXEditor 控件 | PMX 语义字段 | 目标 |
|---|---|---|
| 名称、英名、面数 | `name_jp`、`name_en`、`face_count` | S2，校验所有材质面数总和 |
| 漫反射色与非透明率 | `diffuse_color[RGBA]` | S2 |
| 反射色、反射强度 | `specular_color`、`specular_strength` | S2 |
| 环境色 | `ambient_color[RGB]` | S2 |
| 描绘 flags | 双面、地面影、阴影、边缘、顶点色、线绘制等 bit flags | S2 |
| 轮郭线 | `edge_color`、`edge_size` | S2 |
| Tex、Sphere、Toon | texture index、sphere index/mode、shared/external Toon mode/index | S2，不重排纹理表 |
| 备注 | material comment | S2 |

“同步扩散-环境”不是 PMX 的字段或 flag。它应实现为显式操作：

```python
material.ambient_color = material.diffuse_color[:3]
```

该命令只能在用户调用时执行，读取和普通保存时不能自动同步；否则会改变原模型的视觉语义。
材质高层编辑排在 Joint 之后，但 reader/writer 仍必须更早完整消费 Material section，
因为它位于 Bone 前面。

### 3.5 Soft Body 与其他 PMX 2.1：长期计划

Soft Body 页面及所有 PMX 2.1 特有内容明确进入长期路线，不在骨骼/刚体/Joint/材质阶段
实现。完整 Soft Body 范围包括：

- shape（TriMesh/Rope）、关联材质、group、非碰撞 mask、flags。
- BLink distance、cluster count、总质量、collision margin、aero model。
- Config 的全部物理系数、Cluster 系数、Iteration 参数和 Material 参数。
- Anchor（rigid body、vertex、near）和 Pin vertex 列表。
- PMX 2.1 的 Flip Morph、Impulse Morph、其他 Joint 类型和所有版本条件字段。

在这一阶段之前，strict reader 遇到包含未支持 PMX 2.1 可变长 record 的文件必须抛出
带 section/offset 的 `UnsupportedPmxFeatureError`；writer 绝不能静默删除 Soft Body。

### 3.6 顶点、面、Morph、表示枠：长期编辑计划

顶点、面、表情变换（Morph）与表示枠的高层编辑不在初始四阶段实现。它们仍须先达到 S0，
因为 PMX 是顺序的可变长格式：

```text
Header -> Vertex -> Face -> Texture -> Material -> Bone -> Morph
       -> Display Frame -> Rigid Body -> Joint -> Soft Body
```

若没有正确消费 Vertex/Face/Material/Morph/Display Frame，就无法定位刚体或 Joint，也无法
证明编辑骨骼后没有损坏中间 section。早期应采用“结构解析 + 原始 section/span 保留”的
实现；这不是对这些页面开放编辑能力。

长期编辑阶段分别覆盖：

- Vertex：Additional UV 0-4、BDEF1/BDEF2/BDEF4/SDEF/QDEF、edge scale。
- Face：index 与材质 face count 联动、拓扑修改的引用/重编号策略。
- Morph：Group、Vertex、Bone quaternion、UV、Material、Flip、Impulse 的 item 编辑。
- Display Frame：名称、special flag、bone/morph item 的增删与重排。

## 4. 最终交付顺序

编辑功能的发布顺序固定如下：

1. `[已完成]` PMX 2.0 结构/语义读取基座：little-endian Cursor、EOF、count limits、
   完整性报告、全部 section 和 partial 模型拒写。
2. `[W11a 已完成]` 现有骨骼 record 的 S2/S3：包含“表示先”两种形式和全部
   PMX 2.0 IK/付与/轴/外部亲字段；集合增删/重排未开放。
3. `[W11b 已完成]` 刚体 S1/S2：包含完整 collision mask 与骨骼/Joint 引用保护。
4. `[W11c 下一步]` PMX 2.0 Joint S1/S2/S3：包含 Spring 6DOF 全字段与单位一致性。
5. 材质 S1/S2/S3：包含全部纹理/Toon 布局及“同步扩散-环境”显式命令。
6. PMX 2.1 / Soft Body：完整字段、Anchor/Pin、PMX 2.1 Morph/Joint。
7. 顶点、面、Morph、表示枠的高层编辑。
8. fast Python/Cython parity 与无损 patch 扩展，且只能在标准 Python 正确性证明之后进行。

第 1 步不是用户可见的编辑器页面，但它是其余所有步骤的数据安全前置条件。第 2-5 步
均只操作临时输出；每一阶段完成前不得覆盖真实模型原件。

## 5. 每阶段统一验收

每个页面达到“可编辑”前，必须同时满足：

1. 所有可见控件都有明确的模型字段或显式 S3 操作定义。
2. 合成 fixture 覆盖每个条件字段、index size、sentinel 和错误分支。
3. `read -> modify -> write -> read` 全字段比较只出现预期的白名单变化。
4. 真实 corpus 只对 `tmp_path` 副本运行，原件 hash 在测试前后相同。
5. 所有跨引用通过 validator：Bone、Rigid Body、Joint、Morph、Frame、Soft Body 均无悬空索引。
6. 输出文件由 strict reader 完整解析到 EOF；未支持 feature 一律 fail closed。

在这些门槛完成前，项目文档应写明“未支持编辑”或“只读结构遍历”，不得依据 UI 截图或
模型类字段宣称已支持对应 PMXEditor 页面。
