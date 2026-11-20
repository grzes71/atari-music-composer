# Manual Verification Guide: A/B Comparison Panel & Playback (Windows GUI + Audio)

Procedura ręcznej weryfikacji **Phase 3 (A/B Comparison + PCM Transport)** w uruchomionej aplikacji desktopowej `Atari Music Composer Studio` na systemie Windows (WASAPI / głośniki / słuchawki).

> **Uwaga:** Jest to lista kontrolna do ręcznego wykonania przez użytkownika przed ostatecznym odbiorem wizualnym i odsłuchowym. Żaden z poniższych scenariuszy nie jest tu oznaczony jako wykonany.

## Przygotowanie

1. Aktywuj środowisko wirtualne:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. Uruchom Studio (opcjonalnie od razu z kompozycją testową):
   ```powershell
   atari-music-studio examples\ai\action_fast.json
   ```
3. Upewnij się, że systemowe urządzenie odtwarzania dźwięku jest aktywne i nie wyciszone.
4. *(Opcjonalnie do Scenariusza 4 – różne długości utworów)* Przygotuj w `examples\` lub katalogu roboczym dwie kompozycje albo edytuj konfigurację w ten sposób, aby oba warianty miały różną długość po syntezie (lub porównaj utwór dłuższy i krótszy / przetestuj osobno przełączanie na krótszym i dłuższym WAV).

---

## Scenariusz 1 – Podstawowy przepływ A/B (Save, Render, Listen, Switch)

- **Cel testu:** Zweryfikować zapis dwóch niezależnych wariantów A i B, ich wyrenderowanie oraz bezproblemowe przełączanie odsłuchu bez niepożądanej zmiany konfiguracji edytora.
- **Instrukcja:**
  1. Uruchom Studio i otwórz `examples\ai\action_fast.json`.
  2. Kliknij **Save to A** w panelu *A/B Comparison* (sprawdź statusy `Not rendered` i `Matches editor`).
  3. Zmień instrument w **CH1** (np. na `lead_attack_bite`) oraz w **CH4** (np. `perc_snare_crisp`). Zwróć uwagę, że Variant A zachowuje swoją starą konfigurację i zmienia etykietę na `Differs from editor`.
  4. Kliknij **Save to B**.
  5. Kliknij **Render A**, a po zakończeniu **Render B**.
  6. Kliknij **Listen A** i posłuchaj brzmienia.
  7. Kliknij **Listen B** (lub **Switch A/B**), a następnie wróć na **A**.
- **Oczekiwany rezultat:**
  - Oba warianty mają status `Ready`.
  - Wariant A i B wyraźnie różnią się brzmieniem instrumentów CH1/CH4 zgodnie z zapisanymi aranżacjami.
  - Przełączanie **Listen A / B / Switch A/B** nie zmienia ustawień w `ChannelStripWidget` ani `PresetBarWidget`.
  - Aktywnie odtwarzany slot jest wyróżniony obramowaniem i plakietką `LISTENING`.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**

---

## Scenariusz 2 – Zachowanie pozycji podczas przełączania (Playing → Playing)

- **Cel testu:** Ocenić zachowanie przybliżonej pozycji czasowej oraz jakość przejścia dźwiękowego (przerwa, brak kliknięć/trzasków) podczas szybkiego przełączania w trakcie gry.
- **Instrukcja:**
  1. Z gotowych wariantów A i B z Scenariusza 1 uruchom odtwarzanie A (**Listen A**).
  2. Odczekaj ok. 3–5 sekund (lub przesuń suwak Seek w środek utworu).
  3. W trakcie odtwarzania kliknij **Switch A/B** na wariant B.
  4. Po kolejnych 2–3 sekundach kliknij ponownie **Switch A/B** na wariant A.
- **Oczekiwany rezultat:**
  - Odtwarzanie B kontynuuje z okolic miejsca, w którym przerwano A (dźwięk **nie** wraca do `00:00`).
  - Suwak Seek i zegar `MM:SS / MM:SS` utrzymują ciągłą pozycję zamiast przeskakiwać do zera.
  - Przeładowanie `QAudioSink` może wprowadzić minimalną przerwę bufora, ale bez głośnych trzasków ani błędu urządzenia.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi (opisz długość ewentualnej przerwy / brak kliknięć):**

---

## Scenariusz 3 – Przełączanie w stanie pauzy (Paused → Paused)

- **Cel testu:** Potwierdzić, że przełączenie na drugi wariant w trakcie pauzy korzysta z `prepare_paused_at()` i **nie** powoduje nawet ułamkowego odtworzenia dźwięku aż do ręcznego wznowienia.
- **Instrukcja:**
  1. Uruchom odtwarzanie wariantu A (**Listen A**).
  2. Po kilku sekundach kliknij **Pause** w `TransportBar` (przycisk zmieni się na **Resume**).
  3. Kliknij **Listen B** (lub **Switch A/B**).
  4. Nasłuchuj uważnie głośników / słuchawek, obserwuj przycisk **Resume** oraz suwak pozycji.
  5. Kliknij **Resume** (albo **Play**).
  6. Ponownie użyj **Pause** i wróć przez **Switch A/B** na wariant A.
- **Oczekiwany rezultat:**
  - W kroku 3 **nie słychać nawet krótkiego kliknięcia ani ułamka sekundy muzyki B**.
  - Wariant B pozostaje w stanie `Paused` z zachowaną pozycją i aktywnym przyciskiem **Resume**.
  - Dopiero po kliknięciu **Resume** wariant B zaczyna grać płynnie dokładnie od zapamiętanej pozycji.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**

---

## Scenariusz 4 – Przełączanie między wariantami o różnej długości

- **Cel testu:** Sprawdzić, czy gdy bieżąca pozycja wykracza poza długość krótszego wariantu, pozycja jest bezpiecznie ograniczana (`min(pos, max(0, dur - 100 ms))`), bez natychmiastowego `EOF` ani błędów.
- **Instrukcja:**
  1. Przygotuj sesję z dłuższym wariantem A i krótszym wariantem B (lub ustaw na jednym wariancie wyraźnie inne parametry długości w utworze wielosekwencyjnym / testowych plikach).
  2. Odtwarzaj dłuższy wariant poza czasem trwania krótszego wariantu.
  3. Przełącz na krótszy wariant przyciskiem **Switch A/B** / **Listen**.
- **Oczekiwany rezultat:**
  - Krótszy wariant nie wyłącza się natychmiastowym `EOF` w tej samej klatce — odgrywa końcówkę (~100 ms przed końcem) i dopiero potem naturalnie kończy odtwarzanie (`Finished`), umożliwiając ponowny start od `00:00`.
  - Przełączenie w drugą stronę (z krótszego na dłuższy) zachowuje pozycję bez ucinania utworu.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**

---

## Scenariusz 5 – Renderowanie wariantu B podczas odsłuchu A

- **Cel testu:** Potwierdzić niezależność kolejki renderowania od aktywnego odtwarzacza oraz brak automatycznego przejmowania transportu przez kończący się render A/B.
- **Instrukcja:**
  1. Uruchom odtwarzanie wariantu A (**Listen A**).
  2. W trakcie gry A zmodyfikuj instrument w edytorze i kliknij **Save to B**, a następnie **Render B**.
  3. Obserwuj pasek statusu B (`Rendering Variant B...` → `Ready`) oraz słuchaj muzyki z głośników.
  4. Dopiero po zakończeniu renderowania kliknij **Listen B**.
- **Oczekiwany rezultat:**
  - Podczas `Render B` muzyka wariantu A **nie przerywa się, nie zacina i nie resetuje pozycji**.
  - Po zakończeniu `Render B` wariant A nadal gra (`LISTENING` pozostaje na A), a B jedynie odblokowuje przycisk **Listen B**.
  - Dopiero ręczne kliknięcie **Listen B** przełącza odsłuch na B.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**

---

## Scenariusz 6 – Wspólna serializowana kolejka (Editor + A + B)

- **Cel testu:** Zweryfikować działanie jednej kolejki renderowania FIFO oraz spójne statusy `Queued` / `Rendering...` / `Ready` dla trzech różnych konfiguracji.
- **Instrukcja:**
  1. Zapisz różne konfiguracje w **A**, **B** oraz trzecią odmienną konfigurację w edytorze (tak, by żadna nie była jeszcze w cache).
  2. Szybko po sobie kliknij:
     - **Render Preview** (główny pasek transportu),
     - **Render A**,
     - **Render B**.
  3. Obserwuj etykiety statusów podczas pracy w tle.
- **Oczekiwany rezultat:**
  - Zadania wykonują się po kolei bez równoczesnych kolizji plików WAV.
  - W trakcie pracy widać kolejno przejścia statusów (`Queued` → `Rendering...` → `Ready`) oraz aktywny pasek postępu głównego preview.
  - Po ukończeniu wszystkich zadań wszystkie trzy (Editor, A, B) mają własne gotowe wyniki.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**

---

## Scenariusz 7 – Otwarcie nowej kompozycji podczas aktywnego renderowania

- **Cel testu:** Potwierdzić czyszczenie sesji A/B oraz odrzucanie spóźnionych wyników workerów ze starej kompozycji.
- **Instrukcja:**
  1. Na otwartym `examples\ai\action_fast.json` zapisz **A**, zmień instrument i kliknij **Render A** (a opcjonalnie również **Render B** w kolejce).
  2. Natychmiast w trakcie renderowania kliknij **Open Composition (.json / .dsl)...** i otwórz `examples\songs\wybierak-2.dsl`.
  3. Odczekaj 2–3 sekundy po załadowaniu nowej kompozycji.
- **Oczekiwany rezultat:**
  - Sloty A i B natychmiast przechodzą w stan `Empty` dla nowej kompozycji.
  - Transport jest pusty i zatrzymany (brak pozostałego audio ze starego utworu).
  - Kończący się w tle stary worker dla `action_fast.json` **nie** ustawia statusu `Ready` ani nie odtwarza dźwięku w nowej kompozycji.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**

---

## Scenariusz 8 – Zamykanie Studio podczas aktywnego renderowania i odtwarzania

- **Cel testu:** Sprawdzić bezpieczne zamknięcie okna podczas aktywnego wątku renderującego i grającego `QAudioSink`.
- **Instrukcja:**
  1. Odtwarzaj wyrenderowany wariant A (**Listen A**).
  2. Uruchom **Render B** w tle.
  3. W trakcie aktywnego renderowania i odtwarzania zamknij główne okno Studio przyciskiem `X`.
  4. Sprawdź konsolę / Menedżer zadań po zamknięciu okna.
- **Oczekiwany rezultat:**
  - Dźwięk zatrzymuje się natychmiast przy zamykaniu okna.
  - Aplikacja zamyka się czysto bez zawieszenia, wyjątków Python/Qt ani wiszących procesów w tle.
  - Katalog tymczasowy `RenderService` zostaje posprzątany.
- **Wynik:** `[ ] PASS   [ ] FAIL`
- **Uwagi:**
