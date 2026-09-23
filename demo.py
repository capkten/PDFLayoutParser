from pathlib import Path
import sys
import json
import argparse


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hexai_pdf_parser import parse_personal_credit_report


def main():
    parser = argparse.ArgumentParser(description="解析个人信用报告并输出可视化结果")
    parser.add_argument("pdf_path", nargs="?", help="待解析的 PDF 路径")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="输出目录；默认写入 output/demo/<PDF 文件名>/",
    )
    parser.add_argument(
        "--wired-line-tolerance",
        type=float,
        default=2.2,
        help="个人征信报告有线表格线段合并容差（默认：2.2）",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path) if args.pdf_path else ROOT / "征信解析样例.pdf"
    output_dir = args.output_dir or ROOT / "output" / "demo" / pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"正在解析: {pdf_path}")
    document = parse_personal_credit_report(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        use_ml_table_detector=False,
        wired_line_tolerance=args.wired_line_tolerance,
    )
    out_json = output_dir / f"{pdf_path.stem}.json"
    with out_json.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
    print(f"解析结果已写入: {out_json}")
    print(f"可视化目录已写入: {output_dir}")


if __name__ == "__main__":
    main()
