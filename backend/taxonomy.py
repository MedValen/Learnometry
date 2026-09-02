"""
The topic tree and stable concept identity.

Concept identity is the thing that makes mastery tracking possible at all. The
existing generator emits ids like "c1", "c2" - fresh every analyze() call and
meaningless across sessions. Here a concept gets a slug derived from its topic
path and canonical name, so the same concept found in a lecture in September and
in First Aid in November resolves to one row with one continuous history.

The seed tree mirrors First Aid's own structure, because that is the structure
the exam is written against and the structure her SGU course follows.
"""

from __future__ import annotations

import re
import time
import unicodedata

from . import db

# System -> disciplines. First Aid Section II is discipline-first; Section III
# is system-first with the same five disciplines under each.
ORGAN_SYSTEMS = [
    "Cardiovascular", "Endocrine", "Gastrointestinal", "Hematology and Oncology",
    "Musculoskeletal and Skin", "Neurology", "Psychiatry", "Renal",
    "Reproductive", "Respiratory",
]

SYSTEM_DISCIPLINES = ["Embryology", "Anatomy", "Physiology", "Pathology", "Pharmacology"]

GENERAL_PRINCIPLES = {
    "Biochemistry": ["Molecular", "Cellular", "Laboratory Techniques", "Genetics",
                     "Nutrition", "Metabolism"],
    "Immunology": ["Lymphoid Structures", "Cellular Components", "Immune Responses",
                   "Immunosuppressants"],
    "Microbiology": ["Basic Bacteriology", "Clinical Bacteriology", "Mycology",
                     "Parasitology", "Virology", "Systems", "Antimicrobials"],
    "Pathology": ["Cellular Injury", "Inflammation", "Neoplasia", "Aging"],
    "Pharmacology": ["Pharmacokinetics", "Autonomic Drugs", "Toxicities and Adverse Effects",
                     "Miscellaneous"],
    "Public Health Sciences": ["Epidemiology and Biostatistics", "Ethics",
                               "Communication Skills", "Healthcare Delivery",
                               "Quality and Safety"],
}


# ------------------------------------------------------------------ slugs

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text) or "unnamed"


def normalize_name(text: str) -> str:
    """For alias matching. Drops punctuation, case, and filler words."""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9\s]", " ", t.lower())
    t = re.sub(r"\b(the|a|an|of|in|and|to|for)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------- seed

def seed() -> int:
    """Create the base topic tree. Idempotent - safe to call on every boot."""
    rows: list[tuple] = []
    order = 0

    def add(tid, parent, name, depth, path, o):
        rows.append((tid, parent, name, depth, path, o))

    for group, subs in GENERAL_PRINCIPLES.items():
        gid = slugify(group)
        order += 1
        add(gid, None, group, 0, group, order)
        for sub in subs:
            order += 1
            add(f"{gid}.{slugify(sub)}", gid, sub, 1, f"{group} / {sub}", order)

    for system in ORGAN_SYSTEMS:
        sid = slugify(system)
        order += 1
        add(sid, None, system, 0, system, order)
        for disc in SYSTEM_DISCIPLINES:
            order += 1
            add(f"{sid}.{slugify(disc)}", sid, disc, 1, f"{system} / {disc}", order)

    # A home for concepts we cannot confidently place yet.
    order += 1
    add("unsorted", None, "Unsorted", 0, "Unsorted", order)

    db.runmany(
        "INSERT OR IGNORE INTO topic (id, parent_id, name, depth, path, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


# ------------------------------------------------------------ topic lookup

def resolve_topic(path_or_name: str | None) -> str:
    """Best-effort map of a free-text topic label onto the tree.

    Accepts "Renal / Pathology", "Renal Pathology", "renal.pathology", or just
    "Renal". Falls back to 'unsorted' rather than inventing a topic, so bad
    mappings are visible instead of silently fragmenting the tree.
    """
    if not path_or_name:
        return "unsorted"

    raw = str(path_or_name).strip()
    direct = db.q1("SELECT id FROM topic WHERE id = ?", raw.lower())
    if direct:
        return direct["id"]

    parts = [p.strip() for p in re.split(r"[/>|.→-]+", raw) if p.strip()]
    if len(parts) >= 2:
        cand = f"{slugify(parts[0])}.{slugify(parts[1])}"
        if db.q1("SELECT id FROM topic WHERE id = ?", cand):
            return cand

    norm = normalize_name(raw)
    for row in db.q("SELECT id, name, path FROM topic"):
        if normalize_name(row["path"]) == norm or normalize_name(row["name"]) == norm:
            return row["id"]

    # Last resort: a system name mentioned anywhere in the string.
    for row in db.q("SELECT id, name FROM topic WHERE depth = 0"):
        if normalize_name(row["name"]) in norm:
            return row["id"]

    return "unsorted"


# ---------------------------------------------------------- concept identity

HY_TIERS = {"very_high": 0.95, "high": 0.78, "medium": 0.5, "low": 0.25}
YIELD_TO_TIER = {"high": "high", "medium": "medium", "low": "low"}


def concept_slug(topic_id: str, name: str) -> str:
    return f"{topic_id}::{slugify(name)}"


def resolve_concept(
    name: str,
    *,
    topic_id: str = "unsorted",
    one_line: str = "",
    load_risk: str = "",
    yield_tier: str = "medium",
    source_refs: list | None = None,
    aliases: list[str] | None = None,
) -> str:
    """Get-or-create a concept and return its stable id.

    Matching order: exact slug, then normalized-name alias. Anything fuzzier
    would risk merging two genuinely different concepts, which corrupts history
    in a way that is very hard to notice and impossible to undo.
    """
    norm = normalize_name(name)

    hit = db.q1("SELECT concept_id FROM concept_alias WHERE alias = ?", norm)
    if hit:
        return hit["concept_id"]

    cid = concept_slug(topic_id, name)
    existing = db.q1("SELECT id FROM concept WHERE id = ?", cid)
    if existing:
        _add_aliases(cid, [name] + (aliases or []))
        return cid

    tier = YIELD_TO_TIER.get(yield_tier, yield_tier if yield_tier in HY_TIERS else "medium")
    db.run(
        "INSERT INTO concept (id, topic_id, name, one_line, load_risk, high_yield, "
        "hy_tier, source_refs, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        cid, topic_id, name, one_line, load_risk,
        HY_TIERS.get(tier, 0.5), tier, db.js(source_refs or []), time.time(),
    )
    db.run(
        "INSERT OR IGNORE INTO mastery (concept_id, updated_at) VALUES (?, ?)",
        cid, time.time(),
    )
    _add_aliases(cid, [name] + (aliases or []))
    return cid


def _add_aliases(concept_id: str, names: list[str]) -> None:
    rows = [(normalize_name(n), concept_id) for n in names if n and normalize_name(n)]
    if rows:
        db.runmany(
            "INSERT OR IGNORE INTO concept_alias (alias, concept_id) VALUES (?, ?)",
            rows,
        )


def link(src: str, dst: str, relation: str = "confusable_with", weight: float = 1.0) -> None:
    """One edge of the concept graph. Confusable pairs are bidirectional."""
    if src == dst:
        return
    db.run(
        "INSERT OR REPLACE INTO concept_edge (src, dst, relation, weight) VALUES (?, ?, ?, ?)",
        src, dst, relation, weight,
    )
    if relation == "confusable_with":
        db.run(
            "INSERT OR REPLACE INTO concept_edge (src, dst, relation, weight) "
            "VALUES (?, ?, ?, ?)",
            dst, src, relation, weight,
        )


def tree() -> list[dict]:
    """The topic tree with concept counts, for the heatmap."""
    rows = db.q(
        "SELECT t.id, t.parent_id, t.name, t.depth, t.path, t.sort_order, "
        "  COUNT(c.id) AS concepts "
        "FROM topic t LEFT JOIN concept c ON c.topic_id = t.id AND c.retired = 0 "
        "GROUP BY t.id ORDER BY t.sort_order"
    )
    return [dict(r) for r in rows]
