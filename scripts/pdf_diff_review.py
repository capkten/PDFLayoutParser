"""Classify semantic differences between two Markdown snapshots."""

from collections import Counter
import difflib
from html.parser import HTMLParser
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

from scripts.markdown_golden_testset import _load_manifest, scan_page_outputs, source_page_index


_WS_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[Dict[str, Any]] = []
        self._table_stack: List[Dict[str, Any]] = []
        self._row: Optional[List[Dict[str, Any]]] = None
        self._cell: Optional[Dict[str, Any]] = None
        self.body_units: List[str] = []
        self.visible_units: List[str] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        tag = tag.lower()
        if tag == "table":
            table = {"rows": [], "texts": []}
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "tr" and self._table_stack and self._cell is None:
            self._row = []
            self._table_stack[-1]["rows"].append(self._row)
        elif tag in {"td", "th"} and self._row is not None and self._cell is None:
            values = dict(attrs)
            self._cell = {
                "text": [],
                "rowspan": self._span(values.get("rowspan")),
                "colspan": self._span(values.get("colspan")),
            }
            self._row.append(self._cell)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None:
            text = _clean_text("".join(self._cell["text"]))
            self._cell["text"] = text
            self._table_stack[-1]["texts"].append(text)
            self.visible_units.append(text)
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
            return
        if self._table_stack:
            return
        for line in data.splitlines():
            text = _clean_text(line)
            if text:
                self.body_units.append(text)
                self.visible_units.append(text)

    @staticmethod
    def _span(value: Optional[str]) -> int:
        try:
            return max(1, int(value or "1"))
        except ValueError:
            return 1


def parse_markdown(markdown: str) -> Dict[str, Any]:
    parser = _MarkdownParser()
    parser.feed(markdown)
    parser.close()
    tables = []
    for table in parser.tables:
        rows = table["rows"]
        tables.append(
            {
                "rows": len(rows),
                "cells_per_row": [len(row) for row in rows],
                "spans": [
                    [(cell["rowspan"], cell["colspan"]) for cell in row]
                    for row in rows
                ],
                "texts": list(table["texts"]),
            }
        )
    return {
        "table_count": len(tables),
        "tables": tables,
        "body_units": parser.body_units,
        "visible_units": parser.visible_units,
    }


def _table_shapes(snapshot: Dict[str, Any]) -> List[Any]:
    return [
        (table["rows"], tuple(table["cells_per_row"]), tuple(map(tuple, table["spans"])))
        for table in snapshot["tables"]
    ]


def _table_text(snapshot: Dict[str, Any]) -> List[str]:
    return [text for table in snapshot["tables"] for text in table["texts"]]


def _normal_form(markdown: str) -> str:
    parser = parse_markdown(markdown)
    body = "\n".join(parser["body_units"])
    tables = repr((_table_shapes(parser), _table_text(parser)))
    return f"{body}\n{tables}"


def detect_signals(expected: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    signals: List[str] = []
    same_count = expected["table_count"] == actual["table_count"]
    shapes_differ = _table_shapes(expected) != _table_shapes(actual)
    table_text_differ = _table_text(expected) != _table_text(actual)
    body_differ = Counter(expected["body_units"]) != Counter(actual["body_units"])
    visible_same = Counter(expected["visible_units"]) == Counter(actual["visible_units"])
    visible_order_differ = expected["visible_units"] != actual["visible_units"]

    if not same_count:
        signals.append("table_count")
    if same_count and shapes_differ:
        signals.append("table_structure")
    if same_count and not shapes_differ and table_text_differ:
        signals.append("table_text")
    if same_count and body_differ:
        signals.append("body_text")
    if visible_same and visible_order_differ:
        signals.append("reading_order")
    return signals


def build_classification(
    expected: str, actual: str, signals: List[str]
) -> Dict[str, Any]:
    if len(signals) == 1:
        primary = signals[0]
        categories = signals
    elif signals:
        primary = "mixed"
        categories = ["mixed"]
    elif _normal_form(expected) == _normal_form(actual) and expected != actual:
        primary = "formatting"
        categories = ["formatting"]
    else:
        primary = "same"
        categories = ["same"]
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    return {
        "primary_category": primary,
        "categories": categories,
        "signals": signals if signals else (["formatting"] if primary == "formatting" else []),
        "evidence": {
            "table_count": {
                "expected": expected_snapshot["table_count"],
                "actual": actual_snapshot["table_count"],
            },
            "table_shapes_differ": _table_shapes(expected_snapshot)
            != _table_shapes(actual_snapshot),
            "table_text_differ": _table_text(expected_snapshot)
            != _table_text(actual_snapshot),
            "body_text_differ": Counter(expected_snapshot["body_units"])
            != Counter(actual_snapshot["body_units"]),
        },
    }


def classify_markdown(expected: str, actual: str) -> Dict[str, Any]:
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    signals = detect_signals(expected_snapshot, actual_snapshot)
    return build_classification(expected, actual, signals)


def _relative(root: Path, path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _actual_pages(
    actual_root: Path,
) -> Tuple[Dict[int, Dict[str, Any]], List[str], Dict[int, List[str]]]:
    """Use the established scanner, but retain a tolerant index for incomplete pages."""
    try:
        return scan_page_outputs(actual_root), [], {}
    except (OSError, ValueError, AttributeError, TypeError, json.JSONDecodeError) as exc:
        scan_error = str(exc)

    pages: Dict[int, Dict[str, Any]] = {}
    errors: List[str] = []
    page_errors: Dict[int, List[str]] = {}
    for json_path in sorted(actual_root.rglob("*.json")):
        if json_path.parent.name != "pages":
            continue
        page_index: Optional[int] = None
        try:
            local_index = int(json_path.stem.rsplit("-", 1)[1])
            page_index = source_page_index(json_path, local_index)
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if data.get("index") != local_index:
                raise ValueError("JSON index does not match filename index")
            page_type = data.get("page_type")
            if not page_type:
                raise ValueError("missing page_type")
        except (
            OSError,
            ValueError,
            AttributeError,
            TypeError,
            KeyError,
            IndexError,
            json.JSONDecodeError,
        ) as exc:
            message = "{}: {}".format(json_path, exc)
            errors.append(message)
            if page_index is not None:
                page_errors.setdefault(page_index, []).append(message)
            continue
        markdown_path = json_path.with_suffix(".md")
        visual_path = json_path.parent.parent / "tables" / (json_path.stem + ".png")
        if page_index in pages:
            message = "conflicting outputs for page {}: {}".format(page_index, json_path)
            errors.append(message)
            page_errors.setdefault(page_index, []).append(message)
            continue
        pages[page_index] = {
            "page_index": page_index,
            "page_type": page_type,
            "json_index": data.get("index"),
            "local_page_index": local_index,
            "source_page_index": page_index,
            "json_path": json_path,
            "markdown_path": markdown_path if markdown_path.exists() else None,
            "visual_path": visual_path if visual_path.exists() else None,
            "visualized_image_path": None,
            "visualized_image_name": None,
        }
    if scan_error:
        errors.insert(0, scan_error)
    return pages, errors, page_errors


def _find_label_image(testset_root: Path, page: Dict[str, Any]) -> Optional[Path]:
    candidates = []
    source_visual_path = page.get("source_visual_path")
    if source_visual_path:
        candidates.extend(
            [testset_root / source_visual_path, testset_root.parent / source_visual_path]
        )
    source_table_png = page.get("source_table_png")
    if source_table_png:
        candidates.append(testset_root.parent / source_table_png)
    for candidate in candidates:
        if candidate.resolve().exists():
            return candidate.resolve()
    return None


def make_side_by_side(
    expected_png: Optional[Path],
    actual_png: Optional[Path],
    output_png: Path,
    page_index: int,
    errors: Optional[List[str]] = None,
) -> None:
    """Render two PNGs on one PyMuPDF page, including placeholders for missing inputs."""
    pixmaps: List[Optional[fitz.Pixmap]] = []
    for label, path in zip(("label", "current"), (expected_png, actual_png)):
        try:
            pixmaps.append(fitz.Pixmap(str(path)) if path is not None else None)
        except Exception as exc:
            pixmaps.append(None)
            if errors is not None:
                errors.append("unreadable {} PNG: {}".format(label, exc))
    valid = [pix for pix in pixmaps if pix is not None]
    max_height = max([pix.height for pix in valid] or [360])
    scale = min(1.0, 900.0 / max_height)
    gap = 16
    header = 36
    widths = [max(180, int((pix.width if pix else 360) * scale)) for pix in pixmaps]
    doc = fitz.open()
    page = doc.new_page(width=sum(widths) + gap, height=int(max_height * scale) + header)
    labels = ("LABEL", "CURRENT")
    for index, pix in enumerate(pixmaps):
        x = sum(widths[:index]) + (gap if index else 0)
        rect = fitz.Rect(x, header, x + widths[index], page.rect.height)
        page.insert_text((x + 6, 22), labels[index], fontsize=12, color=(0.1, 0.1, 0.1))
        if pix is None:
            page.draw_rect(rect, color=(0.8, 0.2, 0.2), fill=(0.96, 0.9, 0.9), width=1)
            page.insert_textbox(rect, "MISSING RESOURCE", fontsize=12, align=1, color=(0.6, 0.1, 0.1))
        else:
            page.insert_image(rect, pixmap=pix, keep_proportion=True)
    page.insert_text((page.rect.width - 100, 22), "PAGE {:03d}".format(page_index), fontsize=10)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    rendered = page.get_pixmap(alpha=False)
    rendered.save(str(output_png))
    doc.close()


def _diff(expected: str, actual: str) -> str:
    lines = difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="label", tofile="current", lineterm=""
    )
    return "\n".join(lines)


def _searchable_text(markdown: str) -> str:
    """Return body and table cell text used only by the page search index."""
    return "\n".join(parse_markdown(markdown)["visible_units"])


def _safe_json(value: Any) -> str:
    """Serialize data for an inline script without allowing HTML script termination."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html(payload: Dict[str, Any]) -> str:
    """Render the self-contained offline review workbench."""
    data = _safe_json(payload)
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDF Diff Review</title>
<style>
:root{--paper:#f5f0e7;--ink:#24231f;--muted:#756e63;--line:#d8cdbb;--red:#a74337;--green:#347054;--blue:#315b79}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 Georgia,"Times New Roman",serif;height:100vh;overflow:hidden}
button,input,select{font:inherit;color:inherit}button{cursor:pointer;border:1px solid var(--line);background:#fffaf1;padding:7px 10px;border-radius:4px}button:hover{border-color:var(--blue)}
header{height:76px;display:flex;align-items:center;gap:24px;padding:12px 22px;border-bottom:2px solid var(--ink);background:#eee5d6}h1{font-size:23px;margin:0;letter-spacing:.04em}.stats{display:flex;gap:20px;margin-left:auto}.stat b{display:block;font-size:21px}.stat span{color:var(--muted);font-size:12px}
.layout{display:grid;grid-template-columns:255px minmax(420px,1fr) 390px;height:calc(100vh - 76px)}aside,.diff-panel{overflow:auto;padding:16px;border-right:1px solid var(--line)}.diff-panel{border-right:0;border-left:1px solid var(--line);background:#f9f4eb}
.filters{display:grid;gap:8px;margin-bottom:14px}.filters input,.filters select{width:100%;padding:8px;border:1px solid var(--line);background:#fffdf8;border-radius:3px}.page-list{list-style:none;padding:0;margin:0}.page-list button{width:100%;display:grid;grid-template-columns:44px 1fr auto;text-align:left;gap:5px;margin:3px 0;background:transparent;border-color:transparent}.page-list button.active{background:#e0d5c4;border-color:#b9aa94}.kind{color:var(--muted);font-size:11px}.signal{color:var(--red);font-size:11px}.main{padding:16px;overflow:auto}.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.nav{display:flex;gap:7px;align-items:center}.current-page{font-size:17px}.images{display:grid;grid-template-columns:1fr 1fr;gap:12px}.image-card{border:1px solid var(--line);background:#fffdf8;padding:8px}.image-card h2{font-size:13px;margin:0 0 7px;color:var(--muted)}.image-card img{display:block;width:100%;height:auto;min-height:180px;object-fit:contain;background:#e9e1d5}.image-card img.zoomable{cursor:zoom-in}.decision{margin-top:14px;padding:12px;background:#eee5d6;border:1px solid var(--line)}.decision-options{display:flex;gap:8px;flex-wrap:wrap}.decision label{padding:7px 10px;background:#fffaf1;border:1px solid var(--line);border-radius:4px}.decision label.selected{outline:2px solid var(--blue)}
.diff-panel h2{font-size:16px;margin:0 0 9px}.diff-meta{color:var(--muted);font-size:12px;margin-bottom:12px}.diff{white-space:pre-wrap;word-break:break-word;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;background:#fffdf8;border:1px solid var(--line);padding:11px;min-height:140px}.diff .add{color:var(--green);background:#e4f1e8}.diff .del{color:var(--red);background:#f6e3df}.errors{color:var(--red);margin-top:12px}.empty{color:var(--muted);padding:16px;text-align:center}.modal{position:fixed;inset:0;background:#191713d9;display:none;align-items:center;justify-content:center;padding:24px;z-index:2}.modal.open{display:flex}.modal img{max-width:95vw;max-height:92vh;background:white}.modal button{position:absolute;right:20px;top:20px}
@media(max-width:1000px){.layout{grid-template-columns:210px minmax(360px,1fr)}.diff-panel{display:none}.stats{gap:10px}.images{grid-template-columns:1fr}}
</style></head><body>
<header><h1>PDF Diff Review</h1><div class="stats"><div class="stat"><b id="total-count">0</b><span>总页数</span></div><div class="stat"><b id="decided-count">0</b><span>已决策</span></div><div class="stat"><b id="pending-count">0</b><span>待确认</span></div></div><button id="export-review">导出审阅结果</button><span id="storage-warning" role="status" aria-live="polite"></span></header>
<div class="layout"><aside><div class="filters"><select id="category-filter"><option value="all">全部分类</option></select><input id="page-search" type="search" placeholder="搜索页码或文本"></div><ul id="page-list" class="page-list"></ul></aside>
<main class="main"><div class="toolbar"><div class="nav"><button id="previous-page">上一页</button><span id="current-page" class="current-page"></span><button id="next-page">下一页</button></div><button id="zoom-image">放大合成图</button></div><div id="images" class="images"></div><section class="decision"><strong>审阅决策</strong><div id="decision-options" class="decision-options"><label><input type="radio" name="decision" value="keep-current"> 保留当前</label><label><input type="radio" name="decision" value="keep-label"> 保留标签</label><label><input type="radio" name="decision" value="pending" checked> 待确认</label></div></section></main>
<section class="diff-panel"><h2>文本差异</h2><div id="diff-meta" class="diff-meta"></div><pre id="diff" class="diff"></pre><div id="errors" class="errors"></div></section></div>
<div id="image-modal" class="modal"><button id="close-modal">关闭</button><img id="modal-image" alt="放大原图"></div>
<script>
(function(){
"use strict";
var payload=__PAYLOAD__;
var pages=payload.pages||[], decisions=loadDecisions(), visible=[], selectedIndex=0;
var $=function(id){return document.getElementById(id)};
function loadDecisions(){try{return JSON.parse(localStorage.getItem("pdf-diff-review-decisions")||"{}")}catch(e){return {}}}
function showStorageWarning(){var warning=$("storage-warning");if(warning){warning.textContent="浏览器存储不可用，决策仅保留在当前页面";setTimeout(function(){warning.textContent=""},4000)}}
function save(){try{localStorage.setItem("pdf-diff-review-decisions",JSON.stringify(decisions))}catch(e){showStorageWarning()}updateStats()}
function labelFor(category){return {same:"相同",formatting:"格式",body_text:"正文",table_text:"表格文本",table_structure:"表格结构",table_count:"表格数量",reading_order:"阅读顺序",mixed:"混合",missing_resource:"资源缺失"}[category]||category}
function updateStats(){var decided=0;pages.forEach(function(p){if(decisions[p.page_index]&&decisions[p.page_index]!=="pending")decided++});$("total-count").textContent=pages.length;$("decided-count").textContent=decided;$("pending-count").textContent=pages.length-decided}
function renderList(){var filter=$("category-filter").value, query=$("page-search").value.toLowerCase();visible=pages.map(function(p,i){return {p:p,i:i}}).filter(function(x){var p=x.p, text=(p.page_index+" "+(p.primary_category||"")+" "+(p.searchable_text||"")+" "+(p.diff||"")).toLowerCase();return (filter==="all"||p.primary_category===filter)&&(!query||text.indexOf(query)>=0)});var list=$("page-list");list.textContent="";if(!visible.length){var empty=document.createElement("li");empty.className="empty";empty.textContent="没有匹配页面";list.appendChild(empty);return}visible.forEach(function(x){var b=document.createElement("button"), n=document.createElement("span"), c=document.createElement("span"), s=document.createElement("span");b.type="button";b.className=x.i===selectedIndex?"active":"";n.textContent="P"+String(x.p.page_index+1).padStart(3,"0");c.textContent=labelFor(x.p.primary_category);c.className="kind";s.textContent=decisions[x.p.page_index]&&decisions[x.p.page_index]!=="pending"?"已决策":"待确认";s.className="signal";b.append(n,c,s);b.onclick=function(){selectedIndex=x.i;renderList();renderPage()};list.appendChild(b)})}
function renderDiff(text){var out=$("diff");out.textContent="";(text||"").split("\\n").forEach(function(line,i){var span=document.createElement("span");span.textContent=line+(i<((text||"").split("\\n").length-1)?"\\n":"");if(line.charAt(0)==="+")span.className="add";if(line.charAt(0)==="-")span.className="del";out.appendChild(span)})}
function openImage(path,alt){$("modal-image").src=path||"";$("modal-image").alt=alt||"放大原图";$("image-modal").className="modal open"}
function renderPage(){var p=pages[selectedIndex];if(!p)return;$("current-page").textContent="第 "+(p.page_index+1)+" / "+pages.length+" 页";$("images").textContent="";[["标签",p.label_png],["当前",p.source_png]].forEach(function(pair){var card=document.createElement("div"),h=document.createElement("h2"),img=document.createElement("img");card.className="image-card";h.textContent=pair[0];img.src=pair[1]||"";img.alt=pair[0]+"页面图像";img.className="zoomable";img.onclick=function(){openImage(pair[1],pair[0]+"原图")};card.append(h,img);$("images").appendChild(card)});$("diff-meta").textContent=labelFor(p.primary_category)+" · "+(p.signals||[]).join(", ");renderDiff(p.diff);$("errors").textContent=(p.errors||[]).join("\\n");var value=decisions[p.page_index]||"pending";document.querySelectorAll('input[name="decision"]').forEach(function(input){input.checked=input.value===value;input.parentElement.className=input.checked?"selected":""})}
function move(step){if(!visible.length)return;var pos=visible.findIndex(function(x){return x.i===selectedIndex}), next=pos<0?0:Math.max(0,Math.min(visible.length-1,pos+step));selectedIndex=visible[next].i;renderList();renderPage()}
$("category-filter").append.apply($("category-filter"),Object.keys(payload.category_counts||{}).sort().map(function(k){var o=document.createElement("option");o.value=k;o.textContent=labelFor(k);return o}));$("category-filter").onchange=renderList;$("page-search").oninput=function(){renderList()};$("previous-page").onclick=function(){move(-1)};$("next-page").onclick=function(){move(1)};
document.querySelectorAll('input[name="decision"]').forEach(function(input){input.onchange=function(){decisions[pages[selectedIndex].page_index]=input.value;save();renderList()}});document.onkeydown=function(e){if(e.target&&/input|select|textarea/i.test(e.target.tagName))return;if(e.key==="1")document.querySelector('input[value="keep-current"]').click();if(e.key==="2")document.querySelector('input[value="keep-label"]').click();if(e.key==="3")document.querySelector('input[value="pending"]').click();if(e.key==="ArrowLeft")move(-1);if(e.key==="ArrowRight")move(1)};
$("zoom-image").onclick=function(){var p=pages[selectedIndex];if(!p)return;openImage(p.image_path||"","合成审阅图")};$("close-modal").onclick=function(){$("image-modal").className="modal"};$("image-modal").onclick=function(e){if(e.target===$("image-modal"))$("close-modal").click()};$("export-review").onclick=function(){var result={exported_at:new Date().toISOString(),decisions:decisions,pages:pages.map(function(p){return {page_index:p.page_index,decision:decisions[p.page_index]||"pending",primary_category:p.primary_category}})};var blob=new Blob([JSON.stringify(result,null,2)],{type:"application/json"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="pdf-diff-review.json";a.click();URL.revokeObjectURL(a.href)};
updateStats();renderList();renderPage();
})();
</script></body></html>""".replace("__PAYLOAD__", data)


def build_review(actual_root: Path, testset_root: Path, review_dir: Path) -> Dict[str, Any]:
    actual_root = Path(actual_root)
    testset_root = Path(testset_root)
    review_dir = Path(review_dir)
    manifest = _load_manifest(testset_root)
    actual_pages, scan_errors, page_errors = _actual_pages(actual_root)
    pages: List[Dict[str, Any]] = []
    category_counts: Counter = Counter()
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "images").mkdir(parents=True, exist_ok=True)

    manifest_pages = {page["page_index"]: page for page in manifest["pages"]}
    for page_index in range(manifest["page_count"]):
        manifest_page = manifest_pages.get(page_index, {"page_index": page_index, "markdown_status": "failed_no_output"})
        actual = actual_pages.get(page_index)
        expected_md = None
        label_path = manifest_page.get("label_path")
        if label_path:
            expected_md = (testset_root / label_path).resolve()
        actual_md = actual.get("markdown_path") if actual else None
        expected_text = expected_md.read_text(encoding="utf-8") if expected_md and expected_md.exists() else ""
        actual_text = actual_md.read_text(encoding="utf-8") if actual_md and actual_md.exists() else ""
        errors: List[str] = list(page_errors.get(page_index, []))
        actual_json = actual.get("json_path") if actual else None
        for scan_error in scan_errors:
            if (actual_json is not None and str(actual_json) in scan_error) or (
                "page-{:03d}".format(page_index) in scan_error
            ):
                if scan_error not in errors:
                    errors.append(scan_error)
        markdown_required = manifest_page.get("markdown_status") == "markdown"
        if markdown_required and expected_md is None:
            errors.append("missing label Markdown")
        if markdown_required and actual_md is None:
            errors.append("missing actual Markdown")
        expected_png = _find_label_image(testset_root, manifest_page)
        actual_png = actual.get("visual_path") if actual else None
        if expected_png is None:
            errors.append("missing label PNG")
        if actual_png is None:
            errors.append("missing actual PNG")
        classification = classify_markdown(expected_text, actual_text)
        if errors:
            primary = "missing_resource"
            category_counts[primary] += 1
        else:
            primary = classification["primary_category"]
            category_counts[primary] += 1
        image_path = review_dir / "images" / "page-{:03d}.png".format(page_index)
        make_side_by_side(expected_png, actual_png, image_path, page_index, errors)
        label_review_path = None
        if expected_png is not None:
            label_review_path = review_dir / "images" / "source" / "page-{:03d}-label.png".format(page_index)
            try:
                label_review_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(expected_png), str(label_review_path))
            except OSError as exc:
                errors.append("failed to copy label PNG: {}".format(exc))
                label_review_path = None
        source_review_path = None
        if actual_png is not None:
            source_review_path = review_dir / "images" / "source" / "page-{:03d}-current.png".format(page_index)
            try:
                source_review_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(actual_png), str(source_review_path))
            except OSError as exc:
                errors.append("failed to copy current PNG: {}".format(exc))
                source_review_path = None
        record = dict(classification)
        record.update(
            {
                "page_index": page_index,
                "page_type": actual.get("page_type") if actual else manifest_page.get("page_type", "unknown"),
                "primary_category": primary,
                "diff": _diff(expected_text, actual_text),
                "label_path": _relative(testset_root, expected_md),
                "source_markdown": _relative(actual_root, actual_md),
                "label_png": _relative(review_dir, label_review_path),
                "source_png": _relative(review_dir, source_review_path),
                "searchable_text": "\n".join(
                    value for value in (_searchable_text(expected_text), _searchable_text(actual_text)) if value
                ),
                "source_visual_path": manifest_page.get("source_visual_path"),
                "source_table_png": manifest_page.get("source_table_png"),
                "image_path": "images/page-{:03d}.png".format(page_index),
                "errors": errors,
                "source_json": _relative(actual_root, actual.get("json_path") if actual else None),
            }
        )
        pages.append(record)

    payload = {"pages": pages, "category_counts": dict(category_counts)}
    (review_dir / "classification.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "page_count": len(pages),
        "diff_count": sum(1 for page in pages if page["primary_category"] != "same"),
        "category_counts": dict(category_counts),
        "pages": pages,
        "scan_errors": scan_errors,
    }
    (review_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (review_dir / "index.html").write_text(render_html(payload), encoding="utf-8")
    return summary
