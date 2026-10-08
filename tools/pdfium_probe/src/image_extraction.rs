use crate::{save_image_to_png, transform_point_to_viewport};
use pdfium_render::prelude::*;
use serde::Serialize;
use std::path::Path;

#[derive(Clone, Debug, Serialize)]
pub struct ImageBBox {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

#[derive(Clone, Debug, Serialize)]
pub struct ImageDto {
    pub bbox: ImageBBox,
    pub page_index: usize,
    pub resource_index: usize,
    pub width: u32,
    pub height: u32,
    pub path: String,
    pub ext: String,
}

pub fn intersects(image: &ImageDto, region: [f64; 4]) -> bool {
    let bbox = &image.bbox;
    !(bbox.x1 < region[0] || bbox.x0 > region[2] || bbox.y1 < region[1] || bbox.y0 > region[3])
}

struct PageImages<'a> {
    crop: [f64; 4],
    rotation: i64,
    page_index: usize,
    output_dir: &'a Path,
    images: Vec<ImageDto>,
}

impl PageImages<'_> {
    fn visit(&mut self, object: &PdfPageObject, parent: PdfMatrix) -> Result<(), String> {
        if !object.is_active().map_err(|err| err.to_string())? {
            return Ok(());
        }
        if let Some(form) = object.as_x_object_form_object() {
            let matrix = form
                .matrix()
                .map_err(|err| err.to_string())?
                .multiply(parent);
            for child in form.iter() {
                self.visit(&child, matrix)?;
            }
        } else if let Some(image) = object.as_image_object() {
            let matrix = image
                .matrix()
                .map_err(|err| err.to_string())?
                .multiply(parent);
            let points = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)].map(|(x, y)| {
                let (x, y) = matrix.apply_to_points(PdfPoints::new(x), PdfPoints::new(y));
                transform_point_to_viewport(
                    x.value as f64,
                    y.value as f64,
                    self.crop[0],
                    self.crop[1],
                    self.crop[2],
                    self.crop[3],
                    self.rotation,
                )
            });
            let bbox = ImageBBox {
                x0: points
                    .iter()
                    .map(|point| point[0])
                    .fold(f64::INFINITY, f64::min),
                y0: points
                    .iter()
                    .map(|point| point[1])
                    .fold(f64::INFINITY, f64::min),
                x1: points
                    .iter()
                    .map(|point| point[0])
                    .fold(f64::NEG_INFINITY, f64::max),
                y1: points
                    .iter()
                    .map(|point| point[1])
                    .fold(f64::NEG_INFINITY, f64::max),
            };
            let (width, height) = (self.crop[2] - self.crop[0], self.crop[3] - self.crop[1]);
            let (width, height) = if matches!(self.rotation, 90 | 270) {
                (height, width)
            } else {
                (width, height)
            };
            if bbox.x1 <= bbox.x0
                || bbox.y1 <= bbox.y0
                || bbox.x1 <= 0.0
                || bbox.y1 <= 0.0
                || bbox.x0 >= width
                || bbox.y0 >= height
            {
                return Ok(());
            }
            // 原始 bitmap 保留资源尺寸，不应用 placement 的缩放/旋转。
            let bitmap = image
                .get_raw_image()
                .map_err(|err| format!("Could not decode image: {}", err))?;
            let filters = image.filters();
            let jpeg = filters.len() == 1
                && filters.get(0).map_err(|err| err.to_string())?.name() == "DCTDecode";
            let ext = if jpeg { "jpeg" } else { "png" };
            let resource_index = self.images.len();
            let path = self.output_dir.join(format!(
                "page-{:03}-img-{:03}.{}",
                self.page_index, resource_index, ext
            ));
            if jpeg {
                let bytes = image.get_raw_image_data().map_err(|err| err.to_string())?;
                std::fs::write(&path, bytes)
                    .map_err(|err| format!("Could not write image {}: {}", path.display(), err))?;
            } else {
                save_image_to_png(&bitmap, &path)
                    .map_err(|err| format!("Could not write image {}: {}", path.display(), err))?;
            }
            self.images.push(ImageDto {
                bbox,
                page_index: self.page_index,
                resource_index,
                width: bitmap.width(),
                height: bitmap.height(),
                path: path.to_string_lossy().into_owned(),
                ext: ext.to_string(),
            });
        }
        Ok(())
    }
}

pub fn extract_page_images(
    page: &PdfPage,
    page_index: usize,
    output_dir: &Path,
) -> Result<Vec<ImageDto>, String> {
    std::fs::create_dir_all(output_dir).map_err(|err| {
        format!(
            "Could not create image directory {}: {}",
            output_dir.display(),
            err
        )
    })?;
    let crop = page
        .boundaries()
        .crop()
        .or_else(|_| page.boundaries().media())
        .map_err(|err| err.to_string())?
        .bounds;
    let rotation = match page.rotation().map_err(|err| err.to_string())? {
        PdfPageRenderRotation::None => 0,
        PdfPageRenderRotation::Degrees90 => 90,
        PdfPageRenderRotation::Degrees180 => 180,
        PdfPageRenderRotation::Degrees270 => 270,
    };
    let mut extraction = PageImages {
        crop: [
            crop.left().value as f64,
            crop.bottom().value as f64,
            crop.right().value as f64,
            crop.top().value as f64,
        ],
        rotation,
        page_index,
        output_dir,
        images: Vec::new(),
    };
    for object in page.objects().iter() {
        extraction.visit(&object, PdfMatrix::IDENTITY)?;
    }
    Ok(extraction.images)
}
