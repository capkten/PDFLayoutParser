use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList, PyTuple};
use std::collections::BTreeMap;

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
    if val.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!(
            "Field '{}' must be a finite float",
            field_name
        )));
    }
    let num: f64 = val.extract().map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be a float", field_name))
    })?;
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
pub enum OwnedValue {
    Null,
    Bool(bool),
    Integer(i64),
    Float(f64),
    String(String),
    Array(Vec<OwnedValue>),
    Object(BTreeMap<String, OwnedValue>),
}

impl OwnedValue {
    pub fn from_py(value: &Bound<'_, PyAny>, field_name: &str) -> PyResult<Self> {
        if value.is_none() {
            return Ok(Self::Null);
        }
        if value.is_instance_of::<PyBool>() {
            return value
                .extract::<bool>()
                .map(Self::Bool)
                .map_err(|_| PyValueError::new_err(format!("Field '{}' must be a boolean", field_name)));
        }
        if let Ok(integer) = value.extract::<i64>() {
            return Ok(Self::Integer(integer));
        }
        if let Ok(float) = value.extract::<f64>() {
            if !float.is_finite() {
                return Err(PyValueError::new_err(format!(
                    "Field '{}' must be finite, got NaN or Inf",
                    field_name
                )));
            }
            return Ok(Self::Float(float));
        }
        if let Ok(string) = value.extract::<String>() {
            return Ok(Self::String(string));
        }
        if let Ok(list) = value.downcast::<PyList>() {
            let mut values = Vec::with_capacity(list.len());
            for (index, item) in list.iter().enumerate() {
                values.push(Self::from_py(&item, &format!("{}[{}]", field_name, index))?);
            }
            return Ok(Self::Array(values));
        }
        if let Ok(tuple) = value.downcast::<PyTuple>() {
            let mut values = Vec::with_capacity(tuple.len());
            for (index, item) in tuple.iter().enumerate() {
                values.push(Self::from_py(&item, &format!("{}[{}]", field_name, index))?);
            }
            return Ok(Self::Array(values));
        }
        if let Ok(dict) = value.downcast::<PyDict>() {
            let mut values = BTreeMap::new();
            for (key, item) in dict.iter() {
                let key = key.extract::<String>().map_err(|_| {
                    PyValueError::new_err(format!("Field '{}' object keys must be strings", field_name))
                })?;
                values.insert(key.clone(), Self::from_py(&item, &format!("{}.{}", field_name, key))?);
            }
            return Ok(Self::Object(values));
        }
        Err(PyValueError::new_err(format!(
            "Field '{}' contains an unsupported value type",
            field_name
        )))
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        match self {
            Self::Null => Ok(py.None().into_bound(py)),
            Self::Bool(value) => Ok(value.into_py(py).into_bound(py)),
            Self::Integer(value) => Ok(value.into_py(py).into_bound(py)),
            Self::Float(value) => Ok(value.into_py(py).into_bound(py)),
            Self::String(value) => Ok(value.into_py(py).into_bound(py)),
            Self::Array(values) => {
                let list = PyList::empty_bound(py);
                for value in values {
                    list.append(value.to_py(py)?)?;
                }
                Ok(list.into_any())
            }
            Self::Object(values) => {
                let dict = PyDict::new_bound(py);
                for (key, value) in values {
                    dict.set_item(key, value.to_py(py)?)?;
                }
                Ok(dict.into_any())
            }
        }
    }
}

fn required_i64(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<i64> {
    let value = get_req(dict, key)?;
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!("Field '{}' must be an integer", key)));
    }
    value.extract::<i64>().map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be an integer", key))
    })
}

fn required_f64(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<f64> {
    extract_finite_f64(&get_req(dict, key)?, key)
}

fn required_string(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<String> {
    get_req(dict, key)?.extract::<String>().map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be a string", key))
    })
}

fn required_bool(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<bool> {
    let value = get_req(dict, key)?;
    if !value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!("Field '{}' must be a boolean", key)));
    }
    value.extract::<bool>().map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be a boolean", key))
    })
}

fn optional_i64(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<i64>> {
    let value = match get_opt(dict, key)? {
        Some(value) => value,
        None => return Ok(None),
    };
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!("Field '{}' must be an integer", key)));
    }
    value.extract::<i64>().map(Some).map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be an integer", key))
    })
}

fn optional_f64(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<f64>> {
    let value = match get_opt(dict, key)? {
        Some(value) => value,
        None => return Ok(None),
    };
    extract_finite_f64(&value, key).map(Some)
}

fn optional_string(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<String>> {
    let value = match get_opt(dict, key)? {
        Some(value) => value,
        None => return Ok(None),
    };
    value.extract::<String>().map(Some).map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be a string", key))
    })
}

fn required_dict<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyDict>> {
    get_req(dict, key)?.downcast::<PyDict>().map(|value| value.clone()).map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be an object", key))
    })
}

fn required_list<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyList>> {
    get_req(dict, key)?.downcast::<PyList>().map(|value| value.clone()).map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be a list", key))
    })
}

fn required_i64_list(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<i64>> {
    let list = required_list(dict, key)?;
    list.iter()
        .enumerate()
        .map(|(index, value)| {
            if value.is_instance_of::<PyBool>() {
                return Err(PyValueError::new_err(format!(
                    "Field '{}[{}]' must be an integer",
                    key, index
                )));
            }
            value.extract::<i64>().map_err(|_| {
                PyValueError::new_err(format!("Field '{}[{}]' must be an integer", key, index))
            })
        })
        .collect()
}

fn optional_string_list(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<Option<String>>> {
    let list = required_list(dict, key)?;
    list.iter()
        .enumerate()
        .map(|(index, value)| {
            if value.is_none() {
                return Ok(None);
            }
            value.extract::<String>().map(Some).map_err(|_| {
                PyValueError::new_err(format!(
                    "Field '{}[{}]' must be a string or null",
                    key, index
                ))
            })
        })
        .collect()
}

fn optional_f64_list(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<Option<f64>>> {
    let list = required_list(dict, key)?;
    list.iter()
        .enumerate()
        .map(|(index, value)| {
            if value.is_none() {
                return Ok(None);
            }
            extract_finite_f64(&value, &format!("{}[{}]", key, index)).map(Some)
        })
        .collect()
}

fn optional_i64_list(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<Option<i64>>> {
    let list = required_list(dict, key)?;
    list.iter()
        .enumerate()
        .map(|(index, value)| {
            if value.is_none() {
                return Ok(None);
            }
            if value.is_instance_of::<PyBool>() {
                return Err(PyValueError::new_err(format!(
                    "Field '{}[{}]' must be an integer or null",
                    key, index
                )));
            }
            value.extract::<i64>().map(Some).map_err(|_| {
                PyValueError::new_err(format!(
                    "Field '{}[{}]' must be an integer or null",
                    key, index
                ))
            })
        })
        .collect()
}

fn optional_i64_list_present(
    dict: &Bound<'_, PyDict>,
    key: &str,
) -> PyResult<Option<Vec<i64>>> {
    let value = match dict.get_item(key)? {
        Some(value) if !value.is_none() => value,
        _ => return Ok(None),
    };
    let list = value.downcast::<PyList>().map_err(|_| {
        PyValueError::new_err(format!("Field '{}' must be a list", key))
    })?;
    list.iter()
        .enumerate()
        .map(|(index, value)| {
            if value.is_instance_of::<PyBool>() {
                return Err(PyValueError::new_err(format!(
                    "Field '{}[{}]' must be an integer",
                    key, index
                )));
            }
            value.extract::<i64>().map_err(|_| {
                PyValueError::new_err(format!(
                    "Field '{}[{}]' must be an integer",
                    key, index
                ))
            })
        })
        .collect::<PyResult<Vec<_>>>()
        .map(Some)
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let width = required_f64(dict, "width")?;
        let height = required_f64(dict, "height")?;
        let rotation = required_i64(dict, "rotation")?;
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let x0 = required_f64(dict, "x0")?;
        let y0 = required_f64(dict, "y0")?;
        let x1 = required_f64(dict, "x1")?;
        let y1 = required_f64(dict, "y1")?;
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let width = match get_opt(dict, "width")? {
            Some(w) => Some(extract_finite_f64(&w, "width")?),
            None => None,
        };
        let color = match get_opt(dict, "color")? {
            Some(c) => Some(extract_finite_f64(&c, "color")?),
            None => None,
        };
        let source_order = required_i64(dict, "source_order")?;
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
    pub fill: Option<OwnedValue>,
    pub stroke: Option<OwnedValue>,
    pub clip: Option<Rect4>,
    pub source_order: i64,
    pub color: Option<OwnedValue>,
    pub opacity: Option<f64>,
    pub fill_opacity: Option<f64>,
    pub width: Option<f64>,
    pub items: Option<Vec<OwnedValue>>,
    pub extra: BTreeMap<String, OwnedValue>,
}

impl DrawingDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let kind = required_string(dict, "kind")?;
        let lines_list = required_list(dict, "lines")?;
        let mut lines = Vec::with_capacity(lines_list.len());
        for item in lines_list.iter() {
            let l_dict = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'lines' items must be objects")
            })?;
            lines.push(LineDto::from_py(&l_dict)?);
        }
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let fill = match get_opt(dict, "fill")? {
            Some(f) => Some(OwnedValue::from_py(&f, "fill")?),
            None => None,
        };
        let stroke = match get_opt(dict, "stroke")? {
            Some(s) => Some(OwnedValue::from_py(&s, "stroke")?),
            None => None,
        };
        let clip = match get_opt(dict, "clip")? {
            Some(c) => Some(Rect4::from_py(&c.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'clip' must be an object")
            })?.clone())?),
            None => None,
        };
        let source_order = required_i64(dict, "source_order")?;
        let color = match get_opt(dict, "color")? {
            Some(value) => Some(OwnedValue::from_py(&value, "color")?),
            None => None,
        };
        let opacity = match get_opt(dict, "opacity")? {
            Some(value) => Some(extract_finite_f64(&value, "opacity")?),
            None => None,
        };
        let fill_opacity = match get_opt(dict, "fill_opacity")? {
            Some(value) => Some(extract_finite_f64(&value, "fill_opacity")?),
            None => None,
        };
        let width = match get_opt(dict, "width")? {
            Some(value) => Some(extract_finite_f64(&value, "width")?),
            None => None,
        };
        let items = match get_opt(dict, "items")? {
            Some(value) => {
                let list = value.downcast::<PyList>().map_err(|_| {
                    PyValueError::new_err("Field 'items' must be a list")
                })?;
                let mut owned = Vec::with_capacity(list.len());
                for (index, item) in list.iter().enumerate() {
                    owned.push(OwnedValue::from_py(&item, &format!("items[{}]", index))?);
                }
                Some(owned)
            }
            None => None,
        };
        let extra = match get_opt(dict, "extra")? {
            Some(value) => match OwnedValue::from_py(&value, "extra")? {
                OwnedValue::Object(values) => values,
                _ => return Err(PyValueError::new_err("Field 'extra' must be an object")),
            },
            None => BTreeMap::new(),
        };
        Ok(Self {
            schema_version: sv,
            kind,
            lines,
            rect,
            fill,
            stroke,
            clip,
            source_order,
            color,
            opacity,
            fill_opacity,
            width,
            items,
            extra,
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
        match &self.fill {
            Some(value) => d.set_item("fill", value.to_py(py)?)?,
            None => d.set_item("fill", py.None())?,
        }
        match &self.stroke {
            Some(value) => d.set_item("stroke", value.to_py(py)?)?,
            None => d.set_item("stroke", py.None())?,
        }
        match &self.clip {
            Some(c) => d.set_item("clip", c.to_py(py)?)?,
            None => d.set_item("clip", py.None())?,
        }
        d.set_item("source_order", self.source_order)?;
        if let Some(value) = &self.color {
            d.set_item("color", value.to_py(py)?)?;
        }
        if let Some(value) = self.opacity {
            d.set_item("opacity", value)?;
        }
        if let Some(value) = self.fill_opacity {
            d.set_item("fill_opacity", value)?;
        }
        if let Some(value) = self.width {
            d.set_item("width", value)?;
        }
        if let Some(values) = &self.items {
            let list = PyList::empty_bound(py);
            for value in values {
                list.append(value.to_py(py)?)?;
            }
            d.set_item("items", list)?;
        }
        if !self.extra.is_empty() {
            let extra = PyDict::new_bound(py);
            for (key, value) in &self.extra {
                extra.set_item(key, value.to_py(py)?)?;
            }
            d.set_item("extra", extra)?;
        }
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let text = required_string(dict, "text")?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let order = required_i64(dict, "order")?;
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let text = required_string(dict, "text")?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let order = required_i64(dict, "order")?;
        let block = optional_i64(dict, "block")?;
        let line = optional_i64(dict, "line")?;
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let block = required_i64(dict, "block")?;
        let line = required_i64(dict, "line")?;
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let text = required_string(dict, "text")?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let font = optional_string(dict, "font")?;
        let size = match get_opt(dict, "size")? {
            Some(s) => Some(extract_finite_f64(&s, "size")?),
            None => None,
        };
        let flags = optional_i64(dict, "flags")?;
        let order = required_i64(dict, "order")?;
        let char_list = required_list(dict, "characters")?;
        let mut characters = Vec::with_capacity(char_list.len());
        for c in char_list.iter() {
            let cd = c.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'characters' items must be objects")
            })?;
            characters.push(CharacterDto::from_py(&cd)?);
        }
        let sp = SourcePositionDto::from_py(&required_dict(dict, "source_position")?)?;
        let block = required_i64(dict, "block")?;
        let line = required_i64(dict, "line")?;
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

/// Snapshot input extends the native span representation with the complete
/// raw source position captured from PyMuPDF.  Native text stages keep using
/// NativeSpanDto, whose historical block/line source position is sufficient
/// for their current algorithms.
#[derive(Debug, Clone, PartialEq)]
pub struct NativeSpanInputDto {
    pub span: NativeSpanDto,
    pub raw_source_position: Vec<i64>,
    /// Snapshot-only extension preserving each character's complete source position.
    pub character_raw_source_positions: Vec<Vec<i64>>,
}

impl NativeSpanInputDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let raw_source_position = required_i64_list(dict, "raw_source_position")?;
        let character_list = required_list(dict, "characters")?;
        let mut character_raw_source_positions = Vec::with_capacity(character_list.len());
        for item in character_list.iter() {
            let character = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'characters' items must be objects")
            })?;
            character_raw_source_positions
                .push(required_i64_list(&character, "raw_source_position")?);
        }
        Ok(Self {
            span: NativeSpanDto::from_py(dict)?,
            raw_source_position,
            character_raw_source_positions,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = self.span.to_py(py)?;
        dict.set_item("raw_source_position", &self.raw_source_position)?;
        let characters_value = dict
            .get_item("characters")?
            .ok_or_else(|| PyValueError::new_err("Serialized span is missing characters"))?;
        let characters = characters_value
            .downcast::<PyList>()
            .map_err(|_| PyValueError::new_err("Serialized span characters must be a list"))?;
        if characters.len() != self.character_raw_source_positions.len() {
            return Err(PyValueError::new_err(
                "Character source-position extension length does not match characters",
            ));
        }
        for (item, raw_source_position) in characters
            .iter()
            .zip(&self.character_raw_source_positions)
        {
            let character = item
                .downcast::<PyDict>()
                .map_err(|_| PyValueError::new_err("Serialized characters must be objects"))?;
            character.set_item("raw_source_position", raw_source_position)?;
        }
        Ok(dict)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TextLineDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub spans: Vec<NativeSpanInputDto>,
    pub source_position: Vec<i64>,
    pub source_order: i64,
}

impl TextLineDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let schema_version = required_i64(dict, "schema_version")?;
        check_schema_version(schema_version)?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let span_list = required_list(dict, "spans")?;
        let mut spans = Vec::with_capacity(span_list.len());
        for item in span_list.iter() {
            let span = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'spans' items must be objects")
            })?;
            spans.push(NativeSpanInputDto::from_py(&span)?);
        }
        Ok(Self {
            schema_version,
            rect,
            spans,
            source_position: required_i64_list(dict, "source_position")?,
            source_order: required_i64(dict, "source_order")?,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new_bound(py);
        dict.set_item("schema_version", self.schema_version)?;
        dict.set_item("rect", self.rect.to_py(py)?)?;
        let spans = PyList::empty_bound(py);
        for span in &self.spans {
            spans.append(span.to_py(py)?)?;
        }
        dict.set_item("spans", spans)?;
        dict.set_item("source_position", &self.source_position)?;
        dict.set_item("source_order", self.source_order)?;
        Ok(dict)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TextBlockDto {
    pub schema_version: i64,
    pub block_type: Option<i64>,
    pub rect: Rect4,
    pub lines: Vec<TextLineDto>,
    pub source_position: Vec<i64>,
    pub source_order: i64,
}

impl TextBlockDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let schema_version = required_i64(dict, "schema_version")?;
        check_schema_version(schema_version)?;
        let block_type = match dict.get_item("type")? {
            None => Some(0),
            Some(value) if value.is_none() => None,
            Some(value) => {
                if value.is_instance_of::<PyBool>() {
                    return Err(PyValueError::new_err("Field 'type' must be an integer"));
                }
                Some(value.extract::<i64>().map_err(|_| {
                    PyValueError::new_err("Field 'type' must be an integer")
                })?)
            }
        };
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let line_list = if block_type == Some(0) {
            required_list(dict, "lines")?
        } else {
            match dict.get_item("lines")? {
                Some(value) if !value.is_none() => value.downcast::<PyList>()?.clone(),
                _ => PyList::empty_bound(dict.py()),
            }
        };
        let mut lines = Vec::with_capacity(line_list.len());
        for item in line_list.iter() {
            let line = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'lines' items must be objects")
            })?;
            lines.push(TextLineDto::from_py(&line)?);
        }
        Ok(Self {
            schema_version,
            block_type,
            rect,
            lines,
            source_position: required_i64_list(dict, "source_position")?,
            source_order: required_i64(dict, "source_order")?,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new_bound(py);
        dict.set_item("schema_version", self.schema_version)?;
        match self.block_type {
            Some(value) if value != 0 => dict.set_item("type", value)?,
            None => dict.set_item("type", py.None())?,
            _ => {}
        }
        dict.set_item("rect", self.rect.to_py(py)?)?;
        let lines = PyList::empty_bound(py);
        for line in &self.lines {
            lines.append(line.to_py(py)?)?;
        }
        dict.set_item("lines", lines)?;
        dict.set_item("source_position", &self.source_position)?;
        dict.set_item("source_order", self.source_order)?;
        Ok(dict)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ExtractionOptionsDto {
    pub schema_version: i64,
    pub options: BTreeMap<String, OwnedValue>,
}

impl ExtractionOptionsDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let schema_version = required_i64(dict, "schema_version")?;
        check_schema_version(schema_version)?;
        let options = match OwnedValue::from_py(&get_req(dict, "options")?, "options")? {
            OwnedValue::Object(values) => values,
            _ => return Err(PyValueError::new_err("Field 'options' must be an object")),
        };
        Ok(Self {
            schema_version,
            options,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new_bound(py);
        dict.set_item("schema_version", self.schema_version)?;
        let options = PyDict::new_bound(py);
        for (key, value) in &self.options {
            options.set_item(key, value.to_py(py)?)?;
        }
        dict.set_item("options", options)?;
        Ok(dict)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PageSnapshotDto {
    pub schema_version: i64,
    pub page_index: i64,
    pub page: PageDto,
    pub page_y0: f64,
    pub text_blocks: Vec<TextBlockDto>,
    pub spans: Vec<NativeSpanInputDto>,
    pub words: Vec<WordDto>,
    pub drawings: Vec<DrawingDto>,
    pub allowed_regions: Vec<RegionDto>,
    pub excluded_regions: Vec<RegionDto>,
    pub extraction_options: ExtractionOptionsDto,
    /// Snapshot-only extensions for records whose shared algorithm DTOs predate
    /// the full PyMuPDF source-position shape.
    pub word_raw_source_positions: Vec<Vec<i64>>,
    pub drawing_raw_source_positions: Vec<Vec<i64>>,
}

impl PageSnapshotDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let schema_version = required_i64(dict, "schema_version")?;
        check_schema_version(schema_version)?;
        let page_index = required_i64(dict, "page_index")?;
        let page = PageDto::from_py(&required_dict(dict, "page")?)?;
        let page_y0 = optional_f64(dict, "page_y0")?.unwrap_or(0.0);

        let text_block_list = required_list(dict, "text_blocks")?;
        let mut text_blocks = Vec::with_capacity(text_block_list.len());
        for item in text_block_list.iter() {
            let value = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'text_blocks' items must be objects")
            })?;
            text_blocks.push(TextBlockDto::from_py(&value)?);
        }

        let span_list = required_list(dict, "spans")?;
        let mut spans = Vec::with_capacity(span_list.len());
        for item in span_list.iter() {
            let value = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'spans' items must be objects")
            })?;
            spans.push(NativeSpanInputDto::from_py(&value)?);
        }

        let word_list = required_list(dict, "words")?;
        let mut words = Vec::with_capacity(word_list.len());
        let mut word_raw_source_positions = Vec::with_capacity(word_list.len());
        for item in word_list.iter() {
            let value = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'words' items must be objects")
            })?;
            word_raw_source_positions.push(required_i64_list(&value, "raw_source_position")?);
            words.push(WordDto::from_py(&value)?);
        }

        let drawing_list = required_list(dict, "drawings")?;
        let mut drawings = Vec::with_capacity(drawing_list.len());
        let mut drawing_raw_source_positions = Vec::with_capacity(drawing_list.len());
        for item in drawing_list.iter() {
            let value = item.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err("Field 'drawings' items must be objects")
            })?;
            drawing_raw_source_positions.push(required_i64_list(&value, "raw_source_position")?);
            drawings.push(DrawingDto::from_py(&value)?);
        }

        let parse_regions = |key: &str| -> PyResult<Vec<RegionDto>> {
            let list = required_list(dict, key)?;
            let mut regions = Vec::with_capacity(list.len());
            for item in list.iter() {
                let value = item.downcast::<PyDict>().map_err(|_| {
                    PyValueError::new_err(format!("Field '{}' items must be objects", key))
                })?;
                regions.push(RegionDto::from_py(&value)?);
            }
            Ok(regions)
        };

        let extraction_options = ExtractionOptionsDto::from_py(&required_dict(
            dict,
            "extraction_options",
        )?)?;
        Ok(Self {
            schema_version,
            page_index,
            page,
            page_y0,
            text_blocks,
            spans,
            words,
            drawings,
            allowed_regions: parse_regions("allowed_regions")?,
            excluded_regions: parse_regions("excluded_regions")?,
            extraction_options,
            word_raw_source_positions,
            drawing_raw_source_positions,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new_bound(py);
        dict.set_item("schema_version", self.schema_version)?;
        dict.set_item("page_index", self.page_index)?;
        dict.set_item("page", self.page.to_py(py)?)?;
        if self.page_y0 != 0.0 {
            dict.set_item("page_y0", self.page_y0)?;
        }

        let text_blocks = PyList::empty_bound(py);
        for value in &self.text_blocks {
            text_blocks.append(value.to_py(py)?)?;
        }
        dict.set_item("text_blocks", text_blocks)?;

        let spans = PyList::empty_bound(py);
        for value in &self.spans {
            spans.append(value.to_py(py)?)?;
        }
        dict.set_item("spans", spans)?;

        let words = PyList::empty_bound(py);
        for (index, value) in self.words.iter().enumerate() {
            let word = value.to_py(py)?;
            word.set_item(
                "raw_source_position",
                self.word_raw_source_positions
                    .get(index)
                    .ok_or_else(|| PyValueError::new_err("Missing word source-position extension"))?,
            )?;
            words.append(word)?;
        }
        dict.set_item("words", words)?;

        let drawings = PyList::empty_bound(py);
        for (index, value) in self.drawings.iter().enumerate() {
            let drawing = value.to_py(py)?;
            drawing.set_item(
                "raw_source_position",
                self.drawing_raw_source_positions
                    .get(index)
                    .ok_or_else(|| PyValueError::new_err("Missing drawing source-position extension"))?,
            )?;
            drawings.append(drawing)?;
        }
        dict.set_item("drawings", drawings)?;

        for (key, values) in [
            ("allowed_regions", &self.allowed_regions),
            ("excluded_regions", &self.excluded_regions),
        ] {
            let list = PyList::empty_bound(py);
            for value in values {
                list.append(value.to_py(py)?)?;
            }
            dict.set_item(key, list)?;
        }
        dict.set_item("extraction_options", self.extraction_options.to_py(py)?)?;
        Ok(dict)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TextRunEvidenceDto {
    pub schema_version: i64,
    pub source_positions: Vec<SourcePositionDto>,
    pub fonts: Vec<Option<String>>,
    pub sizes: Vec<Option<f64>>,
    pub flags: Vec<Option<i64>>,
    pub source_fragment_indices: Option<Vec<i64>>,
    pub source_fragment_counts: Option<Vec<i64>>,
}

impl TextRunEvidenceDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let schema_version = required_i64(dict, "schema_version")?;
        check_schema_version(schema_version)?;
        let source_list = required_list(dict, "source_positions")?;
        let mut source_positions = Vec::with_capacity(source_list.len());
        for (index, value) in source_list.iter().enumerate() {
            let source = value.downcast::<PyDict>().map_err(|_| {
                PyValueError::new_err(format!(
                    "Field 'source_positions[{}]' must be an object",
                    index
                ))
            })?;
            source_positions.push(SourcePositionDto::from_py(&source.clone())?);
        }
        let fonts = optional_string_list(dict, "fonts")?;
        let sizes = optional_f64_list(dict, "sizes")?;
        let flags = optional_i64_list(dict, "flags")?;
        let source_fragment_indices = optional_i64_list_present(dict, "source_fragment_indices")?;
        let source_fragment_counts = optional_i64_list_present(dict, "source_fragment_counts")?;
        if source_fragment_indices.is_some() != source_fragment_counts.is_some() {
            return Err(PyValueError::new_err(
                "Fragment evidence fields must be provided together",
            ));
        }
        let expected_len = source_positions.len();
        for (field_name, actual_len) in [
            ("fonts", fonts.len()),
            ("sizes", sizes.len()),
            ("flags", flags.len()),
        ] {
            if actual_len != expected_len {
                return Err(PyValueError::new_err(format!(
                    "Field '{}' evidence length {} does not match source_positions length {}",
                    field_name, actual_len, expected_len
                )));
            }
        }
        if let Some(indices) = &source_fragment_indices {
            if indices.len() != expected_len {
                return Err(PyValueError::new_err(format!(
                    "Field 'source_fragment_indices' evidence length {} does not match source_positions length {}",
                    indices.len(), expected_len
                )));
            }
        }
        if let Some(counts) = &source_fragment_counts {
            if counts.len() != expected_len {
                return Err(PyValueError::new_err(format!(
                    "Field 'source_fragment_counts' evidence length {} does not match source_positions length {}",
                    counts.len(), expected_len
                )));
            }
        }
        if let (Some(indices), Some(counts)) = (&source_fragment_indices, &source_fragment_counts) {
            for (index, count) in indices.iter().zip(counts) {
                if *index < 0 || *count <= 0 || *index >= *count {
                    return Err(PyValueError::new_err(
                        "Fragment evidence index/count must satisfy 0 <= index < count",
                    ));
                }
            }
        }
        Ok(Self {
            schema_version,
            source_positions,
            fonts,
            sizes,
            flags,
            source_fragment_indices,
            source_fragment_counts,
        })
    }

    pub fn to_py<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        d.set_item("schema_version", self.schema_version)?;
        let source_positions = PyList::empty_bound(py);
        for position in &self.source_positions {
            source_positions.append(position.to_py(py)?)?;
        }
        d.set_item("source_positions", source_positions)?;
        let fonts = PyList::empty_bound(py);
        for font in &self.fonts {
            match font {
                Some(value) => fonts.append(value)?,
                None => fonts.append(py.None())?,
            }
        }
        d.set_item("fonts", fonts)?;
        let sizes = PyList::empty_bound(py);
        for size in &self.sizes {
            match size {
                Some(value) => sizes.append(value)?,
                None => sizes.append(py.None())?,
            }
        }
        d.set_item("sizes", sizes)?;
        let flags = PyList::empty_bound(py);
        for flag in &self.flags {
            match flag {
                Some(value) => flags.append(value)?,
                None => flags.append(py.None())?,
            }
        }
        d.set_item("flags", flags)?;
        if let Some(indices) = &self.source_fragment_indices {
            d.set_item("source_fragment_indices", indices)?;
        }
        if let Some(counts) = &self.source_fragment_counts {
            d.set_item("source_fragment_counts", counts)?;
        }
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
    pub flow_start: Option<i64>,
    pub flow_end: Option<i64>,
    pub evidence: Option<TextRunEvidenceDto>,
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
        let flow_start = optional_i64(dict, "flow_start")?;
        let flow_end = optional_i64(dict, "flow_end")?;
        let evidence = match get_opt(dict, "evidence")? {
            Some(value) => Some(TextRunEvidenceDto::from_py(
                &value.downcast::<PyDict>()?.clone(),
            )?),
            None => None,
        };
        if let Some(evidence) = &evidence {
            if evidence.source_positions.len() != span_refs.len() {
                return Err(PyValueError::new_err(format!(
                    "TextRun evidence length {} does not match span_refs length {}",
                    evidence.source_positions.len(),
                    span_refs.len()
                )));
            }
        }
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            span_refs,
            source_start,
            source_end,
            order,
            flow_start,
            flow_end,
            evidence,
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
        if let Some(flow_start) = self.flow_start {
            d.set_item("flow_start", flow_start)?;
        }
        if let Some(flow_end) = self.flow_end {
            d.set_item("flow_end", flow_end)?;
        }
        if let Some(evidence) = &self.evidence {
            d.set_item("evidence", evidence.to_py(py)?)?;
        }
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
    pub col_end_hint: Option<i64>,
    pub order: i64,
}

impl AtomDto {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let text = required_string(dict, "text")?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let run_refs = required_i64_list(dict, "run_refs")?;
        let row_hint = optional_i64(dict, "row_hint")?;
        let col_hint = optional_i64(dict, "col_hint")?;
        let col_end_hint = optional_i64(dict, "col_end_hint")?;
        let order = required_i64(dict, "order")?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            run_refs,
            row_hint,
            col_hint,
            col_end_hint,
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
        if let Some(col_end_hint) = self.col_end_hint {
            d.set_item("col_end_hint", col_end_hint)?;
        }
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let x0 = extract_finite_f64(&get_req(dict, "x0")?, "x0")?;
        let x1 = extract_finite_f64(&get_req(dict, "x1")?, "x1")?;
        if x0 >= x1 {
            return Err(PyValueError::new_err("Column band requires x0 < x1"));
        }
        let source_atoms = required_i64_list(dict, "source_atoms")?;
        let order = required_i64(dict, "order")?;
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
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let rect = Rect4::from_py(&required_dict(dict, "rect")?)?;
        let source_order = required_i64(dict, "source_order")?;
        let allowed = required_bool(dict, "allowed")?;
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
    pub colspan: i64,
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
        let colspan = optional_i64(dict, "colspan")?.unwrap_or(1);
        if colspan < 1 {
            return Err(PyValueError::new_err("Field 'colspan' must be positive"));
        }
        let source_refs: Vec<i64> = get_req(dict, "source_refs")?.extract()?;
        Ok(Self {
            schema_version: sv,
            text,
            rect,
            row,
            col,
            colspan,
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
        d.set_item("colspan", self.colspan)?;
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

impl Default for StructureConfig {
    fn default() -> Self {
        Self {
            schema_version: 1,
            line_tolerance: 2.0,
            row_tolerance: 2.0,
            column_tolerance: 2.0,
            span_tolerance: 2.0,
            numeric_tolerance: 2.0,
        }
    }
}

impl StructureConfig {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv = required_i64(dict, "schema_version")?;
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

fn aligned_evidence<T>(values: Vec<Option<T>>, field_name: &str) -> PyResult<Option<Vec<T>>> {
    if values.iter().all(Option::is_none) {
        return Ok(None);
    }
    if values.iter().any(Option::is_none) {
        return Err(PyValueError::new_err(format!(
            "{} evidence must be present for every item",
            field_name
        )));
    }
    Ok(Some(
        values
            .into_iter()
            .map(|value| value.expect("checked aligned evidence"))
            .collect(),
    ))
}

#[derive(Debug, Clone, PartialEq)]
pub struct NativeRegionInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub atoms: Vec<AtomDto>,
    pub bands: Vec<ColumnBandDto>,
    pub atom_evidence: Option<Vec<AtomEvidenceDto>>,
    pub band_evidence: Option<Vec<BandEvidenceDto>>,
    pub output_mode: String,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AtomEvidenceDto {
    pub flow_start: i64,
    pub flow_end: i64,
    pub source_blocks: Vec<i64>,
    pub source_line_start: i64,
    pub source_line_end: i64,
    pub source_position_known: bool,
    pub column_id: Option<i64>,
}

impl AtomEvidenceDto {
    fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Option<Self>> {
        let present = [
            "flow_start",
            "flow_end",
            "source_blocks",
            "source_line_start",
            "source_line_end",
            "source_position_known",
            "column_id",
        ]
        .iter()
        .try_fold(false, |present, key| -> PyResult<bool> {
            Ok(present || dict.contains(*key)?)
        })?;
        if !present {
            return Ok(None);
        }
        Ok(Some(Self {
            flow_start: required_i64(dict, "flow_start")?,
            flow_end: required_i64(dict, "flow_end")?,
            source_blocks: required_i64_list(dict, "source_blocks")?,
            source_line_start: required_i64(dict, "source_line_start")?,
            source_line_end: required_i64(dict, "source_line_end")?,
            source_position_known: required_bool(dict, "source_position_known")?,
            column_id: optional_i64(dict, "column_id")?.map(|value| {
                if value < 0 {
                    return Err(PyValueError::new_err("Field 'column_id' must be non-negative"));
                }
                Ok(value)
            }).transpose()?,
        }))
    }

    fn to_py<'py>(&self, py: Python<'py>, dict: &Bound<'py, PyDict>) -> PyResult<()> {
        dict.set_item("flow_start", self.flow_start)?;
        dict.set_item("flow_end", self.flow_end)?;
        dict.set_item("source_blocks", &self.source_blocks)?;
        dict.set_item("source_line_start", self.source_line_start)?;
        dict.set_item("source_line_end", self.source_line_end)?;
        dict.set_item("source_position_known", self.source_position_known)?;
        dict.set_item("column_id", self.column_id)?;
        let _ = py;
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BandEvidenceDto {
    pub id: i64,
    pub kind: Option<String>,
    pub support: i64,
    pub y_support: i64,
    pub parent_x0: Option<f64>,
    pub parent_x1: Option<f64>,
    pub parent_leaf_count: Option<i64>,
}

impl BandEvidenceDto {
    fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Option<Self>> {
        let present = ["id", "kind", "support", "y_support", "parent_x0", "parent_x1", "parent_leaf_count"]
            .iter()
            .try_fold(false, |present, key| -> PyResult<bool> {
                Ok(present || dict.contains(*key)?)
            })?;
        if !present {
            return Ok(None);
        }
        Ok(Some(Self {
            id: required_i64(dict, "id")?,
            kind: optional_string(dict, "kind")?,
            support: required_i64(dict, "support")?,
            y_support: required_i64(dict, "y_support")?,
            parent_x0: optional_f64(dict, "parent_x0")?,
            parent_x1: optional_f64(dict, "parent_x1")?,
            parent_leaf_count: optional_i64(dict, "parent_leaf_count")?,
        }))
    }

    fn to_py<'py>(&self, py: Python<'py>, dict: &Bound<'py, PyDict>) -> PyResult<()> {
        dict.set_item("id", self.id)?;
        dict.set_item("kind", self.kind.as_deref())?;
        dict.set_item("support", self.support)?;
        dict.set_item("y_support", self.y_support)?;
        dict.set_item("parent_x0", self.parent_x0)?;
        dict.set_item("parent_x1", self.parent_x1)?;
        dict.set_item("parent_leaf_count", self.parent_leaf_count)?;
        let _ = py;
        Ok(())
    }
}

impl NativeRegionInput {
    pub fn from_py(dict: &Bound<'_, PyDict>) -> PyResult<Self> {
        let sv = required_i64(dict, "schema_version")?;
        check_schema_version(sv)?;
        let region = RegionDto::from_py(&required_dict(dict, "region")?)?;
        let atoms_list = required_list(dict, "atoms")?;
        let mut atoms = Vec::with_capacity(atoms_list.len());
        let mut atom_evidence = Vec::with_capacity(atoms_list.len());
        for a in atoms_list.iter() {
            let atom = a
                .downcast::<PyDict>()
                .map_err(|_| PyValueError::new_err("Field 'atoms' items must be objects"))?
                .clone();
            atoms.push(AtomDto::from_py(&atom)?);
            atom_evidence.push(AtomEvidenceDto::from_py(&atom)?);
        }
        let bands_list = required_list(dict, "bands")?;
        let mut bands = Vec::with_capacity(bands_list.len());
        let mut band_evidence = Vec::with_capacity(bands_list.len());
        for b in bands_list.iter() {
            let band = b
                .downcast::<PyDict>()
                .map_err(|_| PyValueError::new_err("Field 'bands' items must be objects"))?
                .clone();
            bands.push(ColumnBandDto::from_py(&band)?);
            band_evidence.push(BandEvidenceDto::from_py(&band)?);
        }
        for (band_index, band) in bands.iter().enumerate() {
            for source_atom in &band.source_atoms {
                if *source_atom < 0 || (*source_atom as usize) >= atoms.len() {
                    return Err(PyValueError::new_err(format!(
                        "bands[{}].source_atoms contains an out-of-range atom reference",
                        band_index
                    )));
                }
            }
        }
        let output_mode = match get_opt(dict, "output_mode")? {
            Some(value) => value.extract::<String>()?,
            None => "columnar".to_string(),
        };
        if output_mode != "row_interleaved" && output_mode != "columnar" {
            return Err(PyValueError::new_err(
                "output_mode must be 'row_interleaved' or 'columnar'",
            ));
        }
        let config = StructureConfig::from_py(&required_dict(dict, "config")?)?;
        Ok(Self {
            schema_version: sv,
            region,
            atoms,
            bands,
            atom_evidence: aligned_evidence(atom_evidence, "atoms")?,
            band_evidence: aligned_evidence(band_evidence, "bands")?,
            output_mode,
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
        if let Some(evidence) = &self.atom_evidence {
            if evidence.len() != self.atoms.len() {
                return Err(PyValueError::new_err("Atom evidence length must match atoms"));
            }
            for (item, evidence) in al.iter().zip(evidence) {
                evidence.to_py(py, &item.downcast::<PyDict>()?.clone())?;
            }
        }
        d.set_item("atoms", al)?;
        let bl = PyList::empty_bound(py);
        for b in &self.bands {
            bl.append(b.to_py(py)?)?;
        }
        if let Some(evidence) = &self.band_evidence {
            if evidence.len() != self.bands.len() {
                return Err(PyValueError::new_err("Band evidence length must match bands"));
            }
            for (item, evidence) in bl.iter().zip(evidence) {
                evidence.to_py(py, &item.downcast::<PyDict>()?.clone())?;
            }
        }
        d.set_item("bands", bl)?;
        d.set_item("output_mode", &self.output_mode)?;
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
    pub columns: Vec<ColumnBandDto>,
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
        let columns = match get_opt(dict, "columns")? {
            Some(value) => {
                let list: Bound<'_, PyList> = value.extract()?;
                let mut columns = Vec::with_capacity(list.len());
                for column in list.iter() {
                    columns.push(ColumnBandDto::from_py(
                        &column.downcast::<PyDict>()?.clone(),
                    )?);
                }
                columns
            }
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
            columns,
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
        let cl = PyList::empty_bound(py);
        for column in &self.columns {
            cl.append(column.to_py(py)?)?;
        }
        d.set_item("columns", cl)?;
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
        "page_snapshot" => {
            let dto = PageSnapshotDto::from_py(data)?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyList;
    use std::sync::Once;

    static PYTHON_INIT: Once = Once::new();

    fn with_test_python<F, R>(f: F) -> R
    where
        F: for<'py> FnOnce(Python<'py>) -> R,
    {
        PYTHON_INIT.call_once(|| pyo3::prepare_freethreaded_python());
        Python::with_gil(f)
    }

    fn base_native_region<'py>(py: Python<'py>) -> Bound<'py, PyDict> {
        let input = PyDict::new_bound(py);
        let region = PyDict::new_bound(py);
        let rect = PyDict::new_bound(py);
        rect.set_item("schema_version", 1).unwrap();
        rect.set_item("x0", 0.0).unwrap();
        rect.set_item("y0", 0.0).unwrap();
        rect.set_item("x1", 100.0).unwrap();
        rect.set_item("y1", 100.0).unwrap();
        region.set_item("schema_version", 1).unwrap();
        region.set_item("rect", rect).unwrap();
        region.set_item("source_order", 0).unwrap();
        region.set_item("allowed", true).unwrap();

        let atom = PyDict::new_bound(py);
        atom.set_item("schema_version", 1).unwrap();
        atom.set_item("text", "项目").unwrap();
        let atom_rect = PyDict::new_bound(py);
        atom_rect.set_item("schema_version", 1).unwrap();
        atom_rect.set_item("x0", 10.0).unwrap();
        atom_rect.set_item("y0", 10.0).unwrap();
        atom_rect.set_item("x1", 40.0).unwrap();
        atom_rect.set_item("y1", 20.0).unwrap();
        atom.set_item("rect", atom_rect).unwrap();
        atom.set_item("run_refs", PyList::new_bound(py, [0])).unwrap();
        atom.set_item("row_hint", 0).unwrap();
        atom.set_item("col_hint", 0).unwrap();
        atom.set_item("order", 0).unwrap();
        let atoms = PyList::empty_bound(py);
        atoms.append(atom).unwrap();

        let band = PyDict::new_bound(py);
        band.set_item("schema_version", 1).unwrap();
        band.set_item("x0", 0.0).unwrap();
        band.set_item("x1", 50.0).unwrap();
        band.set_item("source_atoms", PyList::new_bound(py, [0])).unwrap();
        band.set_item("order", 0).unwrap();
        let bands = PyList::empty_bound(py);
        bands.append(band).unwrap();

        let config = PyDict::new_bound(py);
        config.set_item("schema_version", 1).unwrap();
        config.set_item("line_tolerance", 2.0).unwrap();
        config.set_item("row_tolerance", 2.0).unwrap();
        config.set_item("column_tolerance", 2.0).unwrap();
        config.set_item("span_tolerance", 2.0).unwrap();
        config.set_item("numeric_tolerance", 2.0).unwrap();

        input.set_item("schema_version", 1).unwrap();
        input.set_item("region", region).unwrap();
        input.set_item("atoms", atoms).unwrap();
        input.set_item("bands", bands).unwrap();
        input.set_item("config", config).unwrap();
        input
    }

    fn assert_value_error(result: PyResult<NativeRegionInput>, py: Python<'_>) {
        let error = result.expect_err("invalid DTO input must fail");
        assert_eq!(error.get_type_bound(py).name().unwrap(), "ValueError");
    }

    #[test]
    fn native_region_without_evidence_keeps_legacy_shape() {
        with_test_python(|py| {
            let input = base_native_region(py);
            let dto = NativeRegionInput::from_py(&input).unwrap();
            assert!(dto.atom_evidence.is_none());
            assert!(dto.band_evidence.is_none());

            let output = dto.to_py(py).unwrap();
            let atoms_value = output.get_item("atoms").unwrap().unwrap();
            let atoms = atoms_value.downcast::<PyList>().unwrap();
            let atom_value = atoms.get_item(0).unwrap();
            let atom = atom_value.downcast::<PyDict>().unwrap();
            assert!(!atom.contains("flow_start").unwrap());
            assert!(!atom.contains("unknown_debug_field").unwrap());
        });
    }

    #[test]
    fn native_region_roundtrips_aligned_owned_evidence_and_drops_unknown_fields() {
        with_test_python(|py| {
            let input = base_native_region(py);
            let atoms_value = input.get_item("atoms").unwrap().unwrap();
            let atoms = atoms_value.downcast::<PyList>().unwrap();
            let atom_value = atoms.get_item(0).unwrap();
            let atom = atom_value.downcast::<PyDict>().unwrap();
            atom.set_item("flow_start", 0).unwrap();
            atom.set_item("flow_end", 1).unwrap();
            atom.set_item("source_blocks", PyList::new_bound(py, [14])).unwrap();
            atom.set_item("source_line_start", 3).unwrap();
            atom.set_item("source_line_end", 3).unwrap();
            atom.set_item("source_position_known", true).unwrap();
            atom.set_item("column_id", 0).unwrap();
            atom.set_item("unknown_debug_field", "ignored").unwrap();

            let bands_value = input.get_item("bands").unwrap().unwrap();
            let bands = bands_value.downcast::<PyList>().unwrap();
            let band_value = bands.get_item(0).unwrap();
            let band = band_value.downcast::<PyDict>().unwrap();
            band.set_item("id", 0).unwrap();
            band.set_item("kind", "body").unwrap();
            band.set_item("support", 3).unwrap();
            band.set_item("y_support", 3).unwrap();
            band.set_item("parent_x0", 0.0).unwrap();
            band.set_item("parent_x1", 50.0).unwrap();
            band.set_item("parent_leaf_count", 1).unwrap();

            let dto = NativeRegionInput::from_py(&input).unwrap();
            assert_eq!(dto.atom_evidence.as_ref().unwrap().len(), 1);
            assert_eq!(dto.band_evidence.as_ref().unwrap().len(), 1);
            let output = dto.to_py(py).unwrap();
            let output_atoms_value = output.get_item("atoms").unwrap().unwrap();
            let output_atoms = output_atoms_value.downcast::<PyList>().unwrap();
            let output_atom_value = output_atoms.get_item(0).unwrap();
            let output_atom = output_atom_value.downcast::<PyDict>().unwrap();
            assert_eq!(output_atom.get_item("flow_start").unwrap().unwrap().extract::<i64>().unwrap(), 0);
            assert!(!output_atom.contains("unknown_debug_field").unwrap());
        });
    }

    #[test]
    fn native_region_rejects_partial_or_invalid_evidence_and_references() {
        with_test_python(|py| {
            let input = base_native_region(py);
            let atoms_value = input.get_item("atoms").unwrap().unwrap();
            let atoms = atoms_value.downcast::<PyList>().unwrap();
            let atom_value = atoms.get_item(0).unwrap();
            let atom = atom_value.downcast::<PyDict>().unwrap();
            atom.set_item("flow_start", 0).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);

            atom.del_item("flow_start").unwrap();
            let bands_value = input.get_item("bands").unwrap().unwrap();
            let bands = bands_value.downcast::<PyList>().unwrap();
            let band_value = bands.get_item(0).unwrap();
            let band = band_value.downcast::<PyDict>().unwrap();
            band.set_item("source_atoms", PyList::new_bound(py, [1])).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);

            band.set_item("source_atoms", PyList::new_bound(py, [0])).unwrap();
            band.set_item("x0", f64::NAN).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);
        });
    }

    #[test]
    fn atom_and_band_dtos_reject_non_core_types() {
        with_test_python(|py| {
            let input = base_native_region(py);
            let atoms_value = input.get_item("atoms").unwrap().unwrap();
            let atoms = atoms_value.downcast::<PyList>().unwrap();
            let atom_value = atoms.get_item(0).unwrap();
            let atom = atom_value.downcast::<PyDict>().unwrap();
            atom.set_item("text", 7).unwrap();
            assert_value_error(
                AtomDto::from_py(&atom).map(|_| NativeRegionInput::from_py(&input).unwrap()),
                py,
            );
        });
    }

    #[test]
    fn native_region_rejects_wrong_container_types_as_value_error() {
        with_test_python(|py| {
            let input = base_native_region(py);
            input.set_item("region", PyList::empty_bound(py)).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);

            let input = base_native_region(py);
            input.set_item("atoms", PyDict::new_bound(py)).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);

            let input = base_native_region(py);
            input.set_item("bands", PyDict::new_bound(py)).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);

            let input = base_native_region(py);
            input.set_item("config", PyList::empty_bound(py)).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);

            let input = base_native_region(py);
            let atoms = PyList::empty_bound(py);
            atoms.append(PyList::empty_bound(py)).unwrap();
            input.set_item("atoms", atoms).unwrap();
            assert_value_error(NativeRegionInput::from_py(&input), py);
        });
    }

    #[test]
    fn atom_rect_and_config_schema_reject_wrong_types_as_value_error() {
        with_test_python(|py| {
            let input = base_native_region(py);
            let atoms_value = input.get_item("atoms").unwrap().unwrap();
            let atoms = atoms_value.downcast::<PyList>().unwrap();
            let atom_value = atoms.get_item(0).unwrap();
            let atom = atom_value.downcast::<PyDict>().unwrap();
            atom.set_item("rect", PyList::empty_bound(py)).unwrap();
            let error = AtomDto::from_py(&atom).expect_err("invalid atom rect must fail");
            assert_eq!(error.get_type_bound(py).name().unwrap(), "ValueError");

            let input = base_native_region(py);
            let config_value = input.get_item("config").unwrap().unwrap();
            let config = config_value.downcast::<PyDict>().unwrap();
            config.set_item("schema_version", true).unwrap();
            let error = StructureConfig::from_py(&config)
                .expect_err("boolean schema_version must fail");
            assert_eq!(error.get_type_bound(py).name().unwrap(), "ValueError");

            config.set_item("schema_version", "1").unwrap();
            let error = StructureConfig::from_py(&config)
                .expect_err("string schema_version must fail");
            assert_eq!(error.get_type_bound(py).name().unwrap(), "ValueError");
        });
    }
}
