# 表格提取可配置化 实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- []) syntax for tracking.

**Goal:** 将 table_extractor.py 和 text_region_detector.py 中 50+ 个硬编码数值阈值提取为可配置的 TableConfig 数据类，支持 JSON 文件加载，行为 100% 向后兼容。

**Architecture:** 新增 table_config.py 模块存放嵌套 @dataclass 配置层级；TableExtractor.__init__ 接受可选 TableConfig，保留原有独立参数做向后兼容；Pipeline 和 CLI 透传配置。所有默认值与当前硬编码一致，不改变任何算法逻辑。

**Tech Stack:** Python 3.10+, dataclasses, pytest, PyMuPDF

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | src/hexai_pdf_parser/table_config.py | 全部配置数据类 + JSON 序列化 |
| 修改 | src/hexai_pdf_parser/table_extractor.py | 用 self.cfg.* 替换硬编码 |
| 修改 | src/hexai_pdf_parser/text_region_detector.py | 函数增加可选 config 参数 |
| 修改 | src/hexai_pdf_parser/pipeline.py | 透传 table_config |
| 修改 | src/hexai_pdf_parser/cli.py | 增加 --table-config 参数 |
| 修改 | src/hexai_pdf_parser/__init__.py | 导出 TableConfig |
| 新建 | tests/test_table_config.py | 配置相关测试 |