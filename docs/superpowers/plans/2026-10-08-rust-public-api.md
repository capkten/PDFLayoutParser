# 独立公开 PDF API 全 Rust 化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将设计说明列出的独立 PDF API 改为由 Rust/PDFium 完成 PDF 打开、页面读取、提取、分类、渲染和文件写入，同时保留 Python 公共签名与返回契约。

**Architecture:** 把 tools/pdfium_probe 的页面读取与处理整理成可复用 Rust library crate，由根目录 PyO3 扩展 _pdf_fast 调用。新增轻量 Python 适配模块供 PDFParser 和分类函数使用；Python 只传参数、适配 fitz 对象源字节、转换 DTO 和包装 ApiResult。

**Tech Stack:** Rust 2021、PyO3 =0.22.6 / abi3-py37、pdfium-render 0.8.28、Rust ONNX Runtime 2.0.0-rc.13、PyMuPDF 兼容层、pytest、Maturin 1.8.7。

**Spec:** docs/superpowers/specs/2026-10-08-rust-public-api-design.md

## Global Constraints

- Rust 依赖的 PDFium 版本来源于 tools/pdfium_probe/manifest.json 中的 chromium/8066。
- Python 最低版本保持 >=3.7，PyO3 保持 abi3-py37。
- 文件路径入口禁止调用 PyMuPDF 页面读取、提取和渲染；Rust 出错时不得回退到 Python。
- PDFParser.parse() 主流水线不迁移；路径创建的 PDFParser.classify_page() 即使已有 Python Document 缓存也必须走 Rust。
- classify_pdf_page / classify_page_type 保留 fitz.Page、fitz.Document 输入，通过序列化源 PDF 字节交给 Rust。
- PDFParser(source=Document) 的 classify_page() 保留已缓存 page_type；该数据对象不含原 PDF。
- 保持单区域/多区域结果形态、现有状态码和消息、文件命名、页面类型标签、图像导出副作用以及结构数据类。
- 新增行为必须测试先行；将迁移前 Python 输出保存为可重放基线，并记录每个目标 API 的 Python/Rust 耗时中位数。
- Rust library、扩展和包内 PDFium 动态库均需在当前 Windows x64 环境验证；其余 manifest 目标至少验证资源映射。

---

## File Map

| 文件 | 职责 |
| --- | --- |
| tools/pdfium_probe/src/lib.rs | 可复用 Rust crate 根；导出 PDFium、归一化、分类、表格、渲染模块与 DTO |
| tools/pdfium_probe/src/main.rs | 保留命令行入口和 CLI 参数解析，委托共享 library |
| tools/pdfium_probe/src/public_api.rs | 面向 Python 的请求类型、PDFium 文档打开、公开 API 操作路由和 JSON DTO 输出 |
| tools/pdfium_probe/src/image_extraction.rs | PDFium 页面图像对象、放置 bbox、原图像数据导出 |
| rust/pdfium_api.rs | _pdf_fast PyO3 JSON 请求桥和 fitz 对象字节分类桥 |
| rust/lib.rs | 注册 run_public_pdf_api 与 classify_page_from_bytes 两个 PyO3 入口 |
| src/hexai_pdf_parser/pdfium_api.py | JSON 请求构造、原生库路径定位、Rust 响应到现有 Python 数据类转换 |
| src/hexai_pdf_parser/core/pdf_parser.py | 目标 PDFParser 方法委托 Rust 适配层；保留方法签名和 ApiResult 包装 |
| src/hexai_pdf_parser/extractors/page_classifier.py | classify_pdf_page 与 classify_page_type 改用 Rust 分类入口；保留输入类型和错误语义 |
| Cargo.toml / Cargo.lock | 根 PyO3 crate 依赖共享 pdfium_probe crate 和 JSON 序列化 |
| pyproject.toml | Maturin wheel 中包含包内平台 PDFium 动态库 |
| .gitignore | 忽略由下载/打包步骤生成的包内原生库副本 |
| tools/pdfium_probe/scripts/stage_pdfium_package.py | 校验并把当前构建平台的 PDFium 文件暂存到 Python 包资源目录 |
| tests/test_rust_public_api.py | Rust 路径证明、返回契约、fitz 输入、文件副作用和差异测试 |
| tests/fixtures/rust_public_api/python_baseline.json | 迁移前 Python API 输出基线及对应耗时样本 |
| src/hexai_pdf_parser/debug/rust_public_api_benchmark.py | 同条件运行目标 Rust API 并对照基线耗时 |
| tools/pdfium_probe/changes.md | 中文记录实现范围、根因、测试、差异和性能测量 |

## Rust API 类型契约

tools/pdfium_probe/src/public_api.rs 定义以下共享类型：

~~~rust
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct RegionInput {
    pub page_index: usize,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

#[derive(Debug, serde::Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
pub enum PublicApiOperation {
    ExtractTextInRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        regions: Vec<RegionInput>,
    },
    ExtractTableInRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        regions: Vec<RegionInput>,
        single: bool,
    },
    ExtractTableStructure {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        page_indices: Option<Vec<usize>>,
        regions: Option<Vec<RegionInput>>,
        ml_model_path: Option<String>,
        ml_confidence: f32,
    },
    ExtractImages {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        page_indices: Option<Vec<usize>>,
    },
    ExtractImageInRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        regions: Vec<RegionInput>,
        single: bool,
    },
    RenderPages {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        dpi: f32,
        page_indices: Option<Vec<usize>>,
    },
    RenderRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        regions: Vec<RegionInput>,
        dpi: f32,
        single: bool,
    },
    ClassifyPage {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        page_index: usize,
    },
}

pub fn run_public_api_json(request_json: &str) -> Result<String, String>;
pub fn classify_page_from_pdf_bytes(
    bytes: &[u8],
    page_index: usize,
    pdfium_library_path: Option<&str>,
) -> Result<String, String>;
~~~

run_public_api_json 反序列化请求、加载 PDFium、执行完整 Rust 操作，并通过 `serde_json::json!({"data": data})` 序列化统一响应；图片和渲染结果中的 Image / RenderInfo 字段包含 Rust 写出的文件路径与尺寸，不另造一套重复文件清单。所有 regions 仍使用公开 API 的 0~1 归一化坐标，Rust 按页面大小转换成 points；不把页面对象交还 Python。

根扩展暴露：

~~~rust
#[pyfunction]
fn run_public_pdf_api(request_json: &str) -> PyResult<String>;

#[pyfunction]
fn classify_page_from_bytes(
    pdf_bytes: &[u8],
    page_index: usize,
    pdfium_library_path: Option<&str>,
) -> PyResult<String>;
~~~

Python 的 pdfium_api._run(request: dict) -> Any 仅补入包内 PDFium 库路径、JSON 编解码、取出 `data` 并调用 _pdf_fast.run_public_pdf_api。pdfium_api.classify_bytes(data: bytes, page_index: int) -> str 同样传入可选库路径并调用 _pdf_fast.classify_page_from_bytes。这些接口是唯一的 Python/Rust 高层边界；所有路径操作变体都显式接收可选 pdfium_library_path，Rust 优先按该路径加载，否则尝试系统 PDFium。

---

### Task 1: 保存 Python 基线并准备 Rust 路径测试

**Files:**
- Create: tools/pdfium_probe/scripts/capture_public_api_baseline.py
- Create: tests/fixtures/rust_public_api/python_baseline.json
- Create: tests/test_rust_public_api.py
- Modify: tests/test_pdf_parser.py
- Test: tests/test_rust_public_api.py

**Interfaces:**
- Baseline 脚本输入：tests/fixtures/page_000_vector.pdf、page_437_wireless.pdf、page_705_scanned.pdf 和 tests.conftest.make_pdf_with_image 生成的临时图片 PDF。
- 基线字段覆盖 text region、table region、table structure、images、image region、page render、region render 和 page classification；每个 API 先预热 1 次，再采集 5 次耗时中位数。
- 文件路径在 JSON 中规范为相对文件名；导出图片按 SHA-256、扩展名和尺寸核对；渲染 PNG 按尺寸和有效 PNG 解码核对，不要求跨渲染器的文件哈希相同。

- [ ] **Step 1: 新增可运行的基线捕获脚本**

在脚本中定义 FULL_PAGE = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}，逐个调用当前 PDFParser 方法，将 ApiResult 转成稳定 JSON；对每个 API 单独创建临时输出目录，先预热一次，再测量五次并保存耗时样本；将 path 转为 basename。导出图片记录 basename、尺寸和 SHA-256，渲染 PNG 记录 basename、像素尺寸和解码是否成功。

~~~python
def capture_api_snapshot(pdf_path, temp_dir):
    with PDFParser(pdf_path, render_dpi=72) as parser:
        return {
            "text_region": normalize(parser.extract_text_in_region(FULL_PAGE)),
            "table_region": normalize(parser.extract_table_in_region(FULL_PAGE)),
            "table_structure": normalize(parser.extract_table_structure(page_indices=[0])),
            "images": normalize(parser.extract_images(str(temp_dir / "images"), page_indices=[0])),
            "image_region": normalize(
                parser.extract_image_in_region(FULL_PAGE, str(temp_dir / "region-images"))
            ),
            "render_pages": normalize(
                parser.render_pages(str(temp_dir / "renders"), dpi=72, page_indices=[0])
            ),
            "render_region": normalize(
                parser.render_region(FULL_PAGE, str(temp_dir / "crops"), dpi=72)
            ),
            "classify_page": normalize(parser.classify_page(0)),
        }
~~~

- [ ] **Step 2: 用现有 Python 实现生成基线**

Run: python tools/pdfium_probe/scripts/capture_public_api_baseline.py --output tests/fixtures/rust_public_api/python_baseline.json

Expected: JSON 覆盖三个已跟踪 PDF 和临时生成的图片 PDF；每个目标 API 先预热 1 次、再运行 5 次并保存耗时样本，路径字段规范化，导出图像 SHA 与尺寸保存，PNG 渲染图可解码且记录尺寸，脚本返回非零时不得继续迁移。

- [ ] **Step 3: 新增接口差异测试骨架**

~~~python
def test_pdfparser_path_apis_do_not_open_with_pymupdf(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("target API used PyMuPDF")

    monkeypatch.setattr(fitz, "open", forbidden)
    parser = PDFParser(str(FIXTURE_DIR / "page_000_vector.pdf"))
    result = parser.extract_text_in_region(FULL_PAGE)
    assert result.code == 1
    assert result.data
~~~

- [ ] **Step 4: 先运行测试并记录预期失败**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py

Expected: FAIL，因为当前路径仍会调用 PyMuPDF，且 _pdf_fast.run_public_pdf_api 尚不存在。

- [ ] **Step 5: 更新现有缓存句柄断言**

将 test_extract_images_and_render_pages_reuse_parser_handle 改为确认图片和渲染 API 不调用 fitz.open；API 不再复用 Python PDF 句柄，而是在一次 Rust 批量调用中复用一个 PDFium 文档。

- [ ] **Step 6: 提交基线和失败测试**

~~~powershell
git add tests/test_rust_public_api.py tests/test_pdf_parser.py tests/fixtures/rust_public_api/python_baseline.json tools/pdfium_probe/scripts/capture_public_api_baseline.py
git commit -m "test: capture public PDF API baselines"
~~~

### Task 2: 把 pdfium_probe 拆出可复用 Rust library

**Files:**
- Create: tools/pdfium_probe/src/lib.rs
- Modify: tools/pdfium_probe/src/main.rs
- Modify: tools/pdfium_probe/Cargo.toml
- Test: tools/pdfium_probe/src/lib.rs

**Interfaces:**
- CLI 对外命令和参数不变。
- Library 根导出 PdfiumRawPage、PdfiumRawSnapshot、extract_page、render_page_to_image、get_platform_native_lib、classifier、normalizer、pipeline、table_engine。

- [ ] **Step 1: 加入 library 导出冒烟测试**

~~~rust
#[test]
fn library_exports_pdfium_manifest_resolver() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let (path, _) = get_platform_native_lib(&root).expect("manifest should resolve");
    assert!(path.ends_with("pdfium.dll")
        || path.ends_with("libpdfium.so")
        || path.ends_with("libpdfium.dylib"));
}
~~~

- [ ] **Step 2: 运行测试确认 library 入口缺失**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml --lib

Expected: FAIL，因为当前只有 binary crate，没有 src/lib.rs。

- [ ] **Step 3: 抽出共享模块和根级类型**

将 main.rs 中 PDFium 原始结构、坐标转换、extract_page、PNG helper 和 manifest resolver 移到 lib.rs；在 lib.rs 用 pub mod 声明现有 classifier、normalizer、pipeline、layout、markdown、table_engine 等模块。保留 main.rs 的命令参数解析和 main()，改为 use pdfium_probe::{...} 调用 library。

- [ ] **Step 4: 确认 CLI 与原测试仍通过**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml

Expected: 原有 Rust 测试通过，CLI 的 parse 子命令在 --help 下保留原选项。

- [ ] **Step 5: 提交 library 提取**

~~~powershell
git add tools/pdfium_probe/src/lib.rs tools/pdfium_probe/src/main.rs tools/pdfium_probe/Cargo.toml
git commit -m "refactor: expose pdfium probe as a library"
~~~

### Task 3: 新增 Rust API 请求路由、文本区域提取和分类

**Files:**
- Create: tools/pdfium_probe/src/public_api.rs
- Modify: tools/pdfium_probe/src/lib.rs
- Test: tools/pdfium_probe/src/public_api.rs

**Interfaces:**
- 使用本计划前文定义的 RegionInput、PublicApiOperation、run_public_api_json 和 classify_page_from_pdf_bytes。
- ExtractTextInRegion 产出 Vec<Block> 兼容 JSON：text、bbox 与按原顺序排列的 lines。
- ClassifyPage 返回字符串 "vector" 或 "scanned"。

- [ ] **Step 1: 为路径分类和文本区域增加失败测试**

~~~rust
fn fixture(name: &str) -> String {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures")
        .join(name)
        .to_string_lossy()
        .into_owned()
}

#[test]
fn classifies_vector_fixture_through_public_api() {
    let request = serde_json::json!({
        "operation": "classify_page",
        "pdf_path": fixture("page_000_vector.pdf"),
        "page_index": 0
    });
    let value: serde_json::Value =
        serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
    assert_eq!(value["data"], "vector");
}

#[test]
fn extracts_only_words_intersecting_region() {
    let request = serde_json::json!({
        "operation": "extract_text_in_region",
        "pdf_path": fixture("page_000_vector.pdf"),
        "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}]
    });
    let value: serde_json::Value =
        serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
    assert!(!value["data"].as_array().unwrap().is_empty());
}
~~~

- [ ] **Step 2: 运行测试确认操作尚未实现**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml public_api::tests

Expected: FAIL because public_api and both operations have not been added.

- [ ] **Step 3: 实现同一次打开内的 PDFium 加载器**

在 public_api.rs 增加私有 with_document helper，接收 PDF 路径、可选 pdfium_library_path 和闭包；按“请求给定路径、tools/pdfium_probe 当前平台 manifest 路径、系统 PDFium”的顺序逐个尝试，某一路径绑定失败仍继续后续候选；全部失败则返回含尝试路径的错误字符串。run_public_api_json 对 JSON 解析和 PDF 操作错误均返回 Err，不把异常吞成空结果。该 helper 为每个批量请求只加载一次 PDF 文档。

- [ ] **Step 4: 由 Rust 生成区域文字 DTO**

对每个 region 取其 page_index 对应页，在 Rust 中用页面宽高将 0~1 坐标转为 points；基于 `normalize_raw_page` 返回的 `NormalizedPageDto.words` 筛 bbox（字段顺序为 x0、y0、x1、y1、text、block_idx、line_idx、word_idx），按 `(block_idx, line_idx)` 聚合并按 x0 排序，构造和 Python `Block` / `Line` 对应的 JSON DTO。空区域输出 data: []。不调用任何 Python `get_text`。

- [ ] **Step 5: 将页面分类改为 Rust 原始页分类器**

ClassifyPage 调用 extract_page 与 classifier::classify_raw_page。classify_page_from_pdf_bytes 使用 PDFium load_pdf_from_byte_slice 打开序列化输入，并复用完全相同的分类函数；两个入口都按同一顺序解析可选 PDFium 库路径和系统回退。

- [ ] **Step 6: 运行 Rust 测试并提交**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml public_api::tests

Expected: 分类与区域正例、空结果及页码越界测试通过。

~~~powershell
git add tools/pdfium_probe/src/public_api.rs tools/pdfium_probe/src/lib.rs
git commit -m "feat: add Rust text region and classification APIs"
~~~

### Task 4: 实现 Rust 区域表格与结构提取

**Files:**
- Modify: tools/pdfium_probe/src/public_api.rs
- Test: tools/pdfium_probe/src/public_api.rs

**Interfaces:**
- ExtractTableInRegion 返回单区域 Table 或 null；多区域返回表格数组。
- ExtractTableStructure 返回 TableStructure[]；每个 CellStructure 包含 text、索引、bbox、四角坐标、tl/br 行列索引和 cell 内字符级 TextBlock。普通 Table 还保留 confidence、source 与 h_lines / v_lines；横竖线从同页归一化 drawing line 几何生成，无线表没有线数据时保持 None。
- ml_model_path / ml_confidence 在 Rust 侧传给现有 ONNX detector。

- [ ] **Step 1: 增加指定区域 table 和空区域测试**

~~~rust
#[test]
fn recovers_wireless_table_from_designated_region() {
    let request = serde_json::json!({
        "operation": "extract_table_in_region",
        "pdf_path": fixture("page_437_wireless.pdf"),
        "single": true,
        "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
    });
    let value: serde_json::Value =
        serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
    assert!(value["data"]["cells"].as_array().unwrap().len() > 0);
}

#[test]
fn returns_null_for_region_without_table() {
    let request = serde_json::json!({
        "operation": "extract_table_in_region",
        "pdf_path": fixture("page_000_vector.pdf"),
        "single": true,
        "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.2, "y1": 0.2}]
    });
    let value: serde_json::Value =
        serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
    assert!(value["data"].is_null());
}
~~~

- [ ] **Step 2: 运行测试确认表格路由缺失**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml public_api::tests

Expected: table region 和 table structure 用例失败，因为对应 PublicApiOperation 分支尚未实现。

- [ ] **Step 3: 实现 Rust 直接区域表格恢复**

读取并归一化一次页面后调用 table_engine::recover_table_in_region。保持有线优先、无线补充、候选有效性和现有 Rust 表格 DTO；多区域时在同一 document 上循环，单区域无结果为 JSON null，多区域不添加空表。普通 Table 的 h_lines / v_lines 从 table bbox 内的 NormalizedPageDto.page_snapshot.drawings 生成；若没有线数据则保留 Python 模型的 None。

- [ ] **Step 4: 从 native span 构造字符级 TableStructure**

为每个 Rust table cell 按 bbox 从 `normalize_raw_page(...).page_snapshot.spans[].characters` 选字符，按页面对象顺序建立 `TextBlock` 与 `TextChar`；cell 坐标四角由 bbox 直接生成；`tl_row` / `tl_col` / `br_row` / `br_col` 按 rowspan / colspan 计算。Python 适配时使用 `CellStructure`（而非普通表格的 `Cell`）。不得经 Python 页面字典补字。

- [ ] **Step 5: 全页/区域模式都覆盖**

regions=Some 时处理区域覆盖的页面并只输出 bbox 与 region 相交的表；否则遍历 page_indices 或全页。初始化一次 Rust `YoloTableDetector`（显式 ml_model_path 优先，未传时用 `detector::resolve_default_model_path()`），按 `ml_confidence` 和现有 DPI 配置生成候选，再由现有 Rust wired/wireless recovery 生成完整 cells；无可用模型时只使用 Rust 能生成的候选，不调用 Python 检测器。

- [ ] **Step 6: 运行 Rust 表格测试并提交**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml public_api::tests

Expected: page_437_wireless.pdf 至少恢复一个非空表；全页和指定区域的 cell 文本、坐标、跨度和 occupancy 检查通过。

~~~powershell
git add tools/pdfium_probe/src/public_api.rs
git commit -m "feat: expose Rust region table APIs"
~~~

### Task 5: 实现嵌入图像导出与区域筛选

**Files:**
- Create: tools/pdfium_probe/src/image_extraction.rs
- Modify: tools/pdfium_probe/src/lib.rs
- Modify: tools/pdfium_probe/src/public_api.rs
- Test: tests/test_rust_public_api.py

**Interfaces:**
- ExtractImages 返回 Image[]，图像文件名格式 page-{page_index:03d}-img-{resource_index:03d}.{ext}。
- ExtractImageInRegion 在 Rust 内先导出目标页面全部图片文件，然后按 bbox 筛选返回项；单区域返回首个匹配或 null，多区域返回扁平列表。

- [ ] **Step 1: 新增有两个相同资源放置位置的图片 PDF 测试**

测试先用 tests/conftest.py 的 make_pdf_with_image 生成图片 PDF，再用 PyMuPDF 测试夹具代码把同一 xref 放到第二个 bbox（只在测试准备阶段使用 PyMuPDF）。断言 Rust 返回两个 placement，resource index 各自递增、bbox 不同，输出路径均存在。

- [ ] **Step 2: 运行测试确认 Rust image exporter 缺失**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py::test_extract_images_tracks_each_page_placement

Expected: FAIL because the PyO3/public Rust route has not been connected and the new module does not exist.

- [ ] **Step 3: 从 PDFium image page objects 读取 placement 和图像数据**

在 image_extraction.rs 中遍历页面对象及 form 子对象；为每个可见放置对象记录经过 parent matrix 和 crop/rotation 转换的 bbox、对象顺序、原始图像宽高、扩展名与 bytes。没有页面 placement 的资源不输出。

- [ ] **Step 4: 在 Rust 写文件并生成 Image DTO**

用 std::fs::create_dir_all 和 std::fs::write 生成现有文件命名；每次 placement 单独写一份文件。文件系统错误传播到 run_public_api_json，不返回缺字段的 Image。

- [ ] **Step 5: 实现 Rust 区域相交筛选**

对请求的 region 页集合去重后，在 Rust 中导出该页所有 image 文件；对每个 region 按闭合 bbox 相交语义选择结果，保留单区域首图和多区域列表语义。测试从首次生成的 PDF 读取图片 xref 并在不同矩形再次插入，明确保证是同一资源的两个 placement。

- [ ] **Step 6: 运行图像专项测试并提交**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py::test_extract_images_tracks_each_page_placement tests/test_rust_public_api.py::test_extract_image_region_preserves_write_scope

Expected: 两个 placement 和区域文件副作用与 API 基线一致。

~~~powershell
git add tools/pdfium_probe/src/image_extraction.rs tools/pdfium_probe/src/lib.rs tools/pdfium_probe/src/public_api.rs tests/test_rust_public_api.py
git commit -m "feat: extract PDF images through Rust"
~~~

### Task 6: 实现整页和区域 Rust 渲染

**Files:**
- Modify: tools/pdfium_probe/src/public_api.rs
- Test: tests/test_rust_public_api.py

**Interfaces:**
- RenderPages 返回 RenderInfo[]，文件名 page-{page_index:03d}.png。
- RenderRegion 返回单个 RenderInfo 或列表，文件名 region-{page_index:03d}-{region_index:03d}.png。
- 页图渲染保留现有 page_type badge；裁剪渲染不添加 badge。

- [ ] **Step 1: 新增渲染输出测试**

~~~python
def test_rust_render_page_and_region_dimensions(tmp_path):
    parser = PDFParser(str(FIXTURE_DIR / "page_000_vector.pdf"), render_dpi=72)
    full = parser.render_pages(str(tmp_path / "pages"), page_indices=[0])
    crop = parser.render_region(FULL_PAGE, str(tmp_path / "regions"), dpi=72)
    assert full.data[0].width and full.data[0].height
    assert crop.data.width == full.data[0].width
    assert (tmp_path / "pages" / "page-000.png").is_file()
~~~

- [ ] **Step 2: 运行测试确认 Rust 渲染路由缺失**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py::test_rust_render_page_and_region_dimensions

Expected: FAIL because render_pages and render_region still use PyMuPDF.

- [ ] **Step 3: 实现 Rust 全页渲染及 badge**

调用现有 render_page_to_image，根据 Rust classifier 结果在 Rust 图像层绘制与 page_type_label.py 相同位置、尺寸、填色和文字，再写 page-{index:03}.png。页面标签不得通过 Python/PyMuPDF 添加。

- [ ] **Step 4: 实现区域渲染**

Rust 按 region 和 dpi 计算 crop 后的像素图；如果 pdfium-render 不能直接裁剪，先渲染页面再用 image crate 在 Rust 中裁切。写 region-{page:03}-{region:03}.png 并回传像素宽高与 dpi。

- [ ] **Step 5: 运行渲染对照并提交**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py::test_rust_render_page_and_region_dimensions

Expected: 页面/裁剪尺寸与迁移基线一致，目标 PyMuPDF get_pixmap 被禁用时仍通过。

~~~powershell
git add tools/pdfium_probe/src/public_api.rs tests/test_rust_public_api.py
git commit -m "feat: render PDF pages and regions through Rust"
~~~

### Task 7: 把 Rust API 通过 PyO3 暴露

**Files:**
- Modify: Cargo.toml
- Modify: Cargo.lock
- Create: rust/pdfium_api.rs
- Modify: rust/lib.rs
- Test: rust/pdfium_api.rs

**Interfaces:**
- _pdf_fast.run_public_pdf_api(request_json: str) -> str
- _pdf_fast.classify_page_from_bytes(pdf_bytes: bytes, page_index: int, pdfium_library_path: Optional[str]) -> str
- 根 crate 依赖 pdfium_probe = { path = "tools/pdfium_probe" }；serde/serde_json 直接依赖仅在 PyO3 JSON 边界需要时新增。

- [ ] **Step 1: 为两个 Python 函数加入 Rust binding 测试**

测试 run_public_pdf_api 对错误 JSON 返回 PyValueError，有效 classify_page_from_bytes 返回 "vector"，坏 PDF 返回可读异常消息。

- [ ] **Step 2: 运行扩展 Rust 测试确认 binding 未注册**

Run: cargo test --manifest-path Cargo.toml --lib pdfium_api

Expected: FAIL because the module and registered functions are absent.

- [ ] **Step 3: 实现 JSON 路由绑定**

~~~rust
#[pyfunction]
fn run_public_pdf_api(request_json: &str) -> PyResult<String> {
    pdfium_probe::public_api::run_public_api_json(request_json)
        .map_err(pyo3::exceptions::PyValueError::new_err)
}
~~~

- [ ] **Step 4: 实现 bytes 分类绑定并注册模块**

classify_page_from_bytes 调用 pdfium_probe::public_api::classify_page_from_pdf_bytes；在 _pdf_fast 的 #[pymodule] 初始化中添加两个函数。不要把 PDFium handle 或 PyMuPDF 对象交给 Python。

- [ ] **Step 5: 运行根 crate 编译与单元测试**

Run: cargo test --manifest-path Cargo.toml --lib pdfium_api

Expected: 两个 binding 存在、异常稳定、根 PyO3 crate 编译通过。

- [ ] **Step 6: 提交 PyO3 API**

~~~powershell
git add Cargo.toml Cargo.lock rust/pdfium_api.rs rust/lib.rs
git commit -m "feat: expose PDFium public APIs through PyO3"
~~~

### Task 8: Python 适配层与公开方法切换

**Files:**
- Create: src/hexai_pdf_parser/pdfium_api.py
- Modify: src/hexai_pdf_parser/core/pdf_parser.py
- Modify: src/hexai_pdf_parser/extractors/page_classifier.py
- Modify: tests/test_pdf_parser.py
- Modify: tests/test_classify_pdf_page.py
- Test: tests/test_rust_public_api.py

**Interfaces:**
- pdfium_api._run(request: dict) -> Any
- pdfium_api.classify_bytes(data: bytes, page_index: int) -> str
- pdfium_api 为路径请求添加包内 PDFium 路径 native/<platform>/<library>；不存在时传 None，由 Rust 依次尝试 manifest 路径和系统 PDFium。

- [ ] **Step 1: 先补齐 wrapper 分派测试**

每个 PDFParser 目标方法以 monkeypatch 替代 pdfium_api._run，检查 operation 名、path、page_indices、regions、dpi、model 参数和 output_dir 均正确；测试应在当前实现下失败。

- [ ] **Step 2: 运行测试确认 wrapper 尚未切换**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py

Expected: FAIL because the target methods still execute their Python implementations.

- [ ] **Step 3: 实现 Python JSON/DTO 适配**

pdfium_api.py 只负责 json.dumps/loads、原生资源路径定位、dict 到现有数据类的转换。bbox 使用 BBox，普通 table cell 使用 Cell，结构化 table cell 使用 CellStructure，字符级结构使用 TextChar/TextBlock，图像与渲染分别使用 Image/RenderInfo。

- [ ] **Step 4: 切换 PDFParser 的七个目标方法**

替换 extract_text_in_region、extract_table_in_region、extract_table_structure、extract_images、extract_image_in_region、render_pages、render_region 的 PyMuPDF 处理代码为 _run；保留公开签名和 _execute_result。区域归一化、bbox 过滤、图像筛选、页面渲染及文件写入不得留在 Python。

- [ ] **Step 5: 切换分类入口**

路径版 classify_pdf_page 发 classify_page 请求。fitz.Document 使用 source.tobytes()；fitz.Page 使用 source.parent.tobytes() 和 source.number 调 classify_bytes。路径 PDFParser.classify_page 即使 _document 已缓存也调用 Rust；只有 PDFParser(source=Document) 保留已有页类型数据。

- [ ] **Step 6: 删除迁移产生的 Python 私有孤儿代码**

先用 rg 确认 _get_page_sizes、区域 PyMuPDF bbox 路径、目标方法的 ImageExtractor/RenderEngine 导入及 page_classifier.py 的旧检查 helper 不再被其他调用；只删除由这次改动造成且没有兼容调用的未使用私有代码。保留其他 parse() 需要的依赖和方法。

- [ ] **Step 7: 运行现有公开 API 测试**

Run: maturin develop --release

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_pdf_parser.py tests/test_classify_pdf_page.py tests/test_page_classifier.py

Expected: 既有 API 返回形态、消息、文件名、对象输入和 cached Document 行为通过。

- [ ] **Step 8: 提交 Python 切换**

~~~powershell
git add src/hexai_pdf_parser/pdfium_api.py src/hexai_pdf_parser/core/pdf_parser.py src/hexai_pdf_parser/extractors/page_classifier.py tests/test_pdf_parser.py tests/test_classify_pdf_page.py tests/test_rust_public_api.py
git commit -m "feat: route standalone PDF APIs through Rust"
~~~

### Task 9: 打包 PDFium 原生库并验证安装包

**Files:**
- Create: tools/pdfium_probe/scripts/stage_pdfium_package.py
- Modify: pyproject.toml
- Modify: .gitignore
- Modify: src/hexai_pdf_parser/pdfium_api.py
- Test: tests/test_rust_public_api.py

**Interfaces:**
- 暂存脚本检测当前构建平台，复用 download_pdfium.py 和 manifest.json 的 SHA-256 校验，再复制到 src/hexai_pdf_parser/native/<platform>/。
- _native_library_path() -> Optional[str] 返回包内 PDFium 路径；不支持的平台返回 None 并让 Rust 尝试系统库。

- [ ] **Step 1: 添加暂存脚本测试**

用临时 source/destination 目录测试同平台文件复制、SHA-256 保持和缺文件错误；测试不访问网络。另以 manifest 固定验证 win-x64、linux-x64、mac-x64、mac-arm64 各自的包内文件名和目录映射。

- [ ] **Step 2: 运行测试确认暂存脚本缺失**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py::test_stage_pdfium_package

Expected: FAIL because stage_pdfium_package.py and its copy helper do not exist.

- [ ] **Step 3: 实现平台资源暂存**

stage_pdfium_package.py 先运行已有 `tools/pdfium_probe/scripts/download_pdfium.py`，再按当前构建平台读取 manifest 对应平台项，校验并复制其 library_relpath 到 src/hexai_pdf_parser/native/<platform>/<library-name>；复制前后若 manifest 有 library_sha256 必须一致。发布矩阵为 win-x64、linux-x64、mac-x64、mac-arm64 分别构建目标平台 wheel，每个 wheel 含本平台 PDFium 库。

- [ ] **Step 4: 纳入 wheel 并忽略生成副本**

在 pyproject.toml 的 Maturin include 添加 src/hexai_pdf_parser/native/**/*；在 .gitignore 添加仅匹配 src/hexai_pdf_parser/native/ 的规则。Python 适配层用 Path(__file__).parent / "native" / platform / name 找资源，并使用 `Optional[str]` 标注可能不存在的路径以兼容 Python 3.7 语法。

- [ ] **Step 5: 构建并检查 Windows wheel**

Run: python tools/pdfium_probe/scripts/stage_pdfium_package.py; python -m maturin build --release --out output/rust-public-api-wheel

Expected: Windows x64 wheel 构建成功，wheel 内容中存在 hexai_pdf_parser/native/win-x64/pdfium.dll，安装后 classify_page 可在禁止 PyMuPDF 页面读取时运行；四个平台的资源路径映射测试通过，其他平台动态库加载需在对应 CI 构建环境验证。

- [ ] **Step 6: 提交打包支持**

~~~powershell
git add pyproject.toml .gitignore src/hexai_pdf_parser/pdfium_api.py tools/pdfium_probe/scripts/stage_pdfium_package.py tests/test_rust_public_api.py
git commit -m "build: package PDFium for the Rust API"
~~~

### Task 10: 完成差异/性能验收、变更记录和合并

**Files:**
- Create: src/hexai_pdf_parser/debug/rust_public_api_benchmark.py
- Modify: tests/test_rust_public_api.py
- Modify: tools/pdfium_probe/changes.md
- Test: tests/test_rust_public_api.py
- Test: tests/test_pdf_parser.py
- Test: tests/test_classify_pdf_page.py

**Interfaces:**
- Benchmark 接收 fixture PDF、重复次数和 Python baseline JSON，输出每个 API 的 python_median_ms、rust_median_ms、speedup 与结果差异摘要。
- 基线和 Rust 时间各至少预热 1 次、测量 5 次；比较使用中位数。

- [ ] **Step 1: 补齐所有目标 API 的 no-PyMuPDF 测试**

针对路径入口 monkeypatch fitz.open、fitz.Page.get_text、get_images、get_image_info、get_pixmap 和 fitz.Document.extract_image 为立即失败；逐个调用目标 API。单独保留 fitz 对象分类测试，允许且只允许 tobytes() 数据传递。

- [ ] **Step 2: 与迁移前基线比较结果**

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_rust_public_api.py

Expected: 返回 code/message、单/多区域结构、bbox 容差、表格结构、图像 metadata 与文件副作用、页面类型、渲染尺寸比较均通过；所有差异在测试摘要中显式列出。

- [ ] **Step 3: 运行 Python/Rust benchmark**

Run: python src/hexai_pdf_parser/debug/rust_public_api_benchmark.py --baseline tests/fixtures/rust_public_api/python_baseline.json --runs 5 --output output/rust-public-api-benchmark.json

Expected: 输出全部目标 API 的两侧中位耗时和 speedup；不删除或改写 baseline。

- [ ] **Step 4: 执行 Rust 与 Python 回归**

Run: cargo test --manifest-path tools/pdfium_probe/Cargo.toml

Run: cargo test --manifest-path Cargo.toml --lib

Run: $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q tests/test_pdf_parser.py tests/test_classify_pdf_page.py tests/test_page_classifier.py tests/test_extract_table_region.py tests/test_image_extractor.py tests/test_rust_public_api.py

Expected: 每条命令均结束并读取最终退出码和失败摘要；若依赖、样本或模型缺失，按实际结果记录，不以超时或部分输出宣称通过。

- [ ] **Step 5: 对中文无线表格页面核对结构和渲染**

用 `Path(tempfile.mkdtemp(prefix="rust-public-api-wireless-", dir="output"))` 创建全新的独立目录，对 `tests/fixtures/page_437_wireless.pdf` 第 0 页调用 `extract_table_structure(page_indices=[0])` 和 `render_pages(page_indices=[0])`。核对结构化结果中的 table 数量、source、行列数、每个 cell 的跨度及 bbox，并打开新生成的 PNG 检查表格边界、空槽位和相邻表格。记录实际绝对输出目录。该检查只验证共享 Rust table engine 的公开 API 接线，不允许在 Cell 生成后回读 page words。

Expected: 页面结构与 PNG 来自本次运行的独立目录；表格结构无 occupancy 冲突，页面截图确认没有边界或相邻表格误并问题。

- [ ] **Step 6: 写中文 changes 记录并做差异检查**

在 tools/pdfium_probe/changes.md 新增日期条目，记录迁移范围、根因、PyO3/共享库调用链、无 PyMuPDF 后备约束、API 输出差异、测试命令和 benchmark 输出路径。

Run: git diff --check

Expected: 无空白错误，且记录中的测试/耗时均来自当前实际命令输出。

- [ ] **Step 7: 合入 dev-rust 并在合并结果复测**

实现分支为 codex/rust-public-api，基线分支为 dev-rust。先运行 `git worktree list` 确认 dev-rust 未被其他工作树占用；若未占用，在本任务 worktree 切换到 dev-rust 并合并实现分支，合并后重新执行 Task 10 Step 4 的命令。若 dev-rust 已在其他工作树中检出，则在该工作树确认状态干净后执行合并和复测；不得改动或清理其中的未提交文件。任何测试失败都保留 worktree 与分支并排查，不回滚或清理其他 worktree。

~~~powershell
# 仅当 git worktree list 确认 dev-rust 未被其他工作树检出时，在本任务工作树中执行：
git worktree list
git switch dev-rust
git merge codex/rust-public-api
~~~

Expected: dev-rust 包含所有经验证提交，合并后测试结果与合并前一致。

---

## Spec Coverage Checklist

- 范围与不迁移 parse()：Task 8、Task 10。
- 共享 Rust 核心库与 PyO3：Task 2、Task 7。
- Rust 区域文本、分类：Task 3、Task 8。
- Rust 表格和字符级 table structure：Task 4。
- Rust 图像导出、区域筛选：Task 5。
- Rust 整页与区域渲染及页面标签：Task 6。
- fitz 输入兼容和缓存规则：Task 8。
- PDFium 打包与系统库 fallback：Task 9。
- Python/Rust 结果和速度差异：Task 1、Task 10。
- 中文变更记录、回归、无线表格页面结构与 PNG 核对、差异检查及合并后复测：Task 10。
