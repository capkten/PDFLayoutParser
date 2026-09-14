# Task 3 完成报告：离线 PDF Diff 审阅工作台

## 状态

已完成。实现位于 `scripts/pdf_diff_review.py`，测试位于 `tests/test_pdf_diff_review.py`。

## 实现内容

- 新增 `render_html(payload: dict) -> str`，生成无前端依赖、数据内嵌的离线审阅工作台。
- 采用纸张档案与墨色标记视觉：暖纸色背景、深色文字、增删差异分别使用绿色和红色。
- 左侧提供页码列表、分类筛选、页码/文本搜索，并显示页面分类与决策状态。
- 顶部显示总页数、已决策数和待确认数。
- 中间显示标签/当前的 PNG 审阅区，图片仅使用 `images/page-XXX.png` 相对路径；提供放大原图模态窗口。
- 右侧显示 diff。文本由浏览器端 `textContent` 写入 DOM，未使用 `innerHTML`，避免 diff 内容被解释为 HTML。
- 提供上一页/下一页、`1/2/3` 键盘快捷键、三种互斥决策“保留当前”“保留标签”“待确认”。默认状态为待确认，决策写入 `localStorage`。
- 提供“导出审阅结果”，下载包含时间、决策和页面分类的 JSON。
- 新增 `_safe_json`，将 `<`、`>`、`&` 等字符编码后再注入 inline script，避免恶意内容形成 `</script>` 结束标签。
- `build_review` 现将既有 payload 交给 `render_html` 生成 `index.html`，并记录 `page_type`。

## TDD 与验证

先添加了两项 HTML 字符串测试，并确认在实现前因 `render_html` 不存在而失败；完成实现后目标测试通过。

- `pytest -q tests/test_pdf_diff_review.py`：15 passed，5 个既有 pytest 异步配置/依赖弃用警告。
- `python -m py_compile scripts/pdf_diff_review.py`：通过。
- HTML 独立字符串自检：通过；确认 121 页数据、3 个 radio 决策项、核心控件、`localStorage`、导出按钮、键盘事件、相对 PNG 路径和危险脚本结束序列处理。
- `git diff --check`：通过。

## 手工浏览器检查

已尝试通过浏览器自动化打开临时 HTML，但当前环境浏览器枚举失败：`nodeRepl.fetch request failed`，因此无法完成实际点击切页/筛选/导出检查。该限制不影响上述静态字符串和 Python 测试验证，已保留在本报告中。

## Important 1 修复记录

审阅发现 `renderPage()` 虽然为“标签”和“当前”构造了各自的路径，却将两张卡都绑定到合成 `image_path`；放大按钮也无法明确区分资源。修复保持 `label_png` 和 `source_png` 的生成相对路径不变：两张卡分别使用 `pair[1]`，点击卡片图片可分别打开对应单侧原图；顶部按钮改名为“放大合成图”，明确打开 `image_path` 合成图。新增回归测试锁定这三条资源绑定契约，未引入外部依赖，兼容 Python 3.7，数据仍通过既有 JSON 安全内嵌路径处理。

### 本次真实验证

- `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_pdf_diff_review.py`：16 passed，5 个既有弃用警告。
- `python -m py_compile scripts/pdf_diff_review.py`：通过。
- 独立 HTML 自检：通过；确认 121 页、`img.src=pair[1]` 单侧绑定、单侧图片放大、明确合成图放大、离线资源和 JSON 安全。
- `git diff --check -- scripts/pdf_diff_review.py tests/test_pdf_diff_review.py`：通过。
- 浏览器手工验收仍由主代理负责。

## 变更边界

仅修改 `scripts/pdf_diff_review.py` 与 `tests/test_pdf_diff_review.py`。worktree 中其他 agent 的 `.superpowers/sdd` 文件未回退、未修改、未纳入本次提交。
