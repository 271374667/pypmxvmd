# PyPMXVMD PMX 完整支持重构执行计划

> 文档状态：执行中（W0/W1 已完成，W2 进行中）
>
> 基线日期：2026-07-30
>
> 适用版本：`pypmxvmd 2.7.1`、Python `3.11.12`、`uv`

本文件是 PMX 大规模重构的执行层计划。它回答“按什么顺序改、改哪些文件、
每一步如何证明没有数据损坏”。PMX 格式现状、字段清单和设计背景以
[PMX 支持改进计划](PMX支持改进计划.md)为准；当前工作区约束以
[项目持续开发恢复指南](项目持续开发恢复指南.md)和`.agents`中的规范为准。

## 1. 目标与边界

### 1.1 最终目标

交付一套 correctness-first 的 PMX 实现，满足以下契约：

1. 默认完整读取能解析受支持的 PMX 2.0/2.1 section，并严格到达 EOF。
2. 完整写入不会丢弃任何已声明字段；不能写入的模型必须 fail closed。
3. `read -> write -> read` 对所有语义字段保持等价，索引、flags、enum、名称和
   count 精确一致，浮点字段按字段定义容差比较。
4. 标准 Python、fast Python 和 Cython 只有在逐字段 parity 后才能对外宣称等价。
5. `PmxDocument` 能保存源字节和字段 span，为无损局部修改提供审计证据。
6. 旧的 `load_pmx()`、`save_pmx()` 调用方有迁移路径；旧名称不会无提示消失。

### 1.2 本轮不做的事情

- 不重构 VMD/VPD 的格式实现。
- 不把真实商业模型提交到公开测试目录或覆盖原文件。
- 不在完整 reader/writer 通过前进行性能优化或把 Cython 设为默认实现。
- 不把未知变长 record 当作可忽略尾部。
- 不把“文件能打开”“section count 非零”作为完整支持证明。

## 2. 现状基线

### 2.1 已确认事实

| 区域 | 当前状态 | 影响 |
|---|---|---|
| 公共 reader | `PmxParser.parse_file()`优先走 Cython/fast，当前只可靠覆盖 Header、Vertex、Face、Texture、Material | 真实模型的 Bone、Morph、Frame、Physics 可能为空，属于静默数据丢失 |
| 公共 writer | `write_file()`只编码到 Material，并固定 BDEF1、附加 UV=0 等布局 | 保存真实模型会生成截断或破坏性文件 |
| 备用 Nuthouse | 覆盖较多 section，但仍有 native `struct`、字段缺失和 PMX 2.1 不完整 | 不能直接作为 correctness 基准 |
| 数据模型 | `PmxHeader` 缺少 encoding/index size，Morph 只有部分 item，`PmxSoftBody`为空类 | reader/writer 无法表达完整布局 |
| 验证 | `BaseModel`主要使用可被优化移除的`assert`，缺少跨 section 引用检查 | 畸形输入可能错位、超量分配或写出非法索引 |
| API 命名 | `frames`/`display_frames`、`rigidbodies`/`rigid_bodies`等并存 | 大面积重构时容易破坏调用方 |
| 测试 | 现有 7 个本地 PMX 主要证明旧路径可返回，不证明完整 EOF 或 round-trip | 必须新增 section、偏移、异常和全字段测试 |

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

截至 2026-08-09，读取侧已交付：`PmxParseReport`、`PmxParseResult`、
`load_pmx_partial()`、逐 section span/offset/trailing bytes 证据，以及公共完整读取的
`IncompletePmxError`。7 个真实 PMX 已逐文件报告 Material 后仍有未消费数据。
公共 `save_pmx()` 也已冻结：它在创建目标文件前抛出
`IncompletePmxWriterError`。旧 Header 至 Material serializer 只保留为显式
`PmxParser.write_file_partial()` 测试工具，不能作为成功保存操作。W0 已关闭。

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

### W2：PMX 语义模型补全与兼容层（P0/P1，进行中）

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

截至 2026-08-09，W2 第一批已交付：完整 Header global layout、Material 原始纹理/
Sphere/Toon 索引与 sharing mode、Bone 全 flags/表示先/付与/轴/IK 条件字段、Rigid Body
原始 collision group/mask、Spring 6DOF Joint 字段、兼容别名，以及带字段路径的
`PmxValidationError`。`PmxModel` 已提供 `parse_report`、`is_complete`、
`loaded_sections` 和旧集合名称别名；模型与 PMX 安全包通过严格 mypy。当前基线为
`258 passed, 2 deselected`。W2 尚未关闭：Morph item 全类型、Display Frame、PMX 2.1
占位契约及完整跨引用策略仍需补齐；这些只建立模型表达能力，不代表页面已可编辑。

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

### W5：PMX 2.0 Canonical Writer（P1）

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

### W6：PMX 2.1 与 Soft Body（P2）

**依赖：** W5。  
**主要文件：** `common/pmx/reader.py`、`writer.py`、`types.py`、`validator.py`。

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

### W7：公共 API 迁移与兼容发布（P1/P2）

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

### W8：fast Python 与 Cython parity（P3）

**依赖：** W5；PMX 2.1 完整后再扩大范围。  
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

### W9：PmxDocument 与 lossless patch（P4）

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

Cython 构建和 parity：

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
9. PMX 2.1/Soft Body（W6）
10. fast/Cython parity（W8）
11. document/lossless patch（W9）
12. integration/release/docs（W10）
```

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

- [ ] strict reader 对支持范围内的 PMX 2.0/2.1 到达 EOF。
- [ ] partial reader 的状态、section 和 writer 拒绝行为可测试。
- [ ] canonical writer 覆盖所有已支持字段，没有固定 BDEF1/UV=0 等隐式简化。
- [ ] 7 个本地 PMX 逐文件完成解析证据和临时 round-trip，原件 hash 未变。
- [ ] 合成 fixture 覆盖所有 index size、weight、Morph、IK、Physics、Soft Body 分支。
- [ ] malformed/truncated/unknown feature 都 fail closed，异常带 section/offset。
- [ ] Python/fast/Cython 字段级 parity 全绿，或优化路径明确保持 opt-in。
- [ ] no-op lossless patch 字节完全相同，单字段 patch 通过未修改区域审计。
- [ ] 公共 API、兼容别名、异常、支持矩阵和迁移文档同步。
- [ ] `pytest`、Cython parity、`mkdocs build --strict`、`uv build`、wheel 校验、
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
