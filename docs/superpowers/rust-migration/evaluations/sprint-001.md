# Sprint 001 独立评估：建立可复现 Benchmark 基础设施

## 结论

**Recommendation: PASS**

评估范围针对当前 Sprint 001 交付物（Commit `ae136cc`），在 `codex/pdf-fast-rust-migration` 工作树完成。三路基准执行器、差异比较器、百分位统计、独立进程 worker 调度、峰值内存采样以及模型检测透明缓存均已严格实现并通过全部自动化测试；已成功基于 `feature-dev@dc00211` 基线捕获并固化了 1023 页全量黄金基线工件。生产路由保持为 `python`，未做越界修改。

## 范围与验收核对

| 验收项 | 结果 | 证据 |
|---|---|---|
| **Sprint 范围控制** | PASS | 仅修改了 benchmark 工具脚本、测试和统计模块，未修改生产算法内核，生产路由默认保持 `python`。 |
| **百分位数 API 合同** | PASS | `summarize_timings_with_percentiles` 显式计算 P50/P95/P99，不污染 legacy 5 键 `summarize_timings` API。`test_migration_module_does_not_expose_legacy_summary_alias` 通过。 |
| **三路运行与模式拒绝** | PASS | runner 严格支持 `python`、`shadow`、`rust`；非法模式与 `both` 均抛出清晰 `ValueError`；无环境变量时默认解析为 `python`。 |
| **独立 Worker 进程与 RSS** | PASS | 每次 repetition 均使用全新子进程，记录真实独立 PID；Windows 上采集 `PeakWorkingSetSize`，Linux 上采集 `ru_maxrss`。 |
| **分段耗时采样** | PASS | 互不重叠记录 `extract`, `dto`, `ffi`, `algorithm`, `adapt`, `total` 6 阶段样本与各阶段 P50/P95/P99。 |
| **比对器与差异分类** | PASS | `compare_runs` 与 `compare_manifests` 统一输出分类（`missing_key`, `extra_key`, `list_length`, `text`, `bbox`, `span`, `order`, `value`），映射为 `defect`；计算算法与端到端 P95 speedup。 |
| **真实 feature-dev 基线** | PASS | 从 `D:\codes\PDFLayoutParser\.worktrees\feature-dev-baseline`（HEAD 为 `dc00211fe0cf95bc8c3412c883311fe86f8d8357`）独立执行，成功产出全量 1023 页基准 `output/rust_migration_benchmark/baselines/feature-dev-dc00211/full-pdf-python.json`。 |
| **单元测试与格式** | PASS | `tests/test_rust_migration_benchmark.py` 32 项自动化测试 100% 通过；`git diff --check` exit 0。 |

## 基线工件摘要与复现凭证

### 1. 全量 1023 页黄金基线工件
- **工件路径**: `output/rust_migration_benchmark/baselines/feature-dev-dc00211/full-pdf-python.json`
- **Baseline ID**: `feature-dev-dc00211`
- **Source Commit**: `dc00211fe0cf95bc8c3412c883311fe86f8d8357`
- **输入 SHA256**: `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`
- **输入规模**: 1,023 页，提取 2,312 个表格，86,361 个单元格，0 失败页。
- **运行特征**: 3 个独立子进程 worker (PIDs: `18396`, `26356`, `48920`)。
- **内存峰值 (P50)**: `824,500,224` bytes (~824 MB)。
- **阶段耗时 (P95)**:
  - `total`: 693.95s
  - `algorithm`: 416.37s
  - `extract`: 138.79s
  - `adapt`: 104.09s
  - `dto`: 34.70s
  - `ffi`: 0.0s (Python 模式)

### 2. 自动化测试证据
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_benchmark.py
```
输出: `32 passed, 5 warnings in 5.86s` (exit 0)。

## 结论与后续

Sprint 001 全部 7 个 Step 已圆满闭环，验收判定为 **PASS**，满足进入 **Sprint 002（扩展统一 DTO 和 PyO3 批量边界）** 的全部门禁准则。
