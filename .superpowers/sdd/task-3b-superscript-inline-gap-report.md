# Task 3B bounded slice：superscript inline gap

## 状态

DONE。实现、TDD RED/GREEN、focused regression、自审和提交均已完成。

## 根因

Python oracle 的 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py::_can_join()` 支持一条独立的 superscript 合并规则：candidate 字号严格小于 previous 字号的 `0.82`，且 candidate 的 x 坐标位于 previous bbox 右侧 superscript corridor：

```text
candidate.size < previous.size * 0.82
previous.x1 - previous.size * 0.9 <= candidate.x0
candidate.x0 <= previous.x1 + previous.size * 0.45
```

Rust `rust/native_span.rs::build_text_runs()` 原先只有普通同一 native line 字距、CJK 白名单字距和其他既有路径；`superscript_inline_gap` 的两个 span source line 不同，因此 `基` 和 `2` 被拆为两个 run。根因不是 normal gap 太窄，也不是 CJK gap 配置。

## TDD 记录

### RED

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py -k superscript_inline_gap
```

结果：`1 failed, 1 passed, 11 deselected`。

失败片段：Python helper 输出单个 `基2`；Rust helper 输出两个 run `基`、`2`，失败发生在新增正例断言，而字号阈值/x corridor 反例通过。该失败确认是缺少 superscript join 规则，不是 fixture、导入或编译错误。

### GREEN

新增 Rust/Python helper 正例和反例后，最小 Rust 修改为在现有 source-fragment、`$` 和垂直中心判断之后加入上述严格 superscript 条件。未放宽 normal native-line gap，未增大 CJK gap，未加入业务文字特判。

focused 命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py -k superscript_inline_gap
```

结果：`2 passed, 11 deselected`。

## 文件与变更

- `rust/native_span.rs`：加入严格字号比例和 superscript x corridor 判定；packed numeric 的 same-source-fragment veto 仍在该判定之前。
- `tests/test_rust_native_span_differential.py`：新增真实 Python/Rust helper 的 `基2` 正例、字号不满足严格阈值反例、x 坐标超出 corridor 反例；更新 superscript parity ledger 的计数与 digest。
- `changes.md`：记录根因、判定条件、调用位置、范围和验证结果。
- 本报告：记录完整 RED/GREEN、验证、自审和限制。

保留的输出合同：正例断言 Rust run 的 text、`span_refs`、`source_start/source_end`、bbox 和 evidence sizes；既有 packed numeric fragment evidence 测试继续覆盖 source fragment indices/counts。

## 验证

### differential 与 text-run 回归

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py tests/test_wireless_structure_text_runs.py
```

结果：`58 passed in 3.71s`。

ledger 更新后的完整计数：

- total：`449`
- fixture：alignment corridor `266`，vertical wrapped witness `99`，packed numeric split `14`，CJK non-whitelist `14`，independent fields `14`，source block/line noncontinuous `14`，empty/separator `7`，CJK whitelist `7`，single field control `7`，superscript inline gap `7`
- classification：defect `218`，requires_adaptation `102`，unsupported `129`
- digest：`d1b0b788c4f2facf50ca56426e4c3594c199bbe9c66e786c806bd39d4cdb2574`

### packed numeric fragment regression

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_packed_numeric.py
```

结果：`20 passed in 0.88s`。确认 superscript 分支没有绕过 packed numeric fragment veto 或破坏 fragment evidence。

### Rust unit tests

```powershell
cargo test --lib native_span
```

结果：`4 passed; 0 failed; 46 filtered out`。

### diff 检查

```powershell
git diff --check
```

结果：无输出，退出码 `0`。

## 范围自审

- 未修改 Python 生产实现或默认/shadow/fallback 路由。
- 未修改 `rust/wireless_structure.rs`、column/grid/header、wrapped merge、alignment corridor 或 `build_atoms`。
- 未修改用户已有 dirty 文件 `tests/test_wireless_extractor_split.py`、`tests/test_wireless_structure_recoverer.py`；它们保留在工作区且未纳入提交。
- superscript 条件没有替换或放宽 normal gap，也没有业务文字特判。
- source/order/span/evidence 输出合同保持；新增测试覆盖正例 bbox、span refs、source bounds 和 evidence sizes。
- 页面级 PDF/PNG 重跑不属于本 bounded synthetic text-run slice，未声称完成页面级 parity。

## 未解决限制

本提交只迁移 superscript inline gap 这一条 Task 3B 规则。其他 differential ledger 中已有的批准差异、页面级结构恢复和默认 Rust 路由切换仍不在本任务范围内。
