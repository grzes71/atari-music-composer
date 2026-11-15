"""Experiment 28 — the C1 octave-pulse timbre inside a real game-tune composition.

The question this answers: Experiment 27 found the C1 octave pulse interesting on an isolated note
and on a four-note phrase. Does it still add something useful when one part of an actual game tune
carries it, or does it only work as a test tone?

ONE CONTROLLED A/B, AND NOTHING ELSE
------------------------------------
Both renders are the **same composition** put through the **same production path**. Only one melodic
part changes, and only in two registers:

* **A** — the composition as the existing pipeline renders it: ``load_composition_dsl`` →
  ``generate_music_from_composition`` → ``ir.compile_ir_to_pokey_frames``, unmodified.
* **B** — the same register stream with channel 3 (the lead) rewritten so that, for every frame the
  lead is sounding, the divider alternates between the note's nominal ``N`` and ``N // 2``, and the
  AUDC generator nibble is ``$40``. Every other register, every other channel and every note onset,
  pitch and duration is byte-identical to A.

WHAT IS REUSED RATHER THAN REBUILT
----------------------------------
The effect is Experiment 27's, called directly:

* ``pokey_octave_pulse_experiment.SCHEDULES["C1"]`` and its ``divider_for_frame`` produce the divider
  schedule — no second implementation of the alternation exists here;
* ``pokey_timbre_experiment.C_GENERATOR`` (``$40``) and ``octave_divider`` (``N // 2``, clamped
  through the tracker format) supply the generator and the octave value;
* ``pokey_timbre_experiment.render_registers`` / ``to_int16`` / ``write_wav`` do the rendering, so the
  hardware model, the DAC ladder and the polynomial tables are the ones Experiment 26 established.

DELIBERATE SCOPE DECISION: THE VOLUME IS NOT CHANGED
----------------------------------------------------
Experiment 26's and 27's C1 also replaced the note's volume shape with
``pokey_timbre_experiment.plucked_volume_shape``. This experiment does **not**. The brief lists C1's
relevant behaviour as the generator, the divider alternation and the timing, and requires the same
note onsets, pitches and durations as the baseline; it also forbids changing the musical content. A
different envelope would change articulation and dynamics — a second dimension — and would make it
impossible to tell whether a difference was heard as timbre or as articulation. So the volume nibble
is taken from the baseline stream unchanged, and the A/B difference is the generator and the divider
only. That is a narrowing of "the C1 effect", and it is stated rather than glossed over.

WHAT THIS IS NOT
----------------
No production file is touched: the DSL, IR, compiler, MADS exporter, player and CLI are untouched,
C1 is not registered as an instrument, nothing is added to the instrument library, and the experiment
is not reachable from the production command line. It establishes nothing about general musical
superiority and nothing about readiness for production integration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from atari_music import ir, pokey_hw
from atari_music import pokey_octave_pulse_experiment as e27
from atari_music import pokey_timbre_experiment as e26
from atari_music.ai.client import generate_music_from_composition, load_composition_dsl

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "experiment28"

#: The project's own documented example composition: `docs/music_dsl.md` §4, authored by the project
#: ("POKEY Composer"), also used as a test fixture. It has a recognisable lead melody, a bass part and
#: percussion, and it renders deterministically through the existing pipeline.
DEFAULT_COMPOSITION = REPO_ROOT / "examples" / "songs" / "Vaults-of-Nhyrmeth.dsl"

#: The part that receives C1. Channel 3 is the lead: an 8-bit channel, which is exactly the case
#: Experiment 27's C1 implementation covers. The 16-bit bass (CH1+CH2) is deliberately left alone —
#: C1 as implemented has no 16-bit divider arithmetic, and inventing some would be a different effect.
MELODIC_CHANNEL = 3

SAMPLE_RATE = e26.SAMPLE_RATE
FRAME_RATE_HZ = e26.FRAME_RATE_HZ
TARGET_PEAK = e26.TARGET_PEAK

BASELINE_WAV = "A_baseline.wav"
C1_WAV = "B_c1.wav"

#: The real limits of what this A/B can show. Recorded rather than worked around.
LIMITATIONS: Tuple[str, ...] = (
    "POKEY's $40 is poly5-gated poly4, and the poly5 gate runs at the divider rate too. Doubling the "
    "divider therefore doubles the gate rate as well as the tone, so C1 is a texture and pitch change "
    "together, NOT a clean octave oscillator. A listener may hear it as a rough or metallic colour "
    "rather than as an added octave.",
    "the divider can only change once per 50 Hz frame, so the alternation is fixed at 25 Hz and "
    "cannot be made faster or slower in this experiment",
    "the volume shape is deliberately held at the baseline's, so this is C1's generator and divider "
    "only — a narrower change than the C1 that Experiment 27 listened to",
    "the effect is applied to the lead on CH3, an 8-bit channel. The 16-bit bass on CH1+CH2 is "
    "untouched because C1 as implemented has no 16-bit divider arithmetic; a bass application would "
    "be a different experiment, not this one",
    "only one composition and one part were tested. Nothing here generalises to other tunes, other "
    "registers or other parts",
    "the two files differ in more than the generator alone: the divider also moves, and the two "
    "generators do not have the same RMS at the same DAC volume, so part of any perceived difference "
    "may be loudness. The measured RMS of both files is recorded in summary.json so that can be "
    "judged rather than guessed",
    "one listener, one listening session. This is a preliminary subjective result, not evidence of "
    "general superiority",
)

COMPOSITION_RATIONALE = (
    "the project's own documented example composition (docs/music_dsl.md section 4, authored by the "
    "project) and a test fixture, so its provenance is internal and it is not a copied commercial game "
    "melody; it has a recognisable lead melody on CH3, a supporting bass on CH1+CH2 and percussion on "
    "CH4, and it renders deterministically through the existing pipeline"
)

TARGET_RATIONALE = (
    "the brief asks for one melodic part; CH3 is the melody and is an 8-bit channel, which is the case "
    "Experiment 27's C1 implementation covers. The 16-bit bass on CH1+CH2 is left alone because C1 as "
    "implemented has no 16-bit divider arithmetic"
)

VOLUME_POLICY = (
    "NOT changed: the baseline's AUDC volume nibble is preserved frame for frame. Experiment 26/27's C1 "
    "also replaced the note's volume shape with plucked_volume_shape; that is deliberately not applied "
    "here, so the A/B difference is the generator and the divider only and articulation is not a "
    "confound"
)

SILENT_FRAME_POLICY = (
    "untouched: a rest or a zero-volume frame keeps the baseline's AUDF and AUDC, so the transform "
    "introduces no register write the baseline did not make"
)

PRODUCTION_STATEMENT = (
    "no DSL, IR, compiler, MADS exporter, player or CLI change; C1 is not registered as an instrument "
    "and nothing was added to the instrument library"
)




# ===========================================================================
# 1. The production path. A is whatever the existing pipeline produces.
# ===========================================================================
def load_song(composition: Path = DEFAULT_COMPOSITION) -> ir.IRSong:
    """Compile the DSL through the production path and return the POKEY IR."""
    document = load_composition_dsl(Path(composition))
    return generate_music_from_composition(document).pokey_ir


def song_total_frames(song: ir.IRSong) -> int:
    """The frame count ``compile_ir_to_pokey_frames`` will produce, by the same arithmetic."""
    pattern_map = {pattern.id: pattern for pattern in song.patterns}
    rows = 0
    for pattern_id in song.sequence:
        pattern = pattern_map.get(pattern_id)
        if pattern:
            rows += pattern.rows
    return rows * song.frames_per_tick


def baseline_stream(song: ir.IRSong) -> np.ndarray:
    """Variant A: the production compiler's own output, untouched."""
    return np.asarray(ir.compile_ir_to_pokey_frames(song))


def channel_note_spans(song: ir.IRSong, channel: int) -> List[Dict[str, Any]]:
    """Every note the compiler will place on *channel*, as ``(start, end, midi, is_rest)``.

    The arithmetic mirrors ``ir.compile_ir_to_pokey_frames`` exactly — the same per-pattern row
    cursor and the same ``duration * frames_per_tick`` note length — so the note grid the transform
    uses cannot drift from the grid the compiler used.
    """
    pattern_map = {pattern.id: pattern for pattern in song.patterns}
    total = song_total_frames(song)
    spans: List[Dict[str, Any]] = []
    index = 0
    current_frame = 0
    for pattern_id in song.sequence:
        pattern = pattern_map.get(pattern_id)
        if pattern is None:
            continue
        row_idx = 0
        for note in pattern.tracks.get(channel, []):
            duration_rows = max(1, note.duration)
            note_frames = duration_rows * song.frames_per_tick
            start_f = current_frame + row_idx * song.frames_per_tick
            end_f = min(total, start_f + note_frames)
            if start_f < total:
                midi = note.midi_pitch
                if midi is None and note.pitch:
                    midi = ir.note_name_to_midi(str(note.pitch))
                spans.append({
                    "index": index,
                    "start": start_f,
                    "end": end_f,
                    "frames": end_f - start_f,
                    "midi": midi,
                    "is_rest": bool(note.is_rest) or midi is None,
                    "pattern": pattern.name,
                })
                index += 1
            row_idx += duration_rows
        current_frame += pattern.rows * song.frames_per_tick
    return spans


# ===========================================================================
# 2. B — the same stream with C1 on the melodic channel only.
# ===========================================================================
def apply_c1(
    stream: np.ndarray,
    song: ir.IRSong,
    channel: int = MELODIC_CHANNEL,
) -> np.ndarray:
    """Rewrite one channel's divider and generator with Experiment 27's C1 schedule.

    Per sounding frame of each non-rest note, the divider becomes ``N`` on even frame offsets and
    ``N // 2`` on odd ones — ``SCHEDULES["C1"].divider_for_frame`` from Experiment 27, called
    directly — and the AUDC generator nibble becomes ``$40``.

    Two things are held back on purpose:

    * **the volume nibble** is taken from the baseline unchanged, so the comparison isolates timbre
      from articulation (see the module docstring);
    * **silent frames are not touched at all**. A rest, or a frame whose volume nibble is already 0,
      keeps the baseline's AUDF and AUDC, so the transform cannot introduce a register write the
      baseline did not make.
    """
    out = stream.copy()
    audf_col = ir.audf_column(channel)
    audc_col = ir.audc_column(channel)
    schedule = e27.SCHEDULES["C1"]
    generator = e26.C_GENERATOR & 0xE0

    for span in channel_note_spans(song, channel):
        if span["is_rest"]:
            continue
        nominal = e26.note_divider(int(span["midi"]))
        upper = e26.octave_divider(nominal)
        for offset in range(span["frames"]):
            frame = span["start"] + offset
            volume = int(stream[frame, audc_col]) & 0x0F
            if volume == 0:
                continue
            out[frame, audf_col] = schedule.divider_for_frame(
                nominal, upper, offset, span["index"]
            )
            out[frame, audc_col] = generator | volume
    return out


def stream_differences(baseline: np.ndarray, variant: np.ndarray) -> Dict[str, Any]:
    """Exactly which frames and columns differ, so the claim can be checked rather than trusted."""
    if baseline.shape != variant.shape:
        return {"same_shape": False, "baseline_shape": list(baseline.shape),
                "variant_shape": list(variant.shape)}
    differing = baseline != variant
    per_column = {
        str(column): int(np.count_nonzero(differing[:, column])) for column in range(baseline.shape[1])
    }
    return {
        "same_shape": True,
        "frames": int(baseline.shape[0]),
        "columns": int(baseline.shape[1]),
        "frames_differing": int(np.count_nonzero(differing.any(axis=1))),
        "columns_differing": sorted(int(c) for c in np.unique(np.nonzero(differing)[1])),
        "frames_differing_per_column": per_column,
    }


# ===========================================================================
# 3. The render. One shared gain, no per-file normalisation.
# ===========================================================================
def render_pair(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    composition: Path = DEFAULT_COMPOSITION,
    channel: int = MELODIC_CHANNEL,
) -> Dict[str, Any]:
    """Render A and B, write both WAVs, the summary and the listening note.

    Level policy is Experiment 26's, unchanged: both variants are rendered **raw**, one gain is
    derived from the louder of the two raw renders, and that single gain is applied to both. Nothing
    is normalised per file, so the loudness relation between A and B is preserved.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    song = load_song(composition)
    a_stream = baseline_stream(song)
    b_stream = apply_c1(a_stream, song, channel)

    a_raw = e26.render_registers(a_stream)
    b_raw = e26.render_registers(b_stream)
    reference_peak = max(float(np.max(np.abs(a_raw))), float(np.max(np.abs(b_raw))))
    if reference_peak <= 0.0:
        raise ValueError("both renders are silent; there is nothing to compare")
    gain = TARGET_PEAK / reference_peak

    a_samples = e26.to_int16(a_raw, gain)
    b_samples = e26.to_int16(b_raw, gain)
    a_path = e26.write_wav(output_dir / BASELINE_WAV, a_samples, SAMPLE_RATE)
    b_path = e26.write_wav(output_dir / C1_WAV, b_samples, SAMPLE_RATE)

    result: Dict[str, Any] = {
        "output_dir": output_dir,
        "composition": Path(composition),
        "song": song,
        "channel": channel,
        "a_stream": a_stream,
        "b_stream": b_stream,
        "a_raw": a_raw,
        "b_raw": b_raw,
        "a_samples": a_samples,
        "b_samples": b_samples,
        "gain": gain,
        "reference_peak": reference_peak,
        "files": {BASELINE_WAV: a_path, C1_WAV: b_path},
    }
    result["summary_path"] = write_summary(result, output_dir)
    result["note_path"] = write_listening_note(result, output_dir)
    return result


def _peak(buffer: np.ndarray) -> float:
    return float(np.max(np.abs(buffer)))


def _rms(buffer: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(buffer, dtype=np.float64))))


def _lead_rows(song: ir.IRSong, channel: int) -> List[Dict[str, Any]]:
    """The lead's note grid, with both dividers, for the summary."""
    rows: List[Dict[str, Any]] = []
    for span in channel_note_spans(song, channel):
        nominal = None if span["is_rest"] else e26.note_divider(int(span["midi"]))
        rows.append({
            "index": span["index"],
            "pattern": span["pattern"],
            "start_frame": span["start"],
            "end_frame": span["end"],
            "frames": span["frames"],
            "seconds": round(span["frames"] / FRAME_RATE_HZ, 4),
            "midi": span["midi"],
            "note": None if span["midi"] is None else ir.midi_to_note_name(int(span["midi"])),
            "is_rest": span["is_rest"],
            "nominal_audf": nominal,
            "octave_up_audf": None if nominal is None else e26.octave_divider(nominal),
        })
    return rows


def _measurement(label: str, variant: str, description: str, stream: np.ndarray,
                 raw: np.ndarray, samples: np.ndarray) -> Dict[str, Any]:
    """One row of the measurements table, so the level policy can be audited."""
    return {
        "file": label,
        "variant": variant,
        "description": description,
        "frames": int(stream.shape[0]),
        "samples": int(samples.shape[0]),
        "duration_seconds": round(samples.shape[0] / SAMPLE_RATE, 4),
        "raw_peak": round(_peak(raw), 6),
        "raw_rms": round(_rms(raw), 6),
        "peak_after_gain": round(float(np.max(np.abs(samples))) / 32767.0, 6),
        "rms_after_gain": round(
            float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) / 32767.0, 6
        ),
    }



def build_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """The machine record: what changed, what did not, and how the levels were handled."""
    song = result["song"]
    channel = int(result["channel"])
    spans = channel_note_spans(song, channel)
    sounding = [span for span in spans if not span["is_rest"]]
    gain = float(result["gain"])

    return {
        "experiment": "experiment28",
        "purpose": (
            "does the Experiment 27 C1 octave-pulse timbre add anything useful when one melodic part "
            "of a real game tune carries it, rather than an isolated note or a test phrase"
        ),
        "composition": {
            "file": str(Path(result["composition"]).relative_to(REPO_ROOT)).replace("\\", "/"),
            "title": song.title,
            "author": song.author,
            "tempo_bpm": song.tempo_bpm,
            "frames_per_tick": song.frames_per_tick,
            "uses_16bit_bass": song.uses_16bit_bass,
            "audctl": f"${ir.resolve_audctl_mode(song):02X}",
            "patterns": [{"id": p.id, "name": p.name, "rows": p.rows} for p in song.patterns],
            "sequence": list(song.sequence),
            "instruments": [
                {
                    "id": inst.id,
                    "name": inst.name,
                    "role": inst.role,
                    "distortion": f"${inst.distortion:02X}",
                    "envelope": inst.envelope.model_dump(),
                }
                for inst in song.instruments
            ],
            "why_this_one": COMPOSITION_RATIONALE,
        },
        "target": {
            "channel": channel,
            "role": "lead (melody)",
            "why_this_one": TARGET_RATIONALE,
            "notes_total": len(spans),
            "notes_sounding": len(sounding),
            "rests": len(spans) - len(sounding),
            "sounding_frames": sum(span["frames"] for span in sounding),
            "register": {
                "lowest_midi": min((s["midi"] for s in sounding), default=None),
                "highest_midi": max((s["midi"] for s in sounding), default=None),
                "distinct_dividers": sorted({e26.note_divider(int(s["midi"])) for s in sounding}),
            },
            "notes": _lead_rows(song, channel),
        },
        "c1_effect": {
            "source": (
                "pokey_octave_pulse_experiment.SCHEDULES['C1'].divider_for_frame, called directly; "
                "generator from pokey_timbre_experiment.C_GENERATOR; octave value from "
                "pokey_timbre_experiment.octave_divider"
            ),
            "generator": f"${e26.C_GENERATOR:02X}",
            "divider": (
                "N on even frame offsets, N // 2 on odd frame offsets, restarting at every note onset"
            ),
            "alternation_hz": e27.SCHEDULES["C1"].alternation_hz,
            "volume": VOLUME_POLICY,
            "silent_frames": SILENT_FRAME_POLICY,
        },
        "identical_between_a_and_b": [
            "the composition document and the compiled IR (one compilation, two streams)",
            "note onsets, pitches, durations and phrase timing on every channel",
            "channels 1, 2 and 4 and their register streams, frame for frame",
            "AUDCTL, the frame rate, the sample rate, the bit depth and the output duration",
            "the shared gain and the render path",
        ],
        "differences": stream_differences(result["a_stream"], result["b_stream"]),
        "level_policy": {
            "per_file_normalisation": False,
            "shared_gain": round(gain, 8),
            "reference_peak": round(float(result["reference_peak"]), 8),
            "target_peak": TARGET_PEAK,
            "note": (
                "one gain derived from the louder of the two raw renders is applied to both, so the "
                "loudness relation between A and B is preserved and nothing clips"
            ),
        },
        "measurements": [
            _measurement(BASELINE_WAV, "A", "the existing pipeline, unmodified",
                         result["a_stream"], result["a_raw"], result["a_samples"]),
            _measurement(C1_WAV, "B", "the same stream with C1 on the lead channel only",
                         result["b_stream"], result["b_raw"], result["b_samples"]),
        ],
        "limitations": list(LIMITATIONS),
        "not_claimed": [
            "that C1 sounds better, richer or more musical in context — that is a listening question",
            "that C1 is ready for production integration, or that it should become an instrument",
            "that these two files generalise beyond this one composition and this one part",
            "that the C1 effect tested here is identical to Experiment 27's: the volume shape is held "
            "at the baseline's, which is a deliberate narrowing",
        ],
        "production_untouched": PRODUCTION_STATEMENT,
    }


def write_summary(result: Dict[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "summary.json"
    path.write_text(
        json.dumps(build_summary(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def listening_note(result: Dict[str, Any]) -> str:
    """The short listening instruction that ships next to the two WAVs."""
    summary = build_summary(result)
    composition = summary["composition"]
    target = summary["target"]
    differences = summary["differences"]
    lines: List[str] = [
        "# Experiment 28 — how to listen",
        "",
        "Two files, one composition, one difference.",
        "",
        "* **`A_baseline.wav`** — the composition as the existing pipeline renders it.",
        "* **`B_c1.wav`** — the same render with the C1 octave-pulse timbre on the **lead melody only**.",
        "",
        f"Both are `{composition['title']}` by {composition['author']}, "
        f"{composition['tempo_bpm']} BPM, {composition['frames_per_tick']} frames per row, "
        f"{summary['measurements'][0]['duration_seconds']:.1f} seconds, 44.1 kHz 16-bit mono.",
        "",
        "## How to compare",
        "",
        "1. Set your volume once and leave it alone — both files use the same gain, and neither was",
        "   normalised on its own.",
        "2. Play `A_baseline.wav` through once, then `B_c1.wav` through once, without stopping.",
        "3. Then alternate between them, ideally starting each pass from the same point, and listen for",
        "   **the lead line only**. The bass and the percussion are byte-identical in both files.",
        "4. Ask: does the lead sound like a *different instrument*, or like the same instrument with a",
        "   fault? Does the melody stay recognisable? Does it wear out after thirty seconds?",
        "",
        "## What is different",
        "",
        f"* the lead is on channel {target['channel']}, {target['notes_sounding']} sounding notes "
        f"({target['sounding_frames']} frames);",
        "* in B, every sounding lead frame carries AUDC generator `$40` instead of the baseline's `$A0`;",
        "* in B, the lead's divider alternates every frame between the note's nominal `N` and `N // 2`, "
        "restarting at each note onset (25 Hz);",
        f"* nothing else: {differences['frames_differing']} of {differences['frames']} frames differ, and "
        f"only in register columns {differences['columns_differing']} (AUDF3 and AUDC3).",
        "",
        "The lead's **volume is unchanged**, deliberately, so this is the generator and the divider only.",
        "",
        "## Levels",
        "",
        f"One shared gain of `{summary['level_policy']['shared_gain']}` was applied to both files, taken",
        f"from the louder of the two raw renders (reference peak "
        f"`{summary['level_policy']['reference_peak']}`). No file was normalised on its own.",
        "",
        "| file | raw RMS | RMS after the shared gain |",
        "|---|---|---|",
    ]
    for row in summary["measurements"]:
        lines.append(f"| `{row['file']}` | {row['raw_rms']:.4f} | {row['rms_after_gain']:.4f} |")
    lines += [
        "",
        "The two RMS figures are close, but `$40` and `$A0` do not have exactly the same energy at the",
        "same DAC volume, so a small part of any perceived difference may be loudness. Judge timbre,",
        "not level.",
        "",
        "## What this experiment does not show",
        "",
        "Two files cannot establish that C1 is better, and nothing here measures quality. It is one",
        "composition, one part, one listener. See the limitations in `summary.json` and in",
        "`docs/experiment28_c1_musical_context.md`.",
        "",
        "## Regenerating",
        "",
        "```",
        "python -m atari_music.pokey_c1_musical_context_experiment",
        "```",
        "",
        "Deterministic: the same command reproduces both files byte for byte.",
        "",
    ]
    return "\n".join(lines)


def write_listening_note(result: Dict[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "README.md"
    path.write_text(listening_note(result), encoding="utf-8")
    return path


def main() -> int:
    """Render the pair and print where the files are. No production code is touched."""
    result = render_pair()
    summary = build_summary(result)
    differences = summary["differences"]
    print(f"composition: {summary['composition']['title']} "
          f"({summary['composition']['file']})")
    print(f"target:      CH{summary['target']['channel']} "
          f"({summary['target']['role']}), {summary['target']['notes_sounding']} sounding notes")
    print(f"shared gain: {summary['level_policy']['shared_gain']} "
          f"(reference peak {summary['level_policy']['reference_peak']})")
    print(f"difference:  {differences['frames_differing']}/{differences['frames']} frames, "
          f"columns {differences['columns_differing']}")
    for row in summary["measurements"]:
        print(f"  {row['file']:16s} {row['frames']:5d} frames  {row['duration_seconds']:6.2f}s  "
              f"rms {row['rms_after_gain']:.4f}")
    print(f"summary: {result['summary_path']}")
    print(f"listening note: {result['note_path']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())





