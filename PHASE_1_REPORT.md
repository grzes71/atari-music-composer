# FAZA 1 – RAPORT Z KRYTYCZNYCH POPRAWEK SILNIKA AUDIO

**Projekt:** Atari Music Composer (POKEY 6502 / Python)  
**Data:** 2026-11-15  
**Zakres:** Naprawa obwiedni ADSR, naprawa wyciszania kanałów POKEY (`$00` zamiast `$01`), rozbudowa testów regresyjnych (MADS + `py65` + ASAP 8.0.0) bez zmian w formacie IR, SAP ani publicznym API generatora.

---

## 1. Cel i zachowane granice Fazy 1

Celem Fazy 1 było usunięcie krytycznych błędów poprawności w produkcyjnym silniku audio przed wprowadzaniem nowych technik syntezy w kolejnych fazach:

1. Zastąpienie błędnej, dwuskokowej i niespójnej czasowo obwiedni ADSR w pełni liniowym i przewidywalnym mechanizmem sprzętowym 6502 + referencją Pythona.
2. Usunięcie błędu zapisu wartości `$01` zamiast `$00` do rejestrów `AUDC1..AUDC4` podczas wyciszania kanałów maską `ch_mute_mask`.
3. Zabezpieczenie obu mechanizmów deterministycznymi testami regresyjnymi opartymi o realną asemblację MADS, emulację 6502 (`py65`) oraz weryfikację na plikach `SAP TYPE B` i emulatorze POKEY ASAP 8.0.0.

**Ograniczenia projektowe zachowane w 100%:**
- Brak zmian formatu IR (`src/atari_music/ir.py`) i wersji tabeli instrumentów (`SONG_FORMAT_VERSION = 1`).
- Brak zmian nagłówka/kontenera SAP i publicznego API generatora muzyki.
- Brak nowych typów instrumentów, `IRMacroStep`, vibrato, portamento ani obwiedni wysokości dźwięku (pitch envelope).
- Ścisła zgodność z zestawem rozkazów MOS 6502 (brak rozkazów CMOS 65C02/65816; jawne `CLC`/`SEC` przed `ADC`/`SBC`; strona zerowa wyłącznie `$80..$89`).
- Pełna identyczność bajtowa między `player.asm` i `src/atari_music/asm/player.asm`.

---

## 2. Naprawa obwiedni ADSR (`player.asm`, `pokey_hw.py`)

### 2.1. Zdiagnozowane błędy przed Fazą 1 (`HEAD:player.asm`)
- **Attack:** Zamiast rampy liniowej stosował stały skok dwupoziomowy `(peak >> 1) | 1` przez pierwsze `attack - 1` ramek, a na ostatniej ramce skakał do `peak` (dla `attack=6, peak=14` dawał `[7, 7, 7, 7, 7, 14]`).
- **Decay:** Natychmiastowo spadał z `peak` do `sustain` w jednej ramce, ignorując wielokrokowe wygaszanie przez `ch_dec` ramek VBI.
- **Sustain overshoot:** Dla cichych nut, gdzie `peak_vol < ch_sus`, faza Sustain podbijała głośność powyżej `peak_vol` (np. dla `peak=4, sustain=10` skok z `4` na `10`).
- **Release (niezgodność jednostek czasu):** Procedura porównywała licznik ticków muzycznych `ch_dur,x` bezpośrednio z liczbą ramek VBI `ch_rel,x`, przez co faza Release włączała się przedwcześnie w proporcji `tempo_divider : 1` (np. dla `dur=6` ticków i `tempo_divider=6` = `36` ramek, przy `rel=8` nuta kończyła się po ~20 ramkach z 16 martwymi ramkami ciszy).

### 2.2. Wdrożone rozwiązanie w `player.asm` (`scale_env_step`, `update_envelopes`) i `pokey_hw.py`
- **Wspólny dzielnik całkowitoliczbowy 6502 (`scale_env_step`):** Funkcja bezmnożeniowa (dodawanie i odejmowanie w pętli `1..15` iteracji, bez dodatkowych bajtów na stronie zerowej – korzysta z `zp_tmp_ptr` `$88..$89`) oblicza dokładnie `floor((ch_env_frame,x * Y) / A)` dla `1 <= ch_env_frame,x < A <= 255` oraz `0 <= Y <= 15`.
- **Attack (`@phase_attack`):**
  - Dla `ch_env_frame < ch_att`: `ch_cur_vol = max(1, floor((ch_env_frame * ch_peak_vol) / ch_att))`.
  - Dla `ch_env_frame >= ch_att` (lub `ch_att == 0`): przejście do fazy `2` (`Decay`), `ch_env_frame = 0`, `ch_cur_vol = ch_peak_vol`.
- **Decay (`@phase_decay`):**
  - Wylicza liniowe zejście od `ch_peak_vol` do `ch_sus_lvl`: `ch_peak_vol - floor((ch_env_frame * (ch_peak_vol - ch_sus_lvl)) / ch_dec)`.
  - Dla `ch_dec == 0` lub `ch_env_frame >= ch_dec`: natychmiastowe wejście do `@phase_sustain` w tej samej ramce (brak pustego kroku wstrzymania).
- **Sustain (`@setup_envelope` + `@phase_sustain`):**
  - W `@setup_envelope` docelowy poziom Sustain jest ograniczany do maksimum nuty: `ch_sus_lvl,x = min(ch_sus,x, ch_peak_vol,x)`. Eliminuje to przesterowanie/podbicie głośności cichych nut.
- **Release (`@phase_sustain` -> `@phase_release`):**
  - Wylicza rzeczywistą liczbę pozostałych ramek VBI do końca nuty:
    `frames_remaining = (ch_dur,x - 1) * tempo_divider + tick_counter`
    z szybką ścieżką (`cmp ch_dur,x / bcc @sustain_keep`) i zabezpieczeniem przed przepełnieniem 8-bitowym (`bcs @sustain_keep` dla >= 256 ramek).
  - Gdy `frames_remaining <= ch_rel,x` (dla `ch_rel,x > 0`), obwiednia przechodzi do fazy `4` (`Release`) i liniowo zmniejsza głośność `-1` na ramkę do `0`.
- **Zgodność referencji Pythona (`src/atari_music/pokey_hw.py::player_envelope_volumes`):** Zaktualizowana bit-do-bitu do identycznej arytmetyki całkowitoliczbowej 6502 i zweryfikowana na pełnej macierzy testów parytetu z `py65`.
- **Izolacja historycznego modelu Stage 20 (`src/atari_music/stage20.py`):** Historyczny, 4-parametrowy model zredukowany Stage 20 zachowano w dedykowanym helperze `_stage20_reduced_contour` (`decay=0`, `frames_per_tick=1`, `phase = 1 -> 2 -> 3 -> 4`), nie zakłócając walidacji archeologicznej Stage 20–22.

---

## 3. Naprawa wyciszania kanałów POKEY (`write_pokey_registers`)

### 3.1. Zdiagnozowany błąd (`HEAD:player.asm`)
W `write_pokey_registers` sekwencja:
```asm
lda ch_mute_mask + 0
bne @mute_ch1
...
@mute_ch1:
sta AUDC1_REG
```
pozostawiała w akumulatorze `A` wartość maski (np. `$01` zamiast `$00`) podczas skoku do `@mute_ch1` (analogicznie dla kanałów 2, 3, 4 oraz `ch_mute_mask + 0 | ch_mute_mask + 1` w trybie basu 16-bitowego). W efekcie POKEY zamiast ciszy (`$00`) dostawał `$01` (głośność 1 z generatorem szumu/polinomu 5+17-bitowego), powodując słyszalne bzyczenie i trzaski na wyciszonym kanale.

### 3.2. Wdrożone rozwiązanie (`player.asm` linie 672–753)
- Dla każdego z kanałów 1–4 w trybie 8-bitowym oraz dla połączonej pary 16-bitowej (`AUDCTL & $10`, gdzie `AUDC1 = $00`, a `AUDC2` sprawdza zarówno `ch_mute_mask + 0`, jak i `ch_mute_mask + 1`):
  ```asm
  lda #0
  ldy ch_mute_mask + <ch>
  bne @mute_ch<N>
  ```
- Zapis do `AUDCn_REG` przy aktywnej masce zawsze wynosi dokładnie `$00`.
- Stan wewnętrzny obwiedni i częstotliwości (`ch_audf`, `ch_cur_vol`, `ch_env_phase`, `ch_dur`) jest nadal aktualizowany bez zakłóceń sąsiednich kanałów, dzięki czemu zdjęcie maski (`ch_mute_mask = 0`) natychmiast lub od kolejnej nuty przywraca dźwięk identyczny co do bajtu z wersją niewyciszoną.

---

## 4. Budżet pamięciowy i zgodność sprzętowa 6502

Zweryfikowano asemblerem `tools/mads/mads.exe` oraz analizą `stage15` (`reports/stage15/player_size_analysis.json`) i skryptem `scripts/verify_stage11_runtime.py`:

| Metryka | Przed Fazą 1 (`HEAD` bez C1) | Przed Fazą 1 (`stage15` z C1) | Po Fazie 1 (aktualny `player.asm`) | Limit / Budżet |
|---|---:|---:|---:|---|
| Rozmiar XEX wrappera (`stage15` / `mads`) | 886 B (880 B kod+stan) | 1016 B | **1144 B** (1138 B kod+stan) | `< 2048 B` (wyłącznie dla playera) |
| Podział kod / stan (`stage15`) | — | — | **1067 B kodu + 77 B stanu** | Zapas: **904 B** |
| Strona zerowa (`PLAYER_ZP_BASE`) | 10 B (`$80..$89`) | 10 B (`$80..$89`) | **10 B (`$80..$89`)** | Bez wzrostu (wyłącznie `$80..$FF`) |
| Nieoficjalne instrukcje (`asapscan -u`) | 0 | — | **0** (`""` dla wszystkich 9 SAP) | Ścisły MOS 6502 |
| Relokacja (`$6000..$A000`, split `$5000/$8500`, ZP `$80/$90/$B0`) | — | — | **PASS (wszystkie)** | Pełna relokowalność |

---

## 5. Weryfikacja na prawdziwych binariach `SAP TYPE B` i ASAP 8.0.0

Uruchomiono skrypt `scratch/phase1_verification/build_phase1_checks.py`, który skompilował asemblerem MADS 9 rzeczywistych plików `SAP TYPE B` (`INIT 2000`, `PLAYER 2003`) z kodem `HEAD:player.asm` (konwertowanym z formatu v1 na historyczny v0) oraz z kodem po Fazie 1 (`player.asm` v1), zweryfikowanych narzędziami `tools/asap_all/asapscan.exe` (`-u`, `-t`, `-f`, `-d`) i `tools/asap_all/asapconv.exe` (`-R 44100 -w`). Zestawy porównawcze WAV przeskalowano jednym wspólnym wzmocnieniem grupowym (bez niezależnej normalizacji).

### 5.1. Rzeczywiste przebiegi rejestrów POKEY (`asapscan -d`)

- **ADSR – nuta testowa 36 ramek (`peak=14, attack=6, decay=8, sustain=6, release=8, tempo_divider=6`):**
  - **Przed (`adsr_before.sap`):**
    `[7, 7, 7, 7, 7, 14, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 1, 0, 0, ..., 0]` *(dwustopniowy skok ataku 7->14, zerowy decay, przedwczesne release dające 16 ramek martwej ciszy)*.
  - **Po (`adsr_after.sap`):**
    `[2, 4, 7, 9, 11, 14, 13, 12, 11, 10, 9, 8, 7, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 1, 0, 0, 0]` *(płynny 6-ramkowy Attack, 8-ramkowy Decay, stabilne Sustain=6 przez 14 ramek i 8-ramkowe Release dokładnie pod koniec nuty)*.
- **Ograniczenie Sustain dla cichej nuty (`peak=4, sustain=10`, ramki 42..71 na kanale 2):**
  - **Przed:** `[3, 3, 4, 10, 10, 10, 10, 10, 9, ...]` *(błędny skok głośności do 10 mimo `peak=4`)*.
  - **Po:** `[1, 2, 4, 4, ..., 4, 3, 2, 1, 0, 0, 0]` *(brak przekroczenia `peak=4`, stabilny Sustain na poziomie 4)*.
- **Wyciszenie izolowanego kanału 1 (`ch_mute_mask = [1, 0, 0, 0]`, kanały 2–4 w spoczynku):**
  - **Przed (`mute_solo_ch1_before.sap`):** `AUDC1 = $01` w każdej ramce; ASAP zgłasza aktywny sygnał `TIME 00:05.13 LOOP` (błędne brzmienie/szum mimo wyciszenia).
  - **Po (`mute_solo_ch1_after.sap`):** `AUDC1 = $00` w każdej ramce; ASAP sam wykrywa całkowitą ciszę `TIME 00:00.00`.
- **Wyciszenie basu 16-bitowego (`AUDCTL = $50`, `ch_mute_mask = [0, 1, 0, 0]`):**
  - `mute_16bit_bass.sap`: `AUDC1 = [$00]`, `AUDC2 = [$00]`, przy czym kanał 3 pozostaje w pełni aktywny (`mute_16bit_bass_ch3_active = true`).
- **Dynamiczne wyciszenie i odblokowanie w trakcie frazy (`mute_unmute_recovery.sap`):**
  - Ramki `0..49` (przed wyciszeniem): `100%` zgodności `AUDF1/AUDC1` z niezmodyfikowaną referencją `mute_unmute_reference.sap`.
  - Ramki `50..149` (wyciszenie w trakcie nuty i przez zmianę nuty): ścisłe `AUDC1 == $00` na każdej ramce.
  - Ramki `150..239` (po odblokowaniu): `100%` zgodności `AUDF1/AUDC1` z referencją.

### 5.2. Metryki akustyczne par porównawczych WAV (`scratch/phase1_verification/phase1_metrics.json`)

| Plik WAV | Grupa / Wspólny gain | Raw Peak (dBFS) | Raw RMS (dBFS) | Scaled Peak (dBFS) | Scaled RMS (dBFS) | Uwagi |
|---|---|---:|---:|---:|---:|---|
| `adsr_before.wav` | ADSR (`2.018417`) | -7.10 | -21.25 | -1.00 | -15.15 | 16 martwych ramek + skok `peak<sus` |
| `adsr_after.wav` | ADSR (`2.018417`) | -8.39 | -19.46 | -2.29 | -13.36 | Pełna energia ADSR bez przesteru |
| `mute_solo_ch1_before.wav` | Mute (`1.239316`) | -28.20 | -37.53 | -26.34 | -35.67 | Słyszalne klikanie/bzyczenie z `AUDC1=$01` |
| `mute_solo_ch1_after.wav` | Mute (`1.239316`) | **-120.00** (`0.0`) | **-120.00** (`0.0`) | **-120.00** (`0.0`) | **-120.00** (`0.0`) | Cyfrowa cisza (`AUDC1=$00`) |
| `mute_before_buggy_01.wav` | Mute (`1.239316`) | -3.68 | -13.50 | -1.82 | -11.63 | 4 kanały z wyciekiem `$01` na Ch1 |
| `mute_after_fixed_00.wav` | Mute (`1.239316`) | -2.86 | -13.28 | -1.00 | -11.42 | 4 kanały, Ch1 = `$00`, Ch2–4 czyste |
| `mute_16bit_bass.wav` | Mute (`1.239316`) | -6.13 | -13.42 | -4.27 | -11.56 | Ch1+Ch2 `$00`, Ch3–4 czyste |
| `mute_unmute_reference.wav` | Mute (`1.239316`) | -7.26 | -15.63 | -5.40 | -13.76 | Referencja bez wyciszania |
| `mute_unmute_recovery.wav` | Mute (`1.239316`) | -7.65 | -18.06 | -5.78 | -16.19 | Odtworzenie przed/po wyciszeniu |

---

## 6. Testy regresyjne i pełna suita `pytest`

Dodano dedykowaną suitę `tests/test_phase1_audio_fixes.py` (26 testów opartych na realnej asemblacji MADS i emulacji CPU 6502 w `py65` z obserwowaniem zapisów do `$D200..$D208`):
- Wszystkie cztery fazy ADSR i płynne przejścia `Attack -> Decay -> Sustain -> Release` (dla różnych poziomów, w tym `attack=0`, `decay=0`, `release=0`, bardzo krótkich nut `dur=1`, długich nut `>=256` ramek, `tempo_divider` z zakresu `1..8`, `peak < sustain`).
- Parytet 1:1 wskaźnika `pokey_hw.player_envelope_volumes()` względem maszyny 6502 (`tests/test_pokey_semantics.py` + `tests/test_phase1_audio_fixes.py`).
- Wyciszanie pojedynczego kanału (wszystkie 4 kanały niezależnie), wielokanałowe i nietypowe bajty maski (`$80`, `$FF`, `$02` -> zawsze `$00`), brak wpływu na sąsiednie kanały, wyciszanie basu 16-bitowego oraz przywracanie dźwięku w połowie nuty i przez granicę nut.

**Wyniki uruchomień weryfikacyjnych:**
- `tests/test_phase1_audio_fixes.py`: `26 passed`.
- `tests/test_pokey_semantics.py` + `tests/test_stage15.py`: `131 passed`.
- `tests/test_c1_modulation.py`: `59 passed`.
- `tests/test_stage20.py` + `tests/test_stage21.py` + `tests/test_stage22.py`: `318 passed`.
- `tests/test_stage11.py` (po aktualizacji linii 178 z `0.6338` na odświeżoną wartość Stage 9D `0.6596`): `39 passed in 10.31s`.
- `scripts/verify_stage11_runtime.py`: **ALL STAGE 11 AUTOMATED CHECKS COMPLETED** (6 XEX, 5 relokacji, 3 konfiguracje ZP, audyt DUNGEON 16-bit, 4 przejścia API).
- Pełna suita `python -m pytest -q`: **`2353 passed, 2 deselected`** (deselekcja 2 testów `live` z domyślnego `addopts = "-m 'not live'"` w `pyproject.toml`; wynik weryfikowany końcowo po wszystkich zmianach).

---

## 7. Odświeżenie artefaktów badawczych i bazowych testów

Po zmianie obwiedni ADSR w `pokey_hw.player_envelope_volumes` zaktualizowano zależne testy bazowe i odświeżono wygenerowane (ignorowane w `.gitignore`) artefakty bez naruszania zebranych odpowiedzi słuchaczy:
- `examples/sound_profile_listening/`: przerenderowano 61 bodźców WAV i 6 par utworów A/B oraz zaktualizowano metryki w `manifest.json`, **zachowując nienaruszone** odpowiedzi w `evaluation_ab.csv`, `evaluation_profiles.csv`, `evaluation_songs.csv`, `sample_id`, `ab_trials` i `uses_profile_side`.
- `reports/stage9d/`, `examples/sound_profile_rebinding_10a/` i `examples/sound_profile_volume_contour_10b/`: przebudowano z przywróceniem zachowanych plików `evaluation_rebinding_10a.csv` i `evaluation_volume_contour_10b.csv`.
- Stage 9E na banku referencyjnym potwierdził niezmienność struktury grup duplikatów (`[10, 6, 4, 4, 3, 3]`, 24 redundantne z 61 profili).
- Odświeżono `reports/stage11/`, `reports/stage15/`, `experiments/experiment26..28/` oraz zaktualizowano zamrożone hasze WAV/XEX w `tests/test_sound_profile_library.py`, granice układu XEX w `tests/test_xex_layout.py`, tolerancję zaokrąglenia taksonomii w `tests/test_stage22.py` i wartość korelacji Stage 9D (`0.6338 -> 0.6596`, zachowującą odwrotny znak względem Stage 7B `-0.4401`) w `tests/test_stage11.py`.

---

## 8. Zmodyfikowane i utworzone pliki

- **Kod produkcyjny:**
  - `player.asm`
  - `src/atari_music/asm/player.asm` (identyczny bajtowo z `player.asm`)
  - `src/atari_music/pokey_hw.py`
  - `src/atari_music/stage15.py`
  - `src/atari_music/stage20.py`
- **Testy:**
  - `tests/test_phase1_audio_fixes.py` (nowy, 26 testów MADS+`py65`)
  - `tests/test_pokey_semantics.py`
  - `tests/test_stage22.py`
  - `tests/test_xex_layout.py`
  - `tests/test_sound_profile_library.py`
  - `tests/test_stage11.py`
- **Dokumentacja / historia:**
  - `PHASE_1_REPORT.md`
  - `HISTORY.md`
- **Artefakty weryfikacji Fazy 1 (`scratch/phase1_verification/`):**
  - `scratch/phase1_verification/build_phase1_checks.py`
  - `scratch/phase1_verification/refresh_packages.py`
  - `scratch/phase1_verification/phase1_metrics.json`
  - `scratch/phase1_verification/*.sap`, `scratch/phase1_verification/*.wav`

---

## 9. Rekomendacja gotowości do Fazy 2

**Status: GOTOWY DO FAZY 2.**

1. Fundament czasowy (liniowy Attack/Decay, bezpieczny Sustain `min(peak, sustain)`, zgodny z ramkami VBI Release) oraz czyste wyciszanie kanałów (`$00` w 8-bit i 16-bit) są w pełni zweryfikowane maszynowo na 6502 (`py65`) i w emulatorze POKEY ASAP 8.0.0.
2. Player zajmuje **1144 B** przy limicie **2048 B**, pozostawiając **904 B** zapasu na kolejne mechanizmy syntezy (makra czasowe, modulacje wysokości dźwięku, wibrato, portamento, bogatsze presety perkusji i basu 15 kHz / 16-bit) oraz **10 B** na stronie zerowej z zachowaniem pełnej relokowalności.
3. Cały zestaw testów (`2353 passed`) oraz pakiety eksperymentalne przechodzą bez błędów i z pełną powtarzalnością deterministyczną.
