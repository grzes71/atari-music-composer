"""Unit tests for IR pattern optimizer and migrated musical constants."""

from __future__ import annotations

import pytest

from atari_music import composer_v2, constants, generator, ir_optimizer
from atari_music.ir import IRNote, IRPattern, IRSong

pytestmark = [pytest.mark.core, pytest.mark.audio]


def test_deduplicate_pokey_patterns_merges_and_remaps_sequence() -> None:
    """Verify identical patterns collapse and sequence entries remap consecutively."""
    p0 = IRPattern(id=0, name="P0", rows=16, tracks={0: [IRNote(pitch="C-4", duration=4, volume=12, distortion=10)]})
    p1 = IRPattern(id=1, name="P1", rows=16, tracks={0: [IRNote(pitch="C-4", duration=4, volume=12, distortion=10)]})
    p2 = IRPattern(id=2, name="P2", rows=16, tracks={0: [IRNote(pitch="E-4", duration=4, volume=12, distortion=10)]})

    song = IRSong(
        title="Opt",
        author="Test",
        tempo_bpm=120,
        frames_per_tick=4,
        key="C",
        mode="minor",
        instruments=[],
        patterns=[p0, p1, p2],
        sequence=[0, 1, 2, 0],
    )
    out_song, removed = ir_optimizer.deduplicate_pokey_patterns(song)
    assert removed == 1
    assert [pat.id for pat in out_song.patterns] == [0, 1]
    assert out_song.sequence == [0, 0, 1, 0]


def test_deduplicate_pokey_patterns_unique_patterns_noop() -> None:
    """Verify unique patterns remain untouched with removed_count == 0."""
    p0 = IRPattern(id=0, name="P0", rows=16, tracks={0: [IRNote(pitch="C-4", duration=4, volume=12, distortion=10)]})
    p1 = IRPattern(id=1, name="P1", rows=16, tracks={0: [IRNote(pitch="D-4", duration=4, volume=12, distortion=10)]})
    song = IRSong(
        title="Unique",
        author="Test",
        tempo_bpm=120,
        frames_per_tick=4,
        key="C",
        mode="minor",
        instruments=[],
        patterns=[p0, p1],
        sequence=[0, 1],
    )
    out_song, removed = ir_optimizer.deduplicate_pokey_patterns(song)
    assert removed == 0
    assert len(out_song.patterns) == 2
    assert out_song.sequence == [0, 1]


def test_legacy_reexports_preserve_exact_objects() -> None:
    """Verify backward-compatible re-exports in composer_v2 and generator."""
    assert composer_v2.deduplicate_pokey_patterns is ir_optimizer.deduplicate_pokey_patterns
    assert generator.KEY_BASE_MIDI is constants.KEY_BASE_MIDI
    assert generator.SCALES is constants.SCALES
    assert set(constants.SCALES.keys()) == {"major", "minor", "dorian", "pentatonic"}
    assert constants.KEY_BASE_MIDI["C"] == 60
    assert constants.KEY_BASE_MIDI["B"] == 71
