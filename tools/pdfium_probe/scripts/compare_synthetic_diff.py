import json
import os
import sys
import glob
import argparse

def compare_characters(base_chars, probe_chars, h_tol=0.5, v_tol=0.5):
    """
    逐字符对比文本内容与 BBox。
    只有当文本内容完全一致且字符数量匹配时，才计算字符级坐标偏移。
    """
    if not base_chars and not probe_chars:
        return {
            "matched": True,
            "base_count": 0,
            "probe_count": 0,
            "max_h_delta": 0.0,
            "max_v_delta": 0.0,
            "h_passed": True,
            "v_passed": True,
        }

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
            "h_passed": False,
            "v_passed": False,
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

    h_passed = max_h_delta <= h_tol
    v_passed = max_v_delta <= v_tol

    return {
        "matched": True,
        "base_count": len(base_chars),
        "probe_count": len(probe_chars),
        "max_h_delta": round(max_h_delta, 4),
        "max_v_delta": round(max_v_delta, 4),
        "h_passed": h_passed,
        "v_passed": v_passed,
    }

def match_line_segments(b_pts, p_pts, point_tol=0.5):
    """
    比对线段端点，支持线段首尾方向翻转 (A->B 等价于 B->A)。
    """
    if len(b_pts) != 2 or len(p_pts) != 2:
        if len(b_pts) != len(p_pts):
            return False, 999.0
        max_d = 0.0
        for bp, pp in zip(b_pts, p_pts):
            d = max(abs(bp[0] - pp[0]), abs(bp[1] - pp[1]))
            if d > max_d:
                max_d = d
        return max_d <= point_tol, max_d

    # 正向匹配
    d_fwd = max(
        max(abs(b_pts[0][0] - p_pts[0][0]), abs(b_pts[0][1] - p_pts[0][1])),
        max(abs(b_pts[1][0] - p_pts[1][0]), abs(b_pts[1][1] - p_pts[1][1]))
    )
    # 反向匹配
    d_rev = max(
        max(abs(b_pts[0][0] - p_pts[1][0]), abs(b_pts[0][1] - p_pts[1][1])),
        max(abs(b_pts[1][0] - p_pts[0][0]), abs(b_pts[1][1] - p_pts[0][1]))
    )
    min_d = min(d_fwd, d_rev)
    return min_d <= point_tol, min_d

def compare_drawings(base_drawings, probe_drawings, rect_tol=0.5, point_tol=0.5):
    """
    严格 1:1 矢量线段与路径拓扑比较。
    支持：
    1. 几何包围盒容差比较 (|rect_delta| <= rect_tol)
    2. 端点容差比较 (|point_delta| <= point_tol，支持端点反向)
    3. 矩形语义等价判定 (PyMuPDF 're' 指令与 PDFium 4 段 'l' 闭合路径的几何等价)
    """
    matched_drawings = 0
    used_probe_indices = set()
    drawing_diffs = []
    max_rect_delta = 0.0
    max_point_delta = 0.0

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

            b_items = bd.get("items", [])
            p_items = best_pd.get("items", [])

            # 语义等价检查：PyMuPDF 're' vs PDFium 4 段 'l' 封闭矩形
            is_semantic_rect = False
            if len(b_items) == 1 and b_items[0].get("cmd") == "re" and len(p_items) == 4:
                if all(it.get("cmd") == "l" for it in p_items):
                    if best_delta <= rect_tol:
                        is_semantic_rect = True

            items_matched = False
            item_point_max_delta = 0.0

            if is_semantic_rect:
                items_matched = True
                status = "MATCHED_SEMANTIC_RECT"
            elif len(b_items) == len(p_items) and b_items:
                all_segs_ok = True
                for bi, pi in zip(b_items, p_items):
                    if bi.get("cmd") != pi.get("cmd"):
                        all_segs_ok = False
                        break
                    b_pts = bi.get("points", [])
                    p_pts = pi.get("points", [])
                    seg_ok, seg_d = match_line_segments(b_pts, p_pts, point_tol=point_tol)
                    if seg_d > item_point_max_delta:
                        item_point_max_delta = seg_d
                    if not seg_ok:
                        all_segs_ok = False
                        break
                items_matched = all_segs_ok
                if item_point_max_delta > max_point_delta:
                    max_point_delta = item_point_max_delta

                if best_delta <= rect_tol and items_matched:
                    status = "MATCHED_EXACT"
                elif best_delta > rect_tol:
                    status = "RECT_DELTA_EXCEEDED"
                else:
                    status = "POINT_DELTA_EXCEEDED"
            elif not b_items and not p_items:
                items_matched = True
                status = "MATCHED_EXACT" if best_delta <= rect_tol else "RECT_DELTA_EXCEEDED"
            else:
                status = "TOPOLOGY_MISMATCH"

            drawing_diffs.append({
                "base_index": b_idx,
                "probe_index": best_p_idx,
                "status": status,
                "rect_delta": round(best_delta, 4),
                "point_delta": round(item_point_max_delta, 4),
                "base_rect": b_rect,
                "probe_rect": best_pd["rect"],
                "base_width": bd.get("width"),
                "probe_width": best_pd.get("width"),
                "items_matched": items_matched,
            })
            if status in ["MATCHED_EXACT", "MATCHED_SEMANTIC_RECT"]:
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
        "max_point_delta": round(max_point_delta, 4),
        "details": drawing_diffs,
    }

def compute_order_inversions(matched_pairs):
    """
    计算匹配 Span 的读取顺序逆序对数 (Inversion count)。
    matched_pairs: [(base_order, probe_order, text), ...] 已经按 base_order 递增排序。
    """
    inversions = []
    n = len(matched_pairs)
    for i in range(n):
        for j in range(i + 1, n):
            if matched_pairs[i][1] > matched_pairs[j][1]:
                inversions.append({
                    "span_a": {"base_order": matched_pairs[i][0], "probe_order": matched_pairs[i][1], "text": matched_pairs[i][2]},
                    "span_b": {"base_order": matched_pairs[j][0], "probe_order": matched_pairs[j][1], "text": matched_pairs[j][2]},
                })
    total_possible = (n * (n - 1)) // 2 if n > 1 else 1
    ratio = len(inversions) / total_possible if n > 1 else 0.0
    return {
        "inversion_count": len(inversions),
        "inversion_ratio": round(ratio, 4),
        "inversions": inversions[:5], # 最多保留 5 组样本
    }

def compare_spans(base_spans, probe_spans, bbox_tol=0.5, char_h_tol=0.5, char_v_tol=0.5):
    diff_records = []
    matched_count = 0
    max_bbox_delta = 0.0
    deltas = []
    used_probe_indices = set()
    matched_order_pairs = []

    for b_idx, b_span in enumerate(base_spans):
        b_text = b_span["text"]
        b_bbox = b_span["bbox"]

        # 严格 1:1 文本完全一致候选
        candidate_indices = [
            i for i, p in enumerate(probe_spans)
            if i not in used_probe_indices and p["text"] == b_text
        ]

        if candidate_indices:
            # 找到最近且未使用的 probe span
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

            # 字符级检查
            char_res = compare_characters(
                b_span.get("characters", []),
                best.get("characters", []),
                h_tol=char_h_tol,
                v_tol=char_v_tol
            )

            # 判定状态：若字符序列不匹配，标记为 CHAR_MISMATCH；超差则 DELTA_EXCEEDED
            if not char_res["matched"]:
                status = "CHAR_MISMATCH"
            elif max_d > bbox_tol:
                status = "DELTA_EXCEEDED"
            else:
                status = "MATCHED"

            if status in ["MATCHED", "DELTA_EXCEEDED"]:
                matched_count += 1
                matched_order_pairs.append((b_span.get("order", b_idx), best.get("order", best_idx), b_text))

            diff_records.append({
                "status": status,
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

    # 排序并计算逆序数
    matched_order_pairs.sort(key=lambda x: x[0])
    order_inversion_info = compute_order_inversions(matched_order_pairs)

    return {
        "base_span_count": len(base_spans),
        "probe_span_count": len(probe_spans),
        "matched_count": matched_count,
        "max_bbox_delta": round(max_bbox_delta, 4),
        "p95_bbox_delta": round(p95_delta, 4),
        "order_inversion": order_inversion_info,
        "details": diff_records,
    }

def compare_file(base_path, probe_path, bbox_tol=0.5, rect_tol=0.5, point_tol=0.5):
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
            "probe_dims": (pp["width"], pp["height"], bp["rotation"]),
        }

        span_diff = compare_spans(bp.get("spans", []), pp.get("spans", []), bbox_tol=bbox_tol)
        drawing_diff = compare_drawings(bp.get("drawings", []), pp.get("drawings", []), rect_tol=rect_tol, point_tol=point_tol)

        file_diff["pages"].append({
            "geometry": geo_diff,
            "spans": span_diff,
            "drawings": drawing_diff,
        })

    return file_diff

def main():
    parser = argparse.ArgumentParser(description="Sprint 1 Double-Parser Comparator (PyMuPDF vs PDFium Probe)")
    parser.add_argument("--bbox-tol", type=float, default=0.5,
                        help="Maximum allowable span bbox delta threshold (default 0.5 pt)")
    parser.add_argument("--rect-tol", type=float, default=0.5,
                        help="Maximum allowable drawing rect delta threshold (default 0.5 pt)")
    parser.add_argument("--point-tol", type=float, default=0.5,
                        help="Maximum allowable line endpoint delta threshold (default 0.5 pt)")
    parser.add_argument("--max-inversions", type=int, default=0,
                        help="Maximum allowable span order inversion count (default 0)")
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
            file_diff = compare_file(bf, pf, bbox_tol=args.bbox_tol, rect_tol=args.rect_tol, point_tol=args.point_tol)
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

            inversion_info = s.get("order_inversion", {})
            inv_count = inversion_info.get("inversion_count", 0)

            print(f"  Page {p_idx}:")
            print(f"    - Geometry: Dims Match={dims_ok} (Base={geo['base_dims']}, Probe={geo['probe_dims']})")
            print(f"    - Spans   : Base={s['base_span_count']}, Probe={s['probe_span_count']}, Matched={s['matched_count']}, Max BBox Delta={s['max_bbox_delta']} pt, P95={s['p95_bbox_delta']} pt, Inversions={inv_count}")
            print(f"    - Drawings: Base={d['base_drawing_count']}, Probe={d['probe_drawing_count']}, Matched={d['matched_count']}, Max Rect Delta={d['max_rect_delta']} pt, Max Point Delta={d['max_point_delta']} pt")

            # 检查缺失与异常
            for item in s["details"]:
                if item["status"] == "CHAR_MISMATCH":
                    gate_failures.append(f"{r['file']} p{p_idx}: Character text mismatch in span '{item['text']}'")
                elif item["status"] == "PROBE_MISSING" and item["text"].strip():
                    gate_failures.append(f"{r['file']} p{p_idx}: Non-empty span missing in probe: '{item['text']}'")
                elif item["status"] == "PROBE_MISSING" and not item["text"].strip():
                    gate_failures.append(f"{r['file']} p{p_idx}: Whitespace span missing in probe: '{item['text']}' (Base span count={s['base_span_count']} vs Probe={s['probe_span_count']})")
                elif item["status"] == "DELTA_EXCEEDED":
                    pass # 统一由 s["max_bbox_delta"] 汇总结算

            if s["max_bbox_delta"] > args.bbox_tol:
                gate_failures.append(f"{r['file']} p{p_idx}: Max BBox Delta {s['max_bbox_delta']} pt > threshold {args.bbox_tol} pt")

            if inv_count > args.max_inversions:
                gate_failures.append(f"{r['file']} p{p_idx}: Span order inversion count {inv_count} > threshold {args.max_inversions}")

            if d["base_drawing_count"] != d["probe_drawing_count"]:
                gate_failures.append(f"{r['file']} p{p_idx}: Drawing count mismatch: Base={d['base_drawing_count']} vs Probe={d['probe_drawing_count']}")
            elif d["matched_count"] != d["base_drawing_count"]:
                gate_failures.append(f"{r['file']} p{p_idx}: Drawing topology match mismatch: Base={d['base_drawing_count']} vs Matched={d['matched_count']}")

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
