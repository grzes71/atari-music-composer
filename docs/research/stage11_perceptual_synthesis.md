# Stage 11A — perceptual synthesis

Where does the perceptual character of an archaeology POKEY sound go missing in the current composer pipeline? This document answers that from the published evidence only. Nothing is rendered, no renderer is changed, no profile is selected and no listening is done here.

* experiment: `stage11a` (`stage11a/1`)
* hypothesis under test: *the remaining perceptual gap may be primarily spectral/timbral rather than temporal*
* input artefacts hashed: 13
* go / no-go for Stage 11B: **PROCEED (scoped to the existing renderer)**

Three kinds of statement are kept apart: **Observed** (a value read from a named published artefact), **Inference** (what follows) and **Experimental choice** (what this stage decided, which no measurement forces).

## A1. Evidence matrix

One row per profile feature. *reaches IR* is computed from Stage 9E's field census; everything else is quoted from the artefact named in *provenance*.

| feature | in SoundProfile | in Playable | used by binding | reaches IR | changes WAV | perceptual experiment |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| generator / distortion | yes (synthesis.hardware.distortion) | yes (pokey.hardware.distortion, .waveform) | yes (IRInstrument.distortion) | yes (pokey.hardware.distortion, pokey.hardware.distortion_name) | yes (AUDC high nibble -> one of six waveforms) | 7B character vocabulary; 9D same_generator |
| static envelope (ADSR) | yes (synthesis.envelope) | yes (envelope.*) | yes (four numbers -> IRInstrument.envelope) | yes (envelope.attack_ms, envelope.confidence, envelope.decay_ms) | yes, but envelope.decay_frames alters no frame (9E L2) | not tested in isolation |
| AUDCTL (clock / coupling byte) | yes (synthesis.hardware.audctl_mode) | yes (pokey.hardware.audctl_mode) | yes (IRInstrument.audctl) | yes (pokey.hardware.audctl_mode) | yes for PAIR (AUDCTL column); no effect for VOICE (9E L3) | not tested in isolation |
| 16-bit coupling | yes (scope PAIR; observed.combined_divider) | yes (pairing.*, pokey.channels.*) | yes (is_16bit, pair flag) | yes (pokey.channels.pair) | yes (PAIR audio is built from AUDF1 + AUDF2) | 9D same_scope; 10B carried one PAIR profile |
| pitch trajectory | yes (gesture.pitch.runs; pitch.*) | yes (gesture.pitch, pitch.*) | no | no (IRInstrument has no per-frame divider) | no (never rendered) | not tested (never heard by a listener) |
| volume contour | yes (gesture.volume.runs) | yes (gesture.volume, volume.*) | only when asked (Stage 10B switch; default off) | yes (IRInstrument.volume_contour) | yes (proved frame-for-frame in Stage 10B) | Stage 10B, profile-level and whole-song |
| noise character | yes (hardware.waveform / distortion family) | yes (pokey.hardware.waveform) | yes (via the distortion nibble) | yes (the synth decodes the waveform) | yes (pure / poly4 / poly5 / poly9 / poly17) | 7B ('noise'); 9D clean vs noisy |
| spectral structure (centroid / flatness / bandwidth) | yes in the research record (observed, measured) | no (not a field of PlayableSoundProfile 1.0) | no | no (never a register value) | indirectly: an emergent consequence of generator + frequency + level | descriptor correlations only (never a rendered, toggled feature) |
| timing / repetition | yes (gesture.resolution, timing) | yes (timing.*) | no (the composition's tempo sets frames_per_tick) | no (profile timing is never read) | no (never rendered) | 7B ('repetition' 11 comments; 'faster') |

## A2. Changing the waveform is not the same as being preferred

A feature that changes the waveform has not thereby been shown useful: the listener must prefer it. Stage 10B is the worked example — the volume contour changes the waveform frame-for-frame and was *rejected*.

| feature | class | why |
| :--- | :--- | :--- |
| generator / distortion | positive evidence | 9D: same_generator vs perceived similarity rho -0.5993 (a generator change predicts a heard difference); the clean and noisy families are disjoint; 7B's character vocabulary follows the family. It changes the waveform and the listener keys on it. |
| noise character | positive evidence | The same axis as the generator seen from the listener's side: 'clean' (centroid median 6018 Hz) vs 'noisy' (4135 Hz), Cliff's delta 0.5619, disjoint families (9D correlations.json). Already expressible by the distortion nibble. |
| static envelope (ADSR) | technically relevant but perceptually unvalidated | It changes the WAV (per-frame volume) but has never been toggled in isolation; and 9E measured that envelope.decay_frames alters no frame at all, so part of it may be inert. |
| AUDCTL | technically relevant but perceptually unvalidated | Audible only through 16-bit coupling and the 9/17-bit noise selection; never heard in isolation. |
| 16-bit coupling | technically relevant but perceptually unvalidated | Expressed and audible, but the only perceptual handle is 9D same_scope vs similarity -0.308, the weakest of the six cues there. |
| pitch trajectory | not tested | Never rendered, therefore never heard. The largest *untested* representable gap (30 profiles, 6 duplicate groups); the listener has a word for it ('rising') but no preference data exists. |
| volume contour | negative evidence | Rendered and heard in Stage 10B: 8/8 profile B-vs-C pairs were 'no clear difference', the whole-song pairs preferred the no-contour side, verdict NEGATIVE. It changes the waveform; it was not preferred. |
| spectral structure (centroid / flatness / bandwidth) | inconclusive | The named descriptor's correlation with usefulness flips sign between the two listening datasets (7B -0.4401, 9D +0.6338), and the strongest 9D cue may reflect correlation between the descriptor and the generator family rather than an independent perceptual dimension. |
| timing / repetition | inconclusive | The listener hears repetition and 'faster', but those are produced by the arrangement and the player's row timing, not by any profile field the renderer reads. |

## A3. The renderer / representation gap

**Observed.** The binding reads **13 of 232** documented leaf paths. The census: 74 IGNORED, 21 PLAYER_ONLY, 109 UNREPRESENTABLE, 28 USED.

* the first information loss is at **PlayableSoundProfile -> bound POKEY IR (sound_profiles/binding.py:_rebuild_song)** — the binding reads 13 of 232 documented leaf paths; _rebuild_song writes exactly distortion, envelope, audctl, is_16bit, profile_id and profile_fingerprint
* the renderer does not lose anything the binding writes: per stimulus variant, the columns whose alteration changes the audio: VOICE: AUDF1, AUDC1 (no effect: AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4, AUDCTL); PAIR: AUDF1, AUDF2, AUDC2, AUDCTL (no effect: AUDC1, AUDF3, AUDC3, AUDF4, AUDC4)
* whole sections the binding ignores: `gesture` (135 paths), `metadata` (5 paths), `pairing` (7 paths), `pitch` (18 paths), `playability` (9 paths), `playable_fingerprint` (1 paths), `profile_id` (1 paths), `schema` (1 paths), `scope` (1 paths), `source_profile` (4 paths), `timing` (2 paths), `volume` (20 paths); the measured gesture loss is **control_state**, **modulation**, **pitch**, **timing**, **volume**.

## A4. Why 61 renderable profiles collapse to 37 audio signals

**Observed.** 61 renderable profiles produce 37 distinct audio signals; 24 profiles are redundant across 6 groups (sizes 10, 6, 4, 4, 3, 3). Every group is a `representation_duplicate`, first diverging at `bound_ir`; the audio-only measurement agrees: True.

**Inference.** primarily representation: the groups' documents differ but their bound IR is identical, because the binding carries only distortion, four envelope numbers, AUDCTL and the pair flag. It is not a renderer limit (the audio is a pure function of the nine register bytes the binding does write) and not an archaeology limit (the documents do differ).

## A5. Stage 10A, re-evaluated from the actual answers

**Observed.** 18 of 18 pairs answered. Primary (`default_vs_new` + `old_vs_new`, 12 pairs): NEW won **2**, the other side **6**, ties **4**. Control (`default_vs_old`, 6 pairs): DEFAULT **4**, OLD **1**, ties **1**.

**Inference.** the evidence-based re-binding (NEW) won 2 of the 12 primary pairs; the other side won 6 and 4 were ties. On the 6 control pairs the composer's DEFAULT beat the Stage 9C OLD binding 4-1 (1 tie), reproducing the Stage 9C result with audio that is byte-identical to it — so a one- or two-pair difference here is inside the listener's own instability and is not evidence that re-binding helps.

## A6. Stage 10B, re-evaluated from the actual answers

**Observed.** Profile-level B-vs-C (8 pairs): C **0**, other **0**, no difference **8**. Song-level B-vs-C (6 pairs): C **1**, other **2**, no difference **3**. Contour heard in 7 of 18 pairs.

**Inference.** the volume contour is technically expressible and changes the waveform (proved in the Stage 10B preparation), but at the profile level all 8 B-vs-C pairs were 'no clear difference' (only 2 were even heard), and at the song level C won 1 of 6 against 2 losses and 3 ties. The resolved verdict of Stage 10B is NEGATIVE.

## A7. The strongest remaining hypothesis

| rank | dimension | kind | evidence | confidence | why |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | pitch trajectory (temporal) | representation gap | strong as a representation gap, unknown perceptually | medium | the largest representable gap that has never been heard: 30 profiles / 525 leaf paths / 6 duplicate groups collapse partly because the measured pitch series is discarded; the listener has the word 'rising' for it |
| 2 | spectral / timbral structure | partly already expressible | positive for the generator axis; inconclusive for the descriptor axis | medium | the renderer already reproduces the dominant audible spectral axis, the generator family (six waveforms); the finer spectral descriptors are emergent and their correlation with usefulness is unstable across the two listening datasets |
| 3 | volume contour (temporal) | representation gap, closed | negative | high | tested and rejected: technically expressible and waveform-changing, but the listener showed no advantage at the profile level and a loss at the song level |
| 4 | noise character | already expressible | positive (already present) | high | already expressed: it is the same axis as the generator, which the renderer reproduces and the listener responds to |
| 5 | 16-bit coupling / AUDCTL | already expressible | weak | medium | expressed and audible; no independent perceptual weight measured |
| 6 | timing / gesture gating | representation gap with no policy | inconclusive | low | heard as repetition, but arrangement-driven; Stage 10B found the gating (level-0) contours the most audible potential class and refused them |

## A8. The listener's vocabulary against measurable structure

**Observed.** Stage 7B's own comment groups (counts from its summary): percussion-like (12), repetition (11), high frequency (10), question (10), noise (9), pleasant (7), rising (6), short (6), bass-like (4), clean (3), theme (3), already heard (2), different ending (2), faster (2).

**Observed.** Selected rows of the Stage 9D human-vs-machine table (Spearman, n=60): bandwidth_hz vs usefulness = 0.6596; flatness vs distinctiveness = 0.5002; rolloff_hz vs usefulness = 0.4145; bandwidth_hz vs distinctiveness = -0.3755; centroid_hz vs usefulness = 0.3133; centroid_hz vs distinctiveness = 0.2723; flatness vs usefulness = 0.2302; rolloff_hz vs distinctiveness = 0.212.

**Inference.** The listener's *noise / high frequency / clean* vocabulary maps onto the generator family and the spectral centroid — already expressible. The *rising* vocabulary maps onto pitch trajectory — measured, carried by 30 profiles, and never rendered. The *repetition* vocabulary maps onto the arrangement, not onto any profile field the renderer reads.

**Observed — the one instability that matters.** The descriptor named *spectral bandwidth (Hz)* correlates with usefulness at **-0.4401** in Stage 7B (20 candidates) and at **+0.6338** in Stage 9D (61 profiles): opposite signs under the same name. Any claim that a spectral descriptor predicts usefulness must survive that.

## A9. Go / no-go for Stage 11B

**Experimental choice.** **PROCEED (scoped to the existing renderer).** the spectral hypothesis is not the strongest one the evidence supports, but a controlled spectral experiment is cheap, uses the existing renderer unchanged, and answers the one question the brief asks: can the current POKEY model reproduce the measured spectral character? It is run nonetheless, and its result is recorded against the ranked candidates rather than assumed.

* no renderer, IR, player or DSL change (Stage 11B is ablation with existing code)
* no profile/schema field added; experimental data lives in reports/stage11/
* a variant the renderer cannot express is marked NOT EXPRESSIBLE, never approximated

The hypothesis the brief asked to test — that the gap is principally spectral — is **not the strongest one the evidence supports**: the renderer already reproduces the dominant audible spectral axis (the generator family), and the temporal gesture is the larger representation gap. Stage 11B is run anyway, precisely because the brief asks to *test* the hypothesis rather than assume it, and its result is recorded against the ranked candidates above.

## A10. Reproducibility

This document and every `reports/stage11/*.json` are a pure function of the artefacts below (SHA-256), with no timestamp in any of them, so two runs are byte-identical:

```json
{
  "archaeology/reports/stage7b/human_evaluation_summary.json": "4f655a0add8eaca0f7e15b1900e59efd300372c61416b7cdb3c6616ed38b5a01",
  "archaeology/reports/stage8c/playability_audit.json": "0169755549e69252c6524e3093d0e447409b4f6fb18f076312eacf978c9d1b44",
  "examples/sound_profile_rebinding_10a/evaluation_rebinding_10a.csv": "8b8d5bfdc49f5cbc59f794731d15de3fdfa2b7e5e1ccafb0640b4c34ca31727b",
  "examples/sound_profile_rebinding_10a/manifest.json": "e187ff30de7f73cf6209dcc4c9dfe2ae2ad37b7383c32fc1327afe11ca223f83",
  "examples/sound_profile_volume_contour_10b/evaluation_volume_contour_10b.csv": "638dc932ca50884eb845b747486dbdd0e94f35796dd5015bd3ccca3bd6b080c7",
  "examples/sound_profile_volume_contour_10b/manifest.json": "9359909703a298444bc3f396afea4b89f9d69adfb0e7fed1e4d1851ece1fb996",
  "reports/stage9d/correlations.json": "cfe5e2fc480d5378e3d1c18e603edd3d3ec2318c4d4e77b13df606cfdc313165",
  "reports/stage9d/coverage.json": "4f8848dfe285b572df3fc14532403731cd4d5352effb8b2228d37435c7e5e2ce",
  "reports/stage9e/duplicate_groups.json": "65742bff0633cd62e42f8c3b1c69438fe1f6538f064d00f48a0925e8ae422a46",
  "reports/stage9e/information_loss.json": "c7fd034f9748e4fe8cc63bd459aba675d847fb669994c0e84844739ee349fef0",
  "reports/stage9e/missing_capabilities.json": "ce9a13868e3ac98b2956f54f13726757c96802ec38214e025559113e318a5e07",
  "reports/stage9e/pipeline_fields.json": "f556147e0d84a2f302ab821a89513bfa25d982ab6da2dd8070d71bc12b3ae5c1",
  "tests/data/sound_profiles/bank/registry.json": "b78faec3738cc127d21ae571f526f5761a4292f302eb07de7ba08794746a81fb"
}
```

