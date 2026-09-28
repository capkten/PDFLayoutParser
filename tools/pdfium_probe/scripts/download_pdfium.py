#!/usr/bin/env python3
"""
Downloads and verifies the official PDFium binary according to manifest.json.
Guarantees deterministic, checksummed dependency setup across platforms.
"""

import hashlib
import json
import os
import platform
import sys
import tarfile
import urllib.request

def detect_platform_key():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows" and machine in ["amd64", "x86_64"]:
        return "win-x64"
    elif system == "linux" and machine in ["x86_64", "amd64"]:
        return "linux-x64"
    elif system == "darwin":
        if "arm" in machine or machine == "aarch64":
            return "mac-arm64"
        else:
            return "mac-x64"
    else:
        raise RuntimeError(f"Unsupported system/arch: {system} {machine}")

def verify_sha256(file_path, expected_sha256):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    actual_sha256 = h.hexdigest().lower()
    if actual_sha256 != expected_sha256.lower():
        raise ValueError(
            f"SHA256 mismatch for {file_path}!\n"
            f"  Expected: {expected_sha256}\n"
            f"  Actual:   {actual_sha256}"
        )

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    manifest_path = os.path.join(root, "manifest.json")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    plat_key = detect_platform_key()
    plat_info = manifest["platforms"].get(plat_key)
    if not plat_info:
        print(f"Error: No configuration in manifest.json for platform '{plat_key}'", file=sys.stderr)
        sys.exit(1)

    lib_relpath = plat_info["library_relpath"]
    lib_path = os.path.join(root, lib_relpath)

    # 检查是否已存在且哈希有效
    if os.path.exists(lib_path) and plat_info.get("library_sha256"):
        try:
            verify_sha256(lib_path, plat_info["library_sha256"])
            print(f"[download_pdfium] Verified existing {lib_relpath} (SHA-256 matches).")
            return
        except ValueError:
            print(f"[download_pdfium] Existing {lib_relpath} failed hash check, re-downloading...")

    archive_name = plat_info["archive_name"]
    archive_url = plat_info["archive_url"]
    expected_archive_sha256 = plat_info["archive_sha256"]

    download_dir = os.path.join(root, "native", "downloads")
    os.makedirs(download_dir, exist_ok=True)
    archive_path = os.path.join(download_dir, archive_name)

    print(f"[download_pdfium] Downloading {archive_url} -> {archive_path}")
    req = urllib.request.Request(archive_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(archive_path, "wb") as out_f:
        while chunk := resp.read(65536):
            out_f.write(chunk)

    print(f"[download_pdfium] Verifying archive SHA-256...")
    verify_sha256(archive_path, expected_archive_sha256)
    print(f"[download_pdfium] Archive SHA-256 verified successfully!")

    print(f"[download_pdfium] Extracting library to {os.path.dirname(lib_path)}...")
    os.makedirs(os.path.dirname(lib_path), exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        lib_filename = os.path.basename(lib_relpath)
        extracted = False
        for member in tar.getmembers():
            if os.path.basename(member.name) == lib_filename:
                member_f = tar.extractfile(member)
                with open(lib_path, "wb") as out_f:
                    out_f.write(member_f.read())
                extracted = True
                break
        if not extracted:
            raise FileNotFoundError(f"Could not find {lib_filename} inside {archive_name}")

    if plat_info.get("library_sha256"):
        verify_sha256(lib_path, plat_info["library_sha256"])
        print(f"[download_pdfium] Library binary SHA-256 verified successfully!")
    else:
        # 首次解压计算哈希
        h = hashlib.sha256()
        with open(lib_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        print(f"[download_pdfium] Computed library SHA-256: {h.hexdigest()}")

    print(f"[download_pdfium] Setup complete for {plat_key}: {lib_path}")

if __name__ == "__main__":
    main()
