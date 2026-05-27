"""Utilities for timing and aggregating benchmark runs."""

from __future__ import annotations

from pathlib import Path
from statistics import mean


def summarize_timings(values: list[float]) -> dict[str, float]:
    """Return basic summary statistics for timing values."""

    if not values:
        return {
            "count": 0,
            "total": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    return {
        "count": len(values),
        "total": float(sum(values)),
        "mean": float(mean(values)),
        "min": float(min(values)),
        "max": float(max(values)),
    }


def resolve_model_dir(default_dir: str | Path, override_dir: str | Path | None) -> str:
    """Resolve the model directory used by the benchmark script."""

    if override_dir:
        return str(Path(override_dir))
    return str(Path(default_dir))


def extract_model_profile(model_config: dict) -> dict:
    """Extract preprocessing and label metadata from a Paddle model config."""

    profile = {
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
        "label_list": [],
    }

    global_cfg = model_config.get("Global", {})
    if isinstance(global_cfg, dict):
        model_name = global_cfg.get("model_name")
        if model_name is not None:
            profile["model_name"] = str(model_name)

    draw_threshold = model_config.get("draw_threshold")
    if isinstance(draw_threshold, (int, float)):
        profile["draw_threshold"] = float(draw_threshold)

    for key in ("layout_nms", "layout_unclip_ratio", "layout_merge_bboxes_mode"):
        value = model_config.get(key)
        if value is not None:
            profile[key] = value

    for item in model_config.get("Preprocess", []):
        item_type = item.get("type")
        if item_type == "Resize":
            target_size = item.get("target_size") or profile["target_size"]
            if isinstance(target_size, list) and len(target_size) == 2:
                profile["target_size"] = (int(target_size[0]), int(target_size[1]))
            profile["keep_ratio"] = bool(item.get("keep_ratio", profile["keep_ratio"]))
        elif item_type == "NormalizeImage":
            profile["normalize"] = item.get("norm_type", profile["normalize"])
            mean = item.get("mean")
            std = item.get("std")
            if isinstance(mean, list) and len(mean) == 3:
                profile["mean"] = tuple(float(v) for v in mean)
            if isinstance(std, list) and len(std) == 3:
                profile["std"] = tuple(float(v) for v in std)

    label_list = model_config.get("label_list")
    if isinstance(label_list, list):
        profile["label_list"] = [str(label) for label in label_list]

    return profile
