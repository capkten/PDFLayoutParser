"""Utilities for timing and aggregating benchmark runs."""

from __future__ import annotations

from statistics import mean
from typing import Sequence


SUPPORTED_RUST_MODES = ("python", "shadow", "rust")


def resolve_rust_mode(mode=None):
    """Resolve and validate the migration benchmark mode."""

    import os

    resolved = mode or os.environ.get("PDF_RUST_MODE", "python")
    if resolved not in SUPPORTED_RUST_MODES:
        raise ValueError("unknown mode: {!r}".format(resolved))
    return resolved


def percentile(values: Sequence[float], percent: float) -> float:
    """Return a linearly interpolated percentile, or zero for no values."""

    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percent / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_timings(values: Sequence[float]):
    """Return stable timing statistics, including interpolated percentiles."""

    if not values:
        return {
            "count": 0,
            "total": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }

    numbers = [float(value) for value in values]
    return {
        "count": len(numbers),
        "total": float(sum(numbers)),
        "mean": float(mean(numbers)),
        "min": min(numbers),
        "max": max(numbers),
        "p50": percentile(numbers, 50),
        "p95": percentile(numbers, 95),
        "p99": percentile(numbers, 99),
    }
