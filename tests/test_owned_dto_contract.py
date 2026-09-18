from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hexai_pdf_parser import rust_adapter


def _rect(**overrides):
    value = {
        "schema_version": 1,
        "x0": 0.0,
        "y0": 0.0,
        "x1": 10.0,
        "y1": 20.0,
    }
    value.update(overrides)
    return value


def test_public_rect_dto_roundtrip_preserves_schema_version_one():
    assert rust_adapter.roundtrip_dto("rect", _rect())["schema_version"] == 1


@pytest.mark.parametrize("schema_version", [None, 0, 2])
def test_public_rect_dto_rejects_missing_or_wrong_schema(schema_version):
    value = _rect()
    if schema_version is None:
        value.pop("schema_version")
    else:
        value["schema_version"] = schema_version

    with pytest.raises((ValueError, TypeError)):
        rust_adapter.roundtrip_dto("rect", value)


@pytest.mark.parametrize("field", ["x0", "y0", "x1", "y1"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_public_rect_dto_rejects_non_finite_coordinates(field, value):
    with pytest.raises((ValueError, TypeError)):
        rust_adapter.roundtrip_dto("rect", _rect(**{field: value}))
