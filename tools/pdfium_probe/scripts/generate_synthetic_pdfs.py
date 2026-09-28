import os
import pymupdf as fitz

def generate_all(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    # 1. synth_crop_offset.pdf
    doc1 = fitz.open()
    page1 = doc1.new_page(width=600, height=600)
    page1.set_cropbox(fitz.Rect(50, 50, 550, 550))
    page1.insert_text(fitz.Point(100, 120), "Header in CropBox", fontsize=14)
    page1.insert_text(fitz.Point(100, 220), "Normal Body Text", fontsize=12)
    page1.insert_text(fitz.Point(20, 30), "Outside of CropBox", fontsize=10)
    p1_path = os.path.join(output_dir, "synth_crop_offset.pdf")
    doc1.save(p1_path)
    doc1.close()
    print(f"Generated {p1_path}")

    # 2. synth_rotations.pdf
    doc2 = fitz.open()
    rotations = [0, 90, 180, 270]
    for rot in rotations:
        p = doc2.new_page(width=400, height=600)
        p.set_rotation(rot)
        p.insert_text(fitz.Point(100, 150), f"Page Rotation {rot} Text", fontsize=14)
    p2_path = os.path.join(output_dir, "synth_rotations.pdf")
    doc2.save(p2_path)
    doc2.close()
    print(f"Generated {p2_path}")

    # 3. synth_invisible_text.pdf
    doc3 = fitz.open()
    page3 = doc3.new_page(width=500, height=500)
    page3.insert_text(fitz.Point(50, 100), "Visible Main Title", fontsize=16)
    # render_mode=3 is invisible text (neither stroke nor fill)
    page3.insert_text(fitz.Point(50, 150), "Invisible OCR Text Layer", fontsize=12, render_mode=3)
    page3.insert_text(fitz.Point(50, 200), "Overlapped Text Base", fontsize=12)
    page3.insert_text(fitz.Point(50, 200), "Overlapped Text Top", fontsize=12)
    p3_path = os.path.join(output_dir, "synth_invisible_text.pdf")
    doc3.save(p3_path)
    doc3.close()
    print(f"Generated {p3_path}")

    # 4. synth_mixed_fonts.pdf
    doc4 = fitz.open()
    page4 = doc4.new_page(width=600, height=400)
    page4.insert_text(fitz.Point(50, 100), "Project Revenue:", fontsize=14, fontname="helv")
    page4.insert_text(fitz.Point(170, 95), "1", fontsize=8, fontname="helv") # superscript-like
    page4.insert_text(fitz.Point(180, 100), "主要业务收入", fontsize=14, fontname="china-ss")
    page4.insert_text(fitz.Point(300, 100), "( audited )", fontsize=11, fontname="tiro")
    p4_path = os.path.join(output_dir, "synth_mixed_fonts.pdf")
    doc4.save(p4_path)
    doc4.close()
    print(f"Generated {p4_path}")

    # 5. synth_segmented_lines.pdf
    doc5 = fitz.open()
    page5 = doc5.new_page(width=500, height=400)
    shape = page5.new_shape()
    # Continuous line
    shape.draw_line(fitz.Point(50, 80), fitz.Point(450, 80))
    shape.finish(color=(0, 0, 0), width=1.5)
    # Segmented line
    shape.draw_line(fitz.Point(50, 180), fitz.Point(180, 180))
    shape.finish(color=(0, 0, 0), width=1.0)
    shape.draw_line(fitz.Point(180, 180), fitz.Point(320, 180))
    shape.finish(color=(0, 0, 0), width=1.0)
    shape.draw_line(fitz.Point(320, 180), fitz.Point(450, 180))
    shape.finish(color=(0, 0, 0), width=1.0)
    # Vertical boundaries
    shape.draw_line(fitz.Point(50, 80), fitz.Point(50, 180))
    shape.finish(color=(0, 0, 0), width=1.0)
    shape.draw_line(fitz.Point(450, 80), fitz.Point(450, 180))
    shape.finish(color=(0, 0, 0), width=1.0)
    # Interior cell texts
    shape.commit()
    page5.insert_text(fitz.Point(60, 130), "Table Cell 1", fontsize=12)
    page5.insert_text(fitz.Point(250, 130), "Table Cell 2", fontsize=12)
    p5_path = os.path.join(output_dir, "synth_segmented_lines.pdf")
    doc5.save(p5_path)
    doc5.close()
    print(f"Generated {p5_path}")

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "test_data", "synthetic")
    generate_all(out_dir)
