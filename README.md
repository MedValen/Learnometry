# Learnometry

A study tool for medical coursework that shapes itself around one person's
cognitive profile. Drop lecture files in; get material, questions, and
explanations routed through the channels that actually work for whoever is
signed in.

It was built around a WAIS-5 / D-KEFS profile, and an example profile of that
shape is the worked example the rest of the reasoning hangs off. You get the
same treatment from your own report, or from the app's own screener. No real
evaluation is reproduced anywhere in this repository.

## Where the name came from

The app used to be called **Symbol Span**, after the WAIS-5 visual
working-memory subtest. In the example profile below, Symbol Span comes back
at **11 — comfortably average** — while auditory working memory sits at the
**7th percentile**. That gap, inside the same person, is the most actionable
finding in such a report, and it is why everything here is visual first.

The name changed because the app is no longer about one subtest, or one person.
The measuring is still the point: it finds where your channels differ and routes
material down the wide one.

## The design contract

Every prompt this app sends carries a table like the one below. It lives in
`backend/learner_profile.py`, generated from whatever scores are on file, so the
pedagogy is auditable and editable rather than scattered through the code. You
can read the exact text under **Profile → See what the app tells Claude**.

This is the table for the example profile used throughout this README. The
numbers are illustrative, not anyone's real results:

| Finding | Score | What the app does |
|---|---|---|
| Visual working memory intact | Symbol Span = 11 | Every concept ships with a table, arrow chain, or grid |
| Auditory working memory very low | WMI 80 / AWMI-R 78 | Max 3–4 elements on screen; one question per screen |
| Registration itself reduced | Digits Forward = 6 | Premises restated *inside* every item; instruction bar always visible |
| Reasoning intact | VCI 106 / FRI 101 | Full Step-1 difficulty. Load is simplified, level never is |
| Switching is a strength | Inhibition/Switching = 12 | Interleaving and look-alike discrimination items |
| Naming is slow (+ ESL) | Color Naming = 6 | Recognition → cued recall → free recall. Generous answer matching |
| Formal accommodations | Extended time, low distraction | Nothing timed, no urgency language, no ambient motion |

Every row is derived from a score that is actually present. A report with three
numbers in it produces three rows. Nothing is filled in by assumption, because a
row here is a claim about a real person's cognition, and an invented one would
be worse than a blank.

## Who it's for

More than one person can use the same install. Each has a name, an optional
photo, and their own profile; switching people switches the contract, the
Profile screen, and every prompt from that moment on.

A profile arrives one of three ways:

| Source | What it is | How much it's trusted |
|---|---|---|
| **Report** | Scores typed in from a real neuropsychological evaluation | Best evidence there is. Stated as measured fact |
| **Screener** | Four short in-app tasks, about 15 minutes | Stated as a working preference, never as a measured fact |
| **None** | Nothing entered | The app runs on its general principles and invents nothing about you |

Study history is shared across everyone on the install, and deleting a person
never deletes answers.

### The screener is not a WAIS-5

The WAIS-5 is Pearson's copyrighted instrument, restricted to qualified
administrators, and self-administering it in a browser would produce invalid
scores even if reproducing the items were legal. It isn't, so this doesn't.

What the screener does instead is compare **your own results against each
other**: a visual span task against a spoken one, how fast a known word arrives,
and what a rule change costs you. It produces no IQ, no percentile, and no
comparison to any norm — only sentences like *"your visual span ran 5 items
longer than your spoken span (8 vs 3)"*, and the app settings that follow from
that. If you have a real evaluation, entering it is strictly better.

## Which model runs what

Not every call needs the same model, and the split is a pedagogical decision
rather than a performance one. It lives in one table in `backend/claude.py`.

**`claude-opus-5` — the teaching model.** Everything that decides *what she
learns*. A wrong call at this layer teaches her something false and she has no
way to know.

| Call | Why it stays |
|---|---|
| `generate.analyze` | decides what the concepts even are, and everything downstream is about them |
| `generate.questions` | the items themselves — the highest-stakes output in the app |
| `generate.study_sheet` | the one-screen table *is* the accommodation |
| `generate.review` | reading a session back to her |
| `notes.critique` | judging her own work |
| `coach.send` | open-ended reasoning about an exam |
| `vault.analyse` | reading her handwriting and whiteboard photos |

**`claude-sonnet-5` — the mechanical model.** These take material Opus has
already reasoned about and move it into a different shape against a fixed
schema. The judgement has happened by the time they run.

`anki.build_cards` · `book.extract_section` · `coach.link_note` ·
`planner.strategy` · `resources.find` · `tactics.explain`

**`claude-haiku-4-5` — the key test.** Proving a key authenticates does not need
a frontier model to say "hi".

Two properties are enforced by tests:

- **Demotion is opt-in.** An untagged call, or a task name the table doesn't
  recognise, stays on Opus. A new call site has to ask for the cheaper path.
- **The split is pinned.** `tests/test_account.py` scans every `claude.call`
  site and asserts which tier it lands on. Moving `generate.questions` to save
  tokens breaks a test rather than quietly changing what she is taught.

Override any tier without touching code:

    LEARNOMETRY_MODEL=claude-opus-5
    LEARNOMETRY_MODEL_MECHANICAL=claude-sonnet-5
    LEARNOMETRY_MODEL_TRIVIAL=claude-haiku-4-5-20251001

Setting `LEARNOMETRY_MODEL_MECHANICAL` to the same value as `LEARNOMETRY_MODEL`
puts the whole app back on one model.

## Setup

1. Get an API key: https://console.anthropic.com/settings/keys
2. Either paste it under **Profile → API keys**, or copy `.env.example` to
   `.env` and put it there.
3. Double-click **`run.bat`**, or run `python install.py` once to get a desktop
   and Start Menu shortcut that opens it in its own window.

First run builds a virtualenv and installs dependencies (a minute or two).
After that it starts in a few seconds.

Most of the app works with no key at all: practice, scheduling, mastery, the
vault, the pinboard, plans, drills, and the offline half of the note check.
Generation, the written critique, and the exam chat need one.

### More than one key

Keys are a list, not a value, and they are tried in order.

- **Priority** decides which goes first.
- A key that is **out of credit or rate-limited** is set aside for 15 minutes
  and the next one is tried *inside the same request* — you don't lose a
  question set at eleven at night because a balance hit zero.
- A key that is **actually invalid** is switched off, because retrying a bad key
  on every call only makes everything slower.
- **Test** sends the smallest possible real call, so you find out a key is wrong
  when you paste it rather than mid-session.

Keys live in the local database in plain text, the same way a `.env` file holds
one. The browser only ever sees a masked hint.

### Donations

The Support page carries the addresses in `backend/support.py`. If you fork this
and want it pointing at your own, copy `support.example.json` to
`data/support.json` and fill it in — that file overrides everything in the
source, and `data/` is not in version control, so your addresses stay on your
machine. Blank them all and the page says so rather than rendering an empty box.

Every address is checked before it is displayed. Bech32 (BIP-173) and
base58check are verified in full, so a single mistyped character fails. Ethereum
is length- and charset-checked, plus EIP-55 when the address carries mixed case.
Solana has no checksum to verify at all, and the UI says so rather than implying
a guarantee it cannot give. An address that fails is reported, never quietly
shown — these are usually transcribed by hand from a wallet app, and a wrong
character sends money somewhere unrecoverable.

## Using it

The app has five destinations: **Home** (what to study next), **Study**
(practice, drills, the study sheet, outside material), **Library** (every file
you have added, plus images and the pinboard), **Mastery** (overview, topics,
weaknesses, learning patterns) and **Plan** (terms, exams, readiness). Your
account, progress, the screener, settings and help live behind the avatar in
the top right.

**Library** — drop lecture files (PDF, DOCX, PPTX, TXT, MD, images). PDFs are
sent whole so the diagrams and tables survive; everything else is text-extracted.

Hit **Read the material**. You get:

- a one-screen orientation table for the whole topic
- a concept inventory, each tagged with its yield, its working-memory trap, and
  what it's most confusable with
- flags for anything ambiguous or at odds with standard teaching

**How many questions.** The count isn't a slider you guess at. Each concept
earns items by yield — high 3, medium 2, low 1 — so the total falls out of what
the material actually contains. The arithmetic is shown, and you can override it.

**Practice** — one question per screen. Five item types, chosen per concept:

| Type | What it does | Why it's there |
|---|---|---|
| `recognition` | pick the answer | lowest word-finding demand — rung 1 |
| `cued_recall` | type it, cue available | rung 2, bridges the naming weakness |
| `application` | vignette → reason it out | plays to FRI 101 |
| `discrimination` | two look-alikes, one difference | plays to Inhibition/Switching 12 |
| `visual_map` | complete the table | plays to Symbol Span 11 |

Every item carries a required visual, a *why* for **every** option (right and
wrong), a `derive_from` that lets her rebuild the fact from mechanism instead of
storing it, and a visual/spatial memory hook.

**Scoring is three-way, not two-way:**

- *knew it*
- *knew it, needed the word*
- *didn't know it*

That middle column exists because a two-way score would fold slow lexical
retrieval into "doesn't know the material." For this profile those are different
events with different fixes, and blurring them systematically under-reports what
she knows.

**Study sheet** — a one-page, tables-only sheet to keep open while working. This
is the externalized working memory for the topic.

**Find videos** — live web search, ranked on two axes: what SGU students actually
rate highly, **and** whether the format carries information visually. A five-star
audio-only podcast is still the wrong resource here, and the app says so
directly instead of just listing what's popular. Ratings and review counts come
with citations; nothing about popularity is asserted from the model's memory.

## What's under the hood

| File | Job |
|---|---|
| `backend/learner_profile.py` | the scores, and the design contract built from them |
| `backend/ingest.py` | file → Files API upload (PDF) or extracted text |
| `backend/claude.py` | SDK wrapper: streaming, structured output, graceful beta degradation |
| `backend/generate.py` | analyze pass, question pass, study sheet, post-quiz review |
| `backend/resources.py` | two-axis resource search |
| `backend/app.py` | local server, `127.0.0.1` only |
| `frontend/` | vanilla HTML/CSS/JS, no dependencies |

Model: `claude-opus-5` with adaptive thinking at high effort. Structured outputs
enforce the item schema, so a question can't come back missing its visual or its
per-option explanations. Prompt caching keeps the repeat calls cheap — the course
material and the profile prompt are identical across every request in a session.

## Notes

- Runs on `127.0.0.1` only. Files stay on this machine apart from the content
  sent to the Anthropic API to generate material.
- Uploads are forgotten when the server restarts; saved sessions persist in
  `data/sessions/`.
- Files over ~600k characters are refused rather than silently truncated — half
  a lecture quietly dropped would produce a question set that looks complete and
  isn't.
- This produces study material about medicine. It isn't medical advice and
  doesn't diagnose anyone.

---

# Phase 1 — Foundation (shipped)

The app now has memory. Concepts survive sessions, every answer is kept, and
mastery is computed from history rather than from the current quiz.

Full architecture, formulas, and the phase plan: [docs/architecture.html](docs/architecture.html)

## What changed

| File | |
|---|---|
| `backend/db.py` | SQLite schema — every table for all 8 phases declared up front |
| `backend/taxonomy.py` | 97-node topic tree mirroring First Aid; stable concept slugs |
| `backend/mastery.py` | Mastery, retention, decay. Pure functions, no I/O |
| `backend/bank.py` | Durable question bank, attempt recording, mastery refresh |
| `backend/routes_study.py` | Bank, attempt, session, mastery, heatmap, weakest routes |
| `backend/generate.py` | Difficulty extended to L1–L4; added `key_clue` and `takeaway` |
| `backend/app.py` | Boots the DB, seeds the taxonomy, mounts the router |

Nothing was removed. The existing generate → quiz flow works exactly as before.

## Running the tests

```bash
.venv\Scripts\python.exe tests\test_mastery.py
```

```bash
.venv\Scripts\python.exe tests\test_persistence.py
```

43 checks, no external dependencies, no API key needed. `test_mastery.py` asserts
the design's *properties* rather than specific decimals, so the formula can be
tuned without rewriting the suite — but cannot quietly lose a guarantee.

One test exists purely to enforce a clinical constraint:
`test_response_time_never_changes_mastery`. Naming speed in this profile is
at the 9th percentile. If a future change lets speed influence mastery, that
test fails.

## The three numbers

Mastery is never collapsed into one percentage:

- **mastery** — how well she knows it, from recency-weighted credit
- **retention** — how likely that's still true, decaying since last review
- **estimateConfidence** — how sure *the system* is, from effective sample size

A concept can read `mastery 0.91 / retention 0.62 / review due`.

## Known behavior to decide in Phase 2

A topic's rolled-up mastery averages in concepts with **zero attempts** at the
0.35 prior, so an organ system cannot go green until every concept under it has
been practiced. That is arguably correct for a mastery map, but it makes early
topics look worse than they are. Revisit when the heatmap lands.

## API added

```
POST /api/bank/save              analysis + questions -> durable concepts
GET  /api/bank/stats             counts
POST /api/attempt                record an answer, returns before/after mastery
POST /api/session/start | end    session envelope + summary
GET  /api/mastery/concept/{id}   three numbers, difficulty gap, related concepts
GET  /api/mastery/map            topic tree with rolled-up bands (heatmap)
GET  /api/mastery/weakest        high-yield weaknesses, priority-ranked
GET  /api/mastery/rebuild        recompute all mastery from history
GET  /api/topics                 the taxonomy
```

---

# Phase 2 — Weakness targeting (shipped)

The engine now picks the questions. Practice opens on a launcher (length ×
mode), not on a fixed set you walked through in order.

| File | |
|---|---|
| `backend/scheduler.py` | priority, session composition, variant rotation, SM-2. Pure functions |
| `backend/bank.py` | `candidates()` / `select_session()` bridge the DB to the selector |
| `backend/routes_study.py` | `/api/select`, `/api/select/modes`, `/api/plan/today` |
| `frontend/` | session launcher, mastery map with drill-down, three-number concept view |

## How a question gets chosen

```
priority = weakness^1.5 × yield × forgettingRisk × examRelevance × difficultyGap
```

Priority ranks concepts; it does not pick them. Seven overlapping buckets get
quotas per mode, picks inside each are softmax-sampled (τ=0.35), and a concept
can't return within 6 items. Two sessions on the same data are related, not
identical.

**Variant rotation** is the Keybr property: a weak concept comes back as
anatomy, then localization, then a vignette — never the same stem twice. Once a
concept passes 0.60 the engine serves the hardest variant available.

## The mastery ceiling

Each practice level caps how high mastery can go:

| Sustained practice at | Ceiling | Reaches mastered? |
|---|---|---|
| Level 1, confident | 0.567 | No |
| Level 2, unsure | 0.600 | No |
| Level 3, confident | 0.915 | Yes |
| Level 4, confident | 1.000 | Yes |

**You cannot master a concept by answering recall questions about it**, however
many you answer. That's why difficulty is tracked separately from mastery, and
why the engine escalates.

## Tests

```bash
.venv\Scripts\python.exe tests\test_scheduler.py
```

79 checks across the three suites. Four exist to pin bugs found during Phase 2:

- `test_mastered_is_actually_reachable` — dark green was mathematically
  unreachable; sustained perfect Level 3 topped out at 0.793 against a 0.85
  threshold. Fixed by giving recency and sample-size separate denominators.
- `test_buckets_overlap_rather_than_partition` — an exclusive bucket rule let
  "recently missed" swallow every other category after any session with wrong
  answers.
- `test_all_recently_missed_still_composes_a_full_session` — a 10-question
  session was silently delivering 8.
- `test_alternating_weak_reads_red_not_yellow` — 50% alternating is weak, not
  merely "inconsistent".

## Session modes

`mixed` · `weak_areas` · `high_yield` · `spaced` · `exam_cram` · `new_material`
· `endless` — each reweights the same quota machinery rather than running its
own code path.

---

# Phase 3 — Her own layer (shipped)

Five surfaces that are hers rather than the engine's: a filing system, a place
for photos, a pinboard, a record of what she was told, and time-boxed plans.

| File | |
|---|---|
| `backend/organizer.py` | terms, courses, exams, exam readiness |
| `backend/vault.py` | photo/file storage + optional whiteboard reading |
| `backend/pinboard.py` | pins she controls |
| `backend/coach.py` | instructor emphasis + the conversation over it |
| `backend/planner.py` | time-boxed study plans |
| `backend/routes_org.py` | all Phase 3 routes |
| `backend/db.py` | schema v2 + a migration runner |

## Terms are a second axis, not a second taxonomy

The First Aid tree says what a concept **is**. A term says when she **needs**
it. Exams *reference* topics and concepts and never own them — otherwise
material drilled for the Renal midterm would fork and start from zero when it
reappeared on the final. A parent topic pulls in its whole subtree, so mapping
"Renal / Physiology" to an exam covers everything under it.

Adding an exam immediately changes what practice serves: exam proximity was
already a term in the Phase 2 priority formula.

## Emphasis proposes, she disposes

"Dr. Nassar said acid-base is heavily tested" is often better evidence than any
textbook weighting. But a misheard remark that silently raised a concept's
priority for a month would be very hard to notice and impossible to trace.

So a note records **who said it and how strongly**, Claude suggests which
concepts it points at, and the boost applies only when she confirms it. It
lives in `concept.emphasis_boost` — never folded into `high_yield` — so what
her professor stressed stays separable from what the book says, and undoing it
is exact. Source trust scales it: the same claim from an upperclassman counts
half what it counts from the professor.

Notes save even with no API key. Losing what she wrote down because the API was
down would be the actual failure.

## The whiteboard is evidence, not a photo

A brain dump is a retrieval attempt she already performed. So when she asks the
app to read one, the valuable half of the answer is not what she remembered —
it's what a complete answer would contain that is **absent**. The analysis is
told never to invent errors, and to say plainly when handwriting is illegible
rather than guess.

Storage works offline. Reading an image is opt-in, per image, never on upload.

## Plans that admit what they cannot do

The arithmetic is **computed**; only the strategy is generated.

```
capacity  = study_days x minutes_per_day / 1.0 min per question
priority  = weakness x exam_weight x forgettingRisk x (1.25 if never practised)
questions = 6 if weak · 4 developing · 3 · 2 · 1 if solid
```

Three honesty rules, all enforced by tests:

- **Never schedules more minutes than she said she has.** (This was in the
  docstring before it was in the code — a 3-minute day was emitting a 4-minute
  block until a test caught it.)
- **When time runs out, it names what it dropped.** A plan that silently omits
  half the material looks complete and is worse than useless the night before.
- **When it uses less than half her time, it says why.** A 6-minute day against
  a 45-minute budget is unmapped material, not a scheduling error.

Days are dealt round-robin so topics interleave, the weakest third gets a second
pass at least two days later, and the final day is consolidation only.

**Readiness is not a predicted score.** There's no validation data behind this
app, so a forecast would be invented precision. It reports weighted coverage,
states how many mapped concepts have never been practised, and carries that
caveat in its own payload so no screen can drop it.

## Tests

```bash
.venv\Scripts\python.exe tests\test_organizer.py
```

133 checks across four suites. Notable Phase 3 ones:

- `un-applying restores exactly` / `deleting an applied note removes its boost`
  — emphasis must be fully reversible
- `boost reaches the question selector` — otherwise capturing emphasis is theatre
- `never overruns 3/10/45/120 min per day`
- `plan says when there is more time than material`
- `stored path never leaves the server`

## Schema migrations

`db.py` now carries a migration runner. Upgrading an existing database adds the
new columns in place; **her attempt history is preserved**. Check any time:

```bash
.venv\Scripts\python.exe tools\check_schema.py
```

## API added

```
GET|POST  /api/terms · /api/courses · /api/exams
GET       /api/exams/{id}/readiness      weighted coverage, high-risk list
GET       /api/topic-search              attach topics/concepts to an exam
POST      /api/vault/upload              photos, PDFs, notes
POST      /api/vault/{id}/analyse        read a whiteboard — opt-in
GET|POST  /api/pins
GET|POST  /api/emphasis                  what she was told
POST      /api/emphasis/{id}/apply       confirm (or undo) the priority boost
POST      /api/chats/{id}/send           conversation, loaded with her real state
POST      /api/plan/build                the schedule — computed
POST      /api/plan/strategy             how to work it — generated
```

---

# Phase 4 — Scope filter & drills (shipped)

## Telling the engine what it may serve

Practice used to draw from everything she'd ever studied, so a finished Term 3
exam competed with the block she's actually sitting. The launcher now has a
**Drawing from** panel: filter by term, course, or exam, plus two switches —
*skip material only from exams already sat*, and *include material not attached
to any exam*.

The one thing worth understanding: **narrowing scope suppresses spaced
repetition for everything outside it.** Old material keeps decaying while it's
filtered out. The panel says so rather than hiding it, and the count updates
live as she changes the filter.

A concept sitting on both a finished exam *and* an upcoming one is **not**
treated as previous material — the upcoming exam wins. An impossible filter
serves nothing and explains why, rather than silently falling back to
everything.

| File | |
|---|---|
| `backend/scope.py` | `Scope`, `allowed()`, `describe()`, `options()` |
| `backend/bank.py` | `candidates()` / `select_session()` take a scope |
| `backend/drills.py` | the four drills, all built from her own bank |

## Drills

Four short games under a **Drills** tab, generated from concepts already in her
bank — so **all of it runs offline**, no API key.

| Drill | What it does | Which finding it comes from |
|---|---|---|
| **Sequence** | Items flash in order; she plays the order back. Span adapts up on a clean round, down on a poor one | Symbol Span = 11 vs 7th-percentile auditory span — this is the channel that works |
| **Chunk It** | Break a list of 6–9 into named groups of two or three | AWMI-R 78 makes a bare list of seven unusable; grouping it is the compensation |
| **Odd One Out** | Spot the outsider — and the rule flips every round | Inhibition/Switching = 12, a measured strength, and discrimination is high-yield anyway |
| **Name It** | Produce the term from a description. Never timed, near-misses count, cue on request | Color Naming = 6 — retrieval is slow, not absent |

**What these are, stated honestly.** Evidence that training working memory
itself transfers to real capacity is **weak**, and the app says so on the tab
rather than burying it. These are not a treatment for a 7th-percentile auditory
working memory. What they do instead: practise in the channel that works,
rehearse compensations she can actually use in an exam (chunking, externalising),
build content fluency, and — with Odd One Out — play to a strength. Extended
time and a low-distraction room remain the things that actually help most.

Two design calls follow from that framing:

- **Chunk It is not graded for "correctness".** There are many defensible ways
  to group a list, and marking one right would teach her to guess the app's
  grouping instead of building her own. What's scored is whether every group is
  named and none exceeds three.
- **Drill results never touch mastery.** They live in their own `drill_result`
  table. A drill is a skill exercise, not a knowledge test, and folding its
  scores into the mastery model would corrupt it with a different task. Pace is
  tracked against her own baseline only — never a norm, same rule as `rt_ms`.

## Tests

```bash
.venv\Scripts\python.exe tests\test_scope_drills.py
```

**180 checks across five suites.** Notable new ones:

- `an impossible scope serves nothing rather than everything` — the dangerous
  failure would be silently ignoring the filter
- `concept on an upcoming exam survives the past filter`
- `drills respect the practice filter`
- `a drill never writes to attempt history`
- `describe ignores concepts with no questions` — the count must match what the
  engine can actually serve

## API added

```
GET   /api/scope/options        terms, courses, exams (with a "sat" flag)
POST  /api/scope/describe       what a filter would do, before committing
POST  /api/select               now accepts a `scope` object
POST  /api/drills               which drills are buildable, and why not
POST  /api/drills/build         generate rounds
POST  /api/drills/result        log a run
GET   /api/drills/history       runs, best spans, personal trend
```

---

# Phase 5 — Desktop app, note critique, timer, question tactics

## It's an application now

```bash
.venv\Scripts\python.exe install.py
```

Creates **Start Menu and Desktop shortcuts** with their own icon. Launches via
`pythonw.exe` — no console window, no browser tab, no URL to remember. It opens
in a native window, picks a free port automatically, and closes when she closes
the window.

Nothing is copied: the shortcuts point at this folder, so editing the code
updates the installed app. `python install.py --remove` takes them away.

`python desktop.py` runs the same thing from a terminal. If no native webview is
available it opens the default browser and says so, rather than showing a blank
window.

**Where her data lives.** Running from source: `data/` in this folder. Packaged
as an .exe: `%LOCALAPPDATA%\SymbolSpan`, because a frozen executable's own
folder is read-only and its extraction directory is temporary — the wrong place
for the only copy of her study history.

## Note check

Paste notes on the **Notes** tab. Two layers:

**Measured, offline.** Word count, words per line, average sentence length,
longest unbroken list, table presence, headings. Arithmetic over her actual
text — no API key, and the numbers are shown so she can check them.

**Judged, with Claude.** What to change, quoting her own text, plus a **rewrite
of one passage** in the better shape. That rewrite is the most useful part; the
rest is diagnosis.

Grounded in Dunlosky et al. (2013), which rated study techniques by utility:
practice testing and distributed practice **high**; elaborative interrogation,
self-explanation, interleaving **moderate**; summarisation, highlighting,
rereading **low**. Every flag states its basis so she can see which claims are
strong and which are just practical.

**Two things the app deliberately will not say:**

- *Write by hand instead of typing.* The laptop-vs-longhand result (Mueller &
  Oppenheimer 2014) has not replicated cleanly. Stating it as fact would be
  passing off a contested finding.
- *You're a visual learner.* Learning styles have no support. The reason to
  route visually is a measured ~1.8 SD gap between one person's Symbol Span and
  her auditory span — a fact about her, not a personality type.

Every quote in the critique is checked against her text verbatim. One that
doesn't match is flagged in the UI rather than shown as fact.

## Timer

Off by default, on the Practice launcher. Presets: **no timer**, **double time
(180s)**, **time and a half (135s)**, **standard NBME (90s)**.

It **counts up toward a limit and never cuts her off.** Going over turns the bar
amber and says "over the limit — keep going". Verified: past the limit, nothing
is graded, submit is still offered, the input is still editable.

That's deliberate. Extended time is a formal accommodation, so a hard cut-off
would defeat the point of practising. Elapsed time is stored and never enters
the mastery formula — the same rule that keeps `rt_ms` out of it.

## Reading the question

**"Break down the question"** on any item splits the stem into:

| Role | Means |
|---|---|
| **the ask** | the actual question — almost always the last line |
| **narrows it** | carries who / when / numbers |
| **background** | context, read it second |
| **skim** | setup with nothing discriminating in it |

Runs on pattern-matching alone, no API key. It also detects **negated stems**
(NOT / EXCEPT / LEAST) and says so loudly — that's the most common way to lose a
question you knew. Classification is deliberately conservative: when unsure a
line is called *background*, never *skim*, because telling her to ignore a line
that mattered is much worse than leaving one unclassified.

A six-item **playbook** sits on the Profile tab — read the last line first,
answer before looking at the options, three things narrow every vignette, write
the numbers down, watch for the flip, long stem ≠ hard question. Each says
whether it's a research finding, standard strategy, or just practical. Most are
practical, and it says so.

## Tests

```bash
.venv\Scripts\python.exe tests\test_notes_tactics.py
```

**228 checks across six suites.** Notable:

- `no flag cites laptop-vs-longhand` — pins the honesty constraint in code
- `a two-line wall of text still flags over-writing` — regression: the guard was
  on line count, so the worst case (three enormous paragraph-lines) slipped past
- `timed guidance promises no cut-off`
- `missing API key does not lose the review`
- `roles are drawn from the known set` / `exactly one line is the ask`

## API added

```
POST /api/notes/review        measure + critique
POST /api/notes/{id}/critique run the critique separately
GET  /api/notes               history with a words-per-line trend
POST /api/tactics/dissect     split a stem — offline
POST /api/tactics/explain     Claude's read of one stored question
GET  /api/tactics/playbook    reading strategy + timer presets
POST /api/tactics/timing      what a chosen timer setting means
```

---

# Phase 6 — Per-question markup, notes moved into Profile

## "Break down the question" is now about *that* question

The dissector went from line-level roles to **inline coloured marks over the
actual phrases**, plus advice generated from what was found in that specific
stem.

| Mark | Colour | Means |
|---|---|---|
| **flips the question** | red | NOT / EXCEPT / LEAST — read it again |
| **number — write it down** | green | a lab, vital, or dose |
| **timing** | blue | onset, duration, acute vs chronic |
| **who** | purple | age, sex |
| **finding** | amber | what the examination showed |
| **background** | grey | history, meds, social |
| **skim** | struck through | setup phrasing with nothing discriminating |

Hovering any mark names what it is. The legend only shows kinds actually
present in that stem.

**The advice is conditional, not a template.** A stem with no numbers is told
*"No lab values at all — this is a pattern-recognition item"*; a stem with four
is told to put them in a column because holding them is the expensive part at
Digits Forward = 6. A lean stem is never lectured about padding it doesn't
have. A negated stem gets the warning first, before anything else.

Everything runs offline — no API key.

## Note check moved into Profile

The Notes tab is gone; the tab bar is down from 11 to 10. The note check is now
a collapsed section on **Profile**, with three sources:

- **Paste text** — as before
- **From the vault** — pick a document already saved. Text files are read
  offline; images say so and point at the vault's own "Read it"
- **Upload a file** — DOCX, PPTX, PDF, TXT, MD read straight into a review
  without being stored

Document reading reuses the same extractors as the course-material pipeline, so
a `.docx` of her notes is read exactly the way a `.docx` of a lecture is. A PDF
with no text layer says it's probably a scan and points at the vault rather than
returning an empty review.

## Bugs found

- **Two regex patterns were unmatchable.** A literal backspace character
  (`\x08`) had been baked into the `finding` and `history` patterns, so neither
  ever fired — "Physical examination shows diaphoresis" was being marked *skim*.
- **Vitals were split badly.** `158/94 mm Hg` marked only "94 mm", leaving the
  systolic bare, and `37.0 C` wasn't marked at all. Compound patterns now come
  first so a blood pressure is one value.

## Tests

**247 checks across six suites.** New ones worth naming:

- `segments reassemble to the original line` — the markup can never drop or
  duplicate text
- `marks never overlap`
- `a lean stem is not lectured about padding`
- `a stem with no numbers says so`
- `negated stems get a warning first`
- `images are refused with a pointer to the vault`

## API added

```
GET  /api/notes/sources      vault files that can be read as notes
POST /api/notes/from-asset   critique a document already in the vault
POST /api/notes/upload       critique an uploaded document
```

`POST /api/tactics/dissect` now also returns `segments` per line, a `legend`,
and per-question `advice`.

---

# Phases 4–8 — the rest of the plan (shipped)

## Phase 4 · First Aid ingestion

The book is 849 pages and 257 MB. It is never uploaded. `book.py` walks it with
pypdf on this machine, reads the running header on every page, and maps that
onto the taxonomy.

**Result on the real book: 82 sections, 75 mapped (91%), 94% of pages covered.**
Every organ system splits correctly into Embryology / Anatomy / Physiology /
Pathology / Pharmacology.

Getting there took four separate parsing fixes, because the book uses four
different header shapes:

| Shape | Example | Problem |
|---|---|---|
| standard | ``BIOCHEmISTRY ` BIOCHEMISTRY—MOlECUl AR…`` | header repeats, case scrambled |
| no discipline | `` ` RENAL—EMBRYOLOGY`` | nothing before the backtick — **Renal vanished entirely** |
| no dash | ``Musculoskeletal… ` anatomy and physiology`` | subsection isn't after a dash |
| noisy | ``section iii498 Musculoskeletal…`` | roman numeral runs into the page number |

The key decision: **don't try to reconstruct readable text.** Letter-spacing in
the source turns "MOLECULAR" into "MOlECUl AR" and word boundaries are
unreliable. Reducing both sides to bare letters and matching against the
taxonomy gives a clean path *and* the topic id in one step.

**What's stored:** concept names, topic paths, page ranges, high-yield scores.
**What isn't:** any of the book's prose, tables, figures, or mnemonics. Section
text lives in memory for one extraction call and is discarded. The app cites
into her own copy; it never reproduces it.

High-yield scoring uses three structural signals, no model: presence in First
Aid's own Rapid Review distillation (7 page ranges detected), coverage density,
and cross-system recurrence.

## Phase 5 · Anki export

Not a dump of the question bank — **a multiple-choice item makes a bad
flashcard**, because the options do the remembering for you. What crosses over
is the concept, rewritten as active recall.

Selections: red only · red + orange · today's wrong answers · high-yield
weaknesses · specific concepts. Counts shown live so empty ones are visible.

Three card shapes chosen per concept — `basic`, `cloze`, `clinical` (the last
for concepts with a measured difficulty gap: she can recite it but not apply
it). Every card is previewed and editable before export, and her edits are
re-rendered server-side so they land in the file.

TSV with the specified header. **Works with no API key** — the offline fallback
builds honest basic cards from the concept descriptions the bank already holds.

## Phase 6 · Progression

XP, levels, streaks, 12 achievements, and an organ-system map with boss
challenges. Built to the constraints from the conflict section:

- **Nothing drains.** Bars fill. No countdown, no decaying streak clock.
- **Streaks count correct answers, not consecutive days.** A rest day should
  never erase three weeks.
- **XP follows difficulty and honesty, not speed.** L4 confident = 22 XP,
  L1 guess = 10, a wrong L3 still pays 7. Owning up to a guess pays a bonus,
  because the metacognitive data is worth more than the point difference.
- **Achievements are for things she did**, including *Kept yourself honest*
  (50 answers marked guessed/unsure) and *Brought it back* (a decayed concept
  returned to green).

A boss is only offered once a system is mostly solid — otherwise it's just a
harder version of the work she's avoiding.

## Phase 7 · Learning analytics

Every claim goes through the same gate: **n ≥ 30 per group, effect ≥ 8 points,
p < 0.05**, using a two-proportion z-test implemented in the standard library.
Anything that fails is listed as *pending* with what it's still waiting for,
so she can see what the app is watching rather than wondering why a panel is
empty.

The method is printed on the page, including its limitation: repeated attempts
at the same concept are correlated, so the p-values are optimistic — which is
what the effect-size floor guards against.

Calibration is the most valuable output: *"When you say you knew it, you're
right 76% of the time"* — under about 80% means some of what feels solid is a
misconception rather than a gap, and misconceptions are what to chase first.

## Phase 8 · Polish

- **Thirteen tabs wrapped onto two rows.** Now six primary plus an overflow
  menu — a single 33px row.
- **Keyboard shortcuts**: `1`–`5` pick an option, `Enter` checks then advances,
  `c` opens the cue, `?` breaks down the question, `Esc` backs out. Keycaps
  appear only after she uses a key, so they never clutter for someone who
  clicks. This matters more here than in most apps: the fewer mechanical steps
  between reading and answering, the more of her extended time goes on medicine.
- **Visible focus states** everywhere, since the shortcuts make keyboard use
  likelier.
- **Performance measured, not assumed.** At 1,200 concepts: mastery map 30 ms,
  weakest 20 ms, candidate selection 40 ms. No optimisation needed — the
  mastery cache makes each lookup a single indexed read.
- A dashboard (**Today**) is now the landing surface, naming the single most
  useful next action rather than showing a wall of statistics.

## Tests

```bash
.venv\Scripts\python.exe tests\test_phases_4_7.py
```

**313 checks across seven suites.** The textbook tests run against the real
849-page PDF when it's in Downloads and skip cleanly when it isn't.

Notable:

- `parses a header with nothing before the tick` — the bug that made Renal
  disappear
- `a longer book name still matches by prefix` / `short names don't collide
  across disciplines`
- `offline cards are active recall, not multiple choice`
- `speed is not a term` — pins the XP constraint the same way the mastery
  suite pins it
- `a huge difference on tiny n is not significant`
- `the claim compares her only with herself`

## API added

```
POST /api/book/scan · /api/book/ingest · GET /api/book/sources
GET  /api/anki/selections   POST /api/anki/export · /api/anki/rebuild
GET  /api/game/state · /api/game/map · /api/game/achievements
POST /api/game/boss
GET  /api/analytics
```

---

# After the plan — audit and data safety

With all eight phases shipped, the remaining work was finding what was actually
broken rather than adding more.

## Cold-start audit

Ran every surface against a **completely empty database** — the state a new
user hits, and one that had never been tested end to end.

- All 26 GET endpoints: 200
- All 13 views render with a real empty state, **zero JavaScript errors**
- Every destructive-path POST returns a useful message rather than a stack trace

Three of those messages were leaking Python internals: `str(KeyError("x"))` is
`"'x'"` — quotes included — and that was reaching the UI verbatim as
`'no such exam: nope'`. Now unwrapped.

## Backups

Her answer history is the one thing in the app that **cannot be regenerated**.
Questions can be rewritten, concepts re-extracted, mastery recomputed — a year
of answers is a year of answers, and it was living in a single SQLite file with
no export path.

- **Automatic backup on every start**, last 10 kept, skipped if one was taken in
  the past 6 hours so a restart loop can't churn them
- **SQLite's own `.backup()` API**, not a file copy — copying a database that's
  being written to produces a file that looks fine and is corrupt
- **Restore snapshots the current data first.** Undoing a restore has to be
  possible, or the button is a loaded gun
- **Download the database**, or **export as JSON** — the latter doesn't need
  this app to be readable

Verified end to end: 181 attempts → deleted → restored to 181, safety copy
intact.

Building it surfaced a design smell worth fixing rather than working around:
`backup.py` was deriving the database path from `app.DATA` instead of asking
`db`. Two sources for one fact is how a backup ends up pointing at the wrong
file, so `db.path()` is now the single answer.

## Tests

**324 checks across seven suites.** New:

- `restore snapshots the current data first`
- `json export skips the seeded taxonomy` — it's generated from code, and would
  only bloat the file
- `old backups are pruned`
- `the database downloads as bytes` (checks the SQLite magic header)

---

# Learnometry — more than one person, more than one key

The app got a name that isn't a subtest, and stopped assuming there is only one
of everything: one user, one profile, one API key.

## The profile stopped being a constant

`backend/learner_profile.py` held one real report as module-level constants, and
every prompt read them directly. That was right while there was one person and
wrong the moment there were two.

The report is still there, and it is still the worked example — but it is now
*seeded* into a user row on first run, so the person it was written for keeps
exactly the behaviour she already had while everyone else gets the builder.

    learner_profile.for_user(user)   ->  the full contract for that person
    learner_profile.active()         ->  the cached contract for whoever is signed in
    learner_profile.profile_digest() ->  the same thing, for the Profile screen

The Profile screen used to be static HTML with one person's Symbol Span written into the
markup. Its seven rows are now *derived*:

| Was | Is |
|---|---|
| `"Auditory working memory very low"` hard-coded | emitted when `AWMI-R` or `WMI` is below 85 |
| `"AWMI-R = 78 (7th %ile)"` typed out | percentile computed from the standard score |
| `"Switching is a strength"` always | `"Switching costs her"` below a scaled score of 9, with the opposite rule |
| seven rows, always | one row per score that is actually present |

A test pins all seven of her rows against the regenerated output, including the
percentile, so the generalisation is provably lossless for the case it came
from. A second student with `Symbol Span = 5` and `Inhibition/Switching = 4` gets
"Visual working memory reduced" and "One topic at a time. Blocks, not shuffles."
— the opposite instructions, from the same code.

## The screener

The request was a WAIS-5 for new users. That can't be built: it is Pearson's
copyrighted instrument, restricted to Level C administrators, and a browser
self-administration is invalid even setting the copyright aside.

What is honest, and what got built, is a **within-person screener** — four tasks
compared only against each other:

| Task | What it contrasts |
|---|---|
| Shapes in order | span in the visual channel |
| Words in order | the same span, **read aloud** through `SpeechSynthesis` |
| Name it | how quickly a word you already know arrives |
| Changing rules | accuracy on switch trials vs stay trials |

The visual/spoken pair is the whole point. Presenting one task in two modalities
is what turns "I'm bad at remembering things" into "the spoken channel is the
narrow one" — which is the finding the entire app is built to act on.

Spans adapt: right lengthens, wrong shortens, floor 2, ceiling 9. The result is
sentences with the actual numbers in them:

> Your visual span ran 5 items longer than your spoken span (8 vs 3).
> When the rule changed you were 0% accurate, against 100% when it stayed the same.

and never an IQ, a percentile, or a norm comparison. Tests assert the absence of
all three in the payload, and the disclaimer travels with the result rather than
sitting only on the intro screen. A profile built this way is labelled inside
the prompt as *"a working preference, not a measured fact"*.

**Policy vs finding.** `timed_by_default: false` and `generous_matching: true`
do not wait on a task being completed. They were conditional at first, which
meant skipping the naming task silently bought you the harsher behaviour. Two
tests now hold them true for an empty result.

## API keys are a list

`backend/keys.py`. Priority decides the order; `claude.py` walks the list and
fails over **inside the same request**.

    for key_id, secret in keys.usable():
        try:    ... ; keys.mark_ok(key_id); return
        except: kind = _classify(exc)
                if kind == "request": raise          # bad request fails on every key
                if kind == "invalid":   keys.mark_invalid(key_id, ...)   # switch it off
                else:                   keys.mark_exhausted(key_id, ...) # rest it 15 min

The distinction matters: a 429 or an empty balance is temporary and the key
should come back, while a 401 is permanent and retrying it on every call just
adds latency to everything.

Two bugs worth recording:

- **Priority 0 is falsy.** `MAX(priority) or -1` gave `-1` for a max of `0`, so
  the second key landed on priority 0 alongside the first and the order was
  whatever `created_at` decided.
- **The hint hid the wrong end.** `mask()` showed the first seven characters —
  but every Anthropic key begins `sk-ant-api03-`, so every hint was identical
  and the one job of the hint (telling two keys apart) failed for real keys
  while passing for test ones. It shows the tail now.

**This is the first code in the project that has actually reached the API.**
There has never been a key on this machine, so everything Claude-facing had been
built and tested to its boundary and never executed. The key **Test** button was
run against `api.anthropic.com` with a deliberately malformed key: the SDK
raised, `_classify` returned `invalid`, the key was disabled, and `usable()`
went empty. The failover path is proven for that branch; the success branch
still waits on a real key.

## Identity

Name and optional photo, an identity chip in the header, a switcher, and a
`/profile/preview` endpoint behind **See what the app tells Claude** that prints
the exact system prompt. Nothing about you is hidden from you.

Deleting a person deletes their account and their photo, and deliberately leaves
`attempt` alone — history is shared across the install, and losing a year of it
to a mis-click on the wrong screen is not a recoverable mistake.

## The icon, and one shortcut

`assets/learnometry.ico` and `.png`, wired into the shortcut, the taskbar, and
the pywebview window. `install.py` also retires shortcuts left behind by the old
name — but only after checking each one actually points at this `desktop.py`, so
somebody else's identically-named shortcut is left alone.

## Tests

`tests/test_account.py` — 95 checks. Users, per-user contracts, the screener,
scoring, the digest, and key failover, all offline.

Total across the suite: **419 checks**.

    .venv\Scripts\python.exe tests/test_account.py

## API added

    GET    /api/users                     everyone on this install
    POST   /api/users                     add a person
    GET    /api/users/me                  active user + profile summary + report fields
    POST   /api/users/{id}/active         switch
    PATCH  /api/users/{id}                rename
    DELETE /api/users/{id}                remove the account, keep the history
    POST   /api/users/{id}/photo          upload an avatar
    GET    /api/users/{id}/photo
    DELETE /api/users/{id}/photo
    POST   /api/users/{id}/profile/report enter evaluation scores
    POST   /api/users/{id}/profile/clear
    GET    /api/users/{id}/profile/preview  the exact prompt Claude receives

    GET    /api/screener                  the four tasks + the disclaimer
    POST   /api/screener/start
    POST   /api/screener/build            items for one task
    POST   /api/screener/record           one task's result
    GET    /api/screener/{run}
    POST   /api/screener/{run}/apply      turn a run into a profile

    GET    /api/keys                      masked, with status and cooldowns
    POST   /api/keys
    PATCH  /api/keys/{id}
    DELETE /api/keys/{id}
    POST   /api/keys/order                reprioritise
    POST   /api/keys/wake                 clear all cooldowns
    POST   /api/keys/{id}/test            smallest possible real call

`GET /api/profile` now answers for the active user instead of the constants.
