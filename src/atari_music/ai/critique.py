"""Automated musical critique and revision feedback for Phase 5 (`--quality-passes`).

Evaluates a validated ``AICompositionDoc`` using deterministic metrics from
``analysis.py`` and ``structure_analysis.py`` and produces musical (not schema)
revision guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from atari_music.ai.analysis import CompositionAnalysisReport, analyze_composition, calculate_bpm_frames_per_tick
from atari_music.ai.prompt_library import (
    DENSITY_PROFILES,
    effective_bpm,
    normalize_rhythmic_density,
    recommended_steps_per_beat,
    short_step_threshold,
)
from atari_music.ai.schema import AICompositionDoc
from atari_music.ai.structure_analysis import analyze_composition_structure

# Configurable heuristic thresholds
MIN_PITCH_RANGE_SEMITONES = 7
MIN_PITCH_CLASSES = 4
MAX_SINGLE_DURATION_SHARE = 0.80
MIN_CONSONANCE_RATIO = 0.50
MAX_REPETITION_RATIO = 0.75
MIN_ACTIVE_CHANNELS = 2


def _evaluate_rhythmic_density(
    doc: AICompositionDoc,
    report: CompositionAnalysisReport,
    rhythmic_density: Optional[str],
) -> Tuple[float, List[str], Dict[str, Any]]:
    """Compute opt-in rhythmic-density penalty and numeric findings without penalizing regular pulse."""
    norm = normalize_rhythmic_density(rhythmic_density)
    if norm is None or norm == "low":
        return 0.0, [], {"density_penalty": 0.0}

    prof = DENSITY_PROFILES[norm]
    bpm = doc.metadata.bpm
    fpt = calculate_bpm_frames_per_tick(bpm)
    step_s = fpt / 50.0
    spb = recommended_steps_per_beat(bpm)
    eff = effective_bpm(bpm, spb)
    short_thr = short_step_threshold(spb)

    lead = report.rhythm.role_rhythm.get("lead")
    lead_ch = f"CH{report.rhythm.lead_channel}" if report.rhythm.lead_channel else "lead"

    if lead is None or lead.notes_count < 2:
        missing_pen = {"medium": 15.0, "high": 25.0, "extreme": 30.0}[norm]
        count = lead.notes_count if lead is not None else 0
        finding = (
            f"Active lead melody missing for rhythmic-density='{norm}' (found {count} lead note(s)). "
            f"Add a dedicated lead/melody line with short <= {short_thr}-step figures entering early."
        )
        return missing_pen, [finding], {"density_penalty": round(missing_pen, 2), "lead_notes_count": count}

    penalty = 0.0
    findings: List[str] = []

    assert prof.max_avg_note_beats is not None
    assert prof.max_median_note_beats is not None
    assert prof.min_notes_per_beat is not None
    assert prof.max_intro_delay_beats is not None
    assert prof.max_longest_silence_beats is not None

    max_avg_steps = max(1.0, prof.max_avg_note_beats * spb)
    max_med_steps = max(1.0, prof.max_median_note_beats * spb)
    if lead.avg_note_steps > max_avg_steps or lead.median_note_steps > max_med_steps:
        excess = max(
            (lead.avg_note_steps / max_avg_steps) - 1.0,
            (lead.median_note_steps / max_med_steps) - 1.0,
            0.0,
        )
        dur_pen = min(12.0, excess * 18.0)
        penalty += dur_pen
        grid_hint = (
            "Use 2-3 step asymmetric groupings (e.g. 2+3 / 2+2+1) instead of 5-7 step holds."
            if spb == 5
            else f"Shorten lead notes toward 1-{short_thr} steps."
        )
        findings.append(
            f"Lead melody ({lead_ch}) notes are too long for rhythmic-density='{norm}' at {bpm} BPM "
            f"({spb} steps/beat, {step_s * 1000:.0f} ms/step): avg={lead.avg_note_steps:.2f} steps "
            f"(target <= {max_avg_steps:.2f}), median={lead.median_note_steps:.1f} (target <= {max_med_steps:.1f}). {grid_hint}"
        )

    target_nps = prof.min_notes_per_beat * (eff / 60.0)
    if lead.notes_per_sec < target_nps and target_nps > 0:
        deficit = (target_nps - lead.notes_per_sec) / target_nps
        nps_pen = min(10.0, deficit * 15.0)
        penalty += nps_pen
        findings.append(
            f"Lead melody ({lead_ch}) density is too low ({lead.notes_per_sec:.2f} notes/s < target "
            f"{target_nps:.2f} notes/s for rhythmic-density='{norm}'); increase melodic phrasing density rather than relying only on accompaniment."
        )

    if lead.short_note_ratio < prof.min_short_note_ratio:
        short_pen = min(8.0, (prof.min_short_note_ratio - lead.short_note_ratio) * 16.0)
        penalty += short_pen
        findings.append(
            f"Too few short lead notes ({lead.short_note_ratio:.0%} <= {short_thr} steps vs target >= {prof.min_short_note_ratio:.0%}); "
            f"incorporate crisp <= {short_thr}-step melodic figures."
        )

    max_intro_steps = max(1.0, prof.max_intro_delay_beats * spb)
    intro_delay_steps = report.rhythm.intro_melody.intro_melody_delay_steps
    if intro_delay_steps is not None and intro_delay_steps > max_intro_steps:
        intro_pen = min(
            10.0,
            3.0 + ((intro_delay_steps - max_intro_steps) / max(1.0, max_intro_steps)) * 5.0,
        )
        penalty += intro_pen
        findings.append(
            f"INTRO melody delay is {intro_delay_steps} steps ({intro_delay_steps * step_s:.2f}s) before lead enters in sequence "
            f"(limit for '{norm}' is <= {int(round(max_intro_steps))} steps / {max_intro_steps * step_s:.2f}s); introduce the lead motif much earlier."
        )

    max_silence_steps = max(1.0, prof.max_longest_silence_beats * spb)
    sil_pen = 0.0
    if lead.longest_silence_steps > max_silence_steps:
        sil_pen += min(2.0, ((lead.longest_silence_steps - max_silence_steps) / max(1.0, max_silence_steps)) * 2.0)
    if lead.rest_ratio > prof.max_rest_ratio:
        denom = max(0.05, 1.0 - prof.max_rest_ratio)
        sil_pen += min(1.0, ((lead.rest_ratio - prof.max_rest_ratio) / denom) * 1.5)
    if sil_pen > 0.0:
        penalty += sil_pen
        findings.append(
            f"Lead melody ({lead_ch}) has excessive silence (longest gap={lead.longest_silence_steps} steps vs <= {int(round(max_silence_steps))}, "
            f"rest_ratio={lead.rest_ratio:.0%} vs <= {prof.max_rest_ratio:.0%})."
        )

    extra_summary = {
        "density_penalty": round(penalty, 2),
        "lead_notes_per_sec": round(lead.notes_per_sec, 3),
        "lead_avg_note_steps": round(lead.avg_note_steps, 3),
        "lead_median_note_steps": round(lead.median_note_steps, 3),
        "lead_short_note_ratio": round(lead.short_note_ratio, 3),
        "intro_melody_delay_steps": intro_delay_steps,
    }
    return penalty, findings, extra_summary


@dataclass
class MusicalCritique:
    """Result of evaluating the musical richness of a validated composition."""

    score: float
    findings: List[str] = field(default_factory=list)
    metrics_summary: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_doc(
        cls,
        doc: AICompositionDoc,
        *,
        rhythmic_density: Optional[str] = None,
    ) -> "MusicalCritique":
        """Compute musical quality score (0..100) and actionable composer findings."""
        report = analyze_composition(doc)
        struct = analyze_composition_structure(doc)

        findings: List[str] = []
        score = 100.0

        # 1. Melodic pitch range
        pitch_range = report.melody.pitch_range_semitones
        if pitch_range < MIN_PITCH_RANGE_SEMITONES:
            penalty = min(20.0, float(MIN_PITCH_RANGE_SEMITONES - pitch_range) * 2.5)
            score -= penalty
            findings.append(
                f"Melodic range is narrow ({pitch_range} semitones < {MIN_PITCH_RANGE_SEMITONES}). "
                "Widen the lead contour across at least a fifth or octave with a clear climax note."
            )

        # 2. Pitch class diversity
        pc_count = report.melody.pitch_classes_count
        if pc_count < MIN_PITCH_CLASSES:
            penalty = min(15.0, float(MIN_PITCH_CLASSES - pc_count) * 5.0)
            score -= penalty
            findings.append(
                f"Only {pc_count} distinct pitch classes used. "
                "Introduce scale degrees, chord arpeggios, or passing/neighbour tones."
            )

        # 3. Rhythmic duration variety
        dist = report.rhythm.note_length_distribution
        total_notes = max(1, report.rhythm.total_notes)
        max_dur_share = max((cnt / total_notes for cnt in dist.values()), default=1.0)
        if max_dur_share > MAX_SINGLE_DURATION_SHARE and total_notes >= 6:
            penalty = min(20.0, (max_dur_share - MAX_SINGLE_DURATION_SHARE) * 80.0)
            score -= penalty
            findings.append(
                f"Rhythm is monotonous ({max_dur_share:.0%} of notes share a single duration). "
                "Combine longer phrase endings, short passing notes, syncopations, or fast 1-2 step arpeggios."
            )

        # 4. Dynamic contrast (volume levels)
        vol_dist = report.pokey.volume_distribution
        if len(vol_dist) <= 1 and total_notes >= 6:
            score -= 10.0
            findings.append(
                "Flat dynamics (only a single volume level is used). "
                "Add volume accents on downbeats and melodic peaks, and use softer levels for arpeggios/echoes."
            )

        # 5. Harmonic consonance between simultaneous voices
        if report.harmony.sounding_chords_count > 0 and report.harmony.consonance_ratio < MIN_CONSONANCE_RATIO:
            penalty = min(15.0, (MIN_CONSONANCE_RATIO - report.harmony.consonance_ratio) * 40.0)
            score -= penalty
            findings.append(
                f"Low harmonic consonance ({report.harmony.consonance_ratio:.0%}). "
                "Align bass roots/fifths with lead chord tones on strong beats."
            )

        # 6. Multi-channel orchestration
        active_chs = sum(
            1
            for ch_info in report.rhythm.channel_activity.values()
            if ch_info.get("notes_count", ch_info.get("note_count", 0)) > 0
        )
        if active_chs < MIN_ACTIVE_CHANNELS and doc.hardware.channels >= 2:
            score -= 15.0
            findings.append(
                f"Only {active_chs} active channel(s). "
                "Add a bassline, chord arpeggio/echo voice, or percussion groove on the remaining channels."
            )

        # 7. Structural variety across patterns
        overall_div = (struct.melodic_diversity + struct.rhythmic_diversity + struct.harmonic_diversity) / 3.0
        if (
            report.structure.sequence_pattern_count >= 4
            and report.structure.pattern_count == 1
        ) or (
            report.structure.pattern_count >= 2
            and overall_div < 0.15
            and report.structure.repetition_ratio > MAX_REPETITION_RATIO
        ):
            score -= 15.0
            findings.append(
                "Low structural contrast across sections. "
                "Add a contrasting B section or thematic variation with a shifted harmony, register, or drum fill."
            )

        # 8. Richness calibration (0..15 pts from pitch classes, duration variety, and domain diversity)
        richness_score = (
            min(5.0, max(0, pc_count - 3) * 1.0)
            + min(5.0, max(0, len(dist) - 1) * 1.6)
            + min(5.0, overall_div * 5.0)
        )
        density_penalty, density_findings, density_summary = _evaluate_rhythmic_density(
            doc, report, rhythmic_density
        )
        score -= density_penalty
        findings.extend(density_findings)

        final_score = round(max(0.0, min(100.0, (score - 15.0) + richness_score)), 2)

        summary = {
            "pitch_range_semitones": pitch_range,
            "pitch_classes_count": pc_count,
            "max_duration_share": round(max_dur_share, 3),
            "distinct_volumes": len(vol_dist),
            "consonance_ratio": round(report.harmony.consonance_ratio, 3),
            "active_channels": active_chs,
            "overall_diversity": round(overall_div, 3),
            **density_summary,
        }
        return cls(score=final_score, findings=findings, metrics_summary=summary)

    def format_revision_feedback(self) -> str:
        """Format musical critique into a composer-facing revision prompt."""
        lines = [
            "Your composition passed technical validation. Now refine its MUSICALITY while keeping all hardware and schema rules intact:",
            f"Current musical quality score: {self.score:.1f}/100.0",
            "",
            "Musical improvements to make in this revision:",
        ]
        if self.findings:
            for idx, item in enumerate(self.findings, 1):
                lines.append(f"{idx}. {item}")
        else:
            lines.append(
                "1. Develop the primary motif further in the B section, refine voice leading between bass and lead, "
                "and add a subtle turnaround fill at the end of the phrase."
            )
        lines.extend([
            "",
            "REVISION RULES:",
            "- Keep all POKEY constraints strictly valid (monophonic channels, 16-bit bass CH2 empty if enabled, valid note names and positive durations).",
            "- Return ONLY the complete revised composition in the exact same format (no commentary or markdown fences).",
        ])
        return "\n".join(lines)
