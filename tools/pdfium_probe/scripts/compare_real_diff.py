import json
import os
import sys
import glob
from compare_synthetic_diff import compare_file

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    baseline_dir = os.path.join(root, "test_data", "real_baseline")
    probe_dir = os.path.join(root, "test_data", "real_pdfium_output")

    report = []
    base_files = glob.glob(os.path.join(baseline_dir, "*_pymupdf.json"))
    for bf in base_files:
        sample_name = os.path.basename(bf).replace("_pymupdf.json", "")
        pf = os.path.join(probe_dir, f"{sample_name}_pdfium.json")
        if os.path.exists(pf):
            file_diff = compare_file(bf, pf)
            file_diff["sample_name"] = sample_name
            report.append(file_diff)

    out_report_path = os.path.join(root, "diff_report_real.json")
    with open(out_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Real sample comparison complete! Detailed JSON report written to {out_report_path}")

    print("\n" + "="*80)
    print("      Sprint 1 Real Representative Samples Double-Parser Summary (1-to-1)")
    print("="*80)

    total_base_spans = 0
    total_probe_spans = 0
    total_matched_spans = 0

    for r in sorted(report, key=lambda x: x.get("sample_name", "")):
        sname = r.get("sample_name", r["file"])
        print(f"\n[Real Sample] {sname} (source: {r['file']})")
        for p in r["pages"]:
            geo = p["geometry"]
            s = p["spans"]
            d = p["drawings"]
            p_idx = geo["page_index"]

            total_base_spans += s["base_span_count"]
            total_probe_spans += s["probe_span_count"]
            total_matched_spans += s["matched_count"]

            dims_ok = geo["width_match"] and geo["height_match"] and geo["rotation_match"]
            print(f"  Page {p_idx}:")
            print(f"    - Geometry: Dims Match={dims_ok} (Base={geo['base_dims']}, Probe={geo['probe_dims']})")
            print(f"    - Spans   : Base={s['base_span_count']}, Probe={s['probe_span_count']} (TextObjects), Matched={s['matched_count']}, Max BBox Delta={s['max_bbox_delta']} pt, P95={s['p95_bbox_delta']} pt")
            print(f"    - Drawings: Base={d['base_drawing_count']}, Probe={d['probe_drawing_count']}, Matched={d['matched_count']}, Max Rect Delta={d['max_rect_delta']} pt")

            unmatched_base = [item for item in s["details"] if item["status"] == "PROBE_MISSING"]
            unmatched_probe = [item for item in s["details"] if item["status"] == "BASE_MISSING"]
            print(f"    - Unmatched Base Spans: {len(unmatched_base)} / {s['base_span_count']}")
            print(f"    - Unmatched Probe Objs: {len(unmatched_probe)} / {s['probe_span_count']}")
            if unmatched_base:
                print("      * Sample Missing Base Spans:")
                for m in unmatched_base[:4]:
                    print(f"        [PROBE_MISSING]: '{m['text']}'")
            if unmatched_probe:
                print("      * Sample Atomic Probe TextObjects (Unaggregated):")
                for m in unmatched_probe[:4]:
                    print(f"        [BASE_MISSING] : '{m['text']}'")

    print("\n" + "="*80)
    print("                    Real Samples Aggregate Verdict")
    print("="*80)
    print(f"Total Base Spans  : {total_base_spans}")
    print(f"Total Probe Objs  : {total_probe_spans} (Ratio: {total_probe_spans / max(1, total_base_spans):.2f}x)")
    print(f"Total 1:1 Matched : {total_matched_spans} ({total_matched_spans / max(1, total_base_spans) * 100:.1f}% of base spans)")
    print("\nConclusion: Grain mismatch prevents direct feed to downstream table recovery.")
    print("STATUS: GATE NOT PASSED (Requires Span Horizontal Aggregator in Sprint 2).")

if __name__ == "__main__":
    main()
