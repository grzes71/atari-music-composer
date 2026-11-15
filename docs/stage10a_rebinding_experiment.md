# Stage 10A — evidence-based profile rebinding experiment

Can better *profile assignment* improve whole-song output, with the renderer untouched?

| | |
| :--- | :--- |
| songs | **6** — exactly the Stage 9C Part C set |
| channels decided | **21** across the six songs |
| assignments changed | **10** channels (11 roles) |
| songs left unchanged | **1** |
| blinded comparisons | **18** (3 per song) |
| default and old sides byte-identical to Stage 9C | **yes** |
| Stage 9C package, compositions and old bindings untouched | **yes** |

No profile, fingerprint, schema, WAV of the library, composition, DSL rule, player, renderer or Composer source was modified. The only thing that changed is which profile is bound to which existing instrument — and only in the new package.

---

## 1. Objective

Stage 9C's Part C compared six songs and the profile-bound side lost **5–0** (one tie). Stage
9E then found that the bindings used there were drawn from **generator-family pools**, not from
anything the listener said, and that this is a *musical interpretation* gap rather than a
rendering defect. So the 5–0 result does not yet separate two very different readings:

* **Reading A** — the profile mechanism itself is worse for whole songs.
* **Reading B** — the mechanism is fine, but the wrong profile was put on each role.

This stage prepares the experiment that tells them apart. It changes nothing else:

```text
same composition   same profiles   same renderer   same gain   same duration
                              |
                              v
                   different profile ASSIGNMENT only
```

**What the outcome will mean** (stated before the listening, so it cannot be reinterpreted
afterwards):

| outcome | supports | does **not** mean |
| :--- | :--- | :--- |
| the new assignment wins | Reading B: the 5–0 was at least partly the assignment | that the current profile *representation* is sufficient (Stage 9E's representation gap stands) |
| the new assignment does not win | Reading A for this mechanism: assignment alone is not enough | that sound profiles are useless — only that selection is not the whole problem |
| mixed | nothing yet: some roles benefit and some do not, and §9 says which | — |

This stage does **not** test whether the Sound Profile concept is right, and it does not
attempt to improve the library, the gesture model or the player.

## 2. The six songs

**Observed.** Taken from `examples/sound_profile_listening/manifest.json` — the record of what
the listener actually heard — rather than from a filename convention. Each song's binding file
is re-read and must agree with that manifest profile-by-profile, or the stage refuses to run:
a binding edited since the experiment would silently change what *old* means.

| # | song | source | old binding | instruments (role → channel) |
| ---: | :--- | :--- | :--- | :--- |
| 1 | `Vaults-of-Nhyrmeth.dsl` | `examples/songs/Vaults-of-Nhyrmeth.dsl` | `Vaults-of-Nhyrmeth.dsl.binding.json` | `bass` → ch 1, `lead` → ch 3, `perc` → ch 4 |
| 2 | `as-1.dsl` | `examples/songs/as-1.dsl` | `as-1.dsl.binding.json` | `bass` → ch 1, `lead` → ch 3, `perc` → ch 4 |
| 3 | `dziki2.json` | `examples/songs/dziki2.json` | `dziki2.json.binding.json` | `bass` → ch 1, `bell` → ch 4, `counter` → ch 4, `drum` → ch 4, `lead` → ch 3 |
| 4 | `as-2.dsl` | `examples/songs/as-2.dsl` | `as-2.dsl.binding.json` | `bass` → ch 1, `chord` → ch 2, `lead` → ch 3, `perc` → ch 4 |
| 5 | `funky.json` | `examples/songs/funky.json` | `funky.json.binding.json` | `bass` → ch 3, `lead` → ch 1, `pad` → ch 2, `perc` → ch 4 |
| 6 | `koval.json` | `examples/songs/koval.json` | `koval.json.binding.json` | `arp` → ch 3, `bass` → ch 1, `lead` → ch 2, `pad` → ch 3, `perc` → ch 4 |

Every instrument sounds on exactly one channel, and no composition was touched. Their hashes
before and after the run are equal, and `reports/stage10a/verification.json` records them:

| song | composition sha256 (first 16) |
| :--- | :--- |
| `Vaults-of-Nhyrmeth.dsl` | `cb93bef054afbea9` |
| `as-1.dsl` | `9d57732ab1fc758d` |
| `dziki2.json` | `ec188f4ca1edf812` |
| `as-2.dsl` | `f056cecbc1f81052` |
| `funky.json` | `f46e793f36678d21` |
| `koval.json` | `5091e417d6a9e70d` |

**Inference.** The six songs are not a population and cannot support a general claim about
profile binding. They are the same six songs the 5–0 was measured on, which is exactly what
makes a re-run comparable — and nothing more.

## 3. The old binding

**Observed.** The strategy the old bindings followed is documented in
[profile_integration.md](profile_integration.md) §13.1: a pool per *generator family* — noise
for percussion, poly4 for bass, pure tone for melody — and within a pool, a stable rotation
over the song list. The table below reads each old assignment through that strategy. The rating
columns are the Stage 9C/9D listener's own words and numbers, not a re-rating.

| song | instrument / role | channel | old profile | pool | listener says (U / D / C) | comment |
| :--- | :--- | ---: | :--- | :--- | :--- | :--- |
| `Vaults-of-Nhyrmeth.dsl` | `bass` (bass) | 1 | `pokey_ref_3627798b` | 16-bit bass pool | 3 / 4 / 3 | 'short loud lead tone' |
| `Vaults-of-Nhyrmeth.dsl` | `lead` (lead) | 3 | `pokey_ref_c321892f` | melodic pool | 4 / 1 / 5 | 'clean atari-like lead tone' |
| `Vaults-of-Nhyrmeth.dsl` | `perc` (perc) | 4 | `pokey_ref_6db98eb5` | percussion pool | 3 / 3 / 3 | 'bass/perc?' |
| `as-1.dsl` | `bass` (bass) | 1 | `pokey_ref_331fbbd7` | 16-bit bass pool | 3 / 4 / 3 | 'short lead tone' |
| `as-1.dsl` | `lead` (lead) | 3 | `pokey_ref_1ef377fc` | melodic pool | 4 / 2 / 5 | 'typica clear atari-like nice lead sound' |
| `as-1.dsl` | `perc` (perc) | 4 | `pokey_ref_6db98eb5` | percussion pool | 3 / 3 / 3 | 'bass/perc?' |
| `dziki2.json` | `bass` (bass) | 1 | `pokey_ref_a09c0263` | 16-bit bass pool | 4 / 3 / 3 | 'lound lead sound' |
| `dziki2.json` | `bell` (bell) | 4 | `pokey_ref_80d1ce25` | melodic pool | 4 / 2 / 5 | 'typical atari lead tone' |
| `dziki2.json` | `counter` (counter) | 4 | `pokey_ref_80d1ce25` | melodic pool | 4 / 2 / 5 | 'typical atari lead tone' |
| `dziki2.json` | `drum` (drum) | 4 | `pokey_ref_80d1ce25` | melodic pool | 4 / 2 / 5 | 'typical atari lead tone' |
| `dziki2.json` | `lead` (lead) | 3 | `pokey_ref_7611576e` | melodic pool | 4 / 4 / 4 | 'nice short lead-like sound' |
| `as-2.dsl` | `bass` (bass) | 1 | `pokey_ref_3faf80b4` | 8-bit bass pool | 4 / 4 / 3 | 'louder lead nice tone' |
| `as-2.dsl` | `chord` (chord) | 2 | `pokey_ref_1ef377fc` | melodic pool | 4 / 2 / 5 | 'typica clear atari-like nice lead sound' |
| `as-2.dsl` | `lead` (lead) | 3 | `pokey_ref_25f94201` | melodic pool | 2 / 3 / 4 | 'clean lead atari-like but with some break in background' |
| `as-2.dsl` | `perc` (perc) | 4 | `pokey_ref_6db98eb5` | percussion pool | 3 / 3 / 3 | 'bass/perc?' |
| `funky.json` | `bass` (bass) | 3 | `pokey_ref_5ee9c1a8` | 8-bit bass pool | 4 / 4 / 4 | 'loud atari-like lead sound' |
| `funky.json` | `lead` (lead) | 1 | `pokey_ref_7611576e` | melodic pool | 4 / 4 / 4 | 'nice short lead-like sound' |
| `funky.json` | `pad` (pad) | 2 | `pokey_ref_80d1ce25` | melodic pool | 4 / 2 / 5 | 'typical atari lead tone' |
| `funky.json` | `perc` (perc) | 4 | `pokey_ref_1e9be30a` | percussion pool | 3 / 3 / 3 | 'noisy bass/perc?' |
| `koval.json` | `arp` (arp) | 3 | `pokey_ref_959628d6` | melodic pool | 3 / 3 / 3 | 'loud lead atari-like sound' |
| `koval.json` | `bass` (bass) | 1 | `pokey_ref_5ee9c1a8` | 8-bit bass pool | 4 / 4 / 4 | 'loud atari-like lead sound' |
| `koval.json` | `lead` (lead) | 2 | `pokey_ref_953311ef` | melodic pool | 4 / 3 / 5 | 'clean atari lead tone' |
| `koval.json` | `pad` (pad) | 3 | `pokey_ref_959628d6` | melodic pool | 3 / 3 / 3 | 'loud lead atari-like sound' |
| `koval.json` | `perc` (perc) | 4 | `pokey_ref_2de893a6` | percussion pool | 2 / 3 / 3 | 'noisy bass/perc?' |

U = usefulness, D = distinctiveness, C = Atari character, each 1–5 as the listener gave them.

**Inference.** Three things stand out, and all three are visible in the numbers above rather
than argued from theory:

1. **The strategy did assign the right *kind* of generator.** Every percussion role got a noise
   generator and every pitched role a pitched one, so nothing here is structurally absurd.
2. **Within the pools it was indifferent to the listener.** The six songs draw on only a handful
   of distinct sounds, and they share them across roles and across songs:

| sound (Stage 9D audio group) | bound to these roles |
| :--- | :--- |
| `group 0 ($A, VOICE)` | `Vaults-of-Nhyrmeth.dsl` `lead`, `as-1.dsl` `lead`, `dziki2.json` `bell`, `dziki2.json` `counter`, `dziki2.json` `drum`, `as-2.dsl` `chord`, `funky.json` `pad` |
| `group 1 ($C, PAIR)` | `dziki2.json` `bass` |
| `group 2 ($8, VOICE)` | `Vaults-of-Nhyrmeth.dsl` `perc`, `as-1.dsl` `perc`, `as-2.dsl` `perc`, `funky.json` `perc` |
| `group 3 ($C, VOICE)` | `as-2.dsl` `bass`, `funky.json` `bass`, `koval.json` `bass` |
| `pokey_ref_25f94201 — unlike anything else in the library` | `as-2.dsl` `lead` |
| `pokey_ref_2de893a6 — unlike anything else in the library` | `koval.json` `perc` |
| `pokey_ref_331fbbd7 — unlike anything else in the library` | `as-1.dsl` `bass` |
| `pokey_ref_3627798b — unlike anything else in the library` | `Vaults-of-Nhyrmeth.dsl` `bass` |
| `pokey_ref_7611576e — unlike anything else in the library` | `dziki2.json` `lead`, `funky.json` `lead` |
| `pokey_ref_953311ef — unlike anything else in the library` | `koval.json` `lead` |
| `pokey_ref_959628d6 — unlike anything else in the library` | `koval.json` `arp`, `koval.json` `pad` |

So **11 distinct sounds cover all 24 bound roles**, and the 5 shared ones cover 18 of them. The library is heard
through a much smaller set of sounds than it has profiles.

3. **The listener's ratings for the profiles actually used in songs are not the library's
   best.** The clearest cases are in §6.

## 4. Candidate selection

**Observed / method.** For every channel, the pool of plausible replacements is built by rule,
not by preference:

* the **same scope** as the old profile (a `VOICE` channel stays `VOICE`; swapping the scope
  would change AUDCTL and the hardware configuration, which is not this experiment);
* the listener must have **heard it the way the role needs**: a pitched role accepts only
  profiles tagged `lead_tonal` (the profile followed the melody in the audition), an unpitched
  role only profiles tagged `percussive_noisy` — the listener's own vocabulary, not a
  generator table;
* it must be **rated** (an unrated profile has no evidence and is never chosen), **renderable**
  with no blocking limitation, and **audibly distinct** from the old profile — two profiles
  whose Stage 9C audio is byte-identical write the same six IR values, so swapping one for the
  other would not even be a change;
* and it must **apply**: every candidate is put through `apply_profile_binding` and any refusal
  removes it. Compatibility is measured, never assumed.

**The decision rule.** Stage 9D measured the listener against themselves on byte-identical
pairs — usefulness ICC(1,1) 0.76, distinctiveness 0.73, Atari character 0.92 — so the rule is
built on what that noise allows:

| condition | requirement |
| :--- | :--- |
| **floor** | Atari character ≥ 3 (the listener's neutral point). A sound they heard as *not* Atari-like cannot be the improvement in an Atari composition |
| **no regression** | rated **no lower** than the old profile on usefulness, distinctiveness and Atari character — nothing is traded |
| **a clear gain** | either one rating improves by ≥ 2 (outside the disagreement the listener showed against themselves), or two ratings improve together |

Anything else keeps the old profile, and a candidate that wins on none of these is not a
replacement, however much better it looks on one number.

**Why distinctiveness is not a criterion.** *Observed:* across the whole library the
listener's distinctiveness and Atari-character ratings oppose each other — Spearman **-0.57** (n=60) — and usefulness tracks character (+0.57) while it *anti*-tracks distinctiveness (−0.24). *Inference:* a rule that bought
distinctiveness with character would be moving against the dimension the questionnaire asks
about, so this experiment does not do it. That is also why several channels whose old profile
is the listener's *least* distinctive ("typical atari lead tone", distinctiveness 1) are
**kept**: those profiles are simultaneously the most Atari-like ones in the library (character
5), and no replacement is rated at least as highly on every scale.

**The pools, as measured.** Every candidate that reached the shortlist of its channel, with the
ratings the decision was made on. A candidate marked **ok** satisfies the three conditions;
`applies` is the renderer's answer, not a prediction:

| song | ch | role | old | candidates considered, best first (U/D/C) |
| :--- | ---: | :--- | :--- | :--- |
| `Vaults-of-Nhyrmeth.dsl` | 1 | bass | `pokey_ref_3627798b` | `pokey_ref_089a0846` (4/4/4 **ok**), `pokey_ref_3658a088` (4/3/4), `pokey_ref_9a86568a` (4/3/4), `pokey_ref_ed07bb73` (4/4/3), `pokey_ref_a09c0263` (4/3/3) |
| `Vaults-of-Nhyrmeth.dsl` | 3 | lead | `pokey_ref_c321892f` | `pokey_ref_953311ef` (4/3/5 **ok**), `pokey_ref_0657f037` (4/4/4), `pokey_ref_2b83db43` (4/4/4), `pokey_ref_5ee9c1a8` (4/4/4), `pokey_ref_7611576e` (4/4/4) |
| `Vaults-of-Nhyrmeth.dsl` | 4 | perc | `pokey_ref_6db98eb5` | `pokey_ref_23665c4f` (4/3/4 **ok**), `pokey_ref_914c63ec` (3/3/3), `pokey_ref_a8c81a84` (3/3/3), `pokey_ref_f022d673` (3/3/3), `pokey_ref_c25e268b` (3/5/2) |
| `as-1.dsl` | 1 | bass | `pokey_ref_331fbbd7` | `pokey_ref_089a0846` (4/4/4 **ok**), `pokey_ref_3658a088` (4/3/4), `pokey_ref_9a86568a` (4/3/4), `pokey_ref_ed07bb73` (4/4/3), `pokey_ref_a09c0263` (4/3/3) |
| `as-1.dsl` | 3 | lead | `pokey_ref_1ef377fc` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_0657f037` (4/4/4), `pokey_ref_2b83db43` (4/4/4), `pokey_ref_5ee9c1a8` (4/4/4), `pokey_ref_7611576e` (4/4/4) |
| `as-1.dsl` | 4 | perc | `pokey_ref_6db98eb5` | `pokey_ref_23665c4f` (4/3/4 **ok**), `pokey_ref_914c63ec` (3/3/3), `pokey_ref_a8c81a84` (3/3/3), `pokey_ref_f022d673` (3/3/3), `pokey_ref_c25e268b` (3/5/2) |
| `dziki2.json` | 1 | bass | `pokey_ref_a09c0263` | `pokey_ref_3658a088` (4/3/4), `pokey_ref_f3e3c618` (4/3/3), `pokey_ref_331fbbd7` (3/4/3), `pokey_ref_3627798b` (3/4/3), `pokey_ref_b1b73fa2` (3/4/3) |
| `dziki2.json` | 3 | lead | `pokey_ref_7611576e` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_ad730372` (4/3/5), `pokey_ref_e86c9631` (4/3/5), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `dziki2.json` | 4 | bell + counter + drum | `pokey_ref_80d1ce25` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_0657f037` (4/4/4), `pokey_ref_2b83db43` (4/4/4), `pokey_ref_5ee9c1a8` (4/4/4), `pokey_ref_7611576e` (4/4/4) |
| `as-2.dsl` | 1 | bass | `pokey_ref_3faf80b4` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_ad730372` (4/3/5), `pokey_ref_e86c9631` (4/3/5), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `as-2.dsl` | 2 | chord | `pokey_ref_1ef377fc` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_0657f037` (4/4/4), `pokey_ref_2b83db43` (4/4/4), `pokey_ref_5ee9c1a8` (4/4/4), `pokey_ref_7611576e` (4/4/4) |
| `as-2.dsl` | 3 | lead | `pokey_ref_25f94201` | `pokey_ref_953311ef` (4/3/5 **ok**), `pokey_ref_ad730372` (4/3/5 **ok**), `pokey_ref_e86c9631` (4/3/5 **ok**), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `as-2.dsl` | 4 | perc | `pokey_ref_6db98eb5` | `pokey_ref_23665c4f` (4/3/4 **ok**), `pokey_ref_914c63ec` (3/3/3), `pokey_ref_a8c81a84` (3/3/3), `pokey_ref_f022d673` (3/3/3), `pokey_ref_c25e268b` (3/5/2) |
| `funky.json` | 1 | lead | `pokey_ref_7611576e` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_ad730372` (4/3/5), `pokey_ref_e86c9631` (4/3/5), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `funky.json` | 2 | pad | `pokey_ref_80d1ce25` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_0657f037` (4/4/4), `pokey_ref_2b83db43` (4/4/4), `pokey_ref_5ee9c1a8` (4/4/4), `pokey_ref_7611576e` (4/4/4) |
| `funky.json` | 3 | bass | `pokey_ref_5ee9c1a8` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_ad730372` (4/3/5), `pokey_ref_e86c9631` (4/3/5), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `funky.json` | 4 | perc | `pokey_ref_1e9be30a` | `pokey_ref_23665c4f` (4/3/4 **ok**), `pokey_ref_914c63ec` (3/3/3), `pokey_ref_a8c81a84` (3/3/3), `pokey_ref_f022d673` (3/3/3), `pokey_ref_c25e268b` (3/5/2) |
| `koval.json` | 1 | bass | `pokey_ref_5ee9c1a8` | `pokey_ref_953311ef` (4/3/5), `pokey_ref_ad730372` (4/3/5), `pokey_ref_e86c9631` (4/3/5), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `koval.json` | 2 | lead | `pokey_ref_953311ef` | `pokey_ref_ad730372` (4/3/5), `pokey_ref_e86c9631` (4/3/5), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5), `pokey_ref_80d1ce25` (4/2/5) |
| `koval.json` | 3 | arp + pad | `pokey_ref_959628d6` | `pokey_ref_953311ef` (4/3/5 **ok**), `pokey_ref_ad730372` (4/3/5 **ok**), `pokey_ref_e86c9631` (4/3/5 **ok**), `pokey_ref_0a53188c` (4/2/5), `pokey_ref_1ef377fc` (4/2/5) |
| `koval.json` | 4 | perc | `pokey_ref_2de893a6` | `pokey_ref_23665c4f` (4/3/4 **ok**), `pokey_ref_1e9be30a` (3/3/3), `pokey_ref_568403b4` (3/3/3), `pokey_ref_6db98eb5` (3/3/3), `pokey_ref_7983ed84` (3/3/3) |

(At most five are listed per channel, best first by the rule's own order — usefulness, then
Atari character, then distinctiveness. The full pool, including every refusal and its code, is
in [rebinding.json](../reports/stage10a/rebinding.json).)

## 5. The final experimental rebinding

**Experimental choice.** What changed, and by which rule. (Deltas are the listener's own, from
Stage 9D; `kept` means nothing was rated at least as highly on every scale.)

| song | channel | role(s) | old → new | rule |
| :--- | ---: | :--- | :--- | :--- |
| `Vaults-of-Nhyrmeth.dsl` | 1 | `bass` | `pokey_ref_3627798b` → `pokey_ref_089a0846` | consistent |
| `Vaults-of-Nhyrmeth.dsl` | 3 | `lead` | `pokey_ref_c321892f` → `pokey_ref_953311ef` | margin |
| `Vaults-of-Nhyrmeth.dsl` | 4 | `perc` | `pokey_ref_6db98eb5` → `pokey_ref_23665c4f` | consistent |
| `as-1.dsl` | 1 | `bass` | `pokey_ref_331fbbd7` → `pokey_ref_089a0846` | consistent |
| `as-1.dsl` | 3 | `lead` | `pokey_ref_1ef377fc` (kept) | kept |
| `as-1.dsl` | 4 | `perc` | `pokey_ref_6db98eb5` → `pokey_ref_23665c4f` | consistent |
| `dziki2.json` | 1 | `bass` | `pokey_ref_a09c0263` (kept) | kept |
| `dziki2.json` | 3 | `lead` | `pokey_ref_7611576e` (kept) | kept |
| `dziki2.json` | 4 | `bell` + `counter` + `drum` | `pokey_ref_80d1ce25` (kept) | kept |
| `as-2.dsl` | 1 | `bass` | `pokey_ref_3faf80b4` (kept) | kept |
| `as-2.dsl` | 2 | `chord` | `pokey_ref_1ef377fc` (kept) | kept |
| `as-2.dsl` | 3 | `lead` | `pokey_ref_25f94201` → `pokey_ref_0657f037` | margin |
| `as-2.dsl` | 4 | `perc` | `pokey_ref_6db98eb5` → `pokey_ref_23665c4f` | consistent |
| `funky.json` | 1 | `lead` | `pokey_ref_7611576e` (kept) | kept |
| `funky.json` | 2 | `pad` | `pokey_ref_80d1ce25` (kept) | kept |
| `funky.json` | 3 | `bass` | `pokey_ref_5ee9c1a8` (kept) | kept |
| `funky.json` | 4 | `perc` | `pokey_ref_1e9be30a` → `pokey_ref_23665c4f` | consistent |
| `koval.json` | 1 | `bass` | `pokey_ref_5ee9c1a8` (kept) | kept |
| `koval.json` | 2 | `lead` | `pokey_ref_953311ef` (kept) | kept |
| `koval.json` | 3 | `arp` + `pad` | `pokey_ref_959628d6` → `pokey_ref_ad730372` | margin |
| `koval.json` | 4 | `perc` | `pokey_ref_2de893a6` → `pokey_ref_23665c4f` | margin |

**10 of 21 channels changed**, covering 11 roles in 5 songs:

* `Vaults-of-Nhyrmeth.dsl` — 3 channel(s):
  * channel 1: `bass` → `pokey_ref_089a0846`
  * channel 3: `lead` → `pokey_ref_953311ef`
  * channel 4: `perc` → `pokey_ref_23665c4f`
* `as-1.dsl` — 2 channel(s):
  * channel 1: `bass` → `pokey_ref_089a0846`
  * channel 4: `perc` → `pokey_ref_23665c4f`
* `as-2.dsl` — 2 channel(s):
  * channel 3: `lead` → `pokey_ref_0657f037`
  * channel 4: `perc` → `pokey_ref_23665c4f`
* `funky.json` — 1 channel(s):
  * channel 4: `perc` → `pokey_ref_23665c4f`
* `koval.json` — 2 channel(s):
  * channel 3: `arp` + `pad` → `pokey_ref_ad730372`
  * channel 4: `perc` → `pokey_ref_23665c4f`

**Left untouched, deliberately:**

* `dziki2.json` — 3 channel(s):
  * channel 1 (`bass`): keeps `pokey_ref_a09c0263` — no compatible replacement is rated at least as highly as this profile on every scale the listener used, so this channel keeps the sound Stage 9C already bound
  * channel 3 (`lead`): keeps `pokey_ref_7611576e` — no compatible replacement is rated at least as highly as this profile on every scale the listener used, so this channel keeps the sound Stage 9C already bound
  * channel 4 (`bell` + `counter` + `drum`): keeps `pokey_ref_80d1ce25` — no compatible replacement is rated at least as highly as this profile on every scale the listener used, so this channel keeps the sound Stage 9C already bound

A kept channel is a result, not an omission: it says the listening evidence does not justify
a better profile for that role, and inventing one would make this experiment a redesign
instead of a test.

**How equal candidates were separated.** Where several eligible candidates tied on all three
ratings, the experiment preferred one no other channel had taken, so the six songs do not
converge on one timbre. That preference is an experimental choice, not an inference — the
ratings cannot separate those profiles — and every decision records whether it applied.

## 6. Evidence for each changed assignment

One block per changed channel, in the form the brief asks for. `human_evidence` is quoted from
Stage 9D; `technical` is what the binding layer and the composition impose.

### `Vaults-of-Nhyrmeth.dsl` — channel 1: `bass`

```text
song          = Vaults-of-Nhyrmeth.dsl
instrument    = bass (channel 1, PITCHED)
old_profile   = pokey_ref_3627798b
new_profile   = pokey_ref_089a0846

reason:
  usefulness 3 -> 4 and atari_character 3 -> 4: two ratings improve together with nothing lower (adopted by the consistent rule; no other channel of this song already uses this sound; no other channel of the programme had taken it yet).

human_evidence:
  old: usefulness 3, distinctiveness 4, Atari character 3, comment 'short loud lead tone'
  new: usefulness 4, distinctiveness 4, Atari character 4, comment 'nice atari lead tone'
  rule: consistent

technical:
  scope PAIR, generator $C, AUDCTL $50, status PLAYABLE_WITH_LIMITATION
  channel 1 carries bass: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `Vaults-of-Nhyrmeth.dsl` — channel 3: `lead`

```text
song          = Vaults-of-Nhyrmeth.dsl
instrument    = lead (channel 3, PITCHED)
old_profile   = pokey_ref_c321892f
new_profile   = pokey_ref_953311ef

reason:
  distinctiveness 1 -> 3: a gain of 2, at the threshold the listener's own repeatability requires, with no rating lower (adopted by the margin rule; no other channel of this song already uses this sound; no other channel of the programme had taken it yet).

human_evidence:
  old: usefulness 4, distinctiveness 1, Atari character 5, comment 'clean atari-like lead tone'
  new: usefulness 4, distinctiveness 3, Atari character 5, comment 'clean atari lead tone'
  rule: margin

technical:
  scope VOICE, generator $A, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 3 carries lead: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `Vaults-of-Nhyrmeth.dsl` — channel 4: `perc`

```text
song          = Vaults-of-Nhyrmeth.dsl
instrument    = perc (channel 4, UNPITCHED)
old_profile   = pokey_ref_6db98eb5
new_profile   = pokey_ref_23665c4f

reason:
  usefulness 3 -> 4 and atari_character 3 -> 4: two ratings improve together with nothing lower (adopted by the consistent rule; no other channel of this song already uses this sound; no other channel of the programme had taken it yet).

human_evidence:
  old: usefulness 3, distinctiveness 3, Atari character 3, comment 'bass/perc?'
  new: usefulness 4, distinctiveness 3, Atari character 4, comment 'perc?'
  rule: consistent

technical:
  scope VOICE, generator $8, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 4 carries perc: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `as-1.dsl` — channel 1: `bass`

```text
song          = as-1.dsl
instrument    = bass (channel 1, PITCHED)
old_profile   = pokey_ref_331fbbd7
new_profile   = pokey_ref_089a0846

reason:
  usefulness 3 -> 4 and atari_character 3 -> 4: two ratings improve together with nothing lower (adopted by the consistent rule; no other channel of this song already uses this sound; every eligible alternative was already taken elsewhere in the programme, so this channel takes the best of them).

human_evidence:
  old: usefulness 3, distinctiveness 4, Atari character 3, comment 'short lead tone'
  new: usefulness 4, distinctiveness 4, Atari character 4, comment 'nice atari lead tone'
  rule: consistent

technical:
  scope PAIR, generator $C, AUDCTL $50, status PLAYABLE_WITH_LIMITATION
  channel 1 carries bass: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `as-1.dsl` — channel 4: `perc`

```text
song          = as-1.dsl
instrument    = perc (channel 4, UNPITCHED)
old_profile   = pokey_ref_6db98eb5
new_profile   = pokey_ref_23665c4f

reason:
  usefulness 3 -> 4 and atari_character 3 -> 4: two ratings improve together with nothing lower (adopted by the consistent rule; no other channel of this song already uses this sound; every eligible alternative was already taken elsewhere in the programme, so this channel takes the best of them).

human_evidence:
  old: usefulness 3, distinctiveness 3, Atari character 3, comment 'bass/perc?'
  new: usefulness 4, distinctiveness 3, Atari character 4, comment 'perc?'
  rule: consistent

technical:
  scope VOICE, generator $8, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 4 carries perc: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `as-2.dsl` — channel 3: `lead`

```text
song          = as-2.dsl
instrument    = lead (channel 3, PITCHED)
old_profile   = pokey_ref_25f94201
new_profile   = pokey_ref_0657f037

reason:
  usefulness 2 -> 4 and distinctiveness 3 -> 4: a gain of 2, at the threshold the listener's own repeatability requires, with no rating lower (adopted by the margin rule; no other channel of this song already uses this sound; no other channel of the programme had taken it yet).

human_evidence:
  old: usefulness 2, distinctiveness 3, Atari character 4, comment 'clean lead atari-like but with some break in background'
  new: usefulness 4, distinctiveness 4, Atari character 4, comment 'nice mid-len lead sound'
  rule: margin

technical:
  scope VOICE, generator $A, AUDCTL $00, status PLAYABLE
  channel 3 carries lead: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `as-2.dsl` — channel 4: `perc`

```text
song          = as-2.dsl
instrument    = perc (channel 4, UNPITCHED)
old_profile   = pokey_ref_6db98eb5
new_profile   = pokey_ref_23665c4f

reason:
  usefulness 3 -> 4 and atari_character 3 -> 4: two ratings improve together with nothing lower (adopted by the consistent rule; no other channel of this song already uses this sound; every eligible alternative was already taken elsewhere in the programme, so this channel takes the best of them).

human_evidence:
  old: usefulness 3, distinctiveness 3, Atari character 3, comment 'bass/perc?'
  new: usefulness 4, distinctiveness 3, Atari character 4, comment 'perc?'
  rule: consistent

technical:
  scope VOICE, generator $8, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 4 carries perc: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `funky.json` — channel 4: `perc`

```text
song          = funky.json
instrument    = perc (channel 4, UNPITCHED)
old_profile   = pokey_ref_1e9be30a
new_profile   = pokey_ref_23665c4f

reason:
  usefulness 3 -> 4 and atari_character 3 -> 4: two ratings improve together with nothing lower (adopted by the consistent rule; no other channel of this song already uses this sound; every eligible alternative was already taken elsewhere in the programme, so this channel takes the best of them).

human_evidence:
  old: usefulness 3, distinctiveness 3, Atari character 3, comment 'noisy bass/perc?'
  new: usefulness 4, distinctiveness 3, Atari character 4, comment 'perc?'
  rule: consistent

technical:
  scope VOICE, generator $8, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 4 carries perc: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `koval.json` — channel 3: `arp` + `pad`

```text
song          = koval.json
instrument    = arp, pad (channel 3, PITCHED + PITCHED)
old_profile   = pokey_ref_959628d6
new_profile   = pokey_ref_ad730372

reason:
  usefulness 3 -> 4 and atari_character 3 -> 5: a gain of 2, at the threshold the listener's own repeatability requires, with no rating lower (adopted by the margin rule; no other channel of this song already uses this sound; no other channel of the programme had taken it yet).

human_evidence:
  old: usefulness 3, distinctiveness 3, Atari character 3, comment 'loud lead atari-like sound'
  new: usefulness 4, distinctiveness 3, Atari character 5, comment 'very clean atari lead tone'
  rule: margin

technical:
  scope VOICE, generator $A, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 3 carries arp, pad: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

### `koval.json` — channel 4: `perc`

```text
song          = koval.json
instrument    = perc (channel 4, UNPITCHED)
old_profile   = pokey_ref_2de893a6
new_profile   = pokey_ref_23665c4f

reason:
  usefulness 2 -> 4 and atari_character 3 -> 4: a gain of 2, at the threshold the listener's own repeatability requires, with no rating lower (adopted by the margin rule; no other channel of this song already uses this sound; every eligible alternative was already taken elsewhere in the programme, so this channel takes the best of them).

human_evidence:
  old: usefulness 2, distinctiveness 3, Atari character 3, comment 'noisy bass/perc?'
  new: usefulness 4, distinctiveness 3, Atari character 4, comment 'perc?'
  rule: margin

technical:
  scope VOICE, generator $8, AUDCTL $00, status PLAYABLE_WITH_LIMITATION
  channel 4 carries perc: one profile for the channel
  applies as a whole binding: yes (measured, not assumed)
```

## 7. Machine-level differences

**Observed.** Diagnostics, not a verdict. §13 of the brief is explicit that a higher spectral
distance, a wider bandwidth or a higher RMS does **not** mean a better sound, and nothing below
is used to prefer a version.

**First, the comparability check.** The *default* and *old* sides were compared byte for byte
with the Stage 9C package's own stimuli, and the shared gain was compared with the gain that
package recorded:

| song | gain (dB) | default identical | old identical | bytes compared |
| :--- | ---: | :--- | :--- | ---: |
| `Vaults-of-Nhyrmeth.dsl` | +0.0004 | yes | yes | 1323000 / 1323000 |
| `as-1.dsl` | +3.6083 | yes | yes | 1323000 / 1323000 |
| `dziki2.json` | +1.6229 | yes | yes | 1323000 / 1323000 |
| `as-2.dsl` | +3.9232 | yes | yes | 1323000 / 1323000 |
| `funky.json` | +0.4476 | yes | yes | 1323000 / 1323000 |
| `koval.json` | +0.0004 | yes | yes | 1323000 / 1323000 |

**Inference.** The comparison the listener will make is comparable with the 5–0 it re-tests:
same excerpts, same gain, same renderer, and the old side is the old audio. Stage 9C's own
*default vs old* result can therefore be treated as a control measured in a different session,
which is why the package repeats it (§8).

**Levels and spectra per version.** One shared gain per song, applied to all three versions:

| song | version | peak dBFS | RMS dBFS | centroid Hz | bandwidth Hz | flatness |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `Vaults-of-Nhyrmeth.dsl` | default | -0.92 | -11.67 | 5020 | 6198 | 0.5430 |
| `Vaults-of-Nhyrmeth.dsl` | old | -1.74 | -12.08 | 5420 | 6301 | 0.5751 |
| `Vaults-of-Nhyrmeth.dsl` | new | -0.92 | -14.54 | 4563 | 5852 | 0.5327 |
| `as-1.dsl` | default | -0.92 | -11.68 | 5086 | 6221 | 0.5578 |
| `as-1.dsl` | old | -0.77 | -11.90 | 5522 | 6350 | 0.5890 |
| `as-1.dsl` | new | -1.08 | -11.21 | 5161 | 6142 | 0.5800 |
| `dziki2.json` | default | -0.92 | -10.90 | 5313 | 6272 | 0.5354 |
| `dziki2.json` | old | -0.80 | -14.82 | 4719 | 5921 | 0.5423 |
| `dziki2.json` | new | -0.80 | -14.82 | 4719 | 5921 | 0.5423 |
| `as-2.dsl` | default | -0.92 | -10.53 | 5141 | 6103 | 0.5305 |
| `as-2.dsl` | old | -0.09 | -10.40 | 4965 | 6014 | 0.4927 |
| `as-2.dsl` | new | -0.58 | -13.40 | 5019 | 6026 | 0.4754 |
| `funky.json` | default | -0.92 | -12.81 | 5513 | 6233 | 0.5865 |
| `funky.json` | old | -0.92 | -17.04 | 5068 | 6032 | 0.5271 |
| `funky.json` | new | -0.92 | -17.07 | 5074 | 6033 | 0.5272 |
| `koval.json` | default | -0.92 | -10.93 | 5390 | 6175 | 0.5883 |
| `koval.json` | old | -0.92 | -14.19 | 5237 | 6082 | 0.5804 |
| `koval.json` | new | -0.92 | -14.62 | 5204 | 6067 | 0.5797 |

**Hashes and duration.** One SHA-256 per rendered version, and the excerpt's length, so a
rerun can be compared against this document rather than against a description of it:

| song | version | duration (s) | sha256 (first 16) |
| :--- | :--- | ---: | :--- |
| `Vaults-of-Nhyrmeth.dsl` | default | 15.000 | `a905a29412f48cd9` |
| `Vaults-of-Nhyrmeth.dsl` | old | 15.000 | `70fc0413e9a07b67` |
| `Vaults-of-Nhyrmeth.dsl` | new | 15.000 | `a23c106a14a6bd69` |
| `as-1.dsl` | default | 15.000 | `ef9d540f636e3372` |
| `as-1.dsl` | old | 15.000 | `bc129acb3befbbe3` |
| `as-1.dsl` | new | 15.000 | `a364a0954b4791bc` |
| `dziki2.json` | default | 15.000 | `78f6ff8deb087e8d` |
| `dziki2.json` | old | 15.000 | `de3ece7b8eafa26c` |
| `dziki2.json` | new | 15.000 | `de3ece7b8eafa26c` |
| `as-2.dsl` | default | 15.000 | `3dce1c2b5c36904b` |
| `as-2.dsl` | old | 15.000 | `27f37fa253f67f4d` |
| `as-2.dsl` | new | 15.000 | `c94b7f61564b9978` |
| `funky.json` | default | 15.000 | `f14afa01cb996af9` |
| `funky.json` | old | 15.000 | `007d308bf77b1840` |
| `funky.json` | new | 15.000 | `817f53fc7e3f6933` |
| `koval.json` | default | 15.000 | `ca443700027da8fa` |
| `koval.json` | old | 15.000 | `d9ea96822456eea2` |
| `koval.json` | new | 15.000 | `97e17e0ac0b97a79` |

All three versions of a song have the same frame count and the same duration: the profile
changes what each channel sounds like, never what or when it plays.

**Pairwise differences.** `audio identical` compares the two rendered WAV payloads byte for
byte; `frames identical` compares the register streams; `spectral distance` is the Stage 9C
band-energy cosine distance between the two versions:

| song | pair | audio identical | frames identical | spectral distance | RMS Δ (dB) | AUDCTL |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| `Vaults-of-Nhyrmeth.dsl` | default vs old | no | no | 0.0178 | -0.41 | default $10 → old $50 |
| `Vaults-of-Nhyrmeth.dsl` | default vs new | no | no | 0.0191 | -2.87 | default $10 → new $50 |
| `Vaults-of-Nhyrmeth.dsl` | old vs new | no | no | 0.0161 | -2.46 | old $50 → new $50 |
| `as-1.dsl` | default vs old | no | no | 0.0188 | -0.22 | default $10 → old $50 |
| `as-1.dsl` | default vs new | no | no | 0.0227 | +0.47 | default $10 → new $50 |
| `as-1.dsl` | old vs new | no | no | 0.0098 | +0.69 | old $50 → new $50 |
| `dziki2.json` | default vs old | no | no | 0.0325 | -3.92 | default $10 → old $50 |
| `dziki2.json` | default vs new | no | no | 0.0325 | -3.92 | default $10 → new $50 |
| `dziki2.json` | old vs new | yes | yes | 0.0000 | +0.00 | old $50 → new $50 |
| `as-2.dsl` | default vs old | no | no | 0.0032 | +0.12 | default $00 → old $00 |
| `as-2.dsl` | default vs new | no | no | 0.0054 | -2.87 | default $00 → new $00 |
| `as-2.dsl` | old vs new | no | no | 0.0005 | -3.00 | old $00 → new $00 |
| `funky.json` | default vs old | no | no | 0.0077 | -4.23 | default $00 → old $00 |
| `funky.json` | default vs new | no | no | 0.0077 | -4.26 | default $00 → new $00 |
| `funky.json` | old vs new | no | no | 0.0000 | -0.03 | old $00 → new $00 |
| `koval.json` | default vs old | no | no | 0.0075 | -3.27 | default $00 → old $00 |
| `koval.json` | default vs new | no | no | 0.0073 | -3.69 | default $00 → new $00 |
| `koval.json` | old vs new | no | no | 0.0001 | -0.42 | old $00 → new $00 |

**Register-frame differences.** How many frames differ, and in which columns, between the
versions. Columns are named in row order (`AUDF1, AUDC1, AUDF2, AUDC2, …, AUDCTL`). An AUDF
column differing means the same notes sit at different dividers — a consequence of the
profile's clock, not of the music; a differing AUDC column is a different generator or a
different per-frame volume:

| song | pair | frames differing | columns differing (frames) | AUDCTL |
| :--- | :--- | ---: | :--- | :--- |
| `Vaults-of-Nhyrmeth.dsl` | default vs old | 2280 / 2280 | AUDF1×2240, AUDF2×2240, AUDC2×2240, AUDCTL×2280 | default $10 → old $50 |
| `Vaults-of-Nhyrmeth.dsl` | default vs new | 2280 / 2280 | AUDF1×2240, AUDF2×2240, AUDC2×2240, AUDC3×2121, AUDC4×1233, AUDCTL×2280 | default $10 → new $50 |
| `Vaults-of-Nhyrmeth.dsl` | old vs new | 2141 / 2280 | AUDC2×2107, AUDC3×2121, AUDC4×1233 | old $50 → new $50 |
| `as-1.dsl` | default vs old | 2280 / 2280 | AUDF1×1550, AUDF2×1550, AUDC2×1550, AUDCTL×2280 | default $10 → old $50 |
| `as-1.dsl` | default vs new | 2280 / 2280 | AUDF1×1550, AUDF2×1550, AUDC2×1550, AUDC4×1240, AUDCTL×2280 | default $10 → new $50 |
| `as-1.dsl` | old vs new | 1718 / 2280 | AUDC2×1475, AUDC4×1240 | old $50 → new $50 |
| `dziki2.json` | default vs old | 4608 / 4608 | AUDF1×4080, AUDF2×4080, AUDC2×4080, AUDC3×4414, AUDC4×432, AUDCTL×4608 | default $10 → old $50 |
| `dziki2.json` | default vs new | 4608 / 4608 | AUDF1×4080, AUDF2×4080, AUDC2×4080, AUDC3×4414, AUDC4×432, AUDCTL×4608 | default $10 → new $50 |
| `dziki2.json` | old vs new | 0 / 4608 | — | old $50 → new $50 |
| `as-2.dsl` | default vs old | 1740 / 2160 | AUDC3×1740 | default $00 → old $00 |
| `as-2.dsl` | default vs new | 1868 / 2160 | AUDC3×1716, AUDC4×1539 | default $00 → new $00 |
| `as-2.dsl` | old vs new | 1961 / 2160 | AUDC3×1810, AUDC4×1539 | old $00 → new $00 |
| `funky.json` | default vs old | 4046 / 4608 | AUDC1×4046 | default $00 → old $00 |
| `funky.json` | default vs new | 4048 / 4608 | AUDC1×4046, AUDC4×534 | default $00 → new $00 |
| `funky.json` | old vs new | 534 / 4608 | AUDC4×534 | old $00 → new $00 |
| `koval.json` | default vs old | 6080 / 6144 | AUDC2×5856, AUDC3×3904, AUDC4×3456 | default $00 → old $00 |
| `koval.json` | default vs new | 5856 / 6144 | AUDC2×5856, AUDC4×3072 | default $00 → new $00 |
| `koval.json` | old vs new | 4960 / 6144 | AUDC3×3904, AUDC4×2688 | old $00 → new $00 |

**Clipping.** The peak is normalized to the target from the default side and the same gain is
applied to all three, so a louder timbre could clip. Every version's clipped-sample count is
recorded rather than hidden:

| song | default | old | new |
| :--- | ---: | ---: | ---: |
| `Vaults-of-Nhyrmeth.dsl` | 0 | 0 | 0 |
| `as-1.dsl` | 0 | 0 | 0 |
| `dziki2.json` | 0 | 0 | 0 |
| `as-2.dsl` | 0 | 0 | 0 |
| `funky.json` | 0 | 0 | 0 |
| `koval.json` | 0 | 0 | 0 |

## 8. The listening experiment

**Experimental choice.** A new, blinded package in `examples/sound_profile_rebinding_10a/`.
Nothing from Stage 9C is reused or overwritten.

| | |
| :--- | :--- |
| pairs | **18** — `default vs new`, `old vs new` and the `default vs old` control, once per song |
| excerpt | 15.0 s from the start of the render, identical window for both sides |
| gain | one per song, from the default side, applied to all three versions |
| labels | `A` and `B` only; orientation randomized from seed 20261006 |
| order | the three comparisons of a song are shuffled per song |
| questions | better overall · more convincing Atari · more interesting character · how different (1–5) · comment |
| answers | `evaluation_rebinding_10a.csv`, filled in the browser and downloaded |

The control pair re-asks the Stage 9C question inside this session. It is included because
Stage 9D measured a session effect — Atari character and confidence correlated with presentation
position at Pearson -0.37 and -0.47 — so without it a change in the `default vs new`
result could not be separated from the session the listener was in.
**The twelve primary comparisons are the `default vs new` and `old vs new` pairs**; the six
control pairs are analysed separately, against Stage 9C's own 5–0, and are not counted as
evidence for or against the new assignment.

**What the interface does not say.** No version name, profile id, generator family, scope, source song or technical description appears on the page, and the three comparisons are
captioned identically, so nothing hints which side is the library. The mapping exists only in
`manifest.json`, which the README tells the listener not to open while listening.

**What is asked, exactly:**

1. Which version sounds better overall? (`A` / `B` / no clear difference)
2. Which sounds more convincing as Atari music? (`A` / `B` / no clear difference)
3. Which has the more interesting or appropriate sound character? (`A` / `B` / no clear difference)
4. How different do the two versions sound? (1–5)
5. Comment (free text, optional)

How to listen:

```bash
# open examples/sound_profile_rebinding_10a/index.html, or serve the folder:
python -m http.server 8731 --directory examples/sound_profile_rebinding_10a
```

## 9. Limitations

**Observed and structural.** These are properties of the material, not of the preparation:

* **Six songs are not a population.** A win or a loss here is a direction, not a rate.
* **The same song is heard three times**, so a listener may recognize it and anchor on an
  earlier answer. The order and orientations are randomized to limit this, not to remove it.
* **The ratings came from one phrase.** Every profile was auditioned playing one bright-lead
  line, so `lead_tonal` really means "this followed that melody" and `percussive_noisy` means
  "this did not". They are evidence about character in that context, not about behaviour
  inside a particular arrangement.
* **One profile per channel.** `dziki2.json` puts a bell, a counter and a drum on channel 4, so
  one profile must serve all three. No assignment can be right for all of them, and the
  experiment does not pretend otherwise.
* **The library's top tier is a tie.** Several tonal profiles share the listener's highest
  ratings, so which one a song received is partly an experimental choice (§5).
* **Gestures are still not rendered.** Stage 9E measured that the binding carries six values
  and that every gesture series is discarded before the audio. Rebinding cannot change that,
  and it is the main reason a positive result here would not mean the representation is
  sufficient.

**What this experiment therefore cannot show:** whether a *better library* would beat the
composer's own instruments, whether gesture rendering would, or whether the listener's
preferences generalise beyond these six songs and this sitting.

## 10. STOP condition

**STOP.** The experiment is prepared and nothing else is done:

* no gesture rendering, no player change, no POKEY IR change;
* no change to `SoundProfile`, `PlayableSoundProfile`, the bank, a fingerprint or a profile
  document;
* no change to the DSL, the composer, the generator, the prompts or the MML/MADS exporters;
* no library selection, no profile removed, no rename;
* the Stage 9C package, its stimuli, its answers and its results are untouched (digested
  before and after, and the digests are equal);
* the six compositions and the six old bindings are byte-identical to what they were.

Waiting for: the filled-in `evaluation_rebinding_10a.csv`.

The next decision, in the brief's own terms:

| result | next step |
| :--- | :--- |
| **A** — rebinding improves whole songs | investigate role-aware profile selection, and only then any automatic binding |
| **B** — rebinding does not improve them | profile selection is not the main problem; proceed to the minimal renderer capability experiment Stage 9E scoped |
| **C** — mixed | inspect which roles benefit and which do not |

The next stage is not started here.

