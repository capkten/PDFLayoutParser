# Repository Guidelines

## 项目结构与模块组织
核心库代码位于 `src/pdflayoutparser/`。整体采用流水线拆分，`loader.py`、`text_extractor.py`、`table_extractor.py`、`layout_mapper.py`、`layout_builder.py`、`json_writer.py`、`markdown_writer.py` 和 `render_engine.py` 各自负责单一阶段；CLI 入口在 `src/pdflayoutparser/cli.py`。

测试位于 `tests/`，按功能镜像主包结构，例如 `tests/test_table_extractor.py`、`tests/test_pipeline.py`。`out/`、`out_test/`、`out_test2/`、`out_debug/`、`visualization/` 属于运行或调试产物，不应作为源代码修改目标。

## 处理流程与算法
### 总体流水线
`Pipeline.run()` 是唯一的端到端编排入口，实际顺序固定为：

1. `Loader.load()` 读取 PDF 元信息，生成 `Document` 和每页 `Page`
2. `TextExtractor.extract_blocks()` 提取页面文字层级，得到 `Block -> Line -> Word -> Char`
3. `LayoutMapper.map_blocks()` 将文本块转换为 `LayoutElement(type="text")`
4. `TableExtractor.extract()` 检测表格，优先走线框推断，失败时回退到 `PyMuPDF.find_tables()`
5. `ImageExtractor.extract()` 导出嵌入图片资源并补充 `Image` 元数据
6. 根据 `seal_coords` 生成 `Seal` 对象
7. `LayoutBuilder.build()` 合并文本、表格、图片，生成页面级布局列表
8. `RenderEngine.render()` 输出页面 PNG 预览
9. `JSONWriter.write_page()` / `MarkdownWriter.write_page()` 写出单页结果
10. 全部页面结束后，再写出 `output.json` 和 `output.md`

### 文本提取
`TextExtractor` 直接读取 `page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)`：

- 只保留 `type == 0` 的文本块
- 以 `blocks -> lines -> spans` 结构还原 `Block`、`Line`、`Word`
- 如果 PyMuPDF 没有返回 `chars`，则按 span 宽度平均切分，补出字符级 bbox
- `line.text` 由同一行内的 word 直接拼接，`block.text` 由多行用换行拼接

### 表格提取
`TableExtractor` 以“绘图线条推断表格”为主，核心策略如下：

- 从 `page.get_drawings()` 中筛选可见的矩形边框
- 同时识别三类候选线：
  - 细长矩形，按水平/垂直线处理
  - 普通矩形的四条边
  - 填充但很薄的矩形，视为线
- 通过 `page.get_bboxlog()` 过滤被后续不透明填充完全覆盖的边框，避免把背景或遮挡层当作表格线
- 水平线和垂直线分别按很小的容差合并，但不会跨相邻网格过度合并
- 通过线交点构建连通分量，分离互不相关的表格区域
- 在每个区域内优先使用“完整网格建格”，如果发现列过碎、上部行稀疏，则改用“按行建格”
- 对 WPS / Office 风格的 merged-cell 表格，会尝试从填充矩形中提取子行边界，再重建单元格
- 单元格文本用 `page.get_text("words")` 进行回填，按中心点落入哪个 cell 来归属
- 文字回填后会合并过度切分的窄空列，保留结构性空列
- 如果线框法没有表格，或者结果退化为 1x1、碎片过多、列数过大，则回退到 `page.find_tables()`

### 布局合并
`LayoutBuilder` 的规则比较简单，但很重要：

- 先删除中心点落在任意表格 bbox 内的文本块，避免表格文本重复输出
- 再追加 `table` 和 `image` 类型的 `LayoutElement`
- 页面内 `order` 采用当前列表长度递增，不做跨类型二次排序

### 输出写入
- `JSONWriter` 递归序列化整个 `Document`，输出统一 schema；写文件必须使用 `encoding="utf-8"` 且 `ensure_ascii=False`
- `MarkdownWriter` 对普通文本直接原样输出，对表格优先生成 Markdown 表格；当表格过稀疏或列过多时，降级为紧凑文本列表
- 图片和印章在 Markdown 中输出为链接或占位符，不做二进制内嵌
- `RenderEngine` 使用 PyMuPDF 按指定 `dpi` 导出页面 PNG，文件名形如 `page-000.png`

## 模块职责与对话提示
下面这些约定适合作为后续对话的默认上下文，尤其是在你要求我“继续分析代码”“修改算法”或“检查输出行为”时。

### `loader.py`
- 只负责 PDF 打开和页面元信息采集，不承担文本、表格或图片解析
- 任何新增字段都应能从 `fitz.Page` 或 `fitz.Document` 直接得到
- 如果涉及文件名、页数、旋转角度、页面尺寸，优先检查这里

### `text_extractor.py`
- 负责把 PyMuPDF 的页面文本恢复成层级结构
- 默认保持 whitespace，不主动做语义清洗
- 如果字符级 bbox 异常，优先检查 span 到 char 的回退切分逻辑
- 修改这里时要关注 `blocks -> lines -> words -> chars` 的层级一致性

### `layout_mapper.py`
- 负责把文本块转成统一的 `LayoutElement(type="text")`
- 不做表格识别，也不做文本重排
- 如果页面文字顺序或文字内容有问题，先查 `TextExtractor`，再查这里

### `table_extractor.py`
- 这是整个项目里最复杂、最容易引入回归的模块
- 修改时必须先判断是“线框表格”“merged-cell 表格”还是“PyMuPDF 回退表格”
- 算法关注点按优先级排列：
  1. drawing 里的可见矩形边框是否被正确识别
  2. 线条合并是否过松或过紧
  3. 连通分量是否把多个表格误合并或误切开
  4. 建格阶段是否把 merged-cell、窄列、空列处理正确
  5. 文本回填是否把词放进正确的 cell
- 典型排查路径是先看 `h_lines / v_lines`，再看 regions，再看 cells，再看回填后的文本
- 如果你要我分析表格问题，最好直接给出：页码、表格截图、当前 JSON/Markdown 片段、以及是否来自 WPS / Office 风格 PDF

### `image_extractor.py`
- 只负责导出嵌入图片资源和记录 bbox、尺寸、扩展名
- 这里不做版面判断，也不做图片内容识别
- 如果图片位置不准，优先检查 `page.get_image_info()` 与资源顺序是否对应

### `layout_builder.py`
- 负责把 text、table、image、seal 合成页面布局
- 主要约束是避免文本与表格重复输出
- 如果表格文本在 Markdown 或 JSON 里出现两次，通常是这里的过滤条件或者前面的 bbox 判断出了问题

### `render_engine.py`
- 只负责页面渲染，不参与解析
- 任何预览图问题先看 DPI、矩阵和文件输出路径

### `json_writer.py`
- 负责把模型树稳定地序列化成 JSON
- 保持字段名和模型字段一致，不要在 writer 里偷偷改 schema
- 若新增模型字段，必须同步补齐序列化逻辑和测试

### `markdown_writer.py`
- 负责把布局结果转换成可读 Markdown
- 文本、表格、图片、印章的渲染策略都在这里统一
- 表格输出的关键判断是行列密度、非空列数量和是否需要降级为纯文本列表

### `cli.py`
- 只做参数解析和调用 `Pipeline`
- 不要把业务逻辑堆进 CLI

## 后续对话默认提问方式
当你让我继续处理这个项目时，如果问题涉及代码，最好直接给出以下信息中的至少一项：

- 目标文件或模块名
- 当前现象、报错或不符合预期的输出
- 对应页码、样例 PDF、截图或 JSON/Markdown 片段
- 你希望我改的是“算法”“输出格式”“测试”还是“文档”

如果你只说“继续优化表格”或“看看哪里有问题”，我会默认先按 `table_extractor.py` 的线框提取和回填链路排查。

## 构建、测试与开发命令
安装可编辑环境与开发依赖：

```bash
pip install -e ".[dev]"
```

运行全部测试：

```bash
pytest
```

迭代时运行单个测试文件：

```bash
pytest tests/test_table_extractor.py -v
```

本地运行 CLI：

```bash
python -m pdflayoutparser.cli input.pdf -o out --dpi 200
```

## 编码风格与命名约定
使用 Python 3.10+，统一 4 空格缩进。模块名、函数名、变量名使用 `snake_case`，类名使用 `PascalCase`，测试文件命名为 `test_*.py`。字符串优先使用双引号；模块、类、关键函数在行为不直观时补充简短 docstring。

保持现有流水线结构，避免把解析逻辑堆到 `cli.py` 或测试辅助代码中。新增功能优先落到职责明确的模块，再由 `pipeline.py` 串联。

## 编码规范
所有源码、配置、Markdown、JSON、测试数据及其他文本文件一律使用 UTF-8 编码。创建、读取、修改、重写文件时，都必须按 UTF-8 处理；凡是代码中显式打开文本文件，必须传入 `encoding="utf-8"`，不得依赖系统默认编码。

终端重定向、调试脚本、一次性分析脚本、测试辅助代码也要遵守 UTF-8 规则，避免写出 GBK、ANSI 或其他本地编码文件。JSON 序列化统一使用 `ensure_ascii=False`，避免中文被转义。

新增或修改公开函数时优先补充类型注解；复杂数据流优先使用现有 `models.py` 中的数据模型，不要随意改成松散字典。异常处理要贴近边界层，例如 PDF 读取、文件输出、CLI 参数解析；不要用空 `except` 吞掉错误。

修改表格提取、布局映射、渲染输出时，优先复用现有辅助函数和阶段边界，避免跨模块复制同一套 bbox、文本拼接或排序逻辑。

## 测试规范
项目使用 `pytest`，公共 fixture 位于 `tests/conftest.py`。行为变更必须同步补测试，尤其是 `table_extractor.py`、`pipeline.py`、输出写入器及 CLI。优先在测试中动态构造 PDF，而不是提交新的二进制样例文件。

如果修复的是解析边界问题，至少补一个能复现旧问题的测试用例。提交前至少运行受影响模块测试；改动主流程时运行完整 `pytest`。

## 提交与 Pull Request 规范
Git 历史已采用简短的 Conventional Commits 前缀，例如 `feat:`、`docs:`。继续保持这一风格，例如 `fix: handle merged table rows`，每次提交只聚焦一个主题。

Pull Request 需要说明修改了什么解析行为、影响哪些模块、如何验证；涉及布局检测变化时，附上前后输出片段、JSON 差异或截图。若有关联问题，附上 issue 链接，并写明实际执行过的 `pytest` 命令。
