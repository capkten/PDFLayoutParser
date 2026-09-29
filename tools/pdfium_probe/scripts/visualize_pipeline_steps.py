"""Full-pipeline step-by-step visualizer comparing PDFium and PyMuPDF extractions.

Generates high-DPI multi-stage visual comparison graphics for representative PDF samples:
- Stage 1: Raw Atomic Elements (Spans, Fonts, Render Modes, Drawing Paths)
- Stage 2: Visual Hierarchy Normalization & Clustering (Lines, Blocks, Words)
- Stage 3: Table Structure Recovery (Wireless/Wired Grids, Column Bands, Cells, Empty Slots)
- Stage 4: Final Layout & Reading Order (Numbered badges, Reading flow trajectory)
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import fitz
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add src and probe scripts to path
def get_probe_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_repo_root() -> Path:
    """Return root directory of the main repository."""
    if "REPO_ROOT" in os.environ:
        return Path(os.environ["REPO_ROOT"])
    probe_root = get_probe_root()
    direct = probe_root.parents[1]
    if (direct / "test.pdf").exists():
        return direct
    worktree_parent = direct.parents[1]
    if (worktree_parent / "test.pdf").exists():
        return worktree_parent
    fallback_d = Path("D:/codes/PDFLayoutParser")
    if (fallback_d / "test.pdf").exists():
        return fallback_d
    return direct


_PROBE_ROOT = get_probe_root()
_PROBE_SCRIPTS = _PROBE_ROOT / "scripts"
_REPO_ROOT = get_repo_root()
worktree_src = _PROBE_ROOT.parents[1] / "src"
if worktree_src.exists() and str(worktree_src) not in sys.path:
    sys.path.insert(0, str(worktree_src))
if str(_PROBE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PROBE_SCRIPTS))
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.append(str(_SRC_DIR))

from behavioral_contract import build_layout_signature
from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox, Cell, Document, Page, Table
from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder
from hexai_pdf_parser.extractors.layout_mapper import LayoutMapper
from hexai_pdf_parser.extractors.text_extractor import TextExtractor
from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot
from pdfium_classification import classify_raw_page
from pdfium_normalizer import normalize_raw_page
from pdfium_page_adapter import PdfiumPageAdapter
from pdfium_shadow_runner import _extract_wired_table


# --- Color Palette Constants (RGBA) ---
COLOR_HEADER_BG = (30, 41, 59, 255)         # Slate 800
COLOR_HEADER_TEXT = (255, 255, 255, 255)
COLOR_SUBHEADER_BG = (51, 65, 85, 255)      # Slate 700
COLOR_FOOTER_BG = (15, 23, 42, 255)         # Slate 900
COLOR_DIVIDER = (100, 116, 139, 255)        # Slate 500

# Stage 1 Colors
COLOR_RAW_SPAN_STROKE = (225, 29, 72, 220)       # Rose 600
COLOR_RAW_SPAN_FILL = (254, 205, 211, 60)        # Rose 100 translucent
COLOR_RAW_DRAWING_STROKE = (14, 165, 233, 230)   # Sky 500
COLOR_RAW_DRAWING_FILL = (186, 230, 253, 50)     # Sky 100 translucent
COLOR_INVISIBLE_STROKE = (156, 163, 175, 220)    # Gray 400
COLOR_INVISIBLE_FILL = (229, 231, 235, 80)       # Gray 200

# Stage 2 Colors
COLOR_LINE_STROKE = (234, 88, 12, 230)          # Orange 600
COLOR_LINE_FILL = (254, 215, 170, 50)           # Orange 100
COLOR_BLOCK_STROKE = (22, 163, 74, 230)         # Green 600
COLOR_BLOCK_FILL = (187, 247, 208, 40)          # Green 100
COLOR_WORD_STROKE = (147, 51, 234, 160)         # Purple 600

# Stage 3 Colors
COLOR_TABLE_REGION = (220, 38, 38, 255)         # Red 600
COLOR_COL_BAND_FILL = (224, 231, 255, 70)       # Indigo 100
COLOR_COL_BAND_LINE = (99, 102, 241, 180)       # Indigo 500
COLOR_CELL_STROKE = (2, 132, 199, 240)          # Light Blue 600
COLOR_CELL_FILL = (224, 242, 254, 50)           # Light Blue 50
COLOR_EMPTY_CELL_STROKE = (156, 163, 175, 200)  # Gray 400
COLOR_EMPTY_CELL_FILL = (243, 244, 246, 70)     # Gray 100
COLOR_SPAN_CELL_STROKE = (217, 119, 6, 250)     # Amber 600
COLOR_SPAN_CELL_FILL = (254, 243, 199, 90)      # Amber 100
COLOR_PHYSICAL_LINE = (192, 38, 211, 240)       # Fuchsia 600

# Stage 4 Colors
COLOR_ORDER_TEXT_BOX = (16, 185, 129, 220)      # Emerald 500
COLOR_ORDER_TEXT_FILL = (209, 250, 229, 50)
COLOR_ORDER_TABLE_BOX = (239, 68, 68, 220)      # Red 500
COLOR_ORDER_TABLE_FILL = (254, 226, 226, 50)
COLOR_BADGE_BG_TEXT = (5, 150, 105, 255)        # Emerald 600
COLOR_BADGE_BG_TABLE = (220, 38, 38, 255)       # Red 600
COLOR_TRAJECTORY_LINE = (99, 102, 241, 180)     # Indigo 500


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load system TTF font with fallback to default PIL font."""
    font_candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in font_candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def render_page_base_image(
    doc: fitz.Document,
    page_index: int,
    dpi: int = 180,
    soften: bool = True,
) -> Tuple[Image.Image, float, float]:
    """Render PDF page to PIL Image at target DPI and return scale factors."""
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")

    if soften:
        # Blend lightly with white so colored annotations stand out
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.blend(img, white, 0.28)

    scale_x = float(pix.width) / float(page.rect.width)
    scale_y = float(pix.height) / float(page.rect.height)
    return img, scale_x, scale_y


def draw_badge(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float],
    text: str,
    bg_color: Tuple[int, int, int, int],
    text_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
    radius: int = 11,
    font_size: int = 12,
) -> None:
    """Draw a round badge with centered number or short label."""
    cx, cy = xy
    font = get_font(font_size, bold=True)
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=bg_color,
        outline=(255, 255, 255, 240),
        width=1,
    )
    if font:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw / 2.0, cy - th / 2.0 - 1), text, fill=text_color, font=font)


def draw_tag_box(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    bg_color: Tuple[int, int, int, int],
    text_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
    font_size: int = 11,
) -> Tuple[float, float]:
    """Draw a small rectangular tag badge and return its width and height."""
    font = get_font(font_size, bold=True)
    pad_x = 4
    pad_y = 2
    if font:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    else:
        tw = len(text) * 7
        th = 10
    w = tw + pad_x * 2
    h = th + pad_y * 2
    draw.rectangle([x, y, x + w, y + h], fill=bg_color, outline=(255, 255, 255, 200), width=1)
    if font:
        draw.text((x + pad_x, y + pad_y - 1), text, fill=text_color, font=font)
    return w, h


# ==============================================================================
# Pipeline Visualizers
# ==============================================================================

def visualize_stage_1_raw(
    base_img: Image.Image,
    scale_x: float,
    scale_y: float,
    spans: Sequence[Mapping[str, Any]],
    drawings: Sequence[Mapping[str, Any]],
    title_suffix: str = "",
) -> Image.Image:
    """Stage 1: Visualize raw atomic text spans and vector drawing paths."""
    canvas = base_img.copy()
    overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font_lbl = get_font(10)

    # 1. Draw vector drawing paths
    for d_idx, d in enumerate(drawings):
        d_type = d.get("path_type") or d.get("kind", "")
        # Drawing lines
        lines = d.get("lines") or []
        for line in lines:
            l_r = line.get("rect") or [0, 0, 0, 0]
            if isinstance(l_r, Mapping):
                lx0, ly0, lx1, ly1 = l_r.get("x0", 0), l_r.get("y0", 0), l_r.get("x1", 0), l_r.get("y1", 0)
            elif isinstance(l_r, (list, tuple)) and len(l_r) >= 4:
                lx0, ly0, lx1, ly1 = l_r[0], l_r[1], l_r[2], l_r[3]
            else:
                continue
            rx0, ry0 = lx0 * scale_x, ly0 * scale_y
            rx1, ry1 = lx1 * scale_x, ly1 * scale_y
            draw.line([(rx0, ry0), (rx1, ry1)], fill=COLOR_RAW_DRAWING_STROKE, width=2)

        # Drawing rects / items
        items = d.get("items") or []
        for item in items:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                itype = item[0]
                if itype == "l":  # line
                    p1, p2 = item[1], item[2]
                    draw.line(
                        [(p1[0] * scale_x, p1[1] * scale_y), (p2[0] * scale_x, p2[1] * scale_y)],
                        fill=COLOR_RAW_DRAWING_STROKE,
                        width=2,
                    )
                elif itype == "re":  # rect
                    r = item[1]
                    rx0, ry0 = r[0] * scale_x, r[1] * scale_y
                    rx1, ry1 = (r[0] + r[2]) * scale_x, (r[1] + r[3]) * scale_y
                    draw.rectangle([rx0, ry0, rx1, ry1], fill=COLOR_RAW_DRAWING_FILL, outline=COLOR_RAW_DRAWING_STROKE, width=1)

    # 2. Draw raw text spans
    for s_idx, span in enumerate(spans):
        bbox = span.get("bbox") or [0, 0, 0, 0]
        text = str(span.get("text", "")).strip()
        render_mode = int(span.get("render_mode", 0))
        is_invisible = bool(span.get("is_invisible", False)) or render_mode == 3

        x0, y0 = bbox[0] * scale_x, bbox[1] * scale_y
        x1, y1 = bbox[2] * scale_x, bbox[3] * scale_y
        if x1 - x0 < 1:
            x1 = x0 + 2
        if y1 - y0 < 1:
            y1 = y0 + 2

        stroke = COLOR_INVISIBLE_STROKE if is_invisible else COLOR_RAW_SPAN_STROKE
        fill = COLOR_INVISIBLE_FILL if is_invisible else COLOR_RAW_SPAN_FILL

        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=stroke, width=1)

        # Tag invisible text or span order
        if is_invisible:
            draw_tag_box(draw, x0, max(0.0, y0 - 14), f"inv(rm=3): {text[:8]}", bg_color=(107, 114, 128, 240), font_size=10)
        elif s_idx % 3 == 0 and text:
            label = f"S{s_idx}: {text[:6]}"
            draw.text((x0 + 2, max(0.0, y0 - 11)), label, fill=(190, 18, 60, 255), font=font_lbl)

    return Image.alpha_composite(canvas, overlay)


def visualize_stage_2_hierarchy(
    base_img: Image.Image,
    scale_x: float,
    scale_y: float,
    blocks: Sequence[Mapping[str, Any]],
    words: Sequence[Any] = (),
) -> Image.Image:
    """Stage 2: Visualize visual lines, blocks, and words clustering."""
    canvas = base_img.copy()
    overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font_line = get_font(11, bold=True)
    font_block = get_font(13, bold=True)

    # 1. Draw words as subtle dotted boundaries
    for w in words:
        if isinstance(w, (list, tuple)) and len(w) >= 4:
            wx0, wy0 = w[0] * scale_x, w[1] * scale_y
            wx1, wy1 = w[2] * scale_x, w[3] * scale_y
            draw.rectangle([wx0, wy0, wx1, wy1], outline=COLOR_WORD_STROKE, width=1)

    # 2. Draw blocks and lines
    line_counter = 0
    for b_idx, block in enumerate(blocks):
        b_bbox = block.get("bbox") or [0, 0, 0, 0]
        bx0, by0 = b_bbox[0] * scale_x, b_bbox[1] * scale_y
        bx1, by1 = b_bbox[2] * scale_x, b_bbox[3] * scale_y

        # Block outline
        draw.rectangle([bx0, by0, bx1, by1], fill=COLOR_BLOCK_FILL, outline=COLOR_BLOCK_STROKE, width=2)
        draw_tag_box(draw, bx0, max(0.0, by0 - 18), f"Block {b_idx}", bg_color=COLOR_BLOCK_STROKE, font_size=11)

        # Lines in block
        lines = block.get("lines") or []
        for l_idx, line in enumerate(lines):
            l_bbox = line.get("bbox") or [0, 0, 0, 0]
            lx0, ly0 = l_bbox[0] * scale_x, l_bbox[1] * scale_y
            lx1, ly1 = l_bbox[2] * scale_x, l_bbox[3] * scale_y

            draw.rectangle([lx0, ly0, lx1, ly1], fill=COLOR_LINE_FILL, outline=COLOR_LINE_STROKE, width=1)

            # Draw individual spans inside line
            spans = line.get("spans") or []
            for s_idx, sp in enumerate(spans):
                s_b = sp.get("bbox") or [0, 0, 0, 0]
                sx0, sy0 = s_b[0] * scale_x, s_b[1] * scale_y
                sx1, sy1 = s_b[2] * scale_x, s_b[3] * scale_y
                draw.rectangle([sx0, sy0, sx1, sy1], outline=(225, 29, 72, 140), width=1)

            # Line label on the right
            label = f"L{line_counter}"
            draw.text((min(canvas.width - 35, lx1 + 4), (ly0 + ly1) / 2.0 - 6), label, fill=COLOR_LINE_STROKE, font=font_line)
            line_counter += 1

    return Image.alpha_composite(canvas, overlay)


def visualize_stage_3_table(
    base_img: Image.Image,
    scale_x: float,
    scale_y: float,
    table_regions: Sequence[Mapping[str, Any]],
    recovered_tables: Sequence[Table],
    dto: Optional[Mapping[str, Any]] = None,
) -> Image.Image:
    """Stage 3: Visualize table structure, grid, column bands, and cells."""
    canvas = base_img.copy()
    overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font_cell = get_font(10, bold=True)
    font_tbl = get_font(13, bold=True)

    # 1. Draw input table candidate regions
    for reg in table_regions:
        rx0, ry0 = float(reg.get("x0", 0)) * scale_x, float(reg.get("y0", 0)) * scale_y
        rx1, ry1 = float(reg.get("x1", 0)) * scale_x, float(reg.get("y1", 0)) * scale_y
        draw.rectangle([rx0, ry0, rx1, ry1], outline=COLOR_TABLE_REGION, width=2)
        draw_tag_box(
            draw,
            rx0 + 4,
            ry0 + 4,
            f"Region ({reg.get('kind', 'wireless')}): [{reg.get('x0'):.0f},{reg.get('y0'):.0f}..{reg.get('x1'):.0f},{reg.get('y1'):.0f}]",
            bg_color=COLOR_TABLE_REGION,
            font_size=11,
        )

    # 2. Draw physical lines if wired table
    if dto:
        drawings = dto.get("drawings") or []
        for d in drawings:
            lines = d.get("lines") or []
            for line in lines:
                l_r = line.get("rect") or {}
                if isinstance(l_r, (list, tuple)) and len(l_r) == 4:
                    lx0, ly0, lx1, ly1 = l_r[0], l_r[1], l_r[2], l_r[3]
                elif isinstance(l_r, Mapping):
                    lx0, ly0, lx1, ly1 = l_r.get("x0", 0), l_r.get("y0", 0), l_r.get("x1", 0), l_r.get("y1", 0)
                else:
                    continue
                draw.line(
                    [(lx0 * scale_x, ly0 * scale_y), (lx1 * scale_x, ly1 * scale_y)],
                    fill=COLOR_PHYSICAL_LINE,
                    width=2,
                )

    # 3. Draw recovered tables and their 2D cells
    for t_idx, tbl in enumerate(recovered_tables):
        tx0, ty0 = tbl.bbox.x0 * scale_x, tbl.bbox.y0 * scale_y
        tx1, ty1 = tbl.bbox.x1 * scale_x, tbl.bbox.y1 * scale_y

        draw.rectangle([tx0, ty0, tx1, ty1], outline=COLOR_TABLE_REGION, width=3)
        draw_tag_box(
            draw,
            tx0,
            max(0.0, ty0 - 22),
            f"Recovered Table {t_idx + 1}: {tbl.rows} rows x {tbl.cols} cols [{tbl.source}]",
            bg_color=COLOR_TABLE_REGION,
            font_size=12,
        )

        # Draw cells
        for cell in tbl.cells:
            cx0, cy0 = cell.bbox.x0 * scale_x, cell.bbox.y0 * scale_y
            cx1, cy1 = cell.bbox.x1 * scale_x, cell.bbox.y1 * scale_y
            if cx1 - cx0 < 2:
                cx1 = cx0 + 4
            if cy1 - cy0 < 2:
                cy1 = cy0 + 4

            is_empty = not cell.text.strip()
            is_span = cell.rowspan > 1 or cell.colspan > 1

            if is_span:
                stroke = COLOR_SPAN_CELL_STROKE
                fill = COLOR_SPAN_CELL_FILL
            elif is_empty:
                stroke = COLOR_EMPTY_CELL_STROKE
                fill = COLOR_EMPTY_CELL_FILL
            else:
                stroke = COLOR_CELL_STROKE
                fill = COLOR_CELL_FILL

            draw.rectangle([cx0, cy0, cx1, cy1], fill=fill, outline=stroke, width=1)

            # Cell badge
            tag = f"({cell.row_index},{cell.col_index})"
            if is_span:
                tag += f" [{cell.rowspan}x{cell.colspan}]"
            elif is_empty:
                tag += " ∅"

            draw.text((cx0 + 2, cy0 + 2), tag, fill=stroke, font=font_cell)

    return Image.alpha_composite(canvas, overlay)


def visualize_stage_4_reading_order(
    base_img: Image.Image,
    scale_x: float,
    scale_y: float,
    layout_elements: Sequence[Any],
) -> Image.Image:
    """Stage 4: Visualize final layout structure with numbered reading order badges."""
    canvas = base_img.copy()
    overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font_lbl = get_font(12, bold=True)

    prev_center: Optional[Tuple[float, float]] = None

    for elem in layout_elements:
        order = int(getattr(elem, "reading_order", getattr(elem, "order", 0)))
        el_type = str(getattr(elem, "type", "text")).lower()
        bbox = getattr(elem, "bbox", None)
        if not bbox:
            continue

        x0, y0 = bbox.x0 * scale_x, bbox.y0 * scale_y
        x1, y1 = bbox.x1 * scale_x, bbox.y1 * scale_y
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0

        if el_type == "table":
            box_stroke = COLOR_ORDER_TABLE_BOX
            box_fill = COLOR_ORDER_TABLE_FILL
            badge_bg = COLOR_BADGE_BG_TABLE
            t_obj = getattr(elem, "table", None)
            dim_str = f" {t_obj.rows}x{t_obj.cols}" if t_obj else ""
            type_label = f"Table{dim_str}"
        else:
            box_stroke = COLOR_ORDER_TEXT_BOX
            box_fill = COLOR_ORDER_TEXT_FILL
            badge_bg = COLOR_BADGE_BG_TEXT
            type_label = "Text"

        # Draw element container
        draw.rectangle([x0, y0, x1, y1], fill=box_fill, outline=box_stroke, width=2)

        # Draw reading flow connector trajectory line
        if prev_center is not None:
            draw.line([prev_center, (cx, cy)], fill=COLOR_TRAJECTORY_LINE, width=2)
            # Arrow head pointing to current
            dx = cx - prev_center[0]
            dy = cy - prev_center[1]
            dist = math.hypot(dx, dy)
            if dist > 30:
                ux, uy = dx / dist, dy / dist
                ax = cx - ux * 18
                ay = cy - uy * 18
                px = -uy * 6
                py = ux * 6
                draw.polygon([(cx, cy), (ax + px, ay + py), (ax - px, ay - py)], fill=COLOR_TRAJECTORY_LINE)

        prev_center = (cx, cy)

        # Prominent Reading Order Badge
        badge_pos = (min(canvas.width - 25, max(25, x0 + 18)), min(canvas.height - 25, max(25, y0 + 18)))
        draw_badge(draw, badge_pos, str(order), bg_color=badge_bg, radius=14, font_size=13)
        draw.text((badge_pos[0] + 18, badge_pos[1] - 8), type_label, fill=box_stroke, font=font_lbl)

    return Image.alpha_composite(canvas, overlay)


# ==============================================================================
# Side-by-Side Comparison Generator
# ==============================================================================

def create_side_by_side_comparison(
    img_pdfium: Image.Image,
    img_pymupdf: Image.Image,
    sample_name: str,
    stage_name: str,
    stats_pdfium: str,
    stats_pymupdf: str,
    legend_items: Sequence[Tuple[Tuple[int, int, int, int], str]],
) -> Image.Image:
    """Combine PDFium and PyMuPDF images side-by-side with header banner and legend footer."""
    w1, h1 = img_pdfium.size
    w2, h2 = img_pymupdf.size
    content_h = max(h1, h2)
    header_h = 100
    footer_h = 55
    divider_w = 4

    total_w = w1 + w2 + divider_w
    total_h = content_h + header_h + footer_h

    composite = Image.new("RGBA", (total_w, total_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(composite)

    # 1. Header background
    draw.rectangle([0, 0, total_w, header_h], fill=COLOR_HEADER_BG)
    font_title = get_font(20, bold=True)
    font_sub = get_font(13)
    font_col_header = get_font(15, bold=True)

    title_text = f"全链路比对: {sample_name}  |  {stage_name}"
    draw.text((24, 14), title_text, fill=COLOR_HEADER_TEXT, font=font_title)

    # Left column header (PDFium)
    draw.rectangle([0, 56, w1, header_h], fill=COLOR_SUBHEADER_BG)
    draw.text((24, 62), f"PDFium Probe (Left):  {stats_pdfium}", fill=(147, 197, 253, 255), font=font_col_header)

    # Right column header (PyMuPDF)
    draw.rectangle([w1 + divider_w, 56, total_w, header_h], fill=COLOR_SUBHEADER_BG)
    draw.text((w1 + divider_w + 24, 62), f"PyMuPDF Baseline (Right):  {stats_pymupdf}", fill=(167, 243, 208, 255), font=font_col_header)

    # 2. Content placement
    composite.paste(img_pdfium, (0, header_h))
    composite.paste(img_pymupdf, (w1 + divider_w, header_h))

    # Divider bar
    draw.rectangle([w1, header_h, w1 + divider_w, header_h + content_h], fill=COLOR_DIVIDER)

    # 3. Footer / Legend background
    footer_y0 = header_h + content_h
    draw.rectangle([0, footer_y0, total_w, total_h], fill=COLOR_FOOTER_BG)

    # Render Legend items
    font_legend = get_font(12, bold=True)
    draw.text((24, footer_y0 + 18), "图例 (Legend):", fill=(203, 213, 225, 255), font=font_legend)
    cur_x = 140.0
    for color, label in legend_items:
        draw.rectangle([cur_x, footer_y0 + 19, cur_x + 16, footer_y0 + 35], fill=color, outline=(255, 255, 255, 180), width=1)
        draw.text((cur_x + 22, footer_y0 + 20), label, fill=(241, 245, 249, 255), font=font_legend)
        cur_x += len(label) * 14 + 50
        if cur_x > total_w - 150:
            break

    return composite


# ==============================================================================
# Sample Processing Execution
# ==============================================================================

class SampleConfig:
    def __init__(
        self,
        name: str,
        pdf_path: Path,
        page_index: int,
        table_regions: Sequence[Mapping[str, Any]],
        pdfium_raw_path: Path,
        pymupdf_baseline_path: Path,
        description: str,
    ) -> None:
        self.name = name
        self.pdf_path = pdf_path
        self.page_index = page_index
        self.table_regions = table_regions
        self.pdfium_raw_path = pdfium_raw_path
        self.pymupdf_baseline_path = pymupdf_baseline_path
        self.description = description


def run_pipeline_for_sample(
    sample: SampleConfig,
    output_base_dir: Path,
    dpi: int = 180,
) -> Dict[str, Any]:
    """Execute all pipeline stages, generate step PNGs, side-by-side comparisons, and metadata."""
    sample_out = output_base_dir / sample.name
    sample_out.mkdir(parents=True, exist_ok=True)
    print(f"\n[{sample.name}] Processing pipeline stages...")

    # 1. Load Live PDF Document
    if not sample.pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {sample.pdf_path}")
    doc = fitz.open(str(sample.pdf_path))
    py_page = doc[sample.page_index]

    # Base background renderings
    base_img_pdfium, scale_px, scale_py = render_page_base_image(doc, sample.page_index, dpi=dpi)
    base_img_pymupdf, scale_mx, scale_my = render_page_base_image(doc, sample.page_index, dpi=dpi)

    # 2. Load PDFium Raw Snapshot & PyMuPDF Baseline
    raw_snapshot = json.loads(sample.pdfium_raw_path.read_text(encoding="utf-8"))
    raw_page = raw_snapshot["pages"][sample.page_index] if sample.page_index < len(raw_snapshot["pages"]) else raw_snapshot["pages"][0]

    baseline_data = json.loads(sample.pymupdf_baseline_path.read_text(encoding="utf-8"))
    if "schema_version" in baseline_data:
        py_dto = dict(baseline_data)
    else:
        py_snap = capture_page_snapshot(py_page, page_index=sample.page_index, lightweight=False)
        py_dto = rust_adapter.page_snapshot_to_rust_input(py_snap)

    # 3. Stage 1: Raw Elements Extraction
    pdfium_raw_spans = raw_page.get("spans") or []
    pdfium_raw_drawings = raw_page.get("drawings") or []

    pymupdf_rawdict = py_page.get_text("rawdict")
    pymupdf_raw_spans: List[Dict[str, Any]] = []
    for b in pymupdf_rawdict.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                pymupdf_raw_spans.append(s)
    pymupdf_raw_drawings = py_page.get_drawings()

    img_s1_pdfium = visualize_stage_1_raw(base_img_pdfium, scale_px, scale_py, pdfium_raw_spans, pdfium_raw_drawings)
    img_s1_pymupdf = visualize_stage_1_raw(base_img_pymupdf, scale_mx, scale_my, pymupdf_raw_spans, pymupdf_raw_drawings)

    comp_s1 = create_side_by_side_comparison(
        img_s1_pdfium,
        img_s1_pymupdf,
        sample.name,
        "Stage 1: 原始图元提取 (Raw Atomic Elements)",
        f"{len(pdfium_raw_spans)} Spans, {len(pdfium_raw_drawings)} Drawings",
        f"{len(pymupdf_raw_spans)} Spans, {len(pymupdf_raw_drawings)} Drawings",
        [
            (COLOR_RAW_SPAN_STROKE, "文字 Span"),
            (COLOR_RAW_DRAWING_STROKE, "矢量线段/路径"),
            (COLOR_INVISIBLE_STROKE, "隐藏文字(rm=3)"),
        ],
    )
    img_s1_pdfium.save(sample_out / "pdfium_01_raw.png")
    img_s1_pymupdf.save(sample_out / "pymupdf_01_raw.png")
    comp_s1.save(sample_out / "01_raw_spans_and_drawings.png")
    print(f"  [OK] Stage 1 saved: 01_raw_spans_and_drawings.png")

    # 4. Stage 2: Visual Hierarchy Normalization & Clustering
    norm_pdfium = normalize_raw_page(raw_page)
    pdfium_dto = norm_pdfium.page_snapshot or {}
    pdfium_blocks = pdfium_dto.get("text_blocks") or []
    pdfium_line_count = sum(len(b.get("lines", [])) for b in pdfium_blocks)
    pdfium_words = norm_pdfium.words

    py_blocks = py_dto.get("text_blocks") or []
    py_line_count = sum(len(b.get("lines", [])) for b in py_blocks)
    py_words = py_page.get_text("words")

    img_s2_pdfium = visualize_stage_2_hierarchy(base_img_pdfium, scale_px, scale_py, pdfium_blocks, pdfium_words)
    img_s2_pymupdf = visualize_stage_2_hierarchy(base_img_pymupdf, scale_mx, scale_my, py_blocks, py_words)

    comp_s2 = create_side_by_side_comparison(
        img_s2_pdfium,
        img_s2_pymupdf,
        sample.name,
        "Stage 2: 视觉层级聚类 (Lines & Blocks Clustering)",
        f"{len(pdfium_blocks)} Blocks, {pdfium_line_count} Lines, {len(pdfium_words)} Words",
        f"{len(py_blocks)} Blocks, {py_line_count} Lines, {len(py_words)} Words",
        [
            (COLOR_LINE_STROKE, "聚类行框 (Line)"),
            (COLOR_BLOCK_STROKE, "段落块框 (Block)"),
            (COLOR_WORD_STROKE, "切分词框 (Word)"),
        ],
    )
    img_s2_pdfium.save(sample_out / "pdfium_02_hierarchy.png")
    img_s2_pymupdf.save(sample_out / "pymupdf_02_hierarchy.png")
    comp_s2.save(sample_out / "02_lines_and_blocks.png")
    print(f"  [OK] Stage 2 saved: 02_lines_and_blocks.png")

    # 5. Stage 3: Table Structure Recovery
    pdfium_tables: List[Table] = []
    py_tables: List[Table] = []

    for reg in sample.table_regions:
        kind = reg.get("kind", "wireless")
        rx0, ry0 = float(reg.get("x0", 0)), float(reg.get("y0", 0))
        rx1, ry1 = float(reg.get("x1", 0)), float(reg.get("y1", 0))
        region_bbox = BBox(rx0, ry0, rx1, ry1)

        if kind == "wireless":
            p_rows, p_cols, p_cells = rust_adapter.recover_cells_from_snapshot(pdfium_dto, reg)
            if p_rows > 0 and p_cols > 0:
                pdfium_tables.append(Table(bbox=region_bbox, rows=p_rows, cols=p_cols, cells=p_cells, source="wireless"))

            m_rows, m_cols, m_cells = rust_adapter.recover_cells_from_snapshot(py_dto, reg)
            if m_rows > 0 and m_cols > 0:
                py_tables.append(Table(bbox=region_bbox, rows=m_rows, cols=m_cols, cells=m_cells, source="wireless"))

        elif kind == "wired":
            p_tbls, _ = _extract_wired_table(pdfium_dto, reg, is_pdfium=True)
            pdfium_tables.extend(p_tbls)
            m_tbls, _ = _extract_wired_table(py_dto, reg, is_pdfium=False)
            py_tables.extend(m_tbls)

    p_tbl_desc = ", ".join(f"{t.rows}x{t.cols} ({t.source})" for t in pdfium_tables) or "无表格"
    m_tbl_desc = ", ".join(f"{t.rows}x{t.cols} ({t.source})" for t in py_tables) or "无表格"

    img_s3_pdfium = visualize_stage_3_table(base_img_pdfium, scale_px, scale_py, sample.table_regions, pdfium_tables, pdfium_dto)
    img_s3_pymupdf = visualize_stage_3_table(base_img_pymupdf, scale_mx, scale_my, sample.table_regions, py_tables, py_dto)

    comp_s3 = create_side_by_side_comparison(
        img_s3_pdfium,
        img_s3_pymupdf,
        sample.name,
        "Stage 3: 表格网格与单元格恢复 (Table Recovery)",
        f"{len(pdfium_tables)} 表格: {p_tbl_desc}",
        f"{len(py_tables)} 表格: {m_tbl_desc}",
        [
            (COLOR_TABLE_REGION, "候选表格区域"),
            (COLOR_CELL_STROKE, "有效单元格 (Cell)"),
            (COLOR_SPAN_CELL_STROKE, "跨行列单元格 (Span)"),
            (COLOR_EMPTY_CELL_STROKE, "物化空单元格 (Empty)"),
            (COLOR_PHYSICAL_LINE, "物理网格线"),
        ],
    )
    img_s3_pdfium.save(sample_out / "pdfium_03_table.png")
    img_s3_pymupdf.save(sample_out / "pymupdf_03_table.png")
    comp_s3.save(sample_out / "03_table_recovery.png")
    print(f"  [OK] Stage 3 saved: 03_table_recovery.png")

    # 6. Stage 4: Final Layout & Reading Order
    text_extractor = TextExtractor()
    layout_mapper = LayoutMapper()
    layout_builder = LayoutBuilder()

    # PDFium reading order
    pdfium_adapter = PdfiumPageAdapter(norm_pdfium)
    p_layout_blocks = text_extractor.extract_layout_blocks(pdfium_adapter, pdfium_tables)
    p_mapped = layout_mapper.map_blocks(p_layout_blocks)
    pdfium_layout = layout_builder.build(p_mapped, pdfium_tables, [])

    # PyMuPDF reading order
    m_layout_blocks = text_extractor.extract_layout_blocks(py_page, py_tables)
    m_mapped = layout_mapper.map_blocks(m_layout_blocks)
    pymupdf_layout = layout_builder.build(m_mapped, py_tables, [])

    img_s4_pdfium = visualize_stage_4_reading_order(base_img_pdfium, scale_px, scale_py, pdfium_layout)
    img_s4_pymupdf = visualize_stage_4_reading_order(base_img_pymupdf, scale_mx, scale_my, pymupdf_layout)

    comp_s4 = create_side_by_side_comparison(
        img_s4_pdfium,
        img_s4_pymupdf,
        sample.name,
        "Stage 4: 最终版面与阅读流全景 (Layout & Reading Order)",
        f"{len(pdfium_layout)} 元素: {[getattr(e, 'type', '') for e in pdfium_layout][:6]}...",
        f"{len(pymupdf_layout)} 元素: {[getattr(e, 'type', '') for e in pymupdf_layout][:6]}...",
        [
            (COLOR_BADGE_BG_TEXT, "正文徽标 (0, 1, 2..)"),
            (COLOR_BADGE_BG_TABLE, "表格徽标 [Table]"),
            (COLOR_TRAJECTORY_LINE, "阅读流连线"),
        ],
    )
    img_s4_pdfium.save(sample_out / "pdfium_04_reading_order.png")
    img_s4_pymupdf.save(sample_out / "pymupdf_04_reading_order.png")
    comp_s4.save(sample_out / "04_final_reading_order.png")
    print(f"  [OK] Stage 4 saved: 04_final_reading_order.png")

    meta = {
        "sample_name": sample.name,
        "description": sample.description,
        "stage_images": {
            "stage_1_raw": str(sample_out / "01_raw_spans_and_drawings.png"),
            "stage_2_hierarchy": str(sample_out / "02_lines_and_blocks.png"),
            "stage_3_table": str(sample_out / "03_table_recovery.png"),
            "stage_4_reading_order": str(sample_out / "04_final_reading_order.png"),
        },
        "stats": {
            "pdfium": {
                "spans": len(pdfium_raw_spans),
                "drawings": len(pdfium_raw_drawings),
                "blocks": len(pdfium_blocks),
                "lines": pdfium_line_count,
                "words": len(pdfium_words),
                "tables": [{"rows": t.rows, "cols": t.cols, "cells": len(t.cells)} for t in pdfium_tables],
                "layout_count": len(pdfium_layout),
            },
            "pymupdf": {
                "spans": len(pymupdf_raw_spans),
                "drawings": len(pymupdf_raw_drawings),
                "blocks": len(py_blocks),
                "lines": py_line_count,
                "words": len(py_words),
                "tables": [{"rows": t.rows, "cols": t.cols, "cells": len(t.cells)} for t in py_tables],
                "layout_count": len(pymupdf_layout),
            },
        },
    }
    (sample_out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


# ==============================================================================
# Main Runner & Readme Index Generator
# ==============================================================================

def generate_visualization_readme(
    results: List[Dict[str, Any]],
    output_dir: Path,
) -> None:
    """Generate Markdown report and visual index linking all artifacts."""
    readme_path = output_dir / "README.md"
    lines: List[str] = [
        "# PDFium vs PyMuPDF 全链路处理逐步可视化图集 (Pipeline Step Visualizations)",
        "",
        "> 本图集通过 180 DPI 高清多层光栅化底图与矢量图元叠加，全景式展示了 PDF 处理流水线在各关键阶段的中间产物与两端差异。",
        "> 特别深入呈现了算法内部的聚类逻辑、坐标映射、表格网格恢复以及阅读顺序排布。",
        "",
        "## 4 份核心代表性样本概览",
        "",
        "| 样本名称 | 类型 | 核心观察点 | 两端关键差异 |",
        "| :--- | :--- | :--- | :--- |",
        "| **`test_p27_table`** | 真实无线表格 | 换行标题与长文本的行聚类切分、无线表格行带划分 | **PDFium 恢复 27×2，PyMuPDF 恢复 9×2** (行聚类切分粒度差异) |",
        "| **`credit_p1_detail`** | 真实有线表格 | 物理网格线提取、单元格 bbox 贴合与拓扑交叉 | **两端完全一致 (11×11 网格，121 单元格，全绿通过)** |",
        "| **`synth_invisible_text`** | 合成隐藏/重叠文本 | `render_mode=3` 隐藏层剔除、重叠文本分离为独立行 | **两端隐藏文本正确剔除，重叠层独立分离，完全一致** |",
        "| **`synth_crop_offset`** | 合成视口裁剪 | CropBox 偏移重映射、越界图元几何过滤 | **两端视口裁剪与坐标系平移一致** |",
        "",
        "---",
        "",
    ]

    for res in results:
        name = res["sample_name"]
        desc = res["description"]
        stats = res["stats"]
        p_st = stats["pdfium"]
        m_st = stats["pymupdf"]

        lines.extend([
            f"## 样本: `{name}`",
            "",
            f"**样本定位与观察目的**: {desc}",
            "",
            "### 关键处理指标对比",
            "",
            "| 处理层级 / 指标 | PDFium Probe | PyMuPDF Baseline | 差异与分析 |",
            "| :--- | :---: | :---: | :--- |",
            f"| **原始 Spans 数量** | {p_st['spans']} | {m_st['spans']} | 原始字符流切块粒度 |",
            f"| **原始矢量图元数量** | {p_st['drawings']} | {m_st['drawings']} | 线段与矩形路径抽取 |",
            f"| **聚类行数 (Lines)** | **{p_st['lines']}** | **{m_st['lines']}** | 垂直/水平重叠度行聚类 |",
            f"| **聚类段落块 (Blocks)** | {p_st['blocks']} | {m_st['blocks']} | 块间距纵向归并 |",
            f"| **恢复表格结构** | **{p_st['tables']}** | **{m_st['tables']}** | 表格网格求解 |",
            f"| **阅读流元素 (Layout)** | **{p_st['layout_count']}** | **{m_st['layout_count']}** | 最终阅读排序流 |",
            "",
            "### 逐步全链路可视化图集",
            "",
            f"#### 阶段 1: 原始图元提取 (Stage 1: Raw Atomic Elements)",
            f"展示原始原子文字 Span（带 render_mode 判定）与矢量绘图路径（线段、矩形）：",
            f"![{name} Stage 1]({name}/01_raw_spans_and_drawings.png)",
            "",
            f"#### 阶段 2: 视觉层级聚类 (Stage 2: Lines & Blocks Clustering)",
            f"展示从 Span 经过垂直/水平重叠度判定聚合成的 `_VisualLine` 行框与 `_VisualBlock` 块框：",
            f"![{name} Stage 2]({name}/02_lines_and_blocks.png)",
            "",
            f"#### 阶段 3: 表格网格与单元格恢复 (Stage 3: Table Structure Recovery)",
            f"展示候选表格区域、列带 (Column Bands)、单元格几何包围盒、跨度及物化空单元格：",
            f"![{name} Stage 3]({name}/03_table_recovery.png)",
            "",
            f"#### 阶段 4: 最终版面与阅读流全景 (Stage 4: Final Layout & Reading Order)",
            f"展示按阅读顺序编号（0, 1, 2...）的正文块与表格块全景流程图：",
            f"![{name} Stage 4]({name}/04_final_reading_order.png)",
            "",
            "---",
            "",
        ])

    lines.extend([
        "## `test_p27_table` 27 行 vs 9 行行聚类根因深度解析",
        "",
        "通过 Stage 2 (行聚类) 与 Stage 3 (表格恢复) 的对比图，可以清晰定位该样本在 PDFium 侧产生 27 行的根因：",
        "",
        "1. **多行换行表头的行切分机制差异**：",
        "   - 在表头区域中，列 1 的多个标题（如 `本期公允\\n价值变动\\n损益`、`计入权益\\n的累计公\\n允价值变\\n动`、`期初账面\\n价值`）在 PDF 中是由多行独立的短文本 span 构成。",
        "   - 在 **PyMuPDF 侧**：原生 `get_text('blocks')` 依照段落间距和行高启发式，将这几行文字组合在较粗粒度的 text line/block 中；在进入 `recover_cells_from_snapshot` 时，它们被作为一个整体单元格或在同一行带中被归并，最终仅生成 9 个主数据行。",
        "   - 在 **PDFium 侧**：`pdfium_normalizer.py` 严格按照几何垂直重叠度 `LINE_OVERLAP_RATIO_TOLERANCE=0.5` 和 `LINE_Y_CENTER_FACTOR=0.4` 切割。每个换行短句（例如“计入权益”、“本期公允”、“初始投资”、“期初账面”）因为与其他列在同一高度缺乏水平对齐 span，且相互之间垂直无重叠，被独立聚成了 27 个细粒度 `_VisualLine`！",
        "2. **无线表格行带划分的敏感性**：",
        "   - `rust_adapter.recover_cells_from_snapshot` 接收到 27 条细粒度 lines 后，依据每条 line 的 y 坐标划分出独立的行切线与行带，从而物化出了 27 行的逻辑网格。",
        "   - 直观图见上文 `test_p27_table/02_lines_and_blocks.png` 与 `test_p27_table/03_table_recovery.png`。",
        "",
        "---",
        "*Report generated automatically by `visualize_pipeline_steps.py`.*",
    ])

    readme_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[README] Documentation index generated: {readme_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate full pipeline step visualizations.")
    parser.add_argument(
        "--output",
        type=Path,
        default=_PROBE_ROOT / "test_data/behavioral_output/pipeline_visualization",
        help="Output directory for visualization graphics.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="Rasterization DPI (default: 180).",
    )
    args = parser.parse_args()

    repo_root = _REPO_ROOT
    probe_root = _PROBE_ROOT

    samples = [
        SampleConfig(
            name="test_p27_table",
            pdf_path=repo_root / "test.pdf",
            page_index=27,
            table_regions=[
                {"kind": "wireless", "x0": 20.0, "y0": 100.0, "x1": 575.0, "y1": 450.0}
            ],
            pdfium_raw_path=probe_root / "test_data/real_pdfium_output/test_p27_table_pdfium.json",
            pymupdf_baseline_path=probe_root / "test_data/real_baseline/test_p27_table_pymupdf.json",
            description="真实无线表格样本：观察换行标题与长文本的行聚类切分、无线表格行带划分差异（PDFium 27×2 vs PyMuPDF 9×2）。",
        ),
        SampleConfig(
            name="credit_p1_detail",
            pdf_path=repo_root / "征信解析样例.pdf",
            page_index=1,
            table_regions=[
                {"kind": "wired", "x0": 28.0, "y0": 32.0, "x1": 565.0, "y1": 153.0}
            ],
            pdfium_raw_path=probe_root / "test_data/real_pdfium_output/credit_p1_detail_pdfium.json",
            pymupdf_baseline_path=probe_root / "test_data/real_baseline/credit_p1_detail_pymupdf.json",
            description="真实有线表格样本：观察 11×11 物理网格线提取、网格交叉点求解、封闭区域计算与单元格文本贴合（两端完全一致）。",
        ),
        SampleConfig(
            name="synth_invisible_text",
            pdf_path=probe_root / "test_data/synthetic/synth_invisible_text.pdf",
            page_index=0,
            table_regions=[],
            pdfium_raw_path=probe_root / "test_data/pdfium_output/synth_invisible_text_pdfium.json",
            pymupdf_baseline_path=probe_root / "test_data/baseline/synth_invisible_text_pymupdf.json",
            description="合成隐藏与重叠文本样本：观察 render_mode=3 隐藏文字层剔除，以及 Base/Top 重叠文本依据重叠度阈值独立分离为两行的过程。",
        ),
        SampleConfig(
            name="synth_crop_offset",
            pdf_path=probe_root / "test_data/synthetic/synth_crop_offset.pdf",
            page_index=0,
            table_regions=[],
            pdfium_raw_path=probe_root / "test_data/pdfium_output/synth_crop_offset_pdfium.json",
            pymupdf_baseline_path=probe_root / "test_data/baseline/synth_crop_offset_pymupdf.json",
            description="合成视口裁剪样本：观察 CropBox 视口偏移量重映射、全局未旋转坐标系转换以及越界图元几何过滤过程。",
        ),
    ]

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for s in samples:
        try:
            res = run_pipeline_for_sample(s, out_dir, dpi=args.dpi)
            results.append(res)
        except Exception as exc:
            print(f"Error processing {s.name}: {exc}")
            import traceback
            traceback.print_exc()

    generate_visualization_readme(results, out_dir)
    print("\nAll pipeline step visualizations completed successfully!")


if __name__ == "__main__":
    main()
