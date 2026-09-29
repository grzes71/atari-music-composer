"""Mock AI Composition Provider for offline testing, CI/CD, and evaluation."""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from atari_music.ai.providers.base import AICompositionProvider, CompositionRequest

logger = logging.getLogger(__name__)



class MockAICompositionProvider(AICompositionProvider):
    """Generates valid, deterministic AI composition JSON documents without external APIs.
    
    Supports deterministic multi-attempt scenarios for testing the validation repair loop:
      - None / "immediate_success": Valid composition on first try (1 attempt, 0 retries).
      - "invalid_then_valid": Attempt 1 has NOTE_OVERLAP, attempt 2 has valid repaired events.
      - "always_invalid": Always returns composition with validation error (NOTE_OVERLAP).
      - "changing_errors": Attempt 1 (NOTE_OVERLAP) -> Attempt 2 (INVALID_NOTE) -> Attempt 3 (valid).
      - custom `sequence=[doc1, doc2, ...]`: Deterministically returns successive documents.
    """

    def __init__(
        self,
        scenario: Optional[str] = None,
        sequence: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.scenario = scenario
        self.sequence = sequence
        self.call_count: int = 0
        self.received_feedbacks: List[Optional[str]] = []
        self.received_previous_compositions: List[Optional[Dict[str, Any]]] = []
        self.last_usage: Optional[Dict[str, int]] = None
        self.usage_history: list[Dict[str, int]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate_composition(
        self,
        request: CompositionRequest,
        feedback: Optional[str] = None,
        previous_composition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.call_count += 1
        self.received_feedbacks.append(feedback)
        self.received_previous_compositions.append(previous_composition)
        logger.debug(
            "MockAICompositionProvider: generate_composition call #%d (scenario=%s, feedback=%s)",
            self.call_count,
            self.scenario,
            bool(feedback),
        )

        if self.sequence is not None and len(self.sequence) > 0:
            import copy
            idx = min(self.call_count - 1, len(self.sequence) - 1)
            return copy.deepcopy(self.sequence[idx])

        if self.scenario == "invalid_then_valid":
            doc = self._generate_base_valid(request)
            if self.call_count == 1:
                # Attempt 1: C4 step 0 duration 8, E4 step 4 duration 4 -> NOTE_OVERLAP
                doc["patterns"][0]["channels"]["0"] = [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 8, "volume": 14},
                    {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
                ]
            else:
                # Attempt 2+: Repaired C4 step 0 duration 4, E4 step 4 duration 4 -> valid
                doc["patterns"][0]["channels"]["0"] = [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
                    {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
                ]
            return doc

        elif self.scenario == "always_invalid":
            doc = self._generate_base_valid(request)
            doc["patterns"][0]["channels"]["0"] = [
                {"step": 0, "note": "C4", "instrument": "lead", "duration": 8, "volume": 14},
                {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
            ]
            return doc

        elif self.scenario == "changing_errors":
            doc = self._generate_base_valid(request)
            if self.call_count == 1:
                # Attempt 1: NOTE_OVERLAP
                doc["patterns"][0]["channels"]["0"] = [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 8, "volume": 14},
                    {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
                ]
            elif self.call_count == 2:
                # Attempt 2: Overlap fixed, but invalid pitch name -> INVALID_NOTE
                doc["patterns"][0]["channels"]["0"] = [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
                    {"step": 4, "note": "H4", "instrument": "lead", "duration": 4, "volume": 14},
                ]
            else:
                # Attempt 3: Valid
                doc["patterns"][0]["channels"]["0"] = [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
                    {"step": 4, "note": "E4", "instrument": "lead", "duration": 4, "volume": 14},
                ]
            return doc

        return self._generate_base_valid(request)

    def generate_composition_dsl(
        self,
        request: CompositionRequest,
        feedback: Optional[str] = None,
        previous_dsl: Optional[str] = None,
    ) -> str:
        """Generate deterministic Music DSL string for testing."""
        self.call_count += 1
        self.received_feedbacks.append(feedback)
        self.received_previous_compositions.append({"raw_dsl": previous_dsl} if previous_dsl else None)

        if self.scenario == "dsl_syntax_error_then_valid":
            if self.call_count == 1:
                return 'TITLE "Broken"\nSEQUENCE A\n[PATTERN A]\nCH1 LEAD V14\nC4/0\n'
            return 'TITLE "Fixed"\nKEY C\nMODE MINOR\nBPM 120\nSEQUENCE A\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n'

        if self.scenario == "invalid_then_valid":
            if self.call_count == 1:
                return 'TITLE "Test"\nKEY C\nMODE MINOR\nBPM 120\nSEQUENCE A B\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n'
            return 'TITLE "Test"\nKEY C\nMODE MINOR\nBPM 120\nSEQUENCE A\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n'

        if self.scenario == "always_invalid":
            return 'TITLE "Always Bad"\nSEQUENCE A B\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n'

        from atari_music.ai.schema import AICompositionDoc
        from atari_music.ai.dsl import export_music_dsl
        doc_dict = self._generate_base_valid(request)
        doc = AICompositionDoc.model_validate(doc_dict)
        return export_music_dsl(doc)

    def _generate_base_valid(self, request: CompositionRequest) -> Dict[str, Any]:

        style = (request.style or "action").strip().lower()
        use_16 = request.use_16bit_bass or ("dungeon" in style)
        bpm = request.bpm or (85 if "dungeon" in style else (165 if "action" in style else 120))
        key = request.key or ("A" if "dungeon" in style else ("G" if "action" in style else "C"))
        mode = request.mode or ("dorian" if "dungeon" in style else ("dorian" if "action" in style else "minor"))

        title = f"AI {style.capitalize()} Journey"

        if "dungeon" in style or use_16:
            # 16-bit bass piece
            instruments = [
                {"id": "lead", "name": "Mystic Flute", "character": "dark_lead"},
                {"id": "bass", "name": "16-Bit Deep Drone", "character": "bass"},
                {"id": "pad", "name": "Echo Harmony", "character": "soft_pad"},
                {"id": "bells", "name": "Cavern Drops", "character": "bell"},
            ]
            pat_a = {
                "id": "A",
                "length_steps": 16,
                "channels": {
                    "0": [  # Channel 0: Bass
                        {"step": 0, "note": "A1", "instrument": "bass", "duration": 8, "volume": 14},
                        {"step": 8, "note": "A1", "instrument": "bass", "duration": 8, "volume": 14},
                    ],
                    "1": [],  # Channel 1: Hardware slave for 16-bit bass
                    "2": [  # Channel 2: Lead
                        {"step": 0, "note": "A3", "instrument": "lead", "duration": 4, "volume": 13},
                        {"step": 4, "note": "C4", "instrument": "lead", "duration": 4, "volume": 13},
                        {"step": 8, "note": "D4", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 12, "note": "C4", "instrument": "lead", "duration": 4, "volume": 12},
                    ],
                    "3": [  # Channel 3: Bells / Ornament
                        {"step": 2, "note": "E4", "instrument": "bells", "duration": 2, "volume": 10},
                        {"step": 10, "note": "G4", "instrument": "bells", "duration": 2, "volume": 10},
                    ],
                },
            }
            pat_b = {
                "id": "B",
                "length_steps": 16,
                "channels": {
                    "0": [
                        {"step": 0, "note": "F1", "instrument": "bass", "duration": 8, "volume": 14},
                        {"step": 8, "note": "G1", "instrument": "bass", "duration": 8, "volume": 14},
                    ],
                    "1": [],
                    "2": [
                        {"step": 0, "note": "F3", "instrument": "lead", "duration": 4, "volume": 13},
                        {"step": 4, "note": "A3", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 8, "note": "G3", "instrument": "lead", "duration": 4, "volume": 13},
                        {"step": 12, "note": "E3", "instrument": "lead", "duration": 4, "volume": 12},
                    ],
                    "3": [
                        {"step": 4, "note": "C4", "instrument": "bells", "duration": 2, "volume": 11},
                        {"step": 12, "note": "B3", "instrument": "bells", "duration": 2, "volume": 11},
                    ],
                },
            }
            sequence = ["A", "A", "B", "A"]

        elif "funny" in style:
            # Quirky syncopated piece
            instruments = [
                {"id": "lead", "name": "Bouncy Lead", "character": "bright_lead"},
                {"id": "bass", "name": "Staccato Bass", "character": "bass"},
                {"id": "counter", "name": "Hocket Counter", "character": "counter"},
                {"id": "drums", "name": "Percussion", "character": "percussion"},
            ]
            pat_a = {
                "id": "A",
                "length_steps": 16,
                "channels": {
                    "0": [
                        {"step": 0, "note": "F3", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 3, "note": "A3", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 6, "note": "C4", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 10, "note": "D4", "instrument": "lead", "duration": 2, "volume": 15},
                        {"step": 14, "note": "C4", "instrument": "lead", "duration": 2, "volume": 13},
                    ],
                    "1": [
                        {"step": 0, "note": "F2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 4, "note": "C2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 8, "note": "F2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 12, "note": "C2", "instrument": "bass", "duration": 2, "volume": 12},
                    ],
                    "2": [
                        {"step": 2, "note": "A3", "instrument": "counter", "duration": 2, "volume": 10},
                        {"step": 8, "note": "G3", "instrument": "counter", "duration": 2, "volume": 10},
                    ],
                    "3": [
                        {"step": 0, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 4, "note": "C4", "instrument": "drums", "duration": 1, "volume": 12},
                        {"step": 8, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 12, "note": "C4", "instrument": "drums", "duration": 1, "volume": 12},
                    ],
                },
            }
            pat_b = {
                "id": "B",
                "length_steps": 16,
                "channels": {
                    "0": [
                        {"step": 0, "note": "Bb3", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 4, "note": "D4", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 8, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
                    ],
                    "1": [
                        {"step": 0, "note": "Bb1", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 4, "note": "F2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 8, "note": "C2", "instrument": "bass", "duration": 4, "volume": 12},
                    ],
                    "2": [],
                    "3": [
                        {"step": 0, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 8, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                    ],
                },
            }
            sequence = ["A", "B", "A"]

        else:
            # Action / Driving style (Default)
            instruments = [
                {"id": "lead", "name": "Pulse Lead", "character": "bright_lead"},
                {"id": "bass", "name": "Driving Bass", "character": "bass"},
                {"id": "counter", "name": "Octave Arp", "character": "counter"},
                {"id": "drums", "name": "Combat Drums", "character": "percussion"},
            ]
            pat_a = {
                "id": "A",
                "length_steps": 16,
                "channels": {
                    "0": [
                        {"step": 0, "note": "G3", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 2, "note": "Bb3", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 4, "note": "C4", "instrument": "lead", "duration": 2, "volume": 14},
                        {"step": 6, "note": "D4", "instrument": "lead", "duration": 4, "volume": 15},
                        {"step": 12, "note": "C4", "instrument": "lead", "duration": 2, "volume": 13},
                        {"step": 14, "note": "Bb3", "instrument": "lead", "duration": 2, "volume": 13},
                    ],
                    "1": [
                        {"step": 0, "note": "G2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 2, "note": "G2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 4, "note": "G2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 6, "note": "G2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 8, "note": "G2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 10, "note": "G2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 12, "note": "F2", "instrument": "bass", "duration": 2, "volume": 12},
                        {"step": 14, "note": "F2", "instrument": "bass", "duration": 2, "volume": 12},
                    ],
                    "2": [
                        {"step": 4, "note": "D4", "instrument": "counter", "duration": 2, "volume": 10},
                        {"step": 10, "note": "G4", "instrument": "counter", "duration": 2, "volume": 10},
                    ],
                    "3": [
                        {"step": 0, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 2, "note": "C4", "instrument": "drums", "duration": 1, "volume": 9},
                        {"step": 4, "note": "C4", "instrument": "drums", "duration": 1, "volume": 14},
                        {"step": 6, "note": "C4", "instrument": "drums", "duration": 1, "volume": 9},
                        {"step": 8, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 10, "note": "C4", "instrument": "drums", "duration": 1, "volume": 9},
                        {"step": 12, "note": "C4", "instrument": "drums", "duration": 1, "volume": 14},
                        {"step": 14, "note": "C4", "instrument": "drums", "duration": 1, "volume": 9},
                    ],
                },
            }
            pat_b = {
                "id": "B",
                "length_steps": 16,
                "channels": {
                    "0": [
                        {"step": 0, "note": "Eb4", "instrument": "lead", "duration": 4, "volume": 15},
                        {"step": 4, "note": "D4", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 8, "note": "C4", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 12, "note": "D4", "instrument": "lead", "duration": 4, "volume": 15},
                    ],
                    "1": [
                        {"step": 0, "note": "Eb2", "instrument": "bass", "duration": 4, "volume": 13},
                        {"step": 4, "note": "D2", "instrument": "bass", "duration": 4, "volume": 13},
                        {"step": 8, "note": "C2", "instrument": "bass", "duration": 4, "volume": 13},
                        {"step": 12, "note": "D2", "instrument": "bass", "duration": 4, "volume": 13},
                    ],
                    "2": [
                        {"step": 2, "note": "G4", "instrument": "counter", "duration": 2, "volume": 11},
                        {"step": 6, "note": "F4", "instrument": "counter", "duration": 2, "volume": 11},
                        {"step": 10, "note": "Eb4", "instrument": "counter", "duration": 2, "volume": 11},
                        {"step": 14, "note": "F4", "instrument": "counter", "duration": 2, "volume": 11},
                    ],
                    "3": [
                        {"step": 0, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 4, "note": "C4", "instrument": "drums", "duration": 1, "volume": 14},
                        {"step": 8, "note": "C4", "instrument": "drums", "duration": 1, "volume": 15},
                        {"step": 12, "note": "C4", "instrument": "drums", "duration": 1, "volume": 14},
                    ],
                },
            }
            sequence = ["A", "A", "B", "A"]

        req_ch = request.channels or 4
        if req_ch < 4:
            for pat in (pat_a, pat_b):
                pat["channels"] = {
                    k: v for k, v in pat["channels"].items()
                    if int(k) < req_ch
                }

        return {
            "format": "atari-music-composition",
            "version": 1,
            "metadata": {
                "title": title,
                "author": "Mock AI Composer",
                "description": f"Procedurally composed {style} piece for Atari 8-bit POKEY",
                "key": key,
                "mode": mode,
                "bpm": bpm,
                "duration_seconds": float(request.duration_seconds or 24),
            },
            "hardware": {
                "channels": request.channels or 4,
                "use_16bit_bass": use_16,
            },
            "instruments": instruments,
            "patterns": [pat_a, pat_b],
            "sequence": sequence,
            "loop_point": 0,
            "intent": {
                "style": style,
                "mood": request.mood or [style],
                "structure": "A-B-A",
                "composition_notes": request.notes or f"Generated {style} motif with multi-channel counterpoint.",
            },
            "provenance": {
                "source": "ai",
                "provider": "mock",
                "model": "mock-composer-v1",
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "request_id": f"mock-{abs(hash(style)) % 10000:04d}",
            },
        }
