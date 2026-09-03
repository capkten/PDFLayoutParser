from __future__ import annotations

import argparse
import difflib
import json
import re
import tempfile
import unittest
from pathlib import Path


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
            raise ValueError(f"{json_path}: missing Markdown companion {markdown_path}")

        visual_path = json_path.parent.parent / "tables" / f"{json_path.stem}.png"
        if not visual_path.exists():
            raise ValueError(f"{json_path}: missing table visualization {visual_path}")

        if page_index in results:
            existing = results[page_index]
            raise ValueError(
                f"conflicting outputs for page {page_index}: {existing['json_path']} vs {json_path}"
            )

        results[page_index] = {
            "page_index": page_index,
            "page_type": page_type,
            "json_path": json_path,
            "markdown_path": markdown_path,
            "visual_path": visual_path,
            "relative_path": json_path.relative_to(output_root).as_posix(),
        }

    return results


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


def _run_self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MarkdownGoldenTestsetTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="self-test")
    args = parser.parse_args()

    if args.command == "self-test":
        return _run_self_test()
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
