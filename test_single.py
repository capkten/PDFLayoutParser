"""单页表格提取与可视化单测试验脚本。

针对: 任意单页 PDF（默认解析第 0 页）
用途:
1. 加载单页 PDF 并调用 PDFParser 执行表格提取与结构解析；
2. 控制台格式化输出提取出的表格结构、行列数、置信度以及单元格文字内容；
3. 渲染并生成叠加 2D 单元格网格（Cell Grid）与文本框的可视化 PNG 图片；
4. 导出最新解析的 Markdown 与 JSON 结果便于对比核查。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证优先从项目源码 src 目录加载模块
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

sys.stdout.reconfigure(encoding="utf-8")

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from hexai_pdf_parser.core.pdf_parser import PDFParser
from hexai_pdf_parser.debug.table_visualizer import draw_tables_on_page
from hexai_pdf_parser.writers.json_writer import JSONWriter
from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter

# ==============================================================================
# 单测配置区域（可直接在此修改指定的单个 PDF 路径）
# ==============================================================================
TARGET_PDF_PATH = r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf"
OUTPUT_DIR = str(CURRENT_DIR / "output" / "single_page")
MODEL_PATH = str(CURRENT_DIR / "src" / "hexai_pdf_parser" / "ml" / "table_detector_model" / "best.onnx")
RENDER_DPI = 200
# ==============================================================================


def run_single_test(
    pdf_path: str | Path | None = TARGET_PDF_PATH,
    output_dir: str | Path | None = OUTPUT_DIR,
    dpi: int = RENDER_DPI,
    ml_model_path: str | Path | None = MODEL_PATH,
    page_index: int = 0,
) -> None:
    """执行单个 PDF 页面的表格解析与可视化测试。"""
    if not pdf_path:
        pdf_path = TARGET_PDF_PATH

    pdf_file = Path(pdf_path).resolve()
    if not pdf_file.exists():
        raise FileNotFoundError(f"指定的 PDF 文件不存在: {pdf_file}")

    if output_dir is None:
        output_dir = OUTPUT_DIR
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=" * 80)
    print(f"[test_single] 开始单测: {pdf_file.name} (page_index={page_index})")
    print(f"[test_single] 完整路径: {pdf_file}")
    print(f"[test_single] 模型路径: {ml_model_path}")
    print(f"=" * 80)

    # 1. 执行 PDFParser 解析
    with PDFParser(str(pdf_file), ml_model_path=str(ml_model_path)) as parser:
        result = parser.parse(page_indices=[page_index], output_dir=str(out_dir))
        if result.code == -1:
            raise RuntimeError(result.message)
        doc = result.data

    target_page = next((p for p in doc.pages if p.index == page_index), None)
    if target_page is None:
        if 0 <= page_index < len(doc.pages):
            target_page = doc.pages[page_index]
        elif doc.pages:
            target_page = doc.pages[0]
        else:
            print("[test_single] 警告: 未能从 PDF 解析出任何页面！")
            return

    tables = target_page.tables
    print(f"\n[1] 表格识别结果 (共识别到 {len(tables)} 个表格):")
    print("-" * 80)

    if not tables:
        print("  未检测到任何表格。")
    else:
        for t_idx, table in enumerate(tables):
            tb = table.bbox
            print(f"\n▶ Table {t_idx + 1}:")
            print(f"  - 来源 (source)     : {table.source}")
            print(f"  - 规格 (shape)      : {table.rows} 行 x {table.cols} 列")
            print(f"  - 置信度 (score)    : {table.confidence}")
            print(f"  - 外接矩形 (bbox)   : [{tb.x0:.1f}, {tb.y0:.1f}, {tb.x1:.1f}, {tb.y1:.1f}]")
            print(f"  - 单元格数 (cells)  : {len(table.cells)}")
            print(f"  - 单元格明细列表:")

            # 按行列排序打印单元格
            sorted_cells = sorted(table.cells, key=lambda c: (c.row_index, c.col_index))
            for cell in sorted_cells:
                cb = cell.bbox
                txt = cell.text.replace("\n", " ").strip()
                span_info = []
                if cell.rowspan > 1:
                    span_info.append(f"rowspan={cell.rowspan}")
                if cell.colspan > 1:
                    span_info.append(f"colspan={cell.colspan}")
                span_str = f" ({', '.join(span_info)})" if span_info else ""
                print(f"    [R{cell.row_index}C{cell.col_index}]{span_str} bbox=[{cb.x0:.1f}, {cb.y0:.1f}, {cb.x1:.1f}, {cb.y1:.1f}]: \"{txt}\"")

    # 2. 导出 Markdown 页面内容预览
    # print(f"\n[2] Markdown 页面内容预览:")
    # print("-" * 80)
    # md_writer = MarkdownWriter()
    # page_md = md_writer.to_string(doc)
    # print(page_md[:1500] if len(page_md) > 1500 else page_md)

    # 3. 渲染可视化图片（叠加表格大框、2D 单元格网格与文本框）
    print(f"\n[3] 渲染可视化图片:")
    print("-" * 80)
    doc_handle = fitz.open(str(pdf_file))
    try:
        page_handle = doc_handle[page_index]
        draw_tables_on_page(page_handle, tables, draw_text_boxes=True)
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page_handle.get_pixmap(matrix=matrix, alpha=False)

        if len(doc_handle) == 1 and page_index == 0:
            vis_img_path = out_dir / f"{pdf_file.stem}_visualized.png"
        else:
            vis_img_path = out_dir / f"{pdf_file.stem}_page_{page_index:03d}_visualized.png"
        pix.save(str(vis_img_path))
        print(f"  ✔ 可视化图片已保存: {vis_img_path}")
    finally:
        doc_handle.close()

    # 4. 保存 JSON 与 Markdown 文件
    # json_path = out_dir / f"{pdf_file.stem}_test_out.json"
    # md_path = out_dir / f"{pdf_file.stem}_test_out.md"
    # JSONWriter().write_page(page0, str(json_path))
    # md_writer.write_page(page0, str(md_path))
    # print(f"  ✔ JSON 输出已保存   : {json_path}")
    # print(f"  ✔ Markdown 已保存   : {md_path}")
    print(f"\n[test_single] 测试完成！")


def run_all_missing(
    pdf_dir: str | Path | None = None,
    output_dir: str | Path | None = OUTPUT_DIR,
    dpi: int = RENDER_DPI,
    ml_model_path: str | Path | None = MODEL_PATH,
) -> None:
    """批量解析所有尚未生成可视化图片的 PDF 页面。"""
    if pdf_dir is None:
        pdf_dir = CURRENT_DIR / "pdf_debug"
    p_dir = Path(pdf_dir).resolve()
    out_dir = Path(output_dir or OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_pdfs = sorted(p_dir.glob("*.pdf"))
    missing_pdfs = [p for p in all_pdfs if not (out_dir / f"{p.stem}_visualized.png").exists()]
    total_missing = len(missing_pdfs)
    print(f"================================================================================")
    print(f"[test_single] 扫描目录: {p_dir}")
    print(f"[test_single] 总 PDF 数量: {len(all_pdfs)}, 未处理数量: {total_missing}")
    print(f"================================================================================")

    for idx, pdf in enumerate(missing_pdfs, 1):
        print(f"\n>>>>> [{idx}/{total_missing}] 开始处理: {pdf.name} <<<<<")
        try:
            run_single_test(
                pdf_path=pdf,
                output_dir=out_dir,
                dpi=dpi,
                ml_model_path=ml_model_path,
            )
        except Exception as e:
            print(f"  ❌ 处理失败 {pdf.name}: {e}")

    print(f"\n================================================================================")
    print(f"[test_single] 批量解析完成！共处理 {total_missing} 个 PDF 文件。")
    print(f"================================================================================")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="单页表格提取与可视化单测试验脚本")
    parser.add_argument("target", nargs="?", default=None, help="PDF 路径或页码")
    parser.add_argument("--page", type=int, default=None, help="指定解析的页码索引（0-based）")
    parser.add_argument("--pages", type=str, default=None, help="指定多个页码索引，逗号分隔，如 983,986,1000")
    parser.add_argument("--pdf", type=str, default=TARGET_PDF_PATH, help="指定 PDF 文件路径")
    parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR, help="输出目录")
    parser.add_argument("--dpi", type=int, default=RENDER_DPI, help="渲染 DPI")
    parser.add_argument("--model-path", type=str, default=MODEL_PATH, help="ML 模型路径")
    parser.add_argument("--all", action="store_true", help="批量解析所有未处理的单页 PDF")
    parser.add_argument("--missing", action="store_true", help="批量解析所有未处理的单页 PDF")

    cli_args = parser.parse_args()

    if cli_args.all or cli_args.missing:
        run_all_missing(output_dir=cli_args.output_dir, dpi=cli_args.dpi, ml_model_path=cli_args.model_path)
    elif cli_args.pages:
        page_list = [int(p.strip()) for p in cli_args.pages.split(",") if p.strip()]
        for p_idx in page_list:
            run_single_test(
                pdf_path=cli_args.pdf,
                output_dir=cli_args.output_dir,
                dpi=cli_args.dpi,
                ml_model_path=cli_args.model_path,
                page_index=p_idx,
            )
    elif cli_args.page is not None:
        run_single_test(
            pdf_path=cli_args.pdf,
            output_dir=cli_args.output_dir,
            dpi=cli_args.dpi,
            ml_model_path=cli_args.model_path,
            page_index=cli_args.page,
        )
    elif cli_args.target:
        target = cli_args.target
        if target.isdigit():
            # If target is digits, treat as page index on default target PDF
            run_single_test(
                pdf_path=cli_args.pdf,
                output_dir=cli_args.output_dir,
                dpi=cli_args.dpi,
                ml_model_path=cli_args.model_path,
                page_index=int(target),
            )
        elif not Path(target).is_absolute() and (Path(cli_args.output_dir) / "pdf_debug" / target).exists():
            target_path = Path(cli_args.output_dir) / "pdf_debug" / target
            run_single_test(pdf_path=target_path, output_dir=cli_args.output_dir, dpi=cli_args.dpi, ml_model_path=cli_args.model_path)
        else:
            target_path = Path(target)
            run_single_test(pdf_path=target_path, output_dir=cli_args.output_dir, dpi=cli_args.dpi, ml_model_path=cli_args.model_path)
    else:
        run_single_test(output_dir=cli_args.output_dir, dpi=cli_args.dpi, ml_model_path=cli_args.model_path)
