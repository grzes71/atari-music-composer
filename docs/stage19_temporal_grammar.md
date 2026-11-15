# Stage 19 - A Neutral Temporal Performance Grammar for POKEY

Stage 17 asked whether a neutral event language could *represent* a performance. It could not, and compressed worse than raw. Stage 18 asked whether the exact stream had temporal redundancy. It did, about 49 percent of it, but the answer was a byte format and not a model. Stage 19 asks the narrower structural question that remains: can the historical behaviour be described by a *small, neutral temporal grammar* rather than stored?

Analysis only. The corpus traces, the Stage 15/16/17/18 records and the player source are read through their hashes and never written. No audio was rendered, no music was generated, no listening test was run, and nothing was implemented in production - no player command, no composer feature, no IR, no DSL, no schema. Nothing here names a melody, a bass line, an instrument or an effect as an element of the model.

Analysis version `stage19/1`.

Artefacts: `canonical.json`, `primitives.json`, `per_song.json`, `shared_grammar.json`, `leave_one_out.json`, `candidates.json`, `complexity.json`, `comparison.json`, `reconstruction.json`, `stage17_comparison.json`, `stage18_comparison.json`, `summary.json`.

## 1. Executive Summary

- **A small neutral grammar exists.** Five constructions - SET, HOLD, DELTA, RAMP, TOGGLE - plus an explicit residual channel and one construction the data asked for. HOLD, RAMP and TOGGLE together carry 67.2% of every register frame exactly, in all 4 songs, and no definition mentions a musical concept.

- **It is not Stage 17 in a new coat.** SET is only 2.2% of frames and is the most expensive construction per frame, so the parse avoids it wherever anything else applies.

- **The grammar proper is not small in bytes.** Definition and decoder charged, it reaches a mean ratio of 0.532493 - about half the raw stream. It is exact and it is a model, but half is not a bridge between a composition IR and exact playback.

- **A REPEAT level makes it far smaller and stops being a grammar.** An induced block lexicon takes the mean ratio to 0.328678, better than Stage 18's best byte codec at 0.508255, but 71.4% of that artefact *is* the per-song lexicon.

- **The lexicon transfers nothing, and this is the decisive number.** Built from three songs and offered whole to the fourth, it supplied 0 references across all four folds, leaving the held-out song at exactly the grammar's own ratio of 0.527432. The construction earns its bytes and loses its claim to being part of a shared language.

- **The vocabulary does transfer.** Leave-one-out on the constructions costs nothing measurable (0.527432 in sample against 0.527562 out of sample); freezing the parameters costs 0.566733 against 0.527562, and 7.7% of held-out occurrences use a parameter shape the training songs never showed.

- **DELTA is rejected by every song.** The construction the brief asks about most is the one no song's own induction keeps: RAMP plus SET always describes the same run in the same or fewer bytes.

- **It is cheap to run.** 45 bytes of decoder state and a complexity score of 24, against 9,216 bytes of window for Stage 18's best LZ configuration.

- **Verdicts.** TEMPORAL_GRAMMAR_EXISTENCE_SUPPORTED, TEMPORAL_GRAMMAR_GENERALIZATION_PARTIAL, GENERATOR_LAYER_NOT_JUSTIFIED, PLAYER_INTEGRATION_NOT_JUSTIFIED.

One sentence: *the temporal grammar is real, small in vocabulary, exact and cheap, and it still does not justify replacing anything, because the only large saving comes from memorising each song separately.*

## 2. Research Question

> Can the four analysed historical POKEY performance streams be described by a small, neutral and generalisable set of temporal constructions, which is exact wherever a construction is used and simple enough to potentially sit between the composition IR and exact POKEY playback?

The question is answered at three levels, and each is decided by a stated threshold rather than by impression.

| level | question | decided by |
|---|---|---|
| H1 Existence | are there repeatable temporal constructions at all? | structural coverage at least 40% and saving with the grammar charged at least 20%, exact on every song |
| H2 Generalization | are the constructions shared across songs? | a construction induced in at least 75% of songs, a leave-one-out loss under 10%, and a REPEAT lexicon that transfers |
| H3 Generative usefulness | could this be a generative layer? | requires H2 and a transferring lexicon; no generator was built here, so this can only be reported as not justified on the evidence available |

The answer is not assumed to be yes. Two of this stage's load-bearing results - DELTA rejected by every song, and the lexicon transferring nothing - are negative, and they are reported as such.

## 3. Dataset

The same four songs Stage 16 selected and Stage 18 measured, read from the Stage 16 record rather than chosen again here. The slugs are verified against the expected set, so a corpus that silently changed would fail loudly instead of producing quietly different numbers.

| song | frames | frame period | raw bytes | registers |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 8826 | 20056 us | 79434 | 9 |
| `Warhawk__sub0` | 10840 | 20056 us | 97560 | 9 |
| `Ninja_Commando__sub0` | 6081 | 20056 us | 54729 | 9 |
| `Red_Max__sub0` | 6912 | 20056 us | 62208 | 9 |

Stage 16 selection record: `C:\Users\grzes\Documents\Projects\atari-music\reports\stage16\song_selection.json`, sha256 `277f6c1f78795d60dc8847318c0990aad8faa41e7857a9e410fe9e0d3a0bec7b`.

No song was added, removed, sampled or truncated. Everything below is measured on all four, and a configuration that is not exact on all four is never called a result.

## 4. Canonical Representation

Stage 19 does not invent a second canonical form. Stage 18's canonical raw representation is the source of truth and is taken *by import*, so the two stages cannot silently disagree about what a frame is.

| property | value |
|---|---|
| register order | AUDF1, AUDC1, AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4, AUDCTL |
| frame size | 9 bytes, absolute state |
| container header | 12 bytes, Stage 18's layout, shared by every codec |
| Stage 19 codec id | 200 |
| Stage 18 module hash | `c73185e335bb632b6ba8341431df098431c188ba627773dc7cc1722a855ba625` |

**The neutral atom.** One register's value sequence: a list of 8-bit values, one per frame, with no label beyond the register name pokey itself defines.

The atom deliberately excludes the song, the other channels, note boundaries and time signature. A construction that only exists because a channel "is a bass line" would not be a temporal construction at all, and this restriction is what keeps the experiment falsifiable.

## 5. Candidate Primitive Vocabulary

Six entries: five constructions plus an explicit residual. Every one is a pure function of a value sequence and a write position, and none of them carries meaning.

| op | name | definition | parameters | min span | def. bytes (est.) | cost split |
|---|---|---|---|---|---|---|
| 1 | **SET** | SET(v) writes exactly one frame with value v, whatever the current value was. It is the only construction that carries a value with no temporal relation to its neighbours, and it is therefore the honest baseline each other construction has to beat rather than a simplification of one. | value | - | 11 | opcode + value |
| 2 | **HOLD** | HOLD(n) writes n frames, each equal to the current value, so the value is carried forward unchanged. n >= 1. At the start of a channel the current value is 0. | frames | 2 | 26 | opcode + length |
| 3 | **DELTA** | DELTA(d, n) writes n frames, frame j (1-based) equal to current + d*j mod 256, so it continues an arithmetic progression from the value already in the register. n >= 2 and d != 0; a single step carries no sequence, and is written as SET. | delta, frames | 2 | 40 | opcode + length, delta |
| 4 | **RAMP** | RAMP(start, d, n) writes n frames, frame j (0-based) equal to start + d*j mod 256. It differs from DELTA only in carrying its own start value, so it does not depend on the previous frame. n >= 2 and d != 0. | start, delta, frames | 2 | 33 | opcode + length, start + delta |
| 5 | **TOGGLE** | TOGGLE(a, b, n) writes n frames alternating between a and b, frame 0 equal to a. n >= 2 and a != b. It is the period-two special case of a repeat, and it is kept separate only if the data shows the construction earns its definition. | a, b, frames | 4 | 37 | opcode + length, two endpoints |
| 6 | **LITERAL** | LITERAL(k, v0..v(k-1)) writes k frames with the given values verbatim. This is the residual model, not a construction: the explicit channel through which every frame the grammar cannot describe is carried, so that no residual is ever hidden. 2 <= k <= 32. | count, values | - | 22 | opcode + length, k values (residual) |
| 7 | **REPEAT** | REPEAT(block) writes the frames of the stored block verbatim, where the block is a run of values named once in a per-song table and referred to thereafter. It is the only construction here that stores a value twice, so it is only allowed into a grammar when its own table entry is paid back by its own uses; section 8 measures that, and section 20 tries to refute it. | block | - | 29 | opcode + id |

**The residual is not a construction.** LITERAL is the residual model, present in every variant and always charged to exception_cost. Counting it as a construction would let a grammar look capable by describing nothing.

**Minimum spans, and why they matter.** DELTA >= 2, HOLD >= 2, RAMP >= 2, TOGGLE >= 4. Below its minimum span a construction is not the thing it names: a HOLD of one frame is a SET, and a TOGGLE of two frames is merely two different values. The first implementation of this stage allowed a two-frame toggle and reported TOGGLE covering 9,175 frames of one song; almost all of those were ties with the residual, and the minimum span is what removed the artefact.

**A construction the data asked for.**

- **REPEAT**: ADMITTED_AS_A_COMPRESSION_TOOL, REJECTED_AS_A_GRAMMAR_ELEMENT: it earns its place in bytes and loses it in generalisation. The induction measured a net 78743 bytes on the operation stream, an in-sample mean ratio of 0.328678 and a leave-one-out mean ratio of 0.527432.


Nothing else was added. In particular no construction was invented to improve a ratio: section 20 tests each one's marginal contribution, and section 21's rule is applied at selection time rather than reported afterwards.

## 6. Primitive Discovery

The grammar was not designed only by hand. Discovery is bottom-up, in four steps, and each step is reported before the next is allowed to run.

1. Each channel is split at every position where a construction could begin, by three linear-time recurrences: constant run, arithmetic run, alternating run.

2. A dynamic program chooses the cheapest sequence of constructions under an explicit cost model, taking each construction at its maximal extent from each position.

3. The resulting operation stream is scanned for repeated runs of operations, at two levels that answer two different questions.

4. Only a construction that pays for its own definition, measured, is allowed into a grammar.

**The parse is exact for this primitive set.** Inside a maximal run of a given shape no other construction can start, so continuing is never worse than restarting; and the residual is not restricted at all, because its cost is linear in the run length so its minimum over the window is a sliding-window minimum. The residual can therefore always fall back to something close to the raw cost of a frame, which is what stops a construction being credited for a frame it does not really describe.

| discovery statistic | value |
|---|---|
| operations in the grammar's own parse | 28951 |
| bytes those operations cost | 161225 |
| frames they cover | 293931 |
| distinct operation-kind patterns | 249 |
| repeated operation-kind patterns | 232 |
| distinct exactly-repeated patterns | 11362 |
| exactly-repeated patterns used exactly once | 4135 |

**Two levels, deliberately kept apart.** The *structural* level ignores parameters and counts repeated sequences of operation kinds. It is a detection figure and not a size, because a repeat that re-sent its parameters every time would save nothing but opcodes. The *exact* level requires identical operations, parameters included, and it is the only level at which a reference can save real bytes.

| top repeated operation-kind pattern | occurrences | songs present |
|---|---|---|
| HOLD, SET | 6519 | 4 |
| SET, HOLD | 6491 | 4 |
| HOLD, SET, HOLD | 6456 | 4 |
| SET, HOLD, SET | 5914 | 4 |
| SET, HOLD, SET, HOLD | 5910 | 4 |
| HOLD, SET, HOLD, SET | 5899 | 4 |
| HOLD, LITERAL | 4374 | 4 |
| LITERAL, HOLD | 4274 | 4 |
| HOLD, LITERAL, HOLD | 3945 | 4 |
| LITERAL, HOLD, LITERAL | 3552 | 4 |

Those occurrences overlap each other and other patterns, so they are a detection count and not a coverage figure. The priced question is the exact one, and section 12 answers it.

**The anti-overfitting rule, applied before the result is known.** a pattern used once can never pay: its body must be stored in full and there is no second use to amortise it against. 4135 of the distinct exact patterns in this corpus occur exactly once and are excluded from the bound instead of being counted as discoveries.

## 7. Per-Song Grammar

Each song was given its own induction: start from SET, then repeatedly add the construction that lowers the *grand total* - stream, parameters, residual, the construction's own definition and the decoder - and stop when nothing lowers it. A construction must therefore earn its own installation before it can join a grammar. Ties break on the lower opcode, and the step history is kept so the stopping decision can be audited.

| song | induced vocabulary | count | ratio | ratio with grammar | structural coverage | residual share | grand total (bytes) |
|---|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | SET, HOLD, RAMP, TOGGLE | 4 | 0.702445 | 0.705894 | 55.9% | 42.0% | 56072 |
| `Ninja_Commando__sub0` | SET, HOLD, TOGGLE | 3 | 0.314934 | 0.318734 | 77.4% | 21.0% | 17444 |
| `Red_Max__sub0` | SET, HOLD, RAMP, TOGGLE | 4 | 0.517474 | 0.521878 | 69.5% | 28.1% | 32465 |
| `Warhawk__sub0` | SET, HOLD, RAMP, TOGGLE | 4 | 0.576015 | 0.578823 | 64.7% | 32.7% | 56470 |

**The step history of the first song, as an example of how a decision is reached.**

| step | candidate added | trial vocabulary | grand total | gain (bytes) | accepted |
|---|---|---|---|---|---|
| 1 | HOLD | SET, HOLD | 57322 | 27196 | yes |
| 2 | RAMP | SET, HOLD, RAMP | 56209 | 1113 | yes |
| 3 | TOGGLE | SET, HOLD, RAMP, TOGGLE | 56072 | 137 | yes |
| 4 | DELTA | SET, HOLD, DELTA, RAMP, TOGGLE | 56126 | -54 | no |

**What the inductions disagree about is the interesting part.** DELTA is rejected by every song, and RAMP is rejected by one. The songs are not equally complex temporal objects, and the per-song numbers say how much: the residual share ranges from about a fifth to about two fifths of frames, and that range is the honest measure of how much of each song the grammar does not explain.

## 8. Shared Grammar

The smallest set of constructions common to all four songs, and the largest set any of them used. The two are reported together because the gap between them is the honest measure of how much vocabulary a shared grammar must sacrifice.

| song | induced vocabulary |
|---|---|
| `Draconus_2024__sub0` | HOLD, RAMP, TOGGLE |
| `Ninja_Commando__sub0` | HOLD, TOGGLE |
| `Red_Max__sub0` | HOLD, RAMP, TOGGLE |
| `Warhawk__sub0` | HOLD, RAMP, TOGGLE |

| construction | induced in which songs | songs |
|---|---|---|
| HOLD | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | 4 |
| RAMP | Draconus_2024__sub0, Red_Max__sub0, Warhawk__sub0 | 3 |
| TOGGLE | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | 4 |

**Smallest common vocabulary: HOLD, TOGGLE.**

**Union of all four: HOLD, RAMP, TOGGLE.**

The shared grammar does not have to share parameters. RAMP can be a construction all four songs use while every song drives it with different deltas and lengths, and section 10 separates those two facts rather than blurring them.

## 9. Leave-One-Out

Induce on three songs, then encode the fourth. Three arms, because generalisation means three different things and conflating them would flatter the result.

| arm | what it allows | mean ratio | mean structural coverage | mean residual share |
|---|---|---|---|---|
| shared_vocabulary_arm | only the constructions every training song induced, parameters free | 0.540617 | 61.7% | 36.1% |
| union_vocabulary_arm | every construction any training song induced, parameters free | 0.527562 | 67.2% | 30.6% |
| frozen_parameter_arm | every construction, but only parameter shapes seen in training | 0.566733 | 62.0% | 35.8% |

| song | trained on | shared vocabulary | vocabulary arm | union arm | frozen parameters | unseen parameter share |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | Warhawk__sub0, Ninja_Commando__sub0, Red_Max__sub0 | HOLD, TOGGLE | 0.717275 | 0.702445 | 0.705542 | 0.9% |
| `Ninja_Commando__sub0` | Draconus_2024__sub0, Warhawk__sub0, Red_Max__sub0 | HOLD, RAMP, TOGGLE | 0.314312 | 0.314312 | 0.413474 | 5.8% |
| `Red_Max__sub0` | Draconus_2024__sub0, Warhawk__sub0, Ninja_Commando__sub0 | HOLD, TOGGLE | 0.547180 | 0.517474 | 0.558658 | 9.8% |
| `Warhawk__sub0` | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0 | HOLD, TOGGLE | 0.583702 | 0.576015 | 0.589258 | 14.2% |

**The vocabulary arm is indistinguishable from the in-sample result.** Adding the constructions a song did not itself induce costs essentially nothing, so the vocabulary is genuinely shared rather than fitted. Freezing the parameters costs a measurable but modest amount, and the unseen-parameter share is small.

**The REPEAT lexicon is the exception, and it is categorical.**

| song | shared lexicon offered (blocks) | blocks matched | references emitted | ratio with the frozen lexicon |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 1228 | 4 | 0 | 0.702117 |
| `Warhawk__sub0` | 949 | 0 | 0 | 0.575923 |
| `Ninja_Commando__sub0` | 1538 | 3 | 0 | 0.314312 |
| `Red_Max__sub0` | 1580 | 0 | 0 | 0.517377 |

Offered an average of 1324 blocks built from the other three songs, the held-out song matched 2 of them and emitted 0 references in total. Its mean ratio falls back to 0.527432 - the grammar's own 0.527432. The lexicon is a memorisation of one song wearing the clothes of a construction.

## 10. Parameter Generalization

Whether a construction exists and whether it is driven the same way are two different questions, and they are measured separately. A grammar of five constructions that every song drives with wildly different deltas is far more generalisable than one that each song drives with a private parameter, and only this table tells them apart.

Mean vocabulary overlap across songs: **1.000000** (intersection over union of the constructions each song uses).

| construction | songs present | parameter cardinality by song | total cardinality | shared parameter shapes | occurrences | parameters generalise? |
|---|---|---|---|---|---|---|
| DELTA | 3 | Draconus 2, Ninja 0, Red 1, Warhawk 1 | 3 | 0 | 41 | **no** |
| HOLD | 4 | Draconus 1, Ninja 1, Red 1, Warhawk 1 | 1 | 1 | 11286 | yes |
| RAMP | 4 | Draconus 5, Ninja 1, Red 10, Warhawk 5 | 16 | 1 | 3219 | yes |
| TOGGLE | 4 | Draconus 2, Ninja 9, Red 4, Warhawk 35 | 49 | 0 | 649 | **no** |

A parameter shape is the neutral part of a construction's parameters: the delta for DELTA and RAMP, the two endpoints for TOGGLE, nothing for HOLD. The register is excluded, because the register is not what makes two uses the same.

**The split is real.** every construction is present in the songs that use it, but DELTA, TOGGLE shares no exact parameter shape across all four. For those the construction transfers and the values do not, which is exactly the distinction the brief asks to keep visible.

## 11. Exact Reconstruction

Every encoded fragment is decoded and compared with the canonical raw payload byte for byte. A row whose `exact` is false is not a result, so this section is a gate on every other number in the report.

| song | raw bytes | container bytes | exact | first divergence frame | accounting check | operations used |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 55772 | yes | n/a | True | DELTA, HOLD, LITERAL, RAMP, SET, TOGGLE |
| `Ninja_Commando__sub0` | 54729 | 17202 | yes | n/a | True | HOLD, LITERAL, RAMP, SET, TOGGLE |
| `Red_Max__sub0` | 62208 | 32185 | yes | n/a | True | DELTA, HOLD, LITERAL, RAMP, SET, TOGGLE |
| `Warhawk__sub0` | 97560 | 56187 | yes | n/a | True | DELTA, HOLD, LITERAL, RAMP, SET, TOGGLE |

All five candidate grammars are exact on all four songs: **True**. The accounting check confirms that stream, parameter, residual and lexicon bytes together equal the container exactly, so no byte is hidden outside the model.

**No approximation is permitted anywhere.** No pitch approximation, no quantisation, no rounded values, no omitted silent frames, no inferred values, no implicit musical knowledge. A construction that could only approximate would be marked LOSSY and excluded from the exact grammar; none of the constructions here needed that marking, because every one of them writes explicit values.

## 12. Compression and Description Length

A saving may not be claimed unless the definition that produces it is paid for. Every total on this page is grammar definition + parameters + stream + residual + lexicon table + decoder, and the grammar definition is charged per construction at the current 6502 player's own code density.

| candidate | vocabulary | ratio | ratio with grammar and decoder | stream | parameters | residual | lexicon table | grammar + decoder | grand total |
|---|---|---|---|---|---|---|---|---|---|
| **G0** | - | 1.000000 | 1.000000 | 0 | 0 | 0 | n/a | 0 | 293979 |
| **G1** | - | 0.508255 | 0.508255 | n/a | n/a | n/a | n/a | 0 | n/a |
| **G2** | SET, HOLD | 0.579727 | 0.581671 | 11121.0 | 1621.5 | 30925.0 | 1 | 99.0 | 43804.5 |
| **G3** | SET, HOLD, DELTA | 0.569305 | 0.572393 | 11972.75 | 2284.25 | 28676.75 | 1 | 139.0 | 43150.75 |
| **G4** | SET, HOLD, DELTA, RAMP | 0.566260 | 0.570291 | 12538.25 | 3716.5 | 26437.5 | 1 | 172.0 | 42975.25 |
| **G5** | SET, HOLD, DELTA, RAMP, TOGGLE | 0.527432 | 0.532493 | 12876.75 | 4077.75 | 23381.0 | 1 | 208.0 | 40690.5 |
| **G6** | SET, HOLD, DELTA, RAMP, TOGGLE, REPEAT | 0.328678 | 0.334568 | 2223.0 | 2423.5 | 2960.75 | 17378 | 237.0 | 25397.0 |

**The REPEAT bound, replaced by a real encoding.** The induction first priced a block reference with an optimistic bound. That bound is not the result; the result is the G6 row above, which was built, encoded, decoded and compared.

| exact pattern extraction | value |
|---|---|
| candidate patterns | 7227 |
| references emitted | 7150 |
| distinct patterns used | 1809 |
| gross saving (bytes) | 126141 |
| table cost (bytes) | 47398 |
| net (bytes) | 78743 |
| the saving is bounded by the data it replaces | True |
| verdict | REPEAT_CONSTRUCTION_PAYS |

The first version of that extraction summed occurrences of overlapping n-grams and returned a saving of 955,678 bytes against 161,225 bytes of operations, which is self-evidently impossible. The current extraction is a left-to-right greedy pass that consumes each match, so no operation is referenced twice and the saving cannot exceed the data. The correction is recorded here because the wrong number was briefly believed.

**Where the bytes actually go.** for the grammar proper (G5) the largest bucket is the residual at 23381.0 bytes, which is the honest statement that the grammar does not describe about two fifths of the frames; for G6 the largest bucket is the per-song lexicon. That is the whole difference between a grammar and a dictionary.

## 13. Complexity

A deliberately simple score, defined once and applied identically to every candidate: number of constructions + number of parameter fields + decoder states + special cases. It is not claimed to be a perfect metric. It is claimed to be explicit, deterministic and uniform, which is what makes a Pareto comparison between candidates meaningful.

| candidate | constructions | parameter fields | decoder states | special cases | score | definition lines (est.) | decoder RAM (bytes) |
|---|---|---|---|---|---|---|---|
| G2 | 2 | 2 | 2 | 1 | 7 | 54 | 45 |
| G3 | 3 | 3 | 3 | 3 | 12 | 76 | 45 |
| G4 | 4 | 4 | 5 | 5 | 18 | 94 | 45 |
| G5 | 5 | 6 | 7 | 6 | 24 | 114 | 45 |
| G6 | 6 | 7 | 9 | 7 | 29 | 130 | 45 |

G0 and G1 have no complexity row because they have no vocabulary: one is the raw stream and the other is a byte format with no constructions at all. That absence is the point of the section.


**Pareto frontier** over complexity (down), structural coverage (up) and ratio with the grammar charged (down). Computed by pairwise domination on a name-sorted list, so an exact tie can never reorder it between runs.

| candidate | complexity score | structural coverage | ratio with grammar | constructions |
|---|---|---|---|---|
| G2 | 7 | 56.8% | 0.581671 | SET, HOLD |
| G3 | 12 | 59.8% | 0.572393 | SET, HOLD, DELTA |
| G4 | 18 | 62.6% | 0.570291 | SET, HOLD, DELTA, RAMP |
| G5 | 24 | 67.2% | 0.532493 | SET, HOLD, DELTA, RAMP, TOGGLE |
| G6 | 29 | 96.4% | 0.334568 | SET, HOLD, DELTA, RAMP, TOGGLE, REPEAT |

**Decoder RAM, which the byte count does not show.** The grammar decodes from 45 bytes of state and needs no buffer at all, because a frame-at-a-time decoder can advance nine channel programs in step. Stage 18's best configuration needs a 9,216-byte window. On a machine with 16 KB in total that difference is not a detail - it is the difference between a format that can run and one that cannot.

**Residual cost is part of complexity.** A grammar that describes a third of the stream and carries the rest verbatim is not simpler than one that describes most of it; the residual is charged in section 12 and its share is reported in sections 7 and 11, so a small vocabulary cannot be bought with a large residual.

## 14. Stage 17 Comparison

Stage 17 left questions for a later stage and explicitly did not answer them. Every one gets a status and a verdict here. `status` says whether this stage looked at the question; `verdict` says what it found. A question can be NOT_ADDRESSED and still carry a verdict, and it is reported that way rather than left out.

| status | verdict | Stage 17 question | what this stage found |
|---|---|---|---|
| NOT_ADDRESSED | INCONCLUSIVE | Is the abstraction's failure a limit of the vocabulary or of the detector? | a question about the event vocabulary, not about a byte stream |
| NOT_ADDRESSED | INCONCLUSIVE | When the events come from a composer rather than from a recorded performance, is the encoding smaller? Note-granularity input is the only route the compression finding leaves open. | no music was generated here. One number bears on it: a REPEAT lexicon trained on three songs supplied zero references to the fourth, so a generator would not inherit the byte advantage for free |
| ADDRESSED | INCONCLUSIVE | How far is the current 3-byte note format from the raw dump it replaces? That comparison was never made and it is the one the event language has to win. | this stage does not price the current note format. What it shows is that the grammar proper does not beat the raw dump by much, and that the thing which does beat it - the lexicon - is per-song and so is not a rival representation |
| ADDRESSED | SUPPORTED | Is there any representation of this behaviour that beats the raw dump? If not, the register dump is the right format and the middle layer is unnecessary. | an exact description smaller than the raw dump now exists at two levels: the grammar proper (G5, mean ratio 0.53) and the grammar plus a per-song REPEAT lexicon (G6, mean ratio 0.33). Both are smaller than raw, and both are exact |
| NOT_ADDRESSED | INCONCLUSIVE | Is a technique heard as the same thing when its context changes? Part R says the language does not care; nobody has checked whether a listener does. | no listening test was run and none is proposed here |

**2 of 5 addressed, 1 supported, 0 refuted.**

The question this stage answers most directly is whether *any* representation beats the raw dump. Yes, at two levels: the grammar proper at about half, and the grammar plus a per-song lexicon at about a third. But the second answer is the one that would have made Stage 17's middle layer unnecessary, and it turns out to be a dictionary rather than a language - so the honest reading is that Stage 17's negative result survives, for a sharper reason than before.

**Stage 15/16 techniques, mapped empirically rather than by name.** For every technique the Stage 15 record reports, the frames it claims were looked up in the grammar's own parse of the reference song `Draconus_2024__sub0`. These are interpretations, not model elements, and no construction is ever renamed after a technique.

| technique | frames inspected | dominant construction | share | correspondence | mapped construction |
|---|---|---|---|---|---|
| ARPEGGIO | 192 | HOLD | 18.8% | NO_CORRESPONDENCE | - |
| DISTORTION_CHANGE | 48 | - | n/a | NO_CORRESPONDENCE | - |
| GENERATOR_CHANGE | 400 | RAMP | 0.5% | NO_CORRESPONDENCE | - |
| NOTE_OFF | 400 | HOLD | 23.2% | NO_CORRESPONDENCE | - |
| NOTE_ON | 400 | RAMP | 10.8% | NO_CORRESPONDENCE | - |
| PITCH_CHANGE | 800 | HOLD | 6.2% | NO_CORRESPONDENCE | - |
| PITCH_SLIDE | 800 | RAMP | 45.5% | PARTIAL_CORRESPONDENCE | RAMP |
| PITCH_SWEEP | 800 | RAMP | 8.6% | NO_CORRESPONDENCE | - |
| REGISTER_PATTERN_CHANGE | 252 | HOLD | 27.4% | PARTIAL_CORRESPONDENCE | HOLD |
| TREMOLO | 800 | HOLD | 18.6% | NO_CORRESPONDENCE | - |
| VIBRATO | 88 | HOLD | 18.2% | NO_CORRESPONDENCE | - |
| VOLUME_CHANGE | 800 | TOGGLE | 28.9% | PARTIAL_CORRESPONDENCE | TOGGLE |
| VOLUME_ENVELOPE | 800 | HOLD | 18.8% | NO_CORRESPONDENCE | - |

the Stage 15 event record describes its *reference song* only, and it is sampled to a cap per technique. This mapping therefore covers one song and a sample of its events, and it is reported as such rather than presented as a corpus-wide finding.

Counts: NO_CORRESPONDENCE 10, PARTIAL_CORRESPONDENCE 3. A technique that maps to nothing means the grammar describes its frames with SET or with the residual, which is a real finding: those techniques are named behaviours the temporal level does not distinguish.

## 15. Stage 18 Comparison

Stage 18 is a baseline, not a rival. It produced a byte format; this stage produced a model. The comparison is therefore not only in bytes, and it is reported on six axes at once so that neither side can win by choosing the axis.

| song | raw | G5 (grammar) | G5 ratio | G6 (grammar + lexicon) | G6 ratio | G6 lexicon share | Stage 18 best | Stage 18 ratio |
|---|---|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 55772 | 0.702117 | 35278 | 0.444117 | 67.3% | 50007 | 0.629446 |
| `Warhawk__sub0` | 97560 | 56187 | 0.575923 | 35158 | 0.360373 | 64.7% | 52090 | 0.533862 |
| `Ninja_Commando__sub0` | 54729 | 17202 | 0.314312 | 16361 | 0.298946 | 87.7% | 21318 | 0.389434 |
| `Red_Max__sub0` | 62208 | 32185 | 0.517377 | 13143 | 0.211275 | 66.0% | 29883 | 0.480280 |

| axis | G5 grammar | G6 grammar + lexicon | Stage 18 best |
|---|---|---|---|
| mean ratio | 0.527432 | 0.328678 | 0.508255 |
| ratio with its own definition charged | 0.532493 | 0.328678 | 0.508255 |
| exact | yes | yes | yes |
| generalises across songs | yes | **no** - lexicon transfers nothing | not applicable, it is a format |
| decoder RAM (bytes) | 45 | same | 9216 |
| conceptual usefulness | a vocabulary a generator could target | a dictionary of one song | none claimed |

**Stage 18 compresses better than the grammar proper; Stage 19 is structurally more useful. Neither statement is a mistake.** The grammar proper is 0.53 against Stage 18's 0.51 - close, and in the same league. The configuration that genuinely beats Stage 18 does so by carrying most of its own bytes in a per-song lexicon, and that lexicon is worth nothing on a song it was not built from. This stage did not optimise to beat Stage 18 in bytes, and the place where it does win in bytes is the place where it stops being a grammar.

## 16. Falsification

Six deliberate attempts to break the result. Each states the condition that would have refuted the hypothesis, and reports whether that condition holds. Negative answers are kept in.

| test | hypothesis under attack | refuting condition | holds? | verdict |
|---|---|---|---|---|
| F1 | is most of the grammar just SET, which would make it Stage 17 again? | SET accounts for the majority of operations | no | REFUTED: SET is not the majority, and it is the least efficient construction per frame, so the parse avoids it wherever anything else applies |
| F2 | do DELTA, RAMP and TOGGLE really occur across songs? | a construction appears in only one song | no | PARTIALLY_REFUTED: RAMP is induced in 3 of 4 songs and TOGGLE in 4, but DELTA in only 0. The construction the brief asks about most is the one no song keeps |
| F3 | does coverage collapse when the grammar is not induced from the song? | leave-one-out coverage falls far below the in-sample coverage | no | NOT_REFUTED: the vocabulary transfers. Only the per-song REPEAT lexicon fails, and that is reported separately in F4 |
| F4 | does the residual, or a per-song lexicon, become the dominant part? | the residual or the lexicon is most of the artefact | **yes** | REFUTED FOR THE GRAMMAR, CONFIRMED FOR THE LEXICON. The grammar's residual is about 31% of frames, but the only configuration that beats raw by a wide margin carries most of its own bytes in a per-song lexicon, and that lexicon supplies zero references to a song it was not built from |
| F5 | is the grammar small only because it is allowed very many parameters? | parameter cardinality is large and shared parameters are empty | **yes** | PARTIALLY_REFUTED: every construction is driven by a handful of parameter shapes per song, but TOGGLE shares no exact parameter pair across all four songs, so for TOGGLE the shape transfers and the values do not |
| F6 | does each new construction buy only a marginal gain? | a construction's removal changes the total by less than one percent | no | MIXED, AND THE SHARPEST RESULT OF THE STAGE. TOGGLE earns its place: adding it takes the mean grand total from 42975.25 to 40690.5, 5.3 percent. Adding RAMP on top of DELTA moves it from 43150.75 to 42975.25, only 0.4 percent, and DELTA is rejected outright by every song's own induction (G2 43804.5 against G3 43150.75) - the opposite of the hypothesis, reported as such |

**The measured numbers behind each test.**

- **F1 - is most of the grammar just SET, which would make it Stage 17 again?**

  - measured: `{"all_operations": 28951, "set_operations": 6566, "set_share": 0.226797}`

- **F2 - do DELTA, RAMP and TOGGLE really occur across songs?**

  - measured: `{"DELTA_songs": [], "RAMP_songs": ["Draconus_2024__sub0", "Red_Max__sub0", "Warhawk__sub0"], "TOGGLE_songs": ["Draconus_2024__sub0", "Ninja_Commando__sub0", "Red_Max__sub0", "Warhawk__sub0"], "per_song_induced": {"Draconus_2024__sub0": ["HOLD", "RAMP", "SET", "TOGGLE"], "Ninja_Commando__sub0": ["HOLD", "SET", "TOGGLE"], "Red_Max__sub0": ["HOLD", "RAMP", "SET", "TOGGLE"], "Warhawk__sub0": ["HOLD", "RAMP", "SET", "TOGGLE"]}}`

- **F3 - does coverage collapse when the grammar is not induced from the song?**

  - measured: `{"in_sample_structural_coverage": 0.672079, "shared_vocabulary_coverage": 0.617101}`

- **F4 - does the residual, or a per-song lexicon, become the dominant part?**

  - measured: `{"lexicon_loo_mean_ratio": 0.527432, "lexicon_loo_references": 0, "lexicon_share_of_G6": 0.714254, "residual_share": 0.306187}`

- **F5 - is the grammar small only because it is allowed very many parameters?**

  - measured: `{"DELTA": {"shared_parameter_count": 0, "songs_present_count": 3, "total_parameter_cardinality": 3}, "HOLD": {"shared_parameter_count": 1, "songs_present_count": 4, "total_parameter_cardinality": 1}, "RAMP": {"shared_parameter_count": 1, "songs_present_count": 4, "total_parameter_cardinality": 16}, "TOGGLE": {"shared_parameter_count": 0, "songs_present_count": 4, "total_parameter_cardinality": 49}}`

- **F6 - does each new construction buy only a marginal gain?**

  - measured: `{"G0": {"mean_grand_total": 293979, "mean_ratio_with_grammar": 1.0, "mean_structural_coverage": 0.0, "primitives": []}, "G1": {"mean_grand_total": null, "mean_ratio_with_grammar": 0.508255, "mean_structural_coverage": null, "primitives": []}, "G2": {"mean_grand_total": 43804.5, "mean_ratio_with_grammar": 0.581671, "mean_structural_coverage": 0.567981, "primitives": ["SET", "HOLD"]}, "G3": {"mean_grand_total": 43150.75, "mean_ratio_with_grammar": 0.572393, "mean_structural_coverage": 0.59762, "primitives": ["SET", "HOLD", "DELTA"]}, "G4": {"mean_grand_total": 42975.25, "mean_ratio_with_grammar": 0.570291, "mean_structural_coverage": 0.626265, "primitives": ["SET", "HOLD", "DELTA", "RAMP"]}, "G5": {"mean_grand_total": 40690.5, "mean_ratio_with_grammar": 0.532493, "mean_structural_coverage": 0.672079, "primitives": ["SET", "HOLD", "DELTA", "RAMP", "TOGGLE"]}, "G6": {"mean_grand_total": 25397.0, "mean_ratio_with_grammar": 0.334568, "mean_structural_coverage": 0.964292, "primitives": ["SET", "HOLD", "DELTA", "RAMP", "TOGGLE", "REPEAT"]}}`


the two results that matter are F1 and F4. F1 says the grammar is not Stage 17 in a new coat. F4 says the configuration that looks dramatically better than raw is buying its margin from a per-song lexicon rather than from a shared construction, and the lexicon experiments of section 16 are what prove it.

## 17. Implications for Composer

Research implications only. **No composer feature was implemented, no IR was extended, no DSL was changed, no schema was added and no instrument bank was created.** The STOP condition of the brief is honoured: this section says what the results imply, not what was built.

**What the results do imply.**

- A composer-facing temporal layer would have four constructions to target, not five: HOLD, TOGGLE are the ones every song kept, and RAMP is kept by all but one. That is a small enough target to be worth someone's time.

- The layer would have to be *exact*, and the residual is the reason it cannot be small: 30.6% of frames are not described by any construction and are carried verbatim. A composer layer that aspires to be a bridge must explain that share or accept that it is a compressor with a grammar on top.

- The decoder is cheap enough to be plausible: tens of bytes of state, no buffer, no table. If a future stage ever wants a temporal layer on the machine, RAM is not what stops it.

- The parameter distributions are narrow. Each construction is driven by a handful of shapes per song, which means a generator would have few parameters to get right - and it also means the unseen-parameter share of about eight percent is a floor on how much a generator would have to get *wrong* before it stopped decoding exactly.

**What the results do not imply.**

- That a grammar-shaped layer would be musically better. Exactness is not usefulness, and nothing here was listened to.

- That a generator is feasible. Generalisation and generative usefulness are separate facts, measured separately here, and only the first was established.

- That the lexicon could be replaced by a generator. Zero references transferred across all four folds; the lexicon is not reachable from a shared vocabulary, and a future stage that wanted the byte saving would have to generate the lexicon itself - which is the same problem as generating the song.

**One concrete suggestion for a future stage**, offered as a question and not as a plan: compile a composition into these four constructions and measure the coverage and the residual against the same four songs. That is the only experiment that could move H3, and it is not this stage.

## 18. Final Verdict

| level | verdict |
|---|---|
| H1 existence | TEMPORAL_GRAMMAR_EXISTENCE_SUPPORTED |
| H2 generalization | TEMPORAL_GRAMMAR_GENERALIZATION_PARTIAL |
| H3 generative usefulness | GENERATOR_LAYER_NOT_JUSTIFIED |
| player integration | PLAYER_INTEGRATION_NOT_JUSTIFIED |

**H1 - existence.** **TEMPORAL_GRAMMAR_EXISTENCE_SUPPORTED**. Measured: {"all_exact": true, "saving_percent_with_grammar": 46.750665, "structural_coverage": 0.672079}

**H2 - generalization.** **TEMPORAL_GRAMMAR_GENERALIZATION_PARTIAL**. Measured: {"constructions_transferring": ["HOLD", "RAMP", "TOGGLE"], "in_sample_ratio": 0.527432, "induced_in_share_of_songs": {"DELTA": 0.0, "HOLD": 1.0, "LITERAL": 0.0, "RAMP": 0.75, "REPEAT": 0.0, "SET": 1.0, "TOGGLE": 1.0}, "leave_one_out_frozen_parameter_ratio": 0.566733, "leave_one_out_vocabulary_ratio": 0.527562, "lexicon_blocks_offered": 1323.75, "lexicon_in_sample_ratio": 0.328678, "lexicon_leave_one_out_ratio": 0.527432, "lexicon_references_transferred": 0, "unseen_parameter_share": 0.077013, "vocabulary_loss_share": 0.000246}

**H3 - generative usefulness.** **GENERATOR_LAYER_NOT_JUSTIFIED**. Measured: {"complexity_score": 24, "grammar_definition_lines": 114, "lexicon_transfers": false, "primitives": 5, "structural_coverage": 0.672079} Note: H3 asks whether a *generator* could produce this grammar, and no generator was built or tested here. It is therefore only ever reported as not justified on the evidence available, never as promising

**Player integration.** **PLAYER_INTEGRATION_NOT_JUSTIFIED**. Measured: 5 of 7 conditions met; deciding condition: the grammar proper beats Stage 18's best byte codec

Where the integration verdict is a refusal, the deciding condition is named rather than left implicit, so a future stage knows exactly what it would have to change:

| condition | met | measured |
|---|---|---|
| the grammar proper beats the raw dump by a wide margin | yes | 46.750665 |
| the grammar proper beats Stage 18's best byte codec | **no** | {"grammar": 0.532493, "stage18": 0.508255} |
| the advantage survives when the lexicon does not transfer | yes | {"grammar": 0.532493, "lexicon_leave_one_out": 0.527432} |
| a decoder fits in a few dozen bytes of RAM | yes | 45 |
| the shared vocabulary covers a majority of frames | yes | 0.672079 |
| a small number of constructions is enough | yes | {"decoder_states": 7, "definition_lines_estimate": 114, "parameter_field_names": ["a", "b", "delta", "frames", "start", "value"], "parameter_fields": 6, "primitives": 5, "score": 24, "special_cases": 6} |
| the grammar is smaller than the format it would replace | **no** | "not established. The current note format priced by Stage 17 is several times smaller than the grammar proper and is not an exact representation, so the comparison is not like for like and is not claimed" |

The deciding condition is: **the grammar proper beats Stage 18's best byte codec**.

**Why the answer is not simply yes or no.** The four songs really do share a small, neutral vocabulary of temporal constructions, it really is exact, and it really does transfer to a song that did not contribute to it. That part is a genuine positive result and it is the part the brief was hoping for. But the vocabulary spends about half the raw stream once its own definition is charged, which is not a layer between a composition IR and exact playback - it is a compression format with a grammar inside it. The one thing that is dramatically smaller is a per-song lexicon, and a lexicon that supplies zero references to a song it was not built from is a memorisation, not a language.

## Final question

> **Can the four analysed historical POKEY performance streams be described by a small, neutral and generalisable set of temporal constructions, simple enough to potentially sit between the composition IR and exact POKEY playback?**

**Yes for the constructions, no for the layer. Four neutral constructions - SET, HOLD, RAMP and TOGGLE, with DELTA rejected by every song - describe a majority of the frames exactly, transfer to a song that did not contribute to them, and decode from a few dozen bytes of RAM. But the shared grammar proper is not small: it is about half the raw stream, which is not a bridge between a composition IR and exact playback, and the only configuration that is dramatically smaller buys its margin from a per-song lexicon that transfers nothing.**

The answer is derived from the evidence and not from intuition. Every number below was produced by encoding a stream and decoding it again, and the axes are listed in the order the brief asks for them:

| axis the brief asks for | measured |
|---|---|
| coverage | structural coverage 67.2%, frame coverage 69.4%, change-event coverage 28.2% |
| exact reconstruction | all candidates exact on all songs: True |
| compression | grammar ratio 0.527432, with grammar and decoder charged 0.532493 |
| residual cost | 30.6% of frames carried verbatim |
| grammar complexity | 24 (5 constructions, 6 parameter fields, 7 decoder states, 6 special cases) |
| cross-song generalization | leave-one-out vocabulary ratio 0.527562 |
| leave-one-out (frozen parameters) | 0.566733, unseen parameters 7.7% |
| lexicon transfer | 0 references from a shared lexicon of ~1324 blocks |
| parameter generalization | vocabulary overlap 1.000000; see section 10 for which constructions share values |

**So: yes for the language, no for the layer.** A small neutral set of temporal constructions does describe these four streams exactly, and it transfers to a song it was not induced from. But that language is not small in bytes - it spends about half the raw stream once its own definition is charged - and the one result that is dramatically smaller comes from a per-song lexicon that reproduces nothing on an unseen song. A layer between a composition IR and exact playback would have to be small *and* shared, and this one is shared but not small, or small but not shared. That is not a forced positive and it is not a clean negative either: it is the mixed result the brief asked to be reported as mixed rather than rounded.

**What would change the answer.**

- A composer-generated trace, rather than a recorded performance, showing that the same four constructions cover a majority of the frames. The frozen-parameter result suggests this is the one route left, and it was not tested here.

- A construction that describes the ~40% residual without a per-song lexicon. Today the residual is carried verbatim, and that is the reason the exact grammar cannot get below roughly half of raw.

- Evidence that a generator can emit these constructions with realistic parameters. The unseen-parameter share of about eight percent says the parameter problem is small but not zero, and no generator was built.

- A listening test, if anyone wants to claim the constructions are musically useful. This stage cannot and does not.

**What this stage does not claim.**

- that the grammar is a good Composer abstraction - exactness is not usefulness

- that generalization implies generative usefulness; the two are measured separately here for exactly that reason

- that compression equals musical meaning; the report keeps them apart throughout

**STOP.** Nothing was implemented in production. No player, no composer feature, no Music IR change, no POKEY IR change, no DSL change, no production schema, no instrument bank, no listening test. If this result is judged interesting, the next stage it invites is a generation experiment - whether a composer or a model can emit these four constructions with realistic parameters - and that is a different experiment from this one.
