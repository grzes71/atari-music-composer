# Atari 8-bit POKEY Music Engine & Toolkit

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform: Atari 8-bit](https://img.shields.io/badge/platform-Atari%20800%20XL%20%2F%2065%20XE-red.svg)](https://en.wikipedia.org/wiki/Atari_8-bit_family)
[![Assembler: MADS](https://img.shields.io/badge/assembler-MADS%201.9.6-green.svg)](http://mads.atari8.info/)
[![CPU: MOS 6502](https://img.shields.io/badge/cpu-MOS%206502-orange.svg)](https://en.wikipedia.org/wiki/MOS_Technology_6502)
[![Tests: 135 Passed](https://img.shields.io/badge/tests-135%20passed-brightgreen.svg)](tests/)

Kompletny, profesjonalny system generowania, aranżacji, syntezy i odtwarzania muzyki dla komputerów **Atari 8-bit (Atari 800 XL / 65 XE)** wyposażonych w układ dźwiękowy **POKEY**.

Projekt łączy proceduralną kompozycję w Pythonie z natywnym eksportem do asemblera **MADS** oraz ultra-kompaktowym, w pełni relokowalnym odtwarzaczem napisanym w czystym asemblerze **MOS 6502**.

---

## 🚀 Kompletny Pipeline Projektu

```text
┌───────────────────────────────┐        ┌───────────────────────────────┐
│     Composer v4 (Python)      │        │      AI LLM Composer (JSON)   │
│  Proceduralna kompozycja      │        │  DeepSeek / OpenAI Structured │
└──────────────┬────────────────┘        └──────────────┬────────────────┘
               │                                        │  AICompositionDoc v1
               │                                        ▼
               │                         ┌───────────────────────────────┐
               │                         │  3-Tier Validator & Repair    │
               │                         │  Schema + Musical + Hardware  │
               │                         └──────────────┬────────────────┘
               │                                        │  Composition Interpreter
               │  MusicGenerationResult                 │  & Analysis Engine
               └───────────────────┬────────────────────┘
                                   │  Music IR + POKEY IR
                                   ▼
                    ┌───────────────────────────────┐
                    │       MADS Exporter           │  Konwersja do Structure-of-Arrays (SoA)
                    └──────────────┬────────────────┘
                                   │  music_data.asm (kompaktowe strumienie nut, RLE)
                                   ▼
                    ┌───────────────────────────────┐
                    │        MADS Assembler         │  Kompilacja: player.asm + music_data.asm + harness
                    └──────────────┬────────────────┘
                                   │  Standalone Atari XEX Executable (< 1.6 KB RAM)
                                   ▼
                    ┌───────────────────────────────┐
                    │       Atari 8-bit / POKEY     │  PAL 50 Hz VBLANK / 4 kanały / 16-bit Bass
                    └───────────────────────────────┘
```

---

## ✨ Główne Możliwości

* **Composer v4 — Pełna 4-kanałowa aranżacja:**
  * **6 kanonicznych profili stylistycznych:** `TITLE`, `EXPLORATION`, `ACTION`, `FUNNY`, `DUNGEON`, `ENDING`.
  * **Zaawansowany kontrapunkt dla 2. głosu:** Call & Response, wsparcie harmoniczne (tercje/seksty), ruch równoległy, hocketing, echo motywiczne.
  * **Dedykowany silnik basu:** Walking bass, fanfare, pulse, staccato, modal drone.
  * **Rytmika i ornamentacja (4. głos):** 16-tkowe groovy perkusyjne, werble marszowe, modalne ostinato, wysokie dzwonki.
  * **Wieloczęściowa forma muzyczna:** Dynamiczne stopniowanie obsady (Intro $\to$ A $\to$ B $\to$ Outro $\to$ Loop).
  * **Obsługa 16-bit POKEY Bass:** Sprzęganie kanałów 1 i 2 (`AUDCTL = $10`) w 16-bitowy dzielnik częstotliwości z czystą syntezą sinusoidalną (pure tone).
* **Cyfrowy Syntezator POKEY (Python):**
  * Dokładna emulacja rejestrów POKEY (`AUDF1..4`, `AUDC1..4`, `AUDCTL`).
  * Bezpośredni rendering do 16-bitowego pliku WAV 44.1 kHz PCM mono.
* **Relokowalny Odtwarzacz 6502 (`player.asm`):**
  * **MOS 6502:** Czyste, oficjalne instrukcje 6502 (bez CMOS/65C02).
  * **Pełna relokowalność:** Zero twardych założeń adresowych — działa pod dowolnym adresem (`$4000`, `$6000`, `$7000`, `$8000`, `$A000` lub w rozłącznych bankach).
  * **Konfigurowalne Zero Page:** Wymaga tylko 10 bajtów w Zero Page (`PLAYER_ZP_BASE = $80`), w pełni redefiniowalne przed dołączeniem playera.
  * **Minimalny narzut pamięci:** Kod playera to **754 bajty**, zmienne RAM to **55 bajtów**, dane utworu to **340–750 bajtów**. Cały moduł mieści się w **< 1.6 KB RAM**.
  * **Znikomy narzut CPU:** Średnio **~110–140 cykli na ramkę** (< 1.5% ramki PAL 50 Hz).
  * **Standardowe API:** `music_init`, `music_play`, `music_stop`, `music_update`, `music_is_playing`.
* **Gotowe Executable XEX:**
  * Samodzielne pliki `.xex` gotowe do uruchomienia na fizycznym Atari lub w emulatorze.
  * Synchronizacja z ramką obrazu VBLANK (50 Hz PAL) przez `RTCLOK` (`$14`).
  * Wyciszanie i wznawianie odtwarzania jednym klawiszem (`CH` `$02FC`).
  * **Interaktywny ekran odtwarzacza (ANTIC Mode 2 / Graphics 0):** Wbudowany zegar czasu rzeczywistego (`TIME: MM:SS / TOTAL_MM:SS`), licznik kroków sekwencji (`STEP: XX / TOTAL`), wskaźnik stanu (`[PLAYING]` / `[PAUSED ]`) oraz 4-kanałowy, animowany w czasie rzeczywistym horyzontalny visualizer głośności VU.

---

## 📦 Instalacja i Wymagania

### Wymagania systemowe
* **Python $\ge$ 3.10**
* System operacyjny: Windows / Linux / macOS
* Asembler **MADS $\ge$ 1.9.6** (dołączony w katalogu `tools/mads/mads.exe`)

### Instalacja środowiska Python

```bash
# Sklonuj repozytorium lub przejdź do katalogu projektu
cd atari-music

# Utwórz i aktywuj wirtualne środowisko
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Zainstaluj projekt w trybie deweloperskim
pip install -e .
```

---

## 🎵 Przykłady Użycia

### 1. Python API (`atari_music.api`)

Publiczny interfejs API oferuje funkcję `generate_music(...)`, która jest pojedynczym punktem wejścia do całego silnika.

#### A. Wygenerowanie utworu i eksport do WAV oraz MADS ASM

```python
from atari_music.api import generate_music
from atari_music.mads_exporter import export_mads_asm

# 1. Wygeneruj kompozycję o profilu 'ACTION'
result = generate_music(
    profile="action",
    seed=301,
    length="medium",       # "short" (~15s), "medium" (~24s), "long" (~34s)
    intensity=0.85,        # 0.0 (subdued) .. 1.0 (driving)
    variation=0.60,        # 0.0 (conservative) .. 1.0 (adventurous)
)

print(f"Utwór: {result.music_ir.title}")
print(f"Tempo: {result.metadata.tempo} BPM")
print(f"Tonacja: {result.metadata.key} {result.metadata.mode}")
print(f"Liczba kanałów: {result.metadata.channels_used}")
print(f"Rozmiar danych POKEY IR: {result.metadata.memory_size_bytes} B")

# 2. Wyrenderuj plik audio WAV (44.1 kHz PCM)
wav_path = result.render_wav("output/action_sample.wav")
print(f"Zapisano audio WAV -> {wav_path}")

# 3. Zapisz strukturę POKEY IR w formacie JSON
json_path = result.save_json("output/action_song.json")
print(f"Zapisano POKEY IR JSON -> {json_path}")

# 4. Wyeksportuj kod danych asemblera MADS (.asm)
export_mads_asm(result, output_path="output/action_data.asm", song_label="song_data")
print("Wyeksportowano kod MADS ASM -> output/action_data.asm")
```

#### B. Generowanie 16-bitowego basu (`DUNGEON`)

Dla profilu `DUNGEON` silnik domyślnie sprzęga kanały 1 i 2, tworząc 16-bitowy generator pure tone:

```python
from atari_music.api import generate_music
from atari_music.mads_exporter import export_mads_asm

result = generate_music(
    profile="dungeon",
    seed=501,
    key="A",               # Wymuszenie tonacji A minor/dorian
    tempo=85,              # Wymuszenie tempa 85 BPM
    uses_16bit_bass=True,  # Sprzężenie kanałów 1 i 2 (AUDCTL = $10)
)

print(f"Tryb 16-bit bass: {result.metadata.uses_16bit_bass}")
export_mads_asm(result, "output/dungeon_16bit.asm")
```

---

### 2. Command Line Interface (`atari-music`)

Po instalacji pakietu dostępne jest polecenie CLI `atari-music`:

#### A. Polecenie `compose`

Generuje utwór z poziomu wiersza poleceń z opcją jednoczesnego zapisu WAV, JSON i ASM:

```bash
# Wygenerowanie utworu ACTION ze zdefiniowanym seedem, WAV i MADS ASM:
atari-music compose --profile action --seed 301 --output-wav action.wav --output-asm action.asm

# Wygenerowanie powolnego, melancholijnego motywu eksploracyjnego w tonacji E:
atari-music compose --profile exploration --seed 201 --key E --tempo 80 --output-wav explore.wav

# Generowanie utworu typu TITLE z zapisem do wszystkich formatów:
atari-music compose --profile title --seed 101 --output-wav title.wav --output-json title.json --output-asm title.asm
```

#### B. Polecenie `export-mads`

Konwertuje wcześniej zapisany plik POKEY IR JSON na kod źródłowy asemblera MADS:

```bash
atari-music export-mads title.json -o title_data.asm
```

#### C. Polecenie `analyze`

Analizuje właściwości muzyczne (rytm, melodia, harmonia), wykorzystanie sprzętu POKEY, czas trwania PAL 50 Hz, deterministyczny fingerprint SHA-256 oraz opcjonalnie makrostrukturę utworu:

```bash
# Czytelny raport diagnostyczny w terminalu:
atari-music analyze dungeon.json

# Rozszerzona analiza makrostruktury i dedukcji formy:
atari-music analyze dungeon.json --structure

# Wyjście w formacie JSON (na stdout lub zapisane do pliku) dla narzędzi i agentów:
atari-music analyze dungeon.json --json
atari-music analyze dungeon.json --structure -o report.json
```

---

### 3. Integracja z Projektem 6502 (Asembler MADS)

Wyeksportowany plik `music_data.asm` oraz odtwarzacz [player.asm](player.asm) można dołączyć bezpośrednio do dowolnej gry lub dema na Atari 8-bit.

#### A. Przykładowy plik główny gry / odtwarzacza (`play_music.asm`)

```asm
; =============================================================================
; Minimalny szablon odtwarzacza w grze na Atari 8-bit
; =============================================================================

    org $4000                   ; Adres instalacji programu w RAM

start:
    ; 1. Inicjalizacja sprzętowa
    cli                         ; Odblokuj przerwania CPU
    lda #$40
    sta $D40E                   ; NMIEN: Zezwól na przerwanie VBLANK

    ; 2. Inicjalizacja utworu (wskaźnik w rejestrach X i Y)
    ldx #<song_data             ; Młodszy bajt adresu danych utworu
    ldy #>song_data             ; Starszy bajt adresu danych utworu
    jsr music_init

    ; 3. Rozpoczęcie odtwarzania
    jsr music_play

    ; 4. Pętla główna (synchronizacja VBLANK 50 Hz PAL)
main_loop:
    lda $14                     ; RTCLOK+2: inkrementowany co ramkę przez OS
@wait_vbl:
    cmp $14
    beq @wait_vbl

    ; Opcjonalnie: sprawdzenie klawisza (Spacja = Mute/Play Toggle)
    lda $02FC                   ; Rejestr wciśniętego klawisza (CH)
    cmp #$FF
    beq @no_key
    lda #$FF
    sta $02FC                   ; Skasuj bufor klawisza

    jsr music_is_playing
    bne @mute
    jsr music_play              ; Wznów
    jmp @no_key
@mute:
    jsr music_stop              ; Wycisz POKEY

@no_key:
    ; 5. Krok odtwarzacza (musi być wywoływany dokładnie raz na ramkę)
    jsr music_update

    jmp main_loop

; =============================================================================
; Dołączenie modułów (relokowalne)
; =============================================================================
    icl 'player.asm'            ; Kod odtwarzacza 6502 (~809 bajtów)
    icl 'music_data.asm'        ; Wygenerowane dane utworu (~340-750 bajtów)

; Ustawienie adresu startowego pliku XEX
    run start
```

#### B. Kompilacja do pliku Atari XEX przy użyciu MADS

```bash
# Kompilacja pod Windows:
tools\mads\mads.exe play_music.asm -o:play_music.xex

# Kompilacja pod Linux/macOS (jeśli mads jest zainstalowany w PATH):
mads play_music.asm -o:play_music.xex
```

Powstały plik `play_music.xex` można bezpośrednio otworzyć w emulatorze (np. Altirra) lub wgrać na rzeczywiste Atari (przez SIO2SD, SIDE3, FujiNet itp.).

---

### 4. Relokowalność i Konfiguracja Zero Page

Player jest w 100% relokowalny i nie posiada żadnych ukrytych stałych adresowych.

#### A. Zmiana adresu bazowego w pamięci
Player i dane muzyczne mogą pracować pod dowolnym adresem w pamięci użytkownika:
```asm
    org $6000                   ; Instalacja pod $6000
    ; ...
    icl 'player.asm'
    icl 'music_data.asm'
```

Możliwe jest również rozdzielenie modułów (np. kod playera w jednym banku RAM, dane utworu w innym):
```asm
    org $5000
    icl 'player.asm'

    org $8500
    icl 'music_data.asm'
```

#### B. Zmiana adresu w Zero Page (`PLAYER_ZP_BASE`)
Domyślnie player używa 10 bajtów w wolnym obszarze pamięci zerowej Atari OS: `$80–$89`. Jeśli Twoja gra potrzebuje tego obszaru, możesz przenieść player na inne bajty Zero Page przed jego dołączeniem:

```asm
PLAYER_ZP_BASE = $90           ; Użyj bajtów $90-$99 w Zero Page

    org $4000
    icl 'player.asm'
    icl 'music_data.asm'
```

Asembler MADS automatycznie wygeneruje instrukcje z nowymi adresami Zero Page (`($98),Y` zamiast `($88),Y`).

---

## 🎮 Gotowe Pliki XEX do Testów Odsłuchowych

W katalogu [stage11_xex/](stage11_xex/) znajduje się 6 gotowych, skompilowanych plików binarnych `.xex` reprezentujących wszystkie profile muzyczne:

| Plik XEX | Profil | Seed | BPM | Tonacja | Długość cyklu | Kanały | 16-bit Bass | Rozmiar XEX |
|---|---|---:|---:|---|---:|---:|:---:|---:|
| [`title.xex`](stage11_xex/title.xex) | **TITLE** | 101 | 93 | G minor | 25.6 s | 4 | Nie | 1 242 B |
| [`exploration.xex`](stage11_xex/exploration.xex) | **EXPLORATION** | 201 | 82 | E mixolydian | 25.6 s | 4 | Nie | 1 218 B |
| [`action.xex`](stage11_xex/action.xex) | **ACTION** | 301 | 167 | G dorian | 17.3 s | 4 | Nie | 1 628 B |
| [`funny.xex`](stage11_xex/funny.xex) | **FUNNY** | 401 | 136 | F major | 23.0 s | 4 | Nie | 1 499 B |
| [`dungeon.xex`](stage11_xex/dungeon.xex) | **DUNGEON** | 501 | 85 | A dorian | 25.6 s | 3 (1+2 coupled) | **TAK** | 1 317 B |
| [`ending.xex`](stage11_xex/ending.xex) | **ENDING** | 601 | 112 | C major | 20.5 s | 4 | Nie | 1 563 B |

### Jak przetestować w emulatorze Altirra:
1. Uruchom emulator **Altirra** (skonfiguruj maszynę jako *Atari XL/XE*, system *PAL*).
2. Przeciągnij i upuść plik `.xex` (np. `dungeon.xex`) w okno emulatora.
3. Muzyka wystartuje automatycznie.
4. Wciśnięcie dowolnego klawisza (np. Spacji) wycisza dźwięk. Ponowne wciśnięcie wznawia odtwarzanie.

Szczegółowa checklista odsłuchowa znajduje się w [stage11_xex/README.md](stage11_xex/README.md).

---

## 📊 Budżet Pamięci i Zużycie CPU

### Rozkład pamięci (Memory Map dla adresu `$4000`)

```text
$0080 - $0089   Zero Page Pointers (10 bajtów: zp_ch1..4_ptr, zp_tmp_ptr)
$4000 - $4037   Test Harness (56 bajtów: setup, VBLANK sync, keyboard toggle)
$4038 - $4329   Kod odtwarzacza 6502 (754 bajty czystych instrukcji)
$432A - $4360   Zmienne stanu odtwarzacza (55 bajtów w RAM)
$4361 - $4xxx   Struktury danych utworu (341 - 751 bajtów)
```

Dokładny opis segmentów dla każdego utworu znajduje się w [stage11_xex/memory_map.md](stage11_xex/memory_map.md).

### Pomiar wydajności CPU (cykle procesora na ramkę)

| Faza wykonania | Średni koszt (cykle 6502) | Udział w ramce PAL (35 568 cykli) |
|---|---|---|
| **Ramka typowa (obwiednie głośności)** | ~110 – 140 cykli | **0.35%** |
| **Krok nutowy (ładowanie nowych zdarzeń)** | ~180 – 260 cykli | **0.65%** |
| **Przejście sekwencji (najgorszy przypadek)** | ~340 – 420 cykli | **1.15%** |

Odtwarzacz zużywa ułamek budżetu pojedynczej ramki, dzięki czemu doskonale nadaje się do gier ze skomplikowaną logiką i grafiką ANTIC/GTIA.

---

## 📁 Struktura Projektu

---

## 🤖 AI Music Composition, Structure & Arrangement Layer

Projekt zawiera w pełni zintegrowaną, autonomiczną warstwę **AI Music Composition & Arrangement**.
Model AI pełni wyłącznie rolę **kompozytora i aranżera** (tworząc deklaratywny dokument JSON `atari-music-composition` v1), a nie generatora kodu 6502 ani bezpośrednich rejestrów POKEY. Całość walidacji, interpretacji, analizy, kompilacji i eksportu wykonuje deterministyczny pipeline `atari-music`:

```text
Prompt / Intent -> AI Provider (DeepSeek / OpenAI) -> AICompositionDoc (JSON)
                                                            │
    ┌───────────────────────────────────────────────────────┘
    ▼
3-Tier Validation (Schema -> Musical -> Hardware) ──[ Błąd ]──> Repair Feedback Loop (max 2-3 retries)
    │ [ Sukces ]
    ├───────────────────────────────────────────────────────┬───────────────────────────────────┐
    ▼                                                       ▼                                   ▼
Composition Interpreter                               Musical & POKEY Analysis            Structure & Arrangement Analysis
    │                                                       │                                   │ (repetition ratio, variations,
    ▼                                                       ▼                                   │  material reuse, form deduction,
Music IR & POKEY IR                                   Composition Fingerprint (SHA-256)         │  texture changes, novelty)
    │                                                 & Metrics (Rhythm/Melody/Harmony)         ▼
    ▼                                                                                     Structure Report & JSON
MADS ASM Exporter -> 6502 Player -> Atari XEX Executable (z graficznym timerem i VU)
```

### 1. Konfiguracja Środowiska i `.env` (DeepSeek / OpenAI)
Projekt wspiera elastyczną, 4-stopniową hierarchię konfiguracji z priorytetami:
1. **Argumenty CLI** (najwyższy priorytet),
2. **Zmienne środowiskowe systemu**,
3. **Plik `.env`** (ładowany przez `python-dotenv`),
4. **Wartości domyślne w kodzie** (najniższy priorytet).

W katalogu głównym projektu znajduje się plik wzorcowy [.env.example](.env.example):
```env
# Konfiguracja produkcyjna LLM (np. DeepSeek)
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
LOG_LEVEL=INFO
```

> **Bezpieczeństwo:** Klucze API podlegają automatycznemu maskowaniu (`Config.masked_api_key()`) i **nigdy** nie są zapisywane w plikach JSON, kodzie asemblera, nagłówkach XEX ani raportach ewaluacyjnych.

### 2. Structured Outputs i Monofonia Kanałów POKEY
- **Natywne Structured Outputs**: Provider wykorzystuje schema-constrained JSON oparty bezpośrednio na modelach Pydantic (`AICompositionDoc`), gwarantując poprawność typów bez konieczności czyszczenia tekstu markdown.
- **Ścisła monofonia POKEY**: POKEY posiada 4 fizycznie monofoniczne kanały. Walidator odrzuca jakiekolwiek nakładanie się nut (`NOTE_OVERLAP`) na tym samym kanale, podając dokładny krok, kanał i konfliktujące wysokości.
- **Sprzężenie 16-bitowego basu**: Przy fladze `use_16bit_bass: true` silnik sprzęga Kanały 1 i 2 (`AUDCTL = $50`), rezerwując Kanał 2 jako slave dzielnika częstotliwości.

### 3. Automatyczna Pętla Naprawcza (Composition Repair Loop)
Gdy model wygeneruje kompozycję naruszającą reguły (np. nakładające się nuty lub konflikt kanałów), system nie przerywa pracy:
- Walidator generuje zbiorczy raport [ValidationReport](src/atari_music/ai/schema.py) z kodami błędów (`NOTE_OVERLAP`, `INVALID_NOTE`, `BASS16_CHANNEL_CONFLICT`).
- Pętla `generate_composition_with_retry(..., max_retries=3)` przesyła do modelu ustrukturyzowany feedback wskazujący dokładne miejsce błędu z instrukcją zachowania poprawnych fragmentów.
- Testy na produkcyjnym modelu `deepseek-flash` wykazały **100% skuteczności naprawy** w 2. podejściu.

### 4. Moduł Analizy Muzycznej i Sprzętowej (`analysis.py`)
Wprowadzono moduł [src/atari_music/ai/analysis.py](src/atari_music/ai/analysis.py) oceniający wygenerowane utwory:
* **Rytm:** liczba nut, gęstość nutowa ($\text{nut/s}$), rozkład długości nut, rest ratio, aktywność każdego kanału.
* **Melodia:** rozpiętość w półtonach, liczba unikalnych klas wysokości, średni interwał, stosunek ruchu krokowego do skoków, kierunek melodyczny.
* **Harmonia:** współbrzmienia pionowe, rozkład klas interwałów 0..6, czyste oktawy, kwinty, współczynnik konsonansów/dysonansów.
* **POKEY Hardware:** weryfikacja sprzężenia 16-bit basu, utylizacja 4 kanałów, rozkład głośności i rejestrów distortion ($A0, $C0, $E0), ostrzeżenia dla playera 6502 (np. `ch_dur <= 254`).

### 5. Deterministyczny Composition Fingerprint
Funkcja `composition_fingerprint(doc) -> str` generuje 64-znakowy skrót SHA-256 z kanonicznej postaci utworu:
* **Niezależna** od formatowania JSON, spacji, wcięć czy kolejności kluczy.
* **Deterministyczna:** identyczne utwory dają identyczny hash.
* **Czuła:** zmiana choćby jednej nuty, dynamiki, instrumentu czy czasu trwania natychmiast zmienia fingerprint.

### 6. Pełnometrażowe Utwory 60–120 s & Weryfikacja Czasu Trwania
* **Ścisły pomiar czasu:** Funkcja `calculate_composition_duration()` wylicza rzeczywisty czas odtwarzania utworu w oparciu o sumę długości patternów w sekwencji oraz dzielniki ramek VBLANK PAL (50 Hz).
* **Weryfikacja Invariantu:** Funkcja `verify_duration_invariant()` gwarantuje, że wygenerowany utwór spełnia warunek $60.0 \le t \le 120.0\text{ s}$. Jeśli czas odbiega od założeń, pętla naprawcza automatycznie odsyła feedback korygujący sekwencję.
* **Wbudowany timer i wskaźniki VU:** Wszystkie pliki XEX generowane z kompozycji AI posiadają interaktywny interfejs w trybie ANTIC Mode 2 (Graphics 0) wyświetlający czas odtwarzania w czasie rzeczywistym (`MM:SS / TOTAL`), stan odtwarzacza oraz 4-kanałowy poziomy visualizer głośności.

### 7. Analiza Jakości Struktury i Powtarzalności
Moduł [src/atari_music/ai/structure_analysis.py](src/atari_music/ai/structure_analysis.py) dostarcza obiektywnych, matematycznych metryk makrostruktury kompozycji:
* **Wskaźnik powtórzeń (`repetition_ratio`):** $1.0 - (\text{unikalne patterny} / \text{długość sekwencji})$.
* **Wskaźnik ponownego użycia materiału (`material_reuse_ratio`):** Proporcja kroków sekwencji wykorzystująca już wcześniej zaprezentowany materiał nutowy.
* **Detekcja bloków podciągów n-gramowych:** Wykrywanie najdłuższego powtórzonego podciągu (`longest_repeated_subsequence_len`) oraz odsetka sekwencji pokrytego powtórzeniami (`repeated_subsequences_coverage_pct`).
* **Automatyczna dedukcja formy:** Klasyfikacja formy kompozycji (np. *Rondo-like Episodic*, *Framed Episodic*, *Multi-Thematic Chain*) i czytelny zapis formalny (np. `INTRO - 2x A - B - A' - OUTRO`).
* **Różnorodność dziedzinowa:** Obliczanie entropii Shannona dla wysokości nut (rozpiętość melodyczna), długości nut (rytmika) oraz klas interwałów współbrzmień pionowych (harmonia).

### 8. Zaawansowana Aranżacja, Wariacje Tematyczne i Przejścia
Mechanizmy aranżacyjne przekształcające kompozycje z mechanicznych pętli w rozwijające się utwory:
* **Świadome planowanie formy (`AIFormPlanDef`, `AISectionPlanItem`):** Modele pozwalające zaplanować motyw A, kontrast B, wariacje i przejścia przed wygenerowaniem nut.
* **Wariacje tematyczne ($A'$, $B'$):** Definiowanie wariacji zachowujących rdzeń melodyczno-harmoniczny, lecz modyfikujących rytmikę, kadencję końcową, oktawę lub ornamentację.
* **Krótkie fille i przejścia (8–16 kroków):** Dynamiczne łączniki perkusyjne i melodyczne między sekcjami.
* **Dynamika faktury i breakdowny:** Sekcje o zredukowanej fakturze (np. solo bas i perkusja) budujące napięcie przed repryzą tematu głównego.
* **Nowość w drugiej połowie utworu (`structural_novelty`):** Rozwój motywów w drugiej połowie kompozycji.

### 9. Przykłady Użycia CLI dla AI Composition

```bash
# 1. Wygenerowanie kompozycji z automatyczną pętlą naprawczą (mock lub openai/deepseek):
atari-music ai-compose \
    --style "dark dungeon exploration" \
    --duration 90 \
    --channels 4 \
    --use-16bit-bass \
    --max-retries 3 \
    --provider openai \
    --output dungeon.json

# 2. Walidacja i import kompozycji JSON (eksport do WAV, ASM i POKEY IR):
atari-music import-json dungeon.json \
    --output-wav dungeon.wav \
    --output-asm dungeon.asm

# 3. Bezpośrednia kompilacja kompozycji JSON do Atari XEX (z relokacją i timerem):
atari-music build-xex dungeon.json \
    --output dungeon.xex \
    --player-address 0x4000 \
    --zp-base 0x80

# 4. Szczegółowa analiza właściwości muzycznych i sprzętowych kompozycji:
atari-music analyze dungeon.json --structure
```

### 10. Python API

```python
from atari_music.ai import (
    load_composition_json,
    generate_music_from_composition,
    build_xex_from_composition,
    request_ai_composition,
    analyze_composition,
    analyze_composition_structure,
    composition_fingerprint,
    CompositionRequest,
)

# 1. Żądanie kompozycji od providera (automatyczna obsługa .env i retry loop)
req = CompositionRequest(
    style="dark dungeon exploration",
    bpm=88,
    channels=4,
    use_16bit_bass=True,
    duration_seconds=90,
)
comp = request_ai_composition(req, provider="openai", max_retries=2)

# 2. Analiza struktury i wariacji (Etap 16/17)
struct_metrics = analyze_composition_structure(comp)
print(f"Liczba patternów: {struct_metrics.pattern_count}")
print(f"Repetition Ratio: {struct_metrics.repetition_ratio:.1%}")
print(f"Wariacje tematyczne: {struct_metrics.variation_count}")
print(f"Fille i przejścia: {struct_metrics.transition_fill_count}")
print(f"Forma: {struct_metrics.form.compact_form}")

# 3. Kompilacja do samodzielnego pliku Atari XEX z graficznym timerem
xex_path = build_xex_from_composition(
    comp,
    output_path="dungeon_full.xex",
    player_address=0x4000,
    zp_base=0x80,
)
print(f"Gotowy plik Atari XEX -> {xex_path}")
```

---

## 📁 Struktura Projektu

```text
atari-music/
├── src/atari_music/            # Rdzenny pakiet Pythona
│   ├── api.py                  # Publiczne API: generate_music(...)
│   ├── ai/                     # Warstwa AI Composition, Structure & Arrangement (Etapy 12–17)
│   │   ├── client.py           # Fasada: load_composition_json, build_xex (z timerem i VU)...
│   │   ├── analysis.py         # Analiza muzyczna (rytm, melodia, harmonia) + SHA-256 fingerprint + ground-truth time
│   │   ├── structure_analysis.py# Analiza makrostruktury, wariacji, sekwencji, formy i powtarzalności
│   │   ├── schema.py           # Pydantic schema (AICompositionDoc, AIFormPlanDef, AISectionPlanItem) + ValidationReport
│   │   ├── validation.py       # 3-poziomowa walidacja (Schema, Music, Hardware) + spójność form_plan
│   │   ├── composition.py      # Interpreter JSON -> Music IR -> POKEY IR
│   │   ├── prompts.py          # Szablony promptów systemowych i użytkownika (z wytycznymi aranżacji)
│   │   └── providers/          # Adaptery: MockAI, OpenAI / DeepSeek
│   ├── serialization.py        # Bezstratna serializacja Music IR <-> JSON
│   ├── composer_v4.py          # Silnik proceduralny Composer v4
│   ├── arrangement.py          # Warstwa aranżacji 4 kanałów
│   ├── counterpoint.py         # Silnik kontrapunktu (2. głos)
│   ├── bass_engine.py          # Silnik linii basowych
│   ├── rhythm_ornament.py      # Silnik perkusji i ornamentacji (4. głos)
│   ├── profiles.py             # Definicje 6 profili stylistycznych
│   ├── mads_exporter.py        # Eksporter danych do asemblera MADS
│   ├── pokey_synth.py          # Programowy syntezator POKEY (WAV 44.1 kHz)
│   ├── ir.py                   # POKEY Intermediate Representation (IR)
│   ├── music_ir.py             # Symbolic Music IR
│   └── cli.py                  # Interfejs wiersza poleceń (CLI)
├── config.py                   # Zarządzanie konfiguracją (.env, env vars, CLI overrides)
├── player.asm                  # Odtwarzacz muzyczny 6502 (MADS, obsługa pełnych sekwencji)
├── hardware.asm                # Ekwipacje sprzętowe POKEY, ANTIC, GTIA, PIA
├── examples/ai/                # Gotowe przykłady AI
│   ├── dungeon_dark.json       # Przykłady wzorcowe offline
│   └── live/                   # Rzeczywiste utwory z produkcyjnego LLM (DeepSeek)
│       ├── stage15/            # 37 artefaktów (8 stylów, testy powtarzalności, repair loop)
│       ├── stage15_1/          # 8 pełnometrażowych utworów 60–120s z timerem XEX
│       └── stage17/            # 8 zaawansowanych utworów z wariacjami, fillami i breakdownami
├── stage16_structure_report.md # Raport analityczny makrostruktury i powtarzalności (Etap 16)
├── stage16_structure_metrics.json # Dane metryk struktury zbioru Stage 15.1
├── stage17_arrangement_report.md # Raport i porównanie Stage 15.1 vs Stage 17 (Etap 17)
├── stage17_structure_metrics.json # Dane metryk struktury zbioru Stage 17
├── stage11_xex/                # Gotowy pakiet 6 samodzielnych plików XEX (Composer v4)
├── tools/
│   └── mads/mads.exe           # Asembler MADS v1.9.6
├── tests/
│   ├── test_pokey_music.py            # Testy silnika kompozycyjnego, playera i API
│   ├── test_ai_composition.py         # Testy warstwy AI, walidacji i serializacji
│   ├── test_analysis.py               # Testy modułu analizy muzycznej i fingerprintingu
│   ├── test_duration.py               # Testy weryfikacji czasu trwania ground-truth (60-120s)
│   ├── test_structure_analysis.py     # Testy analizy struktury, powtórzeń, wariacji i formy
│   ├── test_stage14_repair_loop.py    # Testy pętli naprawczej i lokalizacji błędów
│   ├── test_live_production.py        # Testy integracji z produkcyjnym LLM (@pytest.mark.live)
│   ├── test_config.py                 # Testy hierarchii konfiguracji i .env
│   └── test_stage13_llm_integration.py# Testy integracji LLM, Structured Outputs i monofonii
├── HISTORY.md                         # Rejestr zmian projektu
└── pyproject.toml                     # Konfiguracja pakietu Pythona
```

---

## 🧪 Uruchamianie Testów

Projekt posiada pełne pokrycie testami jednostkowymi, integracyjnymi oraz weryfikacją kompilacji asemblera:

```bash
# 1. Uruchomienie pełnego zestawu testów offline (135 testów, ~2.9 s, 0 regresji)
pytest -q

# 2. Uruchomienie opcjonalnych testów live z produkcyjnym LLM (DeepSeek / OpenAI)
pytest -m live -v

# 3. Uruchomienie automatycznej weryfikacji binarnej i relokacyjnej
python scripts/verify_stage11_runtime.py
```

Wszystkie testy weryfikują determinizm generatora, limity pamięci ($\le 2048$ B), 4-kanałową polifonię, kompilację MADS, relokowalność kodu pod różnymi adresami, poprawność połączenia kanałów dla 16-bitowego basu, 3-stopniową walidację importu AI, monofonię kanałów POKEY, pętlę naprawczą z feedbackiem, analizę harmoniczną/melodyczną oraz deterministyczny fingerprint SHA-256.

---

## 📄 Licencja

Projekt objęty licencją MIT. Kod odtwarzacza 6502 (`player.asm`) może być swobodnie wykorzystywany w projektach homebrew, grach i demach na komputery Atari 8-bit.
