# Task 7：通过 PyO3 暴露共享 PDFium API

## 改动与边界

- 根 crate 新增本地 `pdfium_probe` 依赖并更新 `Cargo.lock`。
- `rust/pdfium_api.rs` 提供 `run_public_pdf_api(request_json)` 和 `classify_page_from_bytes(pdf_bytes, page_index, pdfium_library_path=None)`，在 `_pdf_fast` 初始化时注册。
- 两个函数直接调用共享库，将 Rust 字符串错误映射为 `PyValueError`。桥接不解析 JSON、不复制提取算法、不传递 PDFium 句柄、页面或 Python PDF 对象；不回读 page words。
- 本任务仅接通 Rust/PyO3 入口，没有推进 Task 8 的 Python 公开接口迁移，也没有修改生产 ORT 依赖。

## 测试先行

先添加三个通过真实 PyO3 模块调用入口的 Rust 测试，随后运行 `cargo test --manifest-path Cargo.toml --lib pdfium_api`。观察到 0 passed、3 failed：错误均为 `_pdf_fast` 缺少目标属性的 `AttributeError`，证明模块未注册。之后才添加依赖、桥接实现和注册。

三个测试覆盖：错误 JSON 映射为 `ValueError` 且保留 `Invalid public API request`；有效 `tests/fixtures/page_000_vector.pdf` 字节返回 `vector`，省略可选库路径参数；坏 PDF 在显式 `None` 库路径下返回带 `Could not load PDF bytes` 的 `ValueError`。

## 验证结果

- `cargo check --manifest-path Cargo.toml --all-targets`：首次在线运行失败，crates.io `config.json` 的 schannel TLS 握手失败。
- `cargo check --offline --manifest-path Cargo.toml --all-targets`：成功。移除临时测试配置后再次执行 `cargo check --offline --locked --manifest-path Cargo.toml --all-targets`：成功。
- 实现后的 `cargo test --offline --manifest-path Cargo.toml --lib pdfium_api`：默认 ORT 静态链接失败，MSVC 14.40 下出现 `LNK2019` / `LNK2001`，最终 `LNK1120`（13 个未解析符号），包括 `__std_find_end_1`、`__std_remove_8` 等。没有把此结果表述为测试通过。
- Cargo 拒绝 `--features pdfium_probe/ort/load-dynamic`：feature 不能有多个斜杠；同时选择 root/ort package 并传 `ort/load-dynamic` 也失败，因为根 package 没有该 feature。
- 验证时临时在 `tools/pdfium_probe/Cargo.toml` 添加 `[features] test-load-dynamic = ["ort/load-dynamic"]`，执行 `cargo test --offline --manifest-path Cargo.toml --lib --features pdfium_probe/test-load-dynamic pdfium_api`：3 passed、0 failed、103 filtered out。正确的根 feature 写法为 `pdfium_probe/<共享库转发feature>`。随后恢复该 manifest 的原始内容；该临时 feature 不在提交中。
- `rustfmt --edition 2021 --check rust/pdfium_api.rs`、`git diff --check`：成功。

## 未验证与交付范围

未运行 ONNX 模型推理、完整 Rust/Python 套件、安装包构建和 Python 公开方法回归；动态链接下的三个 binding 测试不能证明默认静态链接可用。本任务没有改变页面结构或渲染，因此没有新的页面 PNG 输出。既有未跟踪 `.opencode/`、`.skill-manager/` 保留。
