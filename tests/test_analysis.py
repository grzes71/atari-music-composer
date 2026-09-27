"""Unit and Regression Tests for Musical Analysis and Composition Fingerprinting."""

import copy
import pytest

from atari_music.ai.analysis import (
    CompositionAnalysisReport,
    analyze_composition,
    composition_fingerprint,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)


@pytest.fixture
def base_doc() -> AICompositionDoc:
    """Fixture providing a standard 4-channel composition document."""
    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="Analysis Test Piece",
            bpm=120,
            key="C",
            mode="minor",
        ),
        hardware=AIHardwareConfig(
            channels=4,
            use_16bit_bass=False,
        ),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead Synth", character="bright_lead"),
            AIInstrumentDef(id="bass", name="Bass Synth", character="bass"),
            AIInstrumentDef(id="harm", name="Harmony Pad", character="soft_pad"),
            AIInstrumentDef(id="perc", name="Drums", character="percussion"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [  # Lead
                        AIPatternChannelEvent(step=0, note="C4", instrument="lead", duration=4, volume=14),
                        AIPatternChannelEvent(step=4, note="D4", instrument="lead", duration=4, volume=14),
                        AIPatternChannelEvent(step=8, note="Eb4", instrument="lead", duration=4, volume=14),
                        AIPatternChannelEvent(step=12, note="G4", instrument="lead", duration=4, volume=14),
                    ],
                    "2": [  # Harmony
                        AIPatternChannelEvent(step=0, note="G3", instrument="harm", duration=8, volume=10),
                        AIPatternChannelEvent(step=8, note="Bb3", instrument="harm", duration=8, volume=10),
                    ],
                    "3": [  # Bass
                        AIPatternChannelEvent(step=0, note="C2", instrument="bass", duration=8, volume=12),
                        AIPatternChannelEvent(step=8, note="C2", instrument="bass", duration=8, volume=12),
                    ],
                    "4": [  # Percussion
                        AIPatternChannelEvent(step=0, note="C4", instrument="perc", duration=2, volume=15),
                        AIPatternChannelEvent(step=4, note="C4", instrument="perc", duration=2, volume=12),
                        AIPatternChannelEvent(step=8, note="C4", instrument="perc", duration=2, volume=15),
                        AIPatternChannelEvent(step=12, note="C4", instrument="perc", duration=2, volume=12),
                    ],
                },
            ),
            AIPatternDef(
                id="B",
                length_steps=16,
                channels={
                    "1": [
                        AIPatternChannelEvent(step=0, note="G4", instrument="lead", duration=8, volume=14),
                        AIPatternChannelEvent(step=8, note="F4", instrument="lead", duration=8, volume=14),
                    ],
                    "2": [],
                    "3": [
                        AIPatternChannelEvent(step=0, note="Ab2", instrument="bass", duration=16, volume=12),
                    ],
                    "4": [],
                },
            ),
        ],
        sequence=["A", "B", "A"],
        loop_point=0,
    )


def test_fingerprint_identical_composition(base_doc: AICompositionDoc):
    """Two identical compositions must produce the exact same fingerprint."""
    fp1 = composition_fingerprint(base_doc)
    doc_copy = copy.deepcopy(base_doc)
    fp2 = composition_fingerprint(doc_copy)
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex digest


def test_fingerprint_changes_after_note_change(base_doc: AICompositionDoc):
    """Changing a single pitch must change the fingerprint."""
    fp_orig = composition_fingerprint(base_doc)
    doc_mod = copy.deepcopy(base_doc)
    doc_mod.patterns[0].channels["1"][0].note = "C#4"
    fp_mod = composition_fingerprint(doc_mod)
    assert fp_orig != fp_mod


def test_fingerprint_changes_after_rhythm_change(base_doc: AICompositionDoc):
    """Changing a note duration or step timing must change the fingerprint."""
    fp_orig = composition_fingerprint(base_doc)
    doc_mod = copy.deepcopy(base_doc)
    doc_mod.patterns[0].channels["1"][0].duration = 2
    fp_mod = composition_fingerprint(doc_mod)
    assert fp_orig != fp_mod


def test_fingerprint_changes_after_instrument_change(base_doc: AICompositionDoc):
    """Changing an instrument character or timbre parameters must change the fingerprint."""
    fp_orig = composition_fingerprint(base_doc)
    doc_mod = copy.deepcopy(base_doc)
    doc_mod.instruments[0].character = "dark_pad"
    fp_mod = composition_fingerprint(doc_mod)
    assert fp_orig != fp_mod


def test_empty_composition():
    """Empty composition with no notes must be analyzed without errors."""
    empty_doc = AICompositionDoc(
        metadata=AICompositionMetadata(title="Empty Piece", bpm=100),
        hardware=AIHardwareConfig(channels=4),
        instruments=[],
        patterns=[],
        sequence=[],
        loop_point=0,
    )
    fp = composition_fingerprint(empty_doc)
    assert isinstance(fp, str) and len(fp) == 64

    report = analyze_composition(empty_doc)
    assert isinstance(report, CompositionAnalysisReport)
    assert report.rhythm.total_notes == 0
    assert report.rhythm.total_active_steps == 0
    assert report.melody.min_pitch is None
    assert report.harmony.sounding_chords_count == 0
    assert report.structure.pattern_count == 0
    assert report.structure.duration_seconds == 0.0


def test_one_note_composition():
    """Composition containing exactly one note must be analyzed correctly."""
    one_note_doc = AICompositionDoc(
        metadata=AICompositionMetadata(title="One Note", bpm=120),
        hardware=AIHardwareConfig(channels=4),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [
                        AIPatternChannelEvent(step=0, note="A4", instrument="lead", duration=4, volume=15),
                    ],
                },
            ),
        ],
        sequence=["A"],
        loop_point=0,
    )
    report = analyze_composition(one_note_doc)
    assert report.rhythm.total_notes == 1
    assert report.rhythm.avg_note_length == 4.0
    assert report.melody.min_pitch == 69  # A4 = 69
    assert report.melody.max_pitch == 69
    assert report.melody.pitch_range_semitones == 0
    assert report.melody.unique_pitches_count == 1
    assert report.melody.semitone_steps_count == 0
    assert report.melody.larger_leaps_count == 0
    assert report.melody.stepwise_vs_leap_ratio == 0.0
    assert report.harmony.sounding_chords_count == 0


def test_multi_channel_composition_analysis(base_doc: AICompositionDoc):
    """Multi-channel piece produces rich rhythmic, melodic, harmonic and pokey metrics."""
    report = analyze_composition(base_doc)
    assert report.rhythm.total_notes > 0
    assert report.structure.pattern_count == 2
    assert report.structure.sequence_pattern_count == 3
    assert report.structure.sequence_length == 48  # A(16) + B(16) + A(16)
    assert report.structure.duration_seconds > 0.0

    # Harmony
    assert report.harmony.sounding_chords_count > 0
    assert report.harmony.consonance_ratio >= 0.0

    # Melody
    assert report.melody.unique_pitches_count >= 4
    assert report.melody.pitch_range_semitones > 0


def test_16bit_bass_analysis():
    """16-bit bass mode coupling and AUDF calculations are verified."""
    doc_16 = AICompositionDoc(
        metadata=AICompositionMetadata(title="16-bit Bass Piece", bpm=90),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=True),
        instruments=[
            AIInstrumentDef(id="bass", name="Deep Bass", character="bass"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [
                        AIPatternChannelEvent(step=0, note="C2", instrument="bass", duration=8, volume=15),
                        AIPatternChannelEvent(step=8, note="G1", instrument="bass", duration=8, volume=15),
                    ],
                },
            ),
        ],
        sequence=["A"],
        loop_point=0,
    )
    report = analyze_composition(doc_16)
    assert report.pokey.uses_16bit_bass is True
    assert "Valid coupling" in report.pokey.bass_16bit_channel_usage
    assert len(report.pokey.warnings) == 0


def test_16bit_bass_channel_2_conflict_warning():
    """If channel 2 contains events while 16-bit bass is enabled, a warning is raised."""
    doc_16_conflict = AICompositionDoc(
        metadata=AICompositionMetadata(title="16-bit Conflict", bpm=90),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=True),
        instruments=[
            AIInstrumentDef(id="bass", name="Deep Bass", character="bass"),
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [
                        AIPatternChannelEvent(step=0, note="C2", instrument="bass", duration=8, volume=15),
                    ],
                    "2": [
                        AIPatternChannelEvent(step=0, note="E4", instrument="lead", duration=8, volume=12),
                    ],
                },
            ),
        ],
        sequence=["A"],
        loop_point=0,
    )
    report = analyze_composition(doc_16_conflict)
    assert "WARNING" in report.pokey.bass_16bit_channel_usage
    assert any("Channel 2 contains events" in w for w in report.pokey.warnings)


def test_rest_analysis():
    """Rests (both explicit note='REST' and gaps) are correctly accounted for."""
    doc_rests = AICompositionDoc(
        metadata=AICompositionMetadata(title="Rest Piece", bpm=120),
        hardware=AIHardwareConfig(channels=4),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [
                        AIPatternChannelEvent(step=0, note="C4", instrument="lead", duration=4, volume=14),
                        AIPatternChannelEvent(step=4, note="REST", instrument="lead", duration=4, volume=0),
                        AIPatternChannelEvent(step=8, note="D4", instrument="lead", duration=4, volume=14),
                        # step 12..15 gap (implicit rest)
                    ],
                },
            ),
        ],
        sequence=["A"],
        loop_point=0,
    )
    report = analyze_composition(doc_rests)
    assert report.rhythm.total_notes == 2
    assert report.rhythm.total_active_steps == 8
    assert report.rhythm.rest_ratio == 0.5  # 8 active steps out of 16


def test_repeated_patterns_repetition_metrics():
    """Pattern repetitions in sequence accurately calculate repetition ratio."""
    doc_repeat = AICompositionDoc(
        metadata=AICompositionMetadata(title="Repeats", bpm=120),
        hardware=AIHardwareConfig(channels=4),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [AIPatternChannelEvent(step=0, note="C4", instrument="lead", duration=8, volume=14)],
                },
            ),
            AIPatternDef(
                id="B",
                length_steps=16,
                channels={
                    "1": [AIPatternChannelEvent(step=0, note="G4", instrument="lead", duration=8, volume=14)],
                },
            ),
        ],
        sequence=["A", "B", "A", "B"],  # 4 total, 2 unique -> repetition ratio = 1 - 2/4 = 0.5
        loop_point=0,
    )
    report = analyze_composition(doc_repeat)
    assert report.structure.sequence_pattern_count == 4
    assert report.structure.pattern_repetition_count == 2
    assert report.structure.repetition_ratio == 0.5
