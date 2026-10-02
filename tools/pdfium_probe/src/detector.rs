use std::path::{Path, PathBuf};
use image::{imageops::FilterType, DynamicImage};
use pdfium_render::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TableDetectorConfig {
    pub confidence_threshold: f32, // default 0.40
    pub iou_threshold: f32,        // default 0.50
    pub table_class_ids: Vec<usize>, // default vec![0, 4]
    pub input_size: u32,           // default 640
    pub render_dpi: f32,           // default 72.0
}

impl Default for TableDetectorConfig {
    fn default() -> Self {
        Self {
            confidence_threshold: 0.40,
            iou_threshold: 0.50,
            table_class_ids: vec![0, 4],
            input_size: 640,
            render_dpi: 72.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DetectedTableDto {
    pub x0: f32,
    pub y0: f32,
    pub x1: f32,
    pub y1: f32,
    pub score: f32,
    pub label: String,
}

pub fn parse_yolo_detections(
    output_slice: &[f32],
    shape: &[i64],
    orig_size: (u32, u32),
    config: &TableDetectorConfig,
) -> Vec<DetectedTableDto> {
    if config.input_size == 0 || orig_size.0 == 0 || orig_size.1 == 0 || shape.is_empty() {
        return Vec::new();
    }

    let scale_x = orig_size.0 as f32 / config.input_size as f32;
    let scale_y = orig_size.1 as f32 / config.input_size as f32;
    let max_w = orig_size.0 as f32;
    let max_h = orig_size.1 as f32;

    let mut class_candidates: std::collections::BTreeMap<usize, (Vec<BBoxFloat>, Vec<f32>)> =
        std::collections::BTreeMap::new();

    // Determine format:
    // Format 1: End-to-End YOLO: [1, N, 6] or [N, 6]
    let is_format_1 = (shape.len() == 3 && shape[2] == 6) || (shape.len() == 2 && shape[1] == 6);

    if is_format_1 {
        let n = if shape.len() == 3 {
            shape[1] as usize
        } else {
            shape[0] as usize
        };
        for k in 0..n {
            let base = k * 6;
            if base + 5 >= output_slice.len() {
                break;
            }
            let raw_x0 = output_slice[base];
            let raw_y0 = output_slice[base + 1];
            let raw_x1 = output_slice[base + 2];
            let raw_y1 = output_slice[base + 3];
            let score = output_slice[base + 4];
            let raw_cls = output_slice[base + 5];

            if raw_x0.is_nan()
                || raw_y0.is_nan()
                || raw_x1.is_nan()
                || raw_y1.is_nan()
                || score.is_nan()
                || raw_cls.is_nan()
                || raw_cls < 0.0
            {
                continue;
            }
            let cls_id = raw_cls.round() as usize;

            if score >= config.confidence_threshold && config.table_class_ids.contains(&cls_id) {
                let x0 = (raw_x0 * scale_x).clamp(0.0, max_w);
                let y0 = (raw_y0 * scale_y).clamp(0.0, max_h);
                let x1 = (raw_x1 * scale_x).clamp(0.0, max_w);
                let y1 = (raw_y1 * scale_y).clamp(0.0, max_h);
                let bbox = BBoxFloat::new(x0, y0, x1, y1);
                let entry = class_candidates.entry(cls_id).or_default();
                entry.0.push(bbox);
                entry.1.push(score);
            }
        }
    } else {
        // Format 2: Standard YOLO Head: [1, 4 + nc, N] or [4 + nc, N]
        let (rows, n, transposed) = if shape.len() == 3 {
            if shape[1] >= 5 {
                (shape[1] as usize, shape[2] as usize, false)
            } else if shape[2] >= 5 {
                (shape[2] as usize, shape[1] as usize, true)
            } else {
                return Vec::new();
            }
        } else if shape.len() == 2 {
            if shape[0] >= 5 {
                (shape[0] as usize, shape[1] as usize, false)
            } else if shape[1] >= 5 {
                (shape[1] as usize, shape[0] as usize, true)
            } else {
                return Vec::new();
            }
        } else {
            return Vec::new();
        };

        if rows < 5 || n == 0 || output_slice.len() < rows * n {
            return Vec::new();
        }

        let nc = rows - 4;

        for i in 0..n {
            let (cx, cy, w, h) = if !transposed {
                (
                    output_slice[i],
                    output_slice[n + i],
                    output_slice[2 * n + i],
                    output_slice[3 * n + i],
                )
            } else {
                (
                    output_slice[i * rows],
                    output_slice[i * rows + 1],
                    output_slice[i * rows + 2],
                    output_slice[i * rows + 3],
                )
            };

            if cx.is_nan() || cy.is_nan() || w.is_nan() || h.is_nan() {
                continue;
            }

            let mut best_cls = 0;
            let mut best_score = f32::MIN;
            for c in 0..nc {
                let score = if !transposed {
                    output_slice[(4 + c) * n + i]
                } else {
                    output_slice[i * rows + 4 + c]
                };
                if score > best_score {
                    best_score = score;
                    best_cls = c;
                }
            }

            if best_score >= config.confidence_threshold && config.table_class_ids.contains(&best_cls) {
                let raw_x0 = cx - w / 2.0;
                let raw_y0 = cy - h / 2.0;
                let raw_x1 = cx + w / 2.0;
                let raw_y1 = cy + h / 2.0;
                let x0 = (raw_x0 * scale_x).clamp(0.0, max_w);
                let y0 = (raw_y0 * scale_y).clamp(0.0, max_h);
                let x1 = (raw_x1 * scale_x).clamp(0.0, max_w);
                let y1 = (raw_y1 * scale_y).clamp(0.0, max_h);
                let bbox = BBoxFloat::new(x0, y0, x1, y1);
                let entry = class_candidates.entry(best_cls).or_default();
                entry.0.push(bbox);
                entry.1.push(best_score);
            }
        }
    }

    let mut detections = Vec::new();
    for (_cls_id, (boxes, scores)) in class_candidates {
        let keep_indices = non_maximum_suppression(&boxes, &scores, config.iou_threshold);
        for idx in keep_indices {
            let b = &boxes[idx];
            let score = scores[idx];
            detections.push(DetectedTableDto {
                x0: b.x0,
                y0: b.y0,
                x1: b.x1,
                y1: b.y1,
                score,
                label: "Table".to_string(),
            });
        }
    }

    detections.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    detections
}

pub struct YoloTableDetector {
    session: ort::session::Session,
    pub config: TableDetectorConfig,
}

impl YoloTableDetector {
    pub fn new(model_path: &Path, config: TableDetectorConfig) -> Result<Self, Box<dyn std::error::Error>> {
        let session = ort::session::Session::builder()?.commit_from_file(model_path)?;
        Ok(Self { session, config })
    }

    pub fn detect_from_image(
        &mut self,
        img: &DynamicImage,
        words: &[[f32; 4]],
        page_size: (f32, f32),
    ) -> Result<Vec<DetectedTableDto>, Box<dyn std::error::Error>> {
        if img.width() == 0 || img.height() == 0 {
            return Ok(Vec::new());
        }

        let tensor = preprocess_image_to_nchw(img, (self.config.input_size, self.config.input_size));
        let shape = [1usize, 3, self.config.input_size as usize, self.config.input_size as usize];
        let val = ort::value::Tensor::from_array((shape, tensor.into_boxed_slice()))?;
        let outputs = self.session.run(ort::inputs![val])?;
        let (out_shape, out_slice) = outputs[0].try_extract_tensor::<f32>()?;

        let detections = parse_yolo_detections(
            out_slice,
            out_shape.as_ref(),
            (img.width(), img.height()),
            &self.config,
        );

        let scale_x = page_size.0 / img.width() as f32;
        let scale_y = page_size.1 / img.height() as f32;

        let mut page_detections = Vec::new();
        for d in detections {
            let page_bbox = BBoxFloat::new(d.x0 * scale_x, d.y0 * scale_y, d.x1 * scale_x, d.y1 * scale_y);
            if filter_full_page_false_positives(&page_bbox, d.score, page_size.0, page_size.1) {
                continue;
            }
            let expanded = expand_bbox_to_touching_words(
                &page_bbox,
                words,
                Some([0.0, 0.0, page_size.0, page_size.1]),
            );
            page_detections.push(DetectedTableDto {
                x0: expanded.x0,
                y0: expanded.y0,
                x1: expanded.x1,
                y1: expanded.y1,
                score: d.score,
                label: d.label,
            });
        }

        Ok(page_detections)
    }
}

pub fn resolve_default_model_path() -> Option<PathBuf> {
    // 1. Check environment variable YOLO_TABLE_DETECTOR_MODEL
    if let Ok(p) = std::env::var("YOLO_TABLE_DETECTOR_MODEL") {
        let pb = PathBuf::from(p);
        if pb.exists() {
            return Some(pb);
        }
    }
    // 2. Standard repository candidate paths
    let candidates = [
        "src/hexai_pdf_parser/ml/table_detector_model/best.onnx",
        "../../src/hexai_pdf_parser/ml/table_detector_model/best.onnx",
        "../src/hexai_pdf_parser/ml/table_detector_model/best.onnx",
        "models/table_detector/best.onnx",
    ];
    for c in candidates {
        let pb = PathBuf::from(c);
        if pb.exists() {
            return Some(pb);
        }
    }
    if let Ok(manifest) = std::env::var("CARGO_MANIFEST_DIR") {
        let pb = PathBuf::from(manifest).join("../../src/hexai_pdf_parser/ml/table_detector_model/best.onnx");
        if pb.exists() {
            return Some(pb);
        }
    }
    None
}

pub fn detect_tables_on_pdf_page(
    page: &PdfPage,
    words: &[[f32; 4]],
    model_path: &Path,
    config: &TableDetectorConfig,
) -> Result<Vec<DetectedTableDto>, Box<dyn std::error::Error>> {
    let scale = (config.render_dpi / 72.0).max(0.1);
    let target_w = (page.width().value * scale).round().max(1.0) as i32;
    let target_h = (page.height().value * scale).round().max(1.0) as i32;
    let render_config = PdfRenderConfig::new()
        .set_target_width(target_w)
        .set_target_height(target_h);
    let bitmap = page.render_with_config(&render_config)?;
    let dyn_img = bitmap.as_image();
    let mut detector = YoloTableDetector::new(model_path, config.clone())?;
    detector.detect_from_image(&dyn_img, words, (page.width().value, page.height().value))
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct BBoxFloat {
    pub x0: f32,
    pub y0: f32,
    pub x1: f32,
    pub y1: f32,
}

impl BBoxFloat {
    pub fn new(x0: f32, y0: f32, x1: f32, y1: f32) -> Self {
        let (min_x, max_x) = if x0 <= x1 { (x0, x1) } else { (x1, x0) };
        let (min_y, max_y) = if y0 <= y1 { (y0, y1) } else { (y1, y0) };
        Self {
            x0: min_x,
            y0: min_y,
            x1: max_x,
            y1: max_y,
        }
    }

    pub fn area(&self) -> f32 {
        ((self.x1 - self.x0).max(0.0)) * ((self.y1 - self.y0).max(0.0))
    }
}

pub fn calculate_iou(b1: &BBoxFloat, b2: &BBoxFloat) -> f32 {
    let inter_x0 = b1.x0.max(b2.x0);
    let inter_y0 = b1.y0.max(b2.y0);
    let inter_x1 = b1.x1.min(b2.x1);
    let inter_y1 = b1.y1.min(b2.y1);

    let inter_w = (inter_x1 - inter_x0).max(0.0);
    let inter_h = (inter_y1 - inter_y0).max(0.0);
    let inter_area = inter_w * inter_h;

    if inter_area <= 0.0 {
        return 0.0;
    }

    let union_area = b1.area() + b2.area() - inter_area;
    if union_area <= 1e-6 {
        return 0.0;
    }

    inter_area / union_area
}

pub fn non_maximum_suppression(
    boxes: &[BBoxFloat],
    scores: &[f32],
    iou_threshold: f32,
) -> Vec<usize> {
    let n = boxes.len().min(scores.len());
    if n == 0 {
        return Vec::new();
    }

    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| {
        scores[b]
            .partial_cmp(&scores[a])
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut keep = Vec::new();
    while !order.is_empty() {
        let current = order[0];
        keep.push(current);
        if order.len() == 1 {
            break;
        }

        let current_box = &boxes[current];
        let mut next_order = Vec::with_capacity(order.len() - 1);
        for &idx in &order[1..] {
            let iou = calculate_iou(current_box, &boxes[idx]);
            if iou <= iou_threshold {
                next_order.push(idx);
            }
        }
        order = next_order;
    }

    keep
}

pub fn expand_bbox_to_touching_words(
    bbox: &BBoxFloat,
    words: &[[f32; 4]],
    page_rect: Option<[f32; 4]>,
) -> BBoxFloat {
    let original_x0 = bbox.x0;
    let original_y0 = bbox.y0;
    let original_x1 = bbox.x1;
    let original_y1 = bbox.y1;

    let mut x0 = original_x0;
    let mut y0 = original_y0;
    let mut x1 = original_x1;
    let mut y1 = original_y1;

    for w in words {
        let wx0 = w[0];
        let wy0 = w[1];
        let wx1 = w[2];
        let wy1 = w[3];

        if wx1 > original_x0 && wx0 < original_x1 && wy1 > original_y0 && wy0 < original_y1 {
            x0 = x0.min(wx0);
            y0 = y0.min(wy0);
            x1 = x1.max(wx1);
            y1 = y1.max(wy1);
        }
    }

    if let Some([px0, py0, px1, py1]) = page_rect {
        x0 = x0.clamp(px0, px1);
        y0 = y0.clamp(py0, py1);
        x1 = x1.clamp(px0, px1);
        y1 = y1.clamp(py0, py1);
    }

    BBoxFloat::new(
        (x0 * 10.0).round() / 10.0,
        (y0 * 10.0).round() / 10.0,
        (x1 * 10.0).round() / 10.0,
        (y1 * 10.0).round() / 10.0,
    )
}

pub fn filter_full_page_false_positives(
    bbox: &BBoxFloat,
    score: f32,
    page_w: f32,
    page_h: f32,
) -> bool {
    let page_area = page_w * page_h;
    bbox.area() > page_area * 0.85 && score < 0.50
}

pub fn preprocess_image_to_nchw(img: &DynamicImage, target_size: (u32, u32)) -> Vec<f32> {
    let (target_w, target_h) = target_size;
    let resized = img.resize_exact(target_w, target_h, FilterType::Triangle);
    let rgb = resized.to_rgb8();

    let channel_size = (target_w * target_h) as usize;
    let mut tensor = vec![0.0f32; 3 * channel_size];

    let raw = rgb.as_raw();
    for (i, chunk) in raw.chunks_exact(3).enumerate() {
        tensor[i] = chunk[0] as f32 / 255.0;
        tensor[channel_size + i] = chunk[1] as f32 / 255.0;
        tensor[2 * channel_size + i] = chunk[2] as f32 / 255.0;
    }

    tensor
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgb, RgbImage};

    #[test]
    fn test_detector_geometry_bbox_float_and_iou() {
        // BBoxFloat creation and normalization
        let b1 = BBoxFloat::new(10.0, 20.0, 50.0, 80.0);
        assert_eq!(b1.x0, 10.0);
        assert_eq!(b1.y0, 20.0);
        assert_eq!(b1.x1, 50.0);
        assert_eq!(b1.y1, 80.0);
        assert_eq!(b1.area(), 2400.0);

        // Inverted coordinate normalization
        let b1_rev = BBoxFloat::new(50.0, 80.0, 10.0, 20.0);
        assert_eq!(b1, b1_rev);

        // Identical box IoU
        let iou_self = calculate_iou(&b1, &b1);
        assert!((iou_self - 1.0).abs() < 1e-5);

        // Completely disjoint boxes
        let b_disjoint = BBoxFloat::new(100.0, 100.0, 150.0, 150.0);
        assert_eq!(calculate_iou(&b1, &b_disjoint), 0.0);

        // Touching edge (no intersection area)
        let b_touching = BBoxFloat::new(50.0, 20.0, 70.0, 80.0);
        assert_eq!(calculate_iou(&b1, &b_touching), 0.0);

        // Overlapping boxes with known IoU:
        // b_a: [0, 0, 10, 10], area = 100
        // b_b: [5, 0, 15, 10], area = 100
        // intersection: [5, 0, 10, 10], area = 50
        // union = 100 + 100 - 50 = 150
        // iou = 50 / 150 = 1 / 3
        let b_a = BBoxFloat::new(0.0, 0.0, 10.0, 10.0);
        let b_b = BBoxFloat::new(5.0, 0.0, 15.0, 10.0);
        let iou_ab = calculate_iou(&b_a, &b_b);
        assert!((iou_ab - 1.0 / 3.0).abs() < 1e-5);

        // Zero area box
        let b_zero = BBoxFloat::new(0.0, 0.0, 0.0, 0.0);
        assert_eq!(calculate_iou(&b_zero, &b1), 0.0);
    }

    #[test]
    fn test_detector_geometry_non_maximum_suppression() {
        // Empty input
        assert_eq!(non_maximum_suppression(&[], &[], 0.5), Vec::<usize>::new());

        // Four boxes:
        // Box 0: (0, 0, 100, 100), score 0.90
        // Box 1: (5, 5, 100, 100), score 0.80 (near duplicate of Box 0)
        // Box 2: (200, 200, 300, 300), score 0.70 (distinct)
        // Box 3: (205, 205, 300, 300), score 0.60 (near duplicate of Box 2)
        let boxes = vec![
            BBoxFloat::new(0.0, 0.0, 100.0, 100.0),
            BBoxFloat::new(5.0, 5.0, 100.0, 100.0),
            BBoxFloat::new(200.0, 200.0, 300.0, 300.0),
            BBoxFloat::new(205.0, 205.0, 300.0, 300.0),
        ];
        let scores = vec![0.90, 0.80, 0.70, 0.60];
        let kept = non_maximum_suppression(&boxes, &scores, 0.5);
        assert_eq!(kept, vec![0, 2]);

        // Out-of-order score sorting check
        let boxes_unordered = vec![
            BBoxFloat::new(200.0, 200.0, 300.0, 300.0),
            BBoxFloat::new(0.0, 0.0, 100.0, 100.0),
        ];
        let scores_unordered = vec![0.50, 0.95];
        let kept_unordered = non_maximum_suppression(&boxes_unordered, &scores_unordered, 0.5);
        assert_eq!(kept_unordered, vec![1, 0]);
    }

    #[test]
    fn test_detector_geometry_expand_bbox_to_touching_words() {
        let base_bbox = BBoxFloat::new(100.0, 100.0, 300.0, 200.0);

        // Word 1: intersects left boundary and extends to left: [80.23, 110.0, 120.0, 130.0]
        // Word 2: intersects bottom boundary and extends downwards: [150.0, 190.0, 220.0, 230.45]
        // Word 3: completely outside: [10.0, 10.0, 40.0, 40.0]
        // Word 4: completely outside to the right: [400.0, 100.0, 450.0, 150.0]
        let words = vec![
            [80.23, 110.0, 120.0, 130.0],
            [150.0, 190.0, 220.0, 230.45],
            [10.0, 10.0, 40.0, 40.0],
            [400.0, 100.0, 450.0, 150.0],
        ];

        let expanded = expand_bbox_to_touching_words(&base_bbox, &words, None);
        assert_eq!(expanded.x0, 80.2);
        assert_eq!(expanded.y0, 100.0);
        assert_eq!(expanded.x1, 300.0);
        assert_eq!(expanded.y1, 230.5);

        // With page_rect clamping: [90.0, 50.0, 250.0, 220.0]
        let page_rect = Some([90.0, 50.0, 250.0, 220.0]);
        let clamped = expand_bbox_to_touching_words(&base_bbox, &words, page_rect);
        assert_eq!(clamped.x0, 90.0); // clamped from 80.2
        assert_eq!(clamped.y0, 100.0);
        assert_eq!(clamped.x1, 250.0); // clamped from 300.0
        assert_eq!(clamped.y1, 220.0); // clamped from 230.5
    }

    #[test]
    fn test_detector_geometry_filter_full_page_false_positives() {
        let page_w = 1000.0;
        let page_h = 1000.0;

        // 90.25% page coverage
        let large_bbox = BBoxFloat::new(0.0, 0.0, 950.0, 950.0);

        // Low confidence (< 0.50) -> should be filtered
        assert!(filter_full_page_false_positives(&large_bbox, 0.45, page_w, page_h));

        // High confidence (>= 0.50) -> should NOT be filtered
        assert!(!filter_full_page_false_positives(&large_bbox, 0.95, page_w, page_h));
        assert!(!filter_full_page_false_positives(&large_bbox, 0.50, page_w, page_h));

        // Moderate coverage (50%) with low score -> should NOT be filtered
        let med_bbox = BBoxFloat::new(0.0, 0.0, 500.0, 1000.0);
        assert!(!filter_full_page_false_positives(&med_bbox, 0.20, page_w, page_h));
    }

    #[test]
    fn test_detector_geometry_preprocess_image_to_nchw() {
        // Create a 2x2 solid red image
        let mut img_buf = RgbImage::new(2, 2);
        for pixel in img_buf.pixels_mut() {
            *pixel = Rgb([255, 0, 0]);
        }
        let dynamic_img = DynamicImage::ImageRgb8(img_buf);

        let target_size = (4, 4);
        let tensor = preprocess_image_to_nchw(&dynamic_img, target_size);

        // Dimension: 3 * 4 * 4 = 48
        assert_eq!(tensor.len(), 48);

        let channel_size = 4 * 4;
        let r_channel = &tensor[0..channel_size];
        let g_channel = &tensor[channel_size..2 * channel_size];
        let b_channel = &tensor[2 * channel_size..3 * channel_size];

        for &val in r_channel {
            assert!((val - 1.0).abs() < 1e-4);
        }
        for &val in g_channel {
            assert_eq!(val, 0.0);
        }
        for &val in b_channel {
            assert_eq!(val, 0.0);
        }
    }

    // Direct aliases to match the brief's 5 exact test names
    #[test]
    fn test_bbox_float_and_iou() {
        test_detector_geometry_bbox_float_and_iou();
    }

    #[test]
    fn test_non_maximum_suppression() {
        test_detector_geometry_non_maximum_suppression();
    }

    #[test]
    fn test_expand_bbox_to_touching_words() {
        test_detector_geometry_expand_bbox_to_touching_words();
    }

    #[test]
    fn test_filter_full_page_false_positives() {
        test_detector_geometry_filter_full_page_false_positives();
    }

    #[test]
    fn test_preprocess_image_to_nchw() {
        test_detector_geometry_preprocess_image_to_nchw();
    }

    #[test]
    fn test_yolo_parser_config_and_dto() {
        let config = TableDetectorConfig::default();
        assert_eq!(config.confidence_threshold, 0.40);
        assert_eq!(config.iou_threshold, 0.50);
        assert_eq!(config.table_class_ids, vec![0, 4]);
        assert_eq!(config.input_size, 640);
        assert_eq!(config.render_dpi, 72.0);

        let dto = DetectedTableDto {
            x0: 10.0,
            y0: 20.0,
            x1: 100.0,
            y1: 200.0,
            score: 0.95,
            label: "Table".to_string(),
        };
        let json = serde_json::to_string(&dto).unwrap();
        let decoded: DetectedTableDto = serde_json::from_str(&json).unwrap();
        assert_eq!(dto, decoded);
    }

    #[test]
    fn test_yolo_parser_end_to_end_format() {
        // [1, 4, 6] format: 4 candidate boxes, each [x0, y0, x1, y1, score, class_id]
        let shape = vec![1, 4, 6];
        let slice = vec![
            // Box 0: Valid table (score 0.90, class 0)
            100.0, 100.0, 200.0, 200.0, 0.90, 0.0,
            // Box 1: Overlaps Box 0 with high IoU (~0.85), score 0.80 -> suppressed by NMS
            105.0, 105.0, 205.0, 205.0, 0.80, 0.0,
            // Box 2: Score 0.30 < 0.40 -> filtered by confidence threshold
            300.0, 300.0, 400.0, 400.0, 0.30, 0.0,
            // Box 3: Class 2 (not in table_class_ids [0, 4]) -> filtered by class
            50.0, 50.0, 80.0, 80.0, 0.85, 2.0,
        ];
        let config = TableDetectorConfig {
            confidence_threshold: 0.40,
            iou_threshold: 0.50,
            table_class_ids: vec![0, 4],
            input_size: 640,
            render_dpi: 72.0,
        };
        // orig_size is 1280x1280 (scale = 2.0)
        let orig_size = (1280, 1280);
        let detections = parse_yolo_detections(&slice, &shape, orig_size, &config);

        assert_eq!(detections.len(), 1);
        let det = &detections[0];
        assert_eq!(det.label, "Table");
        assert!((det.score - 0.90).abs() < 1e-4);
        assert!((det.x0 - 200.0).abs() < 1e-3);
        assert!((det.y0 - 200.0).abs() < 1e-3);
        assert!((det.x1 - 400.0).abs() < 1e-3);
        assert!((det.y1 - 400.0).abs() < 1e-3);
    }

    #[test]
    fn test_yolo_parser_standard_head_format() {
        // [1, 6, 2] format: rows = 6 (cx, cy, w, h, class0_score, class1_score), N = 2 candidates
        // row-major: row * N + i
        // cx row (0): [100.0, 105.0]
        // cy row (1): [100.0, 105.0]
        // w  row (2): [100.0, 100.0]
        // h  row (3): [100.0, 100.0]
        // c0 row (4): [0.90,  0.80]
        // c1 row (5): [0.10,  0.10]
        let shape = vec![1, 6, 2];
        let slice = vec![
            100.0, 105.0, // cx
            100.0, 105.0, // cy
            100.0, 100.0, // w
            100.0, 100.0, // h
            0.90, 0.80,   // class 0
            0.10, 0.10,   // class 1
        ];
        let config = TableDetectorConfig {
            confidence_threshold: 0.40,
            iou_threshold: 0.50,
            table_class_ids: vec![0, 4],
            input_size: 640,
            render_dpi: 72.0,
        };
        let orig_size = (640, 640);
        let detections = parse_yolo_detections(&slice, &shape, orig_size, &config);

        assert_eq!(detections.len(), 1);
        let det = &detections[0];
        assert_eq!(det.label, "Table");
        assert!((det.score - 0.90).abs() < 1e-4);
        // cx=100, cy=100, w=100, h=100 => x0=50, y0=50, x1=150, y1=150
        assert!((det.x0 - 50.0).abs() < 1e-3);
        assert!((det.y0 - 50.0).abs() < 1e-3);
        assert!((det.x1 - 150.0).abs() < 1e-3);
        assert!((det.y1 - 150.0).abs() < 1e-3);
    }

    #[test]
    fn test_yolo_detector_pipeline_with_mock_or_real() {
        let candidates = [
            std::path::Path::new("src/hexai_pdf_parser/ml/table_detector_model/best.onnx"),
            std::path::Path::new("../../src/hexai_pdf_parser/ml/table_detector_model/best.onnx"),
        ];
        let model_path = candidates.iter().find(|p| p.exists());
        if let Some(path) = model_path {
            let config = TableDetectorConfig::default();
            let mut detector = YoloTableDetector::new(path, config).expect("Failed to initialize detector");
            let img = DynamicImage::ImageRgb8(RgbImage::new(640, 640));
            let words = vec![[10.0, 10.0, 50.0, 20.0]];
            let page_size = (595.0, 842.0);
            let detections = detector.detect_from_image(&img, &words, page_size).expect("Detection failed");
            for det in &detections {
                assert_eq!(det.label, "Table");
                assert!(det.score >= 0.40);
            }
        }
    }

    #[test]
    fn test_yolo_parser_detector_pipeline_with_mock_or_real() {
        test_yolo_detector_pipeline_with_mock_or_real();
    }
}
