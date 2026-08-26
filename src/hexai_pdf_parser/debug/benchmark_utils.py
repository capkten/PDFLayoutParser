"""Utilities for timing and aggregating benchmark runs."""

from __future__ import annotations

from statistics import mean


def summarize_timings(values):
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

