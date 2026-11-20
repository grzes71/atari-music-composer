# Stage 18 - Temporal Compression of the POKEY Performance History

A falsification experiment. Stage 17 showed that a neutral performance-event language is faithful but does not compress. Stage 18 asks the narrower structural question that remains: does the historical POKEY stream at 50 Hz contain real temporal redundancy that a neutral, lossless, practically decodable format could exploit, without introducing any semantic notion such as instrument, melody or effect?

Analysis only. The 6502 player, the Composer, the DSL, the Music IR, the POKEY IR, the production schemas and the SoundProfile system are read and hashed, never modified. No audio was rendered, no music was generated, no instrument was transferred, and no listening test was run. Nothing was implemented in production.

Analysis version `stage18/1`.

## 1. Executive summary

- **Does temporal redundancy exist? Yes.** The stream is far from random: the four songs use between 1,905 and 4,668 *distinct* frames out of 6,081 to 10,840, and every song has only about 2.4 to 3.8 register changes per frame.
- **Does it give practical compression? Yes, about 49.2 percent.** The best configuration (`hybrid[block_frames=512]`) has a mean ratio of 0.508255 and reconstructs all four songs **byte for byte**. Every one of the 120 measurements is exact.
- **Is it generalisable? Yes.** One configuration with one parameter set is lossless and compressing on all four songs, and the best method varies by song, which the report shows rather than averages away.
- **Is it worth developing further? Not as a player foundation.** It beats the Stage 17 event IR by 3.789205x, but the current note format is still 4.9x smaller than any exact encoding found here, and the decoders that compress best need buffer RAM a 16 KB machine does not have.

| verdict | result |
|---|---|
| temporal compression | `TEMPORAL_COMPRESSION_SUPPORTED` |
| player integration | `PLAYER_INTEGRATION_NOT_JUSTIFIED` |

The redundancy is real and the compression is real. It is simply not the comparison that decides whether anything should change. What follows is the measurement.

## 2. Dataset

Exactly the four Stage 16 songs, read as register traces rather than re-chosen here. No synthetic data is used as primary evidence. The selection record is hashed:

| song | frames | frame period (us) | canonical raw payload (bytes) |
|---|---|---|---|
| `Draconus_2024__sub0` | 8826 | 20056 | 79434 |
| `Warhawk__sub0` | 10840 | 20056 | 97560 |
| `Ninja_Commando__sub0` | 6081 | 20056 | 54729 |
| `Red_Max__sub0` | 6912 | 20056 | 62208 |

- selection record: `C:\Users\grzes\Documents\Projects\atari-music\reports\stage16\song_selection.json`
- its SHA-256: `277f6c1f78795d60dc8847318c0990aad8faa41e7857a9e410fe9e0d3a0bec7b`

## 3. Canonical raw representation

Before any experiments, one unambiguous reference format was defined, because the baseline decides every ratio in the rest of the report. It is not assumed to be optimal; the point of the experiments is to find out what beats it.

```text
frame = AUDF1, AUDC1, AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4, AUDCTL, absolute, one frame after another, nine bytes per frame, AUDCTL repeated every frame even though it never changes in this corpus
```

| design question | decision |
|---|---|
| absolute_or_delta | absolute: no previous-frame dependency in the baseline |
| audctl | part of every frame, not stream-level state |
| container | 12 bytes: 'P8', codec id, flags, frame count u32, period in microseconds u32. Every codec shares this header, so it is a constant in the comparison and cannot bias a ranking |
| first_values | frame 0 is stored like every other frame; no special case |
| how_no_change_is_represented | it is not represented: the baseline repeats the value, which is what makes delta and run-length coding measurable rather than assumed |

| song | frames | raw payload | with container | share of baseline |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 8826 | 79434 | 79446 | 100% |
| `Warhawk__sub0` | 10840 | 97560 | 97572 | 100% |
| `Ninja_Commando__sub0` | 6081 | 54729 | 54741 | 100% |
| `Red_Max__sub0` | 6912 | 62208 | 62220 | 100% |

The raw baseline is **100%**. Every ratio in this report is `compressed_bytes / raw_bytes`, every byte needed for exact reconstruction is counted, and every codec shares the same 12-byte container header so the header cannot bias a ranking.

## 4. RLE results

Two run-length schemes: whole-frame RLE treats a frame as one state, per-register RLE runs nine independent streams. Neither is assumed to be better; both are measured with their headers.

| configuration | song | raw bytes | compressed | ratio | saving % | lossless |
|---|---|---|---|---|---|---|
| `rle_frame` | Draconus | 79446 | 86464 | 1.088337 | -8.833673 | yes |
| `rle_frame` | Ninja | 54741 | 60544 | 1.106008 | -10.600829 | yes |
| `rle_frame` | Red | 62220 | 69134 | 1.111122 | -11.112183 | yes |
| `rle_frame` | Warhawk | 97572 | 98564 | 1.010167 | -1.016685 | yes |
| `rle_register` | Draconus | 79446 | 67420 | 0.848627 | 15.137326 | yes |
| `rle_register` | Ninja | 54741 | 29083 | 0.531284 | 46.871632 | yes |
| `rle_register` | Red | 62220 | 47297 | 0.760158 | 23.984249 | yes |
| `rle_register` | Warhawk | 97572 | 74064 | 0.75907 | 24.092977 | yes |

**Whole-frame RLE makes the stream larger.** The mean run of identical frames across the corpus is between 1.00 and 1.10 frames, so a run-length record is emitted once per frame and its header is pure overhead. Per-register RLE works, because individual registers hold their value for stretches even while other registers change.

## 5. Delta results

Two delta schemes: fixed-width signed deltas, which is a diagnostic because it stores the same number of bytes, and a zero-run variant that stores only the frames that changed, with a bitmap of which registers changed and one byte per changed register.

| configuration | song | raw bytes | compressed | ratio | saving % | lossless |
|---|---|---|---|---|---|---|
| `delta_fixed` | Draconus | 79446 | 79446 | 1.0 | 0.0 | yes |
| `delta_fixed` | Ninja | 54741 | 54741 | 1.0 | 0.0 | yes |
| `delta_fixed` | Red | 62220 | 62220 | 1.0 | 0.0 | yes |
| `delta_fixed` | Warhawk | 97572 | 97572 | 1.0 | 0.0 | yes |
| `delta_gap` | Draconus | 79446 | 53780 | 0.676938 | 32.306221 | yes |
| `delta_gap` | Ninja | 54741 | 28711 | 0.524488 | 47.551196 | yes |
| `delta_gap` | Red | 62220 | 39519 | 0.635149 | 36.485053 | yes |
| `delta_gap` | Warhawk | 97572 | 65889 | 0.675286 | 32.471406 | yes |

**Do the deltas have structure?** The per-register histograms say yes:


### Draconus_2024__sub0

| register | changes | zero share | distinct deltas | entropy (bits/delta) |
|---|---|---|---|---|
| AUDC1 | 5794 | 0.343456 | 24 | 1.6889 |
| AUDC2 | 5367 | 0.391841 | 55 | 3.5291 |
| AUDC3 | 2510 | 0.715581 | 23 | 1.4276 |
| AUDC4 | 2787 | 0.684193 | 23 | 1.7729 |
| AUDCTL | 0 | 1.0 | 1 | 0.0 |
| AUDF1 | 866 | 0.90187 | 76 | 1.0025 |
| AUDF2 | 6179 | 0.29983 | 72 | 3.7773 |
| AUDF3 | 4273 | 0.515807 | 115 | 2.5496 |
| AUDF4 | 5906 | 0.330765 | 103 | 3.6059 |

### Warhawk__sub0

| register | changes | zero share | distinct deltas | entropy (bits/delta) |
|---|---|---|---|---|
| AUDC1 | 0 | 1.0 | 1 | 0.0 |
| AUDC2 | 9546 | 0.119291 | 9 | 2.6451 |
| AUDC3 | 3746 | 0.654396 | 20 | 1.9374 |
| AUDC4 | 9150 | 0.155826 | 10 | 1.7818 |
| AUDCTL | 0 | 1.0 | 1 | 0.0 |
| AUDF1 | 1231 | 0.886429 | 71 | 1.1606 |
| AUDF2 | 1185 | 0.890673 | 17 | 0.8996 |
| AUDF3 | 6868 | 0.366362 | 92 | 3.5888 |
| AUDF4 | 5282 | 0.512686 | 40 | 3.3354 |

The entropy column is a diagnostic and **not** a size: a representation still has to store the value, and every size in this report was obtained by encoding and decoding real bytes.

## 6. Ramp results

Per register, the value sequence is segmented into CONST, LINEAR and QUAD runs with a literal escape. A model segment is only taken when it is *strictly cheaper* than the literal bytes it replaces, so a segment can never make the stream larger, and the minimum-length sweep the brief asks for is reported in full.

| configuration | song | raw bytes | compressed | ratio | saving % | lossless |
|---|---|---|---|---|---|---|
| `ramps[min_length=2]` | Draconus | 79446 | 54295 | 0.68342 | 31.657982 | yes |
| `ramps[min_length=2]` | Ninja | 54741 | 21050 | 0.384538 | 61.54619 | yes |
| `ramps[min_length=2]` | Red | 62220 | 32339 | 0.519752 | 48.024751 | yes |
| `ramps[min_length=2]` | Warhawk | 97572 | 54444 | 0.557988 | 44.201205 | yes |
| `ramps[min_length=3]` | Draconus | 79446 | 54295 | 0.68342 | 31.657982 | yes |
| `ramps[min_length=3]` | Ninja | 54741 | 21050 | 0.384538 | 61.54619 | yes |
| `ramps[min_length=3]` | Red | 62220 | 32339 | 0.519752 | 48.024751 | yes |
| `ramps[min_length=3]` | Warhawk | 97572 | 54444 | 0.557988 | 44.201205 | yes |
| `ramps[min_length=4]` | Draconus | 79446 | 54295 | 0.68342 | 31.657982 | yes |
| `ramps[min_length=4]` | Ninja | 54741 | 21050 | 0.384538 | 61.54619 | yes |
| `ramps[min_length=4]` | Red | 62220 | 32339 | 0.519752 | 48.024751 | yes |
| `ramps[min_length=4]` | Warhawk | 97572 | 54444 | 0.557988 | 44.201205 | yes |
| `ramps[min_length=5]` | Draconus | 79446 | 54574 | 0.686932 | 31.3068 | yes |
| `ramps[min_length=5]` | Ninja | 54741 | 21010 | 0.383807 | 61.619262 | yes |
| `ramps[min_length=5]` | Red | 62220 | 32339 | 0.519752 | 48.024751 | yes |
| `ramps[min_length=5]` | Warhawk | 97572 | 54373 | 0.55726 | 44.273972 | yes |
| `ramps[min_length=6]` | Draconus | 79446 | 55292 | 0.69597 | 30.403041 | yes |
| `ramps[min_length=6]` | Ninja | 54741 | 21618 | 0.394914 | 60.508577 | yes |
| `ramps[min_length=6]` | Red | 62220 | 32354 | 0.519994 | 48.000643 | yes |
| `ramps[min_length=6]` | Warhawk | 97572 | 54297 | 0.556481 | 44.351863 | yes |
| `ramps[min_length=8]` | Draconus | 79446 | 57547 | 0.724354 | 27.564635 | yes |
| `ramps[min_length=8]` | Ninja | 54741 | 21618 | 0.394914 | 60.508577 | yes |
| `ramps[min_length=8]` | Red | 62220 | 34565 | 0.555529 | 44.447123 | yes |
| `ramps[min_length=8]` | Warhawk | 97572 | 54916 | 0.562825 | 43.71746 | yes |

| configuration | mean ratio | median | min | max | mean saving % |
|---|---|---|---|---|---|
| ramps[min_length=2] | 0.536424 | 0.53887 | 0.384538 | 0.68342 | 46.357532 |
| ramps[min_length=3] | 0.536424 | 0.53887 | 0.384538 | 0.68342 | 46.357532 |
| ramps[min_length=4] | 0.536424 | 0.53887 | 0.384538 | 0.68342 | 46.357532 |
| ramps[min_length=5] | 0.536938 | 0.538506 | 0.383807 | 0.686932 | 46.306196 |
| ramps[min_length=6] | 0.54184 | 0.538237 | 0.394914 | 0.69597 | 45.816031 |
| ramps[min_length=8] | 0.559405 | 0.559177 | 0.394914 | 0.724354 | 44.059449 |

The ramps family is the best *simple* result: it needs no buffer, its decoder state is a handful of bytes, and it still removes roughly half the stream. That combination is what makes it the practical candidate in the verdict.

## 7. Motif results

Detection first, as the brief insists: how often do short frame sequences actually repeat? The frame counts below are **not** a compression result. The brief is explicit that the number of found repetitions is not the metric, and the cost is measured in section 8.

| song | motif length (frames) | distinct | repeated | repeated occurrences | frame coverage |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 2 | 4954 | 2561 | 6432 | 0.752436 |
| `Draconus_2024__sub0` | 3 | 5108 | 2507 | 6223 | 0.747904 |
| `Draconus_2024__sub0` | 4 | 5244 | 2454 | 6033 | 0.740426 |
| `Draconus_2024__sub0` | 5 | 5349 | 2392 | 5865 | 0.733175 |
| `Draconus_2024__sub0` | 8 | 5571 | 2239 | 5487 | 0.710514 |
| `Draconus_2024__sub0` | 16 | 5845 | 2070 | 5036 | 0.606843 |
| `Draconus_2024__sub0` | 32 | 6086 | 2002 | 4711 | 0.592341 |
| `Warhawk__sub0` | 2 | 3252 | 2746 | 10333 | 0.993542 |
| `Warhawk__sub0` | 3 | 4139 | 2864 | 9563 | 0.992435 |
| `Warhawk__sub0` | 4 | 4983 | 2928 | 8782 | 0.960424 |
| `Warhawk__sub0` | 5 | 5716 | 2894 | 8014 | 0.957472 |
| `Warhawk__sub0` | 8 | 7770 | 2423 | 5486 | 0.840775 |
| `Warhawk__sub0` | 16 | 8861 | 1935 | 3899 | 0.412085 |
| `Warhawk__sub0` | 32 | 8996 | 1813 | 3626 | 0.35738 |
| `Ninja_Commando__sub0` | 2 | 2147 | 1674 | 5607 | 0.927972 |
| `Ninja_Commando__sub0` | 3 | 2234 | 1726 | 5571 | 0.927972 |
| `Ninja_Commando__sub0` | 4 | 2313 | 1770 | 5535 | 0.927972 |
| `Ninja_Commando__sub0` | 5 | 2384 | 1806 | 5499 | 0.927315 |
| `Ninja_Commando__sub0` | 8 | 2534 | 1882 | 5422 | 0.915803 |
| `Ninja_Commando__sub0` | 16 | 2780 | 1970 | 5256 | 0.911199 |
| `Ninja_Commando__sub0` | 32 | 3089 | 2001 | 4962 | 0.907745 |
| `Red_Max__sub0` | 2 | 2049 | 1208 | 6070 | 0.885272 |
| `Red_Max__sub0` | 3 | 2095 | 1204 | 6019 | 0.88151 |
| `Red_Max__sub0` | 4 | 2129 | 1202 | 5982 | 0.88151 |
| `Red_Max__sub0` | 5 | 2163 | 1200 | 5945 | 0.88151 |
| `Red_Max__sub0` | 8 | 2264 | 1193 | 5834 | 0.88151 |
| `Red_Max__sub0` | 16 | 2475 | 1152 | 5574 | 0.834635 |
| `Red_Max__sub0` | 32 | 2662 | 1159 | 5378 | 0.822917 |

Coverage counts each covered frame once, so it is a real union and not a sum of overlapping occurrences. It is still an *upper bound* on what a motif table could reach, not a size. The next table makes that concrete by pricing the two sides of the trade, using a deliberately generous assumption that no real encoder can meet.

| song | length | repeated | occurrences | coverage | table cost (bytes) | optimistic saving (bytes) | net (bytes) |
|---|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 2 | 2561 | 6432 | 0.752436 | 48659 | 69678 | 21019 |
| `Draconus_2024__sub0` | 4 | 2454 | 6033 | 0.740426 | 90798 | 128844 | 38046 |
| `Draconus_2024__sub0` | 8 | 2239 | 5487 | 0.710514 | 163447 | 233856 | 70409 |
| `Draconus_2024__sub0` | 32 | 2002 | 4711 | 0.592341 | 578578 | 780192 | 201614 |
| `Warhawk__sub0` | 2 | 2746 | 10333 | 0.993542 | 52174 | 136566 | 84392 |
| `Warhawk__sub0` | 4 | 2928 | 8782 | 0.960424 | 108336 | 210744 | 102408 |
| `Warhawk__sub0` | 8 | 2423 | 5486 | 0.840775 | 176879 | 220536 | 43657 |
| `Warhawk__sub0` | 32 | 1813 | 3626 | 0.35738 | 523957 | 522144 | -1813 |
| `Ninja_Commando__sub0` | 2 | 1674 | 5607 | 0.927972 | 31806 | 70794 | 38988 |
| `Ninja_Commando__sub0` | 4 | 1770 | 5535 | 0.927972 | 65490 | 135540 | 70050 |
| `Ninja_Commando__sub0` | 8 | 1882 | 5422 | 0.915803 | 137386 | 254880 | 117494 |
| `Ninja_Commando__sub0` | 32 | 2001 | 4962 | 0.907745 | 578289 | 852768 | 274479 |
| `Red_Max__sub0` | 2 | 1208 | 6070 | 0.885272 | 22952 | 87516 | 64564 |
| `Red_Max__sub0` | 4 | 1202 | 5982 | 0.88151 | 44474 | 172080 | 127606 |
| `Red_Max__sub0` | 8 | 1193 | 5834 | 0.88151 | 87089 | 334152 | 247063 |
| `Red_Max__sub0` | 32 | 1159 | 5378 | 0.822917 | 334951 | 1215072 | 880121 |

*Optimistic saving* assumes every occurrence after the first becomes a free backreference: zero bits for the reference, and every repeated motif stored in full. Real references are not free, so the true saving is smaller than this and the bound is generous by construction.

The bound does **not** settle the question, and it would be dishonest to read it as if it did. What it does is narrow the window: the net is positive at the short lengths and collapses as the motifs grow, and on `Warhawk` at 32 frames it is already negative, where no honest encoder on this plan can win at all. So the only length still worth trying is a short one. Section 8 tries it for real and reports what a reference actually costs.

## 8. Dictionary / backreference results

Two different instruments for the same recurrence. The explicit dictionary builds a motif table and carries it inside the payload, paying for it in full. LZ backreferences point into the frames that have already been decoded, so the history is the dictionary and costs no table at all.

| configuration | mean ratio | median | min | max | mean saving % |
|---|---|---|---|---|---|
| lz[max_candidates=16,min_match_frames=2,window_frames=1024] | 0.562051 | 0.550432 | 0.473927 | 0.673413 | 43.794859 |
| lz[max_candidates=16,min_match_frames=2,window_frames=256] | 0.773043 | 0.74859 | 0.716611 | 0.878383 | 22.695665 |
| lz[max_candidates=16,min_match_frames=2,window_frames=64] | 0.866649 | 0.878456 | 0.809247 | 0.900436 | 13.335145 |
| lz[max_candidates=16,min_match_frames=4,window_frames=1024] | 0.585669 | 0.584597 | 0.48777 | 0.685711 | 41.433142 |
| lz[max_candidates=16,min_match_frames=4,window_frames=256] | 0.792214 | 0.77591 | 0.72653 | 0.890504 | 20.778624 |
| lz[max_candidates=16,min_match_frames=4,window_frames=64] | 0.883998 | 0.900106 | 0.823715 | 0.912066 | 11.600204 |
| lz[max_candidates=16,min_match_frames=8,window_frames=1024] | 0.631934 | 0.657679 | 0.508467 | 0.703912 | 36.806589 |
| lz[max_candidates=16,min_match_frames=8,window_frames=256] | 0.838197 | 0.847494 | 0.747959 | 0.909841 | 16.180329 |
| lz[max_candidates=16,min_match_frames=8,window_frames=64] | 0.913025 | 0.924187 | 0.844669 | 0.959056 | 8.697516 |

| dictionary scope | mean ratio | reading |
|---|---|---|
| per song (model has seen the song) | 1.045782 | the optimistic arm |
| shared (one table for all four) | 1.31863 | pays the table cost once per song |
| leave one out (never trained on the song) | 1.102229 | the honest arm |

**The explicit motif dictionary fails.** All three scopes are above 1.0, meaning the table costs more than the references save. The redundancy between distant frames is real, but naming it is not free, and the name is expensive. LZ captures the same recurrence for nothing, which is the clearest single result in this stage.

| held-out song | trained on | entries | table bytes |
|---|---|---|---|
| `Draconus_2024__sub0` | Warhawk__sub0, Ninja_Commando__sub0, Red_Max__sub0 | 64 | 7192 |
| `Warhawk__sub0` | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0 | 64 | 7192 |
| `Ninja_Commando__sub0` | Draconus_2024__sub0, Warhawk__sub0, Red_Max__sub0 | 64 | 8416 |
| `Red_Max__sub0` | Draconus_2024__sub0, Warhawk__sub0, Ninja_Commando__sub0 | 64 | 5644 |

## 9. Hybrid results

Per block, the cheapest of raw / per-register RLE / delta-gap / ramps / LZ, with the chosen codec id and payload length recorded per block. Cross-block references are not available to the LZ member, which is a real cost of blocking and is visible below.

| configuration | mean ratio | median | min | max | mean saving % |
|---|---|---|---|---|---|
| hybrid[block_frames=1024] | 0.510797 | 0.507282 | 0.3881 | 0.640523 | 48.920305 |
| hybrid[block_frames=2048] | 0.518019 | 0.524604 | 0.386018 | 0.636848 | 48.198126 |
| hybrid[block_frames=256] | 0.530053 | 0.540274 | 0.400449 | 0.639214 | 46.994717 |
| hybrid[block_frames=512] | 0.508255 | 0.507071 | 0.389434 | 0.629446 | 49.174447 |

The hybrid at 512 frames is the best configuration overall (`hybrid[block_frames=512]`, mean ratio 0.508255). It wins by letting each block use whichever representation suits it, and its cost is a decoder that must implement every member.

## 10. Cross-song generalization

Every configuration is reported per song and with mean, median, min and max. The brief forbids reporting an average alone. A configuration is only a candidate if it reconstructs *every* song exactly.

| configuration | worst-song ratio | mean | median | best-song ratio | lossless all |
|---|---|---|---|---|---|
| hybrid[block_frames=512] | 0.629446 | 0.508255 | 0.507071 | 0.389434 | yes |
| hybrid[block_frames=1024] | 0.640523 | 0.510797 | 0.507282 | 0.3881 | yes |
| hybrid[block_frames=2048] | 0.636848 | 0.518019 | 0.524604 | 0.386018 | yes |
| hybrid[block_frames=256] | 0.639214 | 0.530053 | 0.540274 | 0.400449 | yes |
| ramps[min_length=2] | 0.68342 | 0.536424 | 0.53887 | 0.384538 | yes |
| ramps[min_length=3] | 0.68342 | 0.536424 | 0.53887 | 0.384538 | yes |
| ramps[min_length=4] | 0.68342 | 0.536424 | 0.53887 | 0.384538 | yes |
| ramps[min_length=5] | 0.686932 | 0.536938 | 0.538506 | 0.383807 | yes |
| ramps[min_length=6] | 0.69597 | 0.54184 | 0.538237 | 0.394914 | yes |
| ramps[min_length=8] | 0.724354 | 0.559405 | 0.559177 | 0.394914 | yes |
| lz[max_candidates=16,min_match_frames=2,window_frames=1024] | 0.673413 | 0.562051 | 0.550432 | 0.473927 | yes |
| lz[max_candidates=16,min_match_frames=4,window_frames=1024] | 0.685711 | 0.585669 | 0.584597 | 0.48777 | yes |

**Per-song optima are not one method.** The smallest encoding differs by song, which is exactly why a single shared rule has to be measured rather than assumed:

| song | best configuration | ratio |
|---|---|---|
| `Draconus_2024__sub0` | `hybrid[block_frames=512]` | 0.629446 |
| `Ninja_Commando__sub0` | `ramps[min_length=5]` | 0.383807 |
| `Red_Max__sub0` | `hybrid[block_frames=512]` | 0.48028 |
| `Warhawk__sub0` | `lz[max_candidates=16,min_match_frames=2,window_frames=1024]` | 0.473927 |

One configuration is nevertheless lossless *and* compressing on all four songs: `hybrid[block_frames=512]`, mean ratio 0.508255, worst song 0.629446. That is the generalisation claim this stage is prepared to make.

Leave-one-song-out for the dictionary model:

| scope | mean ratio |
|---|---|
| leave_one_out | 1.102229 |
| per_song | 1.045782 |
| shared | 1.31863 |

The fold arm is the honest test and it is the worst of the three: a dictionary trained on three songs does not help the fourth. That is the memorisation test, and the dictionary idea fails it.

## 11. Exact reconstruction

Every method was encoded, wrapped in its container, re-parsed, decoded and compared with the canonical raw payload **byte for byte**. A method that is not exactly reversible is reported as `LOSSLESS = FALSE` and cannot be presented as a solution, whatever its size.

| metric | value |
|---|---|
| measurements taken | 120 |
| every measurement lossless | True |
| methods that failed | 0 |
| requirement | decoded == original, byte for byte, against the canonical payload of all nine registers in every frame |

The per-codec table in `reports/stage18/reconstruction.json` carries, for each measurement: whether reconstruction was exact, the first frame that diverged, how many values differed, the largest error, and the share of frames that came back completely correct. Because every measurement is exact, those columns are `None`, `0`, `0` and `100.0` respectively - which is the point, and the tests assert it.

## 12. Decoder complexity

ESTIMATE. Code sizes are charged at the current player's own density, 1.826 bytes per code line, from the estimates in DECODER_ESTIMATES. state_bytes and temporary_bytes are structural: they count the registers a decoder must hold. dictionary_or_buffer_bytes is computed from the chosen parameters, not assumed: an LZ window of N frames costs N*9 bytes of RAM, and a dictionary costs exactly the table it carries. operations_per_frame_proxy is a PROXY for work per decoded frame and is deliberately not presented as a cycle count.

an Atari with 16 KB has about 16,384 bytes of RAM in total and far less free once the OS, the screen and the program are loaded; the buffer column decides whether a format is usable at all

| configuration | code bytes (EST) | state | temp | buffer/dictionary | worst-case RAM | ops/frame (proxy) | branching |
|---|---|---|---|---|---|---|---|
| `delta_fixed` | 47 | 12 | 0 | 0 | 12 | 10 | NONE |
| `delta_gap` | 84 | 14 | 2 | 0 | 16 | 5 | MEDIUM |
| `dictionary[entries=256,lengths=2|4|8|16,table_bytes=32764,trained_on=Ninja_Commando__sub0]` | 131 | 22 | 2 | 32764 | 32788 | 6 | MEDIUM |
| `hybrid[block_frames=1024]` | 168 | 24 | 3 | 4608 | 4635 | 8 | VERY_HIGH |
| `lz[max_candidates=16,min_match_frames=2,window_frames=1024]` | 117 | 26 | 0 | 9216 | 9242 | 6 | MEDIUM |
| `ramps[min_length=2]` | 142 | 20 | 3 | 0 | 23 | 8 | HIGH |
| `raw` | 22 | 6 | 0 | 0 | 6 | 6 | NONE |
| `rle_frame` | 62 | 8 | 0 | 0 | 8 | 4 | LOW |
| `rle_register` | 73 | 14 | 0 | 0 | 14 | 12 | LOW |

The cheapest decoder is `raw` and the most expensive is `dictionary[entries=256,lengths=2|4|8|16,table_bytes=37120,trained_on=Draconus_2024__sub0]`. The buffer column is the one that decides deployment: a 1024-frame LZ window needs 9,216 bytes of decoded history, which is more than half of a 16 KB machine.

## 13. Comparison with Stage 17

Stage 17's own measured sizes are read from its artefacts rather than recomputed:

| song | raw | best temporal | Stage 17 exact event IR | Stage 17 exact / temporal |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 50007 | 155318 | 3.105925 |
| `Warhawk__sub0` | 97560 | 46242 | 201386 | 4.355045 |
| `Ninja_Commando__sub0` | 54729 | 21010 | 60982 | 2.902523 |
| `Red_Max__sub0` | 62208 | 29883 | 143239 | 4.793327 |

**Temporal compression beats Stage 17 clearly.** Stage 17's exact encoding is generally *larger* than the raw stream it encodes (mean ratio 1.859093), while the best temporal encoding is well below it. At equal exactness, temporal compression is about 3.789205x smaller.

## 14. Comparison with the current note format

This is the comparison that decides whether anything should change, and it goes the other way.

| song | raw | best temporal | current note format | note format / temporal |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 50007 | 8436 | 0.168696 |
| `Warhawk__sub0` | 97560 | 46242 | 10836 | 0.234332 |
| `Ninja_Commando__sub0` | 54729 | 21010 | 2760 | 0.131366 |
| `Red_Max__sub0` | 62208 | 29883 | 8676 | 0.290332 |

the decisive column is current_note_format_vs_temporal: it is far below 1, which means the existing format is still many times smaller than any exact encoding this stage found - because it is not trying to be exact

| representation | exact? | mean ratio to raw |
|---|---|---|
| canonical raw frame state | yes (it *is* the baseline) | 1.0 |
| best temporal (hybrid[block_frames=512]) | yes | 0.491865 |
| Stage 17 exact event encoding | yes | 1.859093 |
| current note format | **no** | 0.101792 |

The caveat is honest and it matters: the current note format is not an exact representation of the reference registers, so the comparison is between an exact format and an approximate one. That is precisely why it wins, and it is why the verdict is about integration rather than about the existence of the compression.

### What Stage 17 handed to this stage, and what was done with it

Stage 17 named questions for a later stage and did not answer them. Reporting which of them this stage closes - and which it does not - is the honest way to place these results. 2 of 5 are answered here.

| status | Stage 17 question | what this stage did |
|---|---|---|
| not addressed | Is the abstraction's failure a limit of the vocabulary or of the detector? | this is about the event vocabulary, not about the byte stream |
| not addressed | When the events come from a composer rather than from a recorded performance, is the encoding smaller? Note-granularity input is the only route the compression finding leaves open. | this stage compresses the historical register stream only; it generates no music and never reads a composer-generated trace |
| answered | How far is the current 3-byte note format from the raw dump it replaces? That comparison was never made and it is the one the event language has to win. | section 14 prices both representations on the same four songs, so the gap between the current note format and the raw dump is now measured rather than assumed |
| answered | Is there any representation of this behaviour that beats the raw dump? If not, the register dump is the right format and the middle layer is unnecessary. | yes for an exact encoding - the best temporal codec is a little under half the raw dump and is exact - but no exact encoding found here beats the current note format, which is far smaller precisely because it is not exact |
| not addressed | Is a technique heard as the same thing when its context changes? Part R says the language does not care; nobody has checked whether a listener does. | no listening test was run and none is proposed here |

The two that are answered are answered *from the same four songs* as Stage 17 used, so the comparison is like for like. The rest are deliberately left open; none of them can be settled by compressing bytes, and pretending otherwise would be exactly the kind of overreach this experiment exists to avoid.

## 15. Failure analysis

a negative result is a full result. Each entry records what was measured and why it happened, so a later stage does not have to rediscover it.

| method | measured | cause | verdict |
|---|---|---|---|
| whole-frame RLE | ratio 1.088337 on Draconus_2024__sub0: larger than the uncompressed stream | there is no consecutive redundancy to remove. The mean run of identical frames is about one frame, so the run-length header is paid once per frame for nothing | `FAILS` |
| fixed-width delta without a zero-run | ratio 1.0, exactly 1.0 by construction | delta changes the values but not the width: nine bytes per frame either way. Compression comes from *not storing* the fields that did not change, which is what the zero-run variant does | `NO_GAIN_BY_DESIGN` |
| explicit motif dictionary | worst per-song ratio 1.376218; per-song mean 1.045782, shared mean 1.31863, leave-one-out mean 1.102229 | the redundancy is real but the dictionary is the wrong instrument for it. A motif long enough to be worth a reference is also long enough that storing it costs most of what the references save, and a shared dictionary pays that cost once per song. LZ captures the same repeats as references into the already-decoded stream, which costs no table at all - and it reaches 0.703912 | `FAILS` |
| dictionary and large-window decoders, as a practical format | buffer/dictionary RAM up to 37120 bytes | an LZ window of 1024 frames needs 9,216 bytes of decoded history and a 256-entry motif table needs up to 37,120 bytes; on a 16 KB machine that is not a compression trade, it is an impossibility | `IMPRACTICAL_ON_TARGET_HARDWARE` |
| temporal compression as a *replacement* for the current note format | the current note format is 0.206182 of the best exact temporal encoding, about 4.9x smaller | the current format is not an exact representation of the reference registers at all: it stores notes and lets the player's own envelope generator fill the frames in between. An exact format answers a different and far more expensive question | `NOT_A_REPLACEMENT` |

ramps, LZ and the hybrid all reconstruct every song exactly and compress it; the failures above are about specific instruments and specific deployment questions

## 16. Falsification

**Hypothesis under test:** the historical POKEY stream at 50 Hz contains real temporal redundancy that a neutral, lossless, practically decodable format can exploit

| refuting result | detail |
|---|---|
| the simplest temporal redundancy does not exist | whole-frame RLE expands the stream (ratio 1.111122). Nothing holds still frame to frame, so 'the stream repeats itself' is false at the level a run-length coder can see |
| recurrent structure exists but is not cheap to name | an explicit motif dictionary is *larger* than raw (ratio 1.346537). The repetition between distant frames is real, but a table of motifs costs more than the references save |
| the dictionary idea does not generalise either | a dictionary trained on three songs and applied to the fourth has mean ratio 1.102229, worse than storing the stream uncompressed |
| the best compression needs RAM the machine does not have | the largest decoder buffer is 37120 bytes against a 16 KB machine |
| even a two-fold win would not make this the better basis for a player | the current note format is 0.206182 of the best exact temporal encoding. Temporal compression beats Stage 17's event IR, but it loses badly to the representation already in production, and that is the comparison that decides integration |

none of these refute the *existence* of temporal redundancy; they bound where it lives and what it is worth. The refutations are about instruments (RLE, motif tables), deployment (RAM) and the comparison that actually matters (the production format).

## 17. Verdict

| verdict | result | rule |
|---|---|---|
| temporal compression | `TEMPORAL_COMPRESSION_SUPPORTED` | SUPPORTED requires a mean saving of at least 25.0 percent with every measurement lossless; PARTIALLY_SUPPORTED requires at least 10.0 percent and losslessness; otherwise NOT_SUPPORTED |
| player integration | `PLAYER_INTEGRATION_NOT_JUSTIFIED` | Part 21: all seven conditions must hold simultaneously. They are listed with their measurements, and the first one that fails carries the decision. |

Part 21's seven conditions, evaluated one by one:

| condition | met | measured |
|---|---|---|
| 1. significant compression | yes | mean saving 49.174447 percent (threshold 25.0) |
| 2. exact reconstruction | yes | every measurement lossless: True |
| 3. generalisation | yes | the single configuration 'hybrid[block_frames=512]' reconstructs all four songs exactly and compresses each of them |
| 4. acceptable decoder complexity | **NO** | branching VERY_HIGH, operations proxy 8 per frame |
| 5. sensible RAM cost | **NO** | best configuration needs 4608 bytes of buffer against a concern threshold of 4096 |
| 6. advantage over the Stage 17 event IR | yes | Stage 17's exact encoding is 3.789205x the size of the best temporal encoding |
| 7. advantage over the current note format | **NO** | the current note format is 0.206182 of the best temporal encoding, i.e. already several times smaller |

The deciding condition is **4. acceptable decoder complexity**.

the two verdicts come from different tests and are deliberately independent: the redundancy can be real and useful in principle while integration is still not justified, and that is exactly what the measurements show.

The practical candidate the verdict records is `raw`: it compresses well and needs no large buffer.

## Final question

**is the historical POKEY performance stream temporally redundant enough that a neutral, lossless, practically decodable temporal-compression format is a better basis for a future player than the current note format or the Stage 17 event IR?**

Yes against the Stage 17 event IR, and no against the current note format. The stream does contain real temporal redundancy - about 49.174447 percent of it is removable with an exact, neutral codec - and that makes temporal compression roughly 3.789205x smaller than Stage 17's exact encoding at the same exactness. But the format already in production is about 4.9x smaller than any exact encoding this stage found, because it is not trying to be exact: it stores notes and lets the player's own envelope fill the frames. On the comparison that decides whether anything should change, temporal compression loses, and it also needs RAM the target machine does not have.

| comparison | result |
|---|---|
| versus current note format | WORSE: the note format is 4.9x smaller, though it is not an exact representation of the registers |
| versus stage 17 event ir | BETTER: 3.789205x smaller, equally exact |

What would change the answer:

- a requirement for exact register reconstruction, which the note format cannot meet and temporal compression can - that is the one scenario where this work becomes the right basis
- a decoder whose buffer fits in a few hundred bytes, which neither LZ nor a motif dictionary provides
- a target machine with far more RAM, which removes the deployment objection but not the 'the production format is already smaller' objection

5 methods failed and are reported with their causes. A stage that only reported the winner would have thrown away the most useful part of this measurement.

---

Stage 18 read four corpus songs and the Stage 16 and Stage 17 records through their hashes, defined one canonical raw representation, implemented eight real byte formats, and decoded every one of them back for a byte-for-byte comparison. No Composer, DSL, Music IR, POKEY IR, player, schema or SoundProfile was modified; the player source is hashed as an input and never written. No audio was rendered, no music was generated, no listening test was run, and nothing was implemented in production. Any implementation would be a separate stage, and only after these results are accepted.
