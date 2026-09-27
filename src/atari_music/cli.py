"""CLI interface for Atari 8-bit Music Analysis Toolkit."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import click

from atari_music.dataset import build_full_dataset
from atari_music.extractor import extract_raw_dump
from atari_music.logging_config import setup_logging


def _set_log_level(ctx: click.Context, param: click.Parameter, value: Optional[str]) -> Optional[str]:
    """Callback to eagerly configure logging level."""
    if value is not None:
        setup_logging(value)
    elif not logging.getLogger().handlers:
        setup_logging()
    return value


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default=None,
    envvar="LOG_LEVEL",
    is_eager=True,
    expose_value=True,
    callback=_set_log_level,
    help="Global logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
)
def cli(log_level: Optional[str] = None) -> None:
    """Atari 8-bit POKEY Music Composer & Toolchain: procedural and AI-assisted music composition, validation, software synthesis, and relocatable MOS 6502 assembly compilation."""
    pass



@cli.command("extract", hidden=True)
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    default=Path("inventory.json"),
    help="Path to inventory.json file",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("dataset"),
    help="Directory where dataset artifacts will be created",
)
@click.option(
    "--asapscan",
    type=click.Path(exists=True, path_type=Path),
    default=Path("tools/asap/asapscan.exe"),
    help="Path to asapscan binary",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=None,
    help="Limit maximum subsongs to process (for testing/benchmarks)",
)
def extract_cmd(
    inventory: Path,
    output_dir: Path,
    asapscan: Path,
    limit: Optional[int],
) -> None:
    """Execute full 3-layer extraction on all SAP files and generate dataset.jsonl."""
    click.echo(f"Starting full POKEY extraction using inventory {inventory}...")
    success, fail, failed_items = build_full_dataset(
        inventory_path=inventory,
        dataset_dir=output_dir,
        asapscan_bin=str(asapscan),
        max_subsongs=limit,
    )
    click.echo(f"\nExtraction completed!")
    click.echo(f"  Successfully processed subsongs: {success}")
    click.echo(f"  Failed subsongs: {fail}")
    if failed_items:
        click.echo("  Failures:")
        for item in failed_items[:10]:
            click.echo(f"    - {item}")


@cli.command("analyze")
@click.argument("composition_json", type=click.Path(exists=True, path_type=Path))
@click.option("--structure", "-s", is_flag=True, default=False, help="Include detailed macro-structural and form analysis.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output machine-readable JSON to stdout.")
@click.option("--output-json", "-o", type=click.Path(path_type=Path), default=None, help="Save JSON analysis report to file.")
def analyze_cmd(
    composition_json: Path,
    structure: bool,
    as_json: bool,
    output_json: Optional[Path],
) -> None:
    """Analyze musical properties, hardware constraints, and structure of a composition JSON."""
    from atari_music.ai.analysis import analyze_composition
    from atari_music.ai.client import load_composition_json
    from atari_music.ai.structure_analysis import analyze_composition_structure

    comp_doc = load_composition_json(composition_json)
    rep = analyze_composition(comp_doc)
    struct_rep = analyze_composition_structure(comp_doc) if structure else None

    if as_json or output_json:
        data = rep.model_dump(mode="json")
        if struct_rep:
            data["macro_structure"] = struct_rep.model_dump(mode="json")
        json_str = json.dumps(data, indent=2)
        if output_json:
            output_json.parent.mkdir(parents=True, exist_ok=True)
            output_json.write_text(json_str, encoding="utf-8")
        if as_json:
            click.echo(json_str)
        elif output_json:
            click.echo(f"Analysis saved to {output_json}")

    if not as_json:
        click.echo(f"=== Composition Analysis: {comp_doc.metadata.title} ===")
        click.echo(f"  Fingerprint (SHA-256): {rep.fingerprint}")
        click.echo(f"  Key/Mode:             {comp_doc.metadata.key} {comp_doc.metadata.mode}")
        click.echo(f"  Tempo:                {comp_doc.metadata.bpm} BPM")
        click.echo(f"  Duration (PAL 50Hz):  {rep.structure.duration_seconds:.2f}s ({rep.structure.sequence_length} steps across {rep.structure.sequence_pattern_count} patterns)")
        click.echo(f"  Repetition Ratio:     {rep.structure.repetition_ratio:.1%}")

        click.echo("\n[Rhythm & Notes]")
        click.echo(f"  Total Notes:          {rep.rhythm.total_notes}")
        click.echo(f"  Note Density:         {rep.rhythm.note_density:.2f} notes/sec")
        click.echo(f"  Rest Ratio:           {rep.rhythm.rest_ratio:.1%}")
        click.echo(f"  Average Note Length:  {rep.rhythm.avg_note_length:.2f} steps")

        click.echo("\n[Melody & Harmony]")
        click.echo(f"  Pitch Range:          {rep.melody.pitch_range_semitones} semitones (MIDI {rep.melody.min_pitch}..{rep.melody.max_pitch})")
        click.echo(f"  Melodic Direction:    {rep.melody.melodic_direction}")
        click.echo(f"  Stepwise vs Leap:     {rep.melody.stepwise_vs_leap_ratio:.2f}")
        click.echo(f"  Consonance Ratio:     {rep.harmony.consonance_ratio:.1%} ({rep.harmony.consonant_intervals_count} consonant / {rep.harmony.dissonant_intervals_count} dissonant)")
        click.echo(f"  Sounding Chords:      {rep.harmony.sounding_chords_count} steps with vertical chords")

        click.echo("\n[POKEY Hardware Utilization]")
        click.echo(f"  Channels Configured:  {comp_doc.hardware.channels}")
        bass_status = f"Yes ({rep.pokey.bass_16bit_channel_usage})" if rep.pokey.uses_16bit_bass else "No"
        click.echo(f"  16-bit Bass Mode:     {bass_status}")
        if rep.pokey.audf_frequency_range:
            click.echo(f"  AUDF Register Range:  {rep.pokey.audf_frequency_range.get('min_audf')} .. {rep.pokey.audf_frequency_range.get('max_audf')}")
        if rep.pokey.warnings:
            click.echo(f"  Warnings ({len(rep.pokey.warnings)}):")
            for w in rep.pokey.warnings:
                click.echo(f"    ! {w}")
        else:
            click.echo("  Hardware Warnings:    None (within safe player bounds)")

        if struct_rep:
            click.echo("\n[Macro-Structure & Form]")
            click.echo(f"  Deduced Form:         {struct_rep.form.compact_form}")
            click.echo(f"  Form Archetype:       {struct_rep.form.archetype}")
            click.echo(f"  Material Reuse Ratio: {struct_rep.material_reuse_ratio:.1%}")
            click.echo(f"  Thematic Variations:  {struct_rep.variation_count} patterns ({struct_rep.variation_ratio:.1%})")
            click.echo(f"  Structural Novelty:   {struct_rep.structural_novelty:.1%}")
            click.echo(f"  Shannon Diversities:  Melody={struct_rep.melodic_diversity:.2f}, Rhythm={struct_rep.rhythmic_diversity:.2f}, Harmony={struct_rep.harmonic_diversity:.2f}")

        if output_json and not as_json:
            click.echo(f"\nSaved JSON report -> {output_json}")


@cli.command("reanalyze-raw", hidden=True)
@click.option(
    "--dataset-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset"),
    help="Path to dataset directory",
)
def reanalyze_raw_cmd(dataset_dir: Path) -> None:
    """Re-analyze features and update dataset.jsonl directly from existing RAW dumps."""
    from atari_music.dataset import reanalyze_dataset_from_raw

    click.echo(f"Re-analyzing dataset from raw dumps in {dataset_dir}...")
    updated = reanalyze_dataset_from_raw(dataset_dir)
    click.echo(f"Successfully re-analyzed {updated} subsongs.")


@cli.command("report", hidden=True)
@click.option(
    "--dataset-jsonl",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset/dataset.jsonl"),
    help="Path to dataset.jsonl file",
)
@click.option(
    "--output-report",
    type=click.Path(path_type=Path),
    default=Path("report_stage2.md"),
    help="Output report markdown path",
)
def report_cmd(dataset_jsonl: Path, output_report: Path) -> None:
    """Generate comprehensive Stage 2 statistical report from dataset.jsonl."""
    from atari_music.reporting import generate_stage2_report

    click.echo(f"Generating Stage 2 report from {dataset_jsonl}...")
    generate_stage2_report(dataset_jsonl, output_report)
    click.echo(f"Saved report to {output_report}")


@cli.command("stage3", hidden=True)
@click.option(
    "--dataset-jsonl",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset/dataset.jsonl"),
    help="Path to dataset.jsonl",
)
@click.option(
    "--visualizations-dir",
    type=click.Path(path_type=Path),
    default=Path("visualizations"),
    help="Output directory for visual dashboards and audio validation",
)
@click.option(
    "--output-report",
    type=click.Path(path_type=Path),
    default=Path("stage3_report.md"),
    help="Output Stage 3 report path",
)
def stage3_cmd(dataset_jsonl: Path, visualizations_dir: Path, output_report: Path) -> None:
    """Execute complete Stage 3 verification, visualization, and report generation."""
    from atari_music.stage3_reporter import run_stage3_pipeline

    click.echo("Running Stage 3 verification pipeline...")
    run_stage3_pipeline(dataset_jsonl, visualizations_dir, output_report)
    click.echo("Stage 3 pipeline complete!")


@cli.command("mine-archetypes", hidden=True)
@click.option(
    "--dataset-jsonl",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset/dataset.jsonl"),
    help="Path to dataset.jsonl",
)
@click.option(
    "--output-path",
    type=click.Path(path_type=Path),
    default=Path("dataset/archetypes.json"),
    help="Output JSON path for mined archetype library",
)
def mine_archetypes_cmd(dataset_jsonl: Path, output_path: Path) -> None:
    """Mine empirical melody, rhythm, bass, and percussion archetypes from dataset."""
    from atari_music.archetypes import mine_archetypes_from_dataset

    click.echo(f"Mining musical archetypes from {dataset_jsonl}...")
    lib = mine_archetypes_from_dataset(dataset_jsonl)
    lib.to_json_file(output_path)
    click.echo(f"Archetype library saved to {output_path}")


@cli.command("generate-song", hidden=True)
@click.option("--seed", type=int, default=42, help="RNG seed for procedural generation")
@click.option("--key", type=str, default="C", help="Musical key (C, D, E, F, G, A, B)")
@click.option("--mode", type=str, default="minor", help="Scale mode (minor, major, dorian, pentatonic)")
@click.option("--tempo", type=int, default=125, help="Tempo in BPM")
@click.option("--distortion-style", type=str, default="hybrid", help="pure_a0, gritty_c0, hybrid")
@click.option("--output-json", type=click.Path(path_type=Path), default=Path("generated/song_custom.json"))
@click.option("--output-wav", type=click.Path(path_type=Path), default=Path("generated/song_custom.wav"))
def generate_song_cmd(
    seed: int,
    key: str,
    mode: str,
    tempo: int,
    distortion_style: str,
    output_json: Path,
    output_wav: Path,
) -> None:
    """Generate a single procedural song, save IR JSON, and render POKEY WAV."""
    from atari_music.generator import generate_song
    from atari_music.ir import calculate_ir_binary_size, compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    params = {
        "key": key,
        "mode": mode,
        "tempo": tempo,
        "distortion_style": distortion_style,
    }
    song = generate_song(seed=seed, parameters=params)
    song.to_json_file(output_json)
    size_b = calculate_ir_binary_size(song)
    click.echo(f"Generated song: '{song.title}' -> IR size: {size_b} B (budget: 2048 B)")

    frames = compile_ir_to_pokey_frames(song)
    render_pokey_to_wav(frames, output_wav)
    click.echo(f"Rendered WAV: {output_wav} ({frames.shape[0]/50.0:.2f} seconds)")


@cli.command("run-experiment", hidden=True)
@click.option("--count", "-n", type=int, default=100, help="Number of songs to generate")
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("generated"))
@click.option("--dataset-jsonl", type=click.Path(exists=True, path_type=Path), default=Path("dataset/dataset.jsonl"))
def run_experiment_cmd(count: int, output_dir: Path, dataset_jsonl: Path) -> None:
    """Generate batch of N songs, render WAVs, compute metrics, and compare with REAL dataset."""
    from atari_music.batch_experiment import run_batch_experiment

    run_batch_experiment(count=count, out_dir=output_dir, dataset_jsonl_path=dataset_jsonl)


@cli.command("stage4-report", hidden=True)
@click.option("--summary-json", type=click.Path(exists=True, path_type=Path), default=Path("generated/analysis_summary.json"))
@click.option("--archetypes-json", type=click.Path(exists=True, path_type=Path), default=Path("dataset/archetypes.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage4_report.md"))
def stage4_report_cmd(summary_json: Path, archetypes_json: Path, output_report: Path) -> None:
    """Generate stage4_report.md from batch experiment results and archetype library."""
    from atari_music.stage4_reporter import generate_stage4_report

    click.echo(f"Generating Stage 4 report -> {output_report}...")
    generate_stage4_report(summary_json, archetypes_json, output_report)
    click.echo("Stage 4 report generated successfully!")


@cli.command("prepare-listening-test", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test"))
@click.option("--raw-dir", type=click.Path(exists=True, path_type=Path), default=Path("dataset/raw"))
@click.option("--dataset-jsonl", type=click.Path(exists=True, path_type=Path), default=Path("dataset/dataset.jsonl"))
def prepare_listening_test_cmd(output_dir: Path, raw_dir: Path, dataset_jsonl: Path) -> None:
    """Prepare 30-sample blinded listening test (Group A, B, and C) with WAVs, CSV, and key."""
    from atari_music.listening_test import prepare_listening_test

    prepare_listening_test(output_dir=output_dir, dataset_raw_dir=raw_dir, dataset_jsonl=dataset_jsonl)


@cli.command("stage5-report", hidden=True)
@click.option("--test-dir", type=click.Path(exists=True, path_type=Path), default=Path("listening_test"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage5_report.md"))
def stage5_report_cmd(test_dir: Path, output_report: Path) -> None:
    """Generate stage5_report.md from listening test setup."""
    from atari_music.stage5_reporter import generate_stage5_report

    click.echo(f"Generating Stage 5 report -> {output_report}...")
    generate_stage5_report(test_dir, output_report)
    click.echo("Stage 5 report generated successfully!")


@cli.command("investigate-memorization", hidden=True)
@click.option("--raw-dir", type=click.Path(exists=True, path_type=Path), default=Path("dataset/raw"))
@click.option("--generated-dir", type=click.Path(exists=True, path_type=Path), default=Path("generated"))
@click.option("--output-comp", type=click.Path(path_type=Path), default=Path("generator_comparison.md"))
@click.option("--output-stage5-5", type=click.Path(path_type=Path), default=Path("stage5_5_report.md"))
def investigate_cmd(raw_dir: Path, generated_dir: Path, output_comp: Path, output_stage5_5: Path) -> None:
    """Run full memorization, transposition, and novelty investigation pipeline."""
    from atari_music.run_investigation import run_full_investigation

    click.echo("Starting Stage 5.5 Memorization & Novelty Investigation...")
    run_full_investigation(
        dataset_raw_dir=raw_dir,
        generated_dir=generated_dir,
        output_comparison_md=output_comp,
        output_stage5_5_md=output_stage5_5,
    )
    click.echo("Investigation finished successfully!")


@cli.command("compose-v2", hidden=True)
@click.option("--seed", type=int, default=42, help="RNG seed")
@click.option("--novelty", type=float, default=0.65, help="Novelty parameter (0.0 .. 1.0)")
@click.option("--key", type=str, default="C", help="Musical key")
@click.option("--mode", type=str, default="minor", help="Scale mode")
@click.option("--tempo", type=int, default=130, help="Tempo in BPM")
@click.option("--min-channels", type=int, default=2, help="Minimum active channels")
@click.option("--max-channels", type=int, default=4, help="Maximum active channels")
@click.option("--output-wav", type=click.Path(path_type=Path), default=Path("generated/composer_v2_sample.wav"))
@click.option("--output-json", type=click.Path(path_type=Path), default=Path("generated/composer_v2_sample.json"))
def compose_v2_cmd(
    seed: int,
    novelty: float,
    key: str,
    mode: str,
    tempo: int,
    min_channels: int,
    max_channels: int,
    output_wav: Path,
    output_json: Path,
) -> None:
    """Compose a song using Composer v2 with pure Music IR, interval grammar, and constraints."""
    from atari_music.composer_v2 import ComposerV2Config, compose_song_v2
    from atari_music.ir import compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    cfg = ComposerV2Config(
        seed=seed,
        novelty=novelty,
        key=key,
        mode=mode,
        tempo=tempo,
        min_channels=min_channels,
        max_channels=max_channels,
    )
    res = compose_song_v2(cfg)
    res.pokey_ir.to_json_file(output_json)
    frames = compile_ir_to_pokey_frames(res.pokey_ir)
    render_pokey_to_wav(frames, output_wav)
    click.echo(f"Composed song: {res.music_ir.title}")
    click.echo(f"Quality: {res.quality_report.model_dump()}")
    click.echo(f"Saved: {output_json} & {output_wav}")


@cli.command("run-composer-v2-experiment", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("experiments/composer_v2"))
@click.option("--raw-dir", type=click.Path(exists=True, path_type=Path), default=Path("dataset/raw"))
def run_v2_experiment_cmd(output_dir: Path, raw_dir: Path) -> None:
    """Run full 60-song experiment (novelty 0.50, 0.65, 0.80) and generate summary."""
    from atari_music.composer_v2_experiment import run_composer_v2_experiments

    run_composer_v2_experiments(base_out_dir=output_dir, dataset_raw_dir=raw_dir)


@cli.command("stage6-report", hidden=True)
@click.option("--summary-json", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v2/summary.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage6_composer_v2_report.md"))
def stage6_report_cmd(summary_json: Path, output_report: Path) -> None:
    """Generate stage6_composer_v2_report.md from experiment results."""
    from atari_music.stage6_reporter import generate_stage6_report

    click.echo(f"Generating Stage 6 report -> {output_report}...")
    generate_stage6_report(summary_json, output_report)
    click.echo("Stage 6 report generated successfully!")


@cli.command("prepare-listening-test-v2", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test_v2"))
@click.option("--seed", type=int, default=2026, help="Randomization seed for anonymization")
def prepare_listening_test_v2_cmd(output_dir: Path, seed: int) -> None:
    """Prepare 80-sample blinded listening test (Group A, B, C, D) with WAVs, CSV, and keys."""
    from atari_music.listening_test_v2 import prepare_listening_test_v2, validate_listening_test_v2

    click.echo(f"Preparing Stage 6.5 blind listening test in '{output_dir}'...")
    res = prepare_listening_test_v2(output_dir=output_dir, seed=seed)
    click.echo(f"Successfully copied and randomized {res['total_samples']} samples!")
    click.echo("Running pre-flight validation checks...")
    val = validate_listening_test_v2(output_dir)
    click.echo(f"Validation status: {val['status']}")


@cli.command("validate-listening-test-v2", hidden=True)
@click.option("--test-dir", type=click.Path(exists=True, path_type=Path), default=Path("listening_test_v2"))
def validate_listening_test_v2_cmd(test_dir: Path) -> None:
    """Run rigorous sanity checks on listening_test_v2 artifacts."""
    from atari_music.listening_test_v2 import validate_listening_test_v2

    click.echo(f"Validating test artifacts in '{test_dir}'...")
    val = validate_listening_test_v2(test_dir)
    click.echo(f"{val['status']}")
    click.echo(f"Distribution: {val['group_distribution']}")
    click.echo(f"Peak bounds: {val['peak_range']}, RMS bounds: {val['rms_range']}")


@cli.command("stage6-5-report", hidden=True)
@click.option("--test-dir", type=click.Path(exists=True, path_type=Path), default=Path("listening_test_v2"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage6_5_listening_report.md"))
def stage6_5_report_cmd(test_dir: Path, output_report: Path) -> None:
    """Generate stage6_5_listening_report.md from listening test v2 setup."""
    from atari_music.listening_test_v2 import generate_stage6_5_report

    click.echo(f"Generating Stage 6.5 report -> {output_report}...")
    generate_stage6_5_report(test_dir, output_report)
    click.echo("Stage 6.5 report generated successfully!")


@cli.command("audit-diversity", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test_v2_selected"))
@click.option("--report-path", type=click.Path(path_type=Path), default=Path("stage6_6_diversity_report.md"))
def audit_diversity_cmd(output_dir: Path, report_path: Path) -> None:
    """Run full Diversity Audit (Stage 6.6) across 80 tracks and build selected 30-track suite."""
    from atari_music.diversity_audit import (
        extract_all_80_track_features,
        compute_similarity_matrices,
        run_clustering,
        select_30_diverse_tracks,
        create_selected_test_suite,
        generate_diversity_report,
    )

    click.echo("Extracting features from all 80 generated tracks...")
    tracks = extract_all_80_track_features()
    click.echo(f"Extracted features for {len(tracks)} tracks.")

    click.echo("Computing multidimensional similarity & distance matrices...")
    sim_data = compute_similarity_matrices(tracks)

    click.echo("Running clustering and silhouette analysis...")
    clust_res = run_clustering(sim_data["overall_dist"], tracks)
    click.echo(f"Optimal clusters found: k={clust_res['best_k']} (Silhouette: {clust_res['best_silhouette']})")

    click.echo("Selecting 30 most diverse & representative tracks across all groups...")
    selected = select_30_diverse_tracks(tracks, sim_data["overall_dist"])
    click.echo(f"Selected {len(selected)} diverse tracks.")

    click.echo(f"Creating selected test suite in '{output_dir}'...")
    suite_info = create_selected_test_suite(selected, output_dir=output_dir)
    click.echo(f"Created suite with {suite_info['selected_count']} WAVs and answer key.")

    click.echo(f"Generating Diversity Audit Report -> {report_path}...")
    generate_diversity_report(tracks, sim_data, clust_res, selected, report_path)
    click.echo("Stage 6.6 Diversity Report generated successfully!")


@cli.command("compose-v3", hidden=True)
@click.option("--profile", "-p", type=str, default="title", help="Music profile: title, exploration, action, funny, dungeon, ending")
@click.option("--seed", "-s", type=int, default=42, help="Deterministic RNG seed")
@click.option("--tempo", type=int, default=None, help="Optional tempo BPM override")
@click.option("--key", "-k", type=str, default=None, help="Key override (C, D, E, F, G, A, B)")
@click.option("--mode", "-m", type=str, default=None, help="Mode override (minor, major, dorian, mixolydian)")
@click.option("--novelty", type=float, default=None, help="Novelty override (0.0 .. 1.0)")
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Path for output JSON")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Path for output WAV")
def compose_v3_cmd(
    profile: str,
    seed: int,
    tempo: Optional[int],
    key: Optional[str],
    mode: Optional[str],
    novelty: Optional[float],
    output_json: Optional[Path],
    output_wav: Optional[Path],
) -> None:
    """Compose a song using Composer v3 with specified profile."""
    from atari_music.composer_v3 import compose_song_v3
    from atari_music.ir import compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    res = compose_song_v3(
        profile=profile,
        seed=seed,
        tempo=tempo,
        key=key,
        mode=mode,
        novelty=novelty,
    )

    q = res.quality_report
    click.echo(f"Composed [{res.profile_name.upper()}]: '{res.music_ir.title}'")
    click.echo(f"Tempo: {q.tempo} BPM, Form: {q.form}, Dur: {q.duration:.1f}s, Mem: {q.memory_size} B, Channels: {q.channels_used}")

    if output_json:
        res.pokey_ir.to_json_file(output_json)
        click.echo(f"Saved POKEY IR -> {output_json}")

    if output_wav:
        frames = compile_ir_to_pokey_frames(res.pokey_ir)
        render_pokey_to_wav(frames, output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")


@cli.command("run-composer-v3-experiment", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("experiments/composer_v3"))
def run_composer_v3_experiment_cmd(output_dir: Path) -> None:
    """Run 18-track experiment across all 6 profiles (3 tracks per profile)."""
    from atari_music.composer_v3_experiment import run_composer_v3_experiment

    click.echo(f"Running Composer v3 experiment -> {output_dir}...")
    run_composer_v3_experiment(output_dir=output_dir)
    click.echo("Composer v3 experiment completed successfully!")


@cli.command("stage7-report", hidden=True)
@click.option("--summary-json", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v3/summary.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage7_composer_v3_report.md"))
def stage7_report_cmd(summary_json: Path, output_report: Path) -> None:
    """Generate stage7_composer_v3_report.md from experiment results."""
    from atari_music.stage7_reporter import generate_stage7_report

    click.echo(f"Generating Stage 7 report -> {output_report}...")
    generate_stage7_report(summary_json, output_report)
    click.echo("Stage 7 report generated successfully!")


@cli.command("prepare-listening-test-v3", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test_v3"))
@click.option("--seed", type=int, default=42)
def prepare_listening_test_v3_cmd(output_dir: Path, seed: int) -> None:
    """Prepare Stage 7.1 blind listening test suite with 18 randomized WAVs."""
    from atari_music.listening_test_v3 import prepare_listening_test_v3

    click.echo(f"Preparing Stage 7.1 listening test suite -> {output_dir}...")
    res = prepare_listening_test_v3(output_dir=output_dir, seed=seed)
    click.echo(f"Generated {res['total_samples']} randomized samples and templates successfully!")


@cli.command("stage7-1-report", hidden=True)
@click.option("--test-dir", type=click.Path(path_type=Path), default=Path("listening_test_v3"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage7_1_listening_report.md"))
def stage7_1_report_cmd(test_dir: Path, output_report: Path) -> None:
    """Execute perceptual audit and generate stage7_1_listening_report.md."""
    from atari_music.listening_test_v3 import execute_full_stage7_1_validation

    click.echo("Running Stage 7.1 perceptual audit and generating report...")
    res = execute_full_stage7_1_validation(base_dir=Path("."))
    click.echo(f"Report generated successfully -> {res['report_path']}")


@cli.command("compose")
@click.option("--profile", "-p", type=str, default="action", help="Music profile: title, exploration, action, funny, dungeon, ending")
@click.option("--seed", "-s", type=int, default=1234, help="Deterministic RNG seed")
@click.option("--key", "-k", type=str, default=None, help="Root key (C, D, E, F, G, A, B)")
@click.option("--tempo", "-t", type=int, default=None, help="Tempo in BPM (50..240)")
@click.option("--length", "-l", type=click.Choice(["short", "medium", "long"], case_sensitive=False), default=None, help="Duration intent: short, medium, long")
@click.option("--intensity", type=float, default=None, help="Expected intensity (0.0 .. 1.0)")
@click.option("--variation", "-v", type=float, default=None, help="Motivic variation level (0.0 .. 1.0)")
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Path for output JSON")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Path for output WAV")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Path for output MADS assembly (.asm)")
def compose_cmd(
    profile: str,
    seed: int,
    key: Optional[str],
    tempo: Optional[int],
    length: Optional[str],
    intensity: Optional[float],
    variation: Optional[float],
    output_json: Optional[Path],
    output_wav: Optional[Path],
    output_asm: Optional[Path],
) -> None:
    """Generate Atari POKEY music via the public Music Generation API."""
    from atari_music.api import generate_music
    from atari_music.mads_exporter import export_mads_asm

    res = generate_music(
        profile=profile,
        seed=seed,
        key=key,
        tempo=tempo,
        length=length,
        intensity=intensity,
        variation=variation,
    )
    m = res.metadata
    click.echo(f"Generated [{m.profile.upper()}]: '{res.music_ir.title}' (Seed: {m.seed})")
    click.echo(f"Key: {m.key} {m.mode}, Tempo: {m.tempo} BPM, Form: {m.form}, Dur: {m.duration:.1f}s, Mem: {m.memory_size_bytes} B, Channels: {m.channels_used}")

    if output_json:
        res.save_json(output_json)
        click.echo(f"Saved POKEY IR -> {output_json}")

    if output_wav:
        res.render_wav(output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")

    if output_asm:
        export_mads_asm(res, output_asm)
        click.echo(f"Exported MADS ASM -> {output_asm}")


@cli.command("export-mads")
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output-asm", "-o", type=click.Path(path_type=Path), required=True, help="Destination MADS assembly path")
def export_mads_cmd(input_json: Path, output_asm: Path) -> None:
    """Convert an existing POKEY IR JSON into relocatable MADS assembly data."""
    from atari_music.ir import IRSong
    from atari_music.mads_exporter import export_mads_asm

    song = IRSong.from_json_file(input_json)
    export_mads_asm(song, output_asm)
    click.echo(f"Successfully exported '{song.title}' -> {output_asm}")


@cli.command("compose-v4", hidden=True)
@click.option("--profile", "-p", type=str, default="title", help="Music profile: title, exploration, action, funny, dungeon, ending")
@click.option("--seed", "-s", type=int, default=42, help="Deterministic RNG seed")
@click.option("--tempo", type=int, default=None, help="Optional tempo BPM override")
@click.option("--key", "-k", type=str, default=None, help="Key override (C, D, E, F, G, A, B)")
@click.option("--mode", "-m", type=str, default=None, help="Mode override (minor, major, dorian, mixolydian)")
@click.option("--novelty", type=float, default=None, help="Novelty override (0.0 .. 1.0)")
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Path for output JSON")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Path for output WAV")
def compose_v4_cmd(
    profile: str,
    seed: int,
    tempo: Optional[int],
    key: Optional[str],
    mode: Optional[str],
    novelty: Optional[float],
    output_json: Optional[Path],
    output_wav: Optional[Path],
) -> None:
    """Compose a song using Composer v4 with specified profile."""
    from atari_music.composer_v4 import compose_song_v4
    from atari_music.ir import compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    res = compose_song_v4(
        profile=profile,
        seed=seed,
        tempo=tempo,
        key=key,
        mode=mode,
        novelty=novelty,
    )

    q = res.quality_report
    click.echo(f"Composed [{res.profile_name.upper()}]: '{res.music_ir.title}'")
    click.echo(f"Tempo: {q.tempo} BPM, Form: {q.form}, Dur: {q.duration:.1f}s, Mem: {q.memory_size} B, Channels: {q.channels_used}")
    click.echo(f"Section Voice Counts: {q.section_channel_counts}")

    if output_json:
        res.pokey_ir.to_json_file(output_json)
        click.echo(f"Saved POKEY IR -> {output_json}")

    if output_wav:
        frames = compile_ir_to_pokey_frames(res.pokey_ir)
        render_pokey_to_wav(frames, output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")


@cli.command("run-composer-v4-experiment", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("experiments/composer_v4"))
def run_composer_v4_experiment_cmd(output_dir: Path) -> None:
    """Run 18-track experiment across all 6 profiles for Composer v4."""
    from atari_music.composer_v4_experiment import run_composer_v4_experiment

    click.echo(f"Running Composer v4 experiment -> {output_dir}...")
    run_composer_v4_experiment(output_dir=output_dir)
    click.echo("Composer v4 experiment completed successfully!")


@cli.command("stage8-report", hidden=True)
@click.option("--v3-summary", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v3/summary.json"))
@click.option("--v4-summary", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v4/summary.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage8_composer_v4_report.md"))
def stage8_report_cmd(v3_summary: Path, v4_summary: Path, output_report: Path) -> None:
    """Generate stage8_composer_v4_report.md comparing v3 and v4 results."""
    from atari_music.stage8_reporter import generate_stage8_report

    click.echo(f"Generating Stage 8 report -> {output_report}...")
    generate_stage8_report(v3_summary, v4_summary, output_report)
    click.echo("Stage 8 report generated successfully!")


@cli.command("import-json")
@click.argument("composition_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Render and save audio WAV")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Export MADS assembly file")
@click.option("--output-ir", type=click.Path(path_type=Path), default=None, help="Export POKEY IR JSON")
def import_json_cmd(
    composition_json: Path,
    output_wav: Optional[Path],
    output_asm: Optional[Path],
    output_ir: Optional[Path],
) -> None:
    """Validate and import an AI composition JSON document."""
    from atari_music.ai.client import load_composition_json, generate_music_from_composition
    from atari_music.mads_exporter import export_mads_asm

    click.echo(f"Validating and loading composition from {composition_json}...")
    comp = load_composition_json(composition_json)
    click.echo(f"Loaded successfully!")
    click.echo(f"  Title: {comp.metadata.title} (Author: {comp.metadata.author or 'Unknown'})")
    click.echo(f"  Key: {comp.metadata.key} {comp.metadata.mode}, BPM: {comp.metadata.bpm}")
    click.echo(f"  Channels: {comp.hardware.channels}, 16-bit bass: {comp.hardware.use_16bit_bass}")
    click.echo(f"  Patterns: {len(comp.patterns)}, Sequence: {' -> '.join(comp.sequence)}")

    if output_wav or output_asm or output_ir:
        click.echo("Compiling composition through Music IR & POKEY IR...")
        res = generate_music_from_composition(comp)
        if output_ir:
            res.save_json(output_ir)
            click.echo(f"Saved POKEY IR -> {output_ir}")
        if output_wav:
            res.render_wav(output_wav)
            click.echo(f"Rendered WAV -> {output_wav}")
        if output_asm:
            export_mads_asm(res.pokey_ir, output_asm)
            click.echo(f"Exported MADS ASM -> {output_asm}")


@cli.command("build-xex")
@click.argument("composition_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("output.xex"), help="Output Atari XEX binary path")
@click.option("--player-address", type=str, default="0x6000", help="Relocatable player address (hex or dec, e.g. 0x6000)")
@click.option("--music-address", type=str, default="0x8000", help="Relocatable music data address (hex or dec, e.g. 0x8000)")
@click.option("--zp-base", type=str, default="0x80", help="Zero-page base address (hex or dec, e.g. 0x80)")
@click.option("--mads", type=click.Path(path_type=Path), default=Path("tools/mads/mads.exe"), help="Path to mads.exe")
def build_xex_cmd(
    composition_json: Path,
    output: Path,
    player_address: str,
    music_address: str,
    zp_base: str,
    mads: Path,
) -> None:
    """Compile AI composition JSON directly to relocatable Atari XEX binary using MADS."""
    from atari_music.ai.client import build_xex_from_composition

    def parse_addr(val: str) -> int:
        s = val.strip()
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s)

    p_addr = parse_addr(player_address)
    m_addr = parse_addr(music_address)
    z_addr = parse_addr(zp_base)

    click.echo(f"Building Atari XEX from {composition_json}...")
    click.echo(f"  Configuration: player=${p_addr:04X}, music=${m_addr:04X}, ZP=${z_addr:02X}")
    xex_path = build_xex_from_composition(
        composition_json,
        output_xex=output,
        player_address=p_addr,
        music_address=m_addr,
        zp_base=z_addr,
        mads_exe=mads,
    )
    size = xex_path.stat().st_size
    click.echo(f"Successfully compiled XEX -> {xex_path} ({size} bytes)")


@cli.command("ai-compose")
@click.option("--style", type=str, default="dark dungeon exploration", help="Composition style/description")
@click.option("--mood", "-m", multiple=True, help="Mood keywords (can be specified multiple times)")
@click.option("--duration", type=float, default=25.0, help="Target duration in seconds")
@click.option("--bpm", type=int, default=120, help="Target BPM")
@click.option("--channels", type=int, default=4, help="POKEY channels (1..4)")
@click.option("--use-16bit-bass/--no-16bit-bass", default=False, help="Enable 16-bit bass mode")
@click.option("--structure", type=str, default="A-B-A", help="Song structure (e.g. A-B-A)")
@click.option("--provider", type=click.Choice(["mock", "openai"], case_sensitive=False), default="mock", help="AI provider")
@click.option("--model", type=str, default=None, help="AI model name override")
@click.option("--max-retries", type=int, default=3, help="Maximum validation repair retry attempts (default: 3)")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default=None,
    is_eager=True,
    expose_value=False,
    callback=_set_log_level,
    help="Logging level override (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    required=False,
    help="Output JSON path (omitted or '-' prints machine-readable JSON to stdout)",
)
def ai_compose_cmd(
    style: str,
    mood: tuple[str, ...],
    duration: float,
    bpm: int,
    channels: int,
    use_16bit_bass: bool,
    structure: str,
    provider: str,
    model: Optional[str],
    max_retries: int,
    output: Optional[Path],
) -> None:
    """Generate a valid AI composition JSON using an AI provider."""
    from atari_music.ai.providers.base import CompositionRequest
    from atari_music.ai.client import request_ai_composition

    req = CompositionRequest(
        style=style,
        mood=list(mood) if mood else ["mysterious", "tense"],
        duration_seconds=duration,
        bpm=bpm,
        channels=channels,
        use_16bit_bass=use_16bit_bass,
        structure=structure,
    )
    is_stdout = output is None or str(output) == "-"

    # Informational logs go to stderr so stdout is not polluted
    click.echo(f"Requesting composition from provider '{provider}'...", err=True)
    click.echo(
        f"  Style: {style}, BPM: {bpm}, Channels: {channels}, 16-bit bass: {use_16bit_bass}, max retries: {max_retries}",
        err=True,
    )
    comp = request_ai_composition(req, provider_name=provider, model=model, max_retries=max_retries)
    json_str = json.dumps(comp.model_dump(mode="json"), indent=2)

    if is_stdout:
        click.echo(json_str)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(json_str)
        click.echo(f"Successfully generated and validated composition -> {output}", err=True)
        click.echo(f"  Title: {comp.metadata.title}", err=True)


if __name__ == "__main__":
    cli()







