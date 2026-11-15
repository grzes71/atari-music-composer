# Kompleksowy audyt silnika audio i sound designu — Atari Music Composer (POKEY 6502)

> **Zakres i status dokumentu:** Wyłącznie audyt techniczny oraz plan rozwoju. W ramach tego opracowania **nie zmodyfikowano** żadnego produkcyjnego pliku źródłowego Pythona, asemblera 6502 (`player.asm`), modeli danych ani generatora muzyki. Wszystkie obserwacje kodowe zweryfikowano bezpośrednio w plikach repozytorium, a eksperymenty dźwiękowe WAV wykonano poza bazą kodu źródłowego.

---

## 1. Podsumowanie aktualnego stanu silnika audio

### 1.1 Architektura potoku generowania i odtwarzania

Silnik **Atari Music Composer** realizuje dwuścieżkowy potok kompilacji muzyki wokół wspólnej reprezentacji pośredniej `IRSong` ([src/atari_music/ir.py](src/atari_music/ir.py)) oraz pojedynczego źródła definicji sprzętowych `pokey_hw` ([src/atari_music/pokey_hw.py](src/atari_music/pokey_hw.py)):

```text
[Źródło kompozycji]
  ├── Generator proceduralny v4 (composer_v4.py, bass_engine.py, rhythm_ornament.py) ─► MusicSong
  ├── Generator archetypów (generator.py) ─────────────────────────────────────────────► IRSong
  └── Ścieżka AI JSON (ai/schema.py -> ai/composition.py) ────────────► MusicSong ─────► IRSong
                                                                                          │
                                    (opcjonalnie) wiązanie profili (sound_profiles/binding.py)
                                                                                          │
                                                    ┌─────────────────────────────────────┴─────────────────────────────────────┐
                                                    ▼                                                                           ▼
                                     [Ścieżka podglądu WAV]                                                     [Ścieżka sprzętowa MADS / XEX]
                          ir.compile_ir_to_pokey_frames(song)                                                mads_exporter.export_mads_asm(song)
                                                    │                                                                           │
                                  macierz (N, 9) uint8 @ 50 Hz PAL                                             tablice Format Version 1 (.byte/.word)
                                                    │                                                                           │
                                                    ▼                                                                           ▼
                          pokey_synth.render_pokey_to_wav() (44.1 kHz)                                     MADS + player.asm -> .xex (xex_layout.py)
```

W projekcie istnieją trzy główne ścieżki tworzenia materiału muzycznego, zbiegające się w `IRSong`:
1. **Composer v4 (`src/atari_music/composer_v4.py`)**: układ 4-kanałowej aranżacji (`arrangement.py`), linia basu (`bass_engine.py`), rytmika (`rhythm_engine.py`) oraz czwarty głos perkusyjno-ornamentalny (`rhythm_ornament.py`).
2. **Generator archetypowy (`src/atari_music/generator.py`)**: starszy generator proceduralny oparty na archetypach melodyczno-rytmicznych.
3. **Ścieżka AI/JSON (`src/atari_music/ai/composition.py`, `src/atari_music/ai/schema.py`)**: kompilacja deklaratywnych dokumentów `AICompositionDoc` do `MusicSong`, a następnie do `IRSong`.

Po stronie sprzętowej ([src/atari_music/ai/client.py](src/atari_music/ai/client.py#L652-L776)) dane wyeksportowane przez `mads_exporter.py` łączone są w asemblerze MADS z relokowalnym sterownikiem **`player.asm`** (identyczne kopie w [player.asm](player.asm) oraz [src/atari_music/asm/player.asm](src/atari_music/asm/player.asm), weryfikowane pod kątem zakresu pamięci `$0400–$BFFF` przez [src/atari_music/xex_layout.py](src/atari_music/xex_layout.py)).

### 1.2 Reprezentacja instrumentów

Instrument w warstwie Pythona definiowany jest przez klasę `IRInstrument` ([src/atari_music/ir.py#L57-L98](src/atari_music/ir.py#L57-L98)):
- `distortion`: bajt konfiguracyjny górnego półbajtu `AUDC` (`$00, $20, $40, $60, $80, $A0, $C0, $E0`),
- `envelope: IREnvelope`: 4-parametrowa obwiednia (`attack_frames`, `decay_frames`, `sustain_vol`, `release_frames`),
- `is_16bit: bool` oraz opcjonalny `audctl: Optional[int]` (używany m.in. przez zewnętrzne wiązanie profili brzmieniowych [src/atari_music/sound_profiles/binding.py](src/atari_music/sound_profiles/binding.py)),
- `modulation: int`: deskryptor modulacji dzielnika — Format Version 1 definiuje wyłącznie `MODULATION_NONE = 0` i `MODULATION_OCTAVE_PULSE = 1` (`c1_octave_pulse`),
- `volume_contour: Optional[List[int]]`: lista mnożników głośności na ramkę VBI — **obsługiwana wyłącznie w podglądzie WAV** (`apply_volume_contour`); eksporter MADS odrzuca utwór wyjątkiem `VolumeContourNotExpressibleError` ([src/atari_music/mads_exporter.py#L71-L94](src/atari_music/mads_exporter.py#L71-L94)),
- Pola **zarezerwowane i całkowicie ignorowane** przy kompilacji ramek i eksportowaniu do ASM: `macro: Optional[List[IRMacroStep]]`, `vibrato_depth: int`, `vibrato_speed: int` (oraz w `IRNote`: `slide_semitones`, `arpeggio_offsets`).

W warstwie 6502 (`Format Version 1`, [player.asm#L110-L135](player.asm#L110-L135), [src/atari_music/mads_exporter.py#L384-L422](src/atari_music/mads_exporter.py#L384-L422)) tablica instrumentów składa się z **4 rekordów po 6 bajtów (łącznie 24 bajty)** przypisanych na stałe do kanałów CH1..CH4:

```text
Bajty rekordu instrumentu (Format Version 1):
+0: distortion   ($00..$E0, górne 3 bity AUDC)
+1: attack       (liczba ramek VBI)
+2: decay        (liczba ramek VBI)
+3: sustain      (poziom głośności 0..15)
+4: release      (próg w ch_dur wyzwalający wygaszanie)
+5: modulation   (0 = brak, 1 = MOD_OCTAVE_PULSE)
```

Rekordy ładowane są **jednorazowo w `music_init`** do tablic RAM `ch_dist[4]`, `ch_att[4]`, `ch_dec[4]`, `ch_sus[4]`, `ch_rel[4]`, `ch_mod[4]`.

### 1.3 Dostępne przebiegi (`AUDC`) i konfiguracje zegarów (`AUDCTL`)

W [src/atari_music/constants.py](src/atari_music/constants.py#L38-L75) oraz [src/atari_music/pokey_hw.py#L56-L75](src/atari_music/pokey_hw.py#L56-L75) zaimplementowano sprzętowo wierne dekodowanie rejestrów POKEY:

| Wartość `AUDC` (bity 7–5) | Flagi (`NOTPOLY5, POLY4, PURETONE`) | Rzeczywisty generator sprzętowy POKEY | Obecne użycie w silniku |
| :---: | :---: | :--- | :--- |
| **`$00`** | `0, 0, 0` | Poly5 bramkujący szum Poly17/Poly9 | Brak w domyślnych kompozytorach (tylko ręcznie / AI override) |
| **`$20`** / **`$60`** | `0, 0, 1` / `0, 1, 1` | Poly5 bramkujący czysty ton (oba tryby identyczne sprzętowo) | Brak w domyślnych kompozytorach |
| **`$40`** | `0, 1, 0` | Poly5 bramkujący Poly4 | Wyłącznie profil eksperymentalny `c1_octave_pulse` |
| **`$80`** | `1, 0, 0` | Szum biały 17-bit (lub 9-bit przy `AUDCTL` bit 7) | Domyślna perkusja (`CH4`) |
| **`$A0`** / **`$E0`** | `1, 0, 1` / `1, 1, 1` | Czysta fala prostokątna (oba tryby identyczne sprzętowo) | Wszystkie domyślne LEAD, HARMONY oraz 16-bit BASS |
| **`$C0`** | `1, 1, 0` | 4-bitowy LFSR Poly4 (cykl 15 kroków) | Domyślny 8-bit BASS w `composer_v4.py` i `ai/composition.py` |

Konfiguracja globalna **`AUDCTL` (`$D208`)**:
- Zegary bazowe PAL zdefiniowane w `constants.py` (`PAL_CLOCK_HZ = 1773447.0 Hz`):
  - Zegar 64 kHz (`AUDCTL` bit 0 = 0): $\frac{1\,773\,447}{28} = \mathbf{63\,337{,}39\text{ Hz}}$ *(uwaga: komentarz w `constants.py#L9` podaje wartość NTSC `~63920.89 Hz`, jednak kod liczy dokładną wartość PAL)*.
  - Zegar 15 kHz (`AUDCTL` bit 0 = `$01`): $\frac{1\,773\,447}{114} = \mathbf{15\,556{,}55\text{ Hz}}$ *(komentarz w `constants.py#L10` również cytuje NTSC `~15696.0 Hz`)*.
  - Zegar CPU 1.77 MHz (`AUDCTL` `$40` dla CH1, `$20` dla CH3): $\mathbf{1\,773\,447{,}0\text{ Hz}}$.
- W trybie domyślnym kompozytorzy używają wyłącznie `AUDCTL = $00` (4 kanały 8-bit @ 63.34 kHz) albo `AUDCTL = $10` (`AUDCTL_JOIN_1_2_16BIT` przy `uses_16bit_bass = True` — para CH1+CH2 taktowana **64 kHz**, o ile zewnętrzne wiązanie `sound_profiles` nie wymusi `$50`). Bity filtrów górnoprzepustowych (`$02`, `$04`), łączenie CH3+CH4 (`$08`) i szum 9-bitowy (`$80`) nie są wykorzystywane przez generatory ani kompilator IR.

### 1.4 Format zdarzeń nutowych, wykorzystanie 4 kanałów i kompatybilność z SAP

- **Rozkład ról na 4 kanałach**:
  - Tryb 8-bit (`uses_16bit_bass = False`): `CH1` (Lead lub Bas w zależności od aranżacji `arrangement.py`), `CH2` (Counter/Harmony), `CH3` (Bass lub Lead), `CH4` (Percussion / Dark Ostinato / Ornament). W `composer_v4.py` i `ai/composition.py` najczęstszy układ 8-bitowy to melody/harmony na CH1–CH2 lub CH2–CH3, bas na CH1 lub CH3, perkusja na CH4.
  - Tryb 16-bit (`uses_16bit_bass = True`): `CH1` dostarcza młodszy bajt dzielnika (`AUDF1`, `AUDC1 = $00` wyciszony), `CH2` dostarcza starszy bajt dzielnika (`AUDF2`) oraz aktywną głośność i dystorsję (`AUDC2`), pozostawiając jedynie 2 niezależne kanały na melodię/harmonię (`CH3`) i perkusję (`CH4`).
- **Format zdarzeń w ścieżkach (`mads_exporter.py#L444-L510`, `player.asm#L267-L380`)**:
  - Każde zdarzenie nutowe lub pauza ma stałą długość **3 bajtów**: `.byte audf, duration_ticks, volume`.
  - Wartość `audf = $FF` oznacza koniec ścieżki w patternie; pozostałe dzielniki są obcinane przez `pokey_hw.clamp_audf_for_tracker()` do przedziału `$00..$FE`.
  - Czas trwania nuty wyrażony jest w tickach (`duration_ticks >= 1`), gdzie jeden tick odpowiada `frames_per_tick` (typowo 3..6 ramek VBI = 60..120 ms przy 50 Hz PAL).
  - W trybie 16-bitowym ścieżka `CH1` przechowuje `.byte div_low, dur, $00`, a ścieżka `CH2` — `.byte div_hi, dur, volume`, co pozwala `player.asm` kontrolować obwiednię głośności basu 16-bitowego z dokładnością do 4 bitów przez kanał 2.
- **Zasoby `player.asm` i kompatybilność z SAP / grami**:
  - Zmierzone narzędziem `stage15.measure_player_size` za pomocą `tools/mads/mads.exe`: skompilowany `player.asm` (729 linii) zajmuje dokładnie **1016 bajtów** (943 B kodu/danych stałych + 73 B zmiennych stanu) wobec twardego limitu `PLAYER_SIZE_LIMIT_BYTES = 2048` B ([src/atari_music/stage15.py#L2095](src/atari_music/stage15.py#L2095)). Daje to **1032 bajty wolnego budżetu** w samym sterowniku.
  - Zużycie strony zerowej (Zero Page): dokładnie **10 bajtów** (`PLAYER_ZP_BASE + 0..9`, domyślnie `$80..$89`).
  - Eksport produkcyjny w tym projekcie wytwarza `.wav`, relokowalny `.asm` MADS oraz wykonywalny `.xex` (pliki `.sap` są analizowane jako korpus wejściowy przez `scripts/inventory.py` i `stage15.py`, brak dedykowanego eksportera kontenera `.sap`). Sterownik zachowuje jednak standardowy interfejs wywołań typu SAP `TYPE B` (`music_init` w X/Y, `music_play`, wywołanie `music_update` raz na ramkę 50 Hz PAL, brak zakazanego zapisu powyżej `$BFFF`), więc każde rozszerzenie zachowujące ten kontrakt i mieszczące się w budżecie cykli VBI pozostaje w pełni gotowe do osadzenia w grach i formacie SAP `TYPE B`.

---

## 2. Najważniejsze ograniczenia obecnej implementacji

Aby precyzyjnie planować rozwój silnika, należy rozdzielić ograniczenia na cztery niezależne warstwy:

### 2.1 Warstwa 1 — Niezmienne ograniczenia sprzętowe układu POKEY
1. **Brak sprzętowych obwiedni i LFO**: POKEY ma wyłącznie 4 rejestry częstotliwości (`AUDF1–4`) i 4 rejestry barwy/głośności (`AUDC1–4` z 4-bitową głośnością liniową `0..15`). Każda zmiana głośności, wysokości lub przebiegu wymaga zapisu przez procesor 6502 (standardowo raz na ramkę 50 Hz VBI = co 20 ms).
2. **Nieliniowa rozdzielczość dzielnika 8-bitowego**: Częstotliwość wyjściowa spełnia zależność:
   $$f = \frac{f_{\text{clock}}}{2 \cdot (\text{AUDF} + M)}$$
   gdzie $M=1$ dla zegarów 64 kHz i 15 kHz, $M=4$ dla pojedynczego kanału 1.77 MHz oraz $M=7$ dla pary 16-bit @ 1.77 MHz. Błąd kwantyzacji pomiędzy kolejnymi wartościami `AUDF` wynosi $\Delta \text{cent} \approx 1200 \log_2\!\left(\frac{\text{AUDF}+2}{\text{AUDF}+1}\right)$, co w wysokich rejestrach 64 kHz powoduje fałsze sięgające 15–40 centów, a poniżej 124.19 Hz w trybie 8-bit @ 64 kHz zupełnie blokuje skalę basową.
3. **Korelacja dzielników z wielomianami LFSR**: W trybach `$C0` (Poly4, cykl 15-krokowy) i `$20` (Poly5, cykl 31-krokowy) jeśli $(\text{AUDF}+1)$ ma wspólny dzielnik z długością rejestru (odpowiednio 3 lub 5 dla Poly4; 31 dla Poly5), rejestr przesuwny blokuje się na krótkim podcyklu, wywołując zanik dźwięku, zmianę wysokości lub niestabilność fazy przy każdym wyzwoleniu nuty.
4. **4 głosy jako twardy zasób**: Łączenie kanałów w tryb 16-bit (`AUDCTL` `$10`/`$08`) lub filtr górnoprzepustowy z zewnętrznym zegarem (`$04`/`$02`) zawsze poświęca jeden z czterech niezależnych głosów.

### 2.2 Warstwa 2 — Ograniczenia i błędy obecnego drivera 6502 (`player.asm`)
1. **Zdegenerowana maszyna stanów ADSR (`update_envelopes`, [player.asm#L455-L547](player.asm#L455-L547), odwzorowana w [src/atari_music/pokey_hw.py#L320-L386](src/atari_music/pokey_hw.py#L320-L386))**:
   - **Attack to skok 2-poziomowy, nie rampa**: W `@attack_ramp` (linie 491–497) głośność przyjmuje stałą wartość połowiczną `(peak_vol >> 1) | 1` przez `attack_frames - 1` ramek, a następnie na ostatniej ramce fazy przeskakuje do `peak_vol` tylko na **jedną ramkę (20 ms)**. Przykład zmierzony w `pokey_hw.player_envelope_volumes(20, 5, 15, att=4, dec=6, sus=10, rel=3)`: `[7, 7, 7, 15, 10, 10, ...]`.
   - **Decay ma zerowe nachylenie (Zero-Slope Bug)**: W `@phase_decay` (linie 499–518) zarówno gałąź trwania opadania `@decay_ramp` (linie 515–518), jak i gałąź przejścia `@decay_instant` (linie 507–513) wykonują identyczny zapis `lda ch_sus,x / sta ch_cur_vol,x`. W rezultacie głośność **spada natychmiastowo w 1. ramce Decay** z `peak_vol` bezpośrednio na `sustain_vol`, a `decay_frames` działa jedynie jako martwe opóźnienie zmiany zmiennej `ch_env_phase`.
   - **Release miesza jednostki (Ticks vs Frames)**: W `@phase_sustain` (linie 524–525) sterownik porównuje pozostały czas nuty w **tickach** (`ch_dur,x`, gdzie 1 tick = 3..6 ramek) z parametrem `ch_rel,x` zdefiniowanym w **ramkach** (`release_frames`), wywołując zanikanie po `-1` na ramkę już przy `ch_dur < ch_rel`. Dla nuty 4-tickowej (`fpt=5`, 20 ramek) z `rel=3`, wygaszanie rusza po połowie nuty (10 ramek przed końcem!), a przy `rel >= total_ticks` natychmiast po zakończeniu fazy Decay.
2. **Sztywne przypisanie 1 instrumentu na kanał**: `load_inst_loop` ([player.asm#L110-L135](player.asm#L110-L135)) wczytuje po jednym instrumencie dla CH1..CH4 wyłącznie podczas `music_init`. Nie istnieje kod zmiany `ch_dist` ani ADSR w trakcie utworu ani w trakcie pojedynczej nuty (np. na transjencie ataku).
3. **Brak innych modulacji poza `MOD_OCTAVE_PULSE`**: Procedura `apply_modulation` ([player.asm#L564-L591](player.asm#L564-L591)) sprawdza wyłącznie `cmp #MOD_OCTAVE_PULSE` (`1`). Brak vibrato, pitch envelope, portamento/glide, arpeggia oraz sekwencerów makr.
4. **Błąd wyciszania w `write_pokey_registers` (`ch_mute_mask`)**: W liniach 610–616 (oraz 621–627, 654–660, 665–671) po stwierdzeniu `ch_mute_mask != 0` kod skacze do `@mute_chN` z akumulatorem równym `1` (wartość maski!), przez co zapisuje do `AUDCn` wartość `$01` (słyszalny pisk o głośności 1 przy barwie `$00`) zamiast `$00`.
5. **Brak obsługi pary 16-bit `CH3+CH4`**: `write_pokey_registers` sprawdza jedynie bit `$10` (`CH1+CH2`), całkowicie pomijając bit `$08` (`AUDCTL_JOIN_3_4_16BIT`).

### 2.3 Warstwa 3 — Ograniczenia formatu danych `Format Version 1` i warstwy `IRSong`
1. **Zarezerwowane (martwe) pola ekspresji w `ir.py`**: W `ComposerV4` (`vibrato_depth`, `vibrato_speed`) oraz w `generator.py` (`macro: List[IRMacroStep]` dla Kick/Snare/Hi-Hat) pola modulacyjne są tworzone w obiektach `IRInstrument`, ale w `_render_note_to_frames` ([src/atari_music/ir.py#L471-L474](src/atari_music/ir.py#L471-L474)) i w `mads_exporter.py` są **celowo ignorowane**, aby utrzymać zgodność WAV z uboższym playerem 6502.
2. **Niska rozdzielczość czasowa nut (`frames_per_tick = 3..6`)**: Zdarzenia perkusyjne czy przednutki nie mogą trwać krócej niż 60–120 ms na poziomie ścieżki, ponieważ minimalny czas w zdarzeniu 3-bajtowym wynosi `1 tick`. Brak makr 50 Hz uniemożliwia formowanie transjentów krótszych niż 1 tick.
3. **Utrata instrumentu w ścieżce AI i wieloinstrumentowości**: `ai/composition.py::_resolve_channel_instrument` ([src/atari_music/ai/composition.py#L227-L268](src/atari_music/ai/composition.py#L227-L268)) oraz `mads_exporter.py::_find_channel_instrument` redukują cały kanał do jednego instrumentu na cały utwór.
4. **Nieoptymalne ustawienie `AUDCTL` dla 16-bitowego basu i brak diagnostyki kontekstowej**:
   - `ir.resolve_audctl_mode()` ([src/atari_music/ir.py#L192-L216](src/atari_music/ir.py#L192-L216)) dla `uses_16bit_bass = True` ustawia jedynie `$10` (64 kHz), zamiast wykorzystywać zegar 1.77 MHz (`$50`) oferujący ~28-krotnie wyższą precyzję strojenia i brak ograniczeń przy wyższych rejestrach basu.
   - `find_pitch_range_issues()` ([src/atari_music/ir.py#L351](src/atari_music/ir.py#L351)) wywołuje `describe_8bit_range_error` bez przekazania faktycznego `audctl` i numeru kanału.

### 2.4 Warstwa 4 — Niewierność programowego syntezatora WAV (`src/atari_music/pokey_synth.py`)
1. **Krytyczny błąd szybkości indeksowania `POLY4` (`$C0`) i `POLY5` (`$20`, `$40`, `$00`)**:
   W [src/atari_music/pokey_synth.py#L148-L152](src/atari_music/pokey_synth.py#L148-L152) syntezator liczy fazę z częstotliwości fali prostokątnej `freq = clock / (2 * (N + 1))`, a następnie mapuje jeden okres $2\pi$ tej częstotliwości na **cały 15-krokowy cykl `POLY4_SEQ` oraz cały 31-krokowy cykl `POLY5_SEQ`**:
   ```python
   poly5_idx = (phase_seq * (31.0 / (2.0 * math.pi))).astype(np.int64) % 31
   poly4_idx = (phase_seq * (15.0 / (2.0 * math.pi))).astype(np.int64) % 15
   ```
   Na rzeczywistym układzie POKEY jedno przepełnienie dzielnika przesuwa rejestr LFSR **o 1 krok**, a więc na jeden okres fali prostokątnej `freq` (dwa przepełnienia dzielnika) przypadają dokładnie **2 kroki** rejestru LFSR, a nie 15 czy 31! Obecna implementacja odtwarza zatem wielomiany `POLY4` z szybkością **7.5× wyższą** (a `POLY5` **15.5× wyższą**) od sprzętu, zamieniając niskoczęstotliwościowe dzielniki `$C0` na agresywne bzyczenie o zawyżonej wysokości (patrz pomiar w Sekcji 7: dominanta `372.5 Hz` zamiast `124.2 Hz` / `16.6 Hz`).
2. **Brak symulacji filtrów górnoprzepustowych (`AUDCTL` `$04` i `$02`) oraz łączenia `CH3+CH4` (`$08`)**: Pętla renderująca ([src/atari_music/pokey_synth.py#L112-L139](src/atari_music/pokey_synth.py#L112-L139)) ignoruje bity `$02`, `$04` i `$08`, co uniemożliwia testowanie efektów PWM i dual-16bit w podglądzie WAV.
3. **Liniowe sumowanie kanałów**: `audio_mix += wave_samples * amp` pomija nieliniową saturację wzmacniacza wyjściowego POKEY dla wysokich sum głośności.

---

## 3. Zidentyfikowane problemy z brzmieniami LEAD, BASS i PERCUSSION

### 3.1 Problemy brzmień LEAD (Obszar B)

1. **Monokultura przebiegu `$A0`**: W `composer_v4.py::_compile_v4_to_pokey_ir` ([src/atari_music/composer_v4.py#L422-L438](src/atari_music/composer_v4.py#L422-L438)) i `ai/composition.py::map_instrument_character` ([src/atari_music/ai/composition.py#L84-L87](src/atari_music/ai/composition.py#L84-L87)) wszystkie domyślne leady używają statycznego `$A0` (czystej fali prostokątnej 50% duty). Jedynym wyjątkiem w całym projekcie jest eksperymentalny preset `c1_octave_pulse` w bibliotece `data/instrument_libraries/lead/v0.1/library.json`.
2. **Brak jakiejkolwiek modulacji wysokości i barwy**: Zapisywane w `ComposerV4` pola `vibrato_depth` (1..2) oraz `vibrato_speed` (1..4) nigdy nie docierają do wyjścia audio. Długa nuta trzyma ten sam dzielnik `AUDF` od pierwszej do ostatniej ramki, co daje sterylny efekt „organów z generatora zegarowego”.
3. **Płaska obwiednia przez błąd Decay**: Zadeklarowane dla leadów obwiednie (np. `att=1, dec=4, sus=12, rel=3`) dają w rzeczywistości 1 ramkę szczytu (`14`), natychmiastowy spadek na płaski poziom `12`, a przy krótszych nutach przedwczesny release wynikający z porównania `ch_dur < ch_rel` w tickach. Brak stopniowego zaniku uniemożliwia uzyskanie naturalnych brzmień szarpanych (`Plucked`) i dzwonkowych (`Bell`).

### 3.2 Problemy brzmień BASS (Obszar C — źródła charczenia i „stanów logicznych”)

Przeprowadzona inspekcja kodu oraz diagnostyka numeryczna ujawniły **trzy nakładające się przyczyny** złej jakości basu 8-bitowego:

1. **Przyczyna #1 — Masowe obcinanie częstotliwości basu na progu `AUDF = $FE` (124.19 Hz)**:
   W `bass_engine.py` ([src/atari_music/bass_engine.py#L40-L44](src/atari_music/bass_engine.py#L40-L44), linia 158) zakres wysokości basu 8-bitowego jest ograniczony od dołu do `MIDI 33` (`A1 = 55.0 Hz`), a typowy korzeń oktawy oscyluje między `MIDI 33..45` (`55.0..110.0 Hz`). Tymczasem przy domyślnym zegarze **64 kHz (`AUDCTL = $00`)** maksymalny dopuszczalny dzielnik `AUDF_TRACKER_MAX = $FE` (`254`) daje częstotliwość progową:
   $$f_{\min, 64\text{kHz}} = \frac{63\,337{,}39}{2 \cdot (254 + 1)} = \mathbf{124{,}19\text{ Hz}} \quad (\approx \text{B2 / MIDI } 47{,}9)$$
   Każda nuta niższa niż B2 zostaje obcięta przez `clamp_audf_for_tracker()` do **tego samego bajtu `AUDF = $FE`**. Bezpośredni pomiar dla 6 profili `ComposerV4` (`seed=42, uses_16bit_bass=False`) potwierdził skalę degradacji:

   | Profil `ComposerV4` | Nuty basowe w patternach | Zakres MIDI w patternach | Zakres Hz żądanych | Nuty obcięte na `$FE` (`124.2 Hz`) | % zniszczonych nut basu |
   | :--- | :---: | :---: | :---: | :---: | :---: |
   | `title` | 20 | 36..46 (C2..A#2) | 65.4..116.5 Hz | 20 / 20 | **100.0%** |
   | `exploration` | 20 | 36..46 (C2..A#2) | 65.4..116.5 Hz | 20 / 20 | **100.0%** |
   | `dungeon` | 12 | 36..46 (C2..A#2) | 65.4..116.5 Hz | 12 / 12 | **100.0%** |
   | `action` | 40 | 36..58 (C2..A#3) | 65.4..233.1 Hz | 32 / 40 | **80.0%** |
   | `ending` | 32 | 33..59 (A1..B3) | 55.0..246.9 Hz | 19 / 32 | **59.4%** |
   | `funny` | 24 | 38..56 (D2..G#3) | 73.4..207.7 Hz | 13 / 24 | **54.2%** |

   W trzech z sześciu profili **100% linii basowej zamienia się w monotonny dron na jednym dzielniku `$FE`**, pozbawiony ruchu harmonicznego.

2. **Przyczyna #2 — Fizyka rejestru Poly4 (`$C0`) przy `AUDF = $FE` i dzielnikach podzielnych przez 3 i 5**:
   Domyślny 8-bitowy bas (`composer_v4.py#L440`, `ai/composition.py#L70`) używa trybu `DISTORTION_4BIT_POLY` (`$C0`). 4-bitowy rejestr LFSR ma cykl **15 kroków** o niesymetrycznym rozkładzie impulsów (`111101011001000`). Przy `AUDF = $FE` (`254`) i zegarze 64 kHz powstają jednocześnie dwa niepożądane zjawiska sprzętowe:
   - **Przekroczenie progu fuzji wysokości (~30 Hz)**: Przepełnienie dzielnika następuje z częstością $248{,}38\text{ Hz}$, zatem cały 15-krokowy cykl powtarza się co $248{,}38 / 15 = \mathbf{16{,}56\text{ Hz}}$. Ucho ludzkie nie odbiera tego jako stabilnego dźwięku basowego, lecz jako ciąg nieregularnych trzasków i „przełączania stanów logicznych” (*motorboating*).
   - **Zdegenerowana podzielność $254 + 1 = 255 = 3 \times 5 \times 17$**: Ponieważ efektywny okres $(N+1)=255$ dzieli się jednocześnie przez oba nietrywialne dzielniki długości cyklu 15 (zarówno **3**, jak i **5**), w rzeczywistym układzie POKEY licznik Poly4 próbkowany jest w zaledwie 3 lub 5 stanach zamiast pełnych 15. W efekcie barwa gwałtownie kolabuje lub cichnie zależnie od losowej fazy początkowej w momencie uderzenia nuty.

3. **Przyczyna #3 — Artefakt fazy w `pokey_synth.py` potęgujący jazgot `$C0`**:
   Przez opisane w §2.4 upakowanie 15 stanów Poly4 w jeden okres $2\pi$, podgląd WAV dla `$C0 @ AUDF=$FE` generuje widmo z dominantą na **372.5 Hz ($3 \times 124{,}2\text{ Hz}$)** i środkiem ciężkości widma aż na **5963.9 Hz**, sprawiając wrażenie agresywnego, wysokotonowego brzęczenia zamiast basu.

### 3.3 Problemy brzmień PERCUSSION (Obszar D)

1. **Jedno brzmienie dla wszystkich instrumentów perkusyjnych**:
   W `rhythm_ornament.py::_generate_profile_percussion` ([src/atari_music/rhythm_ornament.py#L64-L119](src/atari_music/rhythm_ornament.py#L64-L119)) Kick (`beat == 0`), Snare (`beat == 4`) i Hi-Hat (`beat in (2, 6)`) zapisywane są identycznie jako nuty bezwysokościowe (`pitch=None`, `duration=2`, `role=ChannelRole.PERCUSSION`, różniące się jedynie `velocity=15` vs `10`). Następnie zarówno `ir.py` (linia 509), jak i `mads_exporter.py` (linia 491) podstawiają **tę samą stałą `PERCUSSION_DEFAULT_AUDF = $50`** oraz statyczny instrument kanału 4 (`distortion = $80`, `att=0, dec=3, sus=8, rel=2`).
2. **Skutek akustyczny**: Stopa, werbel i hi-hat to fizycznie ten sam 160-milisekundowy impuls białego szumu o identycznej częstotliwości próbkowania (~391 Hz) i płaskim podtrzymaniu `sustain=8` po pierwszej ramce. Brakuje zarówno krótkich, wysokich transjentów dla hi-hatów (`AUDF = $01..$04`), jak i szybkiego spadku częstotliwości (`pitch drop`) w pierwszych 40–100 ms niezbędnego dla stopy (`Kick`) i tomów (`Tom`).
3. **Zablokowana obsługa makr perkusyjnych**: Mimo iż `generator.py#L195-L232` definiuje gotowe sekwencje `IRMacroStep` dla `POKEY Kick`, `POKEY Snare` i `POKEY Hi-Hat`, obecny kompilator ramek i eksporter MADS całkowicie je ignorują.

---

## 4. Możliwości modulacji i ewolucji brzmienia dostępne w POKEY

Przy taktowaniu silnika raz na ramkę PAL (50 Hz, interwał 20 ms) oraz wolnych **1032 bajtach** w budżecie `player.asm` i **118 wolnych bajtach Zero Page** (`$8A–$FF`), procesor 6502 może bezpiecznie wykonywać dynamiczną modulację rejestrów bez naruszania wydajności gier ani kompatybilności z SAP:

| Mechanizm modulacji / ewolucji | Zasada działania w `player.asm` (50 Hz VBI) | Szacowany koszt CPU (6502) | Zastosowanie dźwiękowe |
| :--- | :--- | :--- | :--- |
| **Prawdziwa wielofazowa obwiednia ADSR** | Narastanie liniowe `0 -> peak`, rzeczywisty spadek w fazie Decay (licznik podkroków lub stałoprzecinkowy akumulator 4.4) do `sustain`, oraz Release liczony w **ramkach VBI** zamiast tickach. | +15..25 cykli / kanał (~80 cykli łącznie) | Miękki atak (`Soft Lead`/`Bass`), naturalne wybrzmienie (`Plucked`, `Bell`), precyzyjne tłumienie krótkich perkusjonaliów. |
| **Dynamiczne przełączanie przebiegu (`attack_distortion`)** | Przez pierwsze $K \in \{1..3\}$ ramki nuty zapis do `AUDCn` używa alternatywnego generatora `ch_att_dist,x` (np. `$20` lub `$C0`), a następnie przełącza się na `ch_dist,x` (`$A0`). | +10..12 cykli / aktywny kanał | Wyraźny, niemęczący ucha transjent szarpnięcia (`Plucked`, `Bell`, `Snare`, `Analog Bass`) na **jednym** kanale. |
| **Obwiednia wysokości (`pitch_envelope` / `pitch_delta`)** | Przez pierwsze `pitch_frames` ramek dodawanie/odejmowanie podpisanego kroku `pitch_delta` do bieżącego `AUDF` (lub start od `AUDF + start_offset`). | +15..20 cykli / aktywny kanał | Głęboki `Kick` i `Tom` (wzrost `AUDF` o `+8..+24`/ramkę), atakowy `Scoop` w Leadzie (`+2 -> 0`), `Sub-Punch` w Basie. |
| **Opóźnione Vibrato tablicowe (`Delayed Vibrato`)** | Odliczanie `vib_delay` ramek od początku nuty, po czym cykliczny odczyt 8-bajtowej tablicy trójkątnej (`0,+1,+2,+1,0,-1,-2,-1`) z podziałem tempa `vib_rate` i przesunięciem bitowym skali. | +25..35 cykli / kanał z vibrato | Śpiewne długie nuty `Soft Lead`, `Retro Synth`, ekspresyjna intonacja bez powiększania ścieżki nutowej. |
| **Portamento / Glide** | Przechowywanie wartości docelowej `ch_target_audf,x` i płynne zbliżanie `ch_audf,x` o `glide_step` na każdą ramkę VBI. | +18..22 cykle / kanał z glide | Efektowne przejścia legato między dźwiękami w `Synth Lead` oraz `Acid-like Lead`. |
| **Szybkie makra ramkowe (50 Hz Micro-Macros)** | Sekwencje 4–8 kroków `(AUDC_nibble|vol, AUDF)` indeksowane per uderzenie (szczególnie na kanale perkusyjnym `CH4`). | +35..45 cykli / 1 kanał z makrem | Wielobarwny zestaw perkusyjny (`Kick`, `Snare`, `CHat`, `OHat`, `Tom`, `Cymbal`) na pojedynczym kanale POKEY. |
| **Filtr górnoprzepustowy (`AUDCTL` `$04` / `$02`) jako PWM/Sweep** | Sparowanie CH1+CH3 (`$04`) lub CH2+CH4 (`$02`), gdzie kanał zegarowy (z głośnością `0`) ma `AUDF_clk = AUDF_main + Δ` z wolnym ruchem $\Delta$. | +20..25 cykli / parę | Płynąca zmiana szerokości impulsu (PWM), phaser, „rezonansowy” sweep w `Retro Synth` i `Acid Lead` (kosztem 1 głosu). |
| **Arpeggio / przeplot alikwotowy 50 Hz** | Uogólnienie istniejącego `MOD_OCTAVE_PULSE` na krótkie tabele interwałów półtonowych lub naprzemiennego dzielnika `N` / `N//2`. | +25..35 cykli / kanał | `Organ-like Lead` (8'+4'+2⅔'), bogate akordy na 1 kanale, dzwonki. |

**Uwaga dotycząca nieliniowej kwantyzacji vibrata w POKEY:** Ponieważ $\Delta f / \Delta\text{AUDF} \propto f^2 / f_{\text{clock}}$, zmiana `AUDF` o `±1` w wysokim rejestrze (np. `AUDF = $20`, A5 = 880 Hz) odpowiada przeskokowi aż o **~52 centy** (pół półtonu), podczas gdy dla `AUDF = $A0` (196 Hz) jest to zaledwie **~10.7 centa**. Z tego powodu głębokie vibrato tablicowe na wysokich rejestrach 8-bitowych wymaga albo ograniczenia amplitudy do `±1` (z opcjonalnym ditheringiem czasowym co 2 ramki), albo użycia kanału 16-bitowego (`$50`) dla ultracystych partii solowych.

---

## 5. Propozycje nowych technik syntezy (ocena wykonalności dla LEAD, BASS i PERCUSSION)

### 5.1 Brzmienia LEAD (Obszar B)

| Charakter brzmienia | Realność na POKEY | Rekomendowana technika i receptura rejestrów | Główne ograniczenia sprzętowe |
| :--- | :---: | :--- | :--- |
| **Soft Lead** | **Wysoka** (1 kanał 8-bit) | Przebieg `$A0`, łagodny `Attack = 3..4` ramki (`4->8->12->15`), powolny `Decay` do `sustain = 10`, opóźnione vibrato (`delay = 10` ramek, `depth = ±1`, ~5 Hz), `Release = 4`. | Kwantyzacja `±1 AUDF` w oktawie 6 sprawia, że vibrato dla `AUDF < $24` staje się zbyt szerokie. |
| **Retro Synth Lead** | **Wysoka** (1 kanał 8-bit lub 2 z HPF) | Transjent 1 ramka `$C0` (vol 14) $\rightarrow$ podtrzymanie `$A0` z `Decay` `14 -> 10` oraz delikatnym `attack scoop` (`AUDF+2 -> AUDF` w 2 ramkach) lub subtelnym vibrato. W wariancie 2-kanałowym: HPF `$04` (`AUDF3 = AUDF1 + 1`). | Wariant HPF zajmuje drugi kanał POKEY jako bezgłośny zegar filtru. |
| **Metallic Lead** | **Wysoka** (1 kanał 8-bit) | Użycie `$20` (Poly5 + pure tone) lub `$C0` (Poly4) z doborem wysokości z bezpiecznej tablicy dzielników (z wyłączeniem wielokrotności 3 i 5 dla `$C0` oraz 31 dla `$20`), lub naprzemienne przełączanie `$A0 <-> $C0` na pierwszych 4 ramkach. | Nie wszystkie dźwięki skali chromatycznej brzmią czysto w trybie `$20`/`$C0` przy zegarze 64 kHz — część wymaga mikro-odstrojenia lub podbicia do 1.77 MHz. |
| **Bell-like Lead** | **Wysoka** (1 kanał 8-bit) | Ramka 0: `$20` lub `$A0` na oktawie wyżej (`AUDF >> 1`, `vol=15`) $\rightarrow$ Ramka 1: `$C0` (`vol=13`) $\rightarrow$ Ramki 2..20: czysty ton `$A0` z ciągłym wykładniczym zanikiem (`11->9->7->6->5->4->3->2->1->0`) bez płaskiego sustainu. | Wymaga naprawionego Decay oraz przełączania `AUDC` na ataku; brak prawdziwych nieharmonicznych widm FM (POKEY imituje dzwon skokiem oktawy i alikwotami LFSR). |
| **Plucked Lead** | **Bardzo wysoka** (1 kanał 8-bit) | Ramka 0: `$20` (`vol=15`, `AUDF+1`), Ramka 1: `$C0` (`vol=13`), Ramki 2+: `$A0` z szybkim opadaniem `11->8->6->4->3->2`. Zmierzony w eksperymencie #3 wzrost dynamiki transjentu to **+10.67 dB** wobec **+2.54 dB** w bazie. | Wymaga włączenia transjentowego `attack_distortion` oraz realnego nachylenia Decay. |
| **Organ-like Lead** | **Wysoka** (1 kanał 8-bit) | Natychmiastowy `Attack = 0`, `Decay = 0`, płaski `sustain = 10..12`, szybki `Release = 1` + przeplot oktawowy (`MOD_OCTAVE_PULSE`) lub 3-krokowy arpeggiator alikwotowy `0, +12, +19` półtonów (stopaż 8'+4'+2⅔'). | W przeplocie 50 Hz przy `Hold=1` słyszalne jest subharmoniczne pulsowanie 25 Hz (pożądane w chiptune, ale nie jest to gładki miks addytywny). |
| **Acid-like Lead** | **Średnia** (1 ch.) / **Wysoka** (2 ch. HPF) | W 1 kanale: makro transjentu `$20 -> $C0 -> $A0` przy akcentach + agresywne `Portamento` między sąsiednimi nutami. W 2 kanałach: włączony filtr HPF `AUDCTL |= $04` (`CH1` słyszalny, `CH3` z `vol=0`), gdzie `AUDF3` przemiata od `AUDF1` w górę lub w dół w trakcie nuty (sweep harmonicznych). | POKEY nie posiada analogowego filtru dolnoprzepustowego z rezonansem (TB-303). Filtr cyfrowy XOR w POKEY generuje grzebieniowe wygaszanie parzystych/wybranych składowych zamiast gładkiego odcięcia LP. |

### 5.2 Brzmienia BASS (Obszar C)

Kluczowym warunkiem uzyskania naturalnego, niemęczącego basu jest **natychmiastowe porzucenie zegara 64 kHz dla zakresu poniżej B2 w trybie 8-bit oraz stosowania `$C0` jako domyślnego generatora basu bez strojenia tablicowego**.

| Charakter brzmienia | Realność na POKEY | Rekomendowana technika i receptura rejestrów | Eliminacja artefaktów / ograniczenia |
| :--- | :---: | :--- | :--- |
| **Soft Bass** | **Bardzo wysoka** | Zegar **15 kHz (`AUDCTL |= $01`)** w trybie 8-bit lub para **16-bit (`$50`)**, czysty przebieg **`$A0`**, łagodny atak 1–2 ramki (`7 -> 13`), płynny Decay `13 -> 9`, `Release = 3`. Przy 15 kHz zakres 8-bit spada aż do **30.50 Hz (`AUDF=$FE`)** (`A1 = 55 Hz` leży idealnie na `AUDF = $8C = 140` z błędem zaledwie `+5` centów!). | Przy włączonym `AUDCTL_15KHZ` ($01) wszystkie nie-1.77MHz kanały korzystają z zegara 15.56 kHz — górny limit dla `AUDF=$00` to 7.78 kHz, ale dla melodycznych kanałów powyżej `A5` można przełączyć `CH1` lub `CH3` na 1.77 MHz albo ograniczyć melodię poniżej `C6`. |
| **Deep Bass** | **Bardzo wysoka** | Para 16-bitowa CH1+CH2 przy zegarze 1.77 MHz (`AUDCTL = $50`), przebieg `$A0`, bezbłędne strojenie poniżej 0.1 centa od `E1 (41.2 Hz)` wzwyż (`E1 = [10, 84]`, `A1 = [243, 62]`), gładka obwiednia `15 -> 12 -> 10`. | Kosztuje 2 kanały (`CH1` jako niemy LSB, `CH2` jako wyjście MSB). |
| **Analog-like Bass** | **Wysoka** | Baza `$A0` (przy 15 kHz lub 16-bit `$50`) + 1–2-ramkowy transjent `$C0` na starcie (`vol=14`) lub krótki sub-punch wysokości (np. `AUDF + 2` w ramce 0 $\rightarrow$ docelowy `AUDF`) z wyraźnym opadaniem głośności. | Wymaga przełączania `AUDC` na pierwszej ramce lub mikro-kopnięcia `AUDF`. |
| **Plucked Bass** | **Bardzo wysoka** | Ostry start (`vol=15` w ramce 0, opcjonalnie `$C0`/`$20` przez 20 ms), po czym szybki wykładniczy Decay bez wysokiego sustainu (`15->12->10->8->7->5->4->3->2`). Potwierdzono w eksperymencie #5 i #6 brak charczenia oraz wyraziste osadzenie na fundamencie `55.0 Hz / 82.5 Hz`. | Brak zastrzeżeń w 15 kHz i 16-bit; przy 64 kHz 8-bit ograniczony wyłącznie do oktawy C3 i wyższych. |
| **Synth Bass** | **Wysoka** | Świadome użycie `$C0` (Poly4) z **dedykowaną tablicą strojenia Poly4** (gdzie faktyczna częstotliwość podstawowa wynosi $\frac{f_{\text{clock}}}{2 \cdot 7{,}5 \cdot (\text{AUDF} + M)}$ i należy bezwzględnie unikać dzielników $(N+1) \bmod 3 = 0$ oraz $(N+1) \bmod 5 = 0$, np. w trybie `AUDCTL_CH1_179MHZ = $40`!). | Przy 1.77 MHz (`$40`) na pojedynczym kanale 8-bit `Poly4` osiąga zakres basowy od `C2 (65 Hz)` do `A3` (ponieważ $1\,773\,447 / (15 \cdot (\text{AUDF}+4))$ dzieli zegar przez **15**, przesuwając oktawy w dół dokładnie o prawie 4 oktawy!). Jest to klasyczny, potężny trik Atari XL/XE (Rob Hubbard / Adam Gilmore) pozwalający na soczysty bas `$C0` bez parowania 16-bit! |
| **Distorted Bass (świadomy efekt)** | **Wysoka** | Przebieg `$20` (Poly5 + pure tone) lub `$00` (Poly5 + Poly17) albo `$80` z włączonym `AUDCTL_9BIT_POLY = $80` i taktowaniem 1.77 MHz (`$40`/`$20`), co daje cykliczny, zgrzytliwy przester basowy w zdefiniowanych wysokościach (z pominięciem wielokrotności 31 w `AUDF+4`). | Wymaga prekompilowanej tablicy strojenia Poly5 / Poly9 (wysokości w skali równomiernej bywają nierównomierne). |

### 5.3 Brzmienia PERCUSSION (Obszar D)

Wszystkie wymienione poniżej instrumenty perkusyjne mogą być odtwarzane zamiennie na **jednym kanale (`CH4`)** dzięki krótkim makrom ramkowym (50 Hz), bez zajmowania dodatkowych głosów:

| Instrument | Czas trwania | Sekwencja ramkowa 50 Hz (`AUDC` \| `vol`, `AUDF`) | Charakter akustyczny |
| :--- | :---: | :--- | :--- |
| **Kick (Stopa)** | 5–6 ramek (100–120 ms) | `F0: $8F, $16` (klik bijaka) $\rightarrow$ `F1: $CF, $3A` (rezonans) $\rightarrow$ `F2: $AD, $6E` $\rightarrow$ `F3: $AA, $A8` $\rightarrow$ `F4: $A7, $DE` $\rightarrow$ `F5: $A3, $FE` | Zdecydowany, krótki klik na starcie przechodzący w szybki spadek czystej fali w dół pasma basowego. |
| **Snare (Werbel)** | 6–7 ramek (120–140 ms) | `F0: $AF, $26` (naciąg) $\rightarrow$ `F1: $CE, $32` (rezonans) $\rightarrow$ `F2: $8D, $0B` (sprężyny) $\rightarrow$ `F3: $8A, $10` $\rightarrow$ `F4: $87, $15` $\rightarrow$ `F5: $84, $1A` $\rightarrow$ `F6: $82, $20` | Czytelny dwuskładnikowy werbel: tonalne uderzenie membrany (20–40 ms) przechodzące w jasny, wygasający szum. |
| **Closed Hi-Hat** | 2 ramki (40 ms) | `F0: $8B, $02` (~10.5 kHz próbkowania szumu) $\rightarrow$ `F1: $84, $04` $\rightarrow$ `F2: $00` (cisza) | Bardzo krótki, ostry metaliczny cykot, wyraźnie odseparowany widmowo od stopy i werbla. |
| **Open Hi-Hat** | 7–8 ramek (140–160 ms) | `F0: $8C, $02` $\rightarrow$ `F1..F6`: przeplot `$80`/`$00` na `AUDF = $03 <-> $06`, płynne opadanie `vol = 10->8->7->5->3->2->1` | Rozsypane syczące wybrzmienie bez wrażenia niskiego dudnienia. |
| **Cymbal (Crash/Ride)** | 12–16 ramek (240–320 ms) | `F0: $2E, $07` (dzwon) $\rightarrow$ `F1: $0C, $04` $\rightarrow$ `F2..F13`: naprzemiennie `$80 @ $03` i `$00 @ $07` z opadaniem `11->10->9->8->7->6->5->4->3->2->1` | Złożony metaliczny transjent na starcie z długim, ziarnistym ogonem szumowym. |
| **Tom (Hi / Mid / Low)** | 5–6 ramek (100–120 ms) | `F0: $CE, base` $\rightarrow$ `F1..F5`: `$A0` z narastającym dzielnikiem `+10..+16`/ramkę (`Hi: $2C->$78`, `Mid: $44->$A4`, `Low: $5C->$DC`) i zanikiem `13->11->8->5->2` | Tonalny bęben z wyraźną wysokością i opadającym strojem. |
| **Noise Percussion (Clap / Rim)** | 2–5 ramek | *Rimshot*: `F0: $CF, $14`, `F1: $88, $08`. *Clap*: 3 szybkie impulsy `F0: $8D,$0A` $\rightarrow$ `F1: $83,$0E` $\rightarrow$ `F2: $8F,$0C` $\rightarrow$ `F3..4: $89->84` | Wyraziste akcenty rytmiczne z mikro-modulacją głośności imitującą wielokrotne klaśnięcie. |

---

## 6. Propozycja rozszerzenia modelu instrumentów

### 6.1 Ocena przydatności kandydujących parametrów dla POKEY

| Parametr | Ocena dla POKEY | Rola i uzasadnienie techniczne |
| :--- | :---: | :--- |
| **`attack`** (`attack_frames`) | **Krytyczny** | Niezbędny do miękkiego narastania (`Soft Lead/Bass`); wymaga naprawy obecnego 2-poziomowego skoku na liniową rampę. |
| **`decay`** (`decay_frames` / `decay_rate`) | **Krytyczny** | Warunek istnienia brzmień `Plucked`, `Bell`, naturalnego basu i krótkiej perkusji; wymaga naprawy błędu zerowego nachylenia w `player.asm`. |
| **`sustain`** (`sustain_vol` 0..15) | **Krytyczny** | Już obecny i poprawny jako docelowy poziom po fazie Decay. |
| **`release`** (`release_frames`) | **Wysoka** | Po naprawie błędu jednostek (ramki VBI zamiast ticków) pozwala na kontrolowane wygaszanie ogona nut niezależnie od tempa. |
| **`vibrato_depth`** | **Wysoka** | Wyrazić najlepiej jako krok w jednostkach `AUDF` (`0..3` w 6502) lub półtonach konwertowanych kontekstowo w IR z uwzględnieniem ostrości wysokich rejestrów. |
| **`vibrato_speed`** | **Wysoka** | Jako dzielnik ramek VBI (`1..8`) sterujący szybkością przejścia 8-krokowej tablicy LFO (np. co 2 ramki = 6.25 Hz). Warto uzupełnić o **`vibrato_delay`**. |
| **`pitch_envelope`** (`pitch_delta`) | **Krytyczna** | Podpisany krok zmiany `AUDF` na ramkę (np. `-16..+31`); jednym mechanizmem realizuje kick/tom pitch drop, punch basowy oraz scoop leadów. |
| **`pitch_decay`** (`pitch_env_frames`) | **Krytyczna** | Czas trwania (w ramkach VBI) działania obwiedni `pitch_envelope`, po którym kanał wraca do wysokości nominalnej lub utrzymuje osiągniętą wartość. |
| **`volume_envelope`** | **Wysoka (jako ADSR + makro)** | W 90% nut melodycznych/basowych wystarcza naprawione 4-parametrowe ADSR (4 bajty); dla perkusji i `Bell` warto udostępnić indeks krótkiej tablicy krokowej 50 Hz. |
| **`modulation_depth` / `modulation_speed`** | **Niska / Zbędna abstrakcja** | POKEY nie ma matrycy FM/LFO ogólnego przeznaczenia. Zamiast abstrakcyjnego `modulation_depth/speed` znacznie lepiej zastosować jawne parametry sprzętowe: **`attack_distortion`** (barwa na transjencie) + `vibrato_*` + tryb **`pulse/arp`**. |
| **`noise_character`** | **Wysoka (dla perkusji i basu)** | Mapuje się bezpośrednio na selekcję trybu POKEY (`$80` Poly17 czysty szum, `$00` Poly5+Poly17 ziarnisty, `$C0` Poly4 bzyczący, `$20` Poly5 metaliczny) oraz bit 7 `AUDCTL` (szum 9-bitowy `$80`). |

### 6.2 Proponowany model danych (Python IR + 6502 Format Version 2)

Projekt powinien ewoluować z zachowaniem **pełnej kompatybilności wstecznej**: jeśli utwór nie używa nowych pól, wyjściowy kod zachowuje identyczną semantykę.

#### A. Warstwa Python (`IRInstrument` w `src/atari_music/ir.py`)
```python
class IRInstrument(BaseModel):
    # Istniejące pola (100% kompatybilności wstecznej)
    id: int
    name: str
    distortion: int = DISTORTION_PURE_TONE
    role: str = "melody"
    envelope: IREnvelope = Field(default_factory=IREnvelope)
    is_16bit: bool = False
    audctl: Optional[int] = None
    modulation: int = pokey_hw.MODULATION_NONE

    # Aktywowane / rozszerzone pola (Format Version 2)
    attack_distortion: Optional[int] = None      # np. $20 lub $C0 dla transjentu ataku
    attack_dist_frames: int = Field(default=0, ge=0, le=15)
    pitch_env_delta: int = Field(default=0, ge=-64, le=64)  # zmiana AUDF na ramkę
    pitch_env_frames: int = Field(default=0, ge=0, le=31)
    vibrato_depth: int = Field(default=0, ge=0, le=7)        # głębia w jednostkach AUDF
    vibrato_speed: int = Field(default=2, ge=1, le=8)        # dzielnik VBI
    vibrato_delay: int = Field(default=8, ge=0, le=31)       # opóźnienie wejścia (ramki)
    glide_speed: int = Field(default=0, ge=0, le=31)         # portamento (AUDF/ramkę)
    noise_character: Optional[str] = None                    # "poly17" | "poly9" | "poly5_noise" | "poly4"
    macro: Optional[List[IRMacroStep]] = None                # aktywne dla perkusji i dzwonków
```

#### B. Warstwa binarna 6502 (`Format Version 2` w `mads_exporter.py` i `player.asm`)
Zamiast sztywnej tablicy `4 kanały × 6 B`, Format Version 2 wprowadza **słownik $N$ instrumentów (np. $N = 8..16$) po 10 bajtów na instrument** + kompaktową tablicę makr perkusyjnych:

```text
Rekord instrumentu Format v2 (10 bajtów / instrument):
+0: dist_sustain      ($00..$E0) — główna barwa kanału
+1: dist_attack       ($00..$E0) — barwa w pierwszych `att_dist_frames` ramkach
+2: env_att_speed     (0..15)     — liczba ramek narastania Attack
+3: env_dec_rate      (0..15)     — ramki na spadek głośności o -1 w fazie Decay
+4: env_sus_vol       (0..15)     — docelowy poziom Sustain
+5: env_rel_frames    (0..15)     — liczba ramek wygaszania Release (w ramkach VBI!)
+6: mod_flags         (bity 0..2: mod_type [0=none,1=oct_pulse,2=vibrato,3=glide,4=hpf_pwm];
                       bit 3: pitch_env_hold; bity 4..7: att_dist_frames [0..15])
+7: pitch_env_delta   (signed byte -128..+127 dodawany do AUDF w fazie pitch env)
+8: pitch_env_frames  (czas działania obwiedni wysokości w ramkach VBI)
+9: vib_params        (bity 7..4: vib_delay / 2; bity 3..2: vib_depth; bity 1..0: vib_rate)
```

- **Kodowanie wielu instrumentów na kanale bez rozdmuchiwania strumienia nut**: W obecnym strumieniu nut `.byte audf, dur, vol` bajt `$FF` jest końcem ścieżki. Zarezerwowanie wartości `$FE` jako 2-bajtowego opcodu **`.byte $FE, inst_id`** (gdzie `AUDF_TRACKER_MAX` przesuwa się z `$FE` na `$FD`, co zmienia najniższą częstotliwość 64 kHz z `124.19 Hz` na `124.68 Hz` — różnica pomijalna, a przy zegarze 15 kHz i tak zbędna poniżej 31 Hz!) umożliwia **dynamiczną zmianę instrumentu w dowolnym punkcie ścieżki** przy zerowym narzucie dla nut, które nie zmieniają barwy.
- **Kodowanie zestawu perkusyjnego na CH4 bez opcodu**: Na kanale przypisanym do perkusji wartości `audf` z zakresu `$F0..$F7` mogą bezpośrednio wywoływać wbudowane 4–8-krokowe makra `(AUDC, AUDF)` w ROM (np. `$F0` = Kick, `$F1` = Snare, `$F2` = CHat, `$F3` = OHat, `$F4` = Tom, `$F5` = Cymbal, `$F6` = Clap). Ścieżka zachowuje dokładnie obecny format 3 bajty na uderzenie!

---

## 7. Przykładowa lista instrumentów demonstracyjnych i wyniki eksperymentów WAV

### 7.1 Zestaw 12 instrumentów demonstracyjnych

| # | Nazwa instrumentu | Rola | Technika syntezy | Wykorzystanie POKEY (`AUDC`, `AUDCTL`, zegar) | Parametry zmienne w czasie (50 Hz) | Oczekiwany efekt dźwiękowy | Główne ograniczenie | Szacowany koszt (ROM/RAM/CPU) |
| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `Expressive Vibrato Lead` | Lead | Liniowy ADSR + Scoop + Delayed Vibrato | `$A0`, `64 kHz` | `vol`: rampa 3f; `AUDF`: `+2->0` w 2f, po `8f` trójkąt `±1` @ 6.25 Hz | Śpiewny, ciepły głos główny bez mechanicznego sztywnienia | W oktawie 6 (`AUDF < $24`) vibrato ograniczone do `±1` | ~85 B ROM, 8 B RAM, ~35 cykli/f |
| 2 | `Dynamic Plucked Lead` | Lead | Dynamiczny przeplot barw + szybki Decay | `$20 -> $C0 -> $A0`, `64 kHz` | `F0`: `$20,v15`; `F1`: `$C0,v13`; `F2+`: `$A0` opad `11->2` | Wyraźne szarpnięcie struny z wysoką dynamiką ataku | Wymaga naprawionego Decay oraz `attack_distortion` | ~50 B ROM, 2 B RAM, ~15 cykli/f |
| 3 | `Metallic Bell Lead` | Lead | Oktawowy atak + wykładnicze wygaszanie | `$20 / $C0 -> $A0`, `64 kHz` | `F0`: `$20, AUDF>>1, v15`; `F1`: `$C0,v12`; `F2..16`: `$A0, v11..1` | Szklisty dzwonek o jasnym transjencie | Brak prawdziwej syntezy FM (przybliżenie alikwotami) | ~70 B ROM, 2 B RAM, ~20 cykli/f |
| 4 | `HPF PWM Synth Lead` | Lead | Filtr górnoprzepustowy XOR jako modulator PWM | `$A0` na CH1 + niemy zegar CH3, `AUDCTL |= $04` | `AUDF3 = AUDF1 + LFO(0..2)` co kilka ramek | Tłusty, płynący lead typu synthwave/C64-PWM | Zużywa dodatkowy kanał CH3 jako modulator | ~50 B ROM, 4 B RAM, ~25 cykli/f |
| 5 | `Warm 15kHz Sub Bass` | Bass | Niski zegar bazowy + czysty ton + rampa | `$A0`, `AUDCTL = $01` (`15.56 kHz`) | `vol`: szybka rampa `2f -> 14`, opad do `10` | Gładki, głęboki dół (do A1=55 Hz) zero charczenia | Ogranicza górny pułap pozostałych kanałów 15 kHz do 7.78 kHz | **0 B w 6502** (konfiguracja IR + naprawiony ADSR) |
| 6 | `16-Bit 1.79MHz Punch` | Bass | Para 16-bit 1.77 MHz + Pitch Drop na starcie | `$A0` na CH2 (`CH1` LSB niemy), `AUDCTL = $50` | `F0..1`: podbicie dzielnika / szybki spadek + Decay `15->10` | Precyzyjny co do < 0.1 centa, potężny bas z uderzeniem | Zajmuje kanały CH1+CH2 | ~25 B kodu dla pitch-punch 16-bit |
| 7 | `Tuned Poly4 Synth Bass` | Bass | Poly4 na zegarze 1.77 MHz z LUT bezpiecznych dzielników | `$C0` na CH1 (`AUDCTL = $40`, `1.77 MHz`) | Stała tablica `AUDF` unikająca $(N+4)\bmod 3=0$ i $\bmod 5=0$ | Klasyczny, warczący ale nastrojony bas Atari na 1 kanale | Krótsza skala strojenia niż 16-bit, niektóre nuty lekko odstrojone | **0 B w 6502** (LUT w Pythonie), poświęca `CH1` na `1.77MHz` |
| 8 | `9-Bit Industrial Bass` | Bass | Poly5/Poly9 w trybie przesterowanym (świadomy efekt) | `$20` / `$80`, `AUDCTL = $80 | $40` | Ręcznie dobrany LUT + szybkie wygaszanie `15->6` | Agresywny bas industrialny zamiast przypadkowego brzęczenia | `AUDCTL` bit 7 wpływa na szum także w perkusji CH4 | ~0–20 B (ustawienie `AUDCTL` + LUT w Pythonie) |
| 9 | `Articulated POKEY Kick` | Perc | 6-ramkowe makro multi-waveform z Pitch Dropem | `$80 -> $C0 -> $A0`, `CH4` | `AUDF`: `$16->$3A->$6E->$A8->$DE->$FE`; `vol`: `15->15->13->10->7->3` | Mięsisty transjent stopy z odczuwalnym dołem | Wyłącznie na 1 głos (CH4) | ~18 B tabeli makra + silnik makr |
| 10 | `Dual-Transient Snare` | Perc | Przejście membrana $\rightarrow$ rezonans $\rightarrow$ szum sprężyn | `$A0 -> $C0 -> $80`, `CH4` | `F0`: `$AF,$26`; `F1`: `$CE,$32`; `F2..6`: `$8D..82`, `$0B..$20` | Wyrazisty trzask werbla oddzielony od stopy i hi-hatu | Jak wyżej (wymaga sekwencera makr 50 Hz) | ~21 B tabeli makra + silnik makr |
| 11 | `Crisp / Shimmer Hi-Hat` | Perc | Krótki szum wysokoczęstotliwościowy + bramkowanie Poly5 | `$80` (CHat) / `$80<->$00` (OHat), `CH4` | `CHat`: 2 ramki `AUDF $02->$04, v11->4`; `OHat`: 7f przeplot `$03/$06` | Krystaliczna cyzelacja hi-hatów bez mulenia basowego pasma | Zegar 64 kHz ogranicza najwyższe składowe do ~10–15 kHz | ~18 B obu makr łącznie |
| 12 | `Pitched Electronic Tom` | Perc | Tonalny spadek dzielnika po krótkim kliknięciu Poly4 | `$C0 -> $A0`, `CH4` | `F0`: `$CE, base`; `F1..5`: `$A0`, `AUDF += 12`/f, `v13..2` | Wyraźne przejścia perkusyjne (High/Mid/Low Tom) | Jeśli `AUDF` przekroczy `$FE`, następuje obcięcie | ~18 B tabeli / lub obwiednia wysokości na nucie |

### 7.2 Empiryczna analiza porównawcza prototypowych renderów WAV

W ramach weryfikacji teoretycznych wniosków wyrenderowano przy użyciu `pokey_synth.render_pokey_to_wav()` zestaw 8 kontrolowanych plików WAV (zapisanych poza bazą projektu w katalogu tymczasowym sesji) oraz zmierzono ich parametry sygnałowe (poziom RMS, Crest Factor, Zero-Crossing Rate, Spectral Centroid, dominantę FFT oraz dynamikę transjentu względem ogona w oknie `0–40 ms` vs `40–200 ms`):

| Plik WAV (katalog `scratch/audit_exp/`) | Wariant i konfiguracja | Czas [s] | RMS [dBFS] | Crest [dB] | ZCR [Hz] | Spectral Centroid [Hz] | Dominanta FFT całego pliku / 1. nuty [Hz] | Transient-to-Tail (0–40 vs 40–200 ms) [dB] | Obserwacja analityczna |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `01_lead_baseline.wav` | **LEAD Baza**: `$A0`, obecny zepsuty ADSR (`player_envelope_volumes`) | 1.60 | -10.73 | 9.82 | 675.3 | 6447.0 | 660.0 / 440.0 | +2.54 | Po 1 ramce szczytu głośność spada na płaskie sustain; brak jakiegokolwiek ruchu intonacji lub barwy. |
| `02_lead_expressive_vibrato.wav` | **LEAD Prototyp A**: `$A0`, płynny Attack 3f + Scoop `+2->0` + opóźnione Vibrato 6.25 Hz | 1.60 | -7.82 | 6.91 | 673.8 | 6644.8 | 662.5 / 442.5 | -6.86 | Ujemny wynik `T2T` potwierdza prawdziwe miękkie narastanie (`Attack` bez skokowego kliku) oraz śpiewne wypełnienie nuty. |
| `03_lead_dynamic_pluck.wav` | **LEAD Prototyp B**: przełączenie `$20 -> $C0 -> $A0` + wykładnicze opadanie | 1.60 | -16.57 | 15.66 | 986.6 | 8287.3 | 659.4 / 440.0 | **+10.67** | Ponad **4-krotny wzrost kontrastu transjentu** (`+10.67 dB` vs `+2.54 dB`), jasny szarpany atak (`Centroid 8287 Hz`) i naturalne wygaszanie. |
| `04_bass_baseline_8bit_clamped.wav` | **BASS Baza**: `64 kHz`, `$C0`, nuty basowe A1–G2 obcięte na `AUDF=$FE` | 1.60 | -11.61 | 10.70 | 496.6 | 5963.9 | **372.5 / 372.5** | +3.05 | **Brak prawidłowego fundamentu basowego**: wszystkie nuty obcięte na `124.2 Hz`, a błąd fazy Poly4 w syntezatorze podbija dominantę do **372.5 Hz** i centroid do **5.96 kHz** (jazgot). |
| `05_bass_15khz_natural.wav` | **BASS Prototyp A**: zegar `15.56 kHz` (`AUDCTL=$01`), `$A0`, płynny Decay | 1.60 | -12.33 | 11.42 | 75.3 | 4279.6 | **82.5 / 55.0** | +2.35 | Odzyskanie dokładnych częstotliwości bazowych **A1 (55.0 Hz)** i **E2 (82.5 Hz)**; środek ciężkości widma niższy o **-1684.3 Hz** względem bazy `$C0`, czysta barwa dołu. |
| `06_bass_16bit_179mhz_punch.wav` | **BASS Prototyp B**: 16-bit `1.77 MHz` (`AUDCTL=$50`), `$A0` + 2-ramkowy Sub-Punch + Decay | 1.60 | -12.09 | 11.18 | 77.5 | 4118.2 | **82.5 / 55.0** | +2.07 | Najczystszy fundament **82.5 / 55.0 Hz** oraz jeszcze ciemniejszy, naturalny profil widmowy (`Centroid 4118 Hz`) bez śladu charczenia. |
| `07_perc_baseline_monotonous.wav` | **PERC Baza**: 4 uderzenia (Kick, CHat, Snare, OHat) jako `$80 @ $50` z `sus=8` | 1.28 | -21.76 | 20.85 | 75.0 | 4048.6 | 134.4 / 132.5 | +13.08 | Rozkład per-uderzenie niemal identyczny: centroidy w wąskim paśmie **3882–4244 Hz** (`Δ = 363 Hz`), ZCR **47–97 Hz**. Wszystkie bębny brzmią jak ten sam szum. |
| `08_perc_macro_articulated.wav` | **PERC Prototyp**: makra 50 Hz (Kick pitch drop, CHat `$02`, Snare `$A0->$C0->$80`, OHat `$80/$00`) | 1.28 | -16.91 | 15.99 | **1157.8** | **6852.9** | 864.8 / 442.5 | +11.08 | Pełna separacja widmowa zestawu: Kick (`Centroid 5503 Hz, ZCR 325 Hz`), CHat (`dom 2819 Hz, Centroid 7632 Hz`), Snare (`dom 866 Hz`), OHat (`Centroid 8855 Hz, ZCR 3122 Hz`). Rozpiętość centroidu między bębnami wzrosła ponad **9-krotnie (`Δ = 3352 Hz`)**. |

*(Uwaga metodologiczna: ze względu na błąd indeksowania fazowego `POLY4` i `POLY5` obecny w `pokey_synth.py`, pliki eksperymentalne odtwarzane były przez aktualny niezmodyfikowany renderer WAV projektu — w szczególności w pliku `04` widoczna jest wspomniana fałszywa dominanta `372.5 Hz`, zaś po naprawie syntezy `POLY4` zgodnej ze sprzętem rzeczywiste bębny i bas `$C0` będą miały dokładnie skorygowaną charakterystykę fazową jak w §2.4.)*

---

## 8. Ranking rekomendowanych ulepszeń

### PRIORYTET 1 — Duży efekt, niewielki koszt (Quick Wins)

#### P1.1: Naprawa maszyny stanów ADSR w `player.asm` i `pokey_hw.py`
- **Opis problemu**: Obecna funkcja `update_envelopes` w [player.asm#L455-L547](player.asm#L455-L547) realizuje Attack jako dwupunktowy skok `(peak>>1)|1`, całkowicie ignoruje nachylenie Decay (`decay_frames` działa tylko jako opóźnienie ze stałą głośnością `sustain`), a Release wyzwala porównując czas w tickach (`ch_dur`) z parametrem w ramkach (`ch_rel`). Ponadto błąd przy maskowaniu `ch_mute_mask` zapisuje `$01` do `AUDCn` zamiast `$00`.
- **Proponowane rozwiązanie**: Zastąpienie `@phase_attack` rampą liniową (np. krok proporcjonalny lub stałoprzecinkowy dodawany do `ch_cur_vol`), implementacja rzeczywistego opadania w `@phase_decay` (`ch_cur_vol` maleje o 1 co `ch_dec` ramek aż osiągnie `ch_sus`), przeliczanie warunku Release na podstawie licznika pozostałych ramek VBI (`remaining_ticks * tempo_divider + tick_counter <= ch_rel`) oraz wyzerowanie akumulatora przed zapisem w gałęziach `@mute_ch*`. Analogiczna aktualizacja modelu referencyjnego w `pokey_hw.player_envelope_volumes()`.
- **Oczekiwany efekt**: Natychmiastowe odblokowanie miękkich wejść (`Soft Lead/Bass`), realnych wybrzmień (`Plucked`, `Bell`) i czystego wygaszania nut przy zachowaniu obecnego formatu danych.
- **Wpływ na CPU**: +15..25 cykli na aktywny kanał (~80 cykli / ramkę VBI — poniżej 0.3% czasu ramki PAL).
- **Wpływ na pamięć**: ~+50 B kodu w `player.asm`, +4..8 B zmiennych RAM; 0 dodatkowych bajtów w danych utworów.
- **Wpływ na format SAP i kompatybilność**: **100% wstecznej kompatybilności** — nie zmienia nagłówka, tablic instrumentów ani 3-bajtowych zdarzeń nutowych; w pełni zgodne z interfejsem SAP `TYPE B`.
- **Poziom trudności implementacji**: Niski.

#### P1.2: Wyeliminowanie obcinania basu na `AUDF = $FE` (`bass_engine.py` oraz `ir.resolve_audctl_mode`)
- **Opis problemu**: 54.2%–100% nut basowych w trybie 8-bit spada poniżej dolnego limitu `124.19 Hz` zegara 64 kHz i zostaje spłaszczonych do jednego dzielnika `AUDF = $FE`, co razem z `$C0` daje jednostajne charczenie o okresie `16.6 Hz`.
- **Proponowane rozwiązanie**:
  1. Gdy linia basowa nie używa trybu 16-bit i zawiera nuty $< 125\text{ Hz}$ (a prowadzenie melodii nie wymaga oktaw powyżej `B7`), w `resolve_audctl_mode()` automatycznie aktywować zegar bazowy **15.56 kHz (`AUDCTL |= $01`)** wraz z czystym przebiegiem **`$A0`** dla basu (opcjonalnie z przełączeniem melodiowych kanałów CH1/CH3 na 1.77 MHz lub ograniczeniem ich rejestru do $f \le 7.78\text{ kHz}$).
  2. Gdy aktywny jest tryb `uses_16bit_bass = True`, ustawiać w `resolve_audctl_mode()` **`$50` (`$10 | $40`)** zamiast `$10`, taktując parę CH1+CH2 pełnym zegarem **1.77 MHz**.
  3. Zaktualizować `find_pitch_range_issues()` w `ir.py`, aby przekazywał rzeczywisty `audctl` i numer kanału do `describe_8bit_range_error()`.
- **Oczekiwany efekt**: Natychmiastowy odzysk pełnej linii melodycznej basu aż do 30.5 Hz (15 kHz) lub sub-basów (16-bit), usunięcie przypadkowego charczenia i redukcja fałszów w 16-bitowym basie.
- **Wpływ na CPU**: **0 cykli** na 6502 (rozwiązanie po stronie kompilatora IR i bajtu `AUDCTL`).
- **Wpływ na pamięć**: **0 bajtów** w `player.asm` i danych binarnych.
- **Wpływ na format SAP i kompatybilność**: **100% kompatybilne** (`AUDCTL` jest już zapisywany w każdej ramce).
- **Poziom trudności implementacji**: Niski.

#### P1.3: Naprawa syntezy `POLY4` / `POLY5` oraz dodanie filtrów HPF (`$02`/`$04`) w `pokey_synth.py`
- **Opis problemu**: `pokey_synth.py` przyspiesza odczyt `POLY4_SEQ` 7.5-krotnie i `POLY5_SEQ` 15.5-krotnie względem zegara dzielnika oraz ignoruje bity `AUDCTL` filtrów górnoprzepustowych (`$02`, `$04`) i łączenia CH3+CH4 (`$08`).
- **Proponowane rozwiązanie**: Zastąpienie fazy ciągłej dyskretnym akumulatorem kroków dzielnika LFSR (przesuw o 1 krok na każde przepełnienie okresu $T = \frac{1}{2 f}$, analogicznie do `ch_lfsr_steps` w gałęzi `POLY9_17`), co naturalnie odtworzy także zjawisko podzielności przez 3, 5 i 31 z rzeczywistego POKEY. Dodanie symulacji przerzutnika D + bramki XOR dla bitów `$04` i `$02` oraz dekodera `AUDCTL_JOIN_3_4_16BIT`.
- **Oczekiwany efekt**: Podgląd WAV przestaje sztucznie wykrzywiać brzmienia `$C0`, `$20`, `$40` i `$00`, dając wierną symulację akustyczną Atari XL/XE oraz umożliwiając odsłuch efektów HPF/PWM.
- **Wpływ na CPU**: Dotyczy wyłącznie renderera Pythonowego (koszt renderowania pozostaje pomijalny przy wektoryzacji NumPy).
- **Wpływ na pamięć**: 0 bajtów po stronie Atari.
- **Wpływ na format SAP i kompatybilność**: Brak wpływu na SAP/XEX (poprawia wiarygodność narzędzi developerskich).
- **Poziom trudności implementacji**: Niski / Średni.

#### P1.4: Wstępne zróżnicowanie perkusji bez makr w `rhythm_ornament.py` i `ir.py`
- **Opis problemu**: Kick, Snare i Hi-Hat używają tej samej stałej `PERCUSSION_DEFAULT_AUDF = $50` i stałego czasu trwania.
- **Proponowane rozwiązanie**: Wprowadzenie w `SymbolicNote` jawnego tagu typu uderzenia (lub przypisania konkretnego `midi_pitch`/indeksu dzielnika na kanale perkusyjnym) i rozróżnienie docelowego `AUDF` w IR: wysokie `$02–$06` dla Hi-Hat, `$14–$20` dla Snare oraz `$50–$90` z krótkim `duration` dla cięższych uderzeń, do czasu wdrożenia pełnych makr z Priorytetu 2.
- **Oczekiwany efekt**: Wyraźne oddzielenie pasmowe stopy, werbla i hi-hatu nawet przed modyfikacją `player.asm`.
- **Wpływ na CPU**: **0 cykli** na 6502.
- **Wpływ na pamięć**: **0 bajtów** w `player.asm`.
- **Wpływ na format SAP i kompatybilność**: **100% kompatybilne** z Format Version 1.
- **Poziom trudności implementacji**: Niski.

---

### PRIORYTET 2 — Istotne rozszerzenia silnika audio i modelu instrumentów

#### P2.1: Sekwencer krótkich makr perkusyjnych i transjentowych (50 Hz Micro-Macros) w `player.asm`
- **Opis problemu**: Pojedynczy kanał perkusyjny (`CH4`) wymaga zmiany jednocześnie barwy (`AUDC`) i częstotliwości (`AUDF`) na przestrzeni pierwszych 2–8 ramek (40–160 ms), czego nie da się wyrazić pojedynczym rekordem nutowym o ziarnie `frames_per_tick`.
- **Proponowane rozwiązanie**: Zarezerwowanie identyfikatorów uderzeń perkusyjnych (`$F0..$F7`) w bajcie `audf` dla kanału oznaczonego jako perkusyjny (lub dowolnego kanału ze wskaźnikiem makra), które uruchamiają z ROM kompaktowy 4–8-krokowy skrypt par `(AUDC_val, AUDF_val)` (z końcowym znacznikiem `$00`), sterujący bezpośrednio `ch_audf`, `ch_dist` i `ch_cur_vol` co ramkę VBI.
- **Oczekiwany efekt**: Pełny, ekspresyjny zestaw perkusyjny (`Kick` z opadaniem tonu, dwufazowy `Snare`, ostry `Closed Hat`, migoczący `Open Hat`, `Cymbal`, `Toms`) działający na **jednym** kanale POKEY.
- **Wpływ na CPU**: +35..45 cykli na ramkę tylko w trakcie trwania aktywnego makra.
- **Wpływ na pamięć**: ~+140 B kodu w `player.asm` + ~80–120 B wbudowanych tablic makr w ROM + 8 B RAM stanu makr (`ch_macro_id[4]`, `ch_macro_pos[4]`).
- **Wpływ na format SAP i kompatybilność**: W pełni kompatybilne z SAP `TYPE B`; zachowuje 3-bajtowy format zdarzeń w ścieżkach (`$F0..$F7` nie kolidują ze znacznikiem końca `$FF`).
- **Poziom trudności implementacji**: Średni.

#### P2.2: Przełączanie barwy na ataku (`attack_distortion`) oraz obwiednia wysokości (`pitch_envelope`) dla Lead i Bass
- **Opis problemu**: Brzmienia `Plucked`, `Bell`, `Analog Bass` i `Tom` potrzebują bogatego w harmoniczne transjentu na początku nuty (`$20` lub `$C0`) przechodzącego w czysty ton podtrzymania (`$A0`), jak również krótkiego kopnięcia lub podciągu wysokości (`AUDF` delta przez $K$ ramek).
- **Proponowane rozwiązanie**: Rozszerzenie rekordu instrumentu w `Format Version 2` o bajty `dist_attack`, `att_dist_frames`, `pitch_env_delta` oraz `pitch_env_frames`. W `music_update` przez pierwsze `att_dist_frames` ramek nuty używane jest `dist_attack`, a przez pierwsze `pitch_env_frames` modyfikowane jest `ch_audf_base` / `ch_audf` o `pitch_env_delta`.
- **Oczekiwany efekt**: Bogate ataki szarpane, dzwonki, elektroniczne tomy i mięsisty „punch” basowy bez angażowania dodatkowych kanałów.
- **Wpływ na CPU**: +25..35 cykli na kanał używający funkcji.
- **Wpływ na pamięć**: ~+95 B kodu w `player.asm`, +12 B RAM (`ch_att_dist`, `ch_att_dcnt`, `ch_p_cnt`), +4 B na rekord instrumentu.
- **Wpływ na format SAP i kompatybilność**: Wymaga podbicia `SONG_FORMAT_VERSION` z `1` na `2` w `player.asm` i `mads_exporter.py` (z zachowaniem twardej walidacji wersji przy starcie `music_init`); kompatybilne z SAP `TYPE B`.
- **Poziom trudności implementacji**: Średni.

#### P2.3: Sprzętowe opóźnione Vibrato (`Delayed Table Vibrato`) oraz Portamento / Glide w `player.asm` i `ir.py`
- **Opis problemu**: Pola `vibrato_depth`, `vibrato_speed` i `slide_semitones` są odcinane w `ir.py` i `mads_exporter.py`.
- **Proponowane rozwiązanie**: Rozszerzenie `apply_modulation` w `player.asm` o tryby `MOD_VIBRATO = 2` (opóźnienie startu `vib_delay`, 8-bajtowa tablica trójkątna w ROM skalowana przez przesunięcie bitowe) oraz `MOD_GLIDE = 3` (zbliżanie `ch_audf_cur` do docelowego `AUDF` z krokiem `glide_speed`). Równolegle wdrożenie identycznej arytmetyki całkowitej w `pokey_hw.py` i wywołanie jej z `ir.py::_render_note_to_frames()`, aby utrzymać parzystość bit-do-bitu z podglądem WAV.
- **Oczekiwany efekt**: Naturalnie brzmiące, długie nuty `Soft Lead` / `Retro Lead` oraz płynne przejścia `Acid` / syntetyczne glissanda przy pełnej zgodności WAV $\equiv$ Atari.
- **Wpływ na CPU**: +30..40 cykli na kanał z aktywnym vibrato/glide.
- **Wpływ na pamięć**: ~+90 B kodu + 8 B tablicy ROM + 8–12 B RAM (`ch_vib_pos[4]`, `ch_vib_wait[4]`, `ch_target_audf[4]`).
- **Wpływ na format SAP i kompatybilność**: Format Version 2; pełna zgodność z SAP `TYPE B` i grami.
- **Poziom trudności implementacji**: Średni.

#### P2.4: Dynamiczna zmiana instrumentu w ścieżce (Inline Opcode `$FE, inst_id`)
- **Opis problemu**: Każda ścieżka skazana jest na jeden statyczny instrument od początku do końca utworu (`_resolve_channel_instrument` i `load_inst_loop`).
- **Proponowane rozwiązanie**: Przekształcenie tablicy instrumentów z `4 × N B` na indeksowaną bibliotekę $K$ instrumentów (np. $K \le 16$ rekordów po 10 B = max 160 B). W 3-bajtowym strumieniu ścieżki zarezerwowanie wartości `$FE` jako 2-bajtowej komendy `.byte $FE, inst_idx` (przy zawężeniu `AUDF_TRACKER_MAX` z `$FE` na `$FD` — przesunięcie najniższego dźwięku 64 kHz o zaledwie 0.48 Hz, a przy basie 15 kHz lub 16-bit zupełnie bez znaczenia). W `fetch_channel_note` po wykryciu `$FE` następuje podmiana parametrów instrumentu kanału `X` i odczyt kolejnego zdarzenia nutowego w tym samym ticku.
- **Oczekiwany efekt**: Pełna wieloinstrumentowość na każdym kanale (np. zmiana z `Plucked Lead` w zwrotce na `Soft Vibrato Lead` w refrenie albo z `Pitched Tom` na `Hi-Hat` na tym samym kanale).
- **Wpływ na CPU**: +45 cykli **wyłącznie w ramce przełączenia instrumentu** (0 narzutu w pozostałych ramkach).
- **Wpływ na pamięć**: ~+70 B kodu w `player.asm` + słownik instrumentów w danych utworu (~60–160 B); +2 B na każdą zmianę instrumentu w strumieniu nut.
- **Wpływ na format SAP i kompatybilność**: Wymaga Format Version 2; w pełni zgodne z SAP `TYPE B`.
- **Poziom trudności implementacji**: Średni.

---

### PRIORYTET 3 — Zaawansowane i eksperymentalne możliwości syntezy

#### P3.1: Dedykowane tablice strojenia nieliniowego dla Poly4 (`$C0`), Poly5 (`$20`) i Poly9 (`$80 + AUDCTL $80`)
- **Opis problemu**: Obliczanie `AUDF` wzorem dla fali prostokątnej podczas korzystania z `$C0` lub `$20` powoduje fałsze (częstotliwość fundamentalna Poly4 jest niższa o współczynnik $7.5$, a Poly5 o $15.5$, dodatkowo na dzielnikach podzielnych przez 3, 5 lub 31 generatory tracą stabilność).
- **Proponowane rozwiązanie**: Wygenerowanie i wbudowanie w `pokey_hw.py` zweryfikowanych tablic strojenia LUT (dla zegarów 64 kHz i 1.77 MHz), mapujących żądane wysokości MIDI na najbliższe stabilne dzielniki z wyłączeniem zabronionych wielokrotności $(N+M) \bmod 3 = 0$, $\bmod 5 = 0$ oraz $\bmod 31 = 0$ (ze zwracaniem błędu odstrojenia w centach dla kompozytora).
- **Oczekiwany efekt**: Możliwość wykorzystania klasycznego, soczystego **1-kanałowego basu `$C0` @ 1.77 MHz (`AUDCTL` `$40`/`$20`)** oraz czystego brzmienia `Metallic Lead` `$20` bez fałszy i przypadkowej utraty dźwięku.
- **Wpływ na CPU**: **0 cykli** na 6502 (strojenie liczone jest statycznie w kompilatorze Python podczas konwersji nut na bajty `AUDF`).
- **Wpływ na pamięć**: **0 bajtów** po stronie Atari.
- **Wpływ na format SAP i kompatybilność**: **100% kompatybilne** z istniejącym formatem.
- **Poziom trudności implementacji**: Średni (wymaga kalibracji psychoakustycznej oraz uprzedniej naprawy `POLY4`/`POLY5` w `pokey_synth.py` z P1.3).

#### P3.2: Synteza PWM / Chorus / Acid Sweep z użyciem filtrów górnoprzepustowych POKEY (`AUDCTL` `$04` / `$02`)
- **Opis problemu**: Statyczny przebieg prostokątny `$A0` nie pozwala na zmianę szerokości impulsu ani efekt przemiatanego filtru.
- **Proponowane rozwiązanie**: Dodanie nowego deskryptora parowanego (analogicznie do 16-bit basu `PairProfile`), aktywującego bit `$04` (CH1 filtrowany przez CH3) lub `$02` (CH2 filtrowany przez CH4), gdzie kanał pomocniczy pracuje z `volume = 0` i `AUDF_clk = AUDF_carrier + offset`, a silnik delikatnie przemiata `offset` (powolne odstrojenie dające ruch fazy PWM lub gwałtowny sweep z góry w dół przy ataku `Acid Lead`).
- **Oczekiwany efekt**: Charakterystyczne, bogate, analogowe „pływanie” fazy (PWM/Phaser) niemożliwe do uzyskania na jednym kanale POKEY.
- **Wpływ na CPU**: +25 cykli na parę kanałów w VBI.
- **Wpływ na pamięć**: ~+50 B kodu w `player.asm`, +4 B RAM stanu przesunięcia.
- **Wpływ na format SAP i kompatybilność**: Kompatybilne z SAP `TYPE B` i grami; wymaga jednak rezerwacji drugiego kanału jako niemego generatora fazy (redukcja polifonii o 1 głos).
- **Poziom trudności implementacji**: Średni / Wysoki.

#### P3.3: Pełna obsługa modulacji 16-bitowych dzielników (`CH1+CH2`) oraz wsparcie drugiej pary (`CH3+CH4`, `AUDCTL` `$08`)
- **Opis problemu**: Obecnie `mads_exporter.py` blokuje wszelkie modulacje na parach 16-bitowych (`ModulationNotExpressibleError`), a `player.asm` nie zawiera ścieżki zapisu dla pary `CH3+CH4`.
- **Proponowane rozwiązanie**: Rozszerzenie `write_pokey_registers` w `player.asm` o obsługę `AUDCTL & $08` (~20 B) oraz umożliwienie 16-bitowego `pitch_envelope` / `vibrato` / `glide` poprzez operację 16-bitową `adc`/`sbc` na parze rejestrów `(ch_audf[lo], ch_audf[hi])`.
- **Oczekiwany efekt**: Możliwość stosowania płynnego portamento, wibrata bez schodków kwantyzacji w oktawach solowych (Lead 16-bit) oraz dwóch niezależnych kanałów 16-bitowych jednocześnie (`AUDCTL = $78` w kompozycjach bez perkusji).
- **Wpływ na CPU**: +20..35 cykli na parę 16-bitową.
- **Wpływ na pamięć**: ~+65 B kodu w `player.asm`.
- **Wpływ na format SAP i kompatybilność**: Format Version 2; pełna zgodność z SAP `TYPE B`.
- **Poziom trudności implementacji**: Średni.

---

## 9. Proponowana roadmapa rozwoju

Wdrożenie ulepszeń zaleca się przeprowadzić w czterech przyrostowych etapach z twardymi bramkami weryfikacji (testy jednostkowe `pytest`, emulacja 6502 `py65` porównująca zapisy `$D200–$D208` bit-do-bitu ze strumieniem `compile_ir_to_pokey_frames()`, kontrola rozmiaru w `stage15` oraz analiza widmowa WAV).

| Etap | Zakres prac (ID rekomendacji) | Szacowany rozmiar `player.asm` (limit `< 2048 B`) | Zapas pamięci w limicie 2 KB | Bramka weryfikacji (Definition of Done) |
| :--- | :--- | :---: | :---: | :--- |
| **Etap 1: Naprawa fundamentów i błędów krytycznych** | **P1.1** (Naprawa ADSR + `ch_mute_mask`), **P1.2** (`AUDCTL $01/$50` dla basu + `find_pitch_range_issues`), **P1.3** (Naprawa `POLY4`/`POLY5`/HPF w `pokey_synth.py`), **P1.4** (Różnicowanie `AUDF` perkusji) | **~1066 B** *(+50 B)* | **982 B** | Format danych v1 bez zmian; 100% zgodności `py65` vs `pokey_hw.player_envelope_volumes()`; 0 obciętych nut basowych na `$FE` dla 6 profili `ComposerV4`; poprawna częstotliwość podstawowa `$C0` i `$20` w FFT WAV. |
| **Etap 2: Ewolucja brzmienia w czasie (`Format Version 2`)** | **P2.1** (Makra perkusyjne `$F0..$F7`), **P2.2** (`attack_distortion` + `pitch_envelope`), **P2.3** (`Delayed Vibrato` + `Portamento/Glide`) | **~1410 B** *(+344 B)* | **638 B** | Podbicie `SONG_FORMAT_VERSION = 2` (twarde odrzucenie niezgodnej wersji w `music_init`); parzystość rejestrów WAV $\equiv$ `py65` dla makr, ataku i vibrato; wyraźna separacja widmowa Kick/Snare/CHat/OHat. |
| **Etap 3: Wieloinstrumentowość i strojenie nieliniowe** | **P2.4** (Inline opcode `$FE, inst_id`), **P3.1** (Tablice LUT dla `$C0 @ 1.77 MHz`, `$20`, `$80+9bit`), aktualizacja bibliotek w `data/instrument_libraries/` i schematów AI | **~1490 B** *(+80 B)* | **558 B** | Obsługa wielu instrumentów per kanał w ścieżce AI i `ComposerV4`; nastrojony bas `$C0 @ 1.77 MHz` zweryfikowany pomiarowo (błąd $\le 20$ centów dla dostępnych stopni LUT); walidacja `xex_layout.py`. |
| **Etap 4: Zaawansowane tryby sprzętowe POKEY** | **P3.2** (Tryby parowane `HPF_PWM` na `$04`/`$02`), **P3.3** (Pełna modulacja 16-bit + `CH3+CH4` `$08`) | **~1605 B** *(+115 B)* | **443 B** | Pełna symulacja filtrów HPF w `pokey_synth.py` i `player.asm`; wsparcie `16-bit vibrato` i `AUDCTL $08/$28` przy bezpiecznym utrzymaniu budżetu sterownika poniżej **~1.6 KB** (z ponad 440 B rezerwy pod limit 2048 B). |

### Podsumowanie budżetu po pełnym wdrożeniu (Etap 1–4)
- **Rozmiar docelowy `player.asm`**: ~1605 bajtów (< 79% dopuszczalnego budżetu `2048 B` w `stage15.PLAYER_SIZE_LIMIT_BYTES`).
- **Strona zerowa (Zero Page)**: bez zmian lub maksymalnie +2..4 bajty (łącznie $\le 14$ B z 128 B dostępnych w `$80..$FF`).
- **Kompatybilność**: Całkowicie zachowana zgodność z architekturą VBI 50 Hz, wymogami pamięciowymi `<= $BFFF`, grami oraz kontenerem SAP `TYPE B`.
