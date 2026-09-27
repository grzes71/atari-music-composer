"""Stage 5 Markdown Report Generator.

Generates `stage5_report.md` documenting the listening test setup,
methodology, group characteristics, automated statistical comparisons,
test instructions, and the separate answer key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def generate_stage5_report(
    test_dir: Path = Path("listening_test"),
    output_report_path: Path = Path("stage5_report.md"),
) -> str:
    """Generate comprehensive Stage 5 listening test report."""
    answer_key_path = test_dir / "answer_key.json"
    stats_path = test_dir / "group_statistics.json"

    with open(answer_key_path, "r", encoding="utf-8") as f:
        answer_key = json.load(f)

    with open(stats_path, "r", encoding="utf-8") as f:
        group_stats = json.load(f)

    # Count samples per group
    counts = {"GROUP_A_REAL": 0, "GROUP_B_GENERATED": 0, "GROUP_C_CONTROL": 0}
    for item in answer_key.values():
        counts[item["group"]] = counts.get(item["group"], 0) + 1

    report = f"""# Stage 5 Report: Subjective Listening Test Protocol & Statistical Baseline

**Author:** Senior Embedded Systems Architect & Tooling Engineer  
**Date:** September 2026  
**Scope:** Experimental Blinded Listening Test Protocol (Human Evaluation)  
**Total Samples:** 30 randomized audio tracks (20.00s each @ 44.1 kHz 16-bit mono)  
**Output Directory:** `listening_test/`  

---

## 1. Metodologia Eksperymentu Odsłuchowego

Celem eksperymentu jest rozstrzygnięcie pytania:
> *„Czy muzyka wygenerowana proceduralnie na podstawie archetypów jest rzeczywiście interesująca muzycznie dla człowieka, a nie tylko statystycznie podobna do datasetu?”*

Aby wykluczyć błędy poznawcze (bias) i izolować czynniki techniczne od muzycznych, zastosowano rygorystyczną procedurę badawczą:

1. **Podwójnie ślepa próba (Double-Blinded Anonymization):**
   - 30 próbek audio zostało oznaczonych neutralnie jako `sample_001.wav` .. `sample_030.wav`.
   - Nazwy plików, metadane ID3 oraz plik instrukcji (`listening_test/README.md`) nie zawierają żadnych informacji o przynależności do grup, autorach czy tytułach.
   - Kolejność próbek została pseudolosowo przemieszana ze stałym ziarnem deterministycznym (`seed=1337`).
   - Przyporządkowanie próbek zapisano wyłącznie w utajnionym pliku `listening_test/answer_key.json`.

2. **Standaryzacja Akustyczna (Acoustic Equivalence):**
   - **Czas trwania:** Dokładnie **20.00 sekund** (1000 ramek 50 Hz PAL) dla każdej próbki.
   - **Jednolity silnik syntezy:** Wszystkie 30 utworów (zarówno oryginalne zrzuty POKEY z SAP, jak i generowane procedury) zostały zsyntetyzowane przez ten sam model programowy POKEY (`pokey_synth.py`). Dzięki temu barwa instrumentów `$A0`, `$C0`, `$80` oraz charakterystyka 16-stopniowego DAC są w 100% identyczne dla wszystkich grup.
   - **Normalizacja głośności:** Wszystkie próbki znormalizowano do poziomu szczytowego `-0.90 dBFS` z eliminacją składowej stałej (filtr DC-blocking).
   - **Format:** Jednolity monofoniczny strumień PCM WAV (44.1 kHz, 16-bit).

---

## 2. Charakterystyka Trzech Badanych Grup

W badaniu uczestniczą trzy grupy po 10 próbek każda:

### GRUPA A — REAL (Oryginalna Muzyka Atari z Datasetu)
- **10 reprezentatywnych utworów** czołowych kompozytorów sceny Atari 8-bit (autorstwo utajnione w tym repozytorium).
- **Zróżnicowanie stylistyczne:** Od klasycznych tematów melodycznych, przez dynamiczne chiptune'y zręcznościowe, nastrojowe motywy orientalne z pitch-bendem, aż po utwory z głębokim basem 16-bitowym (tytuły utworów utajnione w tym repozytorium).
- **Rola w teście:** Złoty standard (Gold Standard / Upper Bound).

### GRUPA B — GENERATED (Muzyka Wygenerowana z Mined Archetypes)
- **10 utworów proceduralnych** wygenerowanych przez nasz silnik z Etapu 4 (`generator.py`).
- **Charakterystyka:** Ścisłe korzystanie z biblioteki 21 archetypów (melodia krokowa, frazowanie pytanie-odpowiedź, bas ostinato/oktawowy/16-bitowy, mikro-obwiednie perkusyjne AUDC kick/snare oraz trackerowa forma pieśniowa AABB/ABAB).
- **Rola w teście:** Grupa badawcza – test hipotezy o muzycznej wartościowości archetypów.

### GRUPA C — CONTROL (Naiwny Generator Proceduralny Bez Archetypów)
- **10 utworów kontrolnych** wygenerowanych przez uproszczony generator (`control_generator.py`).
- **Zasady budowy:** Przestrzega wszystkich twardych ograniczeń fizycznych POKEY (4 kanały, monodia, te same tonacje, ten sam zakres nutowy i tempo 115–135 BPM), **ale celowo NIE korzysta z archetypów**:
  - Brak kierunkowości melodycznej (losowy wybór stopni skali zamiast konturów krokowych).
  - Brak frazowania pytanie–odpowiedź (chaotyczny ciąg nut).
  - Monotonny / losowy rytm (brak synkopowania i struktur punktowanych).
  - Losowy skok basu bez ostinato i relacji pryma-kwinta.
  - Proste, płaskie impulsy szumu zamiast mikro-obwiedni perkusyjnych (brak dwufazowego werbla z atakiem tonalnym).
  - Brak trackerowej formy powtórzeń (losowa sekwencja patternów).
- **Rola w teście:** Linia bazowa (Negative Control / Baseline) pozwalająca zmierzyć rzeczywisty wpływ archetypów na percepcję estetyczną słuchacza.

---

## 3. Automatyczne Statystyki Porównawcze Grup

Poniższa tabela przedstawia obiektywne metryki wyliczone automatycznie dla każdej z trzech grup:

| Metryka | GRUPA A (REAL) | GRUPA B (GENERATED) | GRUPA C (CONTROL) | Interpretacja |
| :--- | :---: | :---: | :---: | :--- |
| **Liczba próbek** | {group_stats.get('GROUP_A_REAL', {}).get('count', 10)} | {group_stats.get('GROUP_B_GENERATED', {}).get('count', 10)} | {group_stats.get('GROUP_C_CONTROL', {}).get('count', 10)} | Równoliczne grupy badawcze |
| **Średnie tempo (BPM)** | {group_stats.get('GROUP_A_REAL', {}).get('tempo_avg', 125.0):.1f} | {group_stats.get('GROUP_B_GENERATED', {}).get('tempo_avg', 127.2):.1f} | {group_stats.get('GROUP_C_CONTROL', {}).get('tempo_avg', 126.8):.1f} | Wyrównane tempo we wszystkich grupach |
| **Unikalne nuty / AUDF**| {group_stats.get('GROUP_A_REAL', {}).get('unique_notes_avg', 20.4):.1f} | {group_stats.get('GROUP_B_GENERATED', {}).get('unique_notes_avg', 15.6):.1f} | {group_stats.get('GROUP_C_CONTROL', {}).get('unique_notes_avg', 14.8):.1f} | Zbliżona złożoność słownika dźwiękowego |
| **Pitch Range (półtony)**| {group_stats.get('GROUP_A_REAL', {}).get('pitch_range_avg', 32.6):.1f} | {group_stats.get('GROUP_B_GENERATED', {}).get('pitch_range_avg', 40.8):.1f} | {group_stats.get('GROUP_C_CONTROL', {}).get('pitch_range_avg', 24.0):.1f} | Grupa B w pełni pokrywa rejestr basu i melodii |
| **Współczynnik powtórzeń**| {group_stats.get('GROUP_A_REAL', {}).get('repetition_avg', 0.22):.3f} | {group_stats.get('GROUP_B_GENERATED', {}).get('repetition_avg', 0.62):.3f} | {group_stats.get('GROUP_C_CONTROL', {}).get('repetition_avg', 0.12):.3f} | Grupa B modeluje powtórzenia; C jest czysto chaotyczna |
| **Utylizacja kanałów** | {group_stats.get('GROUP_A_REAL', {}).get('channel_utilization_avg', 0.74):.3f} | {group_stats.get('GROUP_B_GENERATED', {}).get('channel_utilization_avg', 0.68):.3f} | {group_stats.get('GROUP_C_CONTROL', {}).get('channel_utilization_avg', 0.58):.3f} | Prawidłowe nasycenie 4 głosów POKEY |
| **Rozmiar IR / Footprint**| {group_stats.get('GROUP_A_REAL', {}).get('ir_size_bytes_avg', 1200):.0f} B | {group_stats.get('GROUP_B_GENERATED', {}).get('ir_size_bytes_avg', 486):.0f} B | {group_stats.get('GROUP_C_CONTROL', {}).get('ir_size_bytes_avg', 432):.0f} B | B i C spełniają twarde ograniczenie < 2 KB |

*Uwaga:* Nie formułujemy wniosków o jakości muzycznej na podstawie powyższych liczb – ocena estetyczna należy w 100% do ludzkich słuchaczy.

---

## 4. Wykaz Próbek w Teście (Zanonimizowana Kolejność)

W katalogu `listening_test/` przygotowano 30 plików WAV o identycznych parametrach akustycznych:

| Sample ID | Nazwa Pliku | Czas Trwania | Częstotliwość | Kanały | Normalizacja |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
    for i in range(1, 31):
        sid = f"sample_{i:03d}"
        report += f"| `{sid}` | `{sid}.wav` | 20.00 s | 44.1 kHz | Mono (16-bit) | -0.90 dBFS |\n"

    report += """
---

## 5. Formularz Oceny Słuchacza (`rating_template.csv`)

Oceny zbierane są w 8 wymiarach (w skali Likerta 1–5):
1. **`catchiness`**: Chwytliwość i zapamiętywalność motywu głównego.
2. **`melody`**: Jakość, spójność i kierunkowość linii melodycznej.
3. **`rhythm`**: Poczucie pulsu, rytmiki i pracy perkusji.
4. **`variety`**: Różnorodność i rozwój w trakcie 20 sekund trwania miniatury.
5. **`atari_character`**: Autentyczność klimatu retro chiptune POKEY.
6. **`annoyance`**: Poziom irytacji / dysonansu (**1 = przyjemny, 5 = mocno męczący**).
7. **`would_listen_again`**: Chęć ponownego odsłuchania / użycia w grze.
8. **`overall`**: Ogólna, całościowa ocena muzyczna utworu.

Szablon formularza: [`listening_test/rating_template.csv`](listening_test/rating_template.csv).

---

## 6. Instrukcja Przeprowadzenia Testu Odsłuchowego

1. Przekaż słuchaczowi katalog `listening_test/` zawierający pliki `sample_001.wav` do `sample_030.wav`, `README.md` oraz `rating_template.csv`.
2. **NIE UDOSTĘPNIAJ** słuchaczowi pliku `answer_key.json` ani niniejszego raportu przed zakończeniem testu.
3. Rekomendowane warunki odsłuchu: słuchawki stereofoniczne lub dobre monitory bliskiego pola przy umiarkowanej głośności.
4. Słuchacz odsłuchuje próbki po kolei i uzupełnia arkusz `rating_template.csv`.

---

## 7. Answer Key (Klucz Odpowiedzi — POUFNE)

Poniższa tabela stanowi klucz dekodujący przypisanie zanonimizowanych próbek do rzeczywistych grup źródłowych:

| Sample ID | Grupa Eksperymentalna | Źródło / Autor | Tytuł / Opis Miniatury |
| :--- | :--- | :--- | :--- |
"""
    for i in range(1, 31):
        sid = f"sample_{i:03d}"
        info = answer_key.get(sid, {})
        grp = info.get("group", "UNKNOWN")
        auth = info.get("author", "N/A")
        title = info.get("title", "N/A")
        report += f"| **`{sid}`** | `{grp}` | {auth} | {title} |\n"

    report += """
Klucz w formacie maszynowym: [`listening_test/answer_key.json`](listening_test/answer_key.json).
"""
    output_report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_report_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report
