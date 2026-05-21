# 无线表格结构恢复算法说明

本文只讲当前项目里“已经确认表格区域之后，如何把无线/弱线框表格恢复成结构化 `Table`”这条链路。

这不是 Camelot，也不是模型直接预测 row/col/span 的方案。当前实现仍然是启发式，但前提更强：**表格区域已经被模型或专门逻辑确认可信**，后续只在这个区域内部恢复结构。

## 1. 这条链路的目标

无线表格没有清晰的线框，不能像线框表那样直接依赖水平线和垂直线建网格。当前算法要解决的是：

- 在可信的 `table bbox` 内找到稳定的行
- 推断一张表的大致列骨架
- 把文本块分配到行和列
- 对明显跨列的标题、跨行的标签做轻量推断
- 尽量避免把金额列切碎，或者把表头压扁

它不做的事情：

- 不重新判断“是不是表格”
- 不做 OCR
- 不增加额外模型
- 不试图完整建模所有 rowspan / colspan 语义

## 2. 当前代码入口

无线表格结构恢复主要在这里：

- [`src/pdflayoutparser/table_extractor.py`](../src/pdflayoutparser/table_extractor.py)

关键函数是：

- `_extract_via_text_alignment(page)`
- `capture_text_alignment_snapshot(page, region_bbox)`
- `build_table_from_text_alignment_snapshot(snapshot)`
- `_build_text_alignment_table(region_rows, guides, region_bbox)`
- `_collect_text_rows(words)`
- `_build_region_guides(rows, region_bbox)`
- `_compact_column_guides(rows, guides)`
- `_merge_numeric_fragment_columns(cells)`
- `_infer_sparse_rowspans(cells, rows)`

下面按执行顺序展开。

## 3. 总体流程

当前无线表格结构恢复可以概括成七步：

1. 取出页面上的所有词
2. 在页面内找出候选表格区域
3. 只截取该区域内的词
4. 把词聚成视觉行
5. 从这些行里推断列骨架
6. 按列骨架把词分配到单元格
7. 做轻量清洗和 `rowspan` 推断

其中第 2 步是前提，不是结构恢复的一部分。这个前提来自：

- `layoutanalysis.onnx` 的 `ml_detection`
- 或其他专门逻辑确认的 `Table bbox`

我们现在默认信任这个 bbox。

## 4. 第一步: 取词

### 输入

- `fitz.Page`
- `table bbox`

### 行为

在 `_extract_via_text_alignment()` 和 `capture_text_alignment_snapshot()` 里，先调用：

```python
page.get_text("words")
```

如果是快照模式，会额外带 `clip=fitz.Rect(...)`，只取 bbox 内的词。

### 输出

PyMuPDF 返回的 word tuple，基本包含：

- `x0, y0, x1, y1`
- `text`
- 可选的额外信息

### 这一层的意义

这一层只负责把 PDF 文本层拿出来，不做任何表格判断。它的作用只是给后面的结构恢复准备原材料。

### 风险

- 如果 PDF 文本层本身缺字、乱码、字符顺序异常，后面所有结构推断都会变差
- 这也是为什么我们只信任“区域”，不信任“区域内的每一个 token 都天然属于表格”

### 4.1 先做保守预合并

在进入行聚类之前，我们先对同一页、同一表格区域里的原始 word 做一次很保守的预合并。

这一步的目标很明确：

- 把 renderer 或 PDF 文本层拆碎的 token 重新拼起来
- 优先修复中文和数字交接被拆开的情况
- 避免后面的行带聚类把一个语义单元误拆成多个“假 token”

当前实现是在 `_collect_text_rows()` 里完成的，核心逻辑是：

1. 先把每个 word 规范化成内部 token
   - `text`
   - `x0, y0, x1, y1`
   - `y_center`
   - `is_numeric`
   - `has_decimal`
   - `has_group_separator`
2. 按 `y_center` 和 `x0` 排序
3. 只检查相邻 token 是否满足很严格的合并条件
   - `y_center` 差很小，说明它们大概率在同一视觉行
   - 横向间距极小，或者 bbox 轻微重叠
4. 一旦满足条件，就把两个 token 合并成一个新 token
   - 文本直接拼接
   - bbox 重新取并集
   - 数字分类重新计算
5. 合并后的 token 再回到后续的行聚类逻辑里

这个阶段刻意不做复杂语义判断。它不关心“这是不是一个完整词”，只关心“这两个碎块是不是同一视觉 token 被拆开了”。因此：

- 它会合并 `人民` + `币`
- 它会合并 `47,95` + `4,294` + `.50`
- 它不会跨行乱合并
- 它不会因为字面上接近就吞掉一个真正独立的列值

这一步是为了让后面的行带和列骨架更稳定，而不是替代结构恢复本身。

## 5. 第二步: 把词聚成行

相关函数：

- `_collect_text_rows(words)`

### 输入

- 一组 word tuple

### 核心思想

同一视觉行里的词，它们的 `y_center` 接近。  
所以先对原始碎块做保守预合并，再按 `y_center` 排序，用一个小阈值把 token 聚成 row。

### 具体做法

1. 把每个 word 转成内部 token 结构
   - `text`
   - `x0, y0, x1, y1`
   - `y_center`
   - `is_numeric`
2. 按 `y_center` 从上到下排序
3. 顺序扫描
4. 如果当前 token 的 `y_center` 和当前行中心差值小于 `row_tolerance`，就并入当前行
5. 否则开启新行
6. 每个 row 里再按 `x0` 排序

### 输出

每一行会变成一个结构大致如下的 dict：

```python
{
    "tokens": [...],
    "x0": ...,
    "x1": ...,
    "y0": ...,
    "y1": ...,
}
```

### 为什么这一步重要

后面的列骨架推断，不是直接看单个 token，而是看“行”里的 token 分布。  
如果行切错了，列也会跟着错。

### 当前的保守点

- `row_tolerance` 很小，避免把上下两行粘成一行
- 这意味着某些字体不齐、上下偏移明显的复杂表，可能会被切成多行

## 6. 第三步: 分 span

相关函数：

- `_split_rows_into_spans(rows)`

### 目的

不是所有行都属于同一个连续表段。财报 PDF 里经常出现：

- 标题
- 小节标题
- 表头
- 表体
- 注释
- 下一段表

如果不切 span，整页所有行会被混在一起，列骨架会很脆。

### 具体策略

当前用的是启发式分段，主要依据：

- 行与行之间的垂直空隙
- 章节标记行，例如：
  - `1.`
  - `（一）`
  - `（二）`
  - `3.`
  - 其他显式章节头
- 连续文本行与数字行的过渡模式

### 输出

返回一个 `List[List[dict]]`，每个内层列表是一段连续 span。

### 为什么要分 span

因为列骨架应该尽量从“同一结构段”里推断，而不是把标题行、表头、正文、注释全部混成一张大网。

### 当前局限

- 这一步并不理解语义，只是找空间和格式上的断点
- 某些连续的长表，如果没有显式分段信号，仍然会被看成同一个 span

## 7. 第四步: 推断列骨架

相关函数：

- `_infer_column_guides(rows, region_bbox=None)`
- `_build_region_guides(rows, region_bbox)`
- `_compact_column_guides(rows, guides)`

这是无线表格结构恢复最关键的一层。

### 7.1 `_infer_column_guides()` 做什么

它不是直接决定“有几列”，而是从所有行里收集一批横向锚点 `guide_x`。

#### 锚点来源

对于一行里的 token，会按 token 性质决定用哪种位置做锚点：

- 数字 token：更偏向用左边界或右边界的稳定位置
- 文本 token：更偏向用左边界
- 行首 label：常常用最左的文本位置

这些锚点会带权重：

- 数字 token 权重大
- 能跨多行重复出现的锚点权重大
- 位置更稳定的锚点权重大

#### 聚类

所有锚点按 x 位置聚类，近的合并成一个 guide。

#### 过滤

过滤掉一些明显不该当作列边界的东西，例如：

- 只在一行里出现的孤立文本锚点
- 落在数值列之间的纯标题文本锚点
- 只对一个局部 span 有意义的伪 guide

### 7.2 `_build_region_guides()` 做什么

这一步会把两类 guide 合并：

1. 整个区域的 guide
2. 各个 span 的 guide

也就是说：

- 先看全局
- 再看局部
- 最后合并成一个更稳定的列骨架

### 7.3 `_compact_column_guides()` 做什么

这一步专门解决“列太碎”的问题。

当前做法是：

- 统计每个 guide 被多少行支持
- 统计它是否有数字支持
- 如果 guide 数量超过一个上限，就开始删掉最弱的 guide

它删掉的主要是：

- 支持行很少的 guide
- 离邻居太近的 guide
- 既没有数字支持，也没有足够文本支持的 guide

### 为什么这一层重要

无线表格里，列边界不是实体线，而是“视觉对齐模式”。  
如果我们让 guide 过多，后面 token 会被切碎成很多小列；  
如果 guide 过少，整张表又会压扁成两三列。

所以这一层本质上是在找平衡。

### 当前风险

- 宽表容易被压碎
- 文本密集页容易多出伪 guide
- 短数字碎片容易把列骨架干扰得很乱

## 8. 第五步: 把词分配成 cell

相关函数：

- `_build_text_alignment_table(region_rows, guides, region_bbox)`
- 旧流程里还有 `_build_text_grid_cells(rows, guides)`，本质类似

### 输入

- `region_rows`
- `guides`
- `region_bbox`

### 核心思路

把相邻两个 guide 的中点当作列边界。

举例：

- guide1 = 100
- guide2 = 200
- guide3 = 350

那边界大概就是：

- 150
- 275

然后每个 token 看它的 x 中心点落在哪个区间。

### 分配规则

1. 计算 token 的中心点 `cx`
2. 找到它属于哪个 column interval
3. 同一行里落在同一列的 token 合并成一个 cell
4. 记录：
   - `row_index`
   - `col_index`
   - `bbox`
   - `text`

### 结果

这样会得到一个基础的稀疏网格：

- 有些格子有文本
- 有些格子为空
- 每个 cell 先只代表“这个 token 属于哪个行列区间”

### 为什么不是直接做完 rowspan/colspan

因为先把基础网格建出来，再做 span 推断更稳。  
如果一开始就试图理解合并单元格，规则会很快变复杂。

## 9. 第六步: 合并过碎列

相关函数：

- `_merge_oversegmented_columns(cells)`
- `_merge_numeric_fragment_columns(cells)`

这一步是对“分配后的 cell”做二次收敛。

### 9.1 `_merge_oversegmented_columns()` 做什么

它主要处理线框拆分带来的窄空列。  
在无线结构恢复里，它也被保留，因为文本分配有时会间接制造出类似的碎列。

当前规则大致是：

- 统计每一列的平均宽度
- 统计每一列的文本密度
- 对于“很窄且空”的列，认为它更像边界碎片
- 把它并入相邻的更稳定列

### 9.2 `_merge_numeric_fragment_columns()` 做什么

这是专门修数字列碎片的。

无线/弱线框表里，金额经常被切成：

- `47,95`
- `4,294`
- `.50`

或者被切成多个短片段。  
这一步会检查：

- 是否是短数字片段
- 是否和相邻 cell 横向距离很近
- 是否同一行里形成了连续的碎片串

如果满足条件，就把这些碎片重新拼成一个 cell。

### 为什么这一步重要

这是我们目前最关心的两个问题之一：

- 列骨架过碎
- 金额被切断

如果不做这一步，结果会看起来“很多列”，但实际上只是数字碎成了很多段。

### 当前风险

- 规则太松，会把真正不同列的数字并掉
- 规则太紧，又会保留碎片，导致宽表失真

## 10. 第七步: 推断 rowspan

相关函数：

- `_infer_sparse_rowspans(cells, rows)`

### 它做什么

当前只做非常保守的 rowspan 推断，主要针对：

- 左侧标签
- 短文本标题
- 视觉上像合并单元格的 stub cell

### 触发条件

大致是：

- cell 文本较短
- cell 看起来像标签，而不是数值
- 下方若干行在同一列都没有内容
- 旁边其他列仍然有正常内容

满足这些条件时，认为当前 cell 可能要向下合并。

### 为什么是保守策略

如果 rowspan 判断太激进，会把普通行误合并掉。  
无线表格里，误合并比轻微漏合并更危险，因为它会破坏整张表的行结构。

### 当前局限

- 这不是完整 rowspan 推断
- 只是“明显的竖向标签延伸”
- 对复杂多级表头、嵌套表头、跨组标题支持有限

## 11. 快照模式

相关函数：

- `capture_text_alignment_snapshot(page, region_bbox)`
- `build_table_from_text_alignment_snapshot(snapshot)`

这两步是我们现在专门为了“快速迭代表格结构”加的。

### 11.1 `capture_text_alignment_snapshot()`

它会保存：

- bbox
- rows
- column_guides

也就是把“结构恢复前的中间状态”落成 JSON。

### 11.2 `build_table_from_text_alignment_snapshot()`

它可以直接读取上一步保存的 JSON，然后只执行：

- 列骨架收敛
- cell 分配
- 数字碎片合并
- rowspan 推断

这样我们就不需要每次都重新跑：

- PDF 打开
- 文本提取
- 区域检测
- 整页流水线

### 为什么这个模式重要

因为无线表格算法最难调的是中间层，而不是 PDF 解析本身。  
有了快照，我们可以反复只调：

- guide 收敛阈值
- 列合并阈值
- 数字碎片规则
- rowspan 保守程度

这比整页重跑快很多。

## 12. 当前输出是什么

最后会得到一个 `Table`：

- `bbox`: 表格区域
- `rows`: 行数
- `cols`: 列数
- `cells`: 单元格列表
- `confidence`: 启发式置信度
- `source`: 通常是 `"text_alignment"` 或 `"ml_detection"`

然后交给后续流程：

- `LayoutBuilder` 合并布局
- `JSONWriter` 输出结构化 JSON
- `MarkdownWriter` 输出 Markdown

## 13. 和线框表格的关系

有线表格仍然优先走线框主路径。  
无线结构恢复只是补充路径，不替代线框表格。

也就是说当前顺序是：

1. 线框表格
2. ML 表格区域 + 文本结构恢复
3. 更保守的回退

## 14. 现在这套算法的实际问题

我们已经看到的典型问题主要有两个：

### 14.1 列骨架过碎

表现：

- 一张表被切成很多窄列
- 表头被压扁
- 单元格过多但信息没有变多

原因：

- guide 太多
- 局部 span 的伪 guide 太多
- 数字列和文本列的锚点混杂

### 14.2 金额列被切断

表现：

- 一个金额被拆成多段
- 每段进入不同 cell
- 看起来像多列，实际上是碎片

原因：

- token 分布不连续
- 右对齐/分词造成碎片
- 列骨架边界太密

## 15. 下一步应该怎么迭代

如果继续优化，我建议只盯两件事：

1. 先把 `column_guides` 收得更稳
2. 再把数字碎片合并做得更准

也就是说：

- 先修结构骨架
- 再修 cell 拼接
- 最后才考虑更复杂的 rowspan / colspan

这比一上来追求“完整表格理解”更稳，也更符合当前项目对速度的要求。
