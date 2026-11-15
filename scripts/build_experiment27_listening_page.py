"""Build the Experiment 27 listening page, its blinded audio set and its CSV templates.

Run it with:

```
python scripts/build_experiment27_listening_page.py
```

It writes `experiments/experiment27/listening/`:

| file | what it is |
| :--- | :--- |
| `index.html` | the listening interface — the only file a listener opens |
| `audio/clip_NN.wav` | the twelve clips under blinded names |
| `manifest.json` | the answer key (clip → variant) and the machine record — **not** for the listener |
| `evaluation_experiment27_clips.csv` | the empty per-clip answer template |
| `evaluation_experiment27_summary.csv` | the empty per-listener answer template |
| `README.md` | how to open it and what is asked |

The clip numbering is a **seeded** shuffle of the four variants inside each score, so the mapping is
reproducible; changing `SEED` invalidates answers already collected, which is why it is a constant
and not an argument. The page carries only blinded ids, and the variant names live in the manifest,
so a listener cannot read the answer off the interface.

Nothing is re-rendered here: the audio is copied from the WAVs Experiment 27 already produced, so the
page cannot drift away from the delivered artefact set.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from atari_music import pokey_octave_pulse_experiment as e27  # noqa: E402

EXPERIMENT_DIR = ROOT_DIR / "experiments" / "experiment27"
LISTENING_DIR = EXPERIMENT_DIR / "listening"

#: Fixed, so the clip numbering is reproducible. Changing it invalidates collected answers. The value
#: is arbitrary; it was picked because it deranges all three score blocks, so no clip keeps its
#: "natural" position and a listener cannot guess a variant from a clip number.
SEED = 20

CLIP_PREFIX = "clip"
#: The three scores, in the order the page presents them.
SCORE_ORDER = ("note", "phrase", "phrase_low")
SCORE_DESCRIPTIONS: Dict[str, str] = {
    "note": "a single held note — A-4, about 1 second",
    "phrase": "a four-note phrase — A-4, C-5, E-5, C-5, about 1.6 seconds",
    "phrase_low": "the same phrase an octave lower — A-3, C-4, E-4, C-4",
}
#: One sentence per score, used as the heading of its block.
SCORE_HEADINGS: Dict[str, str] = {
    "note": "Single note",
    "phrase": "Short phrase",
    "phrase_low": "Short phrase, an octave lower",
}

CLIPS_CSV = "evaluation_experiment27_clips.csv"
SUMMARY_CSV = "evaluation_experiment27_summary.csv"

#: The 1–5 ratings asked of every clip. The end labels are what make the number mean something, so
#: they are defined once here and injected into the page and the manifest together.
CLIP_SCALES: List[Dict[str, Any]] = [
    {
        "field": "musical_usefulness_1_5",
        "question": "Could you use this sound in a game tune?",
        "labels": ["no", "maybe", "yes", "yes, gladly", "yes, definitely"],
    },
    {
        "field": "character_interest_1_5",
        "question": "How interesting is the timbre itself?",
        "labels": ["dull", "plain", "fair", "interesting", "striking"],
    },
    {
        "field": "annoyance_1_5",
        "question": "How irritating is it?",
        "labels": ["not at all", "slightly", "moderately", "quite", "very"],
    },
]

#: The one multiple-choice question asked of every clip.
CLIP_PULSE_QUESTION: Dict[str, Any] = {
    "field": "pulse_reads_as",
    "question": "Does the movement inside the note read as…",
    "choices": [
        {"value": "deliberate", "label": "deliberate"},
        {"value": "a fault", "label": "a fault"},
        {"value": "no clear movement", "label": "there is no clear movement"},
        {"value": "unsure", "label": "unsure"},
    ],
}

#: The per-score preference questions.
PREFERENCE_QUESTIONS: List[Dict[str, Any]] = [
    {"field": "best_clip", "question": "Which of these four would you actually use?"},
    {"field": "least_usable_clip", "question": "Which of these four is the least usable?"},
]

#: The questions about the whole set, asked once.
OVERALL_QUESTIONS: List[Dict[str, Any]] = [
    {
        "field": "slower_pulse_better",
        "question": (
            "One variant holds each divider value for several frames instead of flipping every "
            "frame. Does that slower version sound more usable than the fastest one?"
        ),
        "labels": ["yes", "no", "no clear difference"],
    },
    {
        "field": "movement_at_start_better",
        "question": (
            "One variant keeps the movement only at the start of the note and then holds a steady "
            "divider. Does that sound better than a movement running through the whole note?"
        ),
        "labels": ["yes", "no", "no clear difference"],
    },
    {
        "field": "alternating_notes_deliberate",
        "question": (
            "One variant has the movement on some notes and not others, inside the same phrase. "
            "Does that sound deliberate?"
        ),
        "labels": ["yes", "no", "can't tell"],
    },
    {
        "field": "low_register_works",
        "question": "The same effect an octave lower: does it still work there?",
        "labels": [
            "yes, as well", "yes, but different", "better in the low register",
            "worse in the low register", "no",
        ],
    },
    {
        "field": "worth_developing",
        "question": "Is this octave-pulse timbre worth developing further as an instrument?",
        "labels": ["yes", "maybe", "no"],
    },
]

CLIP_FIELDS = (
    "listener", "clip", "score", "musical_usefulness_1_5", "character_interest_1_5",
    "pulse_reads_as", "annoyance_1_5", "comment",
)
SUMMARY_FIELDS = (
    "listener",
    "note_best_clip", "note_least_usable_clip", "note_comment",
    "phrase_best_clip", "phrase_least_usable_clip", "phrase_comment",
    "phrase_low_best_clip", "phrase_low_least_usable_clip", "phrase_low_comment",
    "slower_pulse_better", "movement_at_start_better", "alternating_notes_deliberate",
    "low_register_works", "worth_developing", "comment",
)


def clip_id(index: int) -> str:
    """``clip_01`` … ``clip_12``."""
    return f"{CLIP_PREFIX}_{index:02d}"


def build_mapping() -> List[Dict[str, Any]]:
    """The clip → (variant, score) key, as a seeded shuffle of the variants inside each score.

    Grouping by score is deliberate: the page asks a preference question per score, so a listener
    must be able to compare the four variants of one score without seeing the rest.
    """
    rng = random.Random(SEED)
    clips: List[Dict[str, Any]] = []
    index = 1
    for score in SCORE_ORDER:
        variants = list(e27.VARIANT_ORDER)
        rng.shuffle(variants)
        for variant in variants:
            clips.append({
                "clip": clip_id(index),
                "variant": variant,
                "variant_name": e27.VARIANT_NAMES[variant],
                "score": score,
                "source": e27.wav_filename(variant, score),
                "audio": f"audio/{clip_id(index)}.wav",
            })
            index += 1
    return clips


def write_audio(clips: List[Dict[str, Any]], audio_dir: Path) -> List[str]:
    """Copy each delivered WAV to its blinded name. Returns the files written."""
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for row in clips:
        source = EXPERIMENT_DIR / row["source"]
        if not source.is_file():
            raise FileNotFoundError(
                f"{source} is missing — run `python -m atari_music.pokey_octave_pulse_experiment` "
                "first, then rebuild this page"
            )
        target = audio_dir / Path(row["audio"]).name
        shutil.copyfile(source, target)
        written.append(row["audio"])
    return written


def build_package(clips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The object the page embeds. It carries no variant name, so the page cannot leak the key."""
    return {
        "experiment": "experiment27",
        "title": "POKEY octave-pulse timbre — listening test",
        "clips": [
            {"clip": row["clip"], "audio": row["audio"], "score": row["score"]}
            for row in clips
        ],
        "scores": [
            {
                "score": score,
                "heading": SCORE_HEADINGS[score],
                "description": SCORE_DESCRIPTIONS[score],
                "clips": [row["clip"] for row in clips if row["score"] == score],
            }
            for score in SCORE_ORDER
        ],
        "clip_scales": CLIP_SCALES,
        "pulse_question": CLIP_PULSE_QUESTION,
        "preference_questions": PREFERENCE_QUESTIONS,
        "overall_questions": OVERALL_QUESTIONS,
        "clip_fields": list(CLIP_FIELDS),
        "summary_fields": list(SUMMARY_FIELDS),
    }


_PAGE_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; padding: 1.5rem;
         background: #14161a; color: #e8e8ea; line-height: 1.5; }
  main { max-width: 62rem; margin: 0 auto; }
  h1, h2, h3 { line-height: 1.2; }
  h2 { margin-top: 2.5rem; border-top: 1px solid #2c3036; padding-top: 1.25rem; }
  h3 { margin-top: 1.75rem; }
  .note { background: #1d2026; border-left: 3px solid #4a7; padding: .75rem 1rem; margin: 1rem 0;
          border-radius: 3px; font-size: .95rem; }
  .note.warn { border-left-color: #c85; }
  .card { background: #1a1d22; border: 1px solid #2c3036; border-radius: 6px; padding: 1rem;
          margin: 1rem 0; }
  .card.done { border-color: #3d6; }
  .label { font-weight: 600; min-width: 11rem; }
  audio { width: 100%; max-width: 30rem; }
  .q { margin: .6rem 0; }
  .scale { display: flex; gap: .4rem; flex-wrap: wrap; }
  .scale label { background: #23272e; border: 1px solid #333; border-radius: 4px;
                 padding: .25rem .6rem; cursor: pointer; font-variant-numeric: tabular-nums; }
  .scale input { margin-right: .3rem; }
  textarea, input[type=text] { width: 100%; background: #23272e; color: inherit;
                 border: 1px solid #333; border-radius: 4px; padding: .4rem; font: inherit; }
  textarea { min-height: 3rem; }
  input[type=text] { max-width: 22rem; }
  button { background: #2d5; color: #06120a; border: 0; border-radius: 4px; padding: .55rem 1rem;
           font: inherit; font-weight: 600; cursor: pointer; margin-right: .5rem; margin-bottom: .5rem; }
  button.ghost { background: #333; color: #ddd; }
  .progress { position: sticky; top: 0; background: #14161af2; padding: .6rem 0; z-index: 5;
              border-bottom: 1px solid #2c3036; font-variant-numeric: tabular-nums; }
  .small { font-size: .88rem; color: #aab; }
  .cliphead { display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap; }
  .cliphead .tag { font-family: ui-monospace, Consolas, monospace; background: #23272e;
                   border: 1px solid #333; border-radius: 4px; padding: .1rem .45rem; font-size: .9rem; }
</style>
</head>
<body>
<main>
<h1>POKEY octave-pulse timbre — listening test</h1>

<div class="note">
  <strong>Your ears are the instrument here.</strong> You are hearing four ways of using one POKEY
  mechanism: the channel's divider switching between a note and its octave while the note sounds.
  All twelve clips share the same notes, pitches, durations, generator, volume shape, channel, clock,
  renderer and gain. Only the <em>pattern of the switch</em> differs.
</div>
<div class="note">
  <strong>Set your volume once and leave it alone.</strong> Every clip is presented at the same gain,
  so please judge character rather than loudness. The clips are level-matched to well under 1&nbsp;dB.
</div>
<div class="note">
  <strong>The clips are unlabelled on purpose.</strong> Which clip is which variant is in
  <code>manifest.json</code>, which you can open after you have downloaded your answers. Nothing on
  this page reveals it.
</div>
<div class="note warn">
  <strong>Some clips may sound like a fault rather than an instrument.</strong> That is a possible
  result, and saying so is useful. Answer "a fault" where it applies; there is no expected answer.
</div>

<div class="progress" id="progress">progress</div>

<h2>Your name or initials</h2>
<p class="small">Used only as the first column of the downloaded CSV, so several listeners' files can
be told apart. Leave it blank if you prefer.</p>
<div class="q"><input type="text" id="listener" placeholder="anonymous"
  oninput="setMeta('listener', this.value)"></div>

<div id="scores"></div>

<h2>Questions about the whole set</h2>
<p class="small">Answer these after you have heard all twelve clips.</p>
<div class="card" id="overall">
  <div id="overallQuestions"></div>
  <div class="q"><div class="label">Anything else you noticed (optional)</div>
    <textarea id="overallComment" oninput="setMeta('comment', this.value)"></textarea></div>
</div>

<h2>Finish</h2>
<p class="small">Download both files and put them back in this folder. Nothing is uploaded anywhere —
everything stays in this browser until you download it.</p>
<button onclick="downloadClips()">Download the clip ratings CSV</button>
<button onclick="downloadSummary()">Download the summary CSV</button>
<button class="ghost" onclick="if(confirm('Erase all answers in this browser?')){localStorage.clear();location.reload();}">Reset answers</button>
<p class="small" id="downloadState"></p>

<h2>After you have answered</h2>
<p class="small"><code>manifest.json</code> says which clip is which variant. Nothing on this page, and
neither downloaded CSV, contains that mapping — so reading the manifest early would bias the
ratings. The questions above do describe what the four variants <em>do</em>; what is withheld is
which clip is which.</p>

</main>
"""


_PAGE_SCRIPT = r"""
<script>
const PACKAGE = __PACKAGE__;
const STORE = "experiment27-answers-v1";

let answers = JSON.parse(localStorage.getItem(STORE) || "{}");
let meta = answers.__meta || {};

function save() { localStorage.setItem(STORE, JSON.stringify(answers)); refresh(); }
function get(key, field) { return (answers[key] || {})[field] ?? ""; }
function set(key, field, value) {
  answers[key] = answers[key] || {};
  answers[key][field] = value;
  save();
}
function setMeta(field, value) {
  meta[field] = value;
  answers.__meta = meta;
  save();
}
function listener() { return String(meta.listener ?? "").trim(); }

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}
function download(name, header, rows) {
  const body = [header.join(",")].concat(rows.map(r => r.map(csvEscape).join(","))).join("\n") + "\n";
  const url = URL.createObjectURL(new Blob([body], {type: "text/csv;charset=utf-8"}));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// --- question definitions -------------------------------------------------
// Every question comes from PACKAGE, so the page, the manifest and the CSV columns cannot drift
// apart: they are all rendered from the same declaration.

// --- row builders ---------------------------------------------------------
function scaleRow(key, field, question, labels) {
  const current = get(key, field);
  const inputs = labels.map((label, index) => {
    const value = index + 1;
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${value} ${label}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function choiceRow(key, field, question, values, labels) {
  const current = get(key, field);
  const inputs = values.map((value, index) => {
    const checked = String(current) === String(value) ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${labels[index]}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function commentRow(key, field, question) {
  const value = String(get(key, field)).replace(/</g, "&lt;");
  return `<div class="q"><div class="label">${question}</div>
    <textarea oninput="set('${key}','${field}',this.value)">${value}</textarea></div>`;
}

// --- completion -----------------------------------------------------------
const CLIP_FIELDS = ["musical_usefulness_1_5", "character_interest_1_5", "pulse_reads_as",
                     "annoyance_1_5"];
function clipDone(id) {
  const fields = PACKAGE.clip_scales.map(s => s.field).concat([PACKAGE.pulse_question.field]);
  return fields.every(field => get(id, field) !== "");
}

const PREF_FIELDS = ["best_clip", "least_usable_clip"];
function scoreDone(score) { return PREF_FIELDS.every(field => get(score, field) !== ""); }

function overallDone() {
  return PACKAGE.overall_questions.every(q => get("overall", q.field) !== "");
}

// --- rendering ------------------------------------------------------------
const CLIP_BY_ID = {};
PACKAGE.clips.forEach(clip => { CLIP_BY_ID[clip.clip] = clip; });

function clipCard(clip, position, total) {
  const pulse = PACKAGE.pulse_question;
  const body = `<div class="cliphead"><span class="tag">${clip.clip}</span>
      <span class="small">clip ${position} of ${total}</span></div>
    <div class="q"><audio controls preload="none" src="${clip.audio}"></audio></div>` +
    PACKAGE.clip_scales.map(s => scaleRow(clip.clip, s.field, s.question, s.labels)).join("") +
    choiceRow(clip.clip, pulse.field, pulse.question,
      pulse.choices.map(c => c.value), pulse.choices.map(c => c.label)) +
    commentRow(clip.clip, "comment", "Comment (optional)");
  return `<div class="card" id="${clip.clip}">${body}</div>`;
}

function scoreBlock(entry) {
  const ids = entry.clips;
  const body = `<h3>${entry.heading}</h3>
    <p class="small">All four clips in this block are <strong>${entry.description}</strong>.
    Compare them against each other, then answer the two questions at the bottom of the block.</p>` +
    ids.map((id, index) => clipCard(CLIP_BY_ID[id], index + 1, ids.length)).join("") +
    `<div class="card" id="${entry.score}">
      <div class="cliphead"><span class="tag">${entry.score}</span>
        <span class="small">your verdict on this score</span></div>` +
    PACKAGE.preference_questions.map(q => choiceRow(
      entry.score, q.field, q.question, ids.concat(["none"]), ids.concat(["none of them"])
    )).join("") +
    commentRow(entry.score, "comment", "Comment on this score (optional)") +
    `</div>`;
  return body;
}

document.getElementById("scores").innerHTML = PACKAGE.scores.map(scoreBlock).join("");
document.getElementById("overallQuestions").innerHTML =
  PACKAGE.overall_questions.map(q => choiceRow("overall", q.field, q.question, q.labels, q.labels))
    .join("");
document.getElementById("listener").value = String(meta.listener ?? "");
document.getElementById("overallComment").value = String(meta.comment ?? "");

function refresh() {
  const total = PACKAGE.clips.length;
  const done = PACKAGE.clips.filter(clip => clipDone(clip.clip)).length;
  const prefs = PACKAGE.scores.filter(entry => scoreDone(entry.score)).length;
  document.getElementById("progress").textContent =
    `Progress \u2014 ${done}/${total} clips rated, ${prefs}/${PACKAGE.scores.length} scores judged, ` +
    `whole-set questions ${overallDone() ? "answered" : "not answered yet"} ` +
    `(answers are saved in this browser)`;
  PACKAGE.clips.forEach(clip => {
    const card = document.getElementById(clip.clip);
    if (card) { card.className = "card" + (clipDone(clip.clip) ? " done" : ""); }
  });
  PACKAGE.scores.forEach(entry => {
    const card = document.getElementById(entry.score);
    if (card) { card.className = "card" + (scoreDone(entry.score) ? " done" : ""); }
  });
  const overall = document.getElementById("overall");
  if (overall) { overall.className = "card" + (overallDone() ? " done" : ""); }
}

// --- download -------------------------------------------------------------
function stamp() {
  return (listener() || "anonymous").replace(/[^A-Za-z0-9._-]+/g, "_");
}

function downloadClips() {
  // The header and every row come from the same field list, so they cannot fall out of step.
  function value(clip, field) {
    if (field === "listener") { return listener(); }
    if (field === "clip") { return clip.clip; }
    if (field === "score") { return clip.score; }
    return get(clip.clip, field);
  }
  const rows = PACKAGE.clips.map(clip => PACKAGE.clip_fields.map(f => value(clip, f)));
  download(`evaluation_experiment27_clips__${stamp()}.csv`, PACKAGE.clip_fields, rows);
  document.getElementById("downloadState").textContent =
    "Clip ratings downloaded. Now download the summary CSV too.";
}

function downloadSummary() {
  function value(field) {
    if (field === "listener") { return listener(); }
    if (field === "comment") { return String(meta.comment ?? ""); }
    if (PACKAGE.overall_questions.some(q => q.field === field)) {
      return get("overall", field);
    }
    for (const entry of PACKAGE.scores) {
      for (const q of PACKAGE.preference_questions) {
        if (field === `${entry.score}_${q.field}`) { return get(entry.score, q.field); }
      }
      if (field === `${entry.score}_comment`) { return get(entry.score, "comment"); }
    }
    return "";
  }
  const row = PACKAGE.summary_fields.map(value);
  download(`evaluation_experiment27_summary__${stamp()}.csv`, PACKAGE.summary_fields, [row]);
  document.getElementById("downloadState").textContent =
    "Summary downloaded. Both files are complete.";
}

refresh();
</script>
</body>
</html>
"""


def render_page(package: Dict[str, Any]) -> str:
    """The page, with the package embedded and no variant name anywhere in it."""
    embedded = json.dumps(package, sort_keys=True, ensure_ascii=False)
    page = (_PAGE_HEAD + _PAGE_SCRIPT).replace("__PACKAGE__", embedded)
    return page.replace("__TITLE__", package["title"])


def build_manifest(clips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The answer key and the machine record. Deliberately kept out of the page."""
    experiment = json.loads(
        (EXPERIMENT_DIR / "summary.json").read_text(encoding="utf-8")
    ) if (EXPERIMENT_DIR / "summary.json").is_file() else {}
    return {
        "experiment": "experiment27",
        "manifest_version": 1,
        "private": True,
        "warning": (
            "this is the answer key: clip -> variant. Do not open it while listening, and do not "
            "read README.md either until the answers are downloaded"
        ),
        "seed": SEED,
        "blinding": {
            "method": (
                "the four variants are shuffled inside each score with a seeded RNG and renamed "
                "clip_NN; the page and both CSVs carry the clip id only"
            ),
            "unblind_with": "the 'clips' list below, field 'variant'",
            "reseed_warning": (
                "changing SEED renumbers every clip and invalidates any answer already collected"
            ),
        },
        "clips": clips,
        "scores": {
            score: {"heading": SCORE_HEADINGS[score], "description": SCORE_DESCRIPTIONS[score]}
            for score in SCORE_ORDER
        },
        "variants": experiment.get("variants", {}),
        "level_policy": experiment.get("level_policy", {}),
        "limitations": experiment.get("limitations", []),
        "questions": {
            "clip_scales": CLIP_SCALES,
            "clip_pulse": CLIP_PULSE_QUESTION,
            "preference": PREFERENCE_QUESTIONS,
            "overall": OVERALL_QUESTIONS,
            "note": (
                "the page renders exactly these declarations, so a CSV column can be read against "
                "this manifest without guessing what a number meant"
            ),
        },
        "csv_templates": {
            "clips": {"file": CLIPS_CSV, "fields": list(CLIP_FIELDS)},
            "summary": {"file": SUMMARY_CSV, "fields": list(SUMMARY_FIELDS)},
        },
        "downloaded_columns": {
            "clips": {
                "listener": "free text entered on the page",
                "clip": "the blinded clip id",
                "score": "note | phrase | phrase_low",
                "musical_usefulness_1_5": "1 = no, 5 = yes, definitely",
                "character_interest_1_5": "1 = dull, 5 = striking",
                "pulse_reads_as": "deliberate | a fault | no clear movement | unsure",
                "annoyance_1_5": "1 = not at all, 5 = very",
                "comment": "free text",
            },
            "summary": {
                "listener": "free text entered on the page",
                "<score>_best_clip": "the clip id preferred for that score, or 'none'",
                "<score>_least_usable_clip": "the clip id found least usable, or 'none'",
                "<score>_comment": "free text",
                "slower_pulse_better": "yes | no | no clear difference",
                "onset_only_better": "yes | no | no clear difference",
                "alternating_notes_deliberate": "yes | no | can't tell",
                "low_register_works": "five ordered options, see questions.overall",
                "worth_developing": "yes | maybe | no",
                "comment": "free text",
            },
        },
    }


def write_manifest(clips: List[Dict[str, Any]], listening_dir: Path) -> Path:
    path = Path(listening_dir) / "manifest.json"
    path.write_text(
        json.dumps(build_manifest(clips), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_templates(listening_dir: Path) -> List[Path]:
    """The empty answer templates, with the same headers the page downloads."""
    listening_dir = Path(listening_dir)
    written: List[Path] = []
    for name, fields, rows in (
        (CLIPS_CSV, CLIP_FIELDS, [[row["clip"], row["score"]] for row in build_mapping()]),
        (SUMMARY_CSV, SUMMARY_FIELDS, [[]]),
    ):
        path = listening_dir / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            for row in rows:
                if name == CLIPS_CSV:
                    filled = dict.fromkeys(fields, "")
                    filled["clip"], filled["score"] = row[0], row[1]
                    writer.writerow([filled[field] for field in fields])
                else:
                    writer.writerow([""] * len(fields))
        written.append(path)
    return written


def build_readme(clips: List[Dict[str, Any]]) -> str:
    """The listener-facing instructions, written next to the page."""
    variant_lines = [
        f"* **{variant}** {e27.VARIANT_NAMES[variant]} — {e27.VARIANT_DESCRIPTIONS[variant]}"
        for variant in e27.VARIANT_ORDER
    ]
    lines: List[str] = [
        "# Experiment 27 — listening test",
        "",
        "Four ways of using one POKEY mechanism: the channel's divider switching between a note and",
        "its octave while the note sounds. Twelve clips, all sharing the same notes, pitches,",
        "durations, generator, volume shape, channel, clock, renderer and gain. Only the *pattern of",
        "the switch* differs.",
        "",
        "## How to run it",
        "",
        "1. Open **`index.html`** in a browser. That is the only file a listener needs.",
        "2. Listen to the twelve clips and answer the questions. Answers are saved in the browser, so",
        "   a session can be interrupted and resumed.",
        "3. At the bottom, press **Download the clip ratings CSV** and **Download the summary CSV**,",
        "   and put both files back in this folder.",
        "",
        "Nothing is uploaded anywhere. Everything stays in the browser until you download it.",
        "",
        "If the browser refuses to play local audio, serve the folder instead:",
        "",
        "```bash",
        "python -m http.server 8733 --directory experiments/experiment27/listening",
        "```",
        "",
        "then open <http://localhost:8733/>.",
        "",
        "## What is in here",
        "",
        "| file | what it is |",
        "| :--- | :--- |",
        "| `index.html` | the listening interface — **the only file you need to open** |",
        "| `audio/clip_NN.wav` | the twelve clips under blinded names |",
        f"| `{CLIPS_CSV}` | the empty per-clip answer template |",
        f"| `{SUMMARY_CSV}` | the empty per-listener answer template |",
        "| `manifest.json` | the answer key (clip → variant) and the machine record — **do not open it while listening** |",
        "",
        "Do not open `manifest.json` until the answers are downloaded: it maps every clip to its",
        "variant, and knowing that would bias the ratings. The rest of this file is safe to read.",
        "",
        "## What is asked",
        "",
        "For each of the twelve clips: could you use the sound in a game tune (1–5), how interesting",
        "is the timbre (1–5), how irritating is it (1–5), whether the movement inside the note reads",
        "as deliberate or as a fault, and an optional comment.",
        "",
        "For each of the three scores: which of its four clips you would actually use, which is the",
        "least usable, and an optional comment.",
        "",
        "Once for the whole set: whether a slower pulse is more usable than the fastest one, whether",
        "confining the movement to the start of the note is better than a continuous one, whether",
        "alternating the movement between notes sounds deliberate, whether the effect still works an",
        "octave lower, whether the timbre is worth developing, and an optional comment.",
        "",
        "There are no right answers. If a clip sounds like a fault rather than an instrument, saying",
        "so is a useful result.",
        "",
        "## What the four variants are",
        "",
        "The questions on the page already describe what each variant does, so this is a summary",
        "rather than a secret. What is withheld is **which clip is which** — that is in",
        "`manifest.json`.",
        "",
        *variant_lines,
        "",
        "The four differ only in the pulse schedule:",
        "",
        "| variant | hold per value | active for | active on |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for variant in e27.VARIANT_ORDER:
        schedule = e27.SCHEDULES[variant]
        active_frames = schedule.active_frames
        active_notes = schedule.active_notes
        lines.append(
            f"| {variant} {e27.VARIANT_NAMES[variant]} | {schedule.hold_frames} frame(s) | "
            f"{'whole note' if active_frames is None else str(active_frames) + ' frames'} | "
            f"{'every note' if not active_notes else ', '.join(str(n) for n in active_notes)} |"
        )
    lines += [
        "",
        "## How the blinding works",
        "",
        "The four variants are shuffled inside each score with a fixed seed and copied to",
        "`audio/clip_NN.wav`. The page and both CSVs carry the clip id only, so the labels cannot leak",
        "into the answers. `manifest.json` holds the mapping; join the downloaded CSV to it on the",
        "`clip` column to get the variant names back.",
        "",
        "The WAVs themselves are copies of the delivered Experiment 27 files — nothing is re-rendered",
        "here, so this page cannot drift away from the artefact set.",
        "",
    ]
    return "\n".join(lines)


def write_readme(clips: List[Dict[str, Any]], listening_dir: Path) -> Path:
    path = Path(listening_dir) / "README.md"
    path.write_text(build_readme(clips), encoding="utf-8")
    return path


def build(output_dir: Path = LISTENING_DIR) -> Dict[str, Any]:
    """Build every file of the listening package and return what was written.

    The target directory is a parameter rather than module state, so a build into a temporary
    directory cannot disturb the delivered package and two builds cannot interfere.
    """
    listening_dir = Path(output_dir)
    listening_dir.mkdir(parents=True, exist_ok=True)

    clips = build_mapping()
    page_path = listening_dir / "index.html"
    page_path.write_text(render_page(build_package(clips)), encoding="utf-8")
    return {
        "clips": clips,
        "audio": write_audio(clips, listening_dir / "audio"),
        "page": page_path,
        "manifest": write_manifest(clips, listening_dir),
        "templates": write_templates(listening_dir),
        "readme": write_readme(clips, listening_dir),
    }


def main() -> int:
    result = build()
    print(f"page:     {result['page']}")
    print(f"manifest: {result['manifest']}")
    print(f"readme:   {result['readme']}")
    for path in result["templates"]:
        print(f"template: {path}")
    print(f"audio:    {len(result['audio'])} clips in {LISTENING_DIR / 'audio'}")
    for row in result["clips"]:
        print(f"  {row['clip']}  {row['score']:11s} -> {row['variant']} ({row['variant_name']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





