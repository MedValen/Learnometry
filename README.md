# Learnometry

**Adaptive studying that learns how you learn.**

Learnometry is a local-first study application built for demanding medical coursework. Instead of treating every student the same, it adapts how material is presented, practiced, reviewed, and scheduled based on the learner's own profile and study history.

Import lecture material, generate structured study content, practice with adaptive questions, identify weak areas, track mastery over time, build exam plans, and export targeted weaknesses to Anki.

The goal is simple:

> **Spend more time on what you actually need to learn — in a format that actually works for you.**

---

## What makes Learnometry different?

Most study applications track whether you got a question right or wrong.

Learnometry also asks:

* What concept are you actually weak in?
* Are you forgetting it or did you never master it?
* Can you recall it but struggle to apply it?
* Are certain question formats consistently harder for you?
* Which topics are high-yield for an upcoming exam?
* What material should come back next?
* Does the way information is presented affect your performance?
* How confident should the system be in its conclusions?

The app uses this information to continuously shape future study sessions.

---

## Core Features

### Adaptive Practice

Practice sessions are generated from your existing question bank rather than simply walking through questions in order.

Available modes include:

* Mixed
* Weak Areas
* High Yield
* Spaced Review
* Exam Cram
* New Material
* Endless Practice

The scheduler prioritizes concepts using weakness, yield, forgetting risk, exam relevance, and difficulty gaps.

Weak concepts return more often, but not necessarily with the same question.

A concept may come back as:

* Recognition
* Cued recall
* Application
* Discrimination
* Visual mapping

This helps prevent memorizing the question instead of learning the concept.

---

## Mastery That Means Something

Learnometry does not compress everything into one percentage.

Each concept tracks three separate values:

| Metric                  | Meaning                                      |
| ----------------------- | -------------------------------------------- |
| **Mastery**             | How well you appear to know the concept      |
| **Retention**           | How likely that knowledge is still available |
| **Estimate Confidence** | How confident Learnometry is in its estimate |

For example:

```text
Mastery: 0.91
Retention: 0.62
Status: Review due
```

Difficulty is also tracked independently.

That matters because answering simple recall questions repeatedly cannot produce full mastery. The system eventually requires higher-level application.

---

## Weakness Targeting

Learnometry automatically identifies weaknesses and prioritizes what deserves another attempt.

A simplified version of the concept priority calculation is:

```text
priority =
    weakness^1.5
    × yield
    × forgettingRisk
    × examRelevance
    × difficultyGap
```

Priority determines what deserves attention.

Session composition then uses multiple overlapping buckets and controlled randomization so two sessions are related without becoming identical.

A concept also cannot immediately repeat over and over simply because it is weak.

---

## Question Types

Learnometry can work with several kinds of practice:

| Type               | Purpose                                           |
| ------------------ | ------------------------------------------------- |
| **Recognition**    | Identify the correct answer                       |
| **Cued Recall**    | Retrieve the answer with support available        |
| **Application**    | Apply knowledge to a vignette or problem          |
| **Discrimination** | Separate two easily confused concepts             |
| **Visual Map**     | Reconstruct information spatially or structurally |

Questions can include:

* Explanations for correct answers
* Explanations for incorrect choices
* Mechanistic reasoning
* Memory hooks
* Key clues
* Takeaways
* Structured visual information

---

## Question Breakdown

Medical questions often contain far more information than the learner actually needs.

Learnometry can break a question down directly on the page and highlight things such as:

* **Flips the question** — NOT / EXCEPT / LEAST
* **Numbers** — labs, vitals, doses
* **Timing** — acute, chronic, onset, duration
* **Who** — age or sex
* **Findings**
* **Background**
* **Skimmable setup**

The original question remains intact.

The markup runs offline and does not require an API key.

---

## Study Material

Add lecture material to the Library and have Learnometry analyze it.

Supported material includes:

* PDF
* DOCX
* PPTX
* TXT
* Markdown
* Images

After analysis, Learnometry can create:

* A topic orientation
* Concept inventory
* High-, medium-, and low-yield classifications
* Commonly confused concepts
* Study sheets
* Practice questions
* Review material

Question counts can be derived from the material itself instead of requiring the student to guess how many questions to generate.

By default:

```text
High-yield concept   → 3 questions
Medium-yield concept → 2 questions
Low-yield concept    → 1 question
```

The user can still override the result.

---

## Study Sheets

Learnometry can generate compact, table-oriented study sheets designed to keep important relationships visible while solving questions.

Think of them as **external working memory** for a topic rather than another wall of notes.

---

## Scope Your Practice

Studying for tomorrow's exam should not necessarily pull questions from every course you have ever taken.

Practice can be restricted by:

* Term
* Course
* Exam

You can also choose whether to:

* Exclude material belonging only to completed exams
* Include material not currently assigned to an exam

Learnometry explicitly tells you when narrowing the scope will temporarily suppress spaced repetition for older material.

It never silently ignores an impossible filter and falls back to everything.

---

## Exams & Study Planning

Create:

* Terms
* Courses
* Exams
* Topic mappings
* Study plans

Exam proximity feeds directly into question priority.

Study-plan capacity is computed from the time you actually have available rather than generated by the AI.

```text
capacity =
    study_days
    × minutes_per_day
```

The planner is designed around several rules:

* Never schedule more time than you said you have
* Say what was dropped when everything cannot fit
* Explain when your available time exceeds the material currently mapped
* Give weaker material additional passes
* Use the final study day primarily for consolidation

Exam readiness is presented as **coverage**, not a predicted exam score.

Learnometry does not have validation data that would justify pretending it can predict your grade.

---

## Instructor Emphasis

Sometimes the most useful information is:

> "The professor said this will definitely be tested."

Learnometry allows instructor or course-emphasis notes to be attached to concepts.

The AI can suggest which concepts a note refers to, but **you decide whether the boost is applied**.

The original source and strength remain separate from the concept's normal high-yield score, making the change traceable and reversible.

---

## Notes Review

Paste or upload your notes and Learnometry can analyze their structure.

Offline measurements include things such as:

* Word count
* Words per line
* Sentence length
* Long unbroken lists
* Tables
* Headings

With an API key, Learnometry can also critique the notes and rewrite a selected passage into a potentially more useful study format.

The feature is influenced by evidence around retrieval practice, distributed practice, self-explanation, and interleaving.

It deliberately avoids presenting disputed ideas such as "visual learning styles" as scientific fact.

---

## Drills

Learnometry includes short study drills generated from concepts already in your question bank.

Because they use existing material, they can run offline.

### Sequence

Remember items in order with an adaptive span.

### Chunk It

Break larger lists into smaller named groups.

### Odd One Out

Identify the item that does not belong while the classification rule changes.

### Name It

Retrieve a medical term from its description without a forced timer.

Drill performance is intentionally kept separate from knowledge mastery.

A cognitive exercise is not automatically evidence that you understand the medical concept.

---

## Anki Export

Learnometry can turn targeted weaknesses into active-recall flashcards.

Selections can include:

* Weakest concepts
* Weak + developing concepts
* Today's incorrect answers
* High-yield weaknesses
* Specific concepts

Card formats include:

* Basic
* Cloze
* Clinical

Cards can be previewed and edited before export.

Learnometry intentionally does **not** simply dump multiple-choice questions into Anki. The concept is converted into active recall instead.

An offline fallback can create basic cards without an API key.

---

## Learning Analytics

Learnometry looks for patterns in your own performance rather than comparing you with everyone else.

Potential insights are only surfaced after minimum evidence requirements are met.

The analytics gate currently requires:

```text
n ≥ 30 per group
effect ≥ 8 percentage points
p < 0.05
```

Results that do not meet the threshold remain marked as **pending** instead of being promoted into conclusions.

One particularly useful metric is calibration:

> When you say you knew an answer, how often were you actually correct?

This can help separate genuine knowledge gaps from misconceptions or overconfidence.

---

## Progression

Learnometry includes optional game-like progression:

* XP
* Levels
* Achievements
* Organ-system progression
* Boss challenges
* Streaks

The system intentionally avoids punishment mechanics.

There are:

* No draining progress bars
* No streaks based on consecutive calendar days
* No XP rewards for answering quickly

Difficulty and honest self-assessment matter more than speed.

A rest day does not erase weeks of progress.

---

## Multiple Learners

One Learnometry installation can support multiple people.

Each person can have:

* A name
* Optional photo
* Their own learner profile
* Their own adaptive instructions

Switching users changes the profile used for future AI interactions.

Study history is preserved separately from deleting an account so an accidental profile deletion does not destroy historical attempt data.

---

## Learner Profiles

Learnometry can operate in three ways:

| Profile Source           | How Learnometry treats it |
| ------------------------ | ------------------------- |
| **Professional report**  | Measured information      |
| **Learnometry screener** | Working preference        |
| **No profile**           | No assumptions are made   |

The learner profile affects how the app presents and structures information.

The exact instructions Learnometry sends to the AI can be inspected from inside the application.

Nothing about the learner profile is intended to be hidden from the learner.

---

## The Screener Is NOT a WAIS-5

Learnometry does **not** reproduce or administer the WAIS-5.

The WAIS-5 is a copyrighted professional psychological instrument and is not appropriate for browser-based self-administration.

Instead, Learnometry includes a small **within-person screener**.

It compares the user's own performance across tasks such as:

* Visual sequence span
* Spoken sequence span
* Word retrieval
* Rule switching

It does **not** generate:

* IQ scores
* Percentiles
* Diagnoses
* Normative psychological conclusions

Results are described as working observations about the user's own performance.

A professional evaluation should be used instead whenever one is available.

---

## AI Model Routing

Different tasks can be routed to different Claude models.

The current configuration separates teaching decisions from more mechanical transformations.

### Teaching

```text
claude-opus-5
```

Used for high-stakes educational reasoning such as:

* Material analysis
* Question generation
* Study sheets
* Session review
* Note critique
* Coaching
* Whiteboard analysis

### Mechanical Transformations

```text
claude-sonnet-5
```

Used for tasks where information has already been reasoned about and mostly needs to be transformed into another structure.

Examples include:

* Anki cards
* Book section extraction
* Planning strategy
* Resource organization
* Question tactics

### Key Testing

```text
claude-haiku-4-5
```

Used for minimal authentication testing.

Model tiers can be overridden through environment variables:

```env
LEARNOMETRY_MODEL=claude-opus-5
LEARNOMETRY_MODEL_MECHANICAL=claude-sonnet-5
LEARNOMETRY_MODEL_TRIVIAL=claude-haiku-4-5-20251001
```

---

## Multiple API Keys

Learnometry supports more than one Anthropic API key.

Keys are tried according to priority.

If a key:

* Runs out of credit
* Is temporarily rate-limited

Learnometry can temporarily set it aside and try the next key during the same request.

Invalid credentials are disabled instead of being repeatedly retried.

> **Important:** API keys are currently stored locally in the application's database in plain text, similarly to storing a key in a local `.env` file.

---

## Local-First Design

Learnometry runs locally.

The application server binds to:

```text
127.0.0.1
```

Your local study database, mastery history, plans, and other application state remain on your machine.

Content that requires Claude is sent to the Anthropic API.

Most functionality can still operate without an API key, including portions of:

* Practice
* Scheduling
* Mastery
* Drills
* Vault
* Pinboard
* Study planning
* Question breakdown
* Offline note analysis
* Offline Anki generation

---

## Backups

Study history may represent hundreds or thousands of answers that cannot simply be regenerated.

Learnometry therefore includes automatic database backups.

Current behavior includes:

* Backup on application start
* Last 10 backups retained
* Restart-loop protection
* SQLite-native backup API
* Safety snapshot before a restore
* Database download
* JSON export

The backup system has been tested by deleting and restoring a database containing recorded attempts.

---

## Optional First Aid Integration

Learnometry can locally index a user's own copy of First Aid.

The book itself is **not uploaded**.

The parser works locally and stores structural information such as:

* Concept names
* Topic paths
* Page ranges
* High-yield scores

It does **not** store or redistribute the book's:

* Prose
* Tables
* Figures
* Mnemonics

Learnometry points back to the user's own copy rather than reproducing the source.

---

# Installation

## Requirements

* Python
* An Anthropic API key for AI-powered features
* Windows for the currently documented desktop installation workflow

Get an Anthropic API key from the Anthropic Console.

---

## 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/Learnometry.git
cd Learnometry
```

---

## 2. Add an API key

You can add a key from inside:

```text
Profile → API Keys
```

Or copy:

```text
.env.example
```

to:

```text
.env
```

and add your API key there.

An API key is optional for offline functionality.

---

## 3. Run Learnometry

The easiest option on Windows:

```text
run.bat
```

Or install the desktop shortcut:

```bash
python install.py
```

This creates Start Menu and Desktop shortcuts.

The application launches in its own window rather than requiring you to manually open a browser and enter a local URL.

To remove the shortcuts:

```bash
python install.py --remove
```

You can also run the desktop application directly:

```bash
python desktop.py
```

If a native webview is unavailable, Learnometry falls back to the default browser.

---

# Keyboard Shortcuts

During practice:

| Key     | Action              |
| ------- | ------------------- |
| `1–5`   | Select an answer    |
| `Enter` | Check / advance     |
| `C`     | Open cue            |
| `?`     | Break down question |
| `Esc`   | Go back             |

---

# Architecture

The backend is Python with a lightweight local web application frontend.

```text
Learnometry
│
├── backend/
│   ├── app.py
│   ├── bank.py
│   ├── claude.py
│   ├── coach.py
│   ├── db.py
│   ├── drills.py
│   ├── generate.py
│   ├── learner_profile.py
│   ├── mastery.py
│   ├── organizer.py
│   ├── planner.py
│   ├── resources.py
│   ├── scheduler.py
│   ├── scope.py
│   └── vault.py
│
├── frontend/
│
├── tests/
│
├── desktop.py
├── install.py
├── run.bat
└── README.md
```

Some important components:

| Component            | Responsibility                               |
| -------------------- | -------------------------------------------- |
| `learner_profile.py` | Learner profile → adaptive teaching contract |
| `claude.py`          | Anthropic API wrapper and model routing      |
| `generate.py`        | Material analysis and question generation    |
| `bank.py`            | Durable question bank                        |
| `mastery.py`         | Mastery, retention and confidence            |
| `scheduler.py`       | Adaptive question selection                  |
| `scope.py`           | Course/exam practice filtering               |
| `planner.py`         | Study planning                               |
| `drills.py`          | Offline learning drills                      |
| `vault.py`           | Local study-file storage                     |
| `organizer.py`       | Terms, courses and exams                     |
| `db.py`              | SQLite database and migrations               |

The frontend uses vanilla HTML, CSS, and JavaScript.

---

# Tests

The current test suite contains:

**419 checks**

The tests cover areas including:

* Mastery calculations
* Persistence
* Adaptive scheduling
* Scope filtering
* Drills
* Study planning
* Notes
* Question tactics
* Book parsing
* Analytics
* Backups
* Multiple users
* Learner profiles
* Screener behavior
* API-key failover

Example:

```bash
.venv\Scripts\python.exe tests/test_account.py
```

Several tests exist specifically to prevent design guarantees from quietly disappearing during future development.

For example:

* Response speed must never change mastery
* An impossible study scope must not silently fall back to everything
* Drills must never modify knowledge mastery
* A huge statistical difference on tiny sample sizes must not become a learning claim
* Learner analytics compare the learner with themselves
* Restoring a backup must preserve a safety snapshot
* Screener output must not claim to provide an IQ or percentile

---

# Data & Privacy

Learnometry is designed primarily as a local application.

### Stored locally

Depending on the feature being used, local data can include:

* Question history
* Mastery
* Study sessions
* Plans
* Learner profiles
* Uploaded vault material
* API keys
* Backups

### Sent to Anthropic

Material is sent to Anthropic when a feature requires Claude to process it.

Offline features do not require this transmission.

### API Keys

API keys stored through the application currently live in the local database in plain text.

Treat the Learnometry data directory as sensitive.

---

# Important Limitations

Learnometry is an educational tool.

It:

* Does not provide medical advice
* Does not diagnose learning disabilities
* Does not administer the WAIS-5
* Does not generate legitimate IQ scores
* Does not predict exam grades
* Does not prove that a particular cognitive training exercise will improve general intelligence or working-memory capacity

Its adaptive decisions are tools for studying, not clinical conclusions.

---

# Project Philosophy

A few principles guide the project:

### Simplify cognitive load, not academic difficulty

Making information easier to hold should not mean making the medicine easier.

### Weakness should change what comes next

Analytics are only useful if they affect future practice.

### Don't reward speed when speed isn't the goal

Response time is recorded where useful but does not determine mastery.

### Don't invent certainty

If Learnometry does not have enough evidence to make a learning claim, it should say so.

### Never silently drop material

A partial lecture that looks complete is more dangerous than an explicit error.

### The learner should be able to inspect the system

Adaptive instructions and learner-profile assumptions should be visible rather than hidden inside prompts.

### Data should survive the application

Study history is difficult to recreate. Backups and export are core functionality, not an afterthought.

---

# Status

Learnometry has completed its original eight-phase development plan, including:

* Persistent mastery
* Weakness targeting
* Study organization
* Scope filtering
* Adaptive drills
* Desktop installation
* Note critique
* Question markup
* First Aid indexing
* Anki export
* Progression
* Learning analytics
* UI polish
* Multi-user profiles
* Backup and restore
* API-key management

The next stage is real-world testing and feedback.

---

# Contributing

Issues, bug reports, feature suggestions, and pull requests are welcome.

If you find something broken, please include:

1. What you were trying to do
2. What happened
3. What you expected
4. Any error message
5. Steps that reproduce the problem

Please do **not** include API keys, private medical records, copyrighted course material, or other sensitive data in an issue.

---

# Disclaimer

Learnometry generates and organizes educational material, including medical study content.

Generated material can be incorrect.

Always verify important medical information against authoritative course materials, textbooks, instructors, or other trusted sources.

Learnometry is not a medical device, healthcare provider, psychological assessment, or substitute for professional medical or psychological evaluation.
