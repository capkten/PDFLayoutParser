# Sprint 000：benchmark baseline handoff

本 Sprint 只完成基线核验、能力矩阵、DTO 合同和独立评审模板。feature-dev 与 detached baseline worktree 的完整 SHA 均为 dc00211fe0cf95bc8c3412c883311fe86f8d8357；生产路由仍为 Python。

现有 scripts/benchmark_rust_migration.py 和 scripts/compare_rust_migration.py 是准备性/历史 harness，可生成 Python-only 计时、percentiles、canonicalized tables 和 manifest，但没有 feature-dev 对照的新 runner，也没有 Rust 算法接入。因此本 Sprint 不声称真实分段 baseline、加速比、P95 或回归结果。

后续测量必须在 feature-dev checkout 中运行新 runner，明确执行 python 与 rust 两次并交 comparator；不定义或使用 both。测量应记录输入 PDF/model SHA256、环境、页数、线程数、DPI、warmup/runs、cold/warm、阶段计时、P50/P95/P99、峰值 RSS、结构化 manifest 及 JSON/PNG 路径。

人工核对范围包括 wired extractor、table extractor、wireless recovery、wireless_structure、English extractor、table header normalizer 和 financial header handler。Python 保留 PyMuPDF 采集、公开对象装配、ML、路由、渲染与服务状态；可剥离的几何、排序、span/text-run、列带、网格、occupancy、空槽位和表头拓扑进入矩阵。中文/混合结构只消费 native-span DTO，不回读 page.get_text(words)，不调用 extract_zebra() 或 legacy words 重建。
