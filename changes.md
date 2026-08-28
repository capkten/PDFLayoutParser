# Changes

## 2026-08-28

- 修复旋转页面上下外边界缺失导致有线表格列内容未生成的问题：page-506 原始页面视觉上缺少上下两条外边界，页面归一化后表格 bbox 仍能通过相交线段确定 `y0/y1`，但 `WiredTableExtractor._build_cells_for_region()` 之前只将 `bbox.x0/x1` 和虚拟左右竖线纳入 Cell 网格，没有对称处理 `bbox.y0/y1`。现在横向边界集合加入 bbox 上下界，并在缺少对应物理横线时建立有效的逻辑上下横线，使边界 Cell 能通过后续 outside 检查。修改仅发生在有线表格 Cell 构造阶段，不修改 PDF 内容流、不回读或重建文字。新增上下边界缺失回归测试；`tests/test_wired_table_extractor.py` 为 `14 passed`，规则优先测试为 `6 passed`。独立重跑输出位于 `D:\codes\PDFLayoutParser\output\page_506_rotation_boundary_fix_20260828\`：page-506 表格从 `9x8` 恢复为 `11x8`，此前未分配的 5 个金额全部回到对应 Cell，PNG 视觉检查确认上下边界、网格和文字对齐。扩展 `tests/test_table_extractor.py` 仍有 19 个既有环境/缺失样本/版本期望失败，与本次改动无关。

- 修复 Type3 字体字形路径被误识别为有线表格的问题：页面 726/727 使用 `T54` Type3 字体，PyMuPDF 1.26 会同时提供文本字符和字形内部 drawing，原逻辑将字形中的短横竖笔画送入 `line_projection`。现在根据 Type3 字符的 `origin`、字号和字符步进重建局部视觉区域；完整落入单字符区域的 drawing 在物理线候选入口过滤，不使用该字体异常的原始 char/word bbox。跨字符长线、可见矢量虚线、黑色填充细线和 `1x1/2x2` 图像 tile 恢复均保持原路径。调试可视化同时将绿色文字框裁剪到对应 Cell 网格内，避免异常 Type3 word bbox 跨行、跨表显示。新增异常 Type3 bbox、真实长表格线保留和绿色框裁剪测试；相关测试 `35 passed`。独立页面输出位于 `D:\codes\PDFLayoutParser\output\type3_glyph_filter_20260828_v2\`：页面 726 从 9 张候选降为 1 张真实 `3x2` 表，页面 727 从 5 张降为 4 张真实表；页面 350/351/352/353/355 的表格数量与结构保持不变。

- 修复旋转页面的表格可视化坐标错位：解析阶段和主页面渲染已移除页面 rotation，但表格可视化重新打开 PDF 时未执行同样的归一化，导致 page-506 的红色外框、蓝色网格和绿色文字框与旋转后的原始内容错位。现在可视化入口对传入及重新打开的页面统一调用 `normalize_page_rotation()`；新增回归测试覆盖重新打开旋转页面的路径。

- 增加中文/混合财务表格的局部混合回退：当有线结果包含异常高的主体行 Cell 时，保留原有表格 bbox、表头和汇总行，仅将主体区域交给 native-span 恢复器按文本行拆分；恢复后的 Cell 按有线主体列几何回填，并为未填列物化空 Cell。恢复失败或 occupancy 冲突时保留原有 `line_projection` 结果，不升级为整表无线。新增主体局部回退正例和普通高度有线表反例；native-span、有线及规则优先相关测试通过。未执行页面级重跑，待接入实际 PDF 后验证 `hybrid_line_span_recovery` 的行数、金额配对和 PNG 边界。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 439、440 的模型候选在 native-span 结构恢复阶段丢表：span 到 atom 阶段仅在 native flow 严格连续、上下几何兼容且后续存在右侧字段见证时组合多行字段，连续金额、占位符、flow 跳跃和按行输出的独立字段保持分离；同一 native 行内带正常字距的单字中文可先组合为完整字段。page-439 的中央多行正文 atom 此前又因整体 bbox 高度被误当作单行字高，未能补成独立列带；现在列间距判定使用字体/单行高度，并只在表头对补出列带存在唯一实质覆盖时归入该列，避免中央表头被就近塞入右列。表头跨度改为在基础逻辑网格副本上事务式推断，新增跨度发生 occupancy conflict 时整层回退基础网格，不再丢弃整表。整个结构路径只消费 native span、atom、列带和 Cell，不调用 `page.get_text("words")`，也不回退 legacy 无线重建。相关专项测试为 `79 passed`。独立重跑输出位于 `D:\codes\PDFLayoutParser\output\page_439_440_native_span_conflict_20260828\`：page-439 两张 `wireless_span_recovery` 表分别为 `6x3`、`2x3`，page-440 为 `3x13`；三表逻辑槽位分别覆盖 `18/18`、`6/6`、`39/39`，occupancy 冲突均为 0，page-439 下表唯一空槽保持独立 `1x1`。

## 2026-08-28

- 修复部分中文有线表格以连续微小图像块编码时无法识别的问题：有线提取器在既有 drawing 线之外，补充将同一水平/垂直方向上连续、共线且长度至少 20pt 的 `1x1`/`2x2` 图像 tile 恢复为线候选，并保留页面裁剪及原有连通组件过滤。这样页面 350 的确定组合表不再退回无线逻辑，页面 353 下方和 355 中部的有线表格也能被规则候选发现。新增 tile 线恢复回归测试；有线专项测试为 `10 passed`。页面独立输出位于 `D:\codes\PDFLayoutParser\output\dashed_image_rules_20260828\`：350 为 1 张 `line_projection`（2x2），351 为 2 张（5x3、3x1），352 为 1 张（3x4），353 为 2 张（4x3、2x2），355 为 3 张（13x7、3x3、4x3），此前漏检的 353 下方及 355 中部表格已恢复。

## 2026-08-28

- 修复模型表格候选框扩张递归吸收文字及整页背景图形导致的整页误表问题：`MLTableDetector._expand_bbox_to_touching_words()` 现在只以原始模型 bbox 为交集基准遍历一次文字并取并集，不再读取 `page.get_drawings()` 扩张，页面边界裁剪逻辑保持不变。新增直接相交、拒绝链式扩张和忽略整页背景矩形回归测试；模型检测专项及规则优先测试为 `9 passed`。重跑 `fix/zh_all_table_pages.pdf` 页面索引 `113、123、132、135`，独立输出位于 `D:\codes\PDFLayoutParser\output\model_bbox_single_pass_20260828\`：四页均无 `wireless_span_recovery` 整页表，仅保留 `line_projection` 独立表格，分别为 `3、2、6、3` 张；所有结果 occupancy 冲突为 0。PNG 视觉复核确认表格之间的章节标题、说明文字、注释和页脚均未被误并。

## 2026-08-28

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 193 底部有线表格漏检：根因是该页表格线由 `stroke color=None`、黑色 `fill` 的细矩形组成，而 `WiredTableExtractor._extract_lines_from_drawings()` 将所有无描边 drawing 一律排除，原始横竖线因此均为 0。现在于 drawing 到物理线候选的入口，通过低分辨率页面渲染九点采样估计主背景色；无描边 drawing 仅在无填充或填充色与背景色足够接近时排除，黑色等可见填充细矩形继续进入既有相交、连通组件和封闭 Cell 恢复。该修改不触及无线 native-span、atom、列带或逻辑 Cell 路径，也不新增 `page.get_text("words")` 调用。新增黑色填充线正例、非白背景色比较正例，并保留白色填充页边框拒绝反例；有线提取器专项测试为 `9 passed`。包含 `tests/test_table_extractor.py` 和规则优先测试的扩展结果为 `90 passed, 19 failed`，19 项来自既有路由/模型期望差异、缺失 `152590_20230428_N7ZK_0.pdf` 和旧模块缺失。页面独立输出位于 `D:\codes\PDFLayoutParser\output\page_193_wired_fill_background_20260828\`：恢复 1 张 `line_projection` 表，bbox 为 `[55.44, 676.08, 567.24, 815.88]`，结构为 `4x10`、14 个逻辑 Cell、40 个槽位全覆盖且 occupancy 0 冲突；最终 PNG 确认底部表格边界和主要行列线对齐，上方正文未被吸收，中部字符槽、填写线及独立复选框未被误识别为额外表格。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 191 下方无线表格的换行字段未合并问题：根因是 `注册/地址`、`与本公司/关系`、`业务/性质`、`法定/代表人` 和 `本公司实/际控制人` 在 span 到 atom 阶段保持为上下两个 run，其他列的居中文字在物理网格中插入中间行后，网格后的 multiline 逻辑又因物理行不相邻而拒绝组合。现在于 `build_text_runs()` 返回前，仅在同一 native block/source line、flow 连续、字体/粗体/脚本兼容、上下 bbox 不重叠、横向重叠充分、垂直间距紧密、存在非竞争性交错行且候选唯一时组合换行字段；纯数字、占位符、视觉行互相重叠和没有交错行证据的连续记录保持独立。该调用只消费 native span 派生数据，不回读 `page.get_text("words")`，不修改 `extract_zebra()`、legacy `_rebuild_text_aligned_table()`、列带或逻辑网格路径。新增目标正例、无交错行和视觉行重叠的拒绝误合并反例，以及 `3x7` recoverer 集成测试；无线结构、有线表格与财务表头相关测试结果为 `51 passed`（另有 5 条既有 PyMuPDF/SWIG 弃用警告）。页面独立输出位于 `D:\codes\PDFLayoutParser\output\page_191_wrapped_field_merge_20260828_reviewed\`：页面仍有 3 张 `wireless_span_recovery` 表，目标表 bbox 为 `[92.0, 671.5, 488.0, 771.7]`，恢复为 `3x7`、21 个 Cell、occupancy 0 冲突；最终 PNG 确认五组换行文字均位于单一 Cell，额外伪横线消失、七列边界连续且相邻表格未误并。

## 2026-08-27

- 修复第 192 页真实表格候选在 native-span 恢复阶段丢失或列数错误的问题：禁止独立中文字段 Span 与后续完整数值 Span 跨列合成 atom；只使用原生 `char_boxes`，按整个空白字符 run 内的显著间距将金额、比例和占位符拆为多个字段，不回读 page words；最低层表头细化复用有效重叠判定，避免邻列标题约 1.3pt 的擦边相交制造伪列。重跑 `fix/zh_all_table_pages.pdf` 第 192 页（0-based），页面从上到下三张表均为 `wireless_span_recovery`，结构为 `2x5`、`5x9`、`5x5`，全部占位无冲突；最终输出位于 `output/page_192_span_atom_boundary_fix3/`。无线结构与财务表头专项测试 `48 passed`。

- 修复第 192 页中、下两张表的二叶子列多级表头：依据同层父标题与下一层连续叶子列的完整 `1:2` 拓扑配对恢复 `colspan=2`，不依赖“年初数/金额/比例/坏账准备”等文字；在物理行压缩为逻辑网格后、空单元格物化前，才将已证实父标题和独立首列表头扩展到空表头槽位，避免提前设置 `rowspan` 导致行压缩冲突，整个过程只消费 native span/atom 与逻辑 Cell，不回读 page words。重跑 `fix/zh_all_table_pages.pdf` 第 192 页（0-based），三张表仍为 `wireless_span_recovery`：上表 `2x5`，中表 `5x9` 的四个父标题分别覆盖两列且“企业名称”覆盖完整表头，下表 `5x5` 的两个父标题分别覆盖两列且“项目”覆盖完整表头，全部占位无冲突；视觉检查确认组内父标题竖线消失、组间边界保留且无独立空白表头格。输出位于 `output/page_192_group_header_spans/`，无线结构与财务表头专项测试 `54 passed`。

- 修复第 189 页同一标签列因“正文左对齐、表头/合计居中”被拆成两个列带的问题：在网格构建前识别行占用互斥、纵向位于正文范围之外、间距显著小于后续金额列间距的首部弱对齐列带，并将其删除后重新编号；规则不依赖“项目/合计”等关键字。重跑 `fix/zh_all_table_pages.pdf` 第 189 页（0-based），页面从上到下三张表恢复为 `6x3`、`4x3`、`4x3`，全部导出槽位完整且无占位冲突；输出位于 `output/page_189_sparse_alignment_fix/`，无线结构与财务表头专项测试 `43 passed`。

- 修复第 188 页普通三列表头被误识别为分组财务表头的问题：移除仅由“目/计”等少量第二字符形成、且可与左侧同行前驱连续配对的伪列带；`wireless_span_recovery` 结果不再进入旧财务表头提升逻辑，也不再回读 page words 重写已恢复的 `rowspan/colspan`。重跑 `fix/zh_all_table_pages.pdf` 第 188 页（0-based），三张表为 `10x3`、`8x3`、`3x5`，所有导出单元格占位无冲突；最终图片位于 `output/page_188_paired_cjk_fix_final/tables/page-188.png`。

- 将 `zh`/`mixed` 页面的 native-span 无线表格 source 标记为既有的 `wireless_span_recovery`，使其跳过 legacy `_rebuild_text_aligned_table()`，避免已组合 span 的逻辑网格被 page words 二次重建覆盖；英文、有线及旧 `text_alignment` 路径不变。
- 将中文/混合页面的无线表格生产调用切换到 native-span 结构恢复适配器；保留旧 `extract_cells_from_region` 代码，英文和有线表格逻辑不变；新增适配器与分流回归测试。
- 修复模板区域规则路径对不存在的 `_zh_wireless` 属性的引用，改为调用新的 native-span 无线结构恢复适配器。
- 将无线表格文本条普通连接阈值由 `2 * normal_gap` 调整为 `normal_gap`，并增加表头列间距回归测试；第 184 页中间表恢复到 7 列，但下面稀疏表退化为 4 列，后续需单独处理分隔线对列带推断的干扰。
- 修复 native-span 无线结构恢复中长 `=====`/`-----` 排版线桥接列带、短 `---` 占位被整行删除或参与词距合并的问题：长规则线按连续 separator run 删除，短占位独立保留且不参与普通 gap 估计，普通连接阈值不再超过 `0.8 * font_size`。
- 将同槽位宽字距合并限制为 source block/line 相同、flow 连续的单个 CJK 字符对，用于恢复“合/计”，不再将“比例/坏账准备”跨槽聚合；多行中文 continuation 的垂直间距上限调整为 `1.0 * font_size`。
- 增加合并后物理/逻辑槽位冲突校验，并在物理行压缩为逻辑行后重新计算 `rowspan`，避免多行首列单元格继续覆盖后续逻辑行。
- 重跑 `fix/zh_all_table_pages.pdf` 第 184 页（0-based），语言检测为 `mixed`，页面从上到下三表均为 `wireless_span_recovery`，结构为 `3x3`、`7x7`、`5x7`，最终占位无冲突；输出位于 `output/page_184_structure_fix2/`。无线结构专项测试 `23 passed`；包含 `tests/test_table_extractor.py` 的扩展测试为 `98 passed, 19 failed`，失败来自既有路由行为差异、缺失 `152590_20230428_N7ZK_0.pdf`、旧模块缺失和模型路径期望。
- 将 native-span 恢复后的最终逻辑网格完整物化：所有未被现有 rowspan/colspan 覆盖的槽位各生成独立 `text=""`、`1x1` Cell，不回读 page words，不合并相邻空槽；空槽 bbox 使用表格外边界、相邻列带中点和逻辑行轨道中点生成。
- `wireless_span_recovery` 补齐到 `rows * cols` 后仍使用推断网格可视化，避免完整 cell 数触发 direct-bbox 快捷路径而造成表头断线。第 184 页最新输出位于 `output/page_184_empty_cells/`：顶部/中部/底部分别为 9、49、35 个 Cell，中部和底部各含 12 个独立空 Cell，所有槽位恰好占用一次；PNG 中两层表头横线贯穿全表，七列竖线连续穿过空槽。相关专项测试 `27 passed`；包含 `tests/test_table_extractor.py` 的扩展测试为 `102 passed, 19 failed`，19 项仍为既有路由期望、缺失样本 PDF/旧模块和模型路径差异。

## 2026-08-27

- 完善 span-table document-tree demo：将 `年末数`、`年初数` 及叶表头纳入统一逻辑网格，两个分组表头各保留 `colspan=3`；同步更新 JSON/PNG 验证与回归测试。Demo 测试结果：5 passed。
- 从 GitLab `feature-gangwei` 分支移植无线结构恢复基础逻辑到独立 `tables/wireless_structure` 包：新增原生 Span 来源追踪与数值字段拆分、中文文本条合并、稳定列带推断、物理/逻辑网格和占位冲突检查；暂不接入 demo/生产 pipeline，不做中英文语义配对。
- 继续移植无线结构逻辑：新增列内候选单元格物化、中文同槽位/多行合并、表头下界推断、基于真实 bbox 的叶子列 colspan 和稀疏列补救；仍保持独立包。新增无线结构测试与既有相关测试合计验证通过。
- 将 `feature-gangwei` 的完整 `header_topology` 核心同步到独立包，适配当前 `BBox`/列带接口；覆盖多级表头叶子细化、数值轨迹拆分、父表头跨度推断、稀疏列救援和边界贴合抑制。中英文语义配对未接入。

## 2026-08-26

- 增加无线表格的页面语言分流：英文页面才尝试斑马纹颜色背景提取，中文和混合语言页面直接使用文本对齐逻辑，避免将整页背景误判为表格行。
- 修复 wired 表格提取器将未与表格竖线相交的页眉线、页脚线和超链接下划线误判为表格线的问题。
- 在表格区域识别阶段增加横竖线交叉过滤：横线至少连接两条竖线，竖线至少连接两条横线。
- 新增回归测试，验证未连接的横线不会扩大表格区域。
- 使用 `test_single.py` 验证 `fix/zh_all_table_pages.pdf` 第一页，表格框从 `[65.1, 63.3, 531.0, 782.2]` 恢复为 `[65.3, 100.0, 530.8, 701.8]`，行列数从 `12 x 2` 恢复为 `8 x 2`。
- 修复 wired 表格按全部横线 Y 与竖线 X 生成贯穿式笛卡尔积网格的问题，改为依据线段覆盖关系构造单元格并识别 `rowspan/colspan`；线段交点继续使用 2pt 容差兼容 PDF 坐标微小偏差。
- 新增局部线段和视觉近似相交的回归测试；wired 提取器专项测试结果为 6 passed。
- 调整最终表格门控：有线规则识别到的表格即使未被 ML 检测到，也会保留并补充到最终结果；避免模型漏检导致有线表格丢失。
- 收紧有线线段的可见性判断：drawing 线在进入虚线/普通线候选前检查透明度及描边颜色，透明或接近页面背景色的线不再参与 `line_projection`，避免文本边框和不可见装饰形成碎片表格；可见黑色/彩色虚线、黑色填充细线及 `1x1/2x2` 图像 tile 恢复路径保持不变。新增背景色虚线、透明虚线拒绝测试和可见黑色虚线保留测试；有线提取器专项测试 12 passed。
