"""Helpers for running the Paddle layout model test script."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def bbox_from_detection_row(
    row: Any,
    image_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Convert a Paddle detection row into clipped image coordinates.

    The model used by ``scripts/test_layout_model.py`` already returns
    pixel-space coordinates for this export. If a caller passes normalized
    coordinates in the 0..1 range, they are expanded to image pixels.
    """

    width, height = image_size
    x0 = float(row[2])
    y0 = float(row[3])
    x1 = float(row[4])
    y1 = float(row[5])

    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 1.5:
        x0 *= width
        x1 *= width
        y0 *= height
        y1 *= height

    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))

    x0 = min(max(x0, 0.0), float(width))
    y0 = min(max(y0, 0.0), float(height))
    x1 = min(max(x1, 0.0), float(width))
    y1 = min(max(y1, 0.0), float(height))
    return x0, y0, x1, y1


def save_image_with_fallback(
    output_path: str | Path,
    image: Any,
    imwrite_fn: Callable[..., bool],
    imencode_fn: Callable[..., tuple[bool, Any]],
    imwrite_params: list[int] | None = None,
) -> str:
    """Save an image, falling back to encoded bytes when ``imwrite`` fails."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    params = imwrite_params or []
    if imwrite_fn(str(path), image, params):
        return "imwrite"

    suffix = path.suffix.lower() or ".png"
    success, encoded = imencode_fn(suffix, image)
    if not success:
        raise RuntimeError(f"Failed to encode image for {path}")

    if hasattr(encoded, "tobytes"):
        data = encoded.tobytes()
    else:
        data = bytes(encoded)

    path.write_bytes(data)
    return "imencode"
