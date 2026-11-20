# Research Programme Overview

Before the production toolchain took its current shape, the project ran a long, staged research
programme investigating two hard questions: **what makes POKEY music perceptually convincing?** and
**how much "performance style" can be measured, learned, and reproduced from historical material?**
The documents in this section are the preserved research record. They are kept verbatim for
traceability: they motivated the production instrument catalog, the perceptual renderer targets, and
the Music/POKEY IR design, but they are *not* product documentation — commands, numbers, and
conclusions here reflect the time of writing, and several proposals were superseded (or implemented
differently) in later stages.

## Thread 1 — Perceptual synthesis & listening (Stages 9C–14, 10A/B)

Starting from an external "POKEY sound archaeology" profile bank (see
[Sound Profile Integration](../reference/profile-integration.md)), this thread rebuilt instruments from
perceived *identity* rather than raw register dumps: human listening panels (Stage 9C–9D), the gap
between reference hardware and the software renderer (Stage 9E), profile rebinding across generator
families (Stage 10A), perceptually re-weighted volume contours (Stage 10B), spectral evidence and
controlled ablations (Stage 11), decoration-vs-replacement decisions (Stage 12A), pitch trajectories
(Stage 13A), and the final synthesis (Stage 14) that motivated the curated catalog and the
transient-macro/pitch-envelope machinery now in Format v2.

## Thread 2 — Performance style & detector research (Stages 15–25)

A second thread asked whether historical POKEY songs encode a learnable "performance grammar":
defining a compact performance event language (Stage 15/17), testing cross-song generalization
(Stage 16), temporal compression and grammar induction (Stage 18/19), residual performance and
controlled validation (Stage 20/21), then a rigorous audit of the detector itself — error
decomposition (Stage 22), historical-residual controls (Stage 23), corpus overlap and confounding
(Stage 24), and matched control corpus design (Stage 25). These stages defined the project's standards
for evidence hygiene (blinded listening, matched controls, confound analysis) that later production
verification borrowed (e.g. the py65 parity methodology).

## Thread 3 — Timbre prototyping & the lead library (Experiments 26–30)

The final thread searched the raw space of POKEY timbres for *curated* candidates: a prototype of the
timbre search (E26), the octave-pulse characterisation that became `lead_c1_octave_pulse` (E27 — and
ultimately its 0.17.1 distortion fix), the C1 sound in musical context (E28), candidate curation
(E29), and blind A/B evaluation (E30). The outputs feed the
[catalog](../user-guide/instruments.md) and the Lead Library line.

## How to read these documents

* **Status labels.** Some documents carry explicit status banners ("design only", "[proposed]",
  "[verified]") — treat them as dated claims; check the product documentation
  ([User Guide](../user-guide/workflow.md), [Reference](../reference/song-format-v2.md), and
  [Architecture](../architecture/overview.md)) for what actually shipped.
* **Research-only data.** Referenced datasets (`dataset/`, `music/`, `experiments/`, `listening_test*/`,
  `reports/`) are local research artifacts excluded from the public repository; the corresponding CLI
  research commands (`analyze-stage15`…`analyze-stage25`, listening-test preparation, etc.) are
  experimental tooling outside the production pipeline.
* **Markers.** In the test suite, `experimental` covers these stages (see
  [Testing Strategy](../development/testing.md)); `legacy` covers the pre-Stage-9 generations.
