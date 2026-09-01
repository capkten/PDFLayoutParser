# 中英文无线表格提取分离设计

## 背景与问题

当前无线表格代码主要集中在
`src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py`，同一个
`WirelessTableExtractor` 同时包含英文斑马纹、英文通用无线、英文 words 文本对齐，
以及中文/混合页面的 native-span 分流。中文结构恢复的底层代码虽然已经位于
`wireless_table_recovery.py` 和 `wireless_structure/`，但入口仍与英文实现耦合。

英文和中文逻辑由不同开发者维护，继续在统一文件中修改会增加合并冲突；直接移动
代码又可能破坏以下现有依赖：

- `hexai_pdf_parser.wireless_table_extractor` 的动态兼容模块路径；
- `hexai_pdf_parser.tables.extractors.wireless_table_extractor` 的直接导入；
- 测试对 `WirelessTableExtractor`、`_RowData` 和
  `recover_cells_from_region` 的 monkeypatch；
- `TableExtractor`、`TableTemplateEngine` 和
  `PersonalCreditReportTableExtractor` 的旧方法签名。

## 目标

1. 将英文无线提取算法集中到独立的英文 Python 文件。
2. 将中文/混合无线提取算法集中到独立的中文 Python 文件，并保持 native-span
   结构恢复约束。
3. 让 `TableExtractor` 只负责页面级编排、语言分流和兼容转发，不再保存中英文
   混杂的无线算法实现。
4. 保持现有公共入口、测试导入路径、monkeypatch 目标和表格输出优先级。
5. 让后续中英文开发主要修改各自文件，减少同文件合并冲突。

## 非目标

- 不改变有线表格线段提取、ML 模型、布局规则和表头归一化算法。
- 不重写 native-span 的列带、逻辑网格、跨度和 occupancy 校验算法。
- 不因为本次文件拆分删除已有旧模块别名或修改现有测试的导入方式。
- 不新增业务关键词驱动的中英文表格判定规则。

## 架构

### 英文策略

新增
`src/hexai_pdf_parser/tables/extractors/english_table_extractor.py`，定义
`EnglishTableExtractor`，负责：

- 英文斑马纹背景提取；
- 英文通用无线表格提取；
- 英文 words 文本对齐和物理横线引导逻辑；
- 英文行、列、货币符号、表头、Cell 构造辅助方法；
- 当前 `wireless_table_extractor.py` 中的英文实现；
- 当前 `TableExtractor` 中的旧 words 文本对齐实现。

该模块不能导入中文结构恢复策略。为了保留已有 native-borderless 行为，
英文文本候选方法接收一个可选的 native-span 恢复回调；英文模块只依赖回调接口，
不依赖中文类。

### 中文策略

新增
`src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py`，定义
`ChineseTableExtractor`，负责：

- `zh` 和 `mixed` 页面上的区域提取；
- `recover_cells_from_region` 调用；
- native-span 页面级候选恢复及诊断状态转发；
- 中文/混合页面的失败处理。

中文路径只消费 native span、atom、列带、物理 Cell 和逻辑 Cell。它不调用英文
斑马纹，也不通过 `page.get_text("words")` 重建中文表格。

### 兼容门面

保留
`src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py`，但将其缩减为
`WirelessTableExtractor` 门面：

- 继承或明确转发英文策略方法，使历史调用仍可使用
  `extract_zebra`、`extract_general_wireless`、`extract_cells_from_region` 和
  `_RowData`；
- 根据 `page_language` 将 `extract` 转发给英文或中文策略；
- 将旧路径的 `recover_cells_from_region` 包装为动态回调，保证已有
  monkeypatch 目标继续生效；
- 不再包含英文或中文算法实现。

### 页面级编排

`src/hexai_pdf_parser/tables/table_extractor.py` 保留：

- 有线表格识别；
- ML 区域检测和有线优先组合；
- 布局规则、表头归一化和页面边界裁剪；
- `_extract_via_text_alignment` 的原有公开/半公开方法签名。

其中 `_extract_via_text_alignment` 只检测页面语言、调用门面策略，并转发
`_last_wireless_recovery` 和 `_last_text_alignment_debug`。原有被测试、模板引擎或
下游类调用的文本辅助方法保留为兼容转发，实际算法位于英文策略或 native-span
模块中。

## 调用与数据流

```text
TableExtractor.extract(page)
  -> detect_page_language(page)
  -> _detect_rule_candidates(page, language)
       en:       EnglishTableExtractor.extract_zebra
       zh/mixed: 跳过 extract_zebra
       both:     wired candidates + language text candidates
  -> _extract_model_tables(page, language)
       en:       EnglishTableExtractor.extract
       zh/mixed: ChineseTableExtractor.extract
  -> layout rules / header normalization / page clamp
```

文本候选保留以下优先级：

- 中文/混合页面使用 native-span 恢复；恢复失败时不转入英文 words 重建。
- 英文页面先保留当前 native-span 候选优先行为；没有可接受 native-span 结果时，
  才执行英文 words 文本对齐。
- 有线表格和 ML 区域的既有优先关系不变。

## 稳定接口与模块路径

新增正式类和路径：

- `hexai_pdf_parser.tables.extractors.english_table_extractor.EnglishTableExtractor`
- `hexai_pdf_parser.tables.extractors.chinese_table_extractor.ChineseTableExtractor`
- `hexai_pdf_parser.english_table_extractor`
- `hexai_pdf_parser.chinese_table_extractor`

继续支持：

- `hexai_pdf_parser.wireless_table_extractor.WirelessTableExtractor`
- `hexai_pdf_parser.tables.extractors.wireless_table_extractor.WirelessTableExtractor`
- `hexai_pdf_parser.tables.extractors.wireless_table_extractor._RowData`
- 旧测试对
  `hexai_pdf_parser.tables.extractors.wireless_table_extractor.recover_cells_from_region`
  的 monkeypatch。

顶层动态兼容映射新增 `english_table_extractor` 和
`chinese_table_extractor`，并保持模块对象可正常导入。新旧路径不会要求测试迁移。

## 异常与回退

- 页面语言检测异常继续沿用现有默认语言行为。
- 英文专用方法遇到轻量 page double 缺失 drawing/text API 时，沿用现有空结果和
  words 回退处理。
- 中文策略和 native-span 底层的异常边界保持原实现；门面不吞掉策略异常。
- 中文/混合页面不会因为英文策略为空而改走英文斑马纹或 legacy words 重建。
- 拆分过程中避免双向导入：英文策略只依赖基础模型和回调，中文策略只依赖
  native-span 结构模块，门面依赖两种策略，页面编排依赖门面。

## 测试设计

实现前先添加最小失败测试，至少覆盖：

1. 两个新类可以独立导入，且模块归属分别为英文、中文文件。
2. 顶层旧别名和新的英文/中文别名都可以导入。
3. 门面对 `en`、`zh`、`mixed` 做正确分流。
4. 中文/混合分流不会调用英文 `extract_zebra`。
5. 旧门面仍可直接调用英文方法和 `_RowData`。
6. 旧模块路径上的 `recover_cells_from_region` monkeypatch 仍会影响中文区域提取。
7. `TableExtractor._extract_via_text_alignment` 的签名、语言转发和 debug 状态
   保持可用。
8. `TableExtractor` 的旧文本辅助方法仍能被测试和模板引擎调用。

随后运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_extractor_split.py
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_table_recovery.py tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rule_first_table_detection.py tests/test_financial_header_normalizer.py
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_table_extractor.py
```

同时执行 `git diff --check`。已有缺失样例 PDF、模型路径期望或版本差异导致的失败
必须单独记录，不能归因于本次拆分。

## 验收条件

- 英文算法主体不再位于 `wireless_table_extractor.py` 或 `table_extractor.py`。
- 中文/混合无线算法主体不依赖英文策略文件。
- 兼容门面只包含分流和适配逻辑。
- 旧导入、旧方法签名和测试 monkeypatch 路径可用。
- 新增拆分测试以及现有无线、结构、规则相关测试通过。
- 所有未涉及本次任务的工作区改动保持原样。
- `changes.md` 以中文记录本次拆分的根因、文件边界、兼容路径和测试结果。
