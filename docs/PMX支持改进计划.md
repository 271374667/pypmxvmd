# PyPMXVMD 的 PMX 支持改进计划

## 1. 文档目的

本文记录 PyPMXVMD 当前 PMX 实现中需要修复和补全的部分，并给出分阶段实施顺序、测试矩阵与验收标准。

目标分为两层：

1. **完整、可靠地读写 PMX 2.0/2.1**：任何公共 API 都不能静默返回不完整模型或输出截断文件。
2. **支持可审计的无损修改**：允许上层工具只修改指定字段，并证明其他二进制内容没有发生变化。

第二层主要服务于 PmxPhysicsRebuilder 一类模型修复工具，但建议设计为 PyPMXVMD 的通用能力。

## 2. 审查范围与结论

审查基于提交：

- Commit：`dc4d6cb677e3d68c8bce1abd3b7d71b0d045644c`
- Commit date：`2026-01-23`

> 2026-08-09 状态更新：以下问题清单保留原始审计证据。W0/W1 已完成：公共 PMX
> 读写现已 fail closed，显式 partial API 返回完整性报告；活动 Python reader 已迁移到
> bounds-checked little-endian `PmxCursor`，所有直接 PMX `struct` 调用已有静态防回归，
> `auto` 不再默认进入未完成的 Cython reader。活动 Cursor reader 现已完整消费 PMX 2.0
> 至 Spring 6DOF Joint/EOF；W4 集中式 Validator 已覆盖 PMX 2.0 条件字段、跨引用、
> cycle、资源限制和 strict EOF。PMX 2.1 的 Flip/Impulse、其他 Joint 和 Soft Body 仍
> fail closed。W5 canonical writer、W7 公共 API 迁移、W9 定长 lossless patch 和
> W11a 骨骼安全编辑已完成；下一阶段为 W11b 刚体编辑。

总体结论：

- PMX 2.0 数据模型和 canonical reader 已覆盖 Header 至 Spring 6DOF Joint 的全部 section。
- 审计时公共 `load_pmx()` 默认走 fast/Cython 路径且只解析到材质段；现已改为 PMX 2.0
  完整到 EOF，PMX 2.1 未支持内容明确失败。
- 审计时公共 `save_pmx()` 只写到材质段；现已替换为完整 PMX 2.0 canonical writer，
  写前验证并原子替换目标，未支持内容 fail closed。
- 备用 Nuthouse parser/writer 覆盖范围较大，但存在二进制对齐、Morph 类型缺失和 PMX 2.1 Soft Body 未实现等问题。
- 当前 7 个真实 PMX 2.0 已覆盖 strict 解析、canonical 写回、严格重读和深度语义
  round-trip；也已覆盖 document no-op 逐字节写出，原件哈希不变。变长和集合编辑仍未开放。

因此，在以下问题修复前，PyPMXVMD 不应把公共 PMX API 标记为“完整 PMX 读写支持”。

## 3. 已确认问题

### 3.1 公共 reader 静默返回不完整模型

`PmxParser.parse_file()` 调用 `parse_file_cython()`：

1. Cython 可用时，Cython parser 只解析 Header、Vertex、Face、Texture、Material。
2. Cython 不可用时，`parse_file_fast()` 同样只解析到 Material。
3. fast parser 正常返回，因此不会进入 Nuthouse fallback。

最终公共 `load_pmx()` 返回的以下部分为空：

- `bones`
- `morphs`
- `frames`
- `rigidbodies`
- `joints`
- `softbodies`

真实模型实测：

- 文件：`千咲Ver1.01_C.pmx`
- 顶点：`104883`
- 面：`173656`
- 材质：`51`
- 骨骼、Morph、刚体、关节：全部为 `0`

这类行为比直接抛出 `NotImplementedError` 更危险，因为调用方无法判断模型是否完整。

> 当前修复状态（2026-08-09）：公共 `load_pmx()` 已可完整返回到 EOF 的 PMX 2.0；
> Cursor reader 保存 Additional UV、SDEF、全部 PMX 2.0 Morph、表示枠、刚体和 Spring
> 6DOF Joint。PMX 2.1 未支持内容仍明确失败。canonical writer 已在 W5 完成，但页面级
> 编辑仍未开放。

### 3.2 公共 writer 会生成截断或破坏性输出

当前 `PmxParser.write_file()` 只编码：

- Header
- Vertex
- Face
- Texture
- Material

没有写入：

- Bone count 和 Bone
- Morph count 和 Morph
- Display frame count 和 Display frame
- Rigid body count 和 Rigid body
- Joint count 和 Joint
- Soft body count 和 Soft body

同时还存在以下破坏性简化：

- Header 中附加 UV 数量固定为 `0`。
- 所有顶点权重固定写成 `BDEF1`。
- 所有顶点固定绑定到骨骼索引 `0`。
- 多类索引大小被固定，而不是根据原始布局或完整模型计算。
- 纹理列表会重新去重和排序，无法保证原始索引布局。

> 当前修复状态（2026-08-09）：上述行为只保留在显式 `write_file_partial()` fixture
> 工具中。公共 `save_pmx()` 已使用完整 PMX 2.0 canonical writer；写前集中验证、保持
> 纹理列表/索引顺序、自动选择索引宽度，并在编码成功后原子替换目标。

### 3.3 二进制格式没有统一强制 little-endian、standard size、no padding

PMX 使用 little-endian 紧凑二进制布局。Python `struct` 格式应统一以 `<` 开头。

当前部分实现使用如下格式：

```python
struct.Struct("3f B 5f h")
struct.pack("b b i", ...)
struct.pack("b i", ...)
```

没有 `<` 时，Python 使用 native byte order、native size 和 native alignment。以当前平台为例：

| Format | Native size | PMX expected size |
|---|---:|---:|
| `3f B 5f h` | 38 | 35 |
| `b b i` | 8 | 6 |
| `b i` | 8 | 5 |

这会从第一个包含 padding 的记录开始造成整体错位。真实模型的 Nuthouse parser 已经可以在 Material 段复现此问题。

建议：

- 所有 `struct.Struct`、`pack`、`unpack`、`unpack_from` 统一使用 `<`。
- 在公共 IO 层拒绝未声明前缀的格式，避免新代码再次引入 native alignment。
- 对每种 PMX record 编写固定长度断言测试。

### 3.4 fast、Python、Cython parser 的覆盖范围不一致

当前多个 parser 路径没有共享统一的完整语义：

- `_parse_file_python()` 是部分 parser。
- `parse_file_fast()` 是部分 parser。
- `parse_pmx_cython()` 是部分 parser。
- `PmxParserNuthouse` 试图解析完整文件，但实现和模型并不完整。

建议先建立一个 correctness-first 的纯 Python parser 作为唯一标准实现，再优化 fast/Cython。

fast/Cython 路径只有在满足以下条件后才能作为默认路径：

- 解析所有 PMX section。
- 严格检查边界和 EOF。
- 与标准 Python parser 做所有字段的深度语义比较。
- 在异常、截断和恶意 count 输入下安全失败。

如果暂时只需要几何数据，应公开为明确的部分读取 API，例如：

```python
load_pmx_geometry(path)
load_pmx(path, sections={"header", "vertices", "faces", "materials"})
```

部分读取结果必须带有显式状态，例如：

```python
model.is_complete is False
model.loaded_sections == {...}
```

不能让部分模型伪装成完整 `PmxModel`。

### 3.5 PMX Header 没有保存完整布局信息

当前 `PmxHeader` 主要保存版本、名称和注释，没有完整保存：

- 文本编码：UTF-16LE / UTF-8。
- 附加 UV 数量。
- Vertex index size。
- Texture index size。
- Material index size。
- Bone index size。
- Morph index size。
- Rigid body index size。
- 原始 global flags 数量及未知 flags。

完整 reader/writer 应保存这些字段。writer 应支持：

- `preserve_layout=True`：保留原始 encoding 和 index size。
- `optimize_layout=True`：显式要求时才重新选择 index size。

### 3.6 Morph 实现不完整

枚举声明了以下 Morph 类型：

- Group
- Vertex
- Bone
- UV
- Extended UV 1–4
- Material
- Flip
- Impulse

当前备用 parser/writer 实际只实现：

- Group
- Vertex
- Bone

其余类型不只是“被忽略”，而是没有消费对应的二进制 record，导致下一字段立即错位。

需要补全：

- `PmxMorphItemUv`
- `PmxMorphItemMaterial`
- `PmxMorphItemFlip`
- `PmxMorphItemImpulse`
- 对应 parser、writer、validator 和 round-trip tests

Bone Morph 的旋转建议直接保存原始 quaternion。不要在 reader 中强制转换为 Euler，再在 writer 中转换回 quaternion，否则可能产生：

- 精度变化。
- 欧拉角多解导致的表示变化。
- 万向锁附近的不稳定。
- 无操作 read/write 也发生二进制变化。

可另外提供计算属性，把 quaternion 转换成 Euler 供 UI 使用。

### 3.7 PMX 2.1 支持不完整

当前 `PmxSoftBody` 是空类，parser/writer 中也没有实现 Soft Body record。

需要实现：

- Soft Body 基础属性。
- Config。
- Cluster。
- Iteration。
- Material。
- Anchor。
- Pin vertex。
- 所有索引和数量校验。

PMX 2.1 的 Joint 类型也需要补全，不能只支持 `SPRING6DOF = 0`。

如果短期不准备支持 PMX 2.1，应：

- 对带 Soft Body 的 PMX 2.1 明确抛出 `UnsupportedPmxFeatureError`。
- 禁止 writer 静默删除 Soft Body。
- README 标明 PMX 2.1 的实际支持范围。

### 3.8 模型验证深度不足

审计时 `PmxModel.validate()` 主要验证 Header、Vertex、Material 和 Face，缺少完整的交叉引用校验。

建议增加：

- Face vertex index 范围。
- Material face count 总和与 face index count 一致。
- Vertex weight bone index 范围。
- Bone parent/tail/inherit/IK target/IK link index 范围。
- Bone parent cycle 和不合理自引用。
- Morph item 引用范围。
- Display frame item 引用范围。
- Rigid body bone index 范围。
- Joint rigid body index 范围。
- Soft Body material/rigid body/vertex index 范围。
- 所有 enum 和 flags 合法性。
- 所有 count 的合理上限，避免畸形文件导致过量内存分配。
- parse 完成后必须到达 EOF；如果允许 trailing bytes，必须显式保存和报告。

不要使用可以被 `python -O` 移除的 `assert` 作为生产输入验证。应抛出明确的异常类型。

> 当前修复状态（2026-08-09）：W4 已新增 `PmxValidator`/`validate_pmx_model()`，并让
> `PmxModel.validate()` 统一转发。上述 PMX 2.0 引用、Bone parent/inherit cycle、条件字段、
> enum/flags、有限数值、字符串/count/source 限制和 parse report strict EOF 均已有稳定
> 字段路径与回归测试；`python -O` 行为不变。Soft Body 引用留待 W6。

### 3.9 模型 API 命名不一致

`PmxModel` 实际字段使用：

- `frames`
- `rigidbodies`
- `softbodies`

但部分方法引用：

- `display_frames`
- `rigid_bodies`
- `soft_bodies`

需要统一公共命名，并通过兼容 property 处理旧名称，避免直接破坏 API。

## 4. 分阶段实施优先级

## P0：阻止数据损坏

P0 完成前不建议发布新的 PMX 完整读写版本。

- [x] 公共 `load_pmx()` 不再返回不完整模型；PMX 2.0 完整到 EOF，PMX 2.1 未支持内容
  抛出明确异常，显式 partial API 返回完整性报告。
- [x] W0 期间公共 `save_pmx()` 在 writer 不完整时 fail closed；W5 后已切换为完整
  PMX 2.0 canonical writer，无效或未支持模型仍在替换目标前失败。
- [x] 所有直接 PMX `struct` 格式强制使用 `<`，裸兼容格式由 `BinaryIOHandler`
  归一化为 little-endian，并有 AST 静态回归。
- [x] 标准 Python parser 能完整解析 PMX 2.0 到 EOF。
- [x] 修复 parser 选择逻辑，不再把 partial fast/Cython parser 当成完整 parser，
  且不再因任意解析异常静默回退到 Nuthouse。
- [x] 7 个本地真实 PMX 2.0 均逐文件解析到 EOF 并通过 `model.validate()`。
- [x] 对 truncated file、非法 count、非法 enum 和主要越界 index 提供明确异常。

## P1：完整 PMX 2.0 语义读写

- [x] Header 完整布局字段。
- [x] Additional UV 0–4 reader/model。
- [x] BDEF1/BDEF2/BDEF4/SDEF/QDEF reader/model，其中 SDEF 保留 C/R0/R1。
- [x] Material 全字段 reader/model。
- [x] Bone 模型及 reader：全 flags、inherit、axes、external parent 和 IK。
- [x] Bone writer 与 read → write → read。
- [x] 现有 Bone record 事务化 S2 编辑：变长名称、两种 tail、全 flags/条件载荷与 IK。
- [x] 所有 PMX 2.0 Morph reader/model，Bone 旋转保留原始 quaternion。
- [x] Display frame reader/model。
- [x] Rigid body reader/model。
- [x] Spring 6DOF Joint reader/model。
- [x] 完整 PMX 2.0 canonical writer。
- [x] 完整 PMX 2.0 cross-reference validator。
- [x] read → write → read 深度语义等价。

当前读写证据（2026-08-09）：7 个 PMX 2.0 语料均完成 strict read-write-read 与深度
语义比较，原件 SHA-256 前后不变；合计覆盖 Vertex Morph 845、Material Morph 184、
Group Morph 36、UV Morph 8、Bone Morph 16、刚体 827 和 Spring 6DOF Joint 741 条记录。
该结果证明 canonical S0/S1 读写覆盖。W11a 另以 22 项测试证明现有 Bone record
的 S2 事务编辑；其中 7 个 UTF-16 真实 PMX 执行变长名称和层级联合修改，非目标字节及
原件 SHA-256 均不变。该结果不代表其他页面已达 S2。

## P2：完整 PMX 2.1

- [ ] Flip Morph。
- [ ] Impulse Morph。
- [ ] 全部 PMX 2.1 Joint 类型。
- [ ] Soft Body 全字段。
- [ ] PMX 2.1 真实样本 round-trip。
- [x] 当前未支持的 PMX 2.1 feature 必须 fail closed。

## P3：性能实现与统一行为

- [x] 标准 Python Cursor parser 作为 PMX 2.0 语义基准。
- [x] fast Python 公共路径通过 PMX 2.0 字段级 parity test。
- [ ] Cython parser 完整覆盖并通过字段级 parity test。
- [x] 原生 Cython 未补齐前，公共 Cython 路径返回安全 Cursor 的 canonical 模型并保持行为一致。
- [x] 性能测试只在完整性测试通过后运行。

## P4：可审计的无损补丁模式

- [ ] 保存原始 source bytes。
- [ ] 记录所有可编辑字段的 byte span。
- [ ] 支持固定长度替换。
- [ ] 支持变长 insert/delete。
- [ ] 补丁应用前检查 before bytes。
- [ ] 拒绝重叠 patch。
- [ ] 输出后重新完整解析。
- [ ] 支持语义变化白名单。
- [ ] 验证未修改字节区域完全一致。
- [ ] 无操作 patch 输出必须与输入逐字节相同。

## 5. 推荐的数据结构

### 5.1 完整 Header

```python
@dataclass(slots=True)
class PmxHeader:
    version: float
    encoding: PmxTextEncoding
    additional_uv_count: int
    vertex_index_size: int
    texture_index_size: int
    material_index_size: int
    bone_index_size: int
    morph_index_size: int
    rigidbody_index_size: int
    name_jp: str
    name_en: str
    comment_jp: str
    comment_en: str
    unknown_global_flags: bytes = b""
```

### 5.2 可追踪来源的 Document

建议把“语义模型”和“源文件布局”分开：

```python
@dataclass(slots=True)
class BinarySpan:
    start: int
    end: int


@dataclass(slots=True)
class PmxDocument:
    model: PmxModel
    source_bytes: bytes
    spans: dict[FieldPath, BinarySpan]
    trailing_bytes: bytes = b""
    loaded_sections: frozenset[str] = frozenset()
```

普通用户可以继续使用：

```python
model = load_pmx(path)
```

需要无损修改的工具使用：

```python
document = load_pmx_document(
    path,
    track_spans=True,
    strict_eof=True,
)
```

### 5.3 补丁记录

```python
@dataclass(slots=True)
class BinaryPatch:
    offset: int
    before: bytes
    after: bytes
    description: str
```

W9 已交付的第一阶段 API：

```python
document.model.bones[bone_index].ik_loop_count = 5
patches = document.build_patches()
write_pmx(document, output_path, mode="lossless_patch")
```

`span_for()`/`make_patch()`/`apply_patches()` 可用于审计底层范围。所有 patch 必须精确对应
已登记 span；`encode_lossless()` 会 strict reparse 并将完整结果与当前 model 比较。W11
再在其上增加 `set_tail_bone()` 等高层 transaction 命令。以下报告型结果仍是后续增强：

```python
result.patches
result.changed_byte_count
result.semantic_changes
result.untouched_regions_verified
result.reparse_verified
```

## 6. reader/writer 设计建议

### 6.1 reader 模式

建议提供三种明确模式：

```python
load_pmx(path, mode="strict")
load_pmx(path, mode="lenient")
load_pmx(path, mode="partial", sections={...})
```

`strict`：

- 未知 version/flag/enum 报错。
- 非法 index 报错。
- 截断报错。
- 未声明 trailing bytes 报错。
- 必须完整解析到 EOF。

`lenient`：

- 保存未知 flags 和 trailing bytes。
- 对非关键异常生成 warning。
- 仍然不能静默跳过不认识的变长 record。

`partial`：

- 明确标记模型不完整。
- 禁止通过普通完整 writer 保存。

### 6.2 writer 模式

建议区分：

```python
write_pmx(model, path, mode="canonical")
write_pmx(document, path, mode="preserve_layout")
write_pmx(document, path, mode="lossless_patch")
```

`canonical`：

- 从语义模型完整重建 PMX。
- 允许重新计算 index size。
- 允许选择 encoding。
- 结果要求语义等价，不要求字节相同。

`preserve_layout`：

- 保留原 encoding、index size 和 section 顺序。
- 尽量保留纹理表与索引布局。

`lossless_patch`：

- 不重建完整文件。
- 仅应用经过验证的 patch。
- 所有未修改区域必须与源文件相同。

## 7. 测试矩阵

### 7.1 Header 与索引

- [ ] UTF-16LE。
- [ ] UTF-8。
- [x] Additional UV：0、1、2、3、4。
- [x] Vertex index：1、2、4 字节。
- [x] Texture index：1、2、4 字节。
- [x] Material index：1、2、4 字节。
- [x] Bone index：1、2、4 字节。
- [x] Morph index：1、2、4 字节。
- [x] Rigid body index：1、2、4 字节。

注意 Vertex index 为无符号，其余支持 `-1` sentinel 的索引通常为有符号。

### 7.2 Vertex

- [x] BDEF1。
- [x] BDEF2。
- [x] BDEF4。
- [x] SDEF（含 C/R0/R1）。
- [x] QDEF。
- [x] 边缘倍率。
- [x] Additional UV 0–4。
- [ ] 非规范但可解析的权重值。

### 7.3 Material

- [ ] 所有 material flags。
- [ ] 无纹理 `-1`。
- [ ] 普通 texture。
- [ ] Sphere multiply/add/subtexture。
- [ ] 内置 Toon。
- [ ] 外部 Toon。
- [ ] UTF-8/UTF-16 注释。
- [ ] material face count 总和校验。

### 7.4 Bone 与 IK

字段顺序、`0x0080` 本地付与及 IK 弧度单位按
[PmxEditor 0.236 附带 PMX 规格备份](https://gist.github.com/FlandreDaisuki/90ae5abf3138a15994526b6bfec73c2c)
核对。

- [x] Tail offset。
- [x] Tail bone index。
- [x] Rotate/translate/visible/enabled。
- [x] Local append (`0x0080`) 与未知 flags 透传。
- [x] Inherit rotation/translation。
- [x] Fixed axis。
- [x] Local axes。
- [x] Deform layer（PMXEditor“表示先”）。
- [x] Deform after physics。
- [x] External parent。
- [x] IK 无链接限制。
- [x] IK 有链接限制。
- [x] 单链接和多链接 IK。
- [x] 极限值为零的合法 limits。
- [ ] 左右脚 IK、脚尖 IK 等真实模型结构。

### 7.5 Morph

- [x] Group。
- [x] Vertex。
- [x] Bone quaternion。
- [x] UV。
- [x] Extended UV 1–4。
- [x] Material（乘算/加算及全部系数）。
- [ ] Flip。
- [ ] Impulse。

### 7.6 Physics 与 PMX 2.1

- [x] 所有 rigid body shape/mode。
- [x] 无骨骼绑定的 rigid body。
- [x] Spring 6DOF Joint。
- [ ] PMX 2.1 其他 Joint。
- [ ] Soft Body config/cluster/iteration/material。
- [ ] Soft Body anchor。
- [ ] Soft Body pin vertex。

### 7.7 异常输入

- [x] 非法 magic。
- [x] 不支持的 version。
- [x] global flag count 异常。
- [x] 非法 encoding。
- [x] 非法 index size。
- [x] 负数或超大 count。
- [x] Bone 条件字段截断及非法 IK limit flag。
- [x] 字符串长度越界。
- [x] record 中途截断。
- [x] 当前支持 section 的非法 enum。
- [x] Bone/Morph/Frame/Rigid Body/Joint 主要索引越界。
- [x] section 后存在未知 trailing bytes（当前由 `PmxParseReport` 明确报告；完整入口拒绝）。

## 8. 每次发布必须通过的验收标准

### 8.1 完整解析

对测试语料中的每个 PMX：

```text
parser position == file size
```

除非以 lenient 模式显式保存了 `trailing_bytes`。

### 8.2 语义 round-trip

```text
read(input) -> write(canonical) -> read(output)
```

两次模型必须进行全字段深度比较，不只比较数量。

浮点字段可按字段设置合理 tolerance，但：

- index、flags、enum、name、count 必须精确相等。
- quaternion 应优先精确保存原始 float32 值。

### 8.3 无损 no-op

```text
read_document(input) -> write(lossless_patch, no changes)
```

必须满足：

```text
input bytes == output bytes
```

### 8.4 局部补丁审计

修改一个字段时必须满足：

- patch 的 `before` 与输入一致。
- patch 范围不重叠。
- 输出可以完整重新解析。
- 语义变化仅包含白名单字段。
- 未修改区域字节完全一致。

### 8.5 Python/fast/Cython 一致性

不能只比较 Header 和 section count，需要对所有字段做深度比较：

```text
parse_python(input) == parse_fast(input) == parse_cython(input)
```

## 9. 建议的真实模型回归语料

测试语料应至少包含：

- 标准 PMX 2.0 模型。
- UTF-8 PMX。
- 带 SDEF/QDEF 的模型。
- Additional UV 模型。
- 包含全部 Morph 类型的模型。
- 带完整物理和 Joint 的模型。
- PMX 2.1 Soft Body 模型。
- 自定义骨架和复杂 IK 模型。
- 大于 255、32767、65535 等 index size 边界的合成模型。

与脚 IK 修复相关的回归样本可以包括：

- Alicia 千咲：修复前存在脚尖 IK 脚踝限制问题。
- Alicia 薇薇安泳装：同类问题。
- Fubuki Mark2：正确对照。
- Shiroko Mark2：正确对照。

真实商业或作者模型不应直接提交到公开仓库。可以：

- 取得授权后加入私有 CI 语料。
- 提取最小可复现 PMX。
- 编写合成模型复现相同 Bone/IK 布局。
- 在本地扩展测试中通过环境变量指定私有模型目录。

## 10. 与 PmxPhysicsRebuilder 的集成建议

推荐职责划分：

```text
PyPMXVMD
├── PMX 格式定义
├── 完整 reader/writer
├── validator
├── source span
└── lossless patch

PmxPhysicsRebuilder
├── 物理候选识别
├── 脚 IK 拓扑识别
├── 修复策略与置信度
├── UI 与报告
└── 允许修改字段白名单
```

建议分三步接入：

1. **只读接入**  
   PyPMXVMD 完成 P0/P1 后，先用于模型语义和骨骼拓扑分析。

2. **保留当前补丁引擎**  
   实际写入继续使用 PmxPhysicsRebuilder 已验证的 offset patch 机制。

3. **替换底层补丁实现**  
   PyPMXVMD 完成 P4，并通过 no-op byte equality 和局部补丁审计后，再把通用能力下沉到 PyPMXVMD。

不要在完整 writer 尚未通过真实模型 round-trip 前，用全模型重新序列化替代当前局部二进制补丁。

## 11. 推荐实施顺序

建议按以下顺序开发，避免同时维护多条不完整路径：

1. `[已完成]` 冻结 partial PMX writer，避免误用。
2. `[已完成]` 在 Binary IO 层统一 `<` 并增加格式长度测试。
3. `[已完成]` 以 Cursor 实现完整、严格的 PMX 2.0 reader。
4. `[已完成]` 完成 PMX 2.0 validator 的规则和异常矩阵。
5. `[已完成]` 实现 canonical PMX 2.0 writer，并通过语义 round-trip。
6. `[已完成]` 完成公共 API 模式与兼容迁移。
7. `[已完成]` 增加 source span、PmxDocument 和定长 lossless patch 模式。
8. `[骨骼已完成；下一步刚体]` 依次交付骨骼、刚体、Joint、材质的 S2/S3 编辑能力。
9. 长期补全 PMX 2.1/Soft Body 与 Vertex/Face/Morph/Display Frame 高层编辑。
10. 让原生 fast/Cython 对齐标准 parser。

优先级原则是：

```text
正确性 > 完整性 > 可审计性 > 性能
```

性能优化不应先于完整字段 parity 和真实模型 round-trip。
