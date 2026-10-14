"""Process-wide synchronization entry point for PyMuPDF native calls.

PyMuPDF / MuPDF is not thread-safe. Multiple threads in the same process
must not execute native operations simultaneously. This module provides a single
process-wide RLock to serialize native library calls while allowing all
pure-Python processing (table geometry, text layout, template matching, ML inference)
to execute concurrently.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")

# Process-wide re-entrant lock protecting all underlying MuPDF C library operations.
pymupdf_lock = threading.RLock()


@contextmanager
def synchronized_pymupdf() -> Iterator[None]:
    """Context manager acquiring the process-wide PyMuPDF lock."""
    with pymupdf_lock:
        yield


def sync_pymupdf(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator wrapping a function call with the process-wide PyMuPDF lock."""
    def wrapper(*args: Any, **kwargs: Any) -> T:
        with pymupdf_lock:
            return func(*args, **kwargs)
    return wrapper
