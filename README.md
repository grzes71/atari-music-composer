# Atari 8-bit POKEY Music Engine & Toolkit

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform: Atari 8-bit](https://img.shields.io/badge/platform-Atari%20800%20XL%20%2F%2065%20XE-red.svg)](https://en.wikipedia.org/wiki/Atari_8-bit_family)
[![Assembler: MADS](https://img.shields.io/badge/assembler-MADS%201.9.6-green.svg)](http://mads.atari8.info/)
[![CPU: MOS 6502](https://img.shields.io/badge/cpu-MOS%206502-orange.svg)](https://en.wikipedia.org/wiki/MOS_Technology_6502)
[![Tests: 646 Passed](https://img.shields.io/badge/tests-646%20passed-brightgreen.svg)](tests/)

Kompletny, profesjonalny system generowania, aranżacji, syntezy i odtwarzania muzyki dla komputerów **Atari 8-bit (Atari 800 XL / 65 XE)** wyposażonych w układ dźwiękowy **POKEY**.

Projekt łączy proceduralną kompozycję w Pythonie z natywnym eksportem do asemblera **MADS** oraz ultra-kompaktowym, w pełni relokowalnym odtwarzaczem napisanym w czystym asemblerze **MOS 6502**.

---

## 🚀 Kompletny Pipeline Projektu

```text
┌───────────────────────────────┐        ┌───────────────────────────────────────────┐
│     Composer v4 (Python)      │        │          AI LLM Composer                  │
│  Proceduralna kompozycja      │        │       DeepSeek / OpenAI                   │
└──────────────┬────────────────┘        └─────────────┬───────────────────┬─────────┘
               │                                       │ JSON              │ Music DSL
               │                                       ▼                   ▼
               │                         ┌───────────────────────────┐ ┌─────────────┐
               │                         │  AICompositionDoc v1      │ │ DSL Parser  │
               │                         │  (Canonical SSOT)         │◄┤ (lossless)  │
               │                         └─────────────┬─────────────┘ └─────────────┘
               │                                       │
               │                                       ▼
               │                         ┌───────────────────────────┐
               │                         │  3-Tier Validator & Repair│
               │                         │  Schema + Music + Hardware│
               │                         └─────────────┬─────────────┘
               │                                       │  Composition Interpreter
               │  MusicGenerationResult                │  & Analysis Engine
               └───────────────────┬───────────────────┘
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
* **Profile brzmieniowe POKEY (Stage 9) — opcjonalne, zewnętrzne:** Renderowanie istniejącej kompozycji z użyciem prawdziwego profilu brzmienia zmierzonego przez projekt [POKEY Sound Archaeology](../pokey-sound-architecture/). Profil dostarcza wyłącznie realizację sprzętową głosu (generator/distortion, konfiguracja AUDCTL, tryb dzielnika 8/16-bit, obwiednia), a kompozycja pozostaje właścicielem nut, czasu trwania, velocity i aranżacji. Szczegóły: [docs/profile_integration.md](docs/profile_integration.md).
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
* **Kompaktowy Music DSL (Domain-Specific Language):**
  * Alternatywne, oszczędne wejście tekstowe dla LLM, redukujące zużycie tokenów o **~49.4%** względem JSON w kontrolowanych testach empirycznych (oraz do 83% przy kompresji tokenizera).
  * Bezstratny parser i serializer dwukierunkowy (`AICompositionDoc` $\leftrightarrow$ Music DSL) ze ścisłą diagnostyką składniową (linia i kolumna).
  * Pełna integracja z 3-stopniową walidacją, syntezą WAV oraz bezpośrednią kompilacją do plików Atari XEX.
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

#### D. Polecenie `ai-compose`

Generuje deklaratywną kompozycję JSON w formacie `atari-music-composition` przy użyciu modeli LLM (OpenAI / DeepSeek) lub deterministycznego mocka.

Zrewidowany system prompt zapewnia pełną swobodę artystyczną oraz autentyczność platformy Atari 8-bit / POKEY:
* **Separacja odpowiedzialności:** LLM koncentruje się wyłącznie na muzyce (melodia, harmonia, rytm, instrumentacja, forma), podczas gdy silnik aplikacji odpowiada za wyliczanie dokładnego czasu PAL 50 Hz, 3-etapową walidację i kompilację.
* **Ekonomia kanałów i rola ciszy:** Wprowadzona zasada *„Do not use all four channels merely because they are available”* oraz *„Silence is a valid compositional choice”* zapobiega przeładowaniu faktury dźwiękowej.
* **Elastyczność formalna:** Brak sztywnych szablonów sekcji — model sam dobiera formę (loop, A/B, rondo, wariacje) do stylu i nastroju.

```bash
# Wygenerowanie utworu dungeon ambient z zapisem do kanonicznego JSON:
atari-music ai-compose --style "dungeon exploration" -m dark -m mysterious --duration 20 -o dungeon.json

# Wygenerowanie utworu w kompaktowym formacie Music DSL (--format dsl):
atari-music ai-compose --style "dungeon exploration" --format dsl -o dungeon.dsl

# Streaming czystego JSON na stdout dla agentów (logi diagnostyczne kierowane na stderr):
atari-music ai-compose --style "fast arcade action" -m energetic --duration 16 > action.json
```

#### E. Polecenie `import-json`

Importuje zewnętrzny plik kompozycji `atari-music-composition` JSON, waliduje go i konwertuje na formaty produkcyjne:

```bash
atari-music import-json song.json --output-wav song.wav --output-asm song.asm
```

#### F. Polecenie `import-dsl`

Importuje kompaktowy plik Music DSL (`.dsl`), waliduje go i konwertuje na formaty produkcyjne lub kanoniczny JSON:

```bash
atari-music import-dsl song.dsl --output-wav song.wav --output-asm song.asm --output-json song.json
```

#### G. Polecenie `build-xex`

Kompiluje plik kompozycji (JSON lub Music DSL) bezpośrednio do samodzielnego pliku wykonywalnego Atari XEX:

```bash
# Dla pliku JSON:
atari-music build-xex song.json -o song.xex --format json --mads tools/mads/mads.exe

# Dla pliku Music DSL:
atari-music build-xex song.dsl -o song.xex --format dsl --mads tools/mads/mads.exe
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

### Twardy limit 2048 bajtów dotyczy odtwarzacza, a nie pliku XEX

Jedynym sztywnym limitem rozmiaru w projekcie jest **2048 bajtów na złożony kod odtwarzacza**
(kod + stan w RAM) — i jest to limit **wyłączny**: odtwarzacz o rozmiarze dokładnie 2048 bajtów
**nie przechodzi** walidacji. Odtwarzacz mierzy się konwencją `atari_music.stage15.measure_player_size`
(MADS na wrapperze `org $6000`, `-b:$6000 -o:...bin`, rozmiar pliku = kod + stan); obecnie jest to
**1016 bajtów**. Sprawdzenie: `atari_music.stage15.player_size_limit_ok()` /
`check_player_size()`; autorytatywny zapis to
[reports/stage15/player_size_analysis.json](reports/stage15/player_size_analysis.json).

Pozostałe trzy wielkości **nie** podlegają temu limitowi i nie należy ich z nim mylić:

| wielkość | limit 2048 B? |
|---|---|
| złożony odtwarzacz (kod + stan) | **tak — ściśle poniżej** |
| dane utworu (patterny, sekwencja, tabela instrumentów) | nie — osobny, znacznie mniejszy budżet POKEY IR |
| **kompletny plik `.xex`** (harness + odtwarzacz + dane) | **nie — brak jakiegokolwiek limitu** |
| segmenty w pamięci (adresy i długości `org`) | nie — ogranicza je mapa pamięci Atari (m.in. granica `$BFFF`) |

Limit 2048 B na kompletny plik XEX obowiązywał do 2026-10-09 i został zniesiony, ponieważ był
wyłącznie przybliżeniem limitu odtwarzacza (szczegóły w [HISTORY.md](HISTORY.md)). Plik `.xex`
może więc legalnie przekraczać 2048 bajtów — i kilka przykładów AI robi to.

### Walidacja układu pamięci (a nie rozmiaru pliku)

Skoro rozmiar pliku nie jest już kryterium, budowanie weryfikuje **zakresy adresów**, które
program ładujący faktycznie zapisze. Po złożeniu MADS kontener jest parsowany
(`atari_music.xex_layout.parse_xex`) i sprawdzany (`validate_xex_layout`):

* segmenty muszą leżeć w całości w **`$0400-$BFFF`** — poniżej jest strona zerowa, stos
  sprzętowy i wektory OS/DOS, których ten binarny plik sam używa (`$02E0/$02E1` RUN,
  IOCB `$0340-$03BF`, cienie `$02C6`/`$02C8`/`$02FC`, strona zerowa odtwarzacza
  `PLAYER_ZP_BASE+0..9`), a powyżej ROM jądra OS (`$C000-$CFFF`), rejestry sprzętowe
  (`$D000-$DFFF`, w tym POKEY) i ROM OS (`$E000-$FFFF`) — zgodnie z regułą „cały kod i dane
  użytkownika muszą kończyć się na `$BFFF` lub niżej";
* `$A000-$BFFF` (okno ROM BASIC-a) jest **dozwolone celowo** — projekt tam się relokuje;
* dwa segmenty nie mogą zajmować tej samej pamięci (program ładujący pisze je w kolejności
  pliku, więc późniejszy niszczy wcześniejszy);
* segmenty RUN/INIT (`$02E0-$02E3`) to protokół programu ładującego, nie dane użytkownika.

Nieudana walidacja usuwa właśnie zapisany plik `.xex` i zgłasza błąd z nazwą segmentu, jego
zakresem i powodem. Szczegóły i dowody: [docs/xex_memory_layout.md](docs/xex_memory_layout.md).

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

### 1. Konfiguracja Środowiska AI i `.env`
Projekt wspiera ujednoliconą, 4-stopniową hierarchię konfiguracji z rygorystycznymi priorytetami:
1. **Argumenty CLI** (najwyższy priorytet, np. `--provider`, `--model`, `--api-key`, `--base-url`, `--env-file`),
2. **Zmienne środowiskowe systemu** (nigdy nie są nadpisywane wartościami z `.env`),
3. **Plik `.env`** (domyślnie `.env` lub wskazany przez globalną opcję `--env-file PATH`),
4. **Wartości domyślne w kodzie** (najniższy priorytet).

W katalogu głównym projektu znajduje się plik wzorcowy [.env.example](.env.example):
```env
# Konfiguracja produkcyjna dostawcy AI
AI_PROVIDER=deepseek
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-flash
LOG_LEVEL=INFO
```

> **Kompatybilność wsteczna:** System zachowuje pełną kompatybilność z istniejącymi konfiguracjami `.env` — w przypadku braku zmiennych `AI_*` automatycznie odpytywane są zmienne legacy: `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`, `DEEPSEEK_BASE_URL` / `OPENAI_BASE_URL` oraz `DEEPSEEK_MODEL` / `OPENAI_MODEL`. Opcja CLI `--provider` pozwala w każdej chwili jawnie nadpisać wartość `AI_PROVIDER`.

> **Bezpieczeństwo:** Klucze API podlegają automatycznemu maskowaniu (`Config.masked_api_key()`) i **nigdy** nie są zapisywane w plikach JSON, kodzie asemblera, nagłówkach XEX ani raportach ewaluacyjnych.

### 2. Structured Outputs i Monofonia Kanałów POKEY
- **Natywne Structured Outputs**: Provider wykorzystuje schema-constrained JSON oparty bezpośrednio na modelach Pydantic (`AICompositionDoc`), gwarantując poprawność typów bez konieczności czyszczenia tekstu markdown.
- **Ścisła monofonia POKEY**: POKEY posiada 4 fizycznie monofoniczne kanały. Walidator odrzuca jakiekolwiek nakładanie się nut (`NOTE_OVERLAP`) na tym samym kanale, podając dokładny krok, kanał i konfliktujące wysokości.
- **Sprzężenie 16-bitowego basu**: Przy fladze `use_16bit_bass: true` silnik sprzęga Kanały 1 i 2 (`AUDCTL = $10`, czyli join 1+2 przy zegarze 64 kHz), rezerwując Kanał 2 jako slave dzielnika częstotliwości. Nie należy mylić tej konfiguracji z profilem archeologicznym PAIR (`AUDCTL = $50` — ten sam join przy zegarze 1.79 MHz); to dwa różne strojenia tej samej nuty (patrz [docs/profile_integration.md](docs/profile_integration.md)).

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
# 1. Wygenerowanie kompozycji (JSON lub Music DSL) z automatyczną pętlą naprawczą:
atari-music ai-compose \
    --style "dark dungeon exploration" \
    --duration 90 \
    --channels 4 \
    --use-16bit-bass \
    --max-retries 3 \
    --provider openai \
    --format json \
    --output dungeon.json

# Wersja w kompaktowym formacie Music DSL (--format dsl):
atari-music ai-compose --style "dark dungeon exploration" --format dsl -o dungeon.dsl

# 2. Walidacja i import kompozycji JSON (eksport do WAV, ASM i POKEY IR):
atari-music import-json dungeon.json \
    --output-wav dungeon.wav \
    --output-asm dungeon.asm

# 3. Walidacja i import kompozycji Music DSL (eksport do WAV, ASM, IR lub kanonicznego JSON):
atari-music import-dsl dungeon.dsl \
    --output-wav dungeon.wav \
    --output-asm dungeon.asm \
    --output-json canonical_dungeon.json

# 4. Bezpośrednia kompilacja kompozycji (JSON lub DSL) do Atari XEX (z relokacją i timerem):
atari-music build-xex dungeon.json --format json --output dungeon.xex
atari-music build-xex dungeon.dsl --format dsl --output dungeon.xex

# 5. Szczegółowa analiza właściwości muzycznych i sprzętowych kompozycji:
atari-music analyze dungeon.json --structure
```

### 10. Python API

```python
from atari_music.ai import (
    load_composition_json,
    load_composition_dsl,
    parse_music_dsl,
    export_music_dsl,
    generate_music_from_composition,
    build_xex_from_composition,
    request_ai_composition,
    analyze_composition,
    analyze_composition_structure,
    composition_fingerprint,
    CompositionRequest,
)

# 1. Żądanie kompozycji od providera (obsługa JSON lub format="dsl")
req = CompositionRequest(
    style="dark dungeon exploration",
    bpm=88,
    channels=4,
    use_16bit_bass=True,
    duration_seconds=90,
    format="dsl",
)
comp = request_ai_composition(req, provider="openai", max_retries=2)

# 2. Bezstratna konwersja do / z Music DSL
dsl_text = export_music_dsl(comp)
comp_from_dsl = load_composition_dsl(dsl_text)

# 3. Analiza struktury i wariacji
struct_metrics = analyze_composition_structure(comp)
print(f"Liczba patternów: {struct_metrics.pattern_count}")
print(f"Repetition Ratio: {struct_metrics.repetition_ratio:.1%}")
print(f"Forma: {struct_metrics.form.compact_form}")

# 4. Kompilacja do samodzielnego pliku Atari XEX z graficznym timerem
xex_path = build_xex_from_composition(
    comp,
    output_path="dungeon_full.xex",
    player_address=0x4000,
    zp_base=0x80,
)
print(f"Gotowy plik Atari XEX -> {xex_path}")
```

### 11. Kompaktowy Music DSL i Wyniki Benchmarku LLM

Projekt oferuje kompaktowy, tekstowy format **Music DSL** jako alternatywny frontend dla modeli LLM. Kanonicznym źródłem prawdy (SSOT) pozostaje `AICompositionDoc` / schemat JSON.

Szczegółowa specyfikacja składni znajduje się w [docs/music_dsl.md](docs/music_dsl.md).

Kontrolowany eksperyment empiryczny (100 prób: 5 kategorii $\times$ 2 formaty $\times$ 10 powtórzeń na modelu `deepseek-flash`, raport w [benchmark_results/run_1790692314/report.md](benchmark_results/run_1790692314/report.md)) wykazał:
* **49.4% redukcji tokenów API:** Średnio 13 913 tokenów na udany utwór w DSL vs 27 512 tokenów w JSON.
* **100% finalnej skuteczności walidacji:** Oba formaty osiągnęły 100% poprawności sprzętowej i muzycznej.
* **Pełną równoważność muzyczną:** Identyczna złożoność polifoniczna, różnorodność interwałowa i gęstość rytmiczna.

---

## 📁 Struktura Projektu

```text
atari-music/
├── src/atari_music/            # Rdzenny pakiet Pythona
│   ├── api.py                  # Publiczne API: generate_music(...)
│   ├── ai/                     # Warstwa AI Composition, Structure & Arrangement
│   │   ├── client.py           # Fasada: load_composition_json, load_composition_dsl, build_xex...
│   │   ├── dsl.py              # Music DSL: parser (parse_music_dsl) i serializer (export_music_dsl)
│   │   ├── analysis.py         # Analiza muzyczna (rytm, melodia, harmonia) + SHA-256 fingerprint
│   │   ├── structure_analysis.py# Analiza makrostruktury, wariacji, sekwencji, formy i powtarzalności
│   │   ├── schema.py           # Pydantic schema (AICompositionDoc) + ValidationReport
│   │   ├── validation.py       # 3-poziomowa walidacja (Schema, Music, Hardware)
│   │   ├── composition.py      # Interpreter JSON/DSL -> Music IR -> POKEY IR
│   │   ├── prompts.py          # Szablony promptów systemowych i użytkownika (JSON & DSL)
│   │   └── providers/          # Adaptery: MockAI, OpenAI / DeepSeek
│   ├── serialization.py        # Bezstratna serializacja Music IR <-> JSON
│   ├── composer_v4.py          # Silnik proceduralny Composer v4
│   ├── arrangement.py          # Warstwa aranżacji 4 kanałów
│   ├── counterpoint.py         # Silnik kontrapunktu (2. głos)
│   ├── bass_engine.py          # Silnik linii basowych
│   ├── rhythm_ornament.py      # Silnik perkusji i ornamentacji (4. głos)
│   ├── profiles.py             # Definicje 6 profili stylistycznych
│   ├── sound_profiles/         # Integracja profili brzmieniowych POKEY (Stage 9 / 9B)
│   │   ├── bank.py             # Wczytywanie, weryfikacja fingerprintów i statusów banku
│   │   └── binding.py          # Zewnętrzne powiązanie instrument -> profil (realizacja sprzętowa)
│   ├── mads_exporter.py        # Eksporter danych do asemblera MADS
│   ├── pokey_synth.py          # Programowy syntezator POKEY (WAV 44.1 kHz)
│   ├── stage9c.py              # Eksperyment odsłuchowy Stage 9C (pakiet blind, analiza wyników)
│   ├── stage9d.py              # Analiza wyników odsłuchu Stage 9D (korelacje, kategorie, shortlista, werdykt)
│   ├── stage9e.py              # Diagnoza luki percepcyjnej Stage 9E (mapa ścieżek, grupy duplikatów, brakujące zdolności)
│   ├── stage10a.py             # Eksperyment ponownego przypisania profili Stage 10A (wybór z dowodów słuchowych, pakiet zaślepiony)
│   ├── stage10b.py             # Eksperyment przeniesienia konturu głośności Stage 10B (mapowanie, dowód perturbacji, regresja, pakiet zaślepiony)
│   ├── ir.py                   # POKEY Intermediate Representation (IR)
│   ├── music_ir.py             # Symbolic Music IR
│   └── cli.py                  # Interfejs wiersza poleceń (CLI)
├── docs/
│   ├── music_dsl.md            # Specyfikacja i gramatyka Music DSL
│   └── profile_integration.md  # Integracja profili POKEY: mechanizm, ścieżki WAV/XEX, błędy
├── benchmark_results/          # Wyniki kontrolowanych eksperymentów LLM (JSON vs DSL)
│   └── run_1790692314/         # Raport 100 prób (report.md, summary.json, raw_trials.json)
├── scripts/
│   ├── benchmark_dsl_vs_json.py# Statyczny benchmark tokenizacji i kompresji DSL
│   └── benchmark_llm_formats.py# Runner 100-próbowego eksperymentu LLM
├── config.py                   # Zarządzanie konfiguracją (.env, env vars, CLI overrides)
├── player.asm                  # Odtwarzacz muzyczny 6502 (MADS, obsługa pełnych sekwencji)
├── hardware.asm                # Ekwipacje sprzętowe POKEY, ANTIC, GTIA, PIA
├── examples/ai/                # Gotowe przykłady AI
├── examples/sound_profile_listening/  # Stage 9C: pakiet odsłuchowy (index.html, audio/, manifest.json, szablony CSV)
├── examples/sound_profile_rebinding_10a/      # Stage 10A: pakiety trzech wersji sześciu utworów i pary zaślepione
├── examples/sound_profile_volume_contour_10b/ # Stage 10B: trzy warianty (A/B/C) profili i utworów, pary zaślepione
├── stage11_xex/                # Gotowy pakiet 6 samodzielnych plików XEX (Composer v4)
├── tools/
│   └── mads/mads.exe           # Asembler MADS v1.9.6
├── tests/
│   ├── test_cli.py                    # Testy interfejsu CLI (import-json, import-dsl, build-xex)
│   ├── test_dsl.py                    # Testy parsera i serializera Music DSL
│   ├── test_pokey_music.py            # Testy silnika kompozycyjnego, playera i API
│   ├── test_ai_composition.py         # Testy warstwy AI, walidacji i serializacji
│   ├── test_analysis.py               # Testy modułu analizy muzycznej i fingerprintingu
│   ├── test_duration.py               # Testy weryfikacji czasu trwania ground-truth (60-120s)
│   ├── test_structure_analysis.py     # Testy analizy struktury, powtórzeń, wariacji i formy
│   ├── test_stage14_repair_loop.py    # Testy pętli naprawczej i lokalizacji błędów
│   ├── test_sound_profiles.py         # Testy integracji profili POKEY (bank, binding, WAV/XEX)
│   ├── test_sound_profile_library.py  # Pełna biblioteka 67 profili: inwentarz, statusy, regresja Stage 9
│   ├── test_stage9c.py                # Eksperyment odsłuchowy: bodziec, poziomy, program A/B, determinizm, analiza
│   ├── test_stage9d.py                # Analiza wyników odsłuchu: statystyki, mapowanie, korelacje, werdykt, determinizm
│   ├── test_stage9e.py                # Diagnoza luki: rejestrowanie odczytów, grupy duplikatów, bierne pola, werdykt, immutability
│   ├── test_stage10a.py               # Ponowne przypisanie: odzyskanie sześciu utworów, reguła decyzji, kompatybilność, zaślepienie, immutability
│   ├── test_stage10b.py               # Kontur głośności: kontrakt mapowania, kwalifikacja profili, dowód perturbacji, regresja bajtowa, pakiet
│   ├── data/sound_profiles/           # Przykład integracji: kompozycja DSL, powiązanie, pełny bank 67 profili
│   ├── test_live_production.py        # Testy integracji z produkcyjnym LLM (@pytest.mark.live)
│   ├── test_config.py                 # Testy hierarchii konfiguracji i .env
│   └── test_stage13_llm_integration.py# Testy integracji LLM, Structured Outputs i monofonii
├── HISTORY.md                         # Rejestr zmian projektu
└── pyproject.toml                     # Konfiguracja pakietu Pythona
```

---

## 🎛️ Profile Brzmieniowe POKEY (integracja z POKEY Sound Archaeology)

> Kompozycja opisuje intencję muzyczną. Profil opisuje realizację na POKEY.

Projekt potrafi wyrenderować **istniejącą** kompozycję przy użyciu profilu brzmienia zmierzonego z klasycznego utworu Atari przez projekt [POKEY Sound Archaeology](../pokey-sound-architecture/). Profile są **zewnętrzne i opcjonalne** — warstwa kompozycji (DSL, `AICompositionDoc`, prompty, struktury muzyczne) nie wie o ich istnieniu i nie zmieniła się.

```text
kompozycja (DSL / JSON)            ← nuty, rytm, tempo, forma, velocity, rola instrumentu
      ↓  parse / walidacja / Music IR
   POKEY IR (IRSong)
      ↓  profile binding           ← profil wchodzi TUTAJ i tylko tutaj
   POKEY IR świadomy profilu
      ├──────────────┐
      ▼              ▼
   WAV           MADS → XEX
```

**Co dostarcza profil:** generator (distortion), konfigurację AUDCTL (zegar/sprzężenie), tryb dzielnika (8-bit / sprzężona para 16-bit) oraz kształt obwiedni.
**Co pozostaje kompozycji:** wysokość nuty (profil dostarcza zegar, nie nutę), czas trwania, przerwy, velocity (profil nigdy nie nadpisuje dynamiki), aranżacja i tożsamość instrumentu.

### Bank profili i powiązania

Bank to katalog zapisany przez projekt archeologii (`registry.json` + `profiles/`). Powiązanie instrumentu z profilem to **osobny plik**, poza kompozycją:

```json
{
  "schema": "atari-music/sound-profile-binding/1",
  "bank": "bank",
  "instruments": { "bass": "pokey_ref_3627798b", "lead": "pokey_ref_a8c81a84" }
}
```

W repozytorium dostępne są dwa banki o różnych rolach:

| | bank demonstracyjny | pełny bank badawczy |
| :--- | :--- | :--- |
| gdzie | `examples/sound_profiles/` | `tests/data/sound_profiles/bank/` |
| rozmiar | 4 profile (proof-of-integration z Stage 9) | **67 profili** — cała opublikowana biblioteka |
| statusy | 4 × `PLAYABLE` | 22 `PLAYABLE`, 39 `PLAYABLE_WITH_LIMITATION`, 6 `MEASUREMENT_ONLY` |

**67 profili to nie 67 rekomendowanych instrumentów.** To kompletna biblioteka techniczna. Profile, których status mówi „opisuje ciszę" (`MEASUREMENT_ONLY`), są publikowane i możliwe do wglądu, ale **odrzucane przy próbie renderowania** (`PROFILE_STATUS_NOT_RENDERABLE`) — nigdy nie są cicho zastępowane domyślnym dźwiękiem. Status jest zapisany w `registry.json` razem z kodami przyczyn. Ostateczna selekcja palety brzmień to osobny, późniejszy etap.

### Wynik rzeczywistego odsłuchu (Stage 9D)

Stage 9C zbudował zaślepiony eksperyment, Stage 9D przeanalizował oddane odpowiedzi (`analyze-listening-test-9d`). Pełny raport: [docs/stage9d_human_listening_results.md](docs/stage9d_human_listening_results.md); wyniki maszynowe: `reports/stage9d/`.

Cztery ustalenia, z których jedno jest negatywne:

1. **Biblioteka jest słyszalnie mniejsza niż liczba profili.** 61 renderowalnych profili daje **37 różnych sygnałów audio** — 24 profile renderują **bajtowo identyczny** dźwięk jak inny profil (grupy po 10, 6, 4, 4, 3, 3). Różnią się gestem, którego player nie odtwarza.
2. **Powiązanie profili z prawdziwymi utworami pogorszyło wynik w tym teście.** Na sześć utworów domyślne instrumenty kompozytora wygrały 5, wersja z profilami 0 (jeden remis), jednogłośnie na wszystkich trzech pytaniach. Sześć utworów to nie populacja — ale kierunek jest jednoznaczny i dlatego końcowa odpowiedź Stage 9D brzmi **NO**.
3. **Metryka podobieństwa jest ślepa na poziom.** Cosine distance na znormalizowanym spektrum daje ≈ 0.00 zarówno dla pary bajtowo identycznej, jak i dla pary różniącej się o 12 dB RMS — a słuchacz się z tym nie zgadzał.
4. **Słuchacz rozpoznaje rodzinę generatora, metryka widzi spektrum.** Wszystko, co zostało nazwane „noisy", to `$0`/`$8`; wszystko „clean" to `$A`/`$C` — zbiory rodzin są rozłączne, a flatness ich nie rozdziela.

### Użycie

```bash
# WAV + ASM z profilem (VOICE i PAIR w jednym przebiegu)
python -m atari_music import-dsl tests/data/sound_profiles/vaults_of_nhyrmeth.dsl \
    --sound-bank tests/data/sound_profiles/bank \
    --profile-bindings tests/data/sound_profiles/vaults_binding.json \
    --output-wav examples/sound_profiles/vaults_profile.wav \
    --output-asm examples/sound_profiles/vaults_profile.asm

# XEX z tej samej, świadomej profilu reprezentacji
python -m atari_music build-xex tests/data/sound_profiles/vaults_of_nhyrmeth.dsl --format dsl \
    -o examples/sound_profiles/vaults_profile.xex \
    --sound-bank tests/data/sound_profiles/bank \
    --profile-bindings tests/data/sound_profiles/vaults_binding.json
```

### Zasady, które są egzekwowane

* **Bez powiązania nic się nie zmienia** — WAV, ASM i XEX są identyczne jak przed tą funkcją (potwierdzone przez porównanie artefaktów przed/po).
* **Dokładne `profile_id`** — brak dopasowań rozmytych, brak „najbliższego" profilu, brak cichego podstawienia; nieznany identyfikator kończy się błędem.
* **Weryfikacja fingerprintu** — profil, którego zawartość nie zgadza się z `playable_fingerprint` w rejestrze, nie zostanie wczytany.
* **Status profilu jest egzekwowany** — profil ze statusem `MEASUREMENT_ONLY` (opisujący ciszę) jest odrzucany z `PROFILE_STATUS_NOT_RENDERABLE`; nieznany status z `PROFILE_STATUS_UNKNOWN`. Nigdy nie ma cichego powrotu do dźwięku domyślnego.
* **`$50` ≠ `$10`** — profil PAIR z zegarem 1.79 MHz (`$50`, offset dzielnika `+7`) nie jest konwertowany na wewnętrzną konwencję 16-bitowego basu (`$10`, offset `+1`); to różne wysokości tej samej nuty.
* **Distortion jako nibble → bajt AUDC** — `"$A"` zamieniane jest na `0xA0` (generator w bitach 7..5), nigdy kopiowane dosłownie jako `0x0A`.
* **Kanał to decyzja kompozycji** — kanał źródłowy profilu jest wyłącznie proweniencją; sprawdzane jest, czy wybrany przez kompozycję kanał może udźwignąć konfigurację profilu.
* **Brak cichej degradacji** — konflikt (AUDCTL, para kanałów, distortion, obwiednia) jest błędem z kodem, nie przybliżeniem.
* **Determinizm** — te same wejścia dają bajtowo identyczne wyjście.

Pełny opis (mechanizm, rejestr, VOICE, PAIR, pitch, volume, alokacja kanałów, ścieżki WAV/XEX, kody błędów, kompatybilność wsteczna, przykład i ograniczenia): [docs/profile_integration.md](docs/profile_integration.md).

### 🔊 Eksperyment odsłuchowy Stage 9C (czy te brzmienia są coś warte?)

Biblioteka mówi, **co da się wyrenderować**. Nie mówi, **co warto zachować** — to pytanie percepcyjne i biblioteka nie może na nie odpowiedzieć. Stage 9C buduje eksperyment, który zadaje je człowiekowi, i niczego nie rozstrzyga za niego.

```bash
# 1. Zbuduj kompletny, samodzielny pakiet odsłuchowy (bank tylko do odczytu)
python -m atari_music.cli prepare-listening-test-9c \
    --package-dir examples/sound_profile_listening \
    --sound-bank tests/data/sound_profiles/bank \
    --songs-dir examples/songs

# 2. Otwórz examples/sound_profile_listening/index.html, posłuchaj i wypełnij trzy CSV

# 3. Analiza wyników -> reports/stage9c/
python -m atari_music.cli analyze-listening-test-9c \
    --package-dir examples/sound_profile_listening
```

Pakiet (`examples/sound_profile_listening/`) działa w przeglądarce — **bez Pythona, bez serwera, bez internetu**:

| część | co porównuje | pytania |
| :--- | :--- | :--- |
| 1 | pojedyncze profile, 61 bodźców | wyrazistość, użyteczność, „atariowość", własny opis słowami, opcjonalna pewność |
| 2 | dwa profile, 30 prób A/B w warstwach (podobne / odległe / ta sama rodzina generatora / różne rodziny / ta sama piosenka źródłowa / różne piosenki) | podobieństwo, preferencja, różnica charakteru, komentarz |
| 3 | prawdziwy utwór: domyślny vs związany z profilem, 6 par | lepsze brzmienie, więcej charakteru, bardziej przekonujący Atari, wielkość różnicy |

**Co jest trzymane stałe:** każdy profil realizuje **ten sam** 32-krokowy frazowany bodziec (ten sam czas, velocity, wysokość, kanał 1 — dla `PAIR` ta sama fraza ze złączem 1+2); każdy bodziec jest sprowadzany do tego samego szczytu (−0,92 dBFS) jednym wzmocnieniem, bez kompresji, EQ i clippingu, a oryginalny i końcowy peak **oraz** RMS każdej próbki są zapisane, więc głośność pozostaje zmierzoną właściwością, a nie założeniem. Próby A/B używają **tych samych** plików bodźców, a pary utworów — jednego wspólnego wzmocnienia i identycznego wycinka, więc kompozycja po obu stronach jest nietknięta.

**Czego to nie rozstrzyga:** żaden gest nie jest wymyślany (player nie ma makra na kanał — profil z konturem słychać jako dźwięk statyczny); nic nie jest przemianowywane, rankingowane ani wybierane. Raport podaje mediany, rozkłady, korelacje, głosy i **słowa słuchacza**, oraz grupy kandydatów z jawnie podanymi progami — i odmawia ogłoszenia finalnej palety. Zaślepienie jest wymuszone konstrukcyjnie: interfejs, nazwy plików i README nigdy nie zawierają `profile_id`, piosenki źródłowej, rodziny generatora, AUDCTL, zakresu ani statusu; mapowanie istnieje wyłącznie w `manifest.json`.

**Analiza wyników:**

```bash
python -m atari_music.cli analyze-listening-test-9d \
    --package-dir examples/sound_profile_listening \
    --docs-dir docs --reports-dir reports/stage9d
```

Wynik: `docs/stage9d_human_listening_results.md` oraz maszynowo `reports/stage9d/{profile_scores.json, profile_scores.csv, correlations.json, hypotheses.json, categories.json, coverage.json, shortlist.json, verdict.json}`. Analiza jest deterministyczna, nie modyfikuje ani odpowiedzi, ani eksperymentu, i **nie wybiera biblioteki** — odpowiada, czy dane uzasadniają przejście do selekcji.

### Diagnoza różnicy percepcyjnej (Stage 9E)

Stage 9D powiedział, że 61 profili brzmi jak 37 dźwięków, a powiązanie z utworami przegrało 5–0. Stage 9E diagnozuje **dlaczego** — nie zmieniając niczego. Zamiast czytać kod, mierzy pipeline:

```bash
python -m atari_music.cli analyze-listening-test-9e
```

Wynik: `docs/stage9e_perceptual_renderer_gap.md` oraz maszynowo `reports/stage9e/{pipeline_fields.json, duplicate_groups.json, profile_diffs.json, information_loss.json, part_c_diagnostics.json, missing_capabilities.json, verdict.json}`.

Jak to jest mierzone, a nie zakładane: dokument profilu jest opakowany w mapowanie, które rejestruje **każdą ścieżkę**, jaką naprawdę czyta `apply_profile_binding`; każde pole IR jest zaburzane, żeby sprawdzić, które klatki zmienia; każda kolumna klatki jest zerowana, żeby sprawdzić, czy zmienia się dźwięk; a własny re-render jest porównywany **bajt po bajcie** ze bodźcem, który słyszał człowiek (**61 z 61 identycznych**). Diagnoza **odmawia uruchomienia**, jeśli się nie zgadza — jej twierdzenia dotyczą więc dokładnie tego pipeline'u, który wygenerował eksperyment.

Trzy zmierzone fakty:

1. **Powiązanie czyta 13 z 232 udokumentowanych ścieżek.** `_rebuild_song` zapisuje na instrumencie sześć wartości: nibble generatora, trzy liczby klatek obwiedni, poziom sustain i AUDCTL. Kroki 5–6 nigdy nie widzą dokumentu profilu. Zmierzony kontur wysokości, kontur głośności, modulacja, zmiany generatora w środku dźwięku i cała proweniencja są obecne w dokumencie i nieczytane przez nic.
2. **Wszystkie 6 grup duplikatów ginie dokładnie na tej granicy.** W każdej grupie dokumenty się różnią (125–691 ścieżek), a powiązany IR jest już identyczny — więc klatki i WAV muszą być identyczne. Klasyfikacja: `representation_duplicate` w 6 z 6 grup (30 profili); **żadna grupa nie wymagała wyjaśnienia przez renderer**. Bajtowo identyczny WAV **nie** oznacza więc profilu zbędnego — jest zbędny *na dziś*.
3. **Przegrana w Part C nie jest artefaktem głośności.** Obie strony każdej pary były renderowane przy **jednym wspólnym wzmocnieniu** (tak jak w Stage 9C); strona z profilami nie była głośniejsza (mediana różnicy RMS −2,39 dB). Powiązanie zastąpiło każdemu instrumentowi generator i/lub obwiednię, więc strony różnią się barwą i artykulacją — a instrumenty kompozytora, projektowane pod ten konkretny utwór, wygrały. To luka **interpretacji muzycznej**, i dlatego pierwszym rekomendowanym krokiem jest ponowne powiązanie sześciu utworów na podstawie dowodów ze słuchania, a nie zmiana silnika.

Kolejność wniosku: luka **reprezentacji** (największa), **interpretacji muzycznej** (druga), a **renderera** tylko marginalna — kompilator klatek używa każdego pola, które powiązanie zapisuje, poza kilkoma zmierzonymi jako bierne (`envelope.decay_frames` nie zmienia żadnej klatki dla 8 z 61 profili). Zdolności, które zamknęłyby pierwszą lukę, są uszeregowane dowodowo w §12 raportu (najpierw zmierzony kontur głośności i kontur wysokości) i **żadna nie jest zaimplementowana**: zmieniłyby to, co słyszy człowiek, unieważniając obecny ranking percepcyjny.

Werdykt: **DIAGNOSTICALLY_COMPLETE** — 6 grup duplikatów, 6 wyjaśnionych, 0 niewyjaśnionych.

### Eksperyment ponownego przypisania profili (Stage 10A)

Stage 9E pokazał, że powiązania w `examples/songs/` wybrano **według rodziny generatora**, a nie według tego, co powiedział słuchacz. Stage 10A zadaje więc pytanie w czystej postaci: **czy samo lepsze przypisanie profili poprawia całe utwory**, przy niezmienionym rendererze, kompozycji i kompozytorze?

```bash
python -m atari_music.cli prepare-rebinding-10a
```

Wynik: zaślepiony pakiet `examples/sound_profile_rebinding_10a/`, raport [docs/stage10a_rebinding_experiment.md](docs/stage10a_rebinding_experiment.md) oraz `reports/stage10a/{songs.json, rebinding.json, machine_comparison.json, verification.json}`.

Jak to jest trzymane w ryzach:

1. **Sześć utworów to dokładnie te same sześć utworów Part C**, wzięte z manifestu Stage 9C — a nie z nazw plików. Jeśli plik powiązania nie zgadza się już z manifestem, budowa **odmawia** uruchomienia: edytowane powiązanie po cichu zmieniłoby znaczenie słowa „stary”.
2. **Zmienia się wyłącznie przypisanie.** Te same bajty kompozycji, to samo tempo, nuty, czasy, velocity, kanały, renderer, sample rate, okno wycinka i wzmocnienie. Trzy wersje na utwór: instrumenty kompozytora, stare powiązanie, nowe powiązanie.
3. **Kompatybilność jest mierzona, nie zakładana.** Każdy kandydat przechodzi przez `apply_profile_binding`; odmowa usuwa go z puli. Ograniczenia z §2–§8 są spełnione z definicji, bo pyta o nie ta sama warstwa, która ich pilnuje.
4. **Strona domyślna i stara są porównane bajt po bajcie z bodźcami Stage 9C** (i wzmocnienie zgadza się z zapisanym w manifeście). Bez tego „re-test” nie byłby porównywalny z 5–0; z tym — jest. Jeśli kiedykolwiek się rozjadą, budowa się zatrzymuje.
5. **Zmiana wymaga dowodu ze słuchania.** Nowy dźwięk musi być oceniony **nie niżej na każdej skali** i wyżej na co najmniej jednej: o dwa punkty na jednej skali albo o jeden punkt na dwóch naraz. Pojedynczy punkt różnicy uznano za szum — bo Stage 9D zmierzył, jak bardzo słuchacz różni się od siebie samego. Ścieżki bez takiego kandydata zostają przy starym profilu i raport mówi które i dlaczego.

**Czego ten etap świadomie nie robi:** nie liczy zwycięzcy z metryk maszynowych i nie ogłasza, że ponowne przypisanie jest lepsze — to rozstrzygnie dopiero odsłuch. Wynik: 10 z 21 kanałów zmienionych w 5 utworach, 1 utwór bez zmian, 18 zaślepionych porównań (6 utworów × 3 pary: domyślne-vs-nowe, stare-vs-nowe i kontrolne domyślne-vs-stare).

### Przeniesienie konturu głośności (Stage 10B)

Stage 9E nazwał pierwszą brakującą zdolność: archeologia **mierzy**, jak głośność zmieniała się wewnątrz dźwięku (`gesture.volume.runs` — bezwzględne poziomy AUDC, jedna próbka na klatkę VBL), a odtwarzacz to **wyrzuca** (58 z 67 profili ma zmierzony kontur, wszystkie z `playable.gesture.volume.enabled: false`). Stage 10A pokazał, że samo przypisanie profili nic nie poprawia. Stage 10B pyta więc wąsko: **czy zmierzony kontur da się przenieść do istniejącego IR i kompilatora klatek — i czy transfer zmienia dźwięk w kierunku, który pomiar opisuje?**

```bash
python -m atari_music.cli prepare-volume-contour-10b
```

Wynik: zaślepiony pakiet `examples/sound_profile_volume_contour_10b/`, raport [docs/stage10b_volume_contour_experiment.md](docs/stage10b_volume_contour_experiment.md) oraz `reports/stage10b/{profiles.json, subjects.json, transfer.json, perturbation.json, regression.json, verification.json}`.

Jak to jest trzymane w ryzach:

1. **Jedna ścieżka renderowania, żadnego równoległego silnika.** Kontur jest polem `IRInstrument.volume_contour` i jednym mnożeniem w `_render_note_to_frames`; kompilator klatek używa go dokładnie tam, gdzie już liczy głośność na klatkę (dolny nibble AUDC). WAV i XEX nadal pochodzą z tej samej reprezentacji.
2. **Velocity pozostaje suwerenne.** Wzór `floor(volumes[i] * contour[i % span] / max(contour) + 0.5)` może tylko **tłumić** (współczynnik ≤ 1): kontur nie podgłośni, nie przesteruje i nie wycieknie z niego bezwzględna głośność źródła. Kontur statyczny jest dokładnym no-op-em.
3. **Dowód perturbacji, nie statystyka.** Dla każdego testowanego profilu porównywane są trzy rendery tej samej kompozycji i tego samego powiązania: bez konturu, z konturem i z konturem **odwróconym**. Sprawdzane jest, że różni się **dokładnie jedna kolumna** (AUDC kanału, który brzmi; dla pary 16-bit AUDC2), że nibble generatora się nie zmienił, że strumień klatek równa się **dokładnie arytmetyce mapowania**, oraz że głośność w audio (RMS na klatkę) idzie za strumieniem objętości (mediana korelacji 0,97).
4. **Regresja bajtowa.** Przy wyłączonej zdolności wszystkie **18 opublikowanych renderów Stage 10A** (6 utworów × 3 wersje) odtwarzają się **bajt po bajcie**. Żaden plik golden nie został zaktualizowany.
5. **Uczciwa granica: XEX.** Eksporter MADS publikuje tabelę nut, a `player.asm` sam buduje obwiednię na klatkę — więc utwór z konturem jest **odrzucany** (`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`), a nie wyeksportowany jako coś, co zagrałoby inaczej niż to, czego słuchano.
6. **Kontur, który bramkuje, nie jest przenoszony.** Poziom 0 w pomiarze znaczy „nic nie brzmiało” — to timing, nie głośność. Przeniesienie go wstawiłoby bramkowanie cudzej aranżacji do kompozycji, która ma własne nuty. Dlatego każdy kanał, na którym kontur **odmówiono**, jest nazwany w raporcie (3 kanały w 2 utworach), a nie przybliżony.

**Czego ten etap świadomie nie robi:** nie ogłasza zwycięzcy i nie twierdzi, że kontur „rozwiązuje problem profili”. Werdykt to **INCONCLUSIVE**: udowodnione jest, że transfer działa (8 z 8 profili, jedna kolumna, dokładna arytmetyka, regresja bajtowa), natomiast to, czy słuchacz go słyszy i czy brzmi lepiej, rozstrzygnie dopiero pakiet odsłuchowy — 18 zaślepionych par (14 B-vs-C + 4 kontrolne A-vs-C), w tym te same sześć utworów co w Stage 10A. Osobno zmierzono, że **najbardziej ruchliwe kontury w banku (do 119 zmian poziomu na 147 klatek) to dokładnie te, które zawierają ciszę** — klasa tremolo zostaje więc nietknięta i jest to ograniczenie zakresu tego etapu, nie biblioteki.

---

## 🧪 Uruchamianie Testów

Projekt posiada pełne pokrycie testami jednostkowymi, integracyjnymi oraz weryfikacją kompilacji asemblera:

```bash
# 1. Uruchomienie pełnego zestawu testów offline (646 testy, 2-7 min, 0 regresji)
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
