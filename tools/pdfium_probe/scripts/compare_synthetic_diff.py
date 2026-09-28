import json
import os
import sys
import glob
import argparse
import hashlib

def compute_file_sha256(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

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

def compare_drawings(base_drawings, probe_drawings, rect_tol=0.5, point_tol=0.5, width_tol=0.95):
    """
    严格 1:1 矢量线段与路径拓扑比较。
    支持：
    1. 几何包围盒容差比较 (|rect_delta| <= rect_tol)
    2. 端点容差比较 (|point_delta| <= point_tol，支持端点反向)
    3. 线宽容差比较 (|width_delta| <= width_tol，容忍发丝线 0.05pt 与默认 1.0pt)
    4. 矩形语义等价判定 (PyMuPDF 're' 指令与 PDFium 4 段 'l' 闭合路径的几何等价)
    """
    matched_drawings = 0
    used_probe_indices = set()
    drawing_diffs = []
    max_rect_delta = 0.0
    max_point_delta = 0.0
    max_width_delta = 0.0

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

            b_w = bd.get("width")
            p_w = best_pd.get("width")
            width_missing = (b_w is None) ^ (p_w is None)
            raw_width_delta = None
            width_delta = None
            if b_w is not None and p_w is not None:
                raw_width_delta = abs(b_w - p_w)
                width_delta = round(raw_width_delta, 4)
                if raw_width_delta > max_width_delta:
                    max_width_delta = raw_width_delta
            elif b_w is None and p_w is None:
                raw_width_delta = 0.0
                width_delta = 0.0

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
                if best_delta > rect_tol:
                    status = "RECT_DELTA_EXCEEDED"
                elif width_missing:
                    status = "WIDTH_DATA_MISSING"
                elif raw_width_delta is not None and raw_width_delta > width_tol:
                    status = "WIDTH_DELTA_EXCEEDED"
                else:
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

                if best_delta > rect_tol:
                    status = "RECT_DELTA_EXCEEDED"
                elif not items_matched:
                    status = "POINT_DELTA_EXCEEDED"
                elif width_missing:
                    status = "WIDTH_DATA_MISSING"
                elif raw_width_delta is not None and raw_width_delta > width_tol:
                    status = "WIDTH_DELTA_EXCEEDED"
                else:
                    status = "MATCHED_EXACT"
            elif not b_items and not p_items:
                items_matched = True
                if best_delta > rect_tol:
                    status = "RECT_DELTA_EXCEEDED"
                elif width_missing:
                    status = "WIDTH_DATA_MISSING"
                elif raw_width_delta is not None and raw_width_delta > width_tol:
                    status = "WIDTH_DELTA_EXCEEDED"
                else:
                    status = "MATCHED_EXACT"
            else:
                status = "TOPOLOGY_MISMATCH"

            # 只有当 rect, items, width 三者均满足容差时，才计入 matched_drawings
            is_matched = status in ["MATCHED_EXACT", "MATCHED_SEMANTIC_RECT"]
            if is_matched:
                matched_drawings += 1

            drawing_diffs.append({
                "base_index": b_idx,
                "probe_index": best_p_idx,
                "status": status,
                "rect_delta": round(best_delta, 4),
                "point_delta": round(item_point_max_delta, 4),
                "width_delta": width_delta,
                "width_missing": width_missing,
                "base_rect": b_rect,
                "probe_rect": best_pd["rect"],
                "base_width": b_w,
                "probe_width": p_w,
                "items_matched": items_matched,
            })
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
        "raw_max_rect_delta": max_rect_delta,
        "max_rect_delta": round(max_rect_delta, 4),
        "raw_max_point_delta": max_point_delta,
        "max_point_delta": round(max_point_delta, 4),
        "raw_max_width_delta": max_width_delta,
        "max_width_delta": round(max_width_delta, 4),
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
    """
    分层统计文本比对指标：
    - candidate_match_count: 找到相同文本 1:1 候选的基准 Span 数量
    - char_match_count: 候选对象内部字符序列完全匹配的数量
    - bbox_pass_count: 候选对象 BBox 最大误差 <= bbox_tol 的数量
    - fully_accepted_count: 文本匹配、字符匹配且 BBox 均达标的数量 (通过门禁)
    - missing_count: 根本未找到候选的基准 Span 数量
    """
    diff_records = []
    candidate_match_count = 0
    char_match_count = 0
    bbox_pass_count = 0
    fully_accepted_count = 0
    missing_count = 0

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
            candidate_match_count += 1
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
            if char_res["matched"]:
                char_match_count += 1

            bbox_ok = max_d <= bbox_tol
            if bbox_ok:
                bbox_pass_count += 1

            # 判定状态
            if not char_res["matched"]:
                status = "CHAR_MISMATCH"
            elif not bbox_ok:
                status = "DELTA_EXCEEDED"
            else:
                status = "MATCHED"

            if status == "MATCHED":
                fully_accepted_count += 1

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
            missing_count += 1
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
        "candidate_match_count": candidate_match_count,
        "char_match_count": char_match_count,
        "bbox_pass_count": bbox_pass_count,
        "fully_accepted_count": fully_accepted_count,
        "missing_count": missing_count,
        "raw_max_bbox_delta": max_bbox_delta,
        "max_bbox_delta": round(max_bbox_delta, 4),
        "p95_bbox_delta": round(p95_delta, 4),
        "order_inversion": order_inversion_info,
        "details": diff_records,
    }

def compare_file(base_path, probe_path, bbox_tol=0.5, rect_tol=0.5, point_tol=0.5, width_tol=0.95):
    with open(base_path, "r", encoding="utf-8") as f:
        base = json.load(f)
    with open(probe_path, "r", encoding="utf-8") as f:
        probe = json.load(f)

    page_count_match = base["page_count"] == probe["page_count"]
    file_diff = {
        "file": base["source_file"],
        "base_page_count": base["page_count"],
        "probe_page_count": probe["page_count"],
        "page_count_match": page_count_match,
        "base_schema": base.get("schema_version", "legacy_snapshot"),
        "probe_schema": probe.get("schema_version", "unknown"),
        "pages": [],
    }

    max_pages = max(base["page_count"], probe["page_count"])
    for p_idx in range(max_pages):
        if p_idx >= len(base["pages"]):
            file_diff["pages"].append({
                "page_index": p_idx,
                "status": "BASE_PAGE_MISSING",
            })
            continue
        if p_idx >= len(probe["pages"]):
            file_diff["pages"].append({
                "page_index": p_idx,
                "status": "PROBE_PAGE_MISSING",
            })
            continue

        bp = base["pages"][p_idx]
        pp = probe["pages"][p_idx]

        b_crop = bp.get("crop_box")
        p_crop = pp.get("crop_box")
        crop_delta = max(abs(b_crop[i] - p_crop[i]) for i in range(4)) if b_crop and p_crop else 0.0

        b_media = bp.get("media_box")
        p_media = pp.get("media_box")
        media_delta = max(abs(b_media[i] - p_media[i]) for i in range(4)) if b_media and p_media else 0.0

        geo_diff = {
            "page_index": p_idx,
            "width_match": bp["width"] == pp["width"],
            "height_match": bp["height"] == pp["height"],
            "rotation_match": bp["rotation"] == pp["rotation"],
            "crop_match": crop_delta <= rect_tol,
            "media_match": media_delta <= rect_tol,
            "crop_delta": round(crop_delta, 4),
            "media_delta": round(media_delta, 4),
            "base_dims": (bp["width"], bp["height"], bp["rotation"]),
            "probe_dims": (pp["width"], pp["height"], pp["rotation"]),
            "base_crop": b_crop,
            "probe_crop": p_crop,
        }

        span_diff = compare_spans(bp.get("spans", []), pp.get("spans", []), bbox_tol=bbox_tol)
        drawing_diff = compare_drawings(
            bp.get("drawings", []),
            pp.get("drawings", []),
            rect_tol=rect_tol,
            point_tol=point_tol,
            width_tol=width_tol
        )

        file_diff["pages"].append({
            "page_index": p_idx,
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
    parser.add_argument("--width-tol", type=float, default=0.95,
                        help="Maximum allowable stroke width delta threshold (default 0.95 pt)")
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
    hash_ledger = []
    gate_failures = []

    synthetic_pdf_dir = os.path.join(root, "test_data", "synthetic")
    base_files = glob.glob(os.path.join(baseline_dir, "*_pymupdf.json"))

    if not base_files:
        gate_failures.append("No baseline JSON files found in test_data/baseline")

    for bf in sorted(base_files):
        name = os.path.basename(bf).replace("_pymupdf.json", "")
        pdf_file = os.path.join(synthetic_pdf_dir, f"{name}.pdf")
        pf = os.path.join(probe_dir, f"{name}_pdfium.json")

        pdf_sha = compute_file_sha256(pdf_file)
        base_sha = compute_file_sha256(bf)
        probe_sha = compute_file_sha256(pf)

        hash_ledger.append({
            "name": name,
            "pdf_file": pdf_file if os.path.exists(pdf_file) else None,
            "pdf_sha256": pdf_sha,
            "baseline_json": bf,
            "baseline_sha256": base_sha,
            "probe_json": pf,
            "probe_sha256": probe_sha,
        })

        if not os.path.exists(pf):
            gate_failures.append(f"Missing probe output file for baseline: {name}_pdfium.json")
            report.append({
                "file": f"{name}.pdf",
                "status": "PROBE_FILE_MISSING",
                "base_file": bf,
                "probe_file": pf,
                "pages": [],
            })
            continue

        file_diff = compare_file(
            bf, pf,
            bbox_tol=args.bbox_tol,
            rect_tol=args.rect_tol,
            point_tol=args.point_tol,
            width_tol=args.width_tol
        )
        report.append(file_diff)

    out_report_path = os.path.join(root, "diff_report_synthetic.json")
    with open(out_report_path, "w", encoding="utf-8") as f:
        json.dump({"summary_report": report, "hash_ledger": hash_ledger}, f, ensure_ascii=False, indent=2)
    print(f"Comparison complete! Detailed JSON report written to {out_report_path}")

    print("\n" + "="*80)
    print("      Sprint 1 Synthetic Double-Parser Comparison Summary (1-to-1)")
    print("="*80)
    for r in report:
        if r.get("status") == "PROBE_FILE_MISSING":
            print(f"\n[Case] {r['file']}: PROBE FILE MISSING ({r['probe_file']})")
            continue

        print(f"\n[Case] {r['file']}")
        if not r.get("page_count_match", True):
            gate_failures.append(f"{r['file']}: Page count mismatch (Base={r['base_page_count']} vs Probe={r['probe_page_count']})")
            print(f"  * Page count mismatch: Base={r['base_page_count']} vs Probe={r['probe_page_count']}")

        for p in r["pages"]:
            p_idx = p["page_index"]
            if p.get("status") == "BASE_PAGE_MISSING":
                gate_failures.append(f"{r['file']} p{p_idx}: Missing base page")
                print(f"  Page {p_idx}: BASE_PAGE_MISSING")
                continue
            if p.get("status") == "PROBE_PAGE_MISSING":
                gate_failures.append(f"{r['file']} p{p_idx}: Missing probe page")
                print(f"  Page {p_idx}: PROBE_PAGE_MISSING")
                continue

            geo = p["geometry"]
            s = p["spans"]
            d = p["drawings"]

            dims_ok = geo["width_match"] and geo["height_match"] and geo["rotation_match"]
            crop_ok = geo.get("crop_match", True)
            media_ok = geo.get("media_match", True)

            if not dims_ok:
                gate_failures.append(f"{r['file']} p{p_idx}: Geometry dimension mismatch (Base={geo['base_dims']} vs Probe={geo['probe_dims']})")
            if not crop_ok:
                gate_failures.append(f"{r['file']} p{p_idx}: CropBox delta {geo.get('crop_delta')} pt > threshold {args.rect_tol} pt")
            if not media_ok:
                gate_failures.append(f"{r['file']} p{p_idx}: MediaBox delta {geo.get('media_delta')} pt > threshold {args.rect_tol} pt")

            inversion_info = s.get("order_inversion", {})
            inv_count = inversion_info.get("inversion_count", 0)

            print(f"  Page {p_idx}:")
            print(f"    - Geometry: Dims Match={dims_ok} (Base={geo['base_dims']}, Probe={geo['probe_dims']}), CropMatch={crop_ok}")
            print(f"    - Spans   : Base={s['base_span_count']}, Probe={s['probe_span_count']} | Candidates={s['candidate_match_count']}, CharsOK={s['char_match_count']}, BBoxPass={s['bbox_pass_count']}, FullyAccepted={s['fully_accepted_count']}, Missing={s['missing_count']}")
            print(f"                Max BBox Delta={s['max_bbox_delta']} pt, P95={s['p95_bbox_delta']} pt, Inversions={inv_count}")
            print(f"    - Drawings: Base={d['base_drawing_count']}, Probe={d['probe_drawing_count']}, Matched={d['matched_count']}")
            print(f"                Max Rect Delta={d['max_rect_delta']} pt, Max Point Delta={d['max_point_delta']} pt, Max Width Delta={d['max_width_delta']} pt")

            # 检查缺失与异常
            for item in s["details"]:
                if item["status"] == "CHAR_MISMATCH":
                    gate_failures.append(f"{r['file']} p{p_idx}: Character text mismatch in span '{item['text']}'")
                elif item["status"] == "PROBE_MISSING" and item["text"].strip():
                    gate_failures.append(f"{r['file']} p{p_idx}: Non-empty span missing in probe: '{item['text']}'")
                elif item["status"] == "PROBE_MISSING" and not item["text"].strip():
                    gate_failures.append(f"{r['file']} p{p_idx}: Whitespace span missing in probe: '{item['text']}' (Base span count={s['base_span_count']} vs Probe={s['probe_span_count']})")
                elif item["status"] == "BASE_MISSING":
                    # 严格等价门禁：未聚合/多余的图元必须被拦截
                    gate_failures.append(f"{r['file']} p{p_idx}: Extra unmapped probe span/TextObject: '{item['text']}'")

            raw_bbox_delta = s.get("raw_max_bbox_delta", s["max_bbox_delta"])
            if raw_bbox_delta > args.bbox_tol:
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
