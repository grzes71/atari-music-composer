# Eksperyment badawczy: Jednokanałowe instrumenty perkusyjne z Atari Rhytmizer w Atari Music Composer

- **Źródło referencyjne brzmienia i parametrów:** `rhytmizer.xex` (*Rythmizer AT1*, `(c) MUNSIE 1986`) oraz dokumentacja reverse engineeringu w [`docs/reverse_engineering/`](docs/reverse_engineering/) (`RHYTMIZER_RESEARCH_REPORT.md`, `rhytmizer_sound_engine.md`, `rhytmizer_instrument_catalog.md`, `rhytmizer_compatibility.md`, `rhytmizer_verification_report.md`)
- **Referencyjny emulator POKEY:** `ASAP 8.0.0` (`tools/asap_all/asapconv.exe`, PAL 50 Hz / `1,773,447.0 Hz`)
- **Środowisko izolacji prototypu:** [`experiments/rhytmizer_drums/`](experiments/rhytmizer_drums/) (zero zmian w produkcyjnym `src/atari_music/asm/player.asm`, eksporterach, modelach danych, `data/instruments/catalog.json`, testach produkcyjnych ani w `rhytmizer.xex`)

---

## 1. Opis architektury eksperymentalnego rozwiązania

### 1.1 Punkt wyjścia (architektura bazowa Composera)
Przed rozpoczęciem eksperymentu zweryfikowano stan bieżącej gałęzi:
- **Produkcyjny player (`src/atari_music/asm/player.asm`):** `1,785` bajtów wg `measure_player_size()` (`1,632` B kodu wykonywalnego + `147` B zmiennych BSS/RAM + `6` B nagłówka segmentu DOS XEX `$FF $FF $00 $60 $F2 $66`; czysty payload code+BSS = `1,779` B).
- **Zero Page:** `10` bajtów (`PLAYER_ZP_BASE + 0..9`, domyślnie `$80..$89`).
- **Twardy limit budżetu (`src/atari_music/player_budget.py`):** ściśle `< 2048` bajtów dla złożonego playera (`262` B zapasu w stanie bazowym).
- **Scheduler i aktualizacja POKEY:** pojedyncze wywołanie `music_update` na każdą ramkę PAL (`50 Hz`, `20.000 ms`), sekwencyjna pętla po 4 kanałach (`X = 0..3`) w kolejności: pobranie zdarzeń 3-bajtowych (`audf, duration, volume`) → `update_envelopes` → `apply_modulation` → `write_pokey_registers`. W formacie v2 istnieją dodatkowo makra przejściowe (`TransientMacroSpec`, do 8 kroków na kanał) oraz obwiednie wysokości (`PitchEnvelopeSpec`), jednak każde przypisanie wymaga danych tablicowych po stronie utworu.

### 1.2 Architektura prototypu jednokanałowego (`player_exp.asm`)
W [`experiments/rhytmizer_drums/asm/player_exp.asm`](experiments/rhytmizer_drums/asm/player_exp.asm) zastosowano **proceduralne mini-procedury 6502 bez tablic parametrów i bez dodatkowych bajtów Zero Page**, aktywowane bitami pola `ch_mod,x` i kompilowane warunkowo na potrzeby pomiarów etapowych (`ENABLE_RHYT_HH`, `ENABLE_RHYT_SNARE`, `ENABLE_RHYT_BD`):

1. **Identyfikator instrumentu (`ch_mod,x`):**
   - Bity `$02` (`MOD_RHYT_HH`), `$04` (`MOD_RHYT_SNARE`), `$08` (`MOD_RHYT_BD`), pozostawiające bit `$01` (`MOD_OCTAVE_PULSE`) w pełni nienaruszonym.
   - Dzięki temu, że `@format_v1` wykonuje `ora any_mod` (a `@format_v2` ustawia `any_mod = 1`), istniejące ścieżki inicjalizacji automatycznie aktywują `apply_modulation` dla kanału perkusyjnego bez zmiany formatu piosenki ani `any_mod`.
2. **Stan klatkowy (jedyna nowa tablica RAM — 4 bajty):**
   - `ch_drum_step .byte 0, 0, 0, 0`: licznik kroku dla kanałów `0..3` (`0` = wygaszony/cisza, `1, 2, 3` = kolejne klatki wybrzmiewania instrumentu).
3. **Wyzwalanie w `fetch_channel_note` (`@setup_envelope`):**
   - Czyszczenie `ch_drum_step,x = 0` na resecie (`music_init`, `PROGRAM_CHANGE`, koniec ścieżki, początek każdej nuty oraz na pauzie `AUDF == 0` lub `peak_vol == 0`).
   - Gdy nuta nie jest pauzą i `(ch_mod,x & MOD_RHYT_MASK) != 0`, procedura ustawia `ch_drum_step,x = 1` i natychmiast wychodzi (`rts`), omijając ADSR/makra/pitch-envelope. Rozmiar haka inicjalizującego jest **stały** niezależnie od liczby włączonych instrumentów (`1`, `2` czy `3`).
4. **Wykonanie klatkowe w `apply_modulation` → `update_rhyt_drum`:**
   - Jeśli `(ch_mod,x & MOD_RHYT_MASK) == 0`: kanał wykonuje w 100% niezmienioną ścieżkę bazową v1/v2 (C1 octave pulse, ADSR, pitch envelope, transient macro).
   - Jeśli `(ch_mod,x & MOD_RHYT_MASK) != 0`: wywołuje `jsr update_rhyt_drum` i przechodzi do następnego kanału (`jmp @next_channel`).
   - `update_rhyt_drum` sprawdza `ch_drum_step,x`: przy `0` zeruje wyłącznie `ch_out_vol,x` (gwarancja ciszy po zakończeniu wybrzmienia nawet przy długim `ch_dur,x`), a przy wartościach `>= 1` zapisuje bezpośrednio `ch_audf,x`, `ch_out_dist,x` i `ch_out_vol,x`, po czym inkrementuje lub zeruje `ch_drum_step,x`. Właściwy zapis do rejestrów POKEY (`$D200–$D208`) wykonuje istniejący `write_pokey_registers`.
5. **Bramka po Etapie 1:** Po implementacji Etapu 1 (`Closed Hi-Hat`) całkowity przyrost rozmiaru wyniósł jedynie `+78 B` (`+44 B` stałego haka szkieletowego, `+30 B` samej procedury Hi-Hat, `+4 B` tablicy `ch_drum_step`, `+0 B` ZP), dając `184 B` zapasu do limitu `2048 B`. Kod okazał się wystarczająco prosty i lekki, by kontynuować Etap 2 (Snare) i Etap 3 (Bass Drum).

---

## 2. Opis każdego instrumentu i zastosowanych parametrów POKEY

Wszystkie warianty eksperymentalne przetestowano w `ASAP 8.0.0` (PAL 50 Hz, pojedynczy kanał `CH4`, `AUDCTL = $00`, zegar bazowy `63,337.39 Hz`). Poniżej zestawiono zarówno badane warianty parametrów, jak i parametry wybrane do `player_exp.asm`.

### 2.1 Etap 1 — Closed Hi-Hat (`MOD_RHYT_HH = $02`)
- **Cel:** Zredukowanie 2-kanałowego Hi-Hata z Rhytmizera (`CH1`: `$80` szum `AUDF1=$00` głośność `4->3->2` przez `21.43 ms` + `CH2`: `$A1` ton `3,518.7 Hz` przy głośności `1`) do jednego kanału przy `50 Hz`.
- **Badane warianty (ASAP 8.0.0, `AUDCTL = $00`):**

| Wariant | Sekwencja `(AUDF, AUDC)` @ `50 Hz` | Peak | RMS | Crest | Span (`-20 dB`) | Centroid FFT | Pasma `<250 / 250–2k / >2k Hz` | Ocena |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| **Oryginał Rhytmizer** | `3×7.14ms` CH1 `($00,$84→$82)` + CH2 `($08,$A1)` | `0.2309` | `0.0307` | `7.51` | `37.0 ms` | `4,185 Hz` | `60.3 / 3.6 / 36.1%` | Punkt odniesienia (`21.43 ms` aktywne + ogon DC) |
| **`hh_a_1f_vol4` (Wybrany)** | **`F0: ($00, $84)`** (`1` klatka = `20 ms`) | **`0.2079`** | **`0.0328`** | **`6.34`** | **`36.0 ms`** | **`5,378 Hz`** | **`53.7 / 6.1 / 40.1%`** | Najbliższy czas trwania i RMS, minimum kodu (`30 B`) |
| `hh_b_2f_vol4_2` | `F0: ($00,$84), F1: ($00,$82)` (`40 ms`) | `0.2079` | `0.0343` | `6.07` | `51.0 ms` | `9,195 Hz` | `20.6 / 6.5 / 72.9%` | Zbyt długi ogon (`51 ms` vs `37 ms`) |
| `hh_c_2f_vol6_2` | `F0: ($00,$86), F1: ($00,$82)` (`40 ms`) | `0.3181` | `0.0503` | `6.32` | `48.0 ms` | `8,460 Hz` | `27.5 / 6.5 / 66.0%` | Za głośny i za długi jak na Closed HH |
| `hh_d_1f_vol5` | `F0: ($00, $85)` (`20 ms`) | `0.2637` | `0.0415` | `6.35` | `36.0 ms` | `5,378 Hz` | `53.7 / 6.1 / 40.1%` | Nieco głośniejszy niż oryginał (`0.264` vs `0.231`) |
| `hh_e_2f_vol4_1` | `F0: ($00,$84), F1: ($00,$81)` (`40 ms`) | `0.2079` | `0.0325` | `6.39` | `47.0 ms` | `7,738 Hz` | `33.9 / 6.5 / 59.6%` | Nadal wydłuża obwiednię do `47 ms` |

- **Implementacja w `player_exp.asm` (`@hh`):** `1` klatka (`20.0 ms`): `AUDF = $00`, `AUDC = $84` (`poly17` przy pełnym zegarze `63.34 kHz`, głośność `4`), kolejna klatka natychmiast zeruje `ch_out_vol,x`. Liczba aktywnych zapisów do kanału: `2` (`AUDF` + `AUDC`).

---

### 2.2 Etap 2 — Snare (`MOD_RHYT_SNARE = $04`)
- **Cel:** Uproszczenie 2-kanałowego Snare z Rhytmizera (`CH1`: `$80` szum `AUDF1=$01` @ `15.56 kHz`, `vol 8->0` + `CH2`: `$A0` ton `311->190 Hz`, `vol 9->1`, `64.36 ms`) do pojedynczej warstwy szumowej na 1 kanale przy `AUDCTL = $00` (`63.34 kHz`) bez rozbudowanego przełączania trybów.
- **Badane warianty (ASAP 8.0.0, `AUDCTL = $00`):**

| Wariant | Sekwencja `(AUDF, AUDC)` @ `50 Hz` | Peak | RMS | Crest | Span (`-20 dB`) | Centroid FFT | Pasma `<250 / 250–2k / >2k Hz` | Ocena |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| **Oryginał Rhytmizer** | `9×7.14ms` CH1 noise `$01` + CH2 sweep `$18..$28` | `0.6095` | `0.1186` | `5.14` | `70.0 ms` | `1,555 Hz` | `43.3 / 33.7 / 23.0%` | Wyraźny pik korpusu `~237 Hz` + szum |
| `sn_a_4f_noise_8_6_4_2` | `F0..F3: ($07, $88→$82)` (`80 ms`) | `0.3404` | `0.0882` | `3.86` | `86.0 ms` | `3,080 Hz` | `7.7 / 43.0 / 49.3%` | Rozciągnięty ogon (`86 ms` vs `70 ms`) |
| `sn_b_4f_pitch_04_07` | `F0: ($04,$89), F1..F3: ($07,$87→$82)` (`80 ms`) | `0.3802` | `0.1003` | `3.79` | `85.0 ms` | `3,224 Hz` | `8.4 / 41.6 / 50.0%` | Wyraźny atak, ale zbyt długi (`85 ms`) |
| `sn_c_4f_tone_noise` | `F0: ($65,$A9), F1..F3: ($07,$87→$82)` (`80 ms`) | `0.3772` | `0.0998` | `3.78` | `84.0 ms` | `2,804 Hz` | `8.1 / 48.2 / 43.6%` | Słychać `20 ms` tonalne „bip” przed szumem |
| `sn_d_3f_tone_noise` | `F0: ($65,$A9), F1: ($07,$87), F2: ($07,$83)` (`60 ms`) | `0.3772` | `0.0972` | `3.88` | `67.0 ms` | `2,707 Hz` | `10.4 / 47.4 / 42.1%` | Tonalny początek odseparowany czasowo od szumu |
| `sn_e_3f_noise_only` | `F0..F2: ($07, $89→$86→$83)` (`60 ms`) | `0.3830` | `0.0919` | `4.17` | `68.0 ms` | `2,956 Hz` | `10.3 / 42.2 / 47.6%` | Płaski atak przy stałym `AUDF=$07` |
| **`sn_f_3f_pitch_04_07` (Wybrany)** | **`F0: ($04,$89) → F1: ($07,$86) → F2: ($07,$83)`** (`60 ms`) | **`0.3802`** | **`0.0936`** | **`4.06`** | **`68.0 ms`** | **`3,214 Hz`** | **`10.1 / 40.4 / 49.5%`** | Zwarty czas (`68 ms` vs `70 ms`), jaśniejszy trzask startowy `$04→$07` |

- **Implementacja w `player_exp.asm` (`@snare`, `+54 B` kodu względem Etapu 1):** `3` klatki (`60.0 ms`): `F0: ($04, $89)`, `F1: ($07, $86)`, `F2: ($07, $83)` (`AUDF = $07` stanowi odpowiednik zegara szumu `7.78 kHz` z Rhytmizera przy `AUDCTL=$00` z błędem `+1.786%`, a `AUDF = $04` daje ostrzejszy transjent początkowy `12.67 kHz`). Liczba aktywnych zapisów do kanału: `6` (`3 × (AUDF + AUDC)`).

---

### 2.3 Etap 3 — Bass Drum (`MOD_RHYT_BD = $08`)
- **Cel:** Próba uzyskania krótkiego kicka na jednym kanale przy `AUDCTL = $00` (`63.34 kHz`) oraz aktualizacji `50 Hz`: wyższa częstotliwość startowa → szybkie obniżenie → spadek głośności.
- **Badane warianty (ASAP 8.0.0, `AUDCTL = $00`):**

| Wariant | Sekwencja `(AUDF, AUDC)` @ `50 Hz` | Peak | RMS | Crest | Span (`-20 dB`) | Centroid FFT | Pasma `<250 / 250–2k / >2k Hz` | Ocena |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| **Oryginał Rhytmizer** | `2×7.14ms` CH1 `($02,$85)` + CH2 `$A0` `$5C→$6E` (`83.6→70.1 Hz`, `$AC`) | `0.5890` | `0.1163` | `5.07` | `30.0 ms` | `233 Hz` | `90.5 / 7.4 / 2.1%` | Bardzo krótki (`14.3 ms`), głęboki sub-bas `<100 Hz` |
| `bd_a_3f_pure_sweep` | `F0: ($80,$AC), F1: ($C0,$AA), F2: ($FF,$A6)` (`60 ms`) | `0.4963` | `0.1351` | `3.67` | `69.0 ms` | `443 Hz` | `78.4 / 18.2 / 3.3%` | Zbyt długi ogon (`69 ms` vs `30 ms`) |
| `bd_b_2f_pure_tight` | `F0: ($B0,$AC), F1: ($FF,$A9)` (`40 ms`) | `0.4963` | `0.1256` | `3.95` | `52.0 ms` | `389 Hz` | `77.3 / 19.8 / 2.9%` | Mniejszy spadek startowy (`179→124 Hz`) |
| `bd_c_3f_poly4_sub` | `F0: ($2A,$CD), F1: ($3D,$CB), F2: ($4C,$C6)` (`60 ms`) | `0.5338` | `0.1425` | `3.75` | `69.0 ms` | `624 Hz` | `49.0 / 45.8 / 5.1%` | Silne harmoniczne `$C0` (`45.8%` w paśmie średnim) |
| `bd_d_2f_poly4_tight` | `F0: ($3D,$CC), F1: ($4C,$CA)` (`40 ms`) | `0.4963` | `0.1251` | `3.97` | `52.0 ms` | `495 Hz` | `60.0 / 36.0 / 4.0%` | Brzęczący charakter `$C0` zamiast czystego `$A0` |
| `bd_e_2f_noise_then_sub` | `F0: ($0B,$88), F1: ($4B,$CC)` (`40 ms`) | `0.3509` | `0.1194` | `2.94` | `56.0 ms` | `571 Hz` | `53.9 / 40.8 / 5.3%` | Szumowy klik + brzęczenie `$C0` |
| **`bd_f_2f_pure_98_ff` (Wariant prototypowy)** | **`F0: ($98,$AD) [207 Hz] → F1: ($FE,$A9) [124.2 Hz]`** (`40 ms`) | **`0.5338`** | **`0.1306`** | **`4.09`** | **`51.0 ms`** | **`339 Hz`** | **`82.6 / 15.0 / 2.5%`** | Najbliższy oryginałowi w ramach `$A0 @ 64 kHz`, mimo limitu `124.2 Hz` |

- **Implementacja w `player_exp.asm` (`@bd`, `+43 B` kodu względem Etapu 2):** `2` klatki (`40.0 ms`): `F0: ($98, $AD)` (`207.0 Hz`, `vol=13`), `F1: ($FE, $A9)` (`124.2 Hz` — najniższy bezpieczny dzielnik trackera `AUDF_TRACKER_MAX = $FE` w trybie 8-bitowym `AUDCTL=$00`, `vol=9`). Liczba aktywnych zapisów do kanału: `4` (`2 × (AUDF + AUDC)`).

---

## 3. Porównanie z oryginalnymi instrumentami Rhytmizera

| Cecha | Oryginalny Rhytmizer (`rhytmizer.xex`) | Prototyp jednokanałowy (`player_exp.asm`) |
| --- | --- | --- |
| **Kanały POKEY** | `CH1` + `CH2` równocześnie (dla Snare, Bass Drum, HH Closed) | Wyłącznie **1 dowolny kanał** (`CH1..CH4`), brak ingerencji w pozostałe |
| **Taktowanie aktualizacji** | Pętla opóźniająca CPU `~140 Hz` (`7.14 ms/krok` przy `$2002=$07`, `9` kroków = `64.3 ms`) | Standardowe VBI **`50 Hz`** (`20.00 ms/ramkę`, wykorzystuje `music_update`) |
| **Rejestr `AUDCTL ($D208)`** | Dynamicznie przełączany: `$00` (HH Closed) lub `$01` (`15.56 kHz` dla Snare i Bass Drum) | Stałe **`$00`** (`63.34 kHz`), zgodne z kanałami melodycznymi Composera |
| **Impuls DAC (`$10`) przed pętlą** | `12–24` cykli `AUDC2=$1F / AUDC1=$1B` w Snare i Bass Drum | Brak (niemożliwy do odwzorowania przy aktualizacji `50 Hz`) |
| **Struktura kodu i danych** | Dedykowane procedury 6502 bez tablic (`~80–106 B` każda + pętla `$271E`) | Wspólny dispatcher `update_rhyt_drum` (`127 B` dla 3 instrumentów, `0 B` tablic danych) |

---

## 4. Wyniki odsłuchu i analiz audio (ASAP 8.0.0)

> [!NOTE]
> Wszystkie metryki numeryczne traktujemy jako narzędzia diagnostyczne — **nie przypisujemy im arbitralnych procentów podobieństwa brzmienia**. Pliki do bezpośredniego odsłuchu A/B znajdują się w [`experiments/rhytmizer_drums/audio/ab_compare/`](experiments/rhytmizer_drums/audio/ab_compare/) w formacie `[Oryginał -> 250 ms ciszy -> Eksperyment -> 250 ms ciszy -> Oryginał -> 250 ms ciszy -> Eksperyment]` po wyrównaniu głośności (`*_norm.wav`), a surowe wyjście ASAP w `audio/original/*_orig_raw.wav` oraz `audio/experimental/*_exp_raw.wav`.

### 4.1 Zbiorcza tabela diagnostyczna (`ASAP 8.0.0`, okno `120 ms`)

| Instrument | Wariant ASAP | Peak (lin / dBFS) | RMS (lin / dBFS) | Crest Factor | Peak Obwiedni | Span (`-20 dB`) | Centroid FFT | Pasma `<250 / 250–2k / >2k Hz` |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Closed Hi-Hat** | Oryginał (`TYPE D`) | `0.2309` (`-12.73 dB`) | `0.0307` (`-30.25 dB`) | `7.51` (`17.52 dB`) | `2.0 ms` | `37.0 ms` | `4,184.7 Hz` | `60.3% / 3.6% / 36.1%` |
| **Closed Hi-Hat** | Prototyp `player_exp` (`TYPE B`) | `0.2088` (`-13.60 dB`) | `0.0326` (`-29.75 dB`) | `6.41` (`16.14 dB`) | `2.0 ms` | `35.0 ms` | `5,583.6 Hz` | `52.7% / 5.9% / 41.4%` |
| **Snare** | Oryginał (`TYPE D`) | `0.6095` (`-4.30 dB`) | `0.1186` (`-18.52 dB`) | `5.14` (`14.22 dB`) | `1.0 ms` | `70.0 ms` | `1,555.0 Hz` | `43.3% / 33.7% / 23.0%` |
| **Snare** | Prototyp `player_exp` (`TYPE B`) | `0.3876` (`-8.23 dB`) | `0.0937` (`-20.57 dB`) | `4.14` (`12.33 dB`) | `2.0 ms` | `66.0 ms` | `3,304.4 Hz` | `9.2% / 38.7% / 52.1%` |
| **Bass Drum** | Oryginał (`TYPE D`) | `0.5890` (`-4.60 dB`) | `0.1163` (`-18.69 dB`) | `5.07` (`14.09 dB`) | `1.0 ms` | `30.0 ms` | `233.2 Hz` | `90.5% / 7.4% / 2.1%` |
| **Bass Drum** | Prototyp `player_exp` (`TYPE B`) | `0.5440` (`-5.29 dB`) | `0.1269` (`-17.93 dB`) | `4.29` (`12.64 dB`) | `4.0 ms` | `49.0 ms` | `395.3 Hz` | `78.3% / 18.8% / 2.9%` |

*(Uwaga diagnostyczna: udział energii w paśmie `<250 Hz` dla krótkich impulsów szumowych w oknie `120 ms` — m.in. `52.7%–60.3%` w Closed Hi-Hat — wynika w dużej mierze z odpowiedzi impulsowej filtra górnoprzepustowego DC wyjścia ASAP na unipolarny skok napięcia DAC `0 → vol → 0`, co widać wyraźnie w dolnych pasmach spektrogramów po zakończeniu impulsu.)*

### 4.2 Interpretacja wykresów diagnostycznych (obwiednia, widmo FFT, spektrogram)
- **Closed Hi-Hat ([`hh_closed_analysis.png`](experiments/rhytmizer_drums/analysis/hh_closed_analysis.png)):**
  - Obwiednia `1 ms RMS` oraz czas zaniku (`35.0 ms` vs `37.0 ms` na poziomie `-20 dB`) pokrywają się bardzo blisko. W widmie FFT jedyną zauważalną różnicą jest wąski pik `~3.52 kHz` w oryginale (cichy ton `$A1` z `CH2`), który przy wysokopasmowym szumie `poly17` jest mało dominujący odsłuchowo.
- **Snare ([`snare_analysis.png`](experiments/rhytmizer_drums/analysis/snare_analysis.png)):**
  - Obwiednia `1 ms` oraz czas wybrzmiewania (`66.0 ms` vs `70.0 ms`) są bardzo zbliżone, podobnie jak szerokopasmowa charakterystyka sprężyn powyżej `700 Hz` w obu spektrogramach (łącznie ze strukturą zegara `AUDF=$07` widoczną po `20 ms`). Jednocześnie FFT ujawnia główny kompromis architektoniczny: oryginał ma wyraźny szczyt rezonansu tonalnego wokół `237 Hz` (`43.3%` energii `<250 Hz`, z `CH2` `$A0` opadającego `311 → 190 Hz`), którego jednokanałowa warstwa szumowa nie wytwarza (`9.2%` energii `<250 Hz`, wyższy centroid `3,304 Hz`). Daje to brzmienie bardziej „piaskowe/szumowe” i lżejsze w dole niż oryginalny werbel Rhytmizera.
- **Bass Drum ([`bass_drum_analysis.png`](experiments/rhytmizer_drums/analysis/bass_drum_analysis.png)):**
  - Tu widoczne są oba twarde ograniczenia jednokanałowego modelu `50 Hz / AUDCTL=$00`:
    1. **Czas trwania:** oryginał zamyka aktywną fazę w `14.3 ms` (`Span -20 dB = 30.0 ms`), podczas gdy `2` klatki przy `50 Hz` trwają `40.0 ms` (`Span -20 dB = 49.0 ms`).
    2. **Wysokość tonu:** na wykresie FFT szczyt widma prototypu wypada w okolicach `124–140 Hz` (`Centroid = 395.3 Hz`), zamiast pasma `<100 Hz` oryginału (`83.6 → 70.1 Hz`, `Centroid = 233.2 Hz`). Prototyp brzmi raczej jak bardzo krótki, wysoki tom lub „typowy Beeper/POKEY thump” niż głęboka stopa z Rhytmizera.

---

## 5. Pomiary rozmiaru kodu po każdym etapie

Pomiary wykonano bezpośrednio przez asembler **MADS** (`-b:$6000 -o:out.bin -t:out.lab`), dokładnie tak jak w [`src/atari_music/player_budget.py`](src/atari_music/player_budget.py). Wartość `total_bytes` odpowiada rozmiarowi wyjściowemu `measure_player_size()` (zawierającemu `6 B` nagłówka segmentu Atari DOS `$FF $FF $00 $60 end_lo end_hi`), a `payload_bytes` to czysty kod + BSS (`exp_bss_end - exp_player_start`).

| Wariant | Rozmiar całkowity (`measure_player_size`) | Czysty payload (kod + RAM) | Przyrost vs baseline | Kod wykonywalny (łącznie) | Kod haków (`init/fetch/mod`) | Kod procedur perkusyjnych | Dane instrumentów (tablice) | RAM (BSS) bazowy + dodatkowy | Zero Page bazowy + dodatkowy | Zapas do limitu `< 2048 B` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | ---: |
| **Aktualny player — baseline** (`src/.../player.asm`) | **`1,785 B`** | `1,779 B` | `0 B` | `1,632 B` | `0 B` | `0 B` | `0 B` | `147 + 0 B` | `10 + 0 B` | `262 B` |
| **Player + Closed Hi-Hat** (`Etap 1`) | **`1,863 B`** | `1,857 B` | **`+78 B`** | `1,706 B` | `+44 B` | `+30 B` | `0 B` | `147 + 4 B` | `10 + 0 B` | `184 B` |
| **Player + Closed Hi-Hat + Snare** (`Etap 2`) | **`1,917 B`** | `1,911 B` | **`+132 B`** (`+54 B`) | `1,760 B` | `+44 B` | `+84 B` (`+54 B`) | `0 B` | `147 + 4 B` | `10 + 0 B` | `130 B` |
| **Player + wszystkie trzy instrumenty** (`Etap 3`) | **`1,960 B`** | `1,954 B` | **`+175 B`** (`+43 B`) | `1,803 B` | `+44 B` | `+127 B` (`+43 B`) | `0 B` | `147 + 4 B` | `10 + 0 B` | `87 B` |

- Wszystkie cztery warianty mieszczą się bezpiecznie poniżej twardego limitu `2,048` bajtów bez jakiejkolwiek optymalizacji istniejącego kodu produkcyjnego.
- **Dane inicjalizacyjne po stronie utworu:** `0 B` nadmiarowych — instrument korzysta z istniejących 6-bajtowych (v1) lub 10-bajtowych SoA (v2) rekordów instrumentu, ustawiając jedynie flagę w bajcie modulacji/flag (`$02`, `$04` lub `$08`) bez żadnych tablic kroków.

---

## 6. Wykorzystanie RAM i Zero Page

- **Zero Page:** `10 B` (bazowe `PLAYER_ZP_BASE + 0..9`) + **`0 B` dodatkowych** (całkowicie bez zmian).
- **RAM / BSS w playerze:** `147 B` (bazowe zmienne) + **`4 B` dodatkowe** (`ch_drum_step .byte 0, 0, 0, 0`, tj. 1 bajt na kanał dla stanów kroków perkusyjnych). Dodatkowy koszt RAM jest stały (`4 B`) niezależnie od tego, czy wkompilowano 1, 2 czy wszystkie 3 instrumenty.

---

## 7. Koszt CPU

Zmierzono dokładną symulacją instrukcja-po-instrukcji w `py65` (z uwzględnieniem skrzyżowań granic stron i cykli skoków) dla pełnego utworu 4-kanałowego (3 aktywne kanały melodyczne `CH1–CH3` z obwiednią ADSR + perkusja na `CH4` kontra identyczny utwór kontrolny z pustym `CH4`):

| Scenariusz wykonania `music_update` | Cykle CPU: Klatka startowa (`F0`) | Delta vs kontrola (`F0`) | Cykle CPU: Klatki aktywne (`F1..`) | Cykle CPU: Ogon wyciszony (`ch_drum_step==0`) | Delta w ogonie | Czas @ PAL (`1.773 MHz`, max ramka) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Kontrola (Baseline `player.asm`, 3 kanały melodyczne + pusty `CH4`)** | `1,383` | `—` | `854` / `661` | `577` | `—` | `0.78 ms` (`~2.2%` klatki PAL) |
| **Closed Hi-Hat** (`CH4`: 1 klatka aktywna) | `1,653` | `+270` cykli | `—` | `1,038` → `758` | `+181` cykli (`when any_mod!=0`) | `0.93 ms` (`~4.7%` ramki przy 1,653 cyc) |
| **Snare** (`CH4`: 3 klatki aktywne) | `1,671` | `+288` cykli | `1,085` (`F1`), `893` (`F2`) | `758` | `+181` cykli | `0.94 ms` |
| **Bass Drum** (`CH4`: 2 klatki aktywne) | `1,669` | `+286` cykli | `1,082` (`F1`) | `845` → `758` | `+181` cykli | `0.94 ms` |

*(Uwaga: całkowity wzrost o `~181` cykli w ogonie wyciszonym względem utworu kontrolnego z `ch_mod=0` wynika przede wszystkim z przejścia `apply_modulation` przez ścieżkę `any_mod != 0` dla 4 kanałów, co w utworze już używającym modulacji C1 lub formatu v2 jest kosztem zerowym poza `+12..25` cyklami testu bitów `MOD_RHYT_MASK` na kanał).*

---

## 8. Ograniczenia rozwiązania

1. **Kwantyzaacja czasowa `50 Hz` (`20.00 ms` / ramkę vs `7.14 ms` w Rhytmizerze):**
   - W oryginalnym Rhytmizerze Bass Drum trwa zaledwie `14.31 ms` (`2` kroki po `7.14 ms`), a Snare ma `9` płynnych kroków na przestrzeni `64.36 ms`. Przy `50 Hz` VBI minimalny krok to `20.00 ms`, co uniemożliwia oddanie szybkich transjentów sub-ramkowych ani dwukrokowego uderzenia krótszego niż `40 ms`.
2. **Twardy próg najniższej częstotliwości `$A0` przy `AUDCTL = $00` (`63.34 kHz`):**
   - Przy 8-bitowym trybie `AUDCTL = $00` (wymaganym dla współdzielenia z kanałami melodycznymi) najniższy możliwy ton czysty `$A0` wynosi `124.19 Hz` (`AUDF=$FE`) lub `123.71 Hz` (`AUDF=$FF`). Jest to wyraźnie wyżej niż oryginalna podstawa Bass Drum z Rhytmizera (`83.64 Hz → 70.07 Hz` przy `AUDCTL=$01`). Przejście na `$C0` (`poly4`) obniża ton podstawowy w okolice `70–85 Hz`, ale silnie zmienia barwę w brzęczący przebieg 15-bitowy.
3. **Brak drugiej równoczesnej warstwy na 1 kanale:**
   - W Snare słychać brak jednoczesnego tonu korpusu (`311 → 190 Hz`), co potwierdza widmo FFT (`9.2%` vs `43.3%` poniżej `250 Hz`).
4. **Brak mikrosekundowych impulsów DAC (`$1F / $1B`):**
   - Przy `50 Hz` nie można odtworzyć `12–24`-cyklowego skoku DAC na początku uderzenia.

---

## 9. Lista wygenerowanych plików i instrukcja odtworzenia eksperymentu

### 9.1 Wygenerowane pliki (wszystkie izolowane w `experiments/rhytmizer_drums/` + raport)
- **Kod 6502 prototypu:** [`experiments/rhytmizer_drums/asm/player_exp.asm`](experiments/rhytmizer_drums/asm/player_exp.asm)
- **Skrypty eksperymentu:**
  - [`experiments/rhytmizer_drums/scripts/explore_variants.py`](experiments/rhytmizer_drums/scripts/explore_variants.py)
  - [`experiments/rhytmizer_drums/scripts/run_experiment.py`](experiments/rhytmizer_drums/scripts/run_experiment.py)
- **Testy automatyczne (`pytest`):** [`experiments/rhytmizer_drums/tests/test_rhytmizer_drums_exp.py`](experiments/rhytmizer_drums/tests/test_rhytmizer_drums_exp.py)
- **Nagrania audio (ASAP 8.0.0):**
  - Oryginały Rhytmizera (`raw` + wyrównane głośnością `norm`): [`experiments/rhytmizer_drums/audio/original/`](experiments/rhytmizer_drums/audio/original/) (`hh_closed_orig_raw.wav`, `hh_closed_orig_norm.wav`, `snare_orig_raw.wav`, `snare_orig_norm.wav`, `bass_drum_orig_raw.wav`, `bass_drum_orig_norm.wav`)
  - Warianty prototypowe (`17` plików WAV): [`experiments/rhytmizer_drums/audio/variants/`](experiments/rhytmizer_drums/audio/variants/) (`hh_a..e`, `sn_a..f`, `bd_a..f`)
  - Wybrane instrumenty z `player_exp.asm` (`raw` + `norm`): [`experiments/rhytmizer_drums/audio/experimental/`](experiments/rhytmizer_drums/audio/experimental/) (`hh_closed_exp_raw.wav`, `hh_closed_exp_norm.wav`, `snare_exp_raw.wav`, `snare_exp_norm.wav`, `bass_drum_exp_raw.wav`, `bass_drum_exp_norm.wav`)
  - Zestawy do wygodnego odsłuchu A/B (`Orig -> Exp -> Orig -> Exp`): [`experiments/rhytmizer_drums/audio/ab_compare/`](experiments/rhytmizer_drums/audio/ab_compare/) (`hh_closed_ab_compare.wav`, `snare_ab_compare.wav`, `bass_drum_ab_compare.wav`)
- **Wyniki liczbowe i wykresy diagnostyczne:**
  - [`experiments/rhytmizer_drums/analysis/experiment_results.json`](experiments/rhytmizer_drums/analysis/experiment_results.json)
  - [`experiments/rhytmizer_drums/analysis/variant_exploration.json`](experiments/rhytmizer_drums/analysis/variant_exploration.json)
  - [`experiments/rhytmizer_drums/analysis/hh_closed_analysis.png`](experiments/rhytmizer_drums/analysis/hh_closed_analysis.png)
  - [`experiments/rhytmizer_drums/analysis/snare_analysis.png`](experiments/rhytmizer_drums/analysis/snare_analysis.png)
  - [`experiments/rhytmizer_drums/analysis/bass_drum_analysis.png`](experiments/rhytmizer_drums/analysis/bass_drum_analysis.png)
- **Raport końcowy:** [`RHYTMIZER_DRUM_PROTOTYPE_REPORT.md`](RHYTMIZER_DRUM_PROTOTYPE_REPORT.md)

### 9.2 Odtworzenie eksperymentu i testów jednym poleceniem
```powershell
# 1. Pełna reprodukcja pomiarów rozmiaru, symulacji py65, renderów ASAP 8.0.0 i wykresów:
.\.venv\Scripts\python.exe experiments/rhytmizer_drums/scripts/run_experiment.py

# 2. Uruchomienie testów eksperymentalnych oraz weryfikacji budżetu produkcyjnego:
.\.venv\Scripts\pytest.exe experiments/rhytmizer_drums/tests/test_rhytmizer_drums_exp.py tests/test_player_budget.py -v
```

---

## 10. Rekomendacja końcowa dla każdego instrumentu

| Instrument | Rekomendacja | Uzasadnienie techniczne i brzmieniowe |
| --- | :---: | --- |
| **1. Closed Hi-Hat** | **`ACCEPT`** | Znakomita relacja jakości do kosztu: sama procedura zajmuje tylko **`30 B`** kodu (+44 B stałego szkieletu, `+4 B` RAM, `0 B` ZP), a `1` klatka (`20.0 ms` @ `$00 / $84`) bardzo dobrze pokrywa się z czasem zaniku (`35 ms` vs `37 ms` przy `-20 dB`) oraz wysokopasmową charakterystyką szumu `poly17` z Rhytmizera. Nadaje się bezpośrednio do włączenia do Composera (w praktyce może też zostać zdefiniowany bez zmian kodu `player.asm` jako 1-krokowe makro v2). |
| **2. Snare** | **`NEEDS FURTHER WORK`** | Przyrost kodu jest umiarkowany (`+54 B` procedury ponad Hi-Hat), czas wybrzmiewania (`60 ms` / `66 ms` span) dobrze trafia w oryginał (`70 ms`), a krótkie przesunięcie częstotliwości `$04 → $07` poprawia atak. Jednak na jednym kanale brakuje wyraźnego rezonansu korpusu (`237 Hz`) z `CH2` Rhytmizera, przez co werbel brzmi wyraźnie lżej i bardziej „szumowo”. Przed ewentualną akceptacją należy przeprowadzić odsłuchowe porównanie `sn_f` (`$04→$07`) z wariantem hybrydowym `sn_d` (`$A0 $65` + `$80 $07`) oraz z istniejącym w katalogu v2 `perc_snare_crisp`. |
| **3. Bass Drum** | **`REJECT`** *(jako procedura 1-kan. `AUDCTL=$00 @ 50 Hz`)* | Przy ograniczeniu do 1 kanału, `50 Hz` i `AUDCTL=$00`, fizyczny limit dzielnika `AUDF = $FE` (`124.2 Hz`) w trybie `$A0` jest ponad pół oktawy wyżej niż `83.6 → 70.1 Hz` z oryginału (a `2` klatki wydłużają kopnięcie do `40 ms` wobec `14.3 ms` w Rhytmizerze). Alternatywa `$C0` (`poly4`) schodzi częstotliwościowo niżej, lecz zmienia barwę w brzęczący przebieg LFSR. W produkcyjnym Composerze nie warto dokładać dedykowanej procedury 6502 (`+43 B`) dla tak dużego kompromisu — właściwy kick powinien wykorzystać katalog v2 (np. istniejący `perc_kick_tight`) albo tryb `AUDCTL=$01` / 16-bit CH1+CH2. |
