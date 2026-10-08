#!/usr/bin/env python3
"""Stage the verified PDFium binary into the Python package tree."""

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


def detect_platform_key():
    system = platform.system().lower()
    machine = platform.machine().lower()
    if not machine and system == "windows" and platform.architecture()[0] == "64bit":
        machine = "amd64"
    if system == "windows" and machine in ("amd64", "x86_64"):
        return "win-x64"
    if system == "linux" and machine in ("x86_64", "amd64"):
        return "linux-x64"
    if system == "darwin":
        if machine in ("x86_64", "amd64"):
            return "mac-x64"
        if machine in ("arm64", "aarch64"):
            return "mac-arm64"
    raise RuntimeError("Unsupported system/arch: {} {}".format(system, machine))


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_pdfium(source_root, destination_root, platform_key, manifest=None):
    source_root = Path(source_root)
    destination_root = Path(destination_root)
    if manifest is None:
        manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["platforms"][platform_key]
    relative_path = Path(entry["library_relpath"])
    source = source_root / relative_path
    if not source.is_file():
        raise FileNotFoundError("PDFium library not found: {}".format(source))
    expected = entry.get("library_sha256")
    if expected and _sha256(source).lower() != expected.lower():
        raise ValueError("SHA256 mismatch for {}".format(source))
    destination = destination_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    if expected and _sha256(destination).lower() != expected.lower():
        raise ValueError("SHA256 mismatch after copying {}".format(destination))
    return destination


def main():
    script_dir = Path(__file__).resolve().parent
    probe_root = script_dir.parent
    package_root = probe_root.parents[1] / "src" / "hexai_pdf_parser"
    platform_key = detect_platform_key()
    manifest = json.loads((probe_root / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["platforms"][platform_key]
    source = probe_root / entry["library_relpath"]
    expected = entry.get("library_sha256")
    source_is_verified = source.is_file() and expected and _sha256(source).lower() == expected.lower()
    if not source_is_verified:
        subprocess.run([sys.executable, str(script_dir / "download_pdfium.py")], check=True)
    destination = stage_pdfium(probe_root, package_root, platform_key, manifest)
    print("[stage_pdfium_package] Staged {}".format(destination))


if __name__ == "__main__":
    main()
