use image::{imageops::FilterType, DynamicImage};
use serde::{Deserialize, Serialize};

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
}
