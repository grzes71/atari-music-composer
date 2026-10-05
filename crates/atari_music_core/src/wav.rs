//! Fast WAV metrics and batch validation using hound & rayon.

use std::path::Path;
use rayon::prelude::*;

#[derive(Debug, Clone)]
pub struct WavStats {
    pub filename: String,
    pub duration_sec: f64,
    pub peak: f64,
    pub rms: f64,
    pub framerate: u32,
    pub channels: u16,
    pub sample_width: u16,
    pub n_frames: u32,
    pub error: Option<String>,
}

pub fn read_wav_stats_file(path: &Path) -> Result<WavStats, String> {
    let mut reader = match hound::WavReader::open(path) {
        Ok(r) => r,
        Err(e) => return Err(format!("Failed to open WAV {}: {}", path.display(), e)),
    };

    let spec = reader.spec();
    let n_frames = reader.duration();
    let framerate = spec.sample_rate;
    let channels = spec.channels;
    let sample_width = spec.bits_per_sample / 8;
    let duration_sec = ((n_frames as f64 / framerate as f64) * 100.0).round() / 100.0;

    let mut peak_raw: i32 = 0;
    let mut sum_sq: f64 = 0.0;
    let mut count: usize = 0;

    for sample in reader.samples::<i16>() {
        let val = match sample {
            Ok(v) => v as i32,
            Err(e) => return Err(format!("Corrupted sample in {}: {}", path.display(), e)),
        };
        let abs_val = val.abs();
        if abs_val > peak_raw {
            peak_raw = abs_val;
        }
        sum_sq += (val as f64) * (val as f64);
        count += 1;
    }

    let peak = (peak_raw as f64) / 32767.0;
    let rms = if count > 0 {
        (sum_sq / count as f64).sqrt() / 32767.0
    } else {
        0.0
    };

    Ok(WavStats {
        filename: path.file_name().unwrap_or_default().to_string_lossy().to_string(),
        duration_sec,
        peak,
        rms,
        framerate,
        channels,
        sample_width,
        n_frames,
        error: None,
    })
}

pub fn inspect_wav_batch_parallel(paths: &[String]) -> Vec<WavStats> {
    paths
        .par_iter()
        .map(|p_str| {
            let path = Path::new(p_str);
            match read_wav_stats_file(path) {
                Ok(stats) => stats,
                Err(err) => WavStats {
                    filename: path.file_name().unwrap_or_default().to_string_lossy().to_string(),
                    duration_sec: 0.0,
                    peak: 0.0,
                    rms: 0.0,
                    framerate: 0,
                    channels: 0,
                    sample_width: 0,
                    n_frames: 0,
                    error: Some(err),
                },
            }
        })
        .collect()
}
