"""Read-through caches for the PyMuPDF calls made during page processing."""

from __future__ import annotations

from typing import Any


def _freeze(value: Any) -> Any:
    """Return a hashable representation for common PyMuPDF arguments."""
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


class CachedPage:
    """Forward a page while caching identical text and drawing reads.

    The wrapped page remains the owner of the PyMuPDF object.  This proxy only
    caches read results; all other attributes and methods are forwarded.
    """

    def __init__(self, page: object) -> None:
        self._page = page
        self._text_cache: dict[Any, Any] = {}
        self._drawings_cache: dict[Any, Any] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)

    @staticmethod
    def _key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, Any]:
        return _freeze(args), _freeze(kwargs)

    def get_text(self, *args: Any, **kwargs: Any) -> Any:
        key = self._key(args, kwargs)
        if key not in self._text_cache:
            self._text_cache[key] = self._page.get_text(*args, **kwargs)
        return self._text_cache[key]

    def get_drawings(self, *args: Any, **kwargs: Any) -> Any:
        key = self._key(args, kwargs)
        if key not in self._drawings_cache:
            self._drawings_cache[key] = self._page.get_drawings(*args, **kwargs)
        return self._drawings_cache[key]
