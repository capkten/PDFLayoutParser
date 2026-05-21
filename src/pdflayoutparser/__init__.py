from typing import List, Optional

from pdflayoutparser.pipeline import Pipeline
from pdflayoutparser.models import Document

def parse_pdf(
    pdf_path: str,
    output_dir: str = ".",
    page_indices: Optional[List[int]] = None,
    render_dpi: int = 200,
    seal_coords: Optional[List[dict]] = None,
    use_ml: bool = False,
    ml_model_path: Optional[str] = None,
    ml_confidence: float = 0.25,
) -> Document:
    """
    Parse PDF layouts into structured JSON and Markdown.

    :param pdf_path: Path to the PDF file.
    :param output_dir: Directory where the output will be saved.
    :param page_indices: List of page indices to parse (0-indexed). If None, parse all pages.
    :param render_dpi: Render DPI.
    :param seal_coords: Optional list of seal coordinates.
    :param use_ml: Enable ML-based table region detection with the bundled YOLO model (requires pdflayoutparser[ml]).
    :param ml_model_path: Path to custom ONNX model for table detection.
    :param ml_confidence: Confidence threshold for ML table detection.
    :return: A parsed Document object.
    """
    pipeline = Pipeline(
        pdf_path=pdf_path,
        output_dir=output_dir,
        render_dpi=render_dpi,
        seal_coords=seal_coords,
        page_indices=page_indices,
        use_ml=use_ml,
        ml_model_path=ml_model_path,
        ml_confidence=ml_confidence,
    )
    return pipeline.run()

__all__ = ["parse_pdf", "Pipeline", "Document"]
