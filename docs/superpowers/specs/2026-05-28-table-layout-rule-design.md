# 表格版式规则系统设计规格

日期：2026-05-28

## 概述

当前项目的表格提取已经具备三条基础链路：

- 线框表格：以 `page.get_drawings()` 和边线建格为主；
- PyMuPDF 回退表格：用于兜底；
- 文本对齐表格：用于三线表、弱线框表和无线表。

现阶段的主要问题不是“没有算法入口”，而是：

1. 区域发现与结构恢复耦合过深；
2. 大量阈值和特殊判断散落在 `table_extractor.py`、`text_region_detector.py`；
3. 缺少“按版式组织规则”的能力；
4. 简单场景只能改硬编码，复杂场景只能继续堆条件分支。

本设计的目标是在不推翻现有通用主链的前提下，引入一套可扩展的“版式驱动表格规则系统”，同时支持：

- 简单场景通过参数配置完成；
- 复杂场景通过 Python 函数规则完成；
- 区域规则与结构规则彻底分离；
- 字段主要用于判定版式，而不是直接替代通用结构算法。

---

## 目标

本次设计要解决以下问题：

1. 允许根据字段、字段顺序、字段距离、表头特征判断某页或某块区域属于哪种表格版式；
2. 在命中版式后，分别对“表格区域”和“表格结构”施加不同规则；
3. 让大多数常见版式只靠 JSON 配置即可扩展；
4. 让复杂版式可以通过函数 handler 接入，而不污染通用主链；
5. 保持现有 `Pipeline`、`TableExtractor`、`Table` / `Cell` 输出模型基本不变。

---

## 非目标

本阶段不做以下事情：

1. 不重写现有线框表格算法；
2. 不引入新的 OCR、检测模型或训练流程；
3. 不修改公开输出 schema；
4. 不把所有业务表格都模板化成强依赖字段的专用解析器；
5. 不要求首版就覆盖所有复杂版式。

---

## 核心设计原则

### 1. 版式是一级概念，字段是判定版式的重要信号

字段本身不应直接等于结构规则。更合理的顺序是：

1. 先根据字段、顺序、距离、重复行特征判断版式；
2. 再由版式绑定区域规则和结构规则；
3. 通用算法仍然是主链，版式规则只做增强和修正。

### 2. 区域和结构必须拆开

“哪里是表格”和“表格内部怎么建结构”不是同一个问题。

- 区域规则负责表格 bbox 的确认、扩张、截断、合并和排除；
- 结构规则负责表头识别、列锚点、主列选择、列拆分、末行裁剪等。

两者既不共享同一套规则对象，也不在一个函数里混写。

### 3. 通用主链优先，规则系统做增强

执行顺序固定为：

1. 先跑现有通用检测链路；
2. 再匹配版式；
3. 再分别执行区域修正和结构修正。

这意味着规则系统不是替代 `TableExtractor`，而是附着在其上的增强层。

### 4. 双轨扩展机制

规则系统必须同时支持两种扩展方式：

- 参数型规则：适用于大部分中等复杂度场景；
- 函数型规则：适用于参数表达困难、需要上下文推理的复杂场景。

参数型优先，函数型兜底。

---

## 总体架构

建议将表格规则系统拆成四层：

1. `TableConfig`
   - 全局算法参数；
   - 版式 profile 列表；
   - handler 开关和调试选项。
2. `LayoutProfileMatcher`
   - 根据页面字段和表头特征匹配版式。
3. `RegionRuleEngine`
   - 只处理表格区域修正。
4. `StructureRuleEngine`
   - 只处理表格结构修正。

执行流建议如下：

1. `TableExtractor.extract(page)` 先运行现有通用链路，得到初始表格结果；
2. 提取页面级文本行、字段候选、表头候选、重复列对齐特征；
3. `LayoutProfileMatcher` 对页面或候选区域打分，选出命中的 profile；
4. `RegionRuleEngine` 根据 profile 修正区域；
5. 在修正区域内复用现有结构恢复逻辑；
6. `StructureRuleEngine` 根据 profile 修正结构；
7. 若 profile 配置了复杂 handler，则在对应阶段执行函数型规则；
8. 输出统一的 `Table` / `Cell`。

---

## 配置模型

### 1. 全局配置

全局配置用于承接当前散落的通用阈值，例如：

- `line_tolerance`
- `merge_group_tol`
- `row_gap_threshold`
- `fallback_max_cols`
- `fallback_max_tables`
- 文本行聚类、列 guide 聚类、区域合并等通用阈值

这一层解决“硬编码外置”的问题，不携带业务语义。

### 2. 版式配置

建议以 `LayoutProfile` 为核心对象：

```python
@dataclass
class LayoutProfile:
    name: str
    enabled: bool = True
    priority: int = 100
    matcher: MatcherConfig
    region_rules: RegionRuleSet
    structure_rules: StructureRuleSet
    region_handler: str | None = None
    structure_handler: str | None = None
```

#### `MatcherConfig`

用于版式匹配，首版建议支持：

- `required_keywords`
- `optional_keywords`
- `forbidden_keywords`
- `keyword_order`
- `keyword_distance`
- `min_repeat_rows`
- `header_band_limit`
- `min_match_score`

#### `RegionRuleSet`

只处理区域，首版建议支持：

- 字段锚点是否可生成候选区域；
- 命中字段后向下扩张多少行；
- 遇到 `注`、`说明`、`单位` 等是否截断；
- 相邻区域在什么距离内合并；
- 是否要求区域内存在重复列对齐；
- 是否允许正文段落进入区域。

#### `StructureRuleSet`

只处理结构，首版建议支持：

- 表头识别方式；
- 主列识别方式；
- 列 guide 来源优先级；
- 数值列是否强约束右对齐；
- 是否允许某些表头一拆二；
- 末尾汇总、页码、注释行裁剪策略。

---

## 参数型规则与函数型规则

### 参数型规则

参数型规则适合以下场景：

- 只需要几个字段命中条件；
- 规则主要表现为阈值、距离、顺序、开关；
- 对区域和结构的修正比较局部、稳定。

优点是：

- 易配置；
- 易测试；
- 易在 CLI / API 中透传；
- 不需要修改源码即可扩展常见版式。

### 函数型规则

函数型规则适合以下场景：

- 版式内部需要复杂上下文推理；
- 需要同时参考页面多处文本和候选表格；
- 参数模型难以表达；
- 同一版式内部还要做精细的区域裁剪或结构重构。

函数型规则不应允许任意字符串 import。建议使用注册表：

```python
REGION_RULE_HANDLERS = {
    "finance.statement_v1": finance_statement_region_handler,
}

STRUCTURE_RULE_HANDLERS = {
    "finance.statement_v1": finance_statement_structure_handler,
}
```

配置中只写 handler 名称，运行时通过注册表解析。

---

## 模块划分建议

建议新增以下模块：

- `src/hexai_pdf_parser/table_config.py`
  - 全局配置与 profile 数据类；
  - JSON 加载与校验。
- `src/hexai_pdf_parser/table_profile_matcher.py`
  - 页面级 / 候选区域级版式匹配。
- `src/hexai_pdf_parser/table_region_rules.py`
  - 参数型区域规则执行器。
- `src/hexai_pdf_parser/table_structure_rules.py`
  - 参数型结构规则执行器。
- `src/hexai_pdf_parser/table_rule_handlers.py`
  - 函数型规则注册表和公共接口。

现有模块改造建议：

- `src/hexai_pdf_parser/table_extractor.py`
  - 从“算法 + 特殊规则混写”改为“通用主链 + 规则编排入口”。
- `src/hexai_pdf_parser/text_region_detector.py`
  - 接收通用配置，消除散落硬编码。
- `src/hexai_pdf_parser/pipeline.py`
  - 透传 `table_config`。
- `src/hexai_pdf_parser/cli.py`
  - 增加 `--table-config`。

---

## 中间结果设计

为了避免直接在最终 `Table` 上反复打补丁，建议在 `table_extractor.py` 内部引入两个中间模型：

### `TableRegionCandidate`

包含：

- `bbox`
- `source`
- `matched_profile`
- `score`
- `matched_keywords`
- `diagnostics`

### `TableStructureCandidate`

包含：

- `region_bbox`
- `rows`
- `header_rows`
- `guides`
- `cells`
- `matched_profile`
- `diagnostics`

区域规则修改 `TableRegionCandidate`，结构规则修改 `TableStructureCandidate`，最后统一落到现有 `Table` 模型。

这样可以显著降低规则系统和输出 schema 的耦合。

---

## 与当前代码的关系

### 1. 对现有线框表逻辑的影响

线框表链路保留，不作为首轮重构重点。

规则系统主要影响的是：

- 文本对齐表区域确认；
- 表头与列结构修正；
- 少量线框表的区域裁剪和末行修正。

### 2. 对现有 `TableExtractor.extract()` 的影响

`extract()` 仍然是对外唯一入口，但内部职责会变化为：

1. 跑通用主链；
2. 收集页面特征；
3. 匹配 profile；
4. 执行区域修正；
5. 执行结构修正；
6. 返回最终表格。

### 3. 对 `Pipeline` 的影响

`Pipeline` 只负责透传配置，不承担规则逻辑。

---

## 测试策略

测试需要分四层：

1. 配置层测试
   - JSON 加载；
   - 默认值；
   - 非法字段校验；
   - handler 名称解析。
2. 匹配层测试
   - 字段命中；
   - 顺序命中；
   - 距离约束；
   - profile 优先级。
3. 规则层测试
   - 区域扩张；
   - 截断；
   - 区域合并；
   - 表头识别；
   - 主列识别；
   - 末行裁剪。
4. 端到端回归测试
   - 线框表不回归；
   - 简单无线表可通过纯配置修正；
   - 复杂版式可通过 handler 修正。

优先使用动态构造 PDF 的方式复现问题，不引入新的二进制样例。

---

## 风险与控制

### 1. 版式误判

风险：错误命中 profile 后会带偏区域和结构修正。

控制方式：

- profile 打分而不是硬命中；
- 支持 `priority + score` 联合排序；
- 允许低置信度时不执行专用规则。

### 2. 参数系统膨胀

风险：为覆盖复杂场景不断往 JSON 里塞例外参数，最后变成不可维护的伪编程语言。

控制方式：

- 只把稳定、通用、局部的行为参数化；
- 复杂逻辑及时转 handler。

### 3. 区域和结构再次耦合

风险：实现时为了省事，在同一个函数里同时改 bbox 和 cell。

控制方式：

- 明确中间模型；
- 区域规则模块不得直接操作 `cells`；
- 结构规则模块不得回写页面级候选区域列表。

### 4. 回归现有主链

风险：规则系统引入后影响普通线框表或未配置 profile 的页面。

控制方式：

- 默认无 profile 时行为保持现状；
- 规则执行必须显式启用；
- 补充回归测试。

---

## 推荐实施顺序

建议按以下顺序推进：

1. 先做 `table_config.py`，把通用参数和 profile 数据模型立住；
2. 再做 `LayoutProfileMatcher`，先支持字段、顺序、距离；
3. 再做 `RegionRuleEngine`，先覆盖区域扩张、截断、合并；
4. 再做 `StructureRuleEngine`，先覆盖表头、主列、末行；
5. 最后接入函数型 handler。

这样能先把“多数版式靠参数配置”打通，再为复杂版式留稳定扩展点。

---

## 成功标准

设计落地后的成功标准是：

1. 不修改源码即可通过配置新增一批中等复杂度版式；
2. 复杂版式能通过 handler 接入，而不是继续把条件堆进 `table_extractor.py`；
3. 区域规则和结构规则在代码和配置上都清晰分离；
4. 未启用 profile 时，现有主链行为不变；
5. 新系统的入口和调试路径清晰，便于后续针对具体页码排查。
