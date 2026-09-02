"""
SQLite persistence.

The whole schema is declared here in one pass, including tables that stay empty
until later phases. Defining them now means Phase 5 is an INSERT rather than a
migration against live attempt history.

Design rule that shapes everything below: `attempt` is append-only and is the
only source of truth. `mastery` is a derived cache that can always be rebuilt
from attempts (see mastery.rebuild_all), so changing the mastery formula is a
backfill, never a data loss.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 11

_local = threading.local()
_db_path: Path | None = None


SCHEMA = """
-- ---------------------------------------------------------------- taxonomy
CREATE TABLE IF NOT EXISTS topic (
    id          TEXT PRIMARY KEY,          -- slug, e.g. "renal.pathology"
    parent_id   TEXT REFERENCES topic(id),
    name        TEXT NOT NULL,
    depth       INTEGER NOT NULL DEFAULT 0,
    path        TEXT NOT NULL,             -- "Renal / Pathology"
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_topic_parent ON topic(parent_id);

CREATE TABLE IF NOT EXISTS concept (
    id            TEXT PRIMARY KEY,        -- stable slug, survives sessions
    topic_id      TEXT NOT NULL REFERENCES topic(id),
    name          TEXT NOT NULL,
    one_line      TEXT NOT NULL DEFAULT '',
    load_risk     TEXT NOT NULL DEFAULT '',   -- WAIS-5 chunking note from analyze()
    high_yield    REAL NOT NULL DEFAULT 0.5,  -- 0..1
    hy_tier       TEXT NOT NULL DEFAULT 'medium',
    -- Instructor emphasis, kept apart from high_yield so what her professor
    -- stressed stays distinguishable from what the textbook weights - and so
    -- undoing it is exact rather than approximate.
    emphasis_boost REAL NOT NULL DEFAULT 0,
    source_refs   TEXT NOT NULL DEFAULT '[]', -- JSON: [{source_id,label,page}]
    created_at    REAL NOT NULL,
    retired       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_concept_topic ON concept(topic_id);

CREATE TABLE IF NOT EXISTS concept_alias (
    alias      TEXT PRIMARY KEY,           -- normalized
    concept_id TEXT NOT NULL REFERENCES concept(id)
);

CREATE TABLE IF NOT EXISTS concept_edge (
    src      TEXT NOT NULL REFERENCES concept(id),
    dst      TEXT NOT NULL REFERENCES concept(id),
    relation TEXT NOT NULL,                -- confusable_with | part_of | causes | ...
    weight   REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, relation)
);
CREATE INDEX IF NOT EXISTS ix_edge_src ON concept_edge(src);

-- ------------------------------------------------------------ question bank
CREATE TABLE IF NOT EXISTS question (
    id            TEXT PRIMARY KEY,
    stem          TEXT NOT NULL,
    premise_table TEXT,
    options       TEXT NOT NULL DEFAULT '[]',  -- JSON [{label,text,correct,why}]
    answer_text   TEXT,
    accepted      TEXT NOT NULL DEFAULT '[]',  -- JSON [str]
    cue           TEXT NOT NULL DEFAULT '',
    why_right     TEXT NOT NULL DEFAULT '',
    derive_from   TEXT NOT NULL DEFAULT '',
    visual        TEXT NOT NULL DEFAULT '',
    memory_hook   TEXT NOT NULL DEFAULT '',
    key_clue      TEXT NOT NULL DEFAULT '',
    takeaway      TEXT NOT NULL DEFAULT '',
    difficulty    INTEGER NOT NULL DEFAULT 1,  -- 1..4, independent of mastery
    fmt           TEXT NOT NULL,               -- recognition | cued_recall | ...
    topic_id      TEXT REFERENCES topic(id),
    high_yield    REAL NOT NULL DEFAULT 0.5,
    source_refs   TEXT NOT NULL DEFAULT '[]',
    objective     TEXT NOT NULL DEFAULT '',   -- JSON list of objective ids
    -- Where in the lecture this came from, e.g. "Slide 13". Separate from
    -- `objective` because they answer different questions: one is what the
    -- course said it would assess, the other is where to go and re-read.
    source_ref    TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    retired       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_q_topic ON question(topic_id);
CREATE INDEX IF NOT EXISTS ix_q_diff  ON question(difficulty);

-- A question can exercise several concepts (boss questions especially).
CREATE TABLE IF NOT EXISTS question_concept (
    question_id TEXT NOT NULL REFERENCES question(id),
    concept_id  TEXT NOT NULL REFERENCES concept(id),
    primary_    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (question_id, concept_id)
);
CREATE INDEX IF NOT EXISTS ix_qc_concept ON question_concept(concept_id);

-- --------------------------------------------------------------- history
-- Append-only. Nothing in the app deletes from this table.
CREATE TABLE IF NOT EXISTS attempt (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT,
    question_id    TEXT NOT NULL REFERENCES question(id),
    concept_id     TEXT NOT NULL REFERENCES concept(id),
    ts             REAL NOT NULL,
    given          TEXT NOT NULL DEFAULT '',
    correct        INTEGER NOT NULL,
    confidence     TEXT NOT NULL DEFAULT 'unsure',  -- knew | unsure | guessed
    used_cue       INTEGER NOT NULL DEFAULT 0,
    error_type     TEXT,
    difficulty     INTEGER NOT NULL DEFAULT 1,
    fmt            TEXT NOT NULL DEFAULT '',
    rt_ms          INTEGER,          -- stored, NEVER an input to mastery
    mastery_before REAL,
    mastery_after  REAL
);
CREATE INDEX IF NOT EXISTS ix_att_concept ON attempt(concept_id, ts);
CREATE INDEX IF NOT EXISTS ix_att_session ON attempt(session_id);
CREATE INDEX IF NOT EXISTS ix_att_ts      ON attempt(ts);

CREATE TABLE IF NOT EXISTS mastery (
    concept_id      TEXT PRIMARY KEY REFERENCES concept(id),
    mastery         REAL NOT NULL DEFAULT 0.35,
    est_confidence  REAL NOT NULL DEFAULT 0.0,
    retention       REAL NOT NULL DEFAULT 1.0,
    effective       REAL NOT NULL DEFAULT 0.35,
    band            TEXT NOT NULL DEFAULT 'red',
    attempts        INTEGER NOT NULL DEFAULT 0,
    correct         INTEGER NOT NULL DEFAULT 0,
    streak          INTEGER NOT NULL DEFAULT 0,
    longest_streak  INTEGER NOT NULL DEFAULT 0,
    variance        REAL NOT NULL DEFAULT 0.0,
    by_difficulty   TEXT NOT NULL DEFAULT '{}',  -- JSON {"1":{"n":,"acc":},...}
    by_format       TEXT NOT NULL DEFAULT '{}',
    avg_rt_ms       REAL,
    last_reviewed   REAL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mastery_eff ON mastery(effective);

-- ------------------------------------------------- scheduling (phase 3)
CREATE TABLE IF NOT EXISTS review (
    concept_id  TEXT PRIMARY KEY REFERENCES concept(id),
    ease        REAL NOT NULL DEFAULT 2.5,
    interval_d  REAL NOT NULL DEFAULT 0,
    due_at      REAL,
    reps        INTEGER NOT NULL DEFAULT 0,
    lapses      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_review_due ON review(due_at);

CREATE TABLE IF NOT EXISTS session (
    id         TEXT PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT 'mixed',
    started_at REAL NOT NULL,
    ended_at   REAL,
    planned    INTEGER NOT NULL DEFAULT 0,
    answered   INTEGER NOT NULL DEFAULT 0,
    correct    INTEGER NOT NULL DEFAULT 0,
    xp         INTEGER NOT NULL DEFAULT 0,
    summary    TEXT NOT NULL DEFAULT '{}'
);

-- --------------------------------------------------- sources (phase 4)
CREATE TABLE IF NOT EXISTS source (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'lecture',  -- textbook | lecture | slides
    filename   TEXT NOT NULL DEFAULT '',
    pages      INTEGER,
    added_at   REAL NOT NULL
);

-- Files she has uploaded. The id is the content hash, so the same lecture
-- uploaded twice is one row rather than two copies on disk.
CREATE TABLE IF NOT EXISTS upload (
    id            TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'lecture',
    pages         INTEGER,
    bytes         INTEGER NOT NULL DEFAULT 0,
    file_id       TEXT,
    added_at      REAL NOT NULL,
    last_seen     REAL NOT NULL,
    -- Which exam this material is for. Nullable: a file can be background
    -- reading that belongs to no single assessment.
    exam_id       TEXT REFERENCES exam(id),
    -- ... and a file can belong to a term or a course without belonging to
    -- any one exam: a handout that spans two papers, background reading for a
    -- block. These are declared HERE as well as in MIGRATIONS[11] because a
    -- migration only ever runs on a database that predates it - a brand-new
    -- install gets its tables from this string and nothing else.
    term_id       TEXT,
    course_id     TEXT,
    tags          TEXT NOT NULL DEFAULT '[]',
    n_concepts    INTEGER NOT NULL DEFAULT 0,
    n_questions   INTEGER NOT NULL DEFAULT 0,
    counted_at    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_upload_exam  ON upload(exam_id);
CREATE INDEX IF NOT EXISTS ix_upload_term  ON upload(term_id);
CREATE INDEX IF NOT EXISTS ix_upload_added ON upload(added_at);

-- Which concepts came out of which file. Materialised from the source-label
-- rule that used to be recomputed on every render; see library.reconcile().
CREATE TABLE IF NOT EXISTS upload_concept (
    upload_id  TEXT NOT NULL REFERENCES upload(id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL REFERENCES concept(id),
    PRIMARY KEY (upload_id, concept_id)
);
CREATE INDEX IF NOT EXISTS ix_uc_concept ON upload_concept(concept_id);

CREATE TABLE IF NOT EXISTS source_section (
    id           TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES source(id),
    section_path TEXT NOT NULL,     -- "Renal / Pathology"
    topic_id     TEXT REFERENCES topic(id),
    page_start   INTEGER,
    page_end     INTEGER,
    ingested_at  REAL
);
CREATE INDEX IF NOT EXISTS ix_sec_source ON source_section(source_id);

-- ------------------------------------------------- later phases, declared now
CREATE TABLE IF NOT EXISTS exam (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    date        TEXT NOT NULL,
    topic_ids   TEXT NOT NULL DEFAULT '[]',
    created_at  REAL NOT NULL,
    term_id     TEXT,
    course_id   TEXT,
    kind        TEXT NOT NULL DEFAULT 'exam',
    concept_ids TEXT NOT NULL DEFAULT '[]',
    notes       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_exam_term ON exam(term_id);
CREATE INDEX IF NOT EXISTS ix_exam_date ON exam(date);

CREATE TABLE IF NOT EXISTS insight (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    claim       TEXT NOT NULL,
    effect      REAL,
    sample_n    INTEGER NOT NULL,
    p_value     REAL,
    computed_at REAL NOT NULL,
    surfaced    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS progression (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    xp             INTEGER NOT NULL DEFAULT 0,
    level          INTEGER NOT NULL DEFAULT 1,
    best_streak    INTEGER NOT NULL DEFAULT 0,
    unlocked       TEXT NOT NULL DEFAULT '[]',
    updated_at     REAL NOT NULL DEFAULT 0
);

-- ===================================================================
-- Phase 3: her own organisation, separate from the knowledge taxonomy.
--
-- The First Aid tree says what a concept IS. These tables say when she
-- NEEDS it. Exams reference concepts rather than owning them, so a
-- concept drilled for the Renal midterm keeps its whole history when it
-- turns up again on the final.
-- ===================================================================

CREATE TABLE IF NOT EXISTS term (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,              -- "Term 4"
    starts     TEXT,                       -- YYYY-MM-DD
    ends       TEXT,
    active     INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS course (
    id         TEXT PRIMARY KEY,
    term_id    TEXT REFERENCES term(id),
    name       TEXT NOT NULL,              -- "Renal & Genitourinary"
    code       TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_course_term ON course(term_id);

-- Photos of whiteboards, exam questions, handwritten notes, handouts.
CREATE TABLE IF NOT EXISTS asset (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'photo',  -- photo|whiteboard|question|handout|note
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime        TEXT NOT NULL DEFAULT '',
    bytes       INTEGER NOT NULL DEFAULT 0,
    caption     TEXT NOT NULL DEFAULT '',
    file_id     TEXT,            -- Files API id, so analysis never re-uploads
    analysis    TEXT,            -- JSON, null until she asks for it
    analysed_at REAL,
    added_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_link (
    asset_id  TEXT NOT NULL REFERENCES asset(id),
    kind      TEXT NOT NULL,     -- term|course|exam|concept|topic|pin
    target_id TEXT NOT NULL,
    PRIMARY KEY (asset_id, kind, target_id)
);
CREATE INDEX IF NOT EXISTS ix_link_target ON asset_link(kind, target_id);

-- Things she wants to keep in front of her.
CREATE TABLE IF NOT EXISTS pin (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'note',  -- topic|mnemonic|image|question|note|link
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    asset_id   TEXT REFERENCES asset(id),
    concept_id TEXT REFERENCES concept(id),
    exam_id    TEXT,
    course_id  TEXT,
    tags       TEXT NOT NULL DEFAULT '[]',
    starred    INTEGER NOT NULL DEFAULT 0,
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pin_exam ON pin(exam_id);

-- "Dr. Nassar said acid-base is heavily tested." The instructor-emphasis
-- signal from the original spec, captured as evidence with a source.
CREATE TABLE IF NOT EXISTS emphasis (
    id          TEXT PRIMARY KEY,
    exam_id     TEXT,
    course_id   TEXT,
    said_by     TEXT NOT NULL DEFAULT 'professor',  -- professor|TA|syllabus|upperclassman|hunch
    text        TEXT NOT NULL,
    strength    TEXT NOT NULL DEFAULT 'mentioned',  -- mentioned|stressed|explicit
    concept_ids TEXT NOT NULL DEFAULT '[]',
    applied     INTEGER NOT NULL DEFAULT 0,         -- she confirmed the boost
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_emph_exam ON emphasis(exam_id);

CREATE TABLE IF NOT EXISTS conversation (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    exam_id    TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversation(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON message(conversation_id, id);

CREATE TABLE IF NOT EXISTS study_plan (
    id              TEXT PRIMARY KEY,
    exam_id         TEXT,
    generated_at    REAL NOT NULL,
    days_left       REAL,
    minutes_per_day INTEGER,
    plan            TEXT NOT NULL DEFAULT '{}',
    superseded      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_plan_exam ON study_plan(exam_id);

-- Drill results live apart from `attempt` on purpose. A drill is a skill
-- exercise, not a knowledge test, and folding its scores into mastery would
-- corrupt the model with a different task.
CREATE TABLE IF NOT EXISTS drill_result (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    drill       TEXT NOT NULL,        -- sequence|chunk|oddone|name
    ts          REAL NOT NULL,
    score       REAL NOT NULL DEFAULT 0,
    span        INTEGER,              -- items held, for the span drill
    rounds      INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    ms          INTEGER,              -- personal baseline only, never a norm
    concept_ids TEXT NOT NULL DEFAULT '[]',
    detail      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_drill_kind ON drill_result(drill, ts);

CREATE TABLE IF NOT EXISTS note_review (
    id         TEXT PRIMARY KEY,
    ts         REAL NOT NULL,
    source     TEXT NOT NULL DEFAULT 'paste',   -- paste | asset
    asset_id   TEXT,
    title      TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    metrics    TEXT NOT NULL DEFAULT '{}',      -- offline heuristics
    critique   TEXT,                            -- JSON, null until Claude runs
    topic_id   TEXT
);
CREATE INDEX IF NOT EXISTS ix_notereview_ts ON note_review(ts);

-- ===================================================================
-- Users. One row per person using this install.
-- ===================================================================

CREATE TABLE IF NOT EXISTS app_user (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    photo       TEXT,                       -- filename under data/avatars
    active      INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    -- The cognitive profile that shapes every prompt. JSON so it can hold a
    -- full neuropsych report, a screener result, or nothing at all.
    profile     TEXT NOT NULL DEFAULT '{}',
    profile_kind TEXT NOT NULL DEFAULT 'none'   -- report | screener | none
);

-- Several API keys, tried in order. Stored locally in plain text, same as the
-- .env file they replace - this is a single-user desktop app and the database
-- sits in her own profile directory. Keys are never sent to the browser.
CREATE TABLE IF NOT EXISTS api_key (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    secret     TEXT NOT NULL,
    priority   INTEGER NOT NULL DEFAULT 0,   -- lower is tried first
    enabled    INTEGER NOT NULL DEFAULT 1,
    last_ok    REAL,
    last_error TEXT,
    cooldown_until REAL,                     -- set when a key is rate-limited
    uses       INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    -- Identity-linked keys are rejected without the workspace they act in.
    workspace_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_key_priority ON api_key(priority);

-- Screener runs, kept so a profile can be re-derived or re-checked later.
-- Standing notes: things she told us that no test measured. Carried into
-- every prompt so the same caveat is not retyped into each new chat.
CREATE TABLE IF NOT EXISTS user_note (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES app_user(id),
    kind       TEXT NOT NULL DEFAULT 'context',
    text       TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_note_user ON user_note(user_id, active);

CREATE TABLE IF NOT EXISTS screener_run (
    id         TEXT PRIMARY KEY,
    user_id    TEXT,
    ts         REAL NOT NULL,
    tasks      TEXT NOT NULL DEFAULT '{}',   -- raw per-task results
    profile    TEXT NOT NULL DEFAULT '{}',   -- derived relative profile
    complete   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def configure(path: Path) -> None:
    global _db_path
    _db_path = path
    path.parent.mkdir(parents=True, exist_ok=True)
    init()


def path() -> Path:
    """Where the database actually is.

    Callers that need the file (backup, restore) must ask here rather than
    recomputing it from app.DATA - two sources for one fact is how a backup
    ends up pointing at the wrong file.
    """
    if _db_path is None:
        raise RuntimeError("db.configure() has not been called")
    return _db_path


def conn() -> sqlite3.Connection:
    """One connection per thread. FastAPI's threadpool needs this."""
    if _db_path is None:
        raise RuntimeError("db.configure() has not been called")
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(_db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        _local.conn = c
        _ALL_CONNS.append(c)
    return c


_ALL_CONNS: list = []


def close_all() -> None:
    """Close every open handle.

    Restoring overwrites the database file underneath live connections, and on
    Windows an open handle blocks the replace outright. Each thread reopens
    lazily on its next call.
    """
    global _ALL_CONNS
    for c in _ALL_CONNS:
        try:
            c.close()
        except Exception:                              # noqa: BLE001
            pass
    _ALL_CONNS = []
    if hasattr(_local, "conn"):
        del _local.conn


def init() -> None:
    c = conn()
    c.executescript(SCHEMA)
    cur = c.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    row = cur.fetchone()
    if row is None:
        c.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                  (str(SCHEMA_VERSION),))
    c.execute(
        "INSERT OR IGNORE INTO progression (id, xp, level, updated_at) VALUES (1, 0, 1, 0)"
    )
    c.commit()
    migrate()


# Columns added to tables that already existed in v1. CREATE TABLE IF NOT
# EXISTS cannot add these, and her attempt history must survive the upgrade.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE exam ADD COLUMN term_id TEXT",
        "ALTER TABLE exam ADD COLUMN course_id TEXT",
        "ALTER TABLE exam ADD COLUMN kind TEXT NOT NULL DEFAULT 'exam'",
        "ALTER TABLE exam ADD COLUMN concept_ids TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE exam ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
        # Kept separate from `high_yield` so what her professor stressed stays
        # distinguishable from what the textbook weights, and is reversible.
        "ALTER TABLE concept ADD COLUMN emphasis_boost REAL NOT NULL DEFAULT 0",
    ],
    3: [],   # drill_result is created by SCHEMA; nothing to alter
    4: [],   # note_review likewise
    5: [],   # app_user / api_key / screener_run come from SCHEMA
    6: [
        # An identity-linked key is refused outright unless the request names
        # the workspace it acts in. Nullable, because org keys must not be
        # forced to carry one.
        "ALTER TABLE api_key ADD COLUMN workspace_id TEXT",
    ],
    7: [],   # the upload table comes from SCHEMA; adopt_orphans() backfills rows
    9: [],   # user_note comes from SCHEMA
    10: [
        # `objective` used to be fed the slide reference, which meant the app
        # had nowhere to record what the course said it was assessing. The two
        # are now separate columns.
        "ALTER TABLE question ADD COLUMN source_ref TEXT NOT NULL DEFAULT ''",
    ],
    8: [
        # Lets a lecture be filed under the exam it will be tested in, which is
        # what makes exam-scoped and whole-term (BCSC) practice possible.
        "ALTER TABLE upload ADD COLUMN exam_id TEXT",
    ],
    11: [
        # A file can belong to a term or a course without belonging to any one
        # exam - background reading for a block, a textbook chapter, a handout
        # that spans two papers. Filing only by exam made those unfilable.
        "ALTER TABLE upload ADD COLUMN term_id TEXT",
        "ALTER TABLE upload ADD COLUMN course_id TEXT",
        "ALTER TABLE upload ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'",
        # Cached counts. `counted_at` of 0 means "never reconciled", which is
        # what library.reconcile() looks for on startup.
        "ALTER TABLE upload ADD COLUMN n_concepts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE upload ADD COLUMN n_questions INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE upload ADD COLUMN counted_at REAL NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS ix_upload_exam ON upload(exam_id)",
        "CREATE INDEX IF NOT EXISTS ix_upload_term ON upload(term_id)",
        "CREATE INDEX IF NOT EXISTS ix_upload_added ON upload(added_at)",
    ],
}


def migrate() -> int:
    """Apply pending migrations. Idempotent - a duplicate column is a no-op."""
    c = conn()
    row = c.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    current = int(row["value"]) if row else 1
    applied = 0
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        for sql in MIGRATIONS[version]:
            try:
                c.execute(sql)
                applied += 1
            except sqlite3.OperationalError as exc:
                # "duplicate column name" means this migration already landed.
                if "duplicate column" not in str(exc).lower():
                    raise
        c.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
    c.commit()
    return applied


# ---------------------------------------------------------------- helpers

def q(sql: str, *params) -> list[sqlite3.Row]:
    return conn().execute(sql, params).fetchall()


def q1(sql: str, *params) -> sqlite3.Row | None:
    return conn().execute(sql, params).fetchone()


def run(sql: str, *params):
    c = conn()
    cur = c.execute(sql, params)
    c.commit()
    return cur


def runmany(sql: str, rows) -> None:
    c = conn()
    c.executemany(sql, rows)
    c.commit()


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def unjs(text, default=None):
    if not text:
        return default if default is not None else []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []
