use std::sync::OnceLock;
use numpy::{PyArray1, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::prelude::*;
use pyo3::types::PyDict;

mod pokey;
mod wav;

static TABLES: OnceLock<pokey::PokeyTables> = OnceLock::new();

fn get_tables() -> &'static pokey::PokeyTables {
    TABLES.get_or_init(pokey::PokeyTables::new)
}

#[pyfunction]
#[pyo3(signature = (frames, sample_rate = 44100, frame_rate_hz = 50.0))]
fn render_pokey_samples<'py>(
    py: Python<'py>,
    frames: PyReadonlyArray2<'py, u8>,
    sample_rate: u32,
    frame_rate_hz: f64,
) -> PyResult<Bound<'py, PyArray1<i16>>> {
    let shape = frames.shape();
    if shape.len() != 2 || shape[1] != 9 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Expected frames array of shape (N, 9), got {:?}",
            shape
        )));
    }

    let flat_slice = frames.as_slice()?;
    let tables = get_tables();

    let pcm_samples = pokey::render_pokey_samples_rust(flat_slice, sample_rate, frame_rate_hz, tables);

    Ok(PyArray1::from_vec(py, pcm_samples))
}

#[pyfunction]
fn read_wav_stats<'py>(py: Python<'py>, path: &str) -> PyResult<Bound<'py, PyDict>> {
    let path_buf = std::path::PathBuf::from(path);
    let stats = wav::read_wav_stats_file(&path_buf)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

    let dict = PyDict::new(py);
    dict.set_item("filename", stats.filename)?;
    dict.set_item("duration_sec", stats.duration_sec)?;
    dict.set_item("peak", stats.peak)?;
    dict.set_item("rms", stats.rms)?;
    dict.set_item("framerate", stats.framerate)?;
    dict.set_item("channels", stats.channels)?;
    dict.set_item("sample_width", stats.sample_width)?;
    dict.set_item("n_frames", stats.n_frames)?;
    Ok(dict)
}

#[pyfunction]
fn batch_inspect_wavs<'py>(py: Python<'py>, paths: Vec<String>) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let results = wav::inspect_wav_batch_parallel(&paths);

    let mut py_list = Vec::with_capacity(results.len());
    for stat in results {
        let dict = PyDict::new(py);
        dict.set_item("filename", stat.filename)?;
        dict.set_item("duration_sec", stat.duration_sec)?;
        dict.set_item("peak", stat.peak)?;
        dict.set_item("rms", stat.rms)?;
        dict.set_item("framerate", stat.framerate)?;
        dict.set_item("channels", stat.channels)?;
        dict.set_item("sample_width", stat.sample_width)?;
        dict.set_item("n_frames", stat.n_frames)?;
        dict.set_item("error", stat.error)?;
        py_list.push(dict);
    }

    Ok(py_list)
}

#[pymodule]
fn _core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(render_pokey_samples, m)?)?;
    m.add_function(wrap_pyfunction!(read_wav_stats, m)?)?;
    m.add_function(wrap_pyfunction!(batch_inspect_wavs, m)?)?;
    Ok(())
}
