# PyPMXVMD PMX 完整支持重构执行计划

> 文档状态：执行中（W0-W5、W7、W9、W11a/W11b/W11c 已完成；下一步 W11d 材质编辑）
>
> 基线日期：2026-07-30
>
> 适用版本：`pypmxvmd 2.7.1`、Python `3.11.12`、`uv`

本文件是 PMX 大规模重构的执行层计划。它回答“按什么顺序改、改哪些文件、
每一步如何证明没有数据损坏”。PMX 格式现状、字段清单和设计背景以
[PMX 支持改进计划](PMX支持改进计划.md)为准；当前工作区约束以
[项目持续开发恢复指南](项目持续开发恢复指南.md)和`.agents`中的规范为准。最新阶段、
下一任务和验证基线只在 `.agents/07-当前进度与接手指南.md` 动态维护。

## 1. 目标与边界

### 1.1 最终目标

交付一套 correctness-first 的 PMX 实现，满足以下契约：

1. 默认完整读取能解析受支持的 PMX 2.0/2.1 section，并严格到达 EOF。
2. 完整写入不会丢弃任何已声明字段；不能写入的模型必须 fail closed。
3. `read -> write -> read` 对所有语义字段保持等价，索引、flags、enum、名称和
   count 精确一致，浮点字段按字段定义容差比较。
4. 当前只以 canonical Python Cursor 作为正确性基准；fast Python/Cython 不在本计划内扩展。
5. `PmxDocument` 能保存源字节和字段 span，为无损局部修改提供审计证据。
6. 旧的 `load_pmx()`、`save_pmx()` 调用方有迁移路径；旧名称不会无提示消失。

### 1.2 本轮不做的事情

- 不重构 VMD/VPD 的格式实现。
- 不把真实商业模型提交到公开测试目录或覆盖原文件。
- 不在本计划内推进 fast/Cython parity、原生 ABI 补全、性能优化或默认实现切换。
- 不把未知变长 record 当作可忽略尾部。
- 不把“文件能打开”“section count 非零”作为完整支持证明。

## 2. 现状基线

### 2.1 已确认事实

| 区域 | 当前状态 | 影响 |
|---|---|---|
| 公共 reader | canonical Cursor 已完整读取 PMX 2.0 至 Joint/EOF；`load_pmx()` 可返回完整 PMX 2.0 | PMX 2.1 的 Flip/Impulse、其他 Joint 与 Soft Body 仍 fail closed |
| 公共 writer | canonical PMX 2.0 writer 已覆盖全 section；W9 可对登记的定长字段执行 lossless patch | canonical 不保证源布局；变长编辑、PMX 2.1 和高层编辑仍未交付 |
| 备用 Nuthouse | 覆盖较多 section，但仍有 native `struct`、字段缺失和 PMX 2.1 不完整 | 不能直接作为 correctness 基准 |
| 数据模型 | PMX 2.0 的 Header、Vertex/SDEF、Material、Bone/IK、Morph、Frame、Rigid Body、Spring 6DOF Joint 均可表达 | PMX 2.1 特有记录和 Soft Body 仍待 W6；高层编辑 API 尚未开始 |
| 验证 | W4 集中式 Validator 已覆盖 PMX 2.0 条件字段、全部跨引用、cycle、资源限制、parse report 与 strict EOF | 已满足 canonical writer 的前置门槛；PMX 2.1 专属记录留待 W6 |
| API 命名 | `frames`/`display_frames`、`rigidbodies`/`rigid_bodies`等并存 | 大面积重构时容易破坏调用方 |
| 测试 | 7 个本地 PMX 已通过 canonical round-trip 和 no-op lossless byte equality；单字段 patch 与异常矩阵由合成 fixture 覆盖 | 变长/集合编辑和 PMX 2.1 尚无此保证 |

### 2.2 不可改变的工程约束

- 所有命令使用 `uv run --python 3.11.12`，不直接调用 `pip`。
- 真实 PMX 只读；所有 writer 输出使用 pytest `tmp_path` 或明确临时目录。
- 每个源码行为变更必须有对应回归测试；文档状态不能代替测试结果。
- 保留用户已有工作树修改，不使用 `reset`、`checkout`或清理命令覆盖它们。

## 3. 目标架构

重构完成后的调用链固定为：

```text
load_pmx / load_pmx_document
        |
        v
PmxParser facade  ---- mode / implementation selection / compatibility aliases
        |
        v
PmxReader (canonical Python, strict cursor, optional spans)
        |
        +--> PmxModel + PmxParseReport
        +--> PmxDocument(source_bytes, spans, trailing_bytes)

PmxModel / PmxDocument
        |
        +--> PmxValidator (model + cross references + limits)
        +--> PmxWriter (canonical / preserve_layout / lossless_patch)

PmxReader/PmxWriter  <---- field-level parity ---->  fast Python / Cython
```

建议新增 `pypmxvmd/common/pmx/` 包，保留现有模块作为兼容外观，避免一次性移动
全部导入路径：

```text
pypmxvmd/common/pmx/
├── errors.py       # 异常层次与 section/offset 上下文
├── limits.py       # count、字符串和总大小上限
├── cursor.py       # little-endian、边界检查、span 追踪
├── types.py        # encoding、index size、flags 和格式枚举
├── reader.py       # 标准 PMX 2.0/2.1 reader
├── writer.py       # canonical/preserve_layout writer
├── validator.py    # 模型和交叉引用验证
├── document.py     # source bytes、span、patch
└── report.py       # loaded_sections、offset、trailing bytes、warnings
```

现有以下文件在迁移期继续保留并改成转发或适配层：

- `pypmxvmd/common/models/pmx.py`
- `pypmxvmd/common/parsers/pmx_parser.py`
- `pypmxvmd/common/parsers/pmx_parser_nuthouse.py`
- `pypmxvmd/common/io/binary_io.py`
- `pypmxvmd/__init__.py`

不要在第一阶段删除旧文件；删除或降级为私有实现必须等兼容测试通过。

## 4. 公开契约（先定行为，再实现）

### 4.1 Reader 模式

```python
load_pmx(path, mode="strict")
load_pmx(path, mode="lenient")
load_pmx(path, mode="partial", sections={"header", "vertices", "faces"})
load_pmx_document(path, mode="strict", track_spans=True)
```

| 模式 | 行为 | 是否允许普通 writer |
|---|---|---:|
| `strict` | 版本、flags、enum、索引、count、截断和 EOF 全部严格检查 | 是，前提是模型完整且验证通过 |
| `lenient` | 保存可识别的未知 flags 和 trailing bytes，并产生 warning | 只能通过 preserve/canonical 的显式策略 |
| `partial` | 只读取请求 section，结果携带 `loaded_sections` 和 `is_complete=False` | 否 |

不允许用 `except Exception` 将 Cython/fast 失败静默切换成“成功”的 partial
模型。fallback 只能捕获明确列出的能力异常，并在报告中保留实现选择和原始错误。

### 4.2 Writer 模式

```python
save_pmx(model, path, mode="canonical")
write_pmx(document, path, mode="preserve_layout")
write_pmx(document, path, mode="lossless_patch")
```

- `canonical`：按语义模型完整重建，允许显式重选 encoding/index size。
- `preserve_layout`：保留原始 encoding、index size、纹理顺序和可保留的未知字段。
- `lossless_patch`：只应用通过 before-byte、重叠、重解析和未修改区域检查的 patch。

不完整 `PmxModel`、带未消费 section 的旧 parser 结果和含未知变长 record 的模型，
都必须在 writer 入口抛出 `IncompletePmxError` 或 `UnsupportedPmxFeatureError`。

### 4.3 异常契约

新增异常至少包括：

```text
PmxError
├── PmxFormatError          # magic/version/header/record 布局错误
├── PmxTruncatedError       # 需要的字节超出 EOF
├── PmxValidationError      # 引用、enum、count 或模型状态错误
├── IncompletePmxError      # partial 模型尝试完整写入
└── UnsupportedPmxFeatureError  # 明确识别但尚未支持的 feature
```

每个解析异常必须包含 `section`、`offset`，必要时还要包含 `record_index`、
`field` 和 `expected/actual`。异常信息不能只保留底层 `struct.error`。

## 5. 工作包与依赖关系

下面的编号是实际执行顺序。每个工作包完成后单独提交，提交前必须通过该包的
退出门槛。`并行`只表示可以同时准备测试或文档，不表示可以跳过依赖。

### W0：基线冻结与失败证据（P0，已完成）

**依赖：** 无。  
**目标：** 把当前“不完整但返回成功”的行为变成可复现的失败测试。

修改范围：

- 新增 `tests/test_pmx_integrity.py`、`tests/pmx_test_helpers.py`。
- 为 7 个 PMX corpus 建立逐文件报告：文件名、长度、已加载 section、最终 offset、
  trailing bytes 和失败上下文。
- 为 Header-only、Material-only、截断 record、非法 count 建立最小合成 fixture。
- 不先修改 Cython；先证明标准、fast、Cython 当前的覆盖差异。

交付物：

- 一个不会依赖打印输出的 `PmxParseReport` 测试断言方式。
- 一组当前必须失败的回归测试，明确指出 parser 在 Material 后仍有未消费数据。
- 更新恢复指南，记录本次审计的实际结果。

退出门槛：

```text
每个 corpus 文件独立执行；partial 结果被测试识别；完整模式在旧实现上明确失败；
非 PMX 测试仍保持 0 failed；没有向 tests/data 写文件。
```

W0 在 2026-08-09 交付时，读取侧新增：`PmxParseReport`、`PmxParseResult`、
`load_pmx_partial()`、逐 section span/offset/trailing bytes 证据，以及公共完整读取的
`IncompletePmxError`。7 个真实 PMX 已逐文件报告 Material 后仍有未消费数据。
公共 `save_pmx()` 也已冻结：它在创建目标文件前抛出
`IncompletePmxWriterError`。旧 Header 至 Material serializer 只保留为显式
`PmxParser.write_file_partial()` 测试工具，不能作为成功保存操作。W0 已关闭；后续 W3
已将 reader 推进为完整 PMX 2.0，以上 Material 边界仅是历史基线。

### W1：二进制 Cursor 与格式安全层（P0，已完成）

**依赖：** W0 的偏移报告。  
**主要文件：** `common/pmx/cursor.py`、`common/io/binary_io.py`、`common/pmx/errors.py`。

实施步骤：

1. 新增只读 `PmxCursor(data, section, limits)`，统一 `position`、`remaining`、
   `read_exact`、`unpack`、`read_index`、`read_string`和 span 记录。
2. 所有 PMX `struct.Struct/pack/unpack/unpack_from` 格式强制以 `<` 开头；在
   PMX 层禁止 native alignment。
3. 区分无符号 vertex index 和允许 `-1` sentinel 的有符号 index。
4. 对负长度、超大长度、非法 position、截断读取、非法 index size 统一抛出带 offset 的异常。
5. 设置默认上限：单个 count、字符串字节数、总 source bytes 和 patch 数量；具体值集中在
   `limits.py`，测试可显式覆盖。
6. 旧 `BinaryIOHandler` 保留兼容方法，但 PMX reader 不再直接使用会删除前缀数据的隐式 API。

测试：

- `tests/test_pmx_cursor.py`：每种整数宽度、signedness、EOF、位置和 span。
- `tests/test_pmx_binary_layout.py`：所有 fixed record 的 `Struct.size` 与规格长度。
- 为 native 格式回归增加静态扫描或测试，防止再次出现无 `<` 格式。

退出门槛：所有 cursor 测试通过；异常包含 section/offset；旧 VMD/VPD IO 测试不回归。

截至 2026-08-09，W1 已交付 `PmxCursor`、`PmxLimits`、有符号/无符号 index 读取、
严格字符串和 count 上限、section span 以及 little-endian 静态回归。公共 `auto` 部分
读取已固定走 Cursor；显式 Cython 路径会先经过安全 Cursor 探测。历史 Material Toon
sharing flag 语义错误已在 Python/Cython 中同步修复，并以 2 字节 texture index fixture
覆盖。非 benchmark 全量结果为 `239 passed, 2 deselected`，benchmark 为
`2 passed, 239 deselected`。W1 已关闭；下一阶段进入 W2 语义模型补全与兼容层。

### W2：PMX 语义模型补全与兼容层（P0/P1，PMX 2.0 已完成）

**依赖：** W1。  
**主要文件：** `common/models/pmx.py`、`common/pmx/types.py`、`common/pmx/errors.py`。

实施步骤：

1. `PmxHeader` 增加 `encoding`、`additional_uv_count`、六类 index size、原始 global
   flags/unknown flags；保留旧构造参数默认值。
2. 顶点补全 BDEF1/BDEF2/BDEF4/SDEF/QDEF 的权重字段和 additional UV 0-4，保留
   quaternion 原始 float32，不在 reader 中强制转 Euler。
3. 补全 Material 的 flags、纹理/球面/Toon 布局和所有原始字段。
4. 补全 Bone、IK、Morph item、Display Frame、Rigid Body、Joint、Soft Body 的字段类型。
5. 为 `PmxModel` 增加 `is_complete`、`loaded_sections`、`parse_report`；把旧名称实现为
   property 别名，并给出弃用提示周期。
6. 新字段必须使用明确默认值和类型检查；生产输入验证不能依赖 `assert`。

测试：

- `tests/test_pmx_model_fields.py`：每个 enum、字段默认值、旧别名和深拷贝。
- `tests/test_pmx_model_validation.py`：错误字段路径、count 上限、enum 和索引容器。
- `tests/test_pmx_compatibility.py`：现有 API fixture 不改变已支持字段的行为。

退出门槛：模型能表达 PMX 2.0 全 section；旧公共导入路径仍可用；不改变 VMD/VPD 模型。

截至 2026-08-09，W2 的 PMX 2.0 范围已交付：完整 Header global layout、Additional UV、
SDEF C/R0/R1、Material 原始纹理/Sphere/Toon、Bone 全条件字段、全部 PMX 2.0 Morph item、
Display Frame、Rigid Body 原始 collision group/mask 和 Spring 6DOF Joint。Bone Morph 保留
原始四元数，所有旋转字段保持 PMX 原始弧度；`PmxModel` 已有完整性证据、兼容集合别名和
上述 section 的主要跨引用验证。PMX 2.1 的 Flip/Impulse、其他 Joint 和 Soft Body 保留给
W6。这一工作包只完成结构/语义表达，不代表 PMXEditor 页面已经可编辑。

### W3：标准 PMX 2.0 Reader（P0/P1）

**依赖：** W1、W2。  
**主要文件：** `common/pmx/reader.py`、`common/pmx/report.py`、
`common/parsers/pmx_parser.py`（facade 接入）。

按以下 section 顺序实现并逐段提交：

1. Magic/version/global flags/文本编码/Header。
2. Vertex（位置、法线、UV、additional UV、五种权重、edge scale）。
3. Face index count 和 vertex indices。
4. Texture table。
5. Material 全字段和 face count。
6. Bone 全 flags、tail、inherit、axis、external parent、IK。
7. Morph 全部已声明 PMX 2.0 类型及 item。
8. Display Frame 及 bone/morph item。
9. Rigid Body。
10. Joint 及其条件字段。

截至 2026-08-09，W3 已完成。活动 Cursor reader 按顺序完整消费 PMX 2.0 的 Bone、Morph、
Display Frame、Rigid Body 和 Spring 6DOF Joint，并要求 Joint 后精确到达 EOF；Additional UV
和 SDEF 三向量也不再被跳过。合成 fixture 覆盖全部 9 种 PMX 2.0 Morph、两类 Frame item、
三种刚体形状/模式、Spring 6DOF Joint、1/2/4 字节 Bone/Morph/Rigid Body index，以及非法
enum、截断和 PMX 2.1 边界。7 个真实 PMX 全部读到 EOF 并通过 `model.validate()`；语料共
覆盖 845 个 Vertex Morph、184 个 Material Morph、36 个 Group Morph、8 个 UV Morph、
16 个 Bone Morph、827 个刚体和 741 个 Spring 6DOF Joint。原生 Cython ABI 仍会丢弃扩展
顶点与 post-Material section，因此公共 `implementation="cython"` 暂返回安全 Cursor 的
canonical 模型；原生迁移仅保留为计划外 W8 候选。非 benchmark 全量结果为 `315 passed`。

每个 section 的实现必须同时完成：

- count 合理上限和剩余字节检查。
- 引用索引先保存原值，最终由 validator 检查。
- report 更新 `loaded_sections`、起止 offset 和 record 数量。
- record 中途截断时抛出带 field 的 `PmxTruncatedError`。

接入规则：

- `PmxParser.parse_file()` 默认改为 canonical Python reader 的 strict 模式。
- Cython/fast 暂时只能由显式 `implementation=` 或 partial API 调用。
- 删除“任意异常后回退且返回模型”的逻辑；保留错误链用于诊断。
- 只有 `cursor.position == len(source_bytes)` 才把模型标记为 complete。

测试：

- `tests/test_pmx_reader_header.py`、`test_pmx_reader_vertices.py`、
  `test_pmx_reader_bones.py`、`test_pmx_reader_morphs.py`、`test_pmx_reader_physics.py`。
- 每个 section 至少一个最小合成 PMX 和一个截断/非法引用样本。
- `tests/test_corpus_parsers.py` 改为断言完整模式的 EOF 和 section 报告，不只断言数量非零。

退出门槛：所有已声明 PMX 2.0 section 在标准 reader 中完整到 EOF；7 个 corpus 逐文件通过或
明确报告不支持 feature；旧 fast/Cython 不再掩盖标准 reader 失败。

### W4：PMX 2.0 Validator（P1）

**状态：** 已完成（2026-08-09）；`PmxModel.validate()` 已统一转发到
`common/pmx/validator.py`，并通过 `python -O`、malformed bytes、全量测试和 7 个真实 PMX。

**依赖：** W2、W3，可与 W3 的后半段并行编写测试。  
**主要文件：** `common/pmx/validator.py`、`common/models/pmx.py`。

验证内容：

- Face vertex index 范围及 `face_count` 总和。
- 顶点 weight bone index 范围和权重模式的字段数量。
- Bone parent/tail/inherit/IK target/link 范围、自引用和可诊断 cycle。
- Morph item、Frame item、Rigid Body、Joint 的所有引用范围。
- enum、flags、版本与条件字段的合法性。
- count、字符串、source size 和递归/嵌套数量上限。
- `strict_eof`；lenient 模式仅把 trailing bytes 放入 report，不静默丢弃。

测试：

- `tests/test_pmx_validator.py` 使用参数化越界、负值、循环和不匹配 count。
- `tests/test_pmx_malformed.py` 使用真实二进制截断和篡改 fixture，验证不会过量分配。

退出门槛：所有错误可定位到字段路径；`python -O` 下验证行为不变；异常输入不写输出文件。

### W5：PMX 2.0 Canonical Writer（P1，已完成）

**依赖：** W1、W2、W3、W4。  
**主要文件：** `common/pmx/writer.py`、`common/parsers/pmx_parser.py`。

实施规则：

1. 先调用 validator，再根据模型和显式 writer 选项确定布局。
2. 自动选择 index size 只能发生在 `canonical`；`preserve_layout` 必须使用 Header 中的原值。
3. 保持纹理列表和索引顺序，不做隐式去重/排序。
4. 按 Header 的 additional UV、encoding、signedness 和 vertex weight mode 写出所有条件字段。
5. 写出 Bone、Morph、Frame、Rigid Body、Joint；任何非空但未支持字段立即报错。
6. 写完重新用 strict reader 解析输出，并在测试中比较全字段语义。
7. `write_file()` 旧入口改为转发到 canonical writer；不再静默生成 partial 文件。

测试：

- `tests/test_pmx_writer_canonical.py`：空模型、最小模型、每种条件字段和 index size 边界。
- `tests/test_pmx_roundtrip.py`：合成全字段模型的 read/write/read 深度比较。
- 真实 corpus 只写入 `tmp_path`，执行 7 个独立 round-trip case。

退出门槛：所有 PMX 2.0 合成 fixture 全字段 round-trip；真实 corpus 输出可再次 strict 解析；
旧 partial 模型写入明确失败；原件 hash 不变。

2026-08-09 交付结果：新增独立 canonical writer，完整编码 PMX 2.0 全 section，自动选择
signed/unsigned index width，保持纹理列表顺序，并在完整内存编码后原子替换目标。三类独立
手工二进制 fixture 与 writer 输出逐字节相等；7 个真实 PMX 仅向 `tmp_path` 写出，全部
strict reparse 且深度语义等价，原件 SHA-256 前后不变。公开 `save_pmx()`/`save()` 和
`PmxParser.write_file()` 已转发到 canonical writer；legacy partial 入口仍显式隔离。

### W6：PMX 2.1 与 Soft Body（P2，长期）

**依赖：** W5。  
**主要文件：** `common/pmx/reader.py`、`writer.py`、`types.py`、`validator.py`。

调度约束：不进入当前近期迭代；先完成 W4/W5 以及 W11 的骨骼、刚体、Joint、材质
优先链，除非用户显式调整优先级。

实施范围：

- PMX 2.1 version/条件字段。
- Flip Morph、Impulse Morph 和相应索引/向量字段。
- 所有 Joint 类型及其特有约束字段。
- Soft Body 基础属性、Config、Cluster、Iteration、Material、Anchor、Pin vertex。
- PMX 2.1 的未知或未实现 feature 必须抛 `UnsupportedPmxFeatureError`，不能删除后继续写。

测试：

- 新增 `tests/fixtures/pmx_builder.py` 生成 PMX 2.1 最小 fixture。
- `tests/test_pmx_21.py` 覆盖每个条件分支、Soft Body 引用、截断和 round-trip。
- 有授权时使用私有 corpus；无授权时使用合成 fixture，不把商业模型提交仓库。

退出门槛：支持范围在 README/API 文档中逐项列出；PMX 2.1 样本完整到 EOF 并可语义 round-trip。

### W7：公共 API 迁移与兼容发布（P1/P2，已完成）

**依赖：** W3、W5。  
**主要文件：** `pypmxvmd/__init__.py`、`common/parsers/pmx_parser.py`、`docs/API_CN.md`、
`docs/API.md`、`README.md`。

实施步骤：

1. 为 `load_pmx` 增加 `mode`、`implementation`、`strict_eof`、`track_spans`等显式参数，
   默认行为选择 strict canonical。
2. 增加 `load_pmx_document`、`save_pmx`/`write_pmx` 的 mode 入口；保留旧位置参数。
3. 将 `parse_file_fast`、`parse_file_cython` 标为显式优化入口，能力不足时返回明确异常。
4. 保留旧字段名 property，并在文档中注明迁移目标；至少一个 minor 版本后再考虑移除。
5. 更新 `load()`/`save()` 自动检测路径，拒绝把 partial 模型送入完整 writer。
6. 文档明确 PMX 2.0/2.1 的实际支持矩阵、异常类型和不保证的字节稳定性。

测试：

- `tests/test_api_integration.py` 增加 strict/lenient/partial/document API。
- `tests/test_api_compatibility.py` 锁定旧调用签名、旧属性别名和错误类型。
- 运行 `mkdocs build --strict` 检查链接和 API 文档。

退出门槛：旧 API 测试全绿；新 API 的不完整/未支持状态可被调用方区分；文档与签名一致。

2026-08-09 交付结果：旧 `file_path`/`more_info`/`implementation` 位置参数保持兼容，
新增参数均为 keyword-only。`load_pmx()`/`load()` 明确区分 strict 与 partial 返回契约，
`save_pmx()`/`write_pmx()`/`save()` 提供 canonical mode。新增
`UnsupportedPmxFeatureError`，使 document/span、preserve layout、lossless patch 与未知
模式不会静默降级；W9 API 名称已 fail-closed 预留。API 兼容、模式矩阵和旧字段别名均有
回归测试，README 及中英文 API 文档已与实际签名同步。

### W8：fast Python 与 Cython parity（计划外性能候选，不排期）

2026-08-10 决策：W8 移出正式执行计划，不再是完整支持、阶段交付或发布的前置门槛。
只有 W6、W10、W11、W12 及全部长期 correctness/格式安全/编辑/集成回归稳定后，才由
用户重新排期决定是否启动。当前保持 canonical Cursor 为唯一正确性基准；既有 fast/Cython
代码只做必要回归维护，不新增 section、不扩大公开职责、不恢复默认启用。

以下内容仅保留为未来重新立项时的候选草案，不属于当前提交序列。

**未来依赖：** 全部功能和发布路线完成且稳定，并由用户显式重新排期。
**主要文件：** `common/parsers/*.pyx`、`common/io/*.pyx`、`scripts/build_cython.py`、
`tests/test_parser_optimization.py`、`tests/test_cython_parsers.py`。

实施顺序：

1. 先为每个 section 复用 canonical reader 的 fixture 和字段级比较器。
2. 一次只实现一个 section 的 fast/Cython 路径，比较模型、report、异常类型和最终 offset。
3. Cython 不可用、编译失败、边界失败时必须与标准路径给出一致的 fail-closed 结果。
4. 所有 parity 通过后才允许把优化实现设为默认；否则保持显式 opt-in。
5. benchmark 只记录趋势，不用单次倍数作为正确性门槛。

退出门槛：`parse_python == parse_fast == parse_cython`覆盖全部支持字段；优化路径同样严格 EOF；
纯 Python 构建和 Cython 构建都通过同一测试矩阵。

### W9：PmxDocument 与 lossless patch（P4，已完成）

**依赖：** W3、W5、W7；不得提前替代现有 Rebuilder offset patch。  
**主要文件：** `common/pmx/document.py`、`common/pmx/reader.py`、`common/pmx/writer.py`、
`tests/test_pmx_document.py`、`tests/test_pmx_patch.py`。

实现范围：

- 保存 `source_bytes`、`BinarySpan`、`loaded_sections`、`trailing_bytes`。
- 支持按 `FieldPath` 生成 `BinaryPatch(offset, before, after, description)`。
- 应用前验证 before bytes、范围、重叠和字段类型。
- 固定长度字段先交付；变长字符串、list insert/delete 作为后续子阶段。
- 输出后 strict reparse，并比较语义变化白名单。
- 验证未修改区域逐字节一致；无操作 patch 必须 `input == output`。

测试退出门槛：

```text
no-op byte equality 通过；单字段修改只改变允许范围；before 不匹配、重叠 patch、越界
和重新解析失败均拒绝写出；真实文件只对临时副本操作。
```

2026-08-09 交付结果：新增 source-backed `PmxDocument`、稳定 `FieldPath`、`BinarySpan`
与 `BinaryPatch`。Cursor 可选登记现有 Material、Bone、Rigid Body、Joint record 中可
直接映射的部分定长数值/枚举/flags/索引/向量字段；`load_pmx_document()`、`mode="document"` 和
`track_spans=True` 已公开。lossless 写入在原子替换前验证模型、before、边界、等长、重叠、
登记范围和字段类型，并 strict reparse 后做全模型语义比较。no-op 逐字节复用源快照；7 个
真实 PMX 仅向 `tmp_path` 写出且源文件 SHA-256 不变。字符串、集合增删、条件布局 flags、
`preserve_layout` 和 PMX 2.1 继续 fail closed。

### W10：PmxPhysicsRebuilder 集成与发布门槛（P4）

**依赖：** W9。  
**目标：** 让上层工具逐步使用语义模型，同时保留可回滚的旧补丁路径。

阶段：

1. 只读接入：用 `PmxDocument` 做骨骼/物理拓扑分析，不写模型。
2. 双写验证：旧 offset patch 和新 patch engine 同时生成临时输出，只比较预期字段和未修改区域。
3. 单写切换：通过配置开关启用新实现，失败自动停止，不自动覆盖原件。
4. 移除旧实现前，保留至少一个版本的回滚文档和产物审计报告。

发布前必须同时完成：README/API/计划文档、版本号、CHANGELOG（如项目采用）、CI、
sdist/wheel 内容校验和用户迁移说明。

### W11：PMXEditor 页面级安全编辑（骨骼 > 刚体 > Joint > 材质）

**依赖：** W4、W5、W7、W9。
**目标：** 按用户确认的固定优先级交付 S2 安全编辑和必要的 S3 便捷命令。

共同前置：

- 每个操作通过 transaction/patch 对象表达，先验证内存模型，再写入临时目标并 strict reparse。
- 第一轮只修改现有 record，不增加/删除集合；涉及全局重编号的增删另立子阶段。
- 每个页面建立字段白名单比较器，断言其他 section 语义不变、未修改字节区域不变。
- 任一未支持条件字段、悬空引用或验证失败都不得创建/替换用户目标文件。

交付顺序：

1. **W11a 骨骼（已完成）**：名称/位置/层级与 flags、`表示先`骨骼/相对、付与、固定轴、Local 轴、
   外部亲和 IK；提供 `set_tail_bone()`、`set_tail_offset()` 等显式操作。退出门槛是两种
   tail 变长 record 都能 read-modify-write-read，Bone/Rigid Body/Morph/Frame 引用无悬空。
2. **W11b 刚体（已完成）**：关联骨骼、三种形状/物理模式、group/mask、姿态和五个物理参数；退出
   门槛是无骨骼 sentinel、16 组 collision mask 和所有 Joint 引用均通过验证。
3. **W11c Joint（已完成）**：PMX 2.0 Spring 6DOF 的 A/B 刚体、位置/旋转、移动/旋转
   限制和弹簧；所有旋转内部保持原始弧度。未定义明确跨工具公式的“按骨骼/刚体位置
   初始化”不作为 S2 退出门槛，也未加入隐式行为。
4. **W11d 材质**：全部颜色、flags、轮郭、纹理/Sphere/Toon、备注与 face count；
   “同步扩散-环境”只作为显式命令，不在读取或普通保存时自动执行。

每个子阶段单独提交和发布能力矩阵；前一页面未达到 S2 验收时不启动下一页面。

2026-08-09 W11a 交付结果：`PmxDocument` 现在保留 Bone record 的精确源 span，
`PmxBoneEditor` 在隔离副本上修改现有骨骼，并为变长名称和所有条件布局重建整条
record。位置、parent、`deform_layer`、基本 flags、两种 tail、付与/本地付与、固定轴、
Local 轴、外部亲和 IK 均有显式命令。事务在写入前完成集中验证、源 `before`
校验、strict reparse 和全模型语义比较；骨骼集合增删/重排仍 fail closed。

2026-08-10 W11b 交付结果：`PmxDocument` 现在也保留 Rigid Body record 的精确源
span；`PmxRigidBodyEditor` 支持现有刚体的变长日/英名、骨骼引用（含 `-1`）、三形状、
三模式、原始 group/mask、姿态和五个物理参数。Bone 1/2/4 字节 index、16 组 mask、
非法引用/枚举/数值、集合重排和 7 个真实 PMX 均有回归；事务复用 W11a 的验证、原子
写入、strict reparse 与全模型比较边界，刚体增删/替换/重排仍 fail closed。

2026-08-10 W11c 交付结果：`PmxDocument` 现在也保留 Joint record 的精确源 span；
`PmxJointEditor` 支持现有 Spring 6DOF Joint 的变长日/英名、类型、A/B 刚体引用（含
`-1`）、position/rotation、两组 min/max 和两组 spring。Rigid Body 1/2/4 字节 index、
非法引用/枚举/float32 数值、集合变更和 7 个真实 PMX 均有回归。限位 setter 要求逐轴
`minimum <= maximum`，同时只拒绝本次新引入的倒置轴，以保留语料中的历史源值并允许
无关字段编辑。Joint 增删/替换/重排与 PMX 2.1 Joint 类型仍 fail closed。

### W12：长期高层编辑（Vertex、Face、Morph、Display Frame）

**依赖：** W11；PMX 2.1 类型还依赖 W6。
**调度：** 不进入当前近期迭代，完成页面优先链后再排期。

- Vertex：Additional UV、五种权重、SDEF/QDEF、edge scale 与骨骼重编号。
- Face：拓扑增删、vertex index 重编号、Material face count 联动。
- Morph：PMX 2.0 全 item 的增删/重排；W6 后再加入 Flip/Impulse。
- Display Frame：bone/morph item 增删、重排、special frame 约束和重编号。
- Soft Body 与所有 PMX 2.1 特有字段仍由 W6 先建立完整 reader/writer/validator，再开放编辑。

退出门槛沿用 W11 的 transaction、白名单语义差异、strict reparse 和真实语料临时副本规则。

## 6. 测试与语料方案

### 6.1 Fixture 分层

| 层级 | 位置 | 用途 | 是否提交真实模型 |
|---|---|---|---:|
| 单元 bytes | `tests/fixtures/` | 固定 record、截断、非法 count | 否 |
| 合成 PMX builder | `tests/pmx_test_helpers.py` | 全字段组合、index 边界、2.1 feature | 否 |
| 本地 corpus | `tests/data/test_models/` | 逐文件真实性回归 | 否，保持现有本地治理 |
| 私有 corpus | 环境变量指定目录 | 授权模型和大模型性能 | 否 |

合成 builder 必须能生成：UTF-16LE/UTF-8、additional UV 0-4、各 index size、五种
weight、全部 PMX 2.0 Morph、Physics、IK、PMX 2.1 Soft Body。

### 6.2 测试标记和命令

正确性阻断集：

```powershell
uv run --python 3.11.12 --no-sync pytest -m "not benchmark" -ra
```

PMX 定向集：

```powershell
uv run --python 3.11.12 --no-sync pytest tests/test_pmx_*.py tests/test_corpus_parsers.py -m "not benchmark" -ra
```

Cython 构建和 parity（计划外；仅未来重新立项时运行）：

```powershell
uv run --python 3.11.12 --no-sync python scripts/build_cython.py
uv run --python 3.11.12 --no-sync pytest tests/test_parser_optimization.py tests/test_cython_parsers.py -m "not benchmark" -ra
```

文档、构建和差异检查：

```powershell
uv run --python 3.11.12 --no-sync mkdocs build --strict
uv build
uv run --python 3.11.12 --no-sync python scripts/verify_wheel.py dist
git diff --check
git status --short
```

### 6.3 每个工作包的通用验收模板

提交前在 PR/提交说明中记录：

```text
变更范围：
新增/修改测试：
运行命令：
通过/失败/跳过数量：
真实语料是否写入：否/说明临时路径
仍未支持的字段：
兼容性影响：
```

## 7. 数据安全和失败策略

1. parser 永远不修改输入文件；writer 默认拒绝覆盖输入路径，除非调用方显式选择且
   实现已通过临时副本验证。
2. count 先与剩余字节及集中上限比较，再分配 list；禁止直接按文件声明 count 分配无限内存。
3. 所有变长字符串都检查字节长度、编码和 EOF；strict 模式不使用 `errors="ignore"`。
4. 未知 version、enum、record 或变长字段必须保留原始上下文并 fail closed。
5. 任何 fallback 都记录实现名称、原始异常和完整性状态；不能只返回一个空 list 模型。
6. 所有 writer 输出先写临时文件，重新解析和验证通过后再由调用方决定是否替换目标。
7. 真实 corpus 的 hash 在测试前后比较，确保测试没有覆盖原件。

## 8. 迁移与提交策略

推荐最小可审查提交序列：

```text
1. integrity tests/report（W0）
2. cursor + binary layout（W1）
3. model/types/compatibility（W2）
4. reader: header/vertex/material（W3a）
5. reader: bone/morph/frame/physics（W3b）
6. validator（W4）
7. canonical writer + PMX 2.0 round-trip（W5）
8. public API migration（W7）
9. document/lossless patch（W9）
10. 页面级编辑：Bone > Rigid Body > Joint > Material（W11）
11. PMX 2.1/Soft Body（W6，长期）
12. Vertex/Face/Morph/Display Frame 高层编辑（W12，长期）
13. integration/release/docs（W10）
```

W8 fast/Cython parity 不在本序列中；所有功能、格式安全、编辑和发布工作稳定后，只有经
用户重新排期才可作为新的计划外性能项目启动。

每个提交只解决一个工作包；不要把 model、reader、writer、validator、Cython 和 patch
一次性混在一个提交中。若某阶段需要调整前一阶段接口，应在提交说明中写出迁移原因和
新增/删除的公开行为。

## 9. 风险清单

| 风险 | 触发信号 | 处理方式 |
|---|---|---|
| 旧模型字段命名破坏调用方 | 外部代码访问 `rigid_bodies` 等别名 | property 兼容、弃用周期、API 测试 |
| native alignment 再次混入 | record size 与规格不符 | cursor 统一封装、静态扫描、固定长度测试 |
| reader 与 writer 顺序漂移 | round-trip 后 EOF 或 section count 失败 | 每个 section 一对一 reader/writer 测试 |
| quaternion 精度损失 | 无操作 round-trip 浮点变化 | 保留原始 float32，Euler 只做计算属性 |
| Cython 继续掩盖错误 | 默认路径成功但 canonical 失败 | 默认 strict canonical，parity 后再启用优化 |
| 畸形 count 导致内存风险 | 测试进程内存异常或长时间运行 | limits、剩余字节预算、异常输入 fixture |
| 商业语料污染仓库 | `git status` 出现 tests/data 输出 | tmp_path、hash 检查、提交前 status 审计 |
| 全量重写破坏物理工具 | Rebuilder 结果出现非预期字节变化 | W9 前保留旧 offset patch，双写比对后再切换 |

## 10. 完成定义（Definition of Done）

PMX 完整支持重构只有在下列项目全部满足时才可标记完成：

- [x] strict reader 对 PMX 2.0 到达 EOF；PMX 2.1 未支持记录明确 fail closed。
- [x] partial reader 的状态、section 和 writer 拒绝行为可测试。
- [x] PMX 2.0 Validator 覆盖条件字段、跨引用、cycle、资源上限和 strict EOF。
- [x] canonical writer 覆盖所有已支持字段，没有固定 BDEF1/UV=0 等隐式简化。
- [x] 7 个本地 PMX 逐文件完成解析证据和临时 round-trip，原件 hash 未变。
- [ ] 合成 fixture 覆盖所有 index size、weight、Morph、IK、Physics、Soft Body 分支。
- [ ] malformed/truncated/unknown feature 都 fail closed，异常带 section/offset。
- [x] 优化路径保持非默认且不扩大职责；fast/Cython 完整 parity 属计划外候选。
- [x] no-op lossless patch 字节完全相同，单字段 patch 通过未修改区域审计。
- [x] W9 公共 API、兼容别名、异常、支持矩阵和迁移文档同步。
- [ ] `pytest`、`mkdocs build --strict`、`uv build`、wheel 校验、
  `git diff --check` 全部通过。

在达到上述定义前，项目文档和发布说明只能写“部分 PMX 支持”或列出已验证 section，
不能写“完整 PMX 读写支持”。

## 11. 开发者接手时的第一条命令

```powershell
git status --short
uv run --python 3.11.12 --no-sync pytest -m "not benchmark" -ra
```

然后从 W0 开始；如果 W0 的失败证据已经存在，也必须复核其报告和测试是否仍对应当前
工作树，再进入 W1。任何阶段遇到未预期的用户改动，应保留改动并在提交说明中记录影响，
不能通过清理工作树来“恢复基线”。
