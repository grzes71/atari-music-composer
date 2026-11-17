"""Automated musical critique and revision feedback for Phase 5 (`--quality-passes`).

Evaluates a validated ``AICompositionDoc`` using deterministic metrics from
``analysis.py`` and ``structure_analysis.py`` and produces musical (not schema)
revision guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from atari_music.ai.analysis import analyze_composition
from atari_music.ai.schema import AICompositionDoc
from atari_music.ai.structure_analysis import analyze_composition_structure

# Configurable heuristic thresholds
MIN_PITCH_RANGE_SEMITONES = 7
MIN_PITCH_CLASSES = 4
MAX_SINGLE_DURATION_SHARE = 0.80
MIN_CONSONANCE_RATIO = 0.50
MAX_REPETITION_RATIO = 0.75
MIN_ACTIVE_CHANNELS = 2


@dataclass
class MusicalCritique:
    """Result of evaluating the musical richness of a validated composition."""

    score: float
    findings: List[str] = field(default_factory=list)
    metrics_summary: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_doc(cls, doc: AICompositionDoc) -> "MusicalCritique":
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
        final_score = round(max(0.0, min(100.0, (score - 15.0) + richness_score)), 2)

        summary = {
            "pitch_range_semitones": pitch_range,
            "pitch_classes_count": pc_count,
            "max_duration_share": round(max_dur_share, 3),
            "distinct_volumes": len(vol_dist),
            "consonance_ratio": round(report.harmony.consonance_ratio, 3),
            "active_channels": active_chs,
            "overall_diversity": round(overall_div, 3),
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
