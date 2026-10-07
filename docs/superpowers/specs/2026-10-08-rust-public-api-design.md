# 独立公开 PDF API 全 Rust 化设计

日期：2026-10-08；状态：待用户审阅

## 背景

`dev-rust` 已将多项表格结构算法实现为 Rust，但 `PDFParser` 的若干独立公开接口仍由 Python/PyMuPDF 打开 PDF、读取页面数据、执行提取或渲染。另一方面，`tools/pdfium_probe` 已有 PDFium 页面读取、归一化、分类、整页渲染和表格恢复代码，但它是独立 Rust 工具，没有接入 Python 公共 API；当前 JSON 导出也没有嵌入图片。

本设计把用户要求的“全部切成 Rust”定义为：对文件路径输入，目标 API 的 PDF 打开、页面读取、业务提取/分类、图像渲染和文件写入均在 Rust 中执行。Python 可以保留公开 API、参数校验、PyO3 调用、结果数据类转换和既有 `ApiResult` 包装，但不能在这些调用路径上使用 PyMuPDF 提取或渲染，也不能在 Rust 失败时回退到 PyMuPDF。

## 目标接口

- `PDFParser.extract_text_in_region`
- `PDFParser.extract_table_in_region`
- `PDFParser.extract_table_structure`
- `PDFParser.extract_images`
- `PDFParser.extract_image_in_region`
- `PDFParser.render_pages`
- `PDFParser.render_region`
- `PDFParser.classify_page`
- `classify_pdf_page` 与 `classify_page_type`

`PDFParser.parse()` 主流水线不在本次范围内。它及其他未列出的接口可以继续使用当前实现。

## 总体架构

采用共享 Rust/PDFium 核心库，通过现有 PyO3 扩展 `_pdf_fast` 暴露面向 PDF 路径、页码、区域和输出参数的高层调用。Python 公共方法调用这些入口，再把 Rust DTO 转成既有 `Block`、`Table`、`TableStructure`、`Image`、`RenderInfo` 等数据类。

将 `tools/pdfium_probe` 当前与 PDF 读取、页面归一化、分类、渲染和表格处理有关的实现整理为可复用 Rust 库；命令行探针继续复用该库。Rust 扩展依赖这个共享实现，避免在 CLI 和 Python 扩展中各维护一套读取及归一化逻辑。扩展提供一组批量入口，每次调用只打开一次 Rust 文档；多区域操作在同一文档句柄内完成。

### 处理路径

1. Python 保留原有参数形式，将路径、页码、区域、DPI、输出目录和配置传入 PyO3。
2. Rust 解析区域坐标并加载 PDFium 文档。
3. Rust 读取页面原生文本、图形和图像对象，构建页面 DTO，并运行分类、表格结构恢复或区域筛选。
4. Rust 完成 PNG 和嵌入图像文件写入，并返回结构化结果 DTO。
5. Python 只负责 DTO 到既有数据类的转换和 `ApiResult` 包装。

`extract_image_in_region` 的图像枚举、区域相交筛选和文件副作用均在同一次 Rust 调用中完成；不得通过 Python 的 `extract_images()` 再筛选。`extract_table_structure` 的单元格字符文本和坐标也必须由 Rust 页面数据产生，不调用 `page.get_text("dict")`。

## 输入与兼容边界

- 文件路径入口由 Rust 打开 PDF；`page_indices`、归一化坐标、区域列表和 DPI 的现有含义保持不变。
- `classify_pdf_page` 当前支持路径、`fitz.Document` 和 `fitz.Page`。继续保留这些输入：路径直接交给 Rust；MuPDF 对象仅由 Python 序列化其原 PDF 字节，再连同页码交给 Rust。Python 不从这些对象提取页面文本、图像或分类特征。
- `PDFParser(source=Document)` 没有原始 PDF 字节。该输入形式的 `classify_page` 继续返回传入 `Document` 中已有的 `page_type`；不从结构化结果重建 PDF。对文件路径创建的 `PDFParser`，即使此前已经缓存 `Document`，`classify_page` 也必须调用 Rust 重新分类，不能走 Python 缓存短路。其他需要读取 PDF 的目标方法仍遵循现有的文件路径要求。
- API 名称、参数、单区域/多区域返回形态、`ApiResult.code` 语义、消息、空结果和错误包装保持兼容。
- `render_pages` 保持 `page-{page_index:03d}.png` 文件命名、DPI 与页面类型标签行为；`render_region` 保持 `region-{page_index:03d}-{region_index:03d}.png` 命名和裁剪语义。
- 嵌入图像导出保持 `Image` 的页码、资源索引、尺寸、扩展名、边界框和文件路径字段。区域图像接口仍会先导出其涉及页面上的全部图像文件，再仅返回与区域相交的图像，保持当前副作用与返回选择。

## Rust 组件职责

| 组件 | 职责 |
| --- | --- |
| 共享 PDFium 核心库 | 加载 PDFium、读取页面文本/路径/图像对象、页面坐标变换、页面归一化和 Rust DTO |
| 页面分类 | 使用 Rust 页面数据运行 `vector` / `scanned` 判定及原因规则 |
| 表格处理 | 复用 Rust 有线与无线表格引擎；区域入口直接恢复指定区域；全页结构入口生成含单元格坐标和字符文本的结构 |
| 图像处理 | 枚举 PDF 页面中的嵌入图像放置对象，导出图像内容并生成与原 API 对应的图像元数据 |
| 渲染 | 使用 PDFium 渲染整页或裁剪区域；Rust 端应用整页页面类型标签并写入 PNG |
| PyO3 与 Python 兼容层 | 传递输入、映射结果 DTO、构造现有数据类和 `ApiResult`；不包含 PDF 页面提取算法 |

ONNX 表格检测若由目标入口使用，继续在 Rust 侧通过现有 Rust ONNX Runtime 集成执行。Python `ml_model_path` 与 `ml_confidence` 参数传给 Rust；不可为了复用模型而调用 Python 检测器。

## PDFium 运行时与打包

优先使用 `tools/pdfium_probe/manifest.json` 中登记的 PDFium 动态库，运行时也可按当前探针行为尝试系统 PDFium。项目 manifest 列出了 `win-x64`、`linux-x64`、`mac-x64` 和 `mac-arm64`；发布包应为这些目标包含相应原生库，并让 Rust 扩展从已安装包路径解析库位置。找不到可用 PDFium 时，返回明确错误并由现有包装转换成 `ApiResult(code=-1)`，不能回退到 PyMuPDF。

## 错误与结果处理

Rust 错误通过 PyO3 转成 Python 异常，再由现有 `_execute_result` 返回 `ApiResult(code=-1, message=..., data=None)`。成功但无内容时仍返回 `code=0` 与现有空结果消息；存在内容时返回 `code=1` 与现有成功消息。输出目录创建、文件写入失败等错误也沿用该包装。

不得静默吞掉 Rust 错误后返回空结果，也不得因某个表格、图像或渲染子步骤失败而改走 Python 实现。

## 验证与验收

1. **Rust 单元与集成测试**：覆盖页面读取、区域边界、页码范围、图像对象、裁剪渲染、分类规则及 Rust 表格结构输出。
2. **Python 公共 API 回归**：运行现有 `test_pdf_parser.py`、`test_classify_pdf_page.py`、`test_page_classifier.py`、图像和表格区域相关测试；补齐文件路径和 `fitz` 对象输入测试。
3. **Rust 路径证明**：对文件路径入口将 PyMuPDF 的页面读取/提取/渲染入口替换为会立即失败的桩，目标 API 仍应成功或按 Rust 错误语义失败；确认区域图像接口不经 Python 的 `extract_images()` 组合。
4. **差异核对**：在同一批固定 PDF 和页码上保存迁移前的 Python 基线，并与 Rust 结果比较。检查返回类型、状态码、文本与行序、分类、表格行列/单元格/跨度、图像数量与元数据、渲染像素尺寸和输出文件。坐标比较采用有明确上限的数值容差；任何无法保持的差异必须在测试报告中逐项列出，不能隐藏在“算法实现不同”之下。
5. **耗时比较**：对每个目标入口使用相同 PDF、页码、区域、DPI 和输出条件，分别运行 Python 基线与 Rust 版本；预热后重复测量并报告中位耗时。该设计要求产出可核对的性能数据，不预设 Rust 必须快于 Python 的阈值。
6. **包构建**：验证 PyO3 扩展编译、Rust 库链接、PDFium 运行时定位和当前 Windows 环境中的安装包构建；其余 manifest 平台至少核对打包资源配置。
7. **提交检查**：运行相关测试、`cargo test`、`git diff --check`，记录受缺失样例、模型或原生运行库影响而无法完成的验证。

完成标准是每个目标的文件路径调用都由 Rust 完成 PDF 页面读取和对应处理，无 Python/PyMuPDF 后备提取；既有公开结果契约通过回归或差异得到验证；运行时资源在目标包中可解析；耗时与结果差异均有实测记录。

## 主要风险

- PyMuPDF 与 PDFium 对文本顺序、字间距、字框、页面旋转、图像放置和像素取整的处理可能存在差异，需要以测试数据定位并收敛。
- PDFium 的嵌入图像对象导出和当前 `ImageExtractor` 按页面资源/xref 匹配 bbox 的方式不完全相同；Rust 实现必须覆盖重复放置、同一资源多次出现和无页面放置对象等情况。
- `_pdf_fast` 当前尚未链接 PDFium 或 Rust ONNX Runtime；扩展依赖与多平台原生库打包需要独立构建验证。
- 本次不迁移 `parse()` 主流水线，所以主解析 API 仍可能通过 Python/PyMuPDF 处理 PDF；该范围边界必须在交付说明中明确。
