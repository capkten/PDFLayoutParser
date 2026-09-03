from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import fitz


DEFAULT_INPUT_PDF = Path("fix/zh_all_table_pages.pdf")
DEFAULT_OUTPUT_ROOT = Path("output/fix_zh_all_table_pages_rerun_20260903")
DEFAULT_TESTSET_ROOT = DEFAULT_OUTPUT_ROOT / "testset_markdown"
DEFAULT_DIFF_ROOT = DEFAULT_TESTSET_ROOT / "diffs"
DEFAULT_EXCLUDED_VISUAL_STEMS = {"part_004_pages_0458_0486_page_024"}
DEFAULT_EXCLUDED_PAGE_BY_STEM = {"part_004_pages_0458_0486_page_024": 482}
DEFAULT_FAILED_PAGE_INDEXES = {408, 410}


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    image_line = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
    lines: list[str] = []
    previous_blank = True
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if image_line.fullmatch(line):
            continue
        if line == "":
            if previous_blank:
                continue
            previous_blank = True
            lines.append("")
            continue
        previous_blank = False
        lines.append(line)

    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def scan_page_outputs(output_root: Path) -> dict[int, dict]:
    output_root = Path(output_root)
    results: dict[int, dict] = {}
    flat_visual_index = _build_flat_visual_index(output_root)

    for json_path in sorted(output_root.rglob("*.json")):
        if json_path.parent.name != "pages":
            continue

        local_page_index = _local_page_index_from_name(json_path)
        page_index = source_page_index(json_path, local_page_index)
        page_data = json.loads(json_path.read_text(encoding="utf-8"))
        if page_data.get("index") != local_page_index:
            raise ValueError(f"{json_path}: JSON index does not match filename index")
        page_type = page_data.get("page_type")
        if not page_type:
            raise ValueError(f"{json_path}: missing page_type")

        markdown_path = json_path.with_suffix(".md")
        if not markdown_path.exists():
            if page_type == "scanned":
                markdown_path = None
            else:
                raise ValueError(f"{json_path}: missing Markdown companion {markdown_path}")
        elif page_type == "scanned":
            markdown_path = markdown_path

        visual_path = json_path.parent.parent / "tables" / f"{json_path.stem}.png"
        if not visual_path.exists():
            raise ValueError(f"{json_path}: missing table visualization {visual_path}")

        visualized_image_path = _find_visualized_image(output_root, visual_path, flat_visual_index)

        if page_type == "vector" and markdown_path is None:
            raise ValueError(f"{json_path}: missing Markdown companion {markdown_path}")

        if page_index in results:
            existing = results[page_index]
            raise ValueError(
                f"conflicting outputs for page {page_index}: {existing['json_path']} vs {json_path}"
            )

        results[page_index] = {
            "page_index": page_index,
            "page_type": page_type,
            "json_index": page_data.get("index"),
            "local_page_index": local_page_index,
            "source_page_index": page_index,
            "json_path": json_path,
            "markdown_path": markdown_path,
            "visual_path": visual_path,
            "visualized_image_path": visualized_image_path,
            "visualized_image_name": visualized_image_path.name if visualized_image_path else None,
            "relative_path": json_path.relative_to(output_root).as_posix(),
        }

    return results


def build_testset(
    input_pdf: Path,
    output_root: Path,
    testset_root: Path,
    excluded_visual_stems: set[str] | None = None,
    failed_page_indexes: set[int] | None = None,
) -> dict:
    input_pdf = Path(input_pdf).resolve()
    output_root = Path(output_root).resolve()
    testset_root = Path(testset_root).resolve()
    excluded_visual_stems = set(DEFAULT_EXCLUDED_VISUAL_STEMS if excluded_visual_stems is None else excluded_visual_stems)
    failed_page_indexes = set(DEFAULT_FAILED_PAGE_INDEXES if failed_page_indexes is None else failed_page_indexes)
    confirmed_flat_visual_page_indexes = {589}

    if not input_pdf.exists():
        raise ValueError(f"input PDF does not exist: {input_pdf}")
    if not output_root.exists():
        raise ValueError(f"output root does not exist: {output_root}")

    page_outputs = scan_page_outputs(output_root)
    excluded_matches: dict[str, list[int]] = {stem: [] for stem in excluded_visual_stems}

    with fitz.open(input_pdf) as doc:
        page_count = doc.page_count

    scanned_indexes = set(page_outputs)
    out_of_range = sorted(index for index in scanned_indexes if index < 0 or index >= page_count)
    if out_of_range:
        raise ValueError(f"page indexes out of range for {input_pdf}: {out_of_range}")

    missing_indexes = set(range(page_count)) - scanned_indexes
    if missing_indexes != failed_page_indexes:
        raise ValueError(
            f"missing page indexes {sorted(missing_indexes)} do not match expected failed pages {sorted(failed_page_indexes)}"
        )

    pages: list[dict] = []
    excluded_visuals: list[dict] = []
    failed_pages: list[dict] = []
    labels_to_write: list[tuple[Path, str]] = []
    label_count = 0
    absent_expected_count = 0
    excluded_count = 0

    for page_index in sorted(page_outputs):
        page_output = page_outputs[page_index]
        visual_name = page_output["visualized_image_name"]
        visual_stem = page_output["visual_path"].stem
        is_excluded = visual_stem in excluded_visual_stems
        if is_excluded:
            excluded_matches[visual_stem].append(page_index)
        page_record = _page_record(output_root, testset_root, page_output)

        if is_excluded and visual_name is None:
            raise ValueError(
                f"missing flat visualized image for excluded page {page_index}: {page_output['visual_path'].name}"
            )
        if page_index in confirmed_flat_visual_page_indexes and visual_name is None:
            raise ValueError(
                f"missing flat visualized image for confirmed page {page_index}: {page_output['visual_path'].name}"
            )

        if is_excluded:
            page_record["markdown_status"] = "excluded"
            page_record["label_path"] = None
            excluded_count += 1
            excluded_visuals.append(
                {
                    "page_index": page_index,
                    "visual_stem": visual_stem,
                    "visual_name": visual_name,
                    "visual_path": _stringify_path(page_output["visualized_image_path"]),
                }
            )
        elif page_output["page_type"] == "scanned":
            page_record["markdown_status"] = "absent_expected"
            page_record["label_path"] = None
            absent_expected_count += 1
        else:
            label_rel_path = Path("labels") / f"page-{page_index:03d}.md"
            page_record["markdown_status"] = "markdown"
            page_record["label_path"] = label_rel_path.as_posix()
            labels_to_write.append(
                (testset_root / label_rel_path, normalize_markdown(page_output["markdown_path"].read_text(encoding="utf-8")))
            )
            label_count += 1

        pages.append(page_record)

    for page_index in sorted(failed_page_indexes):
        failed_pages.append(
            {
                "page_index": page_index,
                "markdown_status": "failed_no_output",
                "expected_original_png": _stringify_path(output_root / "error_pages" / f"page_{page_index:04d}_original.png"),
            }
        )

    for excluded_stem, matched_pages in sorted(excluded_matches.items()):
        if len(matched_pages) != 1:
            raise ValueError(f"excluded visual stem {excluded_stem} matched {len(matched_pages)} pages: {matched_pages}")
        expected_page_index = DEFAULT_EXCLUDED_PAGE_BY_STEM.get(excluded_stem)
        if expected_page_index is not None and matched_pages != [expected_page_index]:
            raise ValueError(
                f"default excluded visual stem {excluded_stem} expected page {expected_page_index}, got {matched_pages}"
            )

    labels_dir = testset_root / "labels"
    if labels_dir.exists():
        shutil.rmtree(labels_dir)
    labels_dir.mkdir(parents=True, exist_ok=True)

    for label_path, content in labels_to_write:
        label_path.write_text(content, encoding="utf-8")

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest = {
        "schema_version": 1,
        "input_pdf": str(input_pdf),
        "input_pdf_posix": input_pdf.as_posix(),
        "page_count": page_count,
        "generated_at": generated_at,
        "excluded_visuals": excluded_visuals,
        "failed_pages": failed_pages,
        "pages": pages,
    }
    testset_root.mkdir(parents=True, exist_ok=True)
    (testset_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (testset_root / "README.md").write_text(
        _build_readme(
            input_pdf=input_pdf,
            output_root=output_root,
            testset_root=testset_root,
            generated_at=generated_at,
            label_count=label_count,
            absent_expected_count=absent_expected_count,
            excluded_visuals=excluded_visuals,
            failed_pages=failed_pages,
            pages=pages,
        ),
        encoding="utf-8",
    )

    return {
        "page_count": page_count,
        "label_count": label_count,
        "absent_expected_count": absent_expected_count,
        "excluded_count": excluded_count,
        "failed_count": len(failed_pages),
        "manifest_path": testset_root / "manifest.json",
        "readme_path": testset_root / "README.md",
        "testset_root": testset_root,
    }


def compare_testset(testset_root: Path, actual_root: Path, diff_root: Path) -> int:
    testset_root = Path(testset_root).resolve()
    actual_root = Path(actual_root).resolve()
    diff_root = Path(diff_root).resolve()

    _reset_directory(diff_root)

    try:
        manifest = _load_manifest(testset_root)
    except Exception as exc:
        _write_status_diff(diff_root / "manifest.diff.md", f"manifest validation failed: {exc}")
        print(f"manifest validation failed: {exc}")
        return 1

    try:
        actual_pages = scan_page_outputs(actual_root)
    except Exception as exc:
        _write_status_diff(diff_root / "scan_error.diff.md", f"actual output scan failed: {exc}")
        print(f"actual output scan failed: {exc}")
        return 1

    manifest_pages = {page["page_index"]: page for page in manifest["pages"]}
    failed_page_indexes = {page["page_index"] for page in manifest["failed_pages"]}
    recorded_indexes = set(manifest_pages) | failed_page_indexes

    passed_pages = 0
    failed_pages = 0
    missing_pages = 0
    extra_pages = 0

    for page_index in sorted(actual_pages):
        if page_index not in recorded_indexes:
            extra_pages += 1
            failed_pages += 1
            _write_status_diff(
                diff_root / f"page-{page_index:03d}.diff.md",
                f"extra actual page {page_index} is not recorded in manifest",
            )

    for page_index in sorted(manifest_pages):
        page_record = manifest_pages[page_index]
        status = page_record["markdown_status"]
        actual_page = actual_pages.get(page_index)

        if status == "markdown":
            if actual_page is None:
                missing_pages += 1
                failed_pages += 1
                _write_status_diff(diff_root / f"page-{page_index:03d}.diff.md", f"missing actual output for page {page_index}")
                continue
            if actual_page["markdown_path"] is None:
                failed_pages += 1
                _write_status_diff(
                    diff_root / f"page-{page_index:03d}.diff.md",
                    f"expected Markdown for page {page_index}, but actual output has no Markdown",
                )
                continue

            label_path = testset_root / page_record["label_path"]
            expected = normalize_markdown(label_path.read_text(encoding="utf-8"))
            actual_text = actual_page["markdown_path"].read_text(encoding="utf-8")
            actual = normalize_markdown(actual_text)
            if expected != actual:
                failed_pages += 1
                write_diff(expected, actual, diff_root / f"page-{page_index:03d}.diff.md")
                (diff_root / f"page-{page_index:03d}.actual.md").write_text(actual_text, encoding="utf-8")
                continue
            passed_pages += 1
            continue

        if status == "absent_expected":
            if actual_page is None:
                missing_pages += 1
                failed_pages += 1
                _write_status_diff(diff_root / f"page-{page_index:03d}.diff.md", f"missing actual output for page {page_index}")
                continue
            if actual_page["markdown_path"] is not None:
                failed_pages += 1
                _write_status_diff(
                    diff_root / f"page-{page_index:03d}.diff.md",
                    f"expected absent Markdown for page {page_index}, but actual Markdown exists",
                )
                continue
            passed_pages += 1
            continue

        if status == "excluded":
            passed_pages += 1
            continue

        failed_pages += 1
        _write_status_diff(diff_root / f"page-{page_index:03d}.diff.md", f"unknown markdown_status for page {page_index}: {status}")

    print(
        f"compare summary: passed={passed_pages} failed={failed_pages} missing={missing_pages} extra={extra_pages} diff_root={diff_root}"
    )
    return 0 if failed_pages == 0 and missing_pages == 0 and extra_pages == 0 else 1


def source_page_index(path: Path, local_page_index: int) -> int:
    path = Path(path)
    local_page_index = int(local_page_index)
    json_index = _local_page_index_from_name(path)
    if json_index != local_page_index:
        raise ValueError(f"{path}: local page index {local_page_index} does not match filename index {json_index}")

    pages_dir = None
    for ancestor in path.parents:
        if ancestor.name == "pages":
            pages_dir = ancestor
            break
    if pages_dir is None:
        raise ValueError(f"cannot resolve page index from {path}")

    for container in pages_dir.parents:
        index_info = _page_container_index(container.name)
        if index_info is None:
            continue
        start, end = index_info
        page_count = end - start + 1
        if not 0 <= local_page_index < page_count:
            raise ValueError(f"{path}: local page index {local_page_index} out of range for {container.name}")
        return start + local_page_index

    raise ValueError(f"cannot resolve page index from {path}")


def write_diff(expected: str, actual: str, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile="expected",
        tofile="actual",
        lineterm="",
    )
    path.write_text("\n".join(diff) + "\n", encoding="utf-8")


def _local_page_index_from_name(path: Path) -> int:
    match = re.search(r"(?:^|[_-])page[_-](\d+)$", path.stem)
    if match is None:
        raise ValueError(f"cannot parse local page index from {path}")
    return int(match.group(1))


def _page_container_index(name: str) -> tuple[int, int] | None:
    direct = re.fullmatch(r"page[_-](\d+)", name)
    if direct is not None:
        page = int(direct.group(1))
        return page, page

    ranged = re.fullmatch(r".*_pages_(\d+)_(\d+)", name)
    if ranged is not None:
        start = int(ranged.group(1))
        end = int(ranged.group(2))
        if end < start:
            raise ValueError(f"invalid page range directory {name}")
        return start, end

    return None


def _build_flat_visual_index(output_root: Path) -> dict[str, list[Path]]:
    visual_dir = output_root / "visualized_images"
    index: dict[str, list[Path]] = {}
    if not visual_dir.exists():
        return index

    for path in sorted(visual_dir.glob("*.png")):
        suffix = "__tables__"
        marker = path.name.rfind(suffix)
        if marker == -1:
            continue
        table_name = path.name[marker + len(suffix):]
        index.setdefault(table_name, []).append(path)
    return index


def _find_visualized_image(output_root: Path, visual_path: Path, flat_visual_index: dict[str, list[Path]]) -> Path | None:
    candidates = flat_visual_index.get(visual_path.name, [])
    if len(candidates) > 1:
        raise ValueError(f"multiple flat visualized images match {visual_path.name} under {output_root / 'visualized_images'}")
    if not candidates:
        return None
    return candidates[0]


def _page_record(output_root: Path, testset_root: Path, page_output: dict) -> dict:
    return {
        "page_index": page_output["page_index"],
        "page_type": page_output["page_type"],
        "markdown_status": None,
        "label_path": None,
        "source_json": _relative_or_absolute(output_root, page_output["json_path"]),
        "source_markdown": _relative_or_absolute(output_root, page_output["markdown_path"]),
        "source_table_png": _relative_or_absolute(output_root, page_output["visual_path"]),
        "source_visual_name": page_output["visualized_image_name"],
        "source_visual_path": _relative_or_absolute(output_root, page_output["visualized_image_path"]),
        "json_index": page_output["json_index"],
        "local_page_index": page_output["local_page_index"],
        "source_page_index": page_output["source_page_index"],
    }


def _relative_or_absolute(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _stringify_path(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _build_readme(
    input_pdf: Path,
    output_root: Path,
    testset_root: Path,
    generated_at: str,
    label_count: int,
    absent_expected_count: int,
    excluded_visuals: list[dict],
    failed_pages: list[dict],
    pages: list[dict],
) -> str:
    included_pages = [page["page_index"] for page in pages if page["markdown_status"] == "markdown"]
    absent_pages = [page["page_index"] for page in pages if page["markdown_status"] == "absent_expected"]
    excluded_pages = [item["page_index"] for item in excluded_visuals]
    confirmed_included = next(
        (page["source_visual_name"] for page in pages if page["page_index"] == 589),
        None,
    )
    lines = [
        "# Markdown 黄金测试集",
        "",
        f"- 生成时间：{generated_at}",
        f"- 输入 PDF：{input_pdf}",
        f"- 解析输出目录：{output_root}",
        f"- 测试集目录：{testset_root}",
        "",
        "## 生成命令",
        "",
        "```powershell",
        "conda run -n base python scripts/markdown_golden_testset.py build \\",
        f"  --pdf {input_pdf} \\",
        f"  --output-root {output_root} \\",
        f"  --testset-root {testset_root}",
        "```",
        "",
        "## 比较命令",
        "",
        "```powershell",
        "conda run -n base python scripts/markdown_golden_testset.py compare \\",
        f"  --testset-root {testset_root} \\",
        f"  --actual-root {output_root} \\",
        f"  --diff-root {testset_root / 'diffs'}",
        "```",
        "",
        "## 当前实际数量",
        "",
        f"- Markdown 标签：{label_count}",
        f"- scanned 且预期无 Markdown：{absent_expected_count}",
        f"- 排除页：{len(excluded_visuals)}",
        f"- failed_no_output：{len(failed_pages)}",
        "",
        "## 说明",
        "",
        "- scanned 页面当前由 MarkdownWriter 预期不生成 Markdown，因此只记录为 `absent_expected`。",
        "- `pages/` 目录之外的分片级 Markdown 汇总文件不参与标签复制。",
        f"- 排除页页码：{excluded_pages or '无'}",
        f"- 排除来源：{', '.join(item['visual_name'] or item['visual_stem'] for item in excluded_visuals) if excluded_visuals else '无'}",
        f"- 确认纳入页 589 对应来源：{confirmed_included or '未找到 visualized_images 记录'}",
        f"- failed 页页码：{[item['page_index'] for item in failed_pages]}",
        "",
        "## 后续差异目录",
        "",
        "建议后续比较失败时把差异输出到 `testset_markdown/diffs/`。",
        "",
        "## 统计提示",
        "",
        f"- 当前纳入页总数：{len(included_pages) + len(absent_pages)}",
        f"- 有标签页索引示例：{included_pages[:5]}{' ...' if len(included_pages) > 5 else ''}",
        f"- 无标签 scanned 页索引示例：{absent_pages[:5]}{' ...' if len(absent_pages) > 5 else ''}",
        "",
    ]
    return "\n".join(lines)


def _reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _load_manifest(testset_root: Path) -> dict:
    manifest_path = testset_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"{manifest_path}: schema_version must be 1")

    pages = manifest.get("pages")
    failed_pages = manifest.get("failed_pages")
    if not isinstance(pages, list) or not isinstance(failed_pages, list):
        raise ValueError(f"{manifest_path}: pages and failed_pages must be lists")

    seen_indexes: set[int] = set()
    for page in pages:
        page_index = page.get("page_index")
        if page_index in seen_indexes:
            raise ValueError(f"{manifest_path}: duplicate page_index {page_index} in pages")
        seen_indexes.add(page_index)
        label_path = page.get("label_path")
        if page.get("markdown_status") == "markdown":
            if not label_path:
                raise ValueError(f"{manifest_path}: page {page_index} missing label_path")
            resolved = (testset_root / label_path).resolve()
            if testset_root not in resolved.parents:
                raise ValueError(f"{manifest_path}: page {page_index} label_path escapes testset_root")
            if not resolved.exists():
                raise ValueError(f"{manifest_path}: page {page_index} label_path does not exist: {resolved}")

    failed_seen: set[int] = set()
    for page in failed_pages:
        page_index = page.get("page_index")
        if page_index in failed_seen or page_index in seen_indexes:
            raise ValueError(f"{manifest_path}: duplicate page_index {page_index} across manifest records")
        failed_seen.add(page_index)

    return manifest


def _write_status_diff(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Compare Failure\n\n{message}\n", encoding="utf-8")


def _write_test_page(
    output_root: Path,
    container_name: str,
    local_page_index: int,
    page_type: str,
    markdown_text: str | None,
    extra_json: dict | None = None,
) -> Path:
    container_dir = output_root / container_name
    pages_dir = container_dir / "pages"
    tables_dir = container_dir / "tables"
    visualized_dir = output_root / "visualized_images"
    pages_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    visualized_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{container_name}_page_{local_page_index:03d}"
    page_json = {"index": local_page_index, "page_type": page_type}
    if extra_json:
        page_json.update(extra_json)
    (pages_dir / f"{stem}.json").write_text(json.dumps(page_json), encoding="utf-8")
    if markdown_text is not None:
        (pages_dir / f"{stem}.md").write_text(markdown_text, encoding="utf-8")
    (tables_dir / f"{stem}.png").write_bytes(b"png")
    (visualized_dir / f"{container_name}__tables__{stem}.png").write_bytes(b"png")
    return container_dir


class MarkdownGoldenTestsetTests(unittest.TestCase):
    def test_source_page_index_from_part_range(self) -> None:
        self.assertEqual(
            source_page_index(
                Path("part_004_pages_0458_0486/pages/file_page_024.json"), 24
            ),
            482,
        )

    def test_source_page_index_from_page_directory(self) -> None:
        self.assertEqual(source_page_index(Path("page_0405/pages/file_page_000.json"), 0), 405)

    def test_source_page_index_rejects_local_index_out_of_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "out of range"):
            source_page_index(Path("page_0405/pages/file_page_001.json"), 1)

    def test_source_page_index_from_zero_based_range(self) -> None:
        self.assertEqual(
            source_page_index(Path("part_000_pages_0000_0170/pages/file_page_000.json"), 0),
            0,
        )

    def test_normalize_markdown_drops_images_and_normalizes_whitespace(self) -> None:
        self.assertEqual(
            normalize_markdown("A\r\n\r\n![image](C:/run/page.png)\r\n\r\n<table>\r\n</table>\r\n"),
            "A\n\n<table>\n</table>",
        )

    def test_scan_page_outputs_pairs_markdown_and_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages_dir = root / "part_004_pages_0458_0486" / "pages"
            tables_dir = root / "part_004_pages_0458_0486" / "tables"
            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)

            json_path = pages_dir / "file_page_024.json"
            json_path.write_text(json.dumps({"index": 24, "page_type": "vector"}), encoding="utf-8")
            (pages_dir / "file_page_024.md").write_text("hello", encoding="utf-8")
            (tables_dir / "file_page_024.png").write_bytes(b"png")

            result = scan_page_outputs(root)

            self.assertEqual(sorted(result), [482])
            self.assertEqual(result[482]["page_index"], 482)
            self.assertEqual(result[482]["page_type"], "vector")
            self.assertEqual(result[482]["relative_path"], "part_004_pages_0458_0486/pages/file_page_024.json")
            self.assertEqual(result[482]["json_path"], json_path)
            self.assertEqual(result[482]["markdown_path"], pages_dir / "file_page_024.md")
            self.assertEqual(result[482]["visual_path"], tables_dir / "file_page_024.png")

    def test_scan_page_outputs_rejects_conflicting_same_source_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_pages = root / "page_0405" / "pages"
            first_tables = root / "page_0405" / "tables"
            second_pages = root / "part_000_pages_0405_0405" / "pages"
            second_tables = root / "part_000_pages_0405_0405" / "tables"
            first_pages.mkdir(parents=True)
            first_tables.mkdir(parents=True)
            second_pages.mkdir(parents=True)
            second_tables.mkdir(parents=True)

            first_json = first_pages / "file_page_000.json"
            first_json.write_text(json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8")
            (first_pages / "file_page_000.md").write_text("first", encoding="utf-8")
            (first_tables / "file_page_000.png").write_bytes(b"png")

            second_json = second_pages / "file_page_000.json"
            second_json.write_text(json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8")
            (second_pages / "file_page_000.md").write_text("second", encoding="utf-8")
            (second_tables / "file_page_000.png").write_bytes(b"png")

            with self.assertRaisesRegex(ValueError, "conflicting outputs for page 405"):
                scan_page_outputs(root)

    def test_scan_page_outputs_rejects_missing_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages_dir = root / "part_000_pages_0000_0170" / "pages"
            tables_dir = root / "part_000_pages_0000_0170" / "tables"
            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)

            json_path = pages_dir / "file_page_000.json"
            json_path.write_text(json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8")
            (tables_dir / "file_page_000.png").write_bytes(b"png")

            with self.assertRaisesRegex(ValueError, "missing Markdown companion"):
                scan_page_outputs(root)

    def test_scan_page_outputs_allows_scanned_page_without_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages_dir = root / "part_000_pages_0000_0170" / "pages"
            tables_dir = root / "part_000_pages_0000_0170" / "tables"
            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)

            json_path = pages_dir / "file_page_001.json"
            json_path.write_text(json.dumps({"index": 1, "page_type": "scanned"}), encoding="utf-8")
            (tables_dir / "file_page_001.png").write_bytes(b"png")

            result = scan_page_outputs(root)

            self.assertEqual(sorted(result), [1])
            self.assertEqual(result[1]["page_type"], "scanned")
            self.assertIsNone(result[1]["markdown_path"])

    def test_scan_page_outputs_rejects_missing_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages_dir = root / "part_000_pages_0000_0170" / "pages"
            tables_dir = root / "part_000_pages_0000_0170" / "tables"
            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)

            json_path = pages_dir / "file_page_000.json"
            json_path.write_text(json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8")
            (pages_dir / "file_page_000.md").write_text("hello", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing table visualization"):
                scan_page_outputs(root)

    def test_write_diff_emits_unified_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "diff.txt"
            write_diff("a\n", "b\n", path)
            content = path.read_text(encoding="utf-8")

            self.assertIn("--- expected", content)
            self.assertIn("+++ actual", content)
            self.assertIn("@@", content)
            self.assertIn("-a", content)
            self.assertIn("+b", content)

    def test_build_testset_creates_manifest_and_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_pdf = root / "input.pdf"
            output_root = root / "output"
            testset_root = root / "testset_markdown"
            visualized_dir = output_root / "visualized_images"

            doc = fitz.open()
            for _ in range(5):
                doc.new_page()
            doc.save(input_pdf)
            doc.close()

            include_dir = output_root / "part_000_pages_0000_0002"
            exclude_dir = output_root / "part_001_pages_0003_0004"
            visualized_dir.mkdir(parents=True)
            for container in (include_dir, exclude_dir):
                (container / "pages").mkdir(parents=True)
                (container / "tables").mkdir(parents=True)

            (include_dir / "pages" / "part_000_pages_0000_0002_page_000.json").write_text(
                json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8"
            )
            (include_dir / "pages" / "part_000_pages_0000_0002_page_000.md").write_text("A\n\n![x](img)\n", encoding="utf-8")
            (include_dir / "tables" / "part_000_pages_0000_0002_page_000.png").write_bytes(b"png")
            (visualized_dir / "part_000_pages_0000_0002__tables__part_000_pages_0000_0002_page_000.png").write_bytes(b"png")

            (include_dir / "pages" / "part_000_pages_0000_0002_page_001.json").write_text(
                json.dumps({"index": 1, "page_type": "scanned"}), encoding="utf-8"
            )
            (include_dir / "tables" / "part_000_pages_0000_0002_page_001.png").write_bytes(b"png")
            (visualized_dir / "part_000_pages_0000_0002__tables__part_000_pages_0000_0002_page_001.png").write_bytes(b"png")

            (include_dir / "pages" / "part_000_pages_0000_0002_page_002.json").write_text(
                json.dumps({"index": 2, "page_type": "vector"}), encoding="utf-8"
            )
            (include_dir / "pages" / "part_000_pages_0000_0002_page_002.md").write_text("B", encoding="utf-8")
            (include_dir / "tables" / "part_000_pages_0000_0002_page_002.png").write_bytes(b"png")
            (visualized_dir / "part_000_pages_0000_0002__tables__part_000_pages_0000_0002_page_002.png").write_bytes(b"png")

            (exclude_dir / "pages" / "part_001_pages_0003_0004_page_000.json").write_text(
                json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8"
            )
            (exclude_dir / "pages" / "part_001_pages_0003_0004_page_000.md").write_text("excluded", encoding="utf-8")
            (exclude_dir / "tables" / "part_001_pages_0003_0004_page_000.png").write_bytes(b"png")
            (visualized_dir / "part_001_pages_0003_0004__tables__part_001_pages_0003_0004_page_000.png").write_bytes(b"png")

            result = build_testset(
                input_pdf=input_pdf,
                output_root=output_root,
                testset_root=testset_root,
                excluded_visual_stems={"part_001_pages_0003_0004_page_000"},
                failed_page_indexes={4},
            )

            self.assertEqual(result["page_count"], 5)
            self.assertEqual(result["label_count"], 2)
            self.assertEqual(result["absent_expected_count"], 1)
            self.assertEqual(result["excluded_count"], 1)
            self.assertEqual(result["failed_count"], 1)
            self.assertFalse((testset_root / "labels" / "page-001.md").exists())
            self.assertFalse((testset_root / "labels" / "page-003.md").exists())
            self.assertFalse((testset_root / "labels" / "page-004.md").exists())
            self.assertEqual((testset_root / "labels" / "page-000.md").read_text(encoding="utf-8"), "A")
            self.assertEqual((testset_root / "labels" / "page-002.md").read_text(encoding="utf-8"), "B")

            manifest = json.loads((testset_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["page_count"], 5)
            self.assertNotIn("testset_root", manifest)
            self.assertNotIn("output_root", manifest)
            self.assertEqual(manifest["excluded_visuals"][0]["page_index"], 3)
            self.assertEqual(manifest["failed_pages"][0]["page_index"], 4)
            self.assertEqual(manifest["pages"][1]["markdown_status"], "absent_expected")
            self.assertNotIn("testset_root", manifest["pages"][0])
            self.assertEqual(
                manifest["pages"][2]["source_visual_name"],
                "part_000_pages_0000_0002__tables__part_000_pages_0000_0002_page_002.png",
            )
            self.assertEqual(manifest["pages"][3]["markdown_status"], "excluded")
            self.assertIn("当前实际数量", (testset_root / "README.md").read_text(encoding="utf-8"))

    def test_scan_page_outputs_uses_root_visualized_image_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "visualized_images").mkdir(parents=True)
            pages_dir = root / "outer" / "part_004_pages_0458_0486" / "pages"
            tables_dir = root / "outer" / "part_004_pages_0458_0486" / "tables"
            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)

            json_path = pages_dir / "part_004_pages_0458_0486_page_024.json"
            json_path.write_text(json.dumps({"index": 24, "page_type": "vector"}), encoding="utf-8")
            (pages_dir / "part_004_pages_0458_0486_page_024.md").write_text("excluded", encoding="utf-8")
            (tables_dir / "part_004_pages_0458_0486_page_024.png").write_bytes(b"png")
            (root / "visualized_images" / "outer__part_004_pages_0458_0486__tables__part_004_pages_0458_0486_page_024.png").write_bytes(b"png")

            result = scan_page_outputs(root)

            self.assertEqual(
                result[482]["visualized_image_name"],
                "outer__part_004_pages_0458_0486__tables__part_004_pages_0458_0486_page_024.png",
            )

    def test_build_testset_rejects_missing_flat_visual_for_excluded_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_pdf = root / "input.pdf"
            output_root = root / "output"
            testset_root = root / "testset_markdown"
            pages_dir = output_root / "part_004_pages_0458_0486" / "pages"
            tables_dir = output_root / "part_004_pages_0458_0486" / "tables"

            doc = fitz.open()
            for _ in range(483):
                doc.new_page()
            doc.save(input_pdf)
            doc.close()

            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)
            (output_root / "visualized_images").mkdir(parents=True)

            json_path = pages_dir / "part_004_pages_0458_0486_page_024.json"
            json_path.write_text(json.dumps({"index": 24, "page_type": "vector"}), encoding="utf-8")
            (pages_dir / "part_004_pages_0458_0486_page_024.md").write_text("excluded", encoding="utf-8")
            (tables_dir / "part_004_pages_0458_0486_page_024.png").write_bytes(b"png")

            with self.assertRaisesRegex(ValueError, "missing flat visualized image"):
                build_testset(
                    input_pdf=input_pdf,
                    output_root=output_root,
                    testset_root=testset_root,
                    excluded_visual_stems={"part_004_pages_0458_0486_page_024"},
                    failed_page_indexes=set(range(483)) - {482},
                )

    def test_build_testset_rejects_missing_excluded_stem_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_pdf = root / "input.pdf"
            output_root = root / "output"
            testset_root = root / "testset_markdown"
            pages_dir = output_root / "part_000_pages_0000_0000" / "pages"
            tables_dir = output_root / "part_000_pages_0000_0000" / "tables"

            doc = fitz.open()
            doc.new_page()
            doc.save(input_pdf)
            doc.close()

            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)
            (output_root / "visualized_images").mkdir(parents=True)

            (pages_dir / "part_000_pages_0000_0000_page_000.json").write_text(
                json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8"
            )
            (pages_dir / "part_000_pages_0000_0000_page_000.md").write_text("ok", encoding="utf-8")
            (tables_dir / "part_000_pages_0000_0000_page_000.png").write_bytes(b"png")
            (output_root / "visualized_images" / "part_000_pages_0000_0000__tables__part_000_pages_0000_0000_page_000.png").write_bytes(b"png")

            with self.assertRaisesRegex(ValueError, "excluded visual stem .* matched 0 pages"):
                build_testset(
                    input_pdf=input_pdf,
                    output_root=output_root,
                    testset_root=testset_root,
                    excluded_visual_stems={"part_004_pages_0458_0486_page_024"},
                    failed_page_indexes=set(),
                )

    def test_build_testset_rejects_default_excluded_stem_on_wrong_page_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_pdf = root / "input.pdf"
            output_root = root / "output"
            testset_root = root / "testset_markdown"
            pages_dir = output_root / "part_004_pages_0457_0485" / "pages"
            tables_dir = output_root / "part_004_pages_0457_0485" / "tables"
            visualized_dir = output_root / "visualized_images"

            doc = fitz.open()
            for _ in range(486):
                doc.new_page()
            doc.save(input_pdf)
            doc.close()

            pages_dir.mkdir(parents=True)
            tables_dir.mkdir(parents=True)
            visualized_dir.mkdir(parents=True)

            (pages_dir / "part_004_pages_0458_0486_page_024.json").write_text(
                json.dumps({"index": 24, "page_type": "vector"}), encoding="utf-8"
            )
            (pages_dir / "part_004_pages_0458_0486_page_024.md").write_text("wrong-page", encoding="utf-8")
            (tables_dir / "part_004_pages_0458_0486_page_024.png").write_bytes(b"png")
            (
                visualized_dir
                / "part_004_pages_0457_0485__tables__part_004_pages_0458_0486_page_024.png"
            ).write_bytes(b"png")

            with self.assertRaisesRegex(ValueError, "default excluded visual stem .* expected page 482, got \\[481\\]"):
                build_testset(
                    input_pdf=input_pdf,
                    output_root=output_root,
                    testset_root=testset_root,
                    failed_page_indexes=set(range(486)) - {481},
                )

    def test_compare_testset_passes_for_matching_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            testset_root = root / "testset_markdown"
            actual_root = root / "actual"
            diff_root = testset_root / "diffs"
            (diff_root / "stale.txt").parent.mkdir(parents=True, exist_ok=True)
            (diff_root / "stale.txt").write_text("stale", encoding="utf-8")

            labels_dir = testset_root / "labels"
            labels_dir.mkdir(parents=True)
            (labels_dir / "page-000.md").write_text("Hello\n\n<table>\n<tr><td>A</td><td></td></tr>\n</table>\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "input_pdf": str(root / "input.pdf"),
                "input_pdf_posix": (root / "input.pdf").as_posix(),
                "page_count": 4,
                "generated_at": "2026-09-03T00:00:00+08:00",
                "excluded_visuals": [],
                "failed_pages": [{"page_index": 3, "markdown_status": "failed_no_output"}],
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "markdown",
                        "label_path": "labels/page-000.md",
                        "source_json": "x.json",
                        "source_markdown": "x.md",
                        "source_table_png": "x.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 0,
                        "local_page_index": 0,
                        "source_page_index": 0,
                    },
                    {
                        "page_index": 1,
                        "markdown_status": "absent_expected",
                        "label_path": None,
                        "source_json": "y.json",
                        "source_markdown": None,
                        "source_table_png": "y.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 1,
                        "local_page_index": 1,
                        "source_page_index": 1,
                    },
                    {
                        "page_index": 2,
                        "markdown_status": "excluded",
                        "label_path": None,
                        "source_json": "z.json",
                        "source_markdown": "z.md",
                        "source_table_png": "z.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 2,
                        "local_page_index": 2,
                        "source_page_index": 2,
                    },
                ],
            }
            (testset_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            _write_test_page(actual_root, "part_000_pages_0000_0002", 0, "vector", "Hello\n\n![img](C:/tmp/x.png)\n\n<table>\n<tr><td>A</td><td></td></tr>\n</table>\n")
            _write_test_page(actual_root, "part_000_pages_0000_0002", 1, "scanned", None)
            _write_test_page(actual_root, "part_000_pages_0000_0002", 2, "vector", "ignored")

            self.assertEqual(compare_testset(testset_root, actual_root, diff_root), 0)
            self.assertFalse((diff_root / "stale.txt").exists())
            self.assertEqual(sorted(diff_root.iterdir()), [])

    def test_compare_testset_writes_diff_and_actual_copy_for_markdown_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            testset_root = root / "testset_markdown"
            actual_root = root / "actual"
            diff_root = testset_root / "diffs"
            labels_dir = testset_root / "labels"
            labels_dir.mkdir(parents=True)
            (labels_dir / "page-000.md").write_text("<table>\n<tr><td>A</td><td></td></tr>\n</table>\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "input_pdf": str(root / "input.pdf"),
                "input_pdf_posix": (root / "input.pdf").as_posix(),
                "page_count": 1,
                "generated_at": "2026-09-03T00:00:00+08:00",
                "excluded_visuals": [],
                "failed_pages": [],
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "markdown",
                        "label_path": "labels/page-000.md",
                        "source_json": "x.json",
                        "source_markdown": "x.md",
                        "source_table_png": "x.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 0,
                        "local_page_index": 0,
                        "source_page_index": 0,
                    }
                ],
            }
            (testset_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            _write_test_page(actual_root, "part_000_pages_0000_0000", 0, "vector", "<table>\n<tr><td>__TEST_DIFF__</td><td colspan=\"2\"></td></tr>\n</table>\n")

            self.assertEqual(compare_testset(testset_root, actual_root, diff_root), 1)
            self.assertTrue((diff_root / "page-000.diff.md").exists())
            self.assertTrue((diff_root / "page-000.actual.md").exists())
            self.assertIn("__TEST_DIFF__", (diff_root / "page-000.actual.md").read_text(encoding="utf-8"))

    def test_compare_testset_writes_diff_for_rowspan_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            testset_root = root / "testset_markdown"
            actual_root = root / "actual"
            diff_root = testset_root / "diffs"
            labels_dir = testset_root / "labels"
            labels_dir.mkdir(parents=True)
            (labels_dir / "page-000.md").write_text("<table>\n<tr><td rowspan=\"2\">A</td></tr>\n</table>\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "input_pdf": str(root / "input.pdf"),
                "input_pdf_posix": (root / "input.pdf").as_posix(),
                "page_count": 1,
                "generated_at": "2026-09-03T00:00:00+08:00",
                "excluded_visuals": [],
                "failed_pages": [],
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "markdown",
                        "label_path": "labels/page-000.md",
                        "source_json": "x.json",
                        "source_markdown": "x.md",
                        "source_table_png": "x.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 0,
                        "local_page_index": 0,
                        "source_page_index": 0,
                    }
                ],
            }
            (testset_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            _write_test_page(actual_root, "part_000_pages_0000_0000", 0, "vector", "<table>\n<tr><td>A</td></tr>\n</table>\n")

            self.assertEqual(compare_testset(testset_root, actual_root, diff_root), 1)
            self.assertTrue((diff_root / "page-000.diff.md").exists())

    def test_compare_testset_ignores_image_paths_and_json_bbox_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            testset_root = root / "testset_markdown"
            actual_root = root / "actual"
            diff_root = testset_root / "diffs"
            labels_dir = testset_root / "labels"
            labels_dir.mkdir(parents=True)
            (labels_dir / "page-000.md").write_text("Hello\n\n![old](C:/a.png)\n\n<table>\n<tr><td>A</td></tr>\n</table>\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "input_pdf": str(root / "input.pdf"),
                "input_pdf_posix": (root / "input.pdf").as_posix(),
                "page_count": 1,
                "generated_at": "2026-09-03T00:00:00+08:00",
                "excluded_visuals": [],
                "failed_pages": [],
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "markdown",
                        "label_path": "labels/page-000.md",
                        "source_json": "x.json",
                        "source_markdown": "x.md",
                        "source_table_png": "x.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 0,
                        "local_page_index": 0,
                        "source_page_index": 0,
                    }
                ],
            }
            (testset_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            _write_test_page(
                actual_root,
                "part_000_pages_0000_0000",
                0,
                "vector",
                "Hello\n\n![new](D:/b.png)\n\n<table>\n<tr><td>A</td></tr>\n</table>\n",
                extra_json={"bbox": [1, 2, 3, 4], "render_path": "D:/elsewhere/page.png"},
            )

            self.assertTrue(
                (actual_root / "visualized_images" / "part_000_pages_0000_0000__tables__part_000_pages_0000_0000_page_000.png").exists()
            )
            self.assertEqual(compare_testset(testset_root, actual_root, diff_root), 0)

    def test_compare_testset_fails_for_missing_extra_and_absent_expected_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            testset_root = root / "testset_markdown"
            actual_root = root / "actual"
            diff_root = testset_root / "diffs"
            labels_dir = testset_root / "labels"
            labels_dir.mkdir(parents=True)
            (labels_dir / "page-000.md").write_text("keep", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "input_pdf": str(root / "input.pdf"),
                "input_pdf_posix": (root / "input.pdf").as_posix(),
                "page_count": 5,
                "generated_at": "2026-09-03T00:00:00+08:00",
                "excluded_visuals": [],
                "failed_pages": [{"page_index": 4, "markdown_status": "failed_no_output"}],
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "markdown",
                        "label_path": "labels/page-000.md",
                        "source_json": "x.json",
                        "source_markdown": "x.md",
                        "source_table_png": "x.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 0,
                        "local_page_index": 0,
                        "source_page_index": 0,
                    },
                    {
                        "page_index": 1,
                        "markdown_status": "absent_expected",
                        "label_path": None,
                        "source_json": "y.json",
                        "source_markdown": None,
                        "source_table_png": "y.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 1,
                        "local_page_index": 1,
                        "source_page_index": 1,
                    },
                    {
                        "page_index": 3,
                        "markdown_status": "excluded",
                        "label_path": None,
                        "source_json": "z.json",
                        "source_markdown": "z.md",
                        "source_table_png": "z.png",
                        "source_visual_name": None,
                        "source_visual_path": None,
                        "json_index": 0,
                        "local_page_index": 0,
                        "source_page_index": 3,
                    },
                ],
            }
            (testset_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            _write_test_page(actual_root, "part_000_pages_0000_0001", 1, "scanned", "__unexpected__")
            _write_test_page(actual_root, "part_001_pages_0003_0004", 0, "vector", "excluded present")
            _write_test_page(actual_root, "part_002_pages_0002_0002", 0, "vector", "extra page")

            self.assertEqual(compare_testset(testset_root, actual_root, diff_root), 1)
            self.assertTrue((diff_root / "page-000.diff.md").exists())
            self.assertTrue((diff_root / "page-001.diff.md").exists())
            self.assertTrue((diff_root / "page-002.diff.md").exists())
            self.assertIn("missing actual output", (diff_root / "page-000.diff.md").read_text(encoding="utf-8"))
            self.assertIn("expected absent Markdown", (diff_root / "page-001.diff.md").read_text(encoding="utf-8"))
            self.assertIn("extra actual page", (diff_root / "page-002.diff.md").read_text(encoding="utf-8"))


def _run_self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MarkdownGoldenTestsetTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="self-test")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--testset-root", type=Path)
    parser.add_argument("--actual-root", type=Path)
    parser.add_argument("--diff-root", type=Path)
    args = parser.parse_args()

    if args.command == "self-test":
        return _run_self_test()
    if args.command == "build":
        repo_root = Path(__file__).resolve().parents[1]
        result = build_testset(
            input_pdf=repo_root / (args.pdf or DEFAULT_INPUT_PDF),
            output_root=repo_root / (args.output_root or DEFAULT_OUTPUT_ROOT),
            testset_root=repo_root / (args.testset_root or DEFAULT_TESTSET_ROOT),
        )
        print(json.dumps({key: _stringify_path(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare":
        repo_root = Path(__file__).resolve().parents[1]
        return compare_testset(
            testset_root=repo_root / (args.testset_root or DEFAULT_TESTSET_ROOT),
            actual_root=repo_root / (args.actual_root or DEFAULT_OUTPUT_ROOT),
            diff_root=repo_root / (args.diff_root or DEFAULT_DIFF_ROOT),
        )
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
