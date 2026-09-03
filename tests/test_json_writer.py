import json
import os

from hexai_pdf_parser.json_writer import JSONWriter
from hexai_pdf_parser.models import Block, BBox, Document, Page


def test_write_document_json(tmp_dir):
    doc = Document(file_name="test.pdf", page_count=1)
    doc.pages.append(
        Page(
            index=0,
            size={"width": 595, "height": 842},
            rotation=0,
            page_type="scanned",
            blocks=[Block(text="Hi", bbox=BBox(0, 0, 10, 10))],
        )
    )
    writer = JSONWriter()
    out_path = os.path.join(tmp_dir, "out.json")
    writer.write(doc, out_path)
    assert os.path.exists(out_path)
    with open(out_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["document"]["file_name"] == "test.pdf"
    assert data["document"]["page_count"] == 1
    assert len(data["pages"]) == 1
    assert data["pages"][0]["index"] == 0
    assert data["pages"][0]["page_type"] == "scanned"
    assert data["pages"][0]["blocks"][0]["text"] == "Hi"
