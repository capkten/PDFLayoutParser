# Task 4A：wireless structure differential harness 报告

> 日期：2026-09-22
> 范围：只建立 Task 4 的 owned-input 字段级差分观测，不修改 Rust 生产算法。

## 结果

Task 4A 已建立可重复的 Python oracle / Rust helper differential harness，fixture 覆盖列带伪列、表头 rescue、物理行、连续性、二叶子表头、rowspan、occupancy 和空槽位。harness 只从 JSON owned atoms/bands/region 构造输入，没有 `fitz.Page` 和 `page.get_text("words")`。

本 slice 的 GREEN 定义是 normalizer、fixture contract 和 mismatch ledger 可重复生成，不要求当前未迁移的 Rust helper 与 Python oracle 零差异。当前差异被保留为迁移输入，不视为 accepted parity。

## TDD / 观测证据

4A 是 observability slice，不直接改变 production behavior，因此不以“新增断言在旧实现上失败”作为 GREEN 门禁。测试先运行 Python oracle，并确认 Rust/Python mismatch ledger 非空且包含三种分类；然后固定测试，使后续 Rust 迁移能复用同一输入和字段路径。此次被中断的实现代理没有提供独立的原始 RED 终端记录，因此本报告不声称已完成一个可复核的历史 RED 命令。

Focused GREEN：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py
3 passed in 0.46s
```

测试固定了：

- 14 个 required fixtures；
- rows、bands、physical_cells、logical_cells、empty_slots、occupancy、diagnostics 七层；
- presence、value、ordering、grouping、bbox、rowspan/colspan、source-continuity、diagnostics 八类字段；
- `requires_adaptation`、`defect`、`unsupported` 三种分类；
- 同一 fixture 两次 ledger 生成结果完全相同，并计算稳定 SHA256。

## 文件

- `tests/test_rust_wireless_structure_differential.py`
- `tests/fixtures/rust_migration/wireless/wireless_structure_differential.json`
- `docs/superpowers/rust-migration/sprints/sprint-006.md`

没有修改：

- `rust/wireless_structure.rs`
- `rust/types.rs`
- Python 生产代码
- `tests/test_wireless_extractor_split.py`
- `tests/test_wireless_structure_recoverer.py`

## 限制

- 该 slice 不改变 Rust 行列/表头算法，因此差异仍然存在。
- 页面级 JSON/PNG 未执行，留给 Task 5。
- Task 4B–4D 必须在本 ledger 基础上逐项迁移并重新 review；不能把 4A 的 mismatch 当成允许忽略项。

## Review-fix 结果（2026-09-22）

本次只修改 `tests/test_rust_wireless_structure_differential.py`、`tests/fixtures/rust_migration/wireless/wireless_structure_differential.json` 和本报告。未修改 Rust/Python 生产代码、route policy、sprint 文档或两个用户 dirty 测试文件。

- Rust adapter 现在消费 fixture-owned 的原始 atoms/bands；Python oracle 在独立副本上执行 prune/refine/rescue。ledger 明确记录 `python_prepared_bands_and_native_span_structure` 与 `rust_adapter_raw_owned_atoms_and_bands` 两个比较阶段。
- Cell identity 改为 row/column/source-position/ordinal 结构键，文本只进入 `value`；左移中文续行增加行列、source line span 和 `S1/S2` source refs 的精确断言。
- paired-CJK、sparse alignment、header note/leaf rescue 增加精确的保留 band geometry/source_atoms 断言；14 个 fixture 均声明显式 classification 和 expected mismatch/category。
- oracle 与 Rust normalized output 都执行 duplicate、out-of-range、uncovered-slot occupancy 校验；Rust 已暴露的 normalized occupancy 冲突进入 diagnostics ledger，不再被静默覆盖或阻断差分输出。

本次修复中实际观察到的 TDD RED（不是历史 RED 证据）：

```text
.FF...                                                                   [100%]
2 failed, 4 passed in 0.95s
AssertionError: complete_two_leaf_parent has no explicit mismatch classification
```

随后补充 fixture contract 后的最终 focused pytest：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py
```

```text
......                                                                   [100%]
6 passed in 0.65s
```

最终 whitespace 检查：

```powershell
git diff --check
```

结果：命令无输出并以成功状态结束。

## Review-fix verification addendum（2026-09-22）

- raw fixture-owned atoms/bands 与 Python prepared bands 分离；Rust 路径消费 raw 输入。
- Rust 侧未调用 Python band prune/refine/rescue 等价 binding，阶段明确记录为 `rust_no_binding_for_python_band_prune_refine_rescue`，因此该部分仍是 adaptation boundary。
- cell identity 使用 layer + row/column + source position + ordinal，文本仅比较为 `value`。
- paired-CJK 与 sparse-alignment fixture 增加被移除 band 的精确 geometry/source_atoms 断言；每个 fixture 保留显式 mismatch classification。
- Python oracle 与 Rust normalized ledger 均执行 duplicate、out-of-range、uncovered-slot occupancy 校验；Rust 校验结果保留在 diagnostics ledger。

本次实际验证命令及结果：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py
```

```text
......                                                                   [100%]
6 passed in 0.67s
```

```powershell
git diff --check
```

结果：无输出，退出码 `0`。

## Re-review fix verification（2026-09-22）

本轮修复严格限制在 Task 4A harness、fixture、报告和 sprint handoff。两个用户已有 dirty 测试文件保持不变；没有修改 Rust/Python 生产代码、route policy 或其他测试。

- ledger 增加显式 `source-reference` 字段，统一记录 `source_refs` 与 `span_refs`，并纳入字段覆盖集合；不再只通过 `grouping` 或 fixture 断言间接观察来源。
- Rust normalized-output 的 duplicate、out-of-range、uncovered-slot 和 ownership mismatch 校验返回结构化 `normalized_output_occupancy` rejection contract；rejection 作为独立 `normalized_output/contract` ledger 记录，同时保留普通 Rust/Python mismatch 记录。
- 14 个 fixture 的 mismatch contract 取消 wildcard classification；每个 fixture 都有 exact expected record，并用按 layer/field 明列的 `allowed_additional_mismatches` 闭合集合。实际集合必须与 expected 加 allowed 完全相等。

### Reconstructed baseline RED（非历史证据）

以下是在临时 detached worktree 的 `d0774c2` pre-fix harness 上，以最终 fixture contract 和最终 rejection/source-reference contract 做的可重构 baseline probe。该结果不是历史终端记录；同时复制了当前 worktree 的同一 `_pdf_fast.pyd` 构建产物，仅用于使旧源码可导入。

实际命令：

```powershell
$target = 'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan'
$baseline = 'D:\codes\PDFLayoutParser-Fast\.worktrees\task-4a-reconstructed-baseline'
git worktree add --detach $baseline d0774c2
Copy-Item "$target\tests\fixtures\rust_migration\wireless\wireless_structure_differential.json" "$baseline\tests\fixtures\rust_migration\wireless\wireless_structure_differential.json"
Copy-Item "$target\src\hexai_pdf_parser\_pdf_fast.pyd" "$baseline\src\hexai_pdf_parser\_pdf_fast.pyd"
Push-Location $baseline
$env:PYTHONPATH = (Resolve-Path 'src').Path
@'
import importlib.util
from pathlib import Path
p = Path('tests/test_rust_wireless_structure_differential.py').resolve()
spec = importlib.util.spec_from_file_location('task4a_baseline', p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
failures = []
if 'source-reference' not in mod.FIELDS:
    failures.append('missing source-reference ledger field')
try:
    result = mod._validate_normalized_occupancy(
        [{'row': 0, 'col': 0, 'rowspan': 2, 'colspan': 1}], [[0]], 1, 1, side='rust'
    )
    if not isinstance(result, dict) or result.get('status') != 'rejected':
        failures.append('Rust normalized occupancy rejection is not structured')
except Exception as error:
    failures.append(f'Rust occupancy contract raised {type(error).__name__}: {error}')
if failures:
    raise AssertionError('RECONSTRUCTED BASELINE RED: ' + '; '.join(failures))
'@ | & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -
Pop-Location
git worktree remove --force $baseline
```

实际输出：

```text
AssertionError: RECONSTRUCTED BASELINE RED: missing source-reference ledger field; Rust occupancy contract raised AttributeError: module 'task4a_baseline' has no attribute '_validate_normalized_occupancy'
BASELINE_PROBE_EXIT=1
```

### Final verification

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH = (Resolve-Path 'src').Path
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py
```

```text
..........                                                               [100%]
10 passed in 0.65s
```

```powershell
git diff --check
```

结果：无输出，退出码 `0`。

### 自审

- [x] 只修改允许的 harness、fixture、report 和 sprint 文件；保留两个用户 dirty 测试文件。
- [x] source-reference/span-reference 已成为 ledger 的直接字段并参与字段覆盖。
- [x] Rust normalized-output occupancy failure 是显式 rejection contract，不再伪装成普通 diagnostics；预期差分仍进入 ledger。
- [x] 每个 fixture 的实际 mismatch/category 集合被 exact expected 与显式 allowed additions 完整闭合，wildcard 会失败。
- [x] 已记录 reconstructed baseline RED，明确不是历史证据，并说明共享构建产物。
- [x] focused pytest（10 tests）、whitespace 检查和 sprint handoff 已完成。

剩余边界：Rust band prune/refine/rescue 等价 binding 仍不存在，阶段继续标记为 `rust_no_binding_for_python_band_prune_refine_rescue`；本 slice 只提供迁移适配边界和可重复差分证据，不宣称 Rust parity。
