import os
import sys
import json
import hashlib
import subprocess
import glob

def compute_file_sha256(path):
    if not os.path.exists(path):
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

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    synthetic_pdf_dir = os.path.join(root, "test_data", "synthetic")
    synthetic_base_dir = os.path.join(root, "test_data", "baseline")
    probe_output_dir = os.path.join(root, "test_data", "pdfium_output")
    real_base_dir = os.path.join(root, "test_data", "real_baseline")
    real_output_dir = os.path.join(root, "test_data", "real_pdfium_output")

    print("[verify_deterministic_hashes] Starting 3-run deterministic stability verification...")

    probe_bin = os.path.join(root, "target", "debug", "pdfium_probe.exe")
    if not os.path.exists(probe_bin):
        # 先编译二进制
        print("[verify_deterministic_hashes] Compiling probe binary...")
        subprocess.run(["cargo", "build"], cwd=root, check=True)

    # 收集 3 次运行的规范化哈希
    run_hashes = {1: {}, 2: {}, 3: {}}

    for run_idx in [1, 2, 3]:
        print(f"[verify_deterministic_hashes] Executing Probe Extraction Run #{run_idx}...")
        res = subprocess.run([probe_bin], cwd=root, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error running probe in run #{run_idx}:\n{res.stderr}")
            sys.exit(1)

        # 记录所有合成输出的规范化哈希
        for pf in glob.glob(os.path.join(probe_output_dir, "*_pdfium.json")):
            name = os.path.basename(pf).replace("_pdfium.json", "")
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            run_hashes[run_idx][f"synthetic:{name}"] = normalize_json_sha256(data)

        # 记录所有真实输出的规范化哈希
        for pf in glob.glob(os.path.join(real_output_dir, "*_pdfium.json")):
            name = os.path.basename(pf).replace("_pdfium.json", "")
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            run_hashes[run_idx][f"real:{name}"] = normalize_json_sha256(data)

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
            base_json_path = os.path.join(synthetic_base_dir, f"{name}_pymupdf.json")
            probe_json_path = os.path.join(probe_output_dir, f"{name}_pdfium.json")
        else:
            pdf_path = None # 真实样本来源可能是全局 test.pdf 等
            base_json_path = os.path.join(real_base_dir, f"{name}_pymupdf.json")
            probe_json_path = os.path.join(real_output_dir, f"{name}_pdfium.json")

        with open(base_json_path, "r", encoding="utf-8") as f:
            base_data = json.load(f)

        item = {
            "category": prefix,
            "sample_name": name,
            "input_pdf": pdf_path,
            "input_pdf_sha256": compute_file_sha256(pdf_path) if pdf_path else "external_source",
            "baseline_json": base_json_path,
            "baseline_normalized_sha256": normalize_json_sha256(base_data),
            "probe_json": probe_json_path,
            "probe_run1_normalized_sha256": h1,
            "probe_run2_normalized_sha256": h2,
            "probe_run3_normalized_sha256": h3,
            "deterministic_stable": is_stable,
        }
        ledger.append(item)

    ledger_path = os.path.join(root, "DETERMINISTIC_HASH_LEDGER.json")
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump({
            "audit_title": "Sprint 1 Deterministic Triple-Run Hash Ledger",
            "pdfium_version": "chromium/8066 (v156.0.8066.0)",
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
        print(f"  [{entry['category']}] {entry['sample_name']}: {status_str}")
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
