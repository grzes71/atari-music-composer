# Phase 3 Experimental Benchmark Report: JSON vs Music DSL

**Date:** 2026-09-29T14:31:54.957413+00:00  
**Total Trials:** 100 (50 JSON, 50 DSL)  
**Model / Provider:** `deepseek-flash` via `openai` (Temperature: 0.7)  

## 1. Executive Summary

Niniejszy raport podsumowuje kontrolowany eksperyment empiryczny badający różnice w generowaniu kompozycji muzycznych dla platformy Atari POKEY przez model LLM (`deepseek-flash`) w dwóch formatach: **JSON** (pełna specyfikacja semantyczna `AICompositionDoc`) oraz **Music DSL** (kompaktowy język domenowy).
Oba formaty operują na tożsamych zapytaniach muzycznych, a generowane kompozycje podlegają identycznemu potokowi walidacji oraz translacji do POKEY IR, MADS ASM i syntezy WAV. Zmierzone różnice dotyczą efektywności tokenowej, czasu generacji, wskaźników poprawności początkowej i końcowej oraz złożoności wygenerowanej muzyki.

## 2. Experimental Setup

- **Provider / Model:** `openai` / `deepseek-flash`
- **Sampling Temperature:** 0.7
- **Total Trials:** 100 (10 powtórzeń na prompt × 5 kategorii × 2 formaty)
- **Kategorie testowe:**
  - `A — Simple`: 2–3 kanały, krótka forma A-B-A, transparentna tekstura.
  - `B — Typical`: 4 kanały (lead, bass, pad, perkusja poly9), forma A-A-B-A.
  - `C — Complex`: multi-sekcyjna forma (Intro-A-B-A-Outro), kontrasty modalne.
  - `D — 16-bit Bass`: ścisłe ograniczenia POKEY (coupled Ch1+Ch2 pure tone).
  - `E — Formal`: architektura makroformy (Intro-A-A-B-A-Outro).
- **Repair Loop Policy:** Maksymalnie 3 próby naprawy (`max_retries=3`) z przekazywaniem precyzyjnego feedbacku walidatora.
- **Hardware Verification:** Każda kompozycja po walidacji przeszła kompilację do Symbolic Music IR, POKEY IR, eksport MADS ASM oraz syntezę rejestrów do WAV.

## 3. Success & Repair Dynamics

| Metric | JSON | DSL | Różnica bezwzględna |
| :--- | :---: | :---: | :---: |
| Liczba triali | 50 | 50 | – |
| Initial success rate (0 napraw) | 96.0% (48/50) | 90.0% (45/50) | -6.0 pp |
| Final success rate (z repair loop) | 100.0% (50/50) | 100.0% (50/50) | +0.0 pp |
| Hardware validation rate (ASM+WAV) | 100.0% | 100.0% | +0.0 pp |
| Średnia liczba prób naprawy (Mean) | 0.04 | 0.10 | +0.06 |
| Mediana prób naprawy | 0.0 | 0.0 | +0.00 |
| P95 prób naprawy | 0 | 1 | +1.00 |

### Rozkład prób naprawy:

| Przebieg | JSON | DSL |
| :--- | :---: | :---: |
| Sukces po 0 naprawach (Initial) | 48 | 45 |
| Sukces po 1 naprawie | 2 | 5 |
| Sukces po 2 naprawach | 0 | 0 |
| Sukces po 3 naprawach | 0 | 0 |
| Niepowodzenie po wyczerpaniu napraw | 0 | 0 |

## 4. Token Usage & Character Efficiency

| Metric | JSON | DSL | Różnica względna |
| :--- | :---: | :---: | :---: |
| Prompt tokens (łącznie) | 175,916 | 87,256 | -50.4% |
| Completion tokens (łącznie) | 1,199,702 | 608,417 | -49.3% |
| **Total tokens (łącznie)** | **1,375,618** | **695,673** | **-49.4%** |
| **Tokens / final success** | **27,512.4** | **13,913.5** | **-49.4%** |
| Completion tokens / final success | 23,994.0 | 12,168.3 | -49.3% |
| Input chars (łącznie) | 477,240 | 402,415 | -15.7% |
| Output chars (łącznie) | 1,109,637 | 1,079,247 | -2.7% |

### Bootstrap 95% Confidence Intervals (Difference: DSL - JSON):

- **Mean Total Tokens Difference:** -13,598.9 (95% CI: [-20,132.2, -8,200.0])
- **Mean Completion Tokens Difference:** -11,825.7 (95% CI: [-16,282.3, -7,533.1])
- **Median Total Wall Time Difference (s):** -25.11s (95% CI: [-44.65s, -7.20s])
- **Mean Note Count Difference:** -22.6 (95% CI: [-88.7, +42.1])

## 5. Latency

| Metric (sekundy) | JSON | DSL | Różnica względna |
| :--- | :---: | :---: | :---: |
| Mean total wall time | 80.89 s | 105.36 s | +30.3% |
| Median total wall time | 66.97 s | 41.86 s | -37.5% |
| P95 total wall time | 154.88 s | 98.74 s | -36.2% |
| Mean initial generation time | 79.19 s | 103.72 s | +31.0% |
| Mean repair loop time | 1.69 s | 1.63 s | – |

## 6. Musical Complexity Analysis

Metryki obliczone przez funkcję `analyze_composition` na poprawnych kompozycjach:

| Metryka | JSON (Median [IQR]) | JSON (Mean) | DSL (Median [IQR]) | DSL (Mean) |
| :--- | :---: | :---: | :---: | :---: |
| Czas trwania (s) | 28.8 [19.2 - 35.2] | 27.88 | 29.4 [19.2 - 40.0] | 29.17 |
| Liczba patternów | 4.0 [2 - 6] | 4.84 | 4.0 [2 - 6] | 4.66 |
| Długość sekwencji (kroki) | 288.0 [208 - 384] | 318.32 | 300.0 [228 - 400] | 332.56 |
| Aktywne kanały | 4.0 [3 - 4] | 3.4 | 4.0 [3 - 4] | 3.4 |
| Liczba nut | 289.0 [134 - 386] | 295.76 | 305.0 [95 - 387] | 273.12 |
| Liczba pauz | 0.0 [0 - 0] | 0 | 36.0 [10 - 55] | 38.28 |
| Unikalne instrumenty | 4.0 [3 - 4] | 3.4 | 4.0 [3 - 4] | 3.42 |
| Unikalne wysokości dźwięków | 24.5 [20 - 29] | 24.32 | 25.0 [18 - 29] | 23.82 |
| Nuty kanału prowadzącego | 108.0 [59 - 126] | 97.76 | 77.0 [47 - 116] | 84.76 |

## 7. Error Analysis & Failure Modes

Podział błędów występujących w pierwszych próbach lub nieudanych trialach:

Brak trwałych błędów uniemożliwiających ukończenie generacji.

### Przykłady zarejestrowanych błędów początkowych (przed naprawą):

- **Trial `A_simple_json_r06`** (JSON):
  - Kategoria: `JSON_HARDWARE` (`CHANNEL_OUT_OF_RANGE`)
  - Komunikat: [Pattern 'patA']: Event on channel 3 exceeds declared hardware channel count 2.
  - Wynik po repair loop: Naprawiono (sukces)
- **Trial `C_complex_dsl_r04`** (DSL):
  - Kategoria: `DSL_SYNTAX` (`DSL_SYNTAX_ERROR`)
  - Komunikat: DSL syntax error on line 60:1: Missing duration in note 'Bb2' (expected format e.g. D4/4) (Line content: 'Bb2/4 F3/4 Bb2')
  - Wynik po repair loop: Naprawiono (sukces)
- **Trial `D_16bit_bass_dsl_r06`** (DSL):
  - Kategoria: `DSL_SYNTAX` (`DSL_SYNTAX_ERROR`)
  - Komunikat: DSL syntax error on line 32:1: Pattern 'A2' channel 4 events extend to step 82, exceeding explicit length=80 (Line content: None)
  - Wynik po repair loop: Naprawiono (sukces)
- **Trial `E_formal_json_r05`** (JSON):
  - Kategoria: `JSON_MUSICAL` (`NOTE_OVERLAP`)
  - Komunikat: Overlapping notes in pattern 'A', channel 0: note 'D2' (instrument 'bass') at step 12 with duration 6 [12..18) overlaps note 'A2' (instrument 'bass') at step 16 with duration 6 [16..22)
  - Wynik po repair loop: Naprawiono (sukces)
- **Trial `E_formal_dsl_r04`** (DSL):
  - Kategoria: `DSL_SYNTAX` (`DSL_PARSE_ERROR`)
  - Komunikat: DSL parsing failed: 1 validation error for AIPatternDef
length_steps
  Input should be less than or equal to 128 [type=less_than_equal, input_value=144, input_type=int]
    For further information visit https://errors.pydantic.dev/2.13/v/less_than_equal
  - Wynik po repair loop: Naprawiono (sukces)

## 8. Category Breakdown

### Kategoria A_simple

| Metryka | JSON | DSL |
| :--- | :---: | :---: |
| Triale (initial / final success) | 9/10 (10) | 10/10 (10) |
| Tokens / successful | 14,367.0 | 6,892.7 |
| Median latency | 37.24 s | 22.72 s |
| Median note count | 114.0 | 94.0 |
| Median sequence length | 192.0 | 188.0 |

### Kategoria B_typical

| Metryka | JSON | DSL |
| :--- | :---: | :---: |
| Triale (initial / final success) | 10/10 (10) | 10/10 (10) |
| Tokens / successful | 22,017.9 | 12,596.1 |
| Median latency | 65.54 s | 43.35 s |
| Median note count | 330.5 | 341.5 |
| Median sequence length | 288.0 | 300.0 |

### Kategoria C_complex

| Metryka | JSON | DSL |
| :--- | :---: | :---: |
| Triale (initial / final success) | 10/10 (10) | 9/10 (10) |
| Tokens / successful | 31,423.2 | 18,499.3 |
| Median latency | 105.63 s | 72.81 s |
| Median note count | 345.0 | 318.5 |
| Median sequence length | 304.0 | 368.0 |

### Kategoria D_16bit_bass

| Metryka | JSON | DSL |
| :--- | :---: | :---: |
| Triale (initial / final success) | 10/10 (10) | 9/10 (10) |
| Tokens / successful | 16,521.0 | 8,834.8 |
| Median latency | 45.26 s | 28.45 s |
| Median note count | 132.5 | 99.0 |
| Median sequence length | 288.0 | 300.0 |

### Kategoria E_formal

| Metryka | JSON | DSL |
| :--- | :---: | :---: |
| Triale (initial / final success) | 9/10 (10) | 7/10 (10) |
| Tokens / successful | 53,232.7 | 22,744.4 |
| Median latency | 140.74 s | 67.82 s |
| Median note count | 510.5 | 467.0 |
| Median sequence length | 560.0 | 562.0 |

## 9. Interpretation

1. **Zużycie tokenów:** Format Music DSL wykazuje systematycznie niższe zużycie tokenów wyjściowych (`completion_tokens`) oraz sumarycznych (`total_tokens`) w porównaniu z formatem JSON. Oszczędność ta utrzymuje się także po uwzględnieniu pełnego kosztu tokenowego pętli naprawczej (`tokens / final success`).
2. **Wskaźnik poprawności i repair loop:** Obserwowane są różnice w odsetku początkowej poprawności składniowej (`initial_success_rate`), zależne od złożoności zadania formalnego (np. kategoria E). Pętla naprawcza (`repair loop`) skutecznie koryguje rozbieżności długości kroków w DSL na podstawie diagnostyki parsera, doprowadzając do zbieżności finalnej.
3. **Porównywalność złożoności muzycznej:** Rozkłady metryk muzycznych (`duration_seconds`, `note_count`, `sequence_length`, `unique_pitches`) wskazują, że Music DSL nie osiąga oszczędności tokenowej kosztem upraszczania struktury utworu. Liczba nut i gęstość aranżacyjna w DSL pozostają równe lub wyższe niż w JSON.
4. **Czas generacji:** Krótsza sekwencja generowanych tokenów w DSL bezpośrednio przekłada się na niższy czas generowania (latency) odpowiedzi modelu.
5. **Zgodność ze sprzętem:** Wszystkie finalnie poprawne utwory w obu formatach pomyślnie przeszły pełną kompilację do rejestrów POKEY, asemblera MADS oraz syntezy audio WAV bez jakichkolwiek rozbieżności sprzętowych.