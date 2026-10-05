//! Fast POKEY Audio Synthesizer in Rust.

use std::f64::consts::PI;

pub const PAL_CLOCK_HZ: f64 = 1773447.0;
pub const PAL_64KHZ_CLOCK: f64 = PAL_CLOCK_HZ / 28.0;   // ~63337.39 Hz
pub const PAL_15KHZ_CLOCK: f64 = PAL_CLOCK_HZ / 114.0;  // ~15556.55 Hz

pub const AUDCTL_15KHZ: u8 = 0x01;
pub const AUDCTL_JOIN_1_2_16BIT: u8 = 0x10;
pub const AUDCTL_CH3_179MHZ: u8 = 0x20;
pub const AUDCTL_CH1_179MHZ: u8 = 0x40;
pub const AUDCTL_9BIT_POLY: u8 = 0x80;

pub const AUDC_VOLUME_MASK: u8 = 0x0F;
pub const AUDC_VOLUME_ONLY: u8 = 0x10;
pub const AUDC_PURETONE: u8 = 0x20;
pub const AUDC_POLY4: u8 = 0x40;
pub const AUDC_NOTPOLY5: u8 = 0x80;

pub static POLY4_SEQ: [f32; 15] = [
    1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0,
];

pub static POLY5_SEQ: [f32; 31] = [
    1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0,
];

pub static POKEY_DAC: [f32; 16] = [
    0.0000, 0.0075, 0.0170, 0.0290, 0.0460, 0.0680, 0.0980, 0.1370,
    0.1880, 0.2520, 0.3340, 0.4400, 0.5750, 0.7480, 0.8800, 1.0000,
];

pub struct PokeyTables {
    pub poly17_seq: Vec<f32>,
    pub poly9_seq: Vec<f32>,
}

impl PokeyTables {
    pub fn new() -> Self {
        let mut poly17 = vec![0.0f32; 131071];
        let mut state17: u32 = 0x1FFFF;
        for i in 0..131071 {
            let new_bit = ((state17 >> 16) ^ (state17 >> 11)) & 1;
            poly17[i] = if new_bit != 0 { 1.0 } else { -1.0 };
            state17 = ((state17 << 1) | new_bit) & 0x1FFFF;
        }

        let mut poly9 = vec![0.0f32; 511];
        let mut state9: u32 = 0x1FF;
        for i in 0..511 {
            let new_bit = ((state9 >> 8) ^ (state9 >> 3)) & 1;
            poly9[i] = if new_bit != 0 { 1.0 } else { -1.0 };
            state9 = ((state9 << 1) | new_bit) & 0x1FF;
        }

        Self {
            poly17_seq: poly17,
            poly9_seq: poly9,
        }
    }
}

#[derive(Copy, Clone, PartialEq, Eq)]
pub enum Waveform {
    VolumeOnly,
    PureTone,
    Poly4,
    Poly9_17,
    Poly5GatedPure,
    Poly5GatedPoly4,
    Poly5GatedPoly9_17,
}

#[inline]
pub fn decode_audc(audc: u8) -> Waveform {
    if audc & AUDC_VOLUME_ONLY != 0 {
        return Waveform::VolumeOnly;
    }
    if audc & AUDC_NOTPOLY5 != 0 {
        if audc & AUDC_PURETONE != 0 {
            return Waveform::PureTone;
        }
        if audc & AUDC_POLY4 != 0 {
            return Waveform::Poly4;
        }
        return Waveform::Poly9_17;
    }
    if audc & AUDC_PURETONE != 0 {
        return Waveform::Poly5GatedPure;
    }
    if audc & AUDC_POLY4 != 0 {
        return Waveform::Poly5GatedPoly4;
    }
    Waveform::Poly5GatedPoly9_17
}

#[inline]
fn base_clock_hz(audctl: u8) -> f64 {
    if audctl & AUDCTL_15KHZ != 0 {
        PAL_15KHZ_CLOCK
    } else {
        PAL_64KHZ_CLOCK
    }
}

#[inline]
fn uses_hs_clock(audctl: u8, channel: usize) -> bool {
    if channel == 1 {
        audctl & AUDCTL_CH1_179MHZ != 0
    } else if channel == 3 {
        audctl & AUDCTL_CH3_179MHZ != 0
    } else {
        false
    }
}

#[inline]
fn pair_uses_hs_clock(audctl: u8, channel: usize) -> bool {
    if channel == 3 {
        audctl & AUDCTL_CH3_179MHZ != 0
    } else {
        audctl & AUDCTL_CH1_179MHZ != 0
    }
}

#[inline]
pub fn hz_from_audf_8bit(audf: u8, audctl: u8, channel: usize) -> f64 {
    if uses_hs_clock(audctl, channel) {
        PAL_CLOCK_HZ / (2.0 * (audf as f64 + 4.0))
    } else {
        base_clock_hz(audctl) / (2.0 * (audf as f64 + 1.0))
    }
}

#[inline]
pub fn hz_from_audf_16bit(divider: u16, audctl: u8, channel: usize) -> f64 {
    if pair_uses_hs_clock(audctl, channel) {
        PAL_CLOCK_HZ / (2.0 * (divider as f64 + 7.0))
    } else {
        base_clock_hz(audctl) / (2.0 * (divider as f64 + 1.0))
    }
}

pub fn render_pokey_samples_rust(
    frames: &[u8],
    sample_rate: u32,
    frame_rate_hz: f64,
    tables: &PokeyTables,
) -> Vec<i16> {
    let num_frames = frames.len() / 9;
    if num_frames == 0 {
        return Vec::new();
    }

    let samples_per_frame = (sample_rate as f64 / frame_rate_hz).round() as usize;
    let total_samples = num_frames * samples_per_frame;

    let mut audio_mix = vec![0.0f32; total_samples];
    let mut ch_phases = [0.0f64; 4];
    let mut ch_lfsr_steps = [0.0f64; 4];

    for f_idx in 0..num_frames {
        let f_row = &frames[f_idx * 9..(f_idx + 1) * 9];
        let audctl = f_row[8];
        let s_start = f_idx * samples_per_frame;
        let _s_end = s_start + samples_per_frame;

        let is_16bit_1_2 = (audctl & AUDCTL_JOIN_1_2_16BIT) != 0;
        let use_9bit = (audctl & AUDCTL_9BIT_POLY) != 0;
        let poly_len = if use_9bit { 511 } else { 131071 };
        let noise_seq = if use_9bit {
            &tables.poly9_seq
        } else {
            &tables.poly17_seq
        };

        for ch in 0..4 {
            let audf = f_row[ch * 2];
            let audc = f_row[ch * 2 + 1];
            let vol = (audc & AUDC_VOLUME_MASK) as usize;

            if vol == 0 {
                continue;
            }

            if is_16bit_1_2 && ch == 0 {
                continue;
            }

            let freq = if is_16bit_1_2 && ch == 1 {
                let div16 = (f_row[0] as u16) | ((f_row[2] as u16) << 8);
                hz_from_audf_16bit(div16, audctl, 1)
            } else {
                hz_from_audf_8bit(audf, audctl, ch + 1)
            };

            let freq = freq.clamp(10.0, 20000.0);
            let amp = POKEY_DAC[vol];

            let waveform = decode_audc(audc);
            if waveform == Waveform::VolumeOnly {
                continue;
            }

            let delta_phase = 2.0 * PI * freq * (samples_per_frame as f64 / sample_rate as f64);
            let phase_base = ch_phases[ch];
            ch_phases[ch] = (ch_phases[ch] + delta_phase).rem_euclid(2.0 * PI);

            let lfsr_base = ch_lfsr_steps[ch];
            let lfsr_step_mult = 2.0 * freq / sample_rate as f64;

            // Handle waveform generation across the samples of this frame
            match waveform {
                Waveform::PureTone => {
                    for s in 0..samples_per_frame {
                        let t = s as f64 / sample_rate as f64;
                        let phase = phase_base + 2.0 * PI * freq * t;
                        let wave_sample = if phase.sin() >= 0.0 { 1.0f32 } else { -1.0f32 };
                        audio_mix[s_start + s] += wave_sample * amp;
                    }
                }
                Waveform::Poly4 => {
                    for s in 0..samples_per_frame {
                        let t = s as f64 / sample_rate as f64;
                        let phase = phase_base + 2.0 * PI * freq * t;
                        let poly4_idx = ((phase * (15.0 / (2.0 * PI))) as i64).rem_euclid(15) as usize;
                        let wave_sample = POLY4_SEQ[poly4_idx] * 2.0 - 1.0;
                        audio_mix[s_start + s] += wave_sample * amp;
                    }
                }
                Waveform::Poly9_17 => {
                    for s in 0..samples_per_frame {
                        let step = (lfsr_base + lfsr_step_mult * s as f64) as i64;
                        let idx = step.rem_euclid(poly_len as i64) as usize;
                        let wave_sample = noise_seq[idx];
                        audio_mix[s_start + s] += wave_sample * amp;
                    }
                }
                Waveform::Poly5GatedPure => {
                    for s in 0..samples_per_frame {
                        let t = s as f64 / sample_rate as f64;
                        let phase = phase_base + 2.0 * PI * freq * t;
                        let poly5_idx = ((phase * (31.0 / (2.0 * PI))) as i64).rem_euclid(31) as usize;
                        let wave_sample = POLY5_SEQ[poly5_idx] * 2.0 - 1.0;
                        audio_mix[s_start + s] += wave_sample * amp;
                    }
                }
                Waveform::Poly5GatedPoly4 => {
                    // Python:
                    // gate = POLY5_SEQ[poly5_idx] > 0.5
                    // body = POLY4_SEQ[poly4_idx] * 2.0 - 1.0
                    // src = np.where(gate, np.arange(gate.shape[0]), 0)
                    // np.maximum.accumulate(src, out=src)
                    // wave_samples = body[src]
                    let mut last_src = 0usize;
                    let mut body = [0.0f32; 1024]; // max samples_per_frame is ~882
                    let mut src_indices = [0usize; 1024];

                    for s in 0..samples_per_frame {
                        let t = s as f64 / sample_rate as f64;
                        let phase = phase_base + 2.0 * PI * freq * t;
                        let poly5_idx = ((phase * (31.0 / (2.0 * PI))) as i64).rem_euclid(31) as usize;
                        let poly4_idx = ((phase * (15.0 / (2.0 * PI))) as i64).rem_euclid(15) as usize;

                        body[s] = POLY4_SEQ[poly4_idx] * 2.0 - 1.0;
                        if POLY5_SEQ[poly5_idx] > 0.5 {
                            last_src = s;
                        }
                        src_indices[s] = last_src;
                    }

                    for s in 0..samples_per_frame {
                        let wave_sample = body[src_indices[s]];
                        audio_mix[s_start + s] += wave_sample * amp;
                    }
                }
                Waveform::Poly5GatedPoly9_17 => {
                    for s in 0..samples_per_frame {
                        let t = s as f64 / sample_rate as f64;
                        let phase = phase_base + 2.0 * PI * freq * t;
                        let poly5_idx = ((phase * (31.0 / (2.0 * PI))) as i64).rem_euclid(31) as usize;
                        let poly5_val = POLY5_SEQ[poly5_idx] * 2.0 - 1.0;

                        let step = (lfsr_base + lfsr_step_mult * s as f64) as i64;
                        let idx = step.rem_euclid(poly_len as i64) as usize;
                        let noise_val = noise_seq[idx];

                        let wave_sample = poly5_val * noise_val;
                        audio_mix[s_start + s] += wave_sample * amp;
                    }
                }
                Waveform::VolumeOnly => {}
            }

            if matches!(waveform, Waveform::Poly9_17 | Waveform::Poly5GatedPoly9_17) {
                let delta_steps = (2.0 * freq) * (samples_per_frame as f64 / sample_rate as f64);
                ch_lfsr_steps[ch] = (ch_lfsr_steps[ch] + delta_steps).rem_euclid(poly_len as f64);
            }
        }
    }

    // Apply DC blocking filter (single-pole high pass: y[n] = x[n] - x[n-1] + R * y[n-1])
    // with R ≈ 0.995 (cut-off ~35 Hz)
    let mut dc_blocked = vec![0.0f32; total_samples];
    let r = 0.995f32;
    for i in 1..total_samples {
        dc_blocked[i] = audio_mix[i] - audio_mix[i - 1] + r * dc_blocked[i - 1];
    }

    // Normalize audio buffer
    let mut peak = 0.0f32;
    for &sample in &dc_blocked {
        let abs_val = sample.abs();
        if abs_val > peak {
            peak = abs_val;
        }
    }

    let scale = if peak > 0.0 {
        (0.90 / peak) * 32767.0
    } else {
        32767.0
    };

    let mut int16_audio = vec![0i16; total_samples];
    for i in 0..total_samples {
        let norm_audio = (dc_blocked[i] * scale) as f64;
        // Match numpy .astype(np.int16) clamping/truncation
        int16_audio[i] = (norm_audio.clamp(-32768.0, 32767.0)) as i16;
    }

    int16_audio
}
