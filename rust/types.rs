use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

pub fn check_schema_version(version: i64) -> PyResult<()> {
    if version != 1 {
        return Err(PyValueError::new_err(format!(
            "Unsupported schema_version: {}, expected 1",
            version
        )));
    }
    Ok(())
}

pub fn extract_finite_f64(val: &Bound<'_, PyAny>, field_name: &str) -> PyResult<f64> {
    let num: f64 = val.extract()?;
    if !num.is_finite() {
        return Err(PyValueError::new_err(format!(
            "Field '{}' must be a finite float, got NaN or Inf",
            field_name
        )));
    }
    Ok(num)
}

pub fn get_req<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    match dict.get_item(key)? {
        Some(val) => Ok(val),
        None => Err(PyValueError::new_err(format!(
            "Missing required field '{}'",
            key
        ))),
    }
}

pub fn get_opt<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
    match dict.get_item(key)? {
        Some(val) if !val.is_none() => Ok(Some(val)),
        _ => Ok(None),
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PageDto {
    pub schema_version: i64,
    pub width: f64,
    pub height: f64,
    pub rotation: i64,
}

impl PageDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let width = extract_finite_f64(&get_req(dict, "width")?, "width")?;
        let height = extract_finite_f64(&get_req(dict, "height")?, "height")?;
        let rotation: i64 = get_req(dict, "rotation")?.extract()?;
        if rotation != 0 && rotation != 90 && rotation != 180 && rotation != 270 {
            return Err(PyValueError::new_err(format!(
                "Invalid rotation: {}, must be 0, 90, 180, or 270",
                rotation
            )));
        }
        Ok(Self {
            schema_version: sv,
            width,
            height,
            rotation,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("width", self.width)?;
        d.set_item("height", self.height)?;
        d.set_item("rotation", self.rotation)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Rect4 {
    pub schema_version: i64,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

impl Rect4 {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let x0 = extract_finite_f64(&get_req(dict, "x0")?, "x0")?;
        let y0 = extract_finite_f64(&get_req(dict, "y0")?, "y0")?;
        let x1 = extract_finite_f64(&get_req(dict, "x1")?, "x1")?;
        let y1 = extract_finite_f64(&get_req(dict, "y1")?, "y1")?;
        Ok(Self {
            schema_version: sv,
            x0,
            y0,
            x1,
            y1,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("x0", self.x0)?;
        d.set_item("y0", self.y0)?;
        d.set_item("x1", self.x1)?;
        d.set_item("y1", self.y1)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Line4 {
    pub schema_version: i64,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

impl Line4 {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let x0 = extract_finite_f64(&get_req(dict, "x0")?, "x0")?;
        let y0 = extract_finite_f64(&get_req(dict, "y0")?, "y0")?;
        let x1 = extract_finite_f64(&get_req(dict, "x1")?, "x1")?;
        let y1 = extract_finite_f64(&get_req(dict, "y1")?, "y1")?;
        Ok(Self {
            schema_version: sv,
            x0,
            y0,
            x1,
            y1,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("x0", self.x0)?;
        d.set_item("y0", self.y0)?;
        d.set_item("x1", self.x1)?;
        d.set_item("y1", self.y1)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub width: Option<f64>,
    pub color: Option<f64>,
    pub source_order: i64,
}

impl LineDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let width = match get_opt(dict, "width")? {
            Some(w) => Some(extract_finite_f64(&w, "width")?),
            None => None,
        };
        let color = match get_opt(dict, "color")? {
            Some(c) => Some(extract_finite_f64(&c, "color")?),
            None => None,
        };
        let source_order: i64 = get_req(dict, "source_order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            rect,
            width,
            color,
            source_order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("width", self.width)?;
        d.set_item("color", self.color)?;
        d.set_item("source_order", self.source_order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DrawingDto {
    pub schema_version: i64,
    pub kind: String,
    pub lines: Vec<LineDto>,
    pub rect: Rect4,
    pub fill: Option<f64>,
    pub stroke: Option<f64>,
    pub clip: Option<Rect4>,
    pub source_order: i64,
}

impl DrawingDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let kind: String = get_req(dict, "kind")?.extract()?;
        let lines_list: Bound<'_, PyList> = get_req(dict, "lines")?.extract()?;
        let mut lines = Vec::with_capacity(lines_list.len());
        for item in lines_list.iter() {
            let l_dict = item.downcast::<PyDict>()?;
            lines.push(LineDto::from_py(&l_dict)?);
        }
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let fill = match get_opt(dict, "fill")? {
            Some(f) => Some(extract_finite_f64(&f, "fill")?),
            None => None,
        };
        let stroke = match get_opt(dict, "stroke")? {
            Some(s) => Some(extract_finite_f64(&s, "stroke")?),
            None => None,
        };
        let clip = match get_opt(dict, "clip")? {
            Some(c) => Some(Rect4::from_py(&c.downcast::<PyDict>()?.clone())?),
            None => None,
        };
        let source_order: i64 = get_req(dict, "source_order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            kind,
            lines,
            rect,
            fill,
            stroke,
            clip,
            source_order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("kind", &self.kind)?;
        let lines_list = PyList::empty_bound(py);
        for l in &self.lines {
            lines_list.append(l.to_py(py)?)?;
        }
        d.set_item("lines", lines_list)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("fill", self.fill)?;
        d.set_item("stroke", self.stroke)?;
        match &self.clip {
            Some(c) => d.set_item("clip", c.to_py(py)?)?,
            None => d.set_item("clip", py.None())?,
        }
        d.set_item("source_order", self.source_order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct OrderedRectDto {
    pub schema_version: i64,
    pub id: i64,
    pub rect: Rect4,
    pub order: i64,
}

impl OrderedRectDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let id: i64 = get_req(dict, "id")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let order: i64 = get_req(dict, "order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            id,
            rect,
            order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("id", self.id)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("order", self.order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CharacterDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub order: i64,
}

impl CharacterDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let order: i64 = get_req(dict, "order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("order", self.order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WordDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub order: i64,
    pub block: Option<i64>,
    pub line: Option<i64>,
}

impl WordDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let order: i64 = get_req(dict, "order")?.extract()?;
        let block: Option<i64> = match get_opt(dict, "block")? {
            Some(b) => Some(b.extract()?),
            None => None,
        };
        let line: Option<i64> = match get_opt(dict, "line")? {
            Some(l) => Some(l.extract()?),
            None => None,
        };
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            order,
            block,
            line,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("order", self.order)?;
        d.set_item("block", self.block)?;
        d.set_item("line", self.line)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct SourcePositionDto {
    pub schema_version: i64,
    pub block: i64,
    pub line: i64,
}

impl SourcePositionDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let block: i64 = get_req(dict, "block")?.extract()?;
        let line: i64 = get_req(dict, "line")?.extract()?;
        Ok(Self {
            schema_version: sv,
            block,
            line,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("block", self.block)?;
        d.set_item("line", self.line)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeSpanDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub font: Option<String>,
    pub size: Option<f64>,
    pub flags: Option<i64>,
    pub order: i64,
    pub characters: Vec<CharacterDto>,
    pub source_position: SourcePositionDto,
    pub block: i64,
    pub line: i64,
}

impl NativeSpanDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let font: Option<String> = match get_opt(dict, "font")? {
            Some(f) => Some(f.extract()?),
            None => None,
        };
        let size = match get_opt(dict, "size")? {
            Some(s) => Some(extract_finite_f64(&s, "size")?),
            None => None,
        };
        let flags: Option<i64> = match get_opt(dict, "flags")? {
            Some(f) => Some(f.extract()?),
            None => None,
        };
        let order: i64 = get_req(dict, "order")?.extract()?;
        let char_list: Bound<'_, PyList> = get_req(dict, "characters")?.extract()?;
        let mut characters = Vec::with_capacity(char_list.len());
        for c in char_list.iter() {
            let cd = c.downcast::<PyDict>()?;
            characters.push(CharacterDto::from_py(&cd)?);
        }
        let sp = SourcePositionDto::from_py(
            &get_req(dict, "source_position")?
                .downcast::<PyDict>()?
                .clone(),
        )?;
        let block: i64 = get_req(dict, "block")?.extract()?;
        let line: i64 = get_req(dict, "line")?.extract()?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            font,
            size,
            flags,
            order,
            characters,
            source_position: sp,
            block,
            line,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("font", &self.font)?;
        d.set_item("size", self.size)?;
        d.set_item("flags", self.flags)?;
        d.set_item("order", self.order)?;
        let cl = PyList::empty_bound(py);
        for c in &self.characters {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("characters", cl)?;
        d.set_item("source_position", self.source_position.to_py(py)?)?;
        d.set_item("block", self.block)?;
        d.set_item("line", self.line)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TextRunDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub span_refs: Vec<i64>,
    pub source_start: i64,
    pub source_end: i64,
    pub order: i64,
}

impl TextRunDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let span_refs: Vec<i64> = get_req(dict, "span_refs")?.extract()?;
        let source_start: i64 = get_req(dict, "source_start")?.extract()?;
        let source_end: i64 = get_req(dict, "source_end")?.extract()?;
        let order: i64 = get_req(dict, "order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            span_refs,
            source_start,
            source_end,
            order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("span_refs", &self.span_refs)?;
        d.set_item("source_start", self.source_start)?;
        d.set_item("source_end", self.source_end)?;
        d.set_item("order", self.order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct AtomDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub run_refs: Vec<i64>,
    pub row_hint: Option<i64>,
    pub col_hint: Option<i64>,
    pub order: i64,
}

impl AtomDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let run_refs: Vec<i64> = get_req(dict, "run_refs")?.extract()?;
        let row_hint: Option<i64> = match get_opt(dict, "row_hint")? {
            Some(rh) => Some(rh.extract()?),
            None => None,
        };
        let col_hint: Option<i64> = match get_opt(dict, "col_hint")? {
            Some(ch) => Some(ch.extract()?),
            None => None,
        };
        let order: i64 = get_req(dict, "order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            run_refs,
            row_hint,
            col_hint,
            order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("run_refs", &self.run_refs)?;
        d.set_item("row_hint", self.row_hint)?;
        d.set_item("col_hint", self.col_hint)?;
        d.set_item("order", self.order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ColumnBandDto {
    pub schema_version: i64,
    pub x0: f64,
    pub x1: f64,
    pub source_atoms: Vec<i64>,
    pub order: i64,
}

impl ColumnBandDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let x0 = extract_finite_f64(&get_req(dict, "x0")?, "x0")?;
        let x1 = extract_finite_f64(&get_req(dict, "x1")?, "x1")?;
        let source_atoms: Vec<i64> = get_req(dict, "source_atoms")?.extract()?;
        let order: i64 = get_req(dict, "order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            x0,
            x1,
            source_atoms,
            order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("x0", self.x0)?;
        d.set_item("x1", self.x1)?;
        d.set_item("source_atoms", &self.source_atoms)?;
        d.set_item("order", self.order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RegionDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub source_order: i64,
    pub allowed: bool,
}

impl RegionDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let source_order: i64 = get_req(dict, "source_order")?.extract()?;
        let allowed: bool = get_req(dict, "allowed")?.extract()?;
        Ok(Self {
            schema_version: sv,
            rect,
            source_order,
            allowed,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("source_order", self.source_order)?;
        d.set_item("allowed", self.allowed)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct GridDto {
    pub schema_version: i64,
    pub rows: i64,
    pub cols: i64,
    pub row_edges: Vec<f64>,
    pub col_edges: Vec<f64>,
    pub occupancy: Vec<Vec<Option<i64>>>,
}

impl GridDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rows: i64 = get_req(dict, "rows")?.extract()?;
        let cols: i64 = get_req(dict, "cols")?.extract()?;

        let re_list: Bound<'_, PyList> = get_req(dict, "row_edges")?.extract()?;
        let mut row_edges = Vec::with_capacity(re_list.len());
        for item in re_list.iter() {
            row_edges.push(extract_finite_f64(&item, "row_edges")?);
        }

        let ce_list: Bound<'_, PyList> = get_req(dict, "col_edges")?.extract()?;
        let mut col_edges = Vec::with_capacity(ce_list.len());
        for item in ce_list.iter() {
            col_edges.push(extract_finite_f64(&item, "col_edges")?);
        }

        let occ_list: Bound<'_, PyList> = get_req(dict, "occupancy")?.extract()?;
        let mut occupancy = Vec::with_capacity(occ_list.len());
        for row in occ_list.iter() {
            let row_list: Bound<'_, PyList> = row.extract()?;
            let mut r_vec = Vec::with_capacity(row_list.len());
            for item in row_list.iter() {
                if item.is_none() {
                    r_vec.push(None);
                } else {
                    let idx: i64 = item.extract()?;
                    r_vec.push(Some(idx));
                }
            }
            occupancy.push(r_vec);
        }

        Ok(Self {
            schema_version: sv,
            rows,
            cols,
            row_edges,
            col_edges,
            occupancy,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rows", self.rows)?;
        d.set_item("cols", self.cols)?;
        d.set_item("row_edges", &self.row_edges)?;
        d.set_item("col_edges", &self.col_edges)?;

        let occ_list = PyList::empty_bound(py);
        for row in &self.occupancy {
            let row_list = PyList::empty_bound(py);
            for item in row {
                match item {
                    Some(idx) => row_list.append(*idx)?,
                    None => row_list.append(py.None())?,
                }
            }
            occ_list.append(row_list)?;
        }
        d.set_item("occupancy", occ_list)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PhysicalCell {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub row: i64,
    pub col: i64,
    pub source_refs: Vec<i64>,
}

impl PhysicalCell {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let row: i64 = get_req(dict, "row")?.extract()?;
        let col: i64 = get_req(dict, "col")?.extract()?;
        let source_refs: Vec<i64> = get_req(dict, "source_refs")?.extract()?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            row,
            col,
            source_refs,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("row", self.row)?;
        d.set_item("col", self.col)?;
        d.set_item("source_refs", &self.source_refs)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CellDto {
    pub schema_version: i64,
    pub text: String,
    pub row: i64,
    pub col: i64,
    pub rect: Rect4,
    pub rowspan: i64,
    pub colspan: i64,
    pub source: Option<PhysicalCell>,
}

impl CellDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let text: String = get_req(dict, "text")?.extract()?;
        let row: i64 = get_req(dict, "row")?.extract()?;
        let col: i64 = get_req(dict, "col")?.extract()?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let rowspan: i64 = get_req(dict, "rowspan")?.extract()?;
        let colspan: i64 = get_req(dict, "colspan")?.extract()?;
        let source = match get_opt(dict, "source")? {
            Some(s) => Some(PhysicalCell::from_py(&s.downcast::<PyDict>()?.clone())?),
            None => None,
        };
        Ok(Self {
            schema_version: sv,
            text,
            row,
            col,
            rect,
            rowspan,
            colspan,
            source,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("text", &self.text)?;
        d.set_item("row", self.row)?;
        d.set_item("col", self.col)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("rowspan", self.rowspan)?;
        d.set_item("colspan", self.colspan)?;
        match &self.source {
            Some(s) => d.set_item("source", s.to_py(py)?)?,
            None => d.set_item("source", py.None())?,
        }
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct LogicalGridDto {
    pub schema_version: i64,
    pub grid: GridDto,
    pub cells: Vec<CellDto>,
    pub empty_slots: Vec<Vec<i64>>,
}

impl LogicalGridDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let grid = GridDto::from_py(&get_req(dict, "grid")?.downcast::<PyDict>()?.clone())?;

        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }

        let empty_slots_list: Bound<'_, PyList> = get_req(dict, "empty_slots")?.extract()?;
        let mut empty_slots = Vec::with_capacity(empty_slots_list.len());
        for slot in empty_slots_list.iter() {
            let s_pair: Vec<i64> = slot.extract()?;
            empty_slots.push(s_pair);
        }

        Ok(Self {
            schema_version: sv,
            grid,
            cells,
            empty_slots,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("grid", self.grid.to_py(py)?)?;

        let cells_list = PyList::empty_bound(py);
        for c in &self.cells {
            cells_list.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cells_list)?;
        d.set_item("empty_slots", &self.empty_slots)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableCandidateDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub source: String,
    pub confidence: Option<f64>,
    pub rows: i64,
    pub cols: i64,
    pub cells: Vec<CellDto>,
}

impl TableCandidateDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let source: String = get_req(dict, "source")?.extract()?;
        let confidence = match get_opt(dict, "confidence")? {
            Some(c) => Some(extract_finite_f64(&c, "confidence")?),
            None => None,
        };
        let rows: i64 = get_req(dict, "rows")?.extract()?;
        let cols: i64 = get_req(dict, "cols")?.extract()?;
        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            rect,
            source,
            confidence,
            rows,
            cols,
            cells,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("source", &self.source)?;
        d.set_item("confidence", self.confidence)?;
        d.set_item("rows", self.rows)?;
        d.set_item("cols", self.cols)?;
        let cells_list = PyList::empty_bound(py);
        for c in &self.cells {
            cells_list.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cells_list)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RowClusterDto {
    pub schema_version: i64,
    pub row_index: i64,
    pub y0: f64,
    pub y1: f64,
    pub item_indices: Vec<i64>,
}

impl RowClusterDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let row_index: i64 = get_req(dict, "row_index")?.extract()?;
        let y0 = extract_finite_f64(&get_req(dict, "y0")?, "y0")?;
        let y1 = extract_finite_f64(&get_req(dict, "y1")?, "y1")?;
        let item_indices: Vec<i64> = get_req(dict, "item_indices")?.extract()?;
        Ok(Self {
            schema_version: sv,
            row_index,
            y0,
            y1,
            item_indices,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("row_index", self.row_index)?;
        d.set_item("y0", self.y0)?;
        d.set_item("y1", self.y1)?;
        d.set_item("item_indices", &self.item_indices)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ColumnClusterDto {
    pub schema_version: i64,
    pub col_index: i64,
    pub x0: f64,
    pub x1: f64,
    pub item_indices: Vec<i64>,
}

impl ColumnClusterDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let col_index: i64 = get_req(dict, "col_index")?.extract()?;
        let x0 = extract_finite_f64(&get_req(dict, "x0")?, "x0")?;
        let x1 = extract_finite_f64(&get_req(dict, "x1")?, "x1")?;
        let item_indices: Vec<i64> = get_req(dict, "item_indices")?.extract()?;
        Ok(Self {
            schema_version: sv,
            col_index,
            x0,
            x1,
            item_indices,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("col_index", self.col_index)?;
        d.set_item("x0", self.x0)?;
        d.set_item("x1", self.x1)?;
        d.set_item("item_indices", &self.item_indices)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct OutputOrderMode {
    pub schema_version: i64,
    pub value: String,
}

impl OutputOrderMode {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let value: String = get_req(dict, "value")?.extract()?;
        Ok(Self {
            schema_version: sv,
            value,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("value", &self.value)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct StructureConfig {
    pub schema_version: i64,
    pub line_tolerance: f64,
    pub row_tolerance: f64,
    pub column_tolerance: f64,
    pub span_tolerance: f64,
    pub numeric_tolerance: f64,
}

impl StructureConfig {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let line_tolerance =
            extract_finite_f64(&get_req(dict, "line_tolerance")?, "line_tolerance")?;
        let row_tolerance = extract_finite_f64(&get_req(dict, "row_tolerance")?, "row_tolerance")?;
        let column_tolerance =
            extract_finite_f64(&get_req(dict, "column_tolerance")?, "column_tolerance")?;
        let span_tolerance =
            extract_finite_f64(&get_req(dict, "span_tolerance")?, "span_tolerance")?;
        let numeric_tolerance =
            extract_finite_f64(&get_req(dict, "numeric_tolerance")?, "numeric_tolerance")?;
        Ok(Self {
            schema_version: sv,
            line_tolerance,
            row_tolerance,
            column_tolerance,
            span_tolerance,
            numeric_tolerance,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("line_tolerance", self.line_tolerance)?;
        d.set_item("row_tolerance", self.row_tolerance)?;
        d.set_item("column_tolerance", self.column_tolerance)?;
        d.set_item("span_tolerance", self.span_tolerance)?;
        d.set_item("numeric_tolerance", self.numeric_tolerance)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackgroundDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub color: Option<f64>,
    pub opacity: Option<f64>,
    pub source_order: i64,
}

impl BackgroundDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let color = match get_opt(dict, "color")? {
            Some(c) => Some(extract_finite_f64(&c, "color")?),
            None => None,
        };
        let opacity = match get_opt(dict, "opacity")? {
            Some(o) => Some(extract_finite_f64(&o, "opacity")?),
            None => None,
        };
        let source_order: i64 = get_req(dict, "source_order")?.extract()?;
        Ok(Self {
            schema_version: sv,
            rect,
            color,
            opacity,
            source_order,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("color", self.color)?;
        d.set_item("opacity", self.opacity)?;
        d.set_item("source_order", self.source_order)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackgroundGroupDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub row_index: i64,
    pub source_indices: Vec<i64>,
}

impl BackgroundGroupDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let row_index: i64 = get_req(dict, "row_index")?.extract()?;
        let source_indices: Vec<i64> = get_req(dict, "source_indices")?.extract()?;
        Ok(Self {
            schema_version: sv,
            rect,
            row_index,
            source_indices,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("row_index", self.row_index)?;
        d.set_item("source_indices", &self.source_indices)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RowBandDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub row_index: i64,
    pub source_backgrounds: Vec<i64>,
    pub words: Vec<WordDto>,
    pub cells: Vec<CellDto>,
}

impl RowBandDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let row_index: i64 = get_req(dict, "row_index")?.extract()?;
        let source_backgrounds: Vec<i64> = get_req(dict, "source_backgrounds")?.extract()?;
        let words_list: Bound<'_, PyList> = get_req(dict, "words")?.extract()?;
        let mut words = Vec::with_capacity(words_list.len());
        for w in words_list.iter() {
            words.push(WordDto::from_py(&w.downcast::<PyDict>()?.clone())?);
        }
        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            rect,
            row_index,
            source_backgrounds,
            words,
            cells,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("rect", self.rect.to_py(py)?)?;
        d.set_item("row_index", self.row_index)?;
        d.set_item("source_backgrounds", &self.source_backgrounds)?;
        let wl = PyList::empty_bound(py);
        for w in &self.words {
            wl.append(w.to_py(py)?)?;
        }
        d.set_item("words", wl)?;
        let cl = PyList::empty_bound(py);
        for c in &self.cells {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cl)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeRecoveryInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub spans: Vec<NativeSpanDto>,
    pub region: RegionDto,
    pub config: StructureConfig,
}

impl NativeRecoveryInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let page = PageDto::from_py(&get_req(dict, "page")?.downcast::<PyDict>()?.clone())?;
        let spans_list: Bound<'_, PyList> = get_req(dict, "spans")?.extract()?;
        let mut spans = Vec::with_capacity(spans_list.len());
        for s in spans_list.iter() {
            spans.push(NativeSpanDto::from_py(&s.downcast::<PyDict>()?.clone())?);
        }
        let region = RegionDto::from_py(&get_req(dict, "region")?.downcast::<PyDict>()?.clone())?;
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            page,
            spans,
            region,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("page", self.page.to_py(py)?)?;
        let sl = PyList::empty_bound(py);
        for s in &self.spans {
            sl.append(s.to_py(py)?)?;
        }
        d.set_item("spans", sl)?;
        d.set_item("region", self.region.to_py(py)?)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeRecoveryOutput {
    pub schema_version: i64,
    pub candidates: Vec<TableCandidateDto>,
    pub atoms: Vec<AtomDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl NativeRecoveryOutput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let c_list: Bound<'_, PyList> = get_req(dict, "candidates")?.extract()?;
        let mut candidates = Vec::with_capacity(c_list.len());
        for c in c_list.iter() {
            candidates.push(TableCandidateDto::from_py(
                &c.downcast::<PyDict>()?.clone(),
            )?);
        }
        let a_list: Bound<'_, PyList> = get_req(dict, "atoms")?.extract()?;
        let mut atoms = Vec::with_capacity(a_list.len());
        for a in a_list.iter() {
            atoms.push(AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
        }
        let d_list: Bound<'_, PyList> = get_req(dict, "diagnostics")?.extract()?;
        let mut diagnostics = Vec::with_capacity(d_list.len());
        for d in d_list.iter() {
            diagnostics.push(DiagnosticDto::from_py(&d.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            candidates,
            atoms,
            diagnostics,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        let cl = PyList::empty_bound(py);
        for c in &self.candidates {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("candidates", cl)?;
        let al = PyList::empty_bound(py);
        for a in &self.atoms {
            al.append(a.to_py(py)?)?;
        }
        d.set_item("atoms", al)?;
        let dl = PyList::empty_bound(py);
        for diag in &self.diagnostics {
            dl.append(diag.to_py(py)?)?;
        }
        d.set_item("diagnostics", dl)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeRegionInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub atoms: Vec<AtomDto>,
    pub bands: Vec<ColumnBandDto>,
    pub config: StructureConfig,
}

impl NativeRegionInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let region = RegionDto::from_py(&get_req(dict, "region")?.downcast::<PyDict>()?.clone())?;
        let atoms_list: Bound<'_, PyList> = get_req(dict, "atoms")?.extract()?;
        let mut atoms = Vec::with_capacity(atoms_list.len());
        for a in atoms_list.iter() {
            atoms.push(AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
        }
        let bands_list: Bound<'_, PyList> = get_req(dict, "bands")?.extract()?;
        let mut bands = Vec::with_capacity(bands_list.len());
        for b in bands_list.iter() {
            bands.push(ColumnBandDto::from_py(&b.downcast::<PyDict>()?.clone())?);
        }
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            region,
            atoms,
            bands,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("region", self.region.to_py(py)?)?;
        let al = PyList::empty_bound(py);
        for a in &self.atoms {
            al.append(a.to_py(py)?)?;
        }
        d.set_item("atoms", al)?;
        let bl = PyList::empty_bound(py);
        for b in &self.bands {
            bl.append(b.to_py(py)?)?;
        }
        d.set_item("bands", bl)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeRegionOutput {
    pub schema_version: i64,
    pub grid: LogicalGridDto,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl NativeRegionOutput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let grid = LogicalGridDto::from_py(&get_req(dict, "grid")?.downcast::<PyDict>()?.clone())?;
        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }
        let d_list: Bound<'_, PyList> = get_req(dict, "diagnostics")?.extract()?;
        let mut diagnostics = Vec::with_capacity(d_list.len());
        for d in d_list.iter() {
            diagnostics.push(DiagnosticDto::from_py(&d.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            grid,
            cells,
            diagnostics,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("grid", self.grid.to_py(py)?)?;
        let cl = PyList::empty_bound(py);
        for c in &self.cells {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cl)?;
        let dl = PyList::empty_bound(py);
        for diag in &self.diagnostics {
            dl.append(diag.to_py(py)?)?;
        }
        d.set_item("diagnostics", dl)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WirelessRecoveryInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub spans: Vec<NativeSpanDto>,
    pub regions: Vec<RegionDto>,
    pub config: StructureConfig,
}

impl WirelessRecoveryInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let page = PageDto::from_py(&get_req(dict, "page")?.downcast::<PyDict>()?.clone())?;
        let spans_list: Bound<'_, PyList> = get_req(dict, "spans")?.extract()?;
        let mut spans = Vec::with_capacity(spans_list.len());
        for s in spans_list.iter() {
            spans.push(NativeSpanDto::from_py(&s.downcast::<PyDict>()?.clone())?);
        }
        let regions_list: Bound<'_, PyList> = get_req(dict, "regions")?.extract()?;
        let mut regions = Vec::with_capacity(regions_list.len());
        for r in regions_list.iter() {
            regions.push(RegionDto::from_py(&r.downcast::<PyDict>()?.clone())?);
        }
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            page,
            spans,
            regions,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("page", self.page.to_py(py)?)?;
        let sl = PyList::empty_bound(py);
        for s in &self.spans {
            sl.append(s.to_py(py)?)?;
        }
        d.set_item("spans", sl)?;
        let rl = PyList::empty_bound(py);
        for r in &self.regions {
            rl.append(r.to_py(py)?)?;
        }
        d.set_item("regions", rl)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WirelessRecoveryOutput {
    pub schema_version: i64,
    pub candidates: Vec<TableCandidateDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl WirelessRecoveryOutput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let c_list: Bound<'_, PyList> = get_req(dict, "candidates")?.extract()?;
        let mut candidates = Vec::with_capacity(c_list.len());
        for c in c_list.iter() {
            candidates.push(TableCandidateDto::from_py(
                &c.downcast::<PyDict>()?.clone(),
            )?);
        }
        let d_list: Bound<'_, PyList> = get_req(dict, "diagnostics")?.extract()?;
        let mut diagnostics = Vec::with_capacity(d_list.len());
        for d in d_list.iter() {
            diagnostics.push(DiagnosticDto::from_py(&d.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            candidates,
            diagnostics,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        let cl = PyList::empty_bound(py);
        for c in &self.candidates {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("candidates", cl)?;
        let dl = PyList::empty_bound(py);
        for diag in &self.diagnostics {
            dl.append(diag.to_py(py)?)?;
        }
        d.set_item("diagnostics", dl)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ZebraInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub backgrounds: Vec<BackgroundDto>,
    pub words: Vec<WordDto>,
    pub region: RegionDto,
    pub config: StructureConfig,
}

impl ZebraInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let page = PageDto::from_py(&get_req(dict, "page")?.downcast::<PyDict>()?.clone())?;
        let bg_list: Bound<'_, PyList> = get_req(dict, "backgrounds")?.extract()?;
        let mut backgrounds = Vec::with_capacity(bg_list.len());
        for b in bg_list.iter() {
            backgrounds.push(BackgroundDto::from_py(&b.downcast::<PyDict>()?.clone())?);
        }
        let w_list: Bound<'_, PyList> = get_req(dict, "words")?.extract()?;
        let mut words = Vec::with_capacity(w_list.len());
        for w in w_list.iter() {
            words.push(WordDto::from_py(&w.downcast::<PyDict>()?.clone())?);
        }
        let region = RegionDto::from_py(&get_req(dict, "region")?.downcast::<PyDict>()?.clone())?;
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            page,
            backgrounds,
            words,
            region,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("page", self.page.to_py(py)?)?;
        let bl = PyList::empty_bound(py);
        for b in &self.backgrounds {
            bl.append(b.to_py(py)?)?;
        }
        d.set_item("backgrounds", bl)?;
        let wl = PyList::empty_bound(py);
        for w in &self.words {
            wl.append(w.to_py(py)?)?;
        }
        d.set_item("words", wl)?;
        d.set_item("region", self.region.to_py(py)?)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct EnglishGridInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub words: Vec<WordDto>,
    pub backgrounds: Vec<BackgroundDto>,
    pub horizontal_lines: Vec<f64>,
    pub config: StructureConfig,
}

impl EnglishGridInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let region = RegionDto::from_py(&get_req(dict, "region")?.downcast::<PyDict>()?.clone())?;
        let w_list: Bound<'_, PyList> = get_req(dict, "words")?.extract()?;
        let mut words = Vec::with_capacity(w_list.len());
        for w in w_list.iter() {
            words.push(WordDto::from_py(&w.downcast::<PyDict>()?.clone())?);
        }
        let bg_list: Bound<'_, PyList> = get_req(dict, "backgrounds")?.extract()?;
        let mut backgrounds = Vec::with_capacity(bg_list.len());
        for b in bg_list.iter() {
            backgrounds.push(BackgroundDto::from_py(&b.downcast::<PyDict>()?.clone())?);
        }
        let horizontal_lines = match get_opt(dict, "horizontal_lines")? {
            Some(value) => value.extract()?,
            None => Vec::new(),
        };
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            region,
            words,
            backgrounds,
            horizontal_lines,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("region", self.region.to_py(py)?)?;
        let wl = PyList::empty_bound(py);
        for w in &self.words {
            wl.append(w.to_py(py)?)?;
        }
        d.set_item("words", wl)?;
        let bl = PyList::empty_bound(py);
        for b in &self.backgrounds {
            bl.append(b.to_py(py)?)?;
        }
        d.set_item("backgrounds", bl)?;
        d.set_item("horizontal_lines", &self.horizontal_lines)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct GeneralWirelessInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub atoms: Vec<AtomDto>,
    pub bands: Vec<ColumnBandDto>,
    pub config: StructureConfig,
}

impl GeneralWirelessInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let region = RegionDto::from_py(&get_req(dict, "region")?.downcast::<PyDict>()?.clone())?;
        let a_list: Bound<'_, PyList> = get_req(dict, "atoms")?.extract()?;
        let mut atoms = Vec::with_capacity(a_list.len());
        for a in a_list.iter() {
            atoms.push(AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
        }
        let b_list: Bound<'_, PyList> = get_req(dict, "bands")?.extract()?;
        let mut bands = Vec::with_capacity(b_list.len());
        for b in b_list.iter() {
            bands.push(ColumnBandDto::from_py(&b.downcast::<PyDict>()?.clone())?);
        }
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            region,
            atoms,
            bands,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("region", self.region.to_py(py)?)?;
        let al = PyList::empty_bound(py);
        for a in &self.atoms {
            al.append(a.to_py(py)?)?;
        }
        d.set_item("atoms", al)?;
        let bl = PyList::empty_bound(py);
        for b in &self.bands {
            bl.append(b.to_py(py)?)?;
        }
        d.set_item("bands", bl)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct LegacyAlignmentInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub words: Vec<WordDto>,
    pub config: StructureConfig,
}

impl LegacyAlignmentInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let region = RegionDto::from_py(&get_req(dict, "region")?.downcast::<PyDict>()?.clone())?;
        let w_list: Bound<'_, PyList> = get_req(dict, "words")?.extract()?;
        let mut words = Vec::with_capacity(w_list.len());
        for w in w_list.iter() {
            words.push(WordDto::from_py(&w.downcast::<PyDict>()?.clone())?);
        }
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            region,
            words,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("region", self.region.to_py(py)?)?;
        let wl = PyList::empty_bound(py);
        for w in &self.words {
            wl.append(w.to_py(py)?)?;
        }
        d.set_item("words", wl)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DiagnosticValueDto {
    pub schema_version: i64,
    pub kind: String,
    pub text: String,
}

impl DiagnosticValueDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let kind: String = get_req(dict, "kind")?.extract()?;
        let text: String = get_req(dict, "text")?.extract()?;
        Ok(Self {
            schema_version: sv,
            kind,
            text,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("kind", &self.kind)?;
        d.set_item("text", &self.text)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DiagnosticDto {
    pub schema_version: i64,
    pub status: String,
    pub path: String,
    pub error_type: Option<String>,
    pub message: Option<String>,
    pub traceback_id: Option<String>,
    pub field: Option<String>,
    pub python_value: Option<DiagnosticValueDto>,
    pub rust_value: Option<DiagnosticValueDto>,
    pub classification: Option<String>,
}

impl DiagnosticDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let status: String = get_req(dict, "status")?.extract()?;
        let path: String = get_req(dict, "path")?.extract()?;
        let error_type: Option<String> = match get_opt(dict, "error_type")? {
            Some(e) => Some(e.extract()?),
            None => None,
        };
        let message: Option<String> = match get_opt(dict, "message")? {
            Some(m) => Some(m.extract()?),
            None => None,
        };
        let traceback_id: Option<String> = match get_opt(dict, "traceback_id")? {
            Some(t) => Some(t.extract()?),
            None => None,
        };
        let field: Option<String> = match get_opt(dict, "field")? {
            Some(f) => Some(f.extract()?),
            None => None,
        };
        let python_value = match get_opt(dict, "python_value")? {
            Some(pv) => Some(DiagnosticValueDto::from_py(
                &pv.downcast::<PyDict>()?.clone(),
            )?),
            None => None,
        };
        let rust_value = match get_opt(dict, "rust_value")? {
            Some(rv) => Some(DiagnosticValueDto::from_py(
                &rv.downcast::<PyDict>()?.clone(),
            )?),
            None => None,
        };
        let classification: Option<String> = match get_opt(dict, "classification")? {
            Some(c) => Some(c.extract()?),
            None => None,
        };
        Ok(Self {
            schema_version: sv,
            status,
            path,
            error_type,
            message,
            traceback_id,
            field,
            python_value,
            rust_value,
            classification,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("status", &self.status)?;
        d.set_item("path", &self.path)?;
        d.set_item("error_type", &self.error_type)?;
        d.set_item("message", &self.message)?;
        d.set_item("traceback_id", &self.traceback_id)?;
        d.set_item("field", &self.field)?;
        match &self.python_value {
            Some(pv) => d.set_item("python_value", pv.to_py(py)?)?,
            None => d.set_item("python_value", py.None())?,
        }
        match &self.rust_value {
            Some(rv) => d.set_item("rust_value", rv.to_py(py)?)?,
            None => d.set_item("rust_value", py.None())?,
        }
        d.set_item("classification", &self.classification)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WiredRegionInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub h_lines: Vec<LineDto>,
    pub v_lines: Vec<LineDto>,
    pub words: Vec<WordDto>,
    pub tolerance: f64,
}

impl WiredRegionInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let page_dict = get_req(dict, "page")?.downcast::<PyDict>()?.clone();
        let page = PageDto::from_py(&page_dict)?;

        let hl_list = get_req(dict, "h_lines")?.downcast::<PyList>()?.clone();
        let mut h_lines = Vec::new();
        for item in hl_list.iter() {
            h_lines.push(LineDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        let vl_list = get_req(dict, "v_lines")?.downcast::<PyList>()?.clone();
        let mut v_lines = Vec::new();
        for item in vl_list.iter() {
            v_lines.push(LineDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        let w_list = get_req(dict, "words")?.downcast::<PyList>()?.clone();
        let mut words = Vec::new();
        for item in w_list.iter() {
            words.push(WordDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        let tolerance = extract_finite_f64(&get_req(dict, "tolerance")?, "tolerance")?;
        Ok(Self {
            schema_version: sv,
            page,
            h_lines,
            v_lines,
            words,
            tolerance,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("page", self.page.to_py(py)?)?;

        let hl_list = PyList::empty_bound(py);
        for l in &self.h_lines {
            hl_list.append(l.to_py(py)?)?;
        }
        d.set_item("h_lines", hl_list)?;

        let vl_list = PyList::empty_bound(py);
        for l in &self.v_lines {
            vl_list.append(l.to_py(py)?)?;
        }
        d.set_item("v_lines", vl_list)?;

        let w_list = PyList::empty_bound(py);
        for w in &self.words {
            w_list.append(w.to_py(py)?)?;
        }
        d.set_item("words", w_list)?;

        d.set_item("tolerance", self.tolerance)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WiredRegionOutput {
    pub schema_version: i64,
    pub regions: Vec<RegionDto>,
    pub grids: Vec<GridDto>,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl WiredRegionOutput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;

        let r_list = get_req(dict, "regions")?.downcast::<PyList>()?.clone();
        let mut regions = Vec::new();
        for item in r_list.iter() {
            regions.push(RegionDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        let g_list = get_req(dict, "grids")?.downcast::<PyList>()?.clone();
        let mut grids = Vec::new();
        for item in g_list.iter() {
            grids.push(GridDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        let c_list = get_req(dict, "cells")?.downcast::<PyList>()?.clone();
        let mut cells = Vec::new();
        for item in c_list.iter() {
            cells.push(CellDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        let d_list = get_req(dict, "diagnostics")?.downcast::<PyList>()?.clone();
        let mut diagnostics = Vec::new();
        for item in d_list.iter() {
            diagnostics.push(DiagnosticDto::from_py(&item.downcast::<PyDict>()?.clone())?);
        }

        Ok(Self {
            schema_version: sv,
            regions,
            grids,
            cells,
            diagnostics,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;

        let r_list = PyList::empty_bound(py);
        for r in &self.regions {
            r_list.append(r.to_py(py)?)?;
        }
        d.set_item("regions", r_list)?;

        let g_list = PyList::empty_bound(py);
        for g in &self.grids {
            g_list.append(g.to_py(py)?)?;
        }
        d.set_item("grids", g_list)?;

        let c_list = PyList::empty_bound(py);
        for c in &self.cells {
            c_list.append(c.to_py(py)?)?;
        }
        d.set_item("cells", c_list)?;

        let d_list = PyList::empty_bound(py);
        for diag in &self.diagnostics {
            d_list.append(diag.to_py(py)?)?;
        }
        d.set_item("diagnostics", d_list)?;

        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeaderGridInput {
    pub schema_version: i64,
    pub grid: LogicalGridDto,
    pub config: StructureConfig,
}

impl HeaderGridInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let grid = LogicalGridDto::from_py(&get_req(dict, "grid")?.downcast::<PyDict>()?.clone())?;
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            grid,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("grid", self.grid.to_py(py)?)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeaderGridOutput {
    pub schema_version: i64,
    pub grid: LogicalGridDto,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl HeaderGridOutput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let grid = LogicalGridDto::from_py(&get_req(dict, "grid")?.downcast::<PyDict>()?.clone())?;
        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }
        let d_list: Bound<'_, PyList> = get_req(dict, "diagnostics")?.extract()?;
        let mut diagnostics = Vec::with_capacity(d_list.len());
        for d in d_list.iter() {
            diagnostics.push(DiagnosticDto::from_py(&d.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            grid,
            cells,
            diagnostics,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        d.set_item("grid", self.grid.to_py(py)?)?;
        let cl = PyList::empty_bound(py);
        for c in &self.cells {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cl)?;
        let dl = PyList::empty_bound(py);
        for diag in &self.diagnostics {
            dl.append(diag.to_py(py)?)?;
        }
        d.set_item("diagnostics", dl)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeaderTokenInput {
    pub schema_version: i64,
    pub cells: Vec<CellDto>,
    pub config: StructureConfig,
}

impl HeaderTokenInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }
        let config =
            StructureConfig::from_py(&get_req(dict, "config")?.downcast::<PyDict>()?.clone())?;
        Ok(Self {
            schema_version: sv,
            cells,
            config,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        let cl = PyList::empty_bound(py);
        for c in &self.cells {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cl)?;
        d.set_item("config", self.config.to_py(py)?)?;
        Ok(d)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct HeaderTokenOutput {
    pub schema_version: i64,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl HeaderTokenOutput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv: i64 = get_req(dict, "schema_version")?.extract()?;
        check_schema_version(sv)?;
        let cells_list: Bound<'_, PyList> = get_req(dict, "cells")?.extract()?;
        let mut cells = Vec::with_capacity(cells_list.len());
        for c in cells_list.iter() {
            cells.push(CellDto::from_py(&c.downcast::<PyDict>()?.clone())?);
        }
        let d_list: Bound<'_, PyList> = get_req(dict, "diagnostics")?.extract()?;
        let mut diagnostics = Vec::with_capacity(d_list.len());
        for d in d_list.iter() {
            diagnostics.push(DiagnosticDto::from_py(&d.downcast::<PyDict>()?.clone())?);
        }
        Ok(Self {
            schema_version: sv,
            cells,
            diagnostics,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        let cl = PyList::empty_bound(py);
        for c in &self.cells {
            cl.append(c.to_py(py)?)?;
        }
        d.set_item("cells", cl)?;
        let dl = PyList::empty_bound(py);
        for diag in &self.diagnostics {
            dl.append(diag.to_py(py)?)?;
        }
        d.set_item("diagnostics", dl)?;
        Ok(d)
    }
}

pub fn roundtrip_dto_py<'py>(
    py: Python<'py>,
    dto_type: &str,
    data: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    match dto_type {
        "page" => {
            let dto = PageDto::from_py(data)?;
            dto.to_py(py)
        }
        "rect" => {
            let dto = Rect4::from_py(data)?;
            dto.to_py(py)
        }
        "line4" => {
            let dto = Line4::from_py(data)?;
            dto.to_py(py)
        }
        "line" => {
            let dto = LineDto::from_py(data)?;
            dto.to_py(py)
        }
        "drawing" => {
            let dto = DrawingDto::from_py(data)?;
            dto.to_py(py)
        }
        "ordered_rect" => {
            let dto = OrderedRectDto::from_py(data)?;
            dto.to_py(py)
        }
        "word" => {
            let dto = WordDto::from_py(data)?;
            dto.to_py(py)
        }
        "character" => {
            let dto = CharacterDto::from_py(data)?;
            dto.to_py(py)
        }
        "source_position" => {
            let dto = SourcePositionDto::from_py(data)?;
            dto.to_py(py)
        }
        "native_span" => {
            let dto = NativeSpanDto::from_py(data)?;
            dto.to_py(py)
        }
        "text_run" => {
            let dto = TextRunDto::from_py(data)?;
            dto.to_py(py)
        }
        "atom" => {
            let dto = AtomDto::from_py(data)?;
            dto.to_py(py)
        }
        "column_band" => {
            let dto = ColumnBandDto::from_py(data)?;
            dto.to_py(py)
        }
        "region" => {
            let dto = RegionDto::from_py(data)?;
            dto.to_py(py)
        }
        "grid" => {
            let dto = GridDto::from_py(data)?;
            dto.to_py(py)
        }
        "physical_cell" => {
            let dto = PhysicalCell::from_py(data)?;
            dto.to_py(py)
        }
        "cell" => {
            let dto = CellDto::from_py(data)?;
            dto.to_py(py)
        }
        "logical_grid" => {
            let dto = LogicalGridDto::from_py(data)?;
            dto.to_py(py)
        }
        "table_candidate" => {
            let dto = TableCandidateDto::from_py(data)?;
            dto.to_py(py)
        }
        "row_cluster" => {
            let dto = RowClusterDto::from_py(data)?;
            dto.to_py(py)
        }
        "column_cluster" => {
            let dto = ColumnClusterDto::from_py(data)?;
            dto.to_py(py)
        }
        "output_order_mode" => {
            let dto = OutputOrderMode::from_py(data)?;
            dto.to_py(py)
        }
        "structure_config" => {
            let dto = StructureConfig::from_py(data)?;
            dto.to_py(py)
        }
        "background" => {
            let dto = BackgroundDto::from_py(data)?;
            dto.to_py(py)
        }
        "background_group" => {
            let dto = BackgroundGroupDto::from_py(data)?;
            dto.to_py(py)
        }
        "row_band" => {
            let dto = RowBandDto::from_py(data)?;
            dto.to_py(py)
        }
        "diagnostic_value" => {
            let dto = DiagnosticValueDto::from_py(data)?;
            dto.to_py(py)
        }
        "diagnostic" => {
            let dto = DiagnosticDto::from_py(data)?;
            dto.to_py(py)
        }
        "wired_region_input" => {
            let dto = WiredRegionInput::from_py(data)?;
            dto.to_py(py)
        }
        "wired_region_output" => {
            let dto = WiredRegionOutput::from_py(data)?;
            dto.to_py(py)
        }
        "native_recovery_input" => {
            let dto = NativeRecoveryInput::from_py(data)?;
            dto.to_py(py)
        }
        "native_recovery_output" => {
            let dto = NativeRecoveryOutput::from_py(data)?;
            dto.to_py(py)
        }
        "native_region_input" => {
            let dto = NativeRegionInput::from_py(data)?;
            dto.to_py(py)
        }
        "native_region_output" => {
            let dto = NativeRegionOutput::from_py(data)?;
            dto.to_py(py)
        }
        "wireless_recovery_input" => {
            let dto = WirelessRecoveryInput::from_py(data)?;
            dto.to_py(py)
        }
        "wireless_recovery_output" => {
            let dto = WirelessRecoveryOutput::from_py(data)?;
            dto.to_py(py)
        }
        "zebra_input" => {
            let dto = ZebraInput::from_py(data)?;
            dto.to_py(py)
        }
        "english_grid_input" => {
            let dto = EnglishGridInput::from_py(data)?;
            dto.to_py(py)
        }
        "general_wireless_input" => {
            let dto = GeneralWirelessInput::from_py(data)?;
            dto.to_py(py)
        }
        "legacy_alignment_input" => {
            let dto = LegacyAlignmentInput::from_py(data)?;
            dto.to_py(py)
        }
        "header_grid_input" => {
            let dto = HeaderGridInput::from_py(data)?;
            dto.to_py(py)
        }
        "header_grid_output" => {
            let dto = HeaderGridOutput::from_py(data)?;
            dto.to_py(py)
        }
        "header_token_input" => {
            let dto = HeaderTokenInput::from_py(data)?;
            dto.to_py(py)
        }
        "header_token_output" => {
            let dto = HeaderTokenOutput::from_py(data)?;
            dto.to_py(py)
        }
        other => Err(PyValueError::new_err(format!(
            "Unknown dto_type '{}'",
            other
        ))),
    }
}
