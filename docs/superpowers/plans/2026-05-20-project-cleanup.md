# Project Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除项目根目录下的所有调试脚本、诊断脚本和临时数据文件，并更新 `.gitignore` 防止再次积累。

**Architecture:** 纯删除操作，所有目标文件均为 untracked 状态，安全可逆。唯一修改的已跟踪文件是 `.gitignore`。

**Tech Stack:** Shell (`rm`)

---

## Task 1: 删除根目录调试和诊断脚本

这些是一次性开发调试脚本，引用了特定 PDF 文件和页码，不属于库的一部分。

**要删除的文件（9 个）：**
- `debug_pipeline.py` — 可视化表格提取流水线步骤
- `debug_region_split.py` — 诊断单元格文本截断问题
- `debug_regions.py` — 逐步调试行提取、合并、区域查找
- `debug_text_visual.py` — 渲染词/片段/行调试叠加图
- `diagnose_34.py` — 诊断第 34 页
- `diagnose_47.py` — 诊断第 47 页表格提取
- `diagnose_47_coords.py` — 导出第 47 页文本行坐标
- `diagnose_pages.py` — 诊断第 33-47 页
- `batch_test.py` — 批量测试脚本（引用外部路径）

- [ ] **Step 1: 删除所有调试/诊断脚本**

```bash
cd D:/codes/PDFLayoutParser
rm -f debug_pipeline.py debug_region_split.py debug_regions.py debug_text_visual.py
rm -f diagnose_34.py diagnose_47.py diagnose_47_coords.py diagnose_pages.py
rm -f batch_test.py
```

- [ ] **Step 2: 验证删除**

```bash
ls debug_*.py diagnose_*.py batch_test.py 2>&1
```

Expected: 全部 `No such file or directory`.

---

## Task 2: 删除根目录临时数据文件

这些是调试过程中产生的文本转储和可视化输出，不属于项目代码。

**要删除的文件（7 个）：**
- `chinese_check.txt`
- `page79_dict.txt`
- `page79_text.txt`
- `rect_text.txt`
- `rect_vs_text.txt`
- `number_split.json`
- `vis_page_058.png`

- [ ] **Step 1: 删除所有临时数据文件**

```bash
cd D:/codes/PDFLayoutParser
rm -f chinese_check.txt page79_dict.txt page79_text.txt
rm -f rect_text.txt rect_vs_text.txt number_split.json vis_page_058.png
```

- [ ] **Step 2: 验证删除**

```bash
ls chinese_check.txt page79_dict.txt page79_text.txt rect_text.txt rect_vs_text.txt number_split.json vis_page_058.png 2>&1
```

Expected: 全部 `No such file or directory`.

---

## Task 3: 更新 `.gitignore`

**文件：** `.gitignore`

- [ ] **Step 1: 在 `.gitignore` 末尾追加以下规则**

```
# Debug / diagnostic scripts (root level)
/debug_*.py
/diagnose_*.py
/batch_test.py

# Build artifacts
build/
dist/
*.egg-info/

# Pipeline output directories
out_*/

# Temporary text/data files at root
/*.txt
/*.json
/*.png
```

- [ ] **Step 2: 验证 `.gitignore` 生效**

```bash
cd D:/codes/PDFLayoutParser
git status --short
```

确认已删除的文件不再出现在 `git status` 中。

---

## Task 4: 验证测试通过

- [ ] **Step 1: 运行完整测试套件**

```bash
cd D:/codes/PDFLayoutParser
pytest -v
```

Expected: 所有测试通过。没有任何测试依赖已删除的文件。

---

## Summary

| 类别 | 数量 |
|------|------|
| 调试/诊断脚本 | 9 个 `.py` 文件 |
| 临时数据文件 | 6 个 `.txt` + 1 个 `.json` + 1 个 `.png` |
| `.gitignore` 更新 | 追加防重复积累规则 |
| **共删除** | **16 个文件** |
