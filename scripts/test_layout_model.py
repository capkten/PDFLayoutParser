"""
Benchmark PP-DocLayout-M on PDFs with visualization and CPU timing.
"""

from __future__ import annotations

import argparse
import json
import os
import site
import sys
from pathlib import Path
from time import perf_counter

import cv2
import fitz  # PyMuPDF
import numpy as np
import paddle
import yaml
from paddle.inference import Config, create_predictor

from pdflayoutparser.benchmark_utils import extract_model_profile
from pdflayoutparser.benchmark_utils import resolve_model_dir
from pdflayoutparser.benchmark_utils import summarize_timings
from pdflayoutparser.layout_model_utils import (
    bbox_from_detection_row,
    save_image_with_fallback,
)
from pdflayoutparser.yolo_layout_utils import (
    YOLO_LAYOUT_LABELS,
    postprocess_yolo_layout,
    preprocess_yolo_image,
)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "models", "PP-DocLayout-M_infer")
PDFS = [
    os.path.join(os.path.dirname(__file__), "..", "152590_20230428_N7ZK_0.pdf"),
    os.path.join(os.path.dirname(__file__), "..", "万马股份2024财报.pdf"),
]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "layout_test_benchmark")
DPI = 200
SCORE_THRESHOLD = 0.5
NMS_THRESHOLD = 0.5
TARGET_SIZE = (640, 640)
MODEL_PROFILE = {
    "target_size": TARGET_SIZE,
    "keep_ratio": False,
    "normalize": "imagenet",
    "mean": (0.485, 0.456, 0.406),
    "std": (0.229, 0.224, 0.225),
    "label_list": [],
}

DEFAULT_LABEL_LIST = [
    "paragraph_title",
    "image",
    "text",
    "number",
    "abstract",
    "content",
    "figure_title",
    "formula",
    "table",
    "table_title",
    "reference",
    "doc_title",
    "footnote",
    "header",
    "algorithm",
    "footer",
    "seal",
    "chart_title",
    "chart",
    "formula_number",
    "header_image",
    "footer_image",
    "aside_text",
]

PLUS_MODEL_NAMES = {"PP-DocLayout_plus-L"}
YOLO_MODEL_NAME = "layoutanalysis"
YOLO_MODEL_FILE = "layoutanalysis.onnx"
YOLO_SCORE_THRESHOLD = 0.25
YOLO_IOU_THRESHOLD = 0.5

COLORS = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (255, 0, 255),
    (0, 255, 255),
    (128, 0, 0),
    (0, 128, 0),
    (0, 0, 128),
    (128, 128, 0),
    (128, 0, 128),
    (0, 128, 128),
    (64, 0, 0),
    (0, 64, 0),
    (0, 0, 64),
    (192, 192, 0),
    (192, 0, 192),
    (0, 192, 192),
    (64, 64, 64),
    (192, 64, 64),
    (64, 192, 64),
    (64, 64, 192),
    (128, 64, 192),
]


def render_page_image(page: fitz.Page, dpi: int = 200) -> np.ndarray:
    """Render one PDF page to a BGR numpy array."""
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    elif pix.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img


def load_model_profile(model_dir: str) -> dict:
    """Load preprocessing metadata from the exported model config."""
    onnx_model_path = Path(model_dir) / YOLO_MODEL_FILE
    onnx_config_path = Path(model_dir) / "model_config.json"
    if onnx_model_path.exists() and onnx_config_path.exists():
        try:
            with open(onnx_config_path, "r", encoding="utf-8") as f:
                model_config = json.load(f) or {}
        except Exception:
            model_config = {}
        return {
            "model_name": str(model_config.get("modelId") or YOLO_MODEL_NAME),
            "draw_threshold": YOLO_SCORE_THRESHOLD,
            "layout_nms": None,
            "layout_unclip_ratio": None,
            "layout_merge_bboxes_mode": None,
            "target_size": (640, 640),
            "keep_ratio": False,
            "normalize": "yolo01",
            "mean": (0.0, 0.0, 0.0),
            "std": (1.0, 1.0, 1.0),
            "label_list": YOLO_LAYOUT_LABELS,
            "onnx_model_path": str(onnx_model_path),
        }

    config_path = Path(model_dir) / "inference.yml"
    if not config_path.exists():
        return {
            "model_name": None,
            "draw_threshold": 0.5,
            "layout_nms": None,
            "layout_unclip_ratio": None,
            "layout_merge_bboxes_mode": None,
            "target_size": (640, 640),
            "keep_ratio": False,
            "normalize": "imagenet",
            "mean": (0.485, 0.456, 0.406),
            "std": (0.229, 0.224, 0.225),
            "label_list": DEFAULT_LABEL_LIST,
            "onnx_model_path": None,
        }

    with open(config_path, "r", encoding="utf-8") as f:
        model_config = yaml.safe_load(f) or {}
    profile = extract_model_profile(model_config)
    if not profile.get("label_list"):
        profile["label_list"] = DEFAULT_LABEL_LIST
    profile["onnx_model_path"] = None
    return profile


def preprocess(
    img: np.ndarray,
    target_size: tuple[int, int] = (640, 640),
    normalize: str = "imagenet",
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406),
    std: tuple[float, float, float] = (0.229, 0.224, 0.225),
):
    """Resize, normalize, and transpose image for model input."""
    h, w = img.shape[:2]
    th, tw = target_size
    resized = cv2.resize(img, (tw, th), interpolation=cv2.INTER_LINEAR)
    img_f = resized.astype(np.float32)
    if normalize == "imagenet":
        img_f = img_f / 255.0
        img_f = (img_f - np.array(mean, dtype=np.float32)) / np.array(std, dtype=np.float32)
    elif normalize in {"none", None}:
        pass
    else:
        raise ValueError(f"Unsupported normalize mode: {normalize}")
    img_f = img_f.transpose(2, 0, 1)
    img_f = np.expand_dims(img_f, axis=0).astype(np.float32)
    scale_factor = np.array([[th / h, tw / w]], dtype=np.float32)
    im_shape = np.array([[th, tw]], dtype=np.float32)
    return img_f, scale_factor, im_shape, (h, w)


def create_onnx_model(model_path: str):
    """Create an ONNX Runtime session for YOLO-style layout detection."""
    import onnxruntime as ort

    session = ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )
    print(f"  Input names: {[item.name for item in session.get_inputs()]}")
    print(f"  Output names: {[item.name for item in session.get_outputs()]}")
    for item in session.get_inputs():
        print(f"    Input '{item.name}': shape={item.shape}, dtype={item.type}")
    for item in session.get_outputs():
        print(f"    Output '{item.name}': shape={item.shape}, dtype={item.type}")
    return session


def create_model(model_dir: str):
    """Create PaddlePaddle inference predictor."""
    model_file = os.path.join(model_dir, "inference.json")
    params_file = os.path.join(model_dir, "inference.pdiparams")
    config = Config(model_file, params_file)
    config.disable_gpu()
    config.set_cpu_math_library_num_threads(os.cpu_count() or 1)
    config.switch_use_feed_fetch_ops(False)
    predictor = create_predictor(config)
    print(f"  Input names: {predictor.get_input_names()}")
    print(f"  Output names: {predictor.get_output_names()}")
    for name in predictor.get_input_names():
        handle = predictor.get_input_handle(name)
        print(f"    Input '{name}': shape={handle.shape()}, dtype={handle.type()}")
    return predictor


def create_paddlex_model(model_name: str, model_dir: str):
    """Create the official PaddleX layout predictor."""
    os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
    if "modelscope" not in sys.modules:
        import types

        sys.modules["modelscope"] = types.ModuleType("modelscope")
    import paddlex

    model = paddlex.create_model(model_name, model_dir=model_dir)
    return model


def run_inference(predictor, img_np, scale_factor, im_shape):
    """Run inference and return raw output tensors."""
    for name in predictor.get_input_names():
        handle = predictor.get_input_handle(name)
        lower = name.lower()
        if "image" in lower or name == "image":
            handle.copy_from_cpu(img_np)
        elif "im_shape" in lower:
            handle.copy_from_cpu(im_shape)
        elif "scale" in lower or name == "scale_factor":
            handle.copy_from_cpu(scale_factor)

    predictor.run()

    results = {}
    for name in predictor.get_output_names():
        handle = predictor.get_output_handle(name)
        results[name] = handle.copy_to_cpu()
    return results


def run_onnx_inference(session, img_np):
    """Run ONNX inference and return the primary detection tensor."""
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img_np})
    return outputs[0]


def normalize_paddlex_boxes(boxes):
    """Convert PaddleX detection boxes to the local visualization schema."""
    detections = []
    for box in boxes:
        detections.append(
            {
                "class_id": int(box["cls_id"]),
                "label": str(box["label"]),
                "score": float(box["score"]),
                "bbox": [float(v) for v in box["coordinate"]],
            }
        )
    return detections


def postprocess(outputs, orig_h, orig_w, label_list, score_threshold=0.5):
    """Parse detection outputs and map boxes back to original image coordinates."""
    detections = []
    for name, data in outputs.items():
        if data.size == 0:
            continue
        print(f"  Output '{name}': shape={data.shape}, dtype={data.dtype}")
        if data.ndim >= 2 and data.shape[-1] >= 6:
            arr = data.reshape(-1, data.shape[-1])
            for det in arr:
                cls_id = int(det[0])
                score = float(det[1])
                if score < score_threshold:
                    continue
                x1, y1, x2, y2 = bbox_from_detection_row(
                    det,
                    image_size=(orig_w, orig_h),
                )
                label = label_list[cls_id] if cls_id < len(label_list) else f"class_{cls_id}"
                detections.append(
                    {
                        "class_id": cls_id,
                        "label": label,
                        "score": score,
                        "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    }
                )
    return detections


def draw_detections(img, detections):
    """Draw bounding boxes and labels on image."""
    result = img.copy()
    for det in detections:
        cls_id = det["class_id"]
        label = det["label"]
        score = det["score"]
        bbox = det.get("bbox") or det.get("coordinate")
        x1, y1, x2, y2 = [int(v) for v in bbox]
        color = COLORS[cls_id % len(COLORS)]
        cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
        text = f"{label}: {score:.2f}"
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(result, (x1, y1 - th - baseline - 4), (x1 + tw, y1), color, -1)
        cv2.putText(result, text, (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return result


def process_pdf(backend, pdf_path, run_dir, dpi=200, max_pages=0):
    """Process one PDF and return timing/output metadata."""
    pdf_name = Path(pdf_path).stem
    pdf_out_dir = Path(run_dir) / pdf_name
    pdf_out_dir.mkdir(parents=True, exist_ok=True)

    page_timings = []
    render_seconds = 0.0
    doc = fitz.open(pdf_path)
    try:
        page_limit = doc.page_count if max_pages <= 0 else min(doc.page_count, max_pages)
        for i in range(page_limit):
            page = doc.load_page(i)
            page_start = perf_counter()

            render_start = perf_counter()
            img = render_page_image(page, dpi=dpi)
            render_seconds += perf_counter() - render_start

            orig_h, orig_w = img.shape[:2]

            if backend["kind"] == "onnx":
                preprocess_start = perf_counter()
                img_np = preprocess_yolo_image(img, TARGET_SIZE)
                preprocess_seconds = perf_counter() - preprocess_start

                inference_start = perf_counter()
                output = run_onnx_inference(backend["session"], img_np)
                inference_seconds = perf_counter() - inference_start

                postprocess_start = perf_counter()
                detections = postprocess_yolo_layout(
                    output,
                    (orig_w, orig_h),
                    label_list=MODEL_PROFILE["label_list"],
                    confidence_threshold=SCORE_THRESHOLD,
                    iou_threshold=YOLO_IOU_THRESHOLD,
                    input_size=TARGET_SIZE[0],
                )
                postprocess_seconds = perf_counter() - postprocess_start
            elif backend["kind"] == "paddlex":
                preprocess_seconds = 0.0
                postprocess_seconds = 0.0
                inference_start = perf_counter()
                result = next(backend["model"].predict(img, threshold=SCORE_THRESHOLD))
                inference_seconds = perf_counter() - inference_start
                detections = normalize_paddlex_boxes(result["boxes"])
            else:
                preprocess_start = perf_counter()
                img_np, scale_factor, im_shape, (orig_h, orig_w) = preprocess(
                    img,
                    TARGET_SIZE,
                    normalize=MODEL_PROFILE["normalize"],
                    mean=MODEL_PROFILE["mean"],
                    std=MODEL_PROFILE["std"],
                )
                preprocess_seconds = perf_counter() - preprocess_start

                inference_start = perf_counter()
                outputs = run_inference(backend["predictor"], img_np, scale_factor, im_shape)
                inference_seconds = perf_counter() - inference_start

                postprocess_start = perf_counter()
                detections = postprocess(
                    outputs,
                    orig_h,
                    orig_w,
                    MODEL_PROFILE["label_list"],
                    SCORE_THRESHOLD,
                )
                postprocess_seconds = perf_counter() - postprocess_start

            draw_start = perf_counter()
            vis = draw_detections(img, detections)
            draw_seconds = perf_counter() - draw_start

            save_start = perf_counter()
            out_path = pdf_out_dir / f"page_{i + 1:03d}.jpg"
            save_mode = save_image_with_fallback(
                out_path,
                vis,
                cv2.imwrite,
                cv2.imencode,
                [cv2.IMWRITE_JPEG_QUALITY, 90],
            )
            save_seconds = perf_counter() - save_start

            json_path = pdf_out_dir / f"page_{i + 1:03d}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"page": i + 1, "detections": detections}, f, ensure_ascii=False, indent=2)

            total_seconds = perf_counter() - page_start
            page_timings.append(
                {
                    "page_index": i + 1,
                    "save_mode": save_mode,
                    "output_image": str(out_path),
                    "detections": len(detections),
                    "preprocess_seconds": preprocess_seconds,
                    "inference_seconds": inference_seconds,
                    "postprocess_seconds": postprocess_seconds,
                    "draw_seconds": draw_seconds,
                    "save_seconds": save_seconds,
                    "total_seconds": total_seconds,
                }
            )
            print(
                f"    page {i + 1:03d}/{page_limit:03d} "
                f"det={len(detections):3d} "
                f"infer={inference_seconds:.3f}s "
                f"page={total_seconds:.3f}s "
                f"save={save_mode}"
            )
    finally:
        doc.close()

    totals = {
        "render_seconds": render_seconds,
        "page_seconds": summarize_timings([item["total_seconds"] for item in page_timings]),
        "preprocess_seconds": summarize_timings([item["preprocess_seconds"] for item in page_timings]),
        "inference_seconds": summarize_timings([item["inference_seconds"] for item in page_timings]),
        "postprocess_seconds": summarize_timings([item["postprocess_seconds"] for item in page_timings]),
        "draw_seconds": summarize_timings([item["draw_seconds"] for item in page_timings]),
        "save_seconds": summarize_timings([item["save_seconds"] for item in page_timings]),
        "detections": summarize_timings([float(item["detections"]) for item in page_timings]),
    }

    return {
        "pdf_name": pdf_name,
        "pdf_path": str(pdf_path),
        "page_count": len(page_timings),
        "render_seconds": render_seconds,
        "pages": page_timings,
        "totals": totals,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Run PP-DocLayout-M CPU benchmark on PDFs.")
    parser.add_argument("--repeat", type=int, default=1, help="How many benchmark runs to repeat")
    parser.add_argument("--max-pages", type=int, default=0, help="Max pages per PDF; 0 means all pages")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output root directory")
    parser.add_argument("--model-dir", default=None, help="Override the Paddle model directory")
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Override the detection score threshold; defaults to the model config threshold",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    model_dir = resolve_model_dir(MODEL_DIR, args.model_dir)
    global MODEL_PROFILE, TARGET_SIZE, SCORE_THRESHOLD
    MODEL_PROFILE = load_model_profile(model_dir)
    TARGET_SIZE = tuple(MODEL_PROFILE["target_size"])
    if args.score_threshold is not None:
        SCORE_THRESHOLD = float(args.score_threshold)
    else:
        SCORE_THRESHOLD = float(MODEL_PROFILE.get("draw_threshold", SCORE_THRESHOLD))

    model_name = MODEL_PROFILE.get("model_name")
    if model_name == YOLO_MODEL_NAME:
        backend = {
            "kind": "onnx",
            "session": create_onnx_model(MODEL_PROFILE["onnx_model_path"]),
        }
    elif model_name in PLUS_MODEL_NAMES:
        backend = {
            "kind": "paddlex",
            "model": create_paddlex_model(model_name, model_dir),
        }
    else:
        backend = {
            "kind": "raw",
            "predictor": create_model(model_dir),
        }

    print("Model loaded successfully.\n")

    overall_start = perf_counter()
    run_summaries = []
    for run_index in range(1, args.repeat + 1):
        run_dir = output_root / f"run-{run_index:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"Starting run {run_index}/{args.repeat}: {run_dir}")
        run_start = perf_counter()
        pdf_summaries = []

        for pdf_path in PDFS:
            pdf_name = Path(pdf_path).stem
            print(f"  Processing: {pdf_name}")
            pdf_summary = process_pdf(
                backend,
                pdf_path,
                run_dir,
                dpi=DPI,
                max_pages=args.max_pages,
            )
            pdf_summaries.append(pdf_summary)
            print(
                f"  Summary {pdf_name}: pages={pdf_summary['page_count']} "
                f"render={pdf_summary['totals']['render_seconds']:.2f}s "
                f"infer_mean={pdf_summary['totals']['inference_seconds']['mean']:.3f}s "
                f"page_mean={pdf_summary['totals']['page_seconds']['mean']:.3f}s"
            )
        run_seconds = perf_counter() - run_start
        run_summaries.append(
            {
                "run_index": run_index,
                "run_dir": str(run_dir),
                "pdfs": pdf_summaries,
                "run_seconds": run_seconds,
            }
        )
        print(f"Completed run {run_index}/{args.repeat} in {run_seconds:.2f}s\n")

    total_seconds = perf_counter() - overall_start
    summary = {
        "model_dir": str(Path(model_dir)),
        "output_dir": str(output_root),
        "repeat": args.repeat,
        "max_pages": args.max_pages,
        "total_seconds": total_seconds,
        "run_seconds": summarize_timings([item["run_seconds"] for item in run_summaries]),
        "runs": run_summaries,
    }

    summary_path = output_root / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary["run_seconds"], ensure_ascii=False, indent=2))
    print(f"Wrote: {summary_path}")
    print(f"Done! Results saved to: {output_root}")


if __name__ == "__main__":
    main()
