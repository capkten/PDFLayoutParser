import json
import os
import sys
import glob
import argparse

def compare_characters(base_chars, probe_chars):
    if not base_chars and not probe_chars:
        return {"matched": True, "base_count": 0, "probe_count": 0, "max_h_delta": 0.0, "max_v_delta": 0.0}

    base_text = "".join(c.get("c", "") for c in base_chars)
    probe_text = "".join(c.get("c", "") for c in probe_chars)

    if base_text != probe_text:
        return {
            "matched": False,
            "reason": f"text_mismatch: base='{base_text}' vs probe='{probe_text}'",
            "base_count": len(base_chars),
            "probe_count": len(probe_chars),
            "max_h_delta": 999.0,
            "max_v_delta": 999.0,
        }

    max_h_delta = 0.0
    max_v_delta = 0.0
    for b_c, p_c in zip(base_chars, probe_chars):
        bb = b_c.get("bbox", [0, 0, 0, 0])
        pb = p_c.get("bbox", [0, 0, 0, 0])
        h_d = max(abs(bb[0] - pb[0]), abs(bb[2] - pb[2]))
        v_d = max(abs(bb[1] - pb[1]), abs(bb[3] - pb[3]))
        if h_d > max_h_delta:
            max_h_delta = h_d
        if v_d > max_v_delta:
            max_v_delta = v_d

    return {
        "matched": True,
        "base_count": len(base_chars),
        "probe_count": len(probe_chars),
        "max_h_delta": round(max_h_delta, 4),
        "max_v_delta": round(max_v_delta, 4),
    }

def compare_drawings(base_drawings, probe_drawings, delta_tol=1.0):
    matched_drawings = 0
    used_probe_indices = set()
    drawing_diffs = []
    max_rect_delta = 0.0

    for b_idx, bd in enumerate(base_drawings):
        b_rect = bd["rect"]
        candidates = []
        for p_idx, pd in enumerate(probe_drawings):
            if p_idx in used_probe_indices:
                continue
            p_rect = pd["rect"]
            r_delta = max(abs(b_rect[i] - p_rect[i]) for i in range(4))
            candidates.append((r_delta, p_idx, pd))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            best_delta, best_p_idx, best_pd = candidates[0]
            used_probe_indices.add(best_p_idx)
            if best_delta > max_rect_delta:
                max_rect_delta = best_delta

            # 比较 items
            b_items = bd.get("items", [])
            p_items = best_pd.get("items", [])
            items_matched = len(b_items) == len(p_items)
            item_point_max_delta = 0.0

            if items_matched and b_items:
                for bi, pi in zip(b_items, p_items):
                    if bi.get("cmd") != pi.get("cmd"):
                        items_matched = False
                        break
                    b_pts = bi.get("points", [])
                    p_pts = pi.get("points", [])
                    if len(b_pts) != len(p_pts):
                        items_matched = False
                        break
                    for bp, pp in zip(b_pts, p_pts):
                        pt_d = max(abs(bp[0] - pp[0]), abs(bp[1] - pp[1]))
                        if pt_d > item_point_max_delta:
                            item_point_max_delta = pt_d

            status = "MATCHED" if best_delta <= delta_tol and items_matched else "DELTA_EXCEEDED"
            drawing_diffs.append({
                "base_index": b_idx,
                "probe_index": best_p_idx,
                "status": status,
                "rect_delta": round(best_delta, 4),
                "base_rect": b_rect,
                "probe_rect": best_pd["rect"],
                "base_width": bd.get("width"),
                "probe_width": best_pd.get("width"),
                "items_matched": items_matched,
                "item_point_max_delta": round(item_point_max_delta, 4),
            })
            if status == "MATCHED":
                matched_drawings += 1
        else:
            drawing_diffs.append({
                "base_index": b_idx,
                "status": "PROBE_MISSING",
                "base_rect": b_rect,
            })

    for p_idx, pd in enumerate(probe_drawings):
        if p_idx not in used_probe_indices:
            drawing_diffs.append({
                "probe_index": p_idx,
                "status": "BASE_MISSING",
                "probe_rect": pd["rect"],
            })

    return {
        "base_drawing_count": len(base_drawings),
        "probe_drawing_count": len(probe_drawings),
        "matched_count": matched_drawings,
        "max_rect_delta": round(max_rect_delta, 4),
        "details": drawing_diffs,
    }

def compare_spans(base_spans, probe_spans):
    diff_records = []
    matched_count = 0
    max_bbox_delta = 0.0
    deltas = []
    used_probe_indices = set()

    for b_idx, b_span in enumerate(base_spans):
        b_text = b_span["text"]
        b_bbox = b_span["bbox"]

        # 严格一对一候选匹配
        candidate_indices = [
            i for i, p in enumerate(probe_spans)
            if i not in used_probe_indices and p["text"] == b_text
        ]

        if candidate_indices:
            # 选择 bbox 曼哈顿距离最近且未被占用的候选
            best_idx = min(
                candidate_indices,
                key=lambda i: sum(abs(probe_spans[i]["bbox"][k] - b_bbox[k]) for k in range(4))
            )
            used_probe_indices.add(best_idx)
            best = probe_spans[best_idx]

            d = [abs(best["bbox"][k] - b_bbox[k]) for k in range(4)]
            max_d = max(d)
            deltas.append(max_d)
            if max_d > max_bbox_delta:
                max_bbox_delta = max_d
            matched_count += 1

            # 字符级检查
            char_res = compare_characters(b_span.get("characters", []), best.get("characters", []))

            diff_records.append({
                "status": "MATCHED",
                "base_order": b_span.get("order"),
                "probe_order": best.get("order"),
                "text": b_text,
                "base_bbox": b_bbox,
                "probe_bbox": best["bbox"],
                "delta_max": round(max_d, 4),
                "delta_x0": round(abs(best["bbox"][0] - b_bbox[0]), 4),
                "delta_y0": round(abs(best["bbox"][1] - b_bbox[1]), 4),
                "delta_x1": round(abs(best["bbox"][2] - b_bbox[2]), 4),
                "delta_y1": round(abs(best["bbox"][3] - b_bbox[3]), 4),
                "base_font": b_span.get("font"),
                "probe_font": best.get("font"),
                "base_size": b_span.get("size"),
                "probe_size": best.get("size"),
                "char_verification": char_res,
            })
        else:
            diff_records.append({
                "status": "PROBE_MISSING",
                "base_order": b_span.get("order"),
                "text": b_text,
                "base_bbox": b_bbox,
                "probe_bbox": None,
            })

    for p_idx, p_span in enumerate(probe_spans):
        if p_idx not in used_probe_indices:
            diff_records.append({
                "status": "BASE_MISSING",
                "probe_order": p_span.get("order"),
                "text": p_span["text"],
                "base_bbox": None,
                "probe_bbox": p_span["bbox"],
            })

    p95_delta = 0.0
    if deltas:
        deltas.sort()
        p95_delta = deltas[int(len(deltas) * 0.95)]

    return {
        "base_span_count": len(base_spans),
        "probe_span_count": len(probe_spans),
        "matched_count": matched_count,
        "max_bbox_delta": round(max_bbox_delta, 4),
        "p95_bbox_delta": round(p95_delta, 4),
        "details": diff_records,
    }

def compare_file(base_path, probe_path):
    with open(base_path, "r", encoding="utf-8") as f:
        base = json.load(f)
    with open(probe_path, "r", encoding="utf-8") as f:
        probe = json.load(f)

    file_diff = {
        "file": base["source_file"],
        "base_page_count": base["page_count"],
        "probe_page_count": probe["page_count"],
        "pages": [],
    }

    for p_idx in range(min(base["page_count"], probe["page_count"])):
        bp = base["pages"][p_idx]
        pp = probe["pages"][p_idx]

        geo_diff = {
            "page_index": p_idx,
            "width_match": bp["width"] == pp["width"],
            "height_match": bp["height"] == pp["height"],
            "rotation_match": bp["rotation"] == pp["rotation"],
            "base_dims": (bp["width"], bp["height"], bp["rotation"]),
            "probe_dims": (pp["width"], pp["height"], pp["rotation"]),
        }

        span_diff = compare_spans(bp.get("spans", []), pp.get("spans", []))
        drawing_diff = compare_drawings(bp.get("drawings", []), pp.get("drawings", []))

        file_diff["pages"].append({
            "geometry": geo_diff,
            "spans": span_diff,
            "drawings": drawing_diff,
        })

    return file_diff

def main():
    parser = argparse.ArgumentParser(description="Sprint 1 Double-Parser Comparator (PyMuPDF vs PDFium Probe)")
    parser.add_argument("--max-delta-threshold", type=float, default=0.5,
                        help="Maximum allowable bbox delta threshold (default 0.5 pt)")
    parser.add_argument("--strict-gate", action="store_true", default=True,
                        help="Enforce strict gate and return non-zero exit code if not compliant")
    parser.add_argument("--no-strict-gate", dest="strict_gate", action="store_false",
                        help="Run in diagnostic report mode without non-zero exit code")
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    baseline_dir = os.path.join(root, "test_data", "baseline")
    probe_dir = os.path.join(root, "test_data", "pdfium_output")

    report = []
    base_files = glob.glob(os.path.join(baseline_dir, "*_pymupdf.json"))
    for bf in base_files:
        name = os.path.basename(bf).replace("_pymupdf.json", "")
        pf = os.path.join(probe_dir, f"{name}_pdfium.json")
        if os.path.exists(pf):
            file_diff = compare_file(bf, pf)
            report.append(file_diff)

    out_report_path = os.path.join(root, "diff_report_synthetic.json")
    with open(out_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Comparison complete! Detailed JSON report written to {out_report_path}")

    gate_failures = []

    print("\n" + "="*80)
    print("      Sprint 1 Synthetic Double-Parser Comparison Summary (1-to-1)")
    print("="*80)
    for r in report:
        print(f"\n[Case] {r['file']}")
        for p in r["pages"]:
            geo = p["geometry"]
            s = p["spans"]
            d = p["drawings"]
            p_idx = geo["page_index"]
            dims_ok = geo["width_match"] and geo["height_match"] and geo["rotation_match"]
            if not dims_ok:
                gate_failures.append(f"{r['file']} p{p_idx}: Geometry mismatch (Base={geo['base_dims']} vs Probe={geo['probe_dims']})")

            print(f"  Page {p_idx}:")
            print(f"    - Geometry: Dims Match={dims_ok} (Base={geo['base_dims']}, Probe={geo['probe_dims']})")
            print(f"    - Spans   : Base={s['base_span_count']}, Probe={s['probe_span_count']}, Matched={s['matched_count']}, Max BBox Delta={s['max_bbox_delta']} pt, P95={s['p95_bbox_delta']} pt")
            print(f"    - Drawings: Base={d['base_drawing_count']}, Probe={d['probe_drawing_count']}, Matched={d['matched_count']}, Max Rect Delta={d['max_rect_delta']} pt")

            # 检查缺失与差异
            for item in s["details"]:
                if item["status"] != "MATCHED":
                    print(f"      * [Span {item['status']}]: '{item['text']}'")
                    # 记录门禁失败：非空白文本缺失
                    if item["status"] == "PROBE_MISSING" and item["text"].strip():
                        gate_failures.append(f"{r['file']} p{p_idx}: Non-empty span missing in probe: '{item['text']}'")
                    elif item["status"] == "PROBE_MISSING" and not item["text"].strip():
                        gate_failures.append(f"{r['file']} p{p_idx}: Whitespace span missing in probe: '{item['text']}' (Base span count={s['base_span_count']} vs Probe={s['probe_span_count']})")
                elif item["delta_max"] > args.max_delta_threshold:
                    # 记录门禁失败：超差
                    pass # 稍后汇总统计最大超差

            if s["max_bbox_delta"] > args.max_delta_threshold:
                gate_failures.append(f"{r['file']} p{p_idx}: Max BBox Delta {s['max_bbox_delta']} pt > threshold {args.max_delta_threshold} pt")

            if d["base_drawing_count"] != d["probe_drawing_count"]:
                gate_failures.append(f"{r['file']} p{p_idx}: Drawing count mismatch: Base={d['base_drawing_count']} vs Probe={d['probe_drawing_count']}")

    print("\n" + "="*80)
    print("                    Sprint 1 Quality Gate Verdict")
    print("="*80)
    if gate_failures:
        print(f"STATUS: FAILED ({len(gate_failures)} gate violations found)")
        for idx, fail in enumerate(gate_failures, 1):
            print(f"  {idx}. {fail}")
        print("\nConclusion: Sprint 1 quality gate NOT PASSED. Sub-word grain aggregation & bbox alignment needed.")
        if args.strict_gate:
            sys.exit(1)
    else:
        print("STATUS: PASSED (All synthetic checks meet strict criteria)")
        sys.exit(0)

if __name__ == "__main__":
    main()
