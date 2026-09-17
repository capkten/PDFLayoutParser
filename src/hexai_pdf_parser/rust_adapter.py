from typing import Any, Dict, List, Tuple

from . import _pdf_fast

Line4 = Tuple[float, float, float, float]


def merge_h_lines(lines: List[Line4], merge_group_tol: float) -> List[Line4]:
    owned_lines = [tuple(float(value) for value in line) for line in lines]
    merged_lines = _pdf_fast.merge_h_lines(owned_lines, float(merge_group_tol))
    return [tuple(float(value) for value in line) for line in merged_lines]


def roundtrip_dto(dto_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _pdf_fast.roundtrip_dto(str(dto_type), data)
