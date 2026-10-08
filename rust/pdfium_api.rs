use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
pub(crate) fn run_public_pdf_api(request_json: &str) -> PyResult<String> {
    pdfium_probe::public_api::run_public_api_json(request_json).map_err(PyValueError::new_err)
}

#[pyfunction]
#[pyo3(signature = (pdf_bytes, page_index, pdfium_library_path=None))]
pub(crate) fn classify_page_from_bytes(
    pdf_bytes: &[u8],
    page_index: usize,
    pdfium_library_path: Option<&str>,
) -> PyResult<String> {
    pdfium_probe::public_api::classify_page_from_pdf_bytes(
        pdf_bytes,
        page_index,
        pdfium_library_path,
    )
    .map_err(PyValueError::new_err)
}

#[cfg(test)]
mod tests {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyModule};

    fn with_module(f: impl for<'py> FnOnce(Python<'py>, Bound<'py, PyModule>)) {
        pyo3::prepare_freethreaded_python();
        Python::with_gil(|py| {
            let module = PyModule::new_bound(py, "_pdf_fast").unwrap();
            crate::_pdf_fast(&module).unwrap();
            f(py, module);
        });
    }

    #[test]
    fn pdfium_api_invalid_json_is_value_error() {
        with_module(|py, module| {
            let error = module
                .getattr("run_public_pdf_api")
                .unwrap()
                .call1(("{",))
                .unwrap_err();
            assert!(error.is_instance_of::<PyValueError>(py));
            assert!(error.to_string().contains("Invalid public API request"));
        });
    }

    #[test]
    fn pdfium_api_classifies_pdf_bytes_as_vector() {
        with_module(|py, module| {
            let bytes = std::fs::read(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/tests/fixtures/page_000_vector.pdf"
            ))
            .unwrap();
            let result: String = module
                .getattr("classify_page_from_bytes")
                .unwrap()
                .call1((PyBytes::new_bound(py, &bytes), 0))
                .unwrap()
                .extract()
                .unwrap();
            assert_eq!(result, "vector");
        });
    }

    #[test]
    fn pdfium_api_bad_pdf_has_readable_value_error() {
        with_module(|py, module| {
            let error = module
                .getattr("classify_page_from_bytes")
                .unwrap()
                .call1((PyBytes::new_bound(py, b"not a PDF"), 0, py.None()))
                .unwrap_err();
            assert!(error.is_instance_of::<PyValueError>(py));
            assert!(error.to_string().contains("Could not load PDF bytes"));
        });
    }
}
