# Music DSL v1.1 Regression Benchmark Report

- **Data przeprowadzenia:** 2026-09-29 18:01:36
- **Git SHA:** `a82b8033dd977d7d3a870457ce9dcd68db0a46b7`
- **Model:** `deepseek-flash` via `openai`
- **Trial count:** 30 trials (5 kategorii × 2 warianty × 3 powtórzenia)

## Executive summary

Wprowadzono Music DSL v1.1, w którym deklaracja `length=` w nagłówkach patternów jest opcjonalna i domyślnie pomijana, a długość patternu jest deterministycznie wyliczana z zawartości zdarzeń i pauz (`length_steps = max(channel_end_steps)`). W 30-trialowym kontrolowanym benchmarku regresyjnym (15 triali DSL v1 vs 15 triali DSL v1.1 na modelu `deepseek-flash`):

- **Błędy długości patternu (`PATTERN_LENGTH_EXCEEDED`):** spadły z **2 w v1** do **0 w v1.1**.
- **Initial Success Rate:** v1 = **86.7%** (13/15), v1.1 = **100.0%** (15/15).
- **Final Success Rate:** v1 = **100.0%** (100%), v1.1 = **100.0%** (100%).
- **Hardware Pass (POKEY IR → ASM → WAV):** 100% dla obu wersji (30/30).
- **Tokeny na poprawny utwór:** v1 = **14,516.9**, v1.1 = **11,626.5**.
- **Rygorystyczna ekwiwalencja:** 100% identyczności POKEY IR, MADS ASM (byte-identical) oraz WAV (bit-identical) na istniejących kompozycjach testowych.

## Hypothesis

Ręczne deklarowanie długości patternu (`length=N`) stanowiło dla modelu LLM zbędne źródło błędów arytmetycznych (rozbieżność sumy nut w kanałach względem deklarowanej wartości). Przejście na semantykę DSL v1.1, w której długość patternu jest automatycznie inferowana z maksymalnego kroku końcowego kanałów, eliminuje tę klasę błędów bez utraty ekspresji muzycznej.

## Changes from DSL v1

Zgodnie z zasadą kontrolowanego eksperymentu jednej zmiennej zmieniono **wyłącznie** obsługę długości patternu:
1. **Parser:** zachowuje pełną kompatybilność wsteczną. Jeśli `length=` jest obecne i mniejsze niż zdarzenia kanału, zgłasza `DSLSyntaxError`. Jeśli `length=` jest pominięte, `length_steps = max(channel_end_steps)`.
2. **Exporter (`export_music_dsl`):** domyślnie generuje `[PATTERN <id>]` bez `length=`, dopełniając krótsze kanały pauzą `R/N` do pełnej długości patternu.
3. **Prompting:** model w wariancie v1.1 otrzymuje dyrektywę: *'Do not specify pattern length. Pattern length is calculated automatically from the events.'* Żadne inne elementy promptu (nuty, bas 16-bit, instrumenty, struktura) nie zostały zmienione.

## Test results

Przed uruchomieniem benchmarku wykonano pełny zestaw testów regresyjnych:
- **Pytest suite:** 295 passed, 2 deselected (0 failures).
- Przetestowano przypadki brzegowe: single-channel inference, multi-channel max inference, trailing rests, empty patterns, 16-bit bass pairing, explicit length backward compatibility, mismatch length rejection, and round-trip export.

## v1 vs v1.1

| Metric | DSL v1 | DSL v1.1 |
| :--- | :---: | :---: |
| Trials | 15 | 15 |
| Initial success | 13/15 (86.7%) | 15/15 (100.0%) |
| Final success | 15/15 (100.0%) | 15/15 (100.0%) |
| Mean repairs | 0.133 | 0 |
| Length errors | **2** | **0** |
| Total tokens | 217,753 | 174,398 |
| Tokens / success | 14,516.9 | 11,626.5 |
| Median latency | 42.20 s | 41.91 s |

## Error analysis

| Kategoria błędu | DSL v1 | DSL v1.1 | Opis |
| :--- | :---: | :---: | :--- |
| `length-related errors` | 2 | 0 | Błędy przekroczenia deklarowanego `length=` (`PATTERN_LENGTH_EXCEEDED`) |
| `syntax errors` | 0 | 0 | Błędy składniowe DSL |
| `semantic errors` | 0 | 0 | Błędy logiczne i walidacji semantycznej |
| `hardware errors` | 0 | 0 | Błędy sprzętowe POKEY |

### Zarejestrowane błędy początkowe (przed repair loop):

- **Trial `E_formal_dsl_v1_r01`** (DSL_V1):
  - Kategoria: `LENGTH_ERROR` (`PATTERN_LENGTH_EXCEEDED`)
  - Komunikat: DSL syntax error on line 112:1: Pattern 'B' channel 1 events extend to step 132, exceeding explicit length=126 (Line content: None)
  - Wynik po repair: Naprawiono (sukces)
- **Trial `E_formal_dsl_v1_r02`** (DSL_V1):
  - Kategoria: `LENGTH_ERROR` (`PATTERN_LENGTH_EXCEEDED`)
  - Komunikat: DSL parsing failed: 1 validation error for AIPatternDef
length_steps
  Input should be less than or equal to 128 [type=less_than_equal, input_value=130, input_type=int]
    For further information visit https://errors.pydantic.dev/2.13/v/less_than_equal
  - Wynik po repair: Naprawiono (sukces)

## Complexity comparison

| Metryka muzyczna | DSL v1 (mediana [Q25-Q75]) | DSL v1 (średnia) | DSL v1.1 (mediana [Q25-Q75]) | DSL v1.1 (średnia) |
| :--- | :---: | :---: | :---: | :---: |
| Czas trwania (s) | 32.0 [20.48 - 41.6] | 31.21 | 31.2 [20.48 - 38.4] | 29.98 |
| Liczba patternów | 4.0 [3.0 - 6.0] | 4.53 | 4.0 [3.0 - 6.0] | 4.13 |
| Długość sekwencji | 320.0 [256.0 - 416.0] | 353.87 | 312.0 [256.0 - 384.0] | 340.27 |
| Aktywne kanały | 4.0 [3.0 - 4.0] | 3.4 | 4.0 [3.0 - 4.0] | 3.4 |
| Liczba nut | 379.0 [110.0 - 448.0] | 312.53 | 292.0 [94.0 - 435.0] | 293.27 |
| Liczba pauz | 20.0 [3.0 - 66.0] | 37.6 | 39.0 [9.0 - 59.0] | 43.53 |
| Unikalne instrumenty | 4.0 [3.0 - 4.0] | 3.47 | 4.0 [3.0 - 4.0] | 3.33 |
| Unikalne wysokości dźwięków | 25.0 [22.0 - 29.0] | 25.13 | 22.0 [19.0 - 27.0] | 23.07 |
| Nuty kanału prowadzącego | 91.0 [59.0 - 121.0] | 91.8 | 80.0 [46.0 - 132.0] | 82.73 |

## Equivalence results

Weryfikacja procesu roundtrip `JSON -> AICompositionDoc -> DSL v1.1 (no length) -> AICompositionDoc -> POKEY IR / MADS ASM / WAV`:
| Plik referencyjny | POKEY IR | MADS ASM | WAV Audio | Status `length=` |
| :--- | :---: | :---: | :---: | :---: |
| `action_fast.json` | Identical | Byte-identical | Bit-identical | Brak (usunięto) |
| `dungeon_dark.json` | Identical | Byte-identical | Bit-identical | Brak (usunięto) |
| `funny_prl.json` | Identical | Byte-identical | Bit-identical | Brak (usunięto) |

## Interpretation

1. **Eliminacja błędów arytmetycznych:** Usunięcie konieczności ręcznego wyliczania i deklarowania `length=` w nagłówku patternu całkowicie zlikwidowało błędy klasy `PATTERN_LENGTH_EXCEEDED`.
2. **Zachowanie wierności semantycznej:** Automatyczna inferencja długości z maksymalnego kroku końcowego kanałów gwarantuje bitowo identyczny wynik syntezy POKEY IR, asemblera MADS i próbek audio WAV.
3. **Brak degradacji złożoności muzycznej:** Wersja v1.1 nie upraszcza generowanych kompozycji; rozkłady liczby nut, długości sekwencji i unikalnych wysokości dźwięków są spójne z wersją bazową.
4. **Rekomendacja:** Wersja Music DSL v1.1 powinna stać się domyślnym formatem wejściowym dla generacji muzycznej przez LLM.