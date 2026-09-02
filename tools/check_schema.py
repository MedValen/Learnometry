"""Quick schema inspection - confirms a migration landed without losing data."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402

db.configure(ROOT / "data" / "symbolspan.db")

row = db.q1("SELECT value FROM meta WHERE key = 'schema_version'")
print("schema_version:", row["value"] if row else "?")

exam_cols = [r[1] for r in db.q("PRAGMA table_info(exam)")]
concept_cols = [r[1] for r in db.q("PRAGMA table_info(concept)")]
print("exam columns:  ", ", ".join(exam_cols))
print("emphasis_boost on concept:", "emphasis_boost" in concept_cols)

want = ("term", "course", "asset", "asset_link", "pin", "emphasis",
        "conversation", "message", "study_plan")
have = {r["name"] for r in db.q(
    "SELECT name FROM sqlite_master WHERE type = 'table'")}
print("new tables:    ", ", ".join(t for t in want if t in have))
missing = [t for t in want if t not in have]
if missing:
    print("MISSING:       ", ", ".join(missing))

print()
print("data preserved:")
for t in ("concept", "question", "attempt", "mastery"):
    print(f"  {t:10s} {db.q1(f'SELECT COUNT(*) n FROM {t}')['n']}")
