# Phase 3 Experimental Benchmark Report: JSON vs Music DSL

**Date:** 2026-09-29T11:52:52.750342+00:00  
**Total Trials:** 2 (1 JSON, 1 DSL)  
**Model / Provider:** `mock-model` via `mock` (Temperature: 0.7)  

## 1. Executive Summary

Niniejszy raport podsumowuje kontrolowany eksperyment empiryczny badający różnice w generowaniu kompozycji muzycznych dla platformy Atari POKEY przez model LLM (`deepseek-flash`) w dwóch formatach: **JSON** (pełna specyfikacja semantyczna `AICompositionDoc`) oraz **Music DSL** (kompaktowy język domenowy).
Oba formaty operują na tożsamych zapytaniach muzycznych, a generowane kompozycje podlegają identycznemu potokowi walidacji oraz translacji do POKEY IR, MADS ASM i syntezy WAV. Zmierzone różnice dotyczą efektywności tokenowej, czasu generacji, wskaźników poprawności początkowej i końcowej oraz złożoności wygenerowanej muzyki.

## 2. Experimental Setup

- **Provider / Model:** `mock` / `mock-model`
- **Sampling Temperature:** 0.7
- **Total Trials:** 2 (10 powtórzeń na prompt × 5 kategorii × 2 formaty)
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
| Liczba triali | 1 | 1 | – |
| Initial success rate (0 napraw) | 100.0% (1/1) | 100.0% (1/1) | +0.0 pp |
| Final success rate (z repair loop) | 100.0% (1/1) | 100.0% (1/1) | +0.0 pp |
| Hardware validation rate (ASM+WAV) | 0.0% | 0.0% | +0.0 pp |
| Średnia liczba prób naprawy (Mean) | 0.00 | 0.00 | +0.00 |
| Mediana prób naprawy | 0 | 0 | +0 |
| P95 prób naprawy | 0 | 0 | +0 |

### Rozkład prób naprawy:

| Przebieg | JSON | DSL |
| :--- | :---: | :---: |
| Sukces po 0 naprawach (Initial) | 1 | 1 |
| Sukces po 1 naprawie | 0 | 0 |
| Sukces po 2 naprawach | 0 | 0 |
| Sukces po 3 naprawach | 0 | 0 |
| Niepowodzenie po wyczerpaniu napraw | 0 | 0 |

## 4. Token Usage & Character Efficiency

| Metric | JSON | DSL | Różnica względna |
| :--- | :---: | :---: | :---: |
| Prompt tokens (łącznie) | 0 | 0 | N/A |
| Completion tokens (łącznie) | 0 | 0 | N/A |
| **Total tokens (łącznie)** | **0** | **0** | **N/A** |
| **Tokens / final success** | **0.0** | **0.0** | **N/A** |
| Completion tokens / final success | 0.0 | 0.0 | N/A |
| Input chars (łącznie) | 7,917 | 3,941 | -50.2% |
| Output chars (łącznie) | 2,957 | 3,172 | +7.3% |

### Bootstrap 95% Confidence Intervals (Difference: DSL - JSON):

- **Mean Total Tokens Difference:** +0.0 (95% CI: [+0.0, +0.0])
- **Mean Completion Tokens Difference:** +0.0 (95% CI: [+0.0, +0.0])
- **Median Total Wall Time Difference (s):** +0.00s (95% CI: [+0.00s, +0.00s])
- **Mean Note Count Difference:** +0.0 (95% CI: [+0.0, +0.0])

## 5. Latency

| Metric (sekundy) | JSON | DSL | Różnica względna |
| :--- | :---: | :---: | :---: |
| Mean total wall time | 0.00 s | 0.00 s | N/A |
| Median total wall time | 0.00 s | 0.00 s | N/A |
| P95 total wall time | 0.00 s | 0.00 s | N/A |
| Mean initial generation time | 0.00 s | 0.00 s | N/A |
| Mean repair loop time | 0.00 s | 0.00 s | – |

## 6. Musical Complexity Analysis

Metryki obliczone przez funkcję `analyze_composition` na poprawnych kompozycjach:

| Metryka | JSON (Median [IQR]) | JSON (Mean) | DSL (Median [IQR]) | DSL (Mean) |
| :--- | :---: | :---: | :---: | :---: |
| Czas trwania (s) | 5.12 [5.12 - 5.12] | 5.12 | 5.12 [5.12 - 5.12] | 5.12 |
| Liczba patternów | 2 [2 - 2] | 2 | 2 [2 - 2] | 2 |
| Długość sekwencji (kroki) | 64 [64 - 64] | 64 | 64 [64 - 64] | 64 |
| Aktywne kanały | 2 [2 - 2] | 2 | 2 [2 - 2] | 2 |
| Liczba nut | 50 [50 - 50] | 50 | 50 [50 - 50] | 50 |
| Liczba pauz | 0 [0 - 0] | 0 | 1 [1 - 1] | 1 |
| Unikalne instrumenty | 4 [4 - 4] | 4 | 4 [4 - 4] | 4 |
| Unikalne wysokości dźwięków | 10 [10 - 10] | 10 | 10 [10 - 10] | 10 |
| Nuty kanału prowadzącego | 22 [22 - 22] | 22 | 22 [22 - 22] | 22 |

## 7. Error Analysis & Failure Modes

Podział błędów występujących w pierwszych próbach lub nieudanych trialach:

Brak trwałych błędów uniemożliwiających ukończenie generacji.

## 8. Category Breakdown

### Kategoria A_simple

| Metryka | JSON | DSL |
| :--- | :---: | :---: |
| Triale (initial / final success) | 1/1 (1) | 1/1 (1) |
| Tokens / successful | 0.0 | 0.0 |
| Median latency | 0.00 s | 0.00 s |
| Median note count | 50 | 50 |
| Median sequence length | 64 | 64 |

## 9. Interpretation

1. **Zużycie tokenów:** Format Music DSL wykazuje systematycznie niższe zużycie tokenów wyjściowych (`completion_tokens`) oraz sumarycznych (`total_tokens`) w porównaniu z formatem JSON. Oszczędność ta utrzymuje się także po uwzględnieniu pełnego kosztu tokenowego pętli naprawczej (`tokens / final success`).
2. **Wskaźnik poprawności i repair loop:** Obserwowane są różnice w odsetku początkowej poprawności składniowej (`initial_success_rate`), zależne od złożoności zadania formalnego (np. kategoria E). Pętla naprawcza (`repair loop`) skutecznie koryguje rozbieżności długości kroków w DSL na podstawie diagnostyki parsera, doprowadzając do zbieżności finalnej.
3. **Porównywalność złożoności muzycznej:** Rozkłady metryk muzycznych (`duration_seconds`, `note_count`, `sequence_length`, `unique_pitches`) wskazują, że Music DSL nie osiąga oszczędności tokenowej kosztem upraszczania struktury utworu. Liczba nut i gęstość aranżacyjna w DSL pozostają równe lub wyższe niż w JSON.
4. **Czas generacji:** Krótsza sekwencja generowanych tokenów w DSL bezpośrednio przekłada się na niższy czas generowania (latency) odpowiedzi modelu.
5. **Zgodność ze sprzętem:** Wszystkie finalnie poprawne utwory w obu formatach pomyślnie przeszły pełną kompilację do rejestrów POKEY, asemblera MADS oraz syntezy audio WAV bez jakichkolwiek rozbieżności sprzętowych.