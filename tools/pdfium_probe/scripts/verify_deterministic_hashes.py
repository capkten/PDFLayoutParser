import os
import sys
import json
import hashlib
import subprocess
import glob

def compute_file_sha256(path):
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def normalize_json_sha256(data):
    """
    规范化 JSON 计算 SHA-256：
    1. 递归按字典键排序
    2. 使用统一的 separators=(',', ':') 紧凑序列化
    3. 排除易变的系统时间戳等（如果有）
    """
    normalized_str = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(normalized_str.encode('utf-8')).hexdigest()

def clean_stale_outputs(output_dirs):
    """清理历史输出目录中的 stale JSON，避免污染哈希台账"""
    for d in output_dirs:
        if os.path.exists(d):
            for f in glob.glob(os.path.join(d, "*_pdfium.json")):
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"[verify_deterministic_hashes] Warning: Failed to remove stale file {f}: {e}")

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    synthetic_pdf_dir = os.path.join(root, "test_data", "synthetic")
    synthetic_base_dir = os.path.join(root, "test_data", "baseline")
    probe_output_dir = os.path.join(root, "test_data", "pdfium_output")
    real_base_dir = os.path.join(root, "test_data", "real_baseline")
    real_output_dir = os.path.join(root, "test_data", "real_pdfium_output")
    native_lib_path = os.path.join(root, "native", "win-x64", "pdfium.dll")

    # 预期样本集合白名单
    expected_synthetic = [
        "synth_crop_offset",
        "synth_invisible_text",
        "synth_mixed_fonts",
        "synth_rotations",
        "synth_segmented_lines",
    ]
    real_sample_meta = {
        "test_p0_cover": {"pdf": "d:/codes/PDFLayoutParser/test.pdf", "page": 0},
        "test_p1_toc": {"pdf": "d:/codes/PDFLayoutParser/test.pdf", "page": 1},
        "test_p27_table": {"pdf": "d:/codes/PDFLayoutParser/test.pdf", "page": 27},
        "credit_p0_header": {"pdf": "d:/codes/PDFLayoutParser/征信解析样例.pdf", "page": 0},
        "credit_p1_detail": {"pdf": "d:/codes/PDFLayoutParser/征信解析样例.pdf", "page": 1},
    }

    print("[verify_deterministic_hashes] Starting 3-run deterministic stability verification...")

    # 清理旧输出，防止 stale JSON 残留
    clean_stale_outputs([probe_output_dir, real_output_dir])

    probe_bin = os.path.join(root, "target", "debug", "pdfium_probe.exe")
    # 强制重新编译保证二进制与代码一致
    print("[verify_deterministic_hashes] Compiling probe binary...")
    subprocess.run(["cargo", "build"], cwd=root, check=True)

    # 收集 3 次运行的规范化哈希
    run_hashes = {1: {}, 2: {}, 3: {}}

    for run_idx in [1, 2, 3]:
        print(f"[verify_deterministic_hashes] Executing Probe Extraction Run #{run_idx}...")
        # 每次运行前清空输出目录
        clean_stale_outputs([probe_output_dir, real_output_dir])
        res = subprocess.run([probe_bin], cwd=root, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error running probe in run #{run_idx}:\n{res.stderr}")
            sys.exit(1)

        # 记录所有合成输出的规范化哈希
        found_synth = []
        for pf in glob.glob(os.path.join(probe_output_dir, "*_pdfium.json")):
            name = os.path.basename(pf).replace("_pdfium.json", "")
            found_synth.append(name)
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            run_hashes[run_idx][f"synthetic:{name}"] = normalize_json_sha256(data)

        # 记录所有真实输出的规范化哈希
        found_real = []
        for pf in glob.glob(os.path.join(real_output_dir, "*_pdfium.json")):
            name = os.path.basename(pf).replace("_pdfium.json", "")
            found_real.append(name)
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            run_hashes[run_idx][f"real:{name}"] = normalize_json_sha256(data)

        # 双向严格白名单核验：既不允许缺失，也不允许意外多余文件
        missing_synth = set(expected_synthetic) - set(found_synth)
        unexpected_synth = set(found_synth) - set(expected_synthetic)
        if missing_synth:
            print(f"Error: Missing expected synthetic samples in run #{run_idx}: {missing_synth}")
            sys.exit(1)
        if unexpected_synth:
            print(f"Error: Unexpected synthetic sample files found in run #{run_idx}: {unexpected_synth}")
            sys.exit(1)

        missing_real = set(real_sample_meta.keys()) - set(found_real)
        unexpected_real = set(found_real) - set(real_sample_meta.keys())
        if missing_real:
            print(f"Error: Missing expected real samples in run #{run_idx}: {missing_real}")
            sys.exit(1)
        if unexpected_real:
            print(f"Error: Unexpected real sample files found in run #{run_idx}: {unexpected_real}")
            sys.exit(1)

    # 构建完整的 Hash Ledger
    ledger = []
    stability_failures = []

    all_keys = sorted(run_hashes[1].keys())
    for k in all_keys:
        prefix, name = k.split(":", 1)
        h1 = run_hashes[1][k]
        h2 = run_hashes[2][k]
        h3 = run_hashes[3][k]

        is_stable = (h1 == h2 == h3)
        if not is_stable:
            stability_failures.append(f"{k}: Hashes differ across runs! Run1={h1}, Run2={h2}, Run3={h3}")

        if prefix == "synthetic":
            pdf_path = os.path.join(synthetic_pdf_dir, f"{name}.pdf")
            page_index = 0
            base_json_path = os.path.join(synthetic_base_dir, f"{name}_pymupdf.json")
            probe_json_path = os.path.join(probe_output_dir, f"{name}_pdfium.json")
        else:
            meta = real_sample_meta[name]
            pdf_path = meta["pdf"]
            page_index = meta["page"]
            base_json_path = os.path.join(real_base_dir, f"{name}_pymupdf.json")
            probe_json_path = os.path.join(real_output_dir, f"{name}_pdfium.json")

        with open(base_json_path, "r", encoding="utf-8") as f:
            base_data = json.load(f)

        input_pdf_sha = compute_file_sha256(pdf_path)

        item = {
            "category": prefix,
            "sample_name": name,
            "page_index": page_index,
            "input_pdf": pdf_path,
            "input_pdf_sha256": input_pdf_sha,
            "baseline_json": base_json_path,
            "baseline_normalized_sha256": normalize_json_sha256(base_data),
            "probe_json": probe_json_path,
            "probe_run1_normalized_sha256": h1,
            "probe_run2_normalized_sha256": h2,
            "probe_run3_normalized_sha256": h3,
            "deterministic_stable": is_stable,
        }
        ledger.append(item)

    native_lib_sha = compute_file_sha256(native_lib_path)

    ledger_path = os.path.join(root, "DETERMINISTIC_HASH_LEDGER.json")
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump({
            "audit_title": "Sprint 1 Deterministic Triple-Run Hash Ledger",
            "schema_version": "pdfium_raw_snapshot_v1.0",
            "environment_provenance": {
                "target_os": "windows-x64",
                "windows_x64_verified": True,
                "native_library_path": os.path.relpath(native_lib_path, root).replace("\\", "/"),
                "native_library_sha256": native_lib_sha,
                "pdfium_release_tag": "chromium/8066",
                "linux_macos_status": "metadata_only_unverified (pending validation on native machines)",
            },
            "entries_count": len(ledger),
            "all_runs_deterministic": len(stability_failures) == 0,
            "entries": ledger,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[verify_deterministic_hashes] Successfully generated Ledger at: {ledger_path}")
    print("\n" + "="*80)
    print("           Sprint 1 Deterministic Triple-Run Hash Verification Summary")
    print("="*80)
    for entry in ledger:
        status_str = "PASS (100% Identical)" if entry["deterministic_stable"] else "FAIL (Drift detected)"
        print(f"  [{entry['category']}] {entry['sample_name']} (p{entry['page_index']}): {status_str}")
        print(f"      PDF SHA256     : {entry['input_pdf_sha256']}")
        print(f"      Baseline SHA256: {entry['baseline_normalized_sha256']}")
        print(f"      Probe SHA256   : {entry['probe_run1_normalized_sha256']}")

    if stability_failures:
        print("\nSTATUS: FAILED (Deterministic stability violated)")
        for fail in stability_failures:
            print(f"  - {fail}")
        sys.exit(1)
    else:
        print(f"\nSTATUS: PASSED (All {len(ledger)} sample outputs exhibit 100% identical SHA-256 hashes across 3 runs)")
        sys.exit(0)

if __name__ == "__main__":
    main()
