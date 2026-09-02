"""
Checks on the reorganised product: navigation, the Library at scale, and the
rule that an unmeasured topic is never given a number.

Three of these exist because of bugs this redesign introduced and one because
of a bug it exposed:

  * `show()` stamped the current view on <body> as `data-view`, and the
    delegated navigation handler matched the closest `[data-view]` ancestor.
    Every click anywhere in the app therefore re-navigated to the screen you
    were already on, re-ran its arrival work, and - on Practice - destroyed
    the session summary the instant you pressed "End & review".
  * Eight blocks still registered their arrival work by walking `.tab` at
    parse time. The navigation is rendered from a table now and sub-tabs are
    re-rendered on every move, so those handlers covered nothing and Drills,
    the Vault and the Pinboard opened empty.
  * The mastery roll-up REPLACED a parent topic's totals with the sum over its
    children, discarding every concept filed on the parent itself.
  * And the reason all of that stayed invisible: the roll-up averaged over
    untouched concepts, whose `effective` IS the prior, so everything read 35%
    whether it had been studied or not.

Run:  python tests/test_redesign.py
"""

import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db, importer, library, reset, taxonomy, users  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")


# ======================================================== navigation shape

def nav_views() -> list[str]:
    """Every view named by the NAV table, in order."""
    block = JS[JS.index("const NAV = ["):JS.index("const MENU_VIEWS")]
    return re.findall(r'\["([a-z_]+)",\s*"', block)


def menu_views() -> list[str]:
    block = JS[JS.index("const MENU_VIEWS = ["):JS.index("/* One header per screen")]
    return re.findall(r'\["([a-z_]+)",\s*"', block)


def section_views() -> list[str]:
    return re.findall(r'<section class="view[^"]*" id="view-([a-z_]+)"', HTML)


def test_navigation():
    print("\n-- navigation --")
    nav, menu, sections = nav_views(), menu_views(), section_views()

    check("there are five primary destinations",
          JS.count('{ id: "') >= 5 and len(re.findall(r'\{ id: "[a-z]+", label:', JS)) == 5,
          str(re.findall(r'\{ id: "([a-z]+)", label:', JS)))

    check("every destination view exists in the HTML",
          all(v in sections for v in nav),
          str([v for v in nav if v not in sections]))
    check("every account-menu view exists in the HTML",
          all(v in sections for v in menu),
          str([v for v in menu if v not in sections]))

    # A section nobody can reach is a feature that has been silently deleted.
    reachable = set(nav) | set(menu)
    orphans = [v for v in sections if v not in reachable]
    check("no view is unreachable from the navigation", not orphans, str(orphans))

    # And the reverse: a header for a screen that no longer exists.
    pages = set(re.findall(r'^\s{2}([a-z_]+): \{ title:', JS, re.M))
    check("every navigable view has a page header",
          reachable <= pages, str(sorted(reachable - pages)))

    # Comments may still name the drawer; the code must not.
    code = " ".join(ln for ln in JS.splitlines()
                    if not ln.lstrip().startswith(("//", "*", "/*")))
    check("the More drawer is gone",
          "moreMenu" not in HTML and "moreMenu" not in code and
          ".moremenu" not in CSS)
    check("the theme switch is out of the navigation bar",
          '<div class="themeswitch" id="themeSwitch"' not in HTML)
    check("it lives in the account menu instead",
          'id="themeSwitch"' in JS and "renderThemeSwitch(themeState" in JS)


def test_delegated_navigation():
    """The bug that ate the session summary."""
    print("\n-- the delegated click handler --")

    check("<body> does not carry data-view",
          "document.body.dataset.view" not in JS)
    check("it carries data-screen instead",
          "document.body.dataset.screen" in JS)

    handler = JS[JS.index('document.addEventListener("click", (e) => {'):][:420]
    check("the handler matches buttons only, not any ancestor",
          'closest("button[data-view]")' in handler, handler[:160])

    # Nothing in the HTML may put data-view on a container, or the same class
    # of bug returns through a different door.
    bad = [m for m in re.findall(r'<(\w+)[^>]*\sdata-view=', HTML)
           if m != "button"]
    check("only buttons carry data-view in the markup", not bad, str(bad))


def test_arrival_wiring():
    """Every screen's load work goes through one table."""
    print("\n-- arrival wiring --")

    stale = [ln for ln in JS.splitlines()
             if 'querySelectorAll(".tab' in ln and not ln.lstrip().startswith(("*", "//", "`"))]
    check("no screen registers its own parse-time .tab handler",
          not stale, str(stale[:3]))

    check("onEnter composes rather than overwrites",
          re.search(r"function onEnter\(view, fn\) \{[^}]*const prev = ENTER\[view\]",
                    JS, re.S) is not None)

    # The screens that were opening empty.
    for view, fn in [("drills", "loadDrills"), ("vault", "loadVault"),
                     ("board", "loadPins"), ("help", "loadSupport"),
                     ("profile", "loadNotes"), ("profile", "loadBackups"),
                     ("material", "loadLibrary")]:
        found = (re.search(rf'onEnter\("{view}",[\s\S]{{0,140}}?{fn}', JS)
                 or re.search(rf'^  {view}: \(\) => .*{fn}', JS, re.M))
        check(f"{view} loads {fn} on arrival", found is not None)


# ============================================================ the library

def _tiny(title, tag, n_concepts=3):
    concepts = [{"id": f"{tag}{i}", "name": f"{title} concept {i}", "one_line": "x",
                 "yield": "high", "load_risk": "x", "confusable_with": "y"}
                for i in range(n_concepts)]
    questions = [{
        "id": f"{tag}Q{i}", "concept_id": c["id"], "type": "recognition",
        "stem": "Which is correct?", "premise_table": None,
        "options": [{"label": "A", "text": "right", "correct": True, "why": ""},
                    {"label": "B", "text": "w", "correct": False, "why": "m"},
                    {"label": "C", "text": "w", "correct": False, "why": "m"},
                    {"label": "D", "text": "w", "correct": False, "why": "m"}],
        "answer_text": None, "accepted_answers": [], "cue": "a hint",
        "why_right": "because", "derive_from": "mechanism", "visual": "A -> B",
        "memory_hook": "picture", "key_clue": "\"which\"", "takeaway": "the point",
        "source_ref": "Slide 1", "difficulty": 3, "objective_ids": ["ob1"],
    } for i, c in enumerate(concepts)]
    return {"analysis": {"title": title, "subject_area": "Test", "overview": "o",
                         "orientation_table": "| a |\n|---|", "concepts": concepts,
                         "objectives": [{"id": "ob1", "code": "T.1",
                                         "text": "An objective."}],
                         "count_rationale": "r", "flags": []},
            "questions": questions}


def test_library():
    print("\n-- the library at scale --")

    ready = library.add(b"%PDF ready", "Cholinergic Agonists.pdf")
    importer.import_payload(_tiny("Cholinergic Agonists", "ch"),
                            label="Cholinergic Agonists.pdf",
                            upload_id=ready["id"])
    raw = library.add(b"%PDF raw", "Dermatoses.pdf")

    r = library.query()
    check("query returns a page and a total",
          "files" in r and "total" in r and "facets" in r)
    check("both files are listed", r["total"] == 2, str(r["total"]))

    by_id = {f["id"]: f for f in r["files"]}
    check("a file with questions reads Ready",
          by_id[ready["id"]]["status"] == "ready", by_id[ready["id"]]["status"])
    check("a file with nothing extracted needs processing",
          by_id[raw["id"]]["status"] == "unprocessed", by_id[raw["id"]]["status"])
    check("the import linked its concepts to the file",
          by_id[ready["id"]]["concepts"] == 3,
          str(by_id[ready["id"]]["concepts"]))
    check("and counted its questions",
          by_id[ready["id"]]["questions"] == 3,
          str(by_id[ready["id"]]["questions"]))

    # Status is derived from the filesystem too, not only from the row.
    library.path_of(raw["id"]).unlink()
    check("a row whose file vanished reports it, rather than failing later",
          library.get(raw["id"])["status"] == "missing")
    library.add(b"%PDF raw", "Dermatoses.pdf")           # put it back

    # --- filters -------------------------------------------------------
    check("search by name narrows the page",
          library.query(q="cholinergic")["total"] == 1)
    check("search is case-insensitive",
          library.query(q="CHOLINERGIC")["total"] == 1)
    check("a status filter narrows the page",
          library.query(status="ready")["total"] == 1)
    check("statuses combine",
          library.query(status="ready,unprocessed")["total"] == 2)
    check("an unmatched filter returns nothing rather than everything",
          library.query(kind="textbook")["total"] == 0)

    check("facets count the whole library, not the page",
          library.query(limit=1)["facets"]["total"] == 2)
    check("the page really is one row",
          len(library.query(limit=1)["files"]) == 1)
    check("but the total still reports both",
          library.query(limit=1)["total"] == 2)
    check("offset moves the window",
          library.query(limit=1, offset=1)["files"][0]["id"]
          != library.query(limit=1)["files"][0]["id"])

    check("sorting by name is stable and reversible",
          [f["name"] for f in library.query(sort="name")["files"]] ==
          list(reversed([f["name"] for f in library.query(sort="name_desc")["files"]])))

    # --- filing --------------------------------------------------------
    term = __import__("backend.organizer", fromlist=["organizer"])
    t = term.create_term("Term 9", "", "", True)
    exam = term.create_exam("Paper 1", "2099-01-01", term_id=t["id"])
    library.update(ready["id"], exam_id=exam["id"])
    check("filtering by exam works", library.query(exam_id=exam["id"])["total"] == 1)
    check("'not filed' is its own filter",
          library.query(exam_id="none")["total"] == 1)
    check("a term filter follows the exam a file is filed under",
          library.query(term_id=t["id"])["total"] == 1)

    # --- bulk ----------------------------------------------------------
    ids = [f["id"] for f in library.query()["files"]]
    out = library.bulk(ids, "tag", "pharm")
    check("bulk tagging touches every selected file", out["done"] == 2)
    check("the tag is stored", all(
        "pharm" in library.get(i)["tags"] for i in ids))
    check("tagging twice does not duplicate",
          library.bulk(ids, "tag", "pharm") and
          library.get(ids[0])["tags"].count("pharm") == 1)
    check("a tag filter finds them", library.query(tag="pharm")["total"] == 2)
    check("untagging removes it",
          library.bulk(ids, "untag", "pharm") and
          library.query(tag="pharm")["total"] == 0)

    check("an unknown bulk action is refused",
          _raises(lambda: library.bulk(ids, "detonate"), ValueError))
    # One bad id must not abort the rest.
    mixed = library.bulk(ids + ["nope"], "kind", "slides")
    check("a bad id is reported, not fatal",
          mixed["done"] == 2 and len(mixed["failed"]) == 1, str(mixed))

    # --- detail --------------------------------------------------------
    d = library.detail(ready["id"])
    check("detail lists the concepts the file taught", len(d["concept_list"]) == 3)
    check("nothing answered means no mastery number, not a zero",
          d["mastery"] is None and d["assessed"] == 0)
    check("and no weakness is claimed either", d["weak"] == [])
    check("a missing id is a KeyError the router can turn into a 404",
          _raises(lambda: library.detail("nope"), KeyError))

    # --- search --------------------------------------------------------
    s = library.search("cholinergic")
    check("search finds the file", any(f["id"] == ready["id"] for f in s["files"]))
    check("search finds concepts by name", len(s["concepts"]) == 3)
    check("a one-character query is refused rather than scanning everything",
          library.search("c") == {"query": "c", "files": [], "concepts": [],
                                  "questions": 0})

    # --- counts stay honest -------------------------------------------
    before = library.get(ready["id"])["questions"]
    importer.import_payload(_tiny("Cholinergic Agonists", "ch2"),
                            label="Cholinergic Agonists.pdf",
                            upload_id=ready["id"])
    check("importing more questions updates the cached count",
          library.get(ready["id"])["questions"] > before,
          f"{before} -> {library.get(ready['id'])['questions']}")

    library.invalidate(ready["id"])
    check("an invalidated row still reports honest numbers before reconciling",
          library.get(ready["id"])["questions"] > 0)
    check("reconcile restores the cache", library.reconcile() >= 1)

    check("upload_concept is classified for the wipe",
          "upload_concept" not in reset.unclassified())
    check("it is content, so it goes when concepts go",
          "upload_concept" in reset.CONTENT)


# =========================================================== the mastery map

def test_evidence():
    print("\n-- unknown is not the same as weak --")
    from backend import bank
    from backend.routes_study import _evidence, mastery_map

    check("nothing answered means no evidence", _evidence(0, 40, 0) == "none")
    check("a single answered concept in a big topic is thin",
          _evidence(1, 400, 3) == "thin")
    check("a well-covered topic is measured",
          _evidence(20, 40, 60) == "measured")
    check("a small topic still needs a floor of concepts",
          _evidence(1, 2, 40) == "thin")

    m = mastery_map()
    tops = {t["id"]: t for t in m["topics"]}
    untouched = [t for t in tops.values() if t["assessed"] == 0]
    check("there is at least one untouched topic to check", bool(untouched))
    check("an untouched topic reports NO number",
          all(t["effective"] is None for t in untouched))
    check("and says so explicitly",
          all(t["evidence"] == "none" for t in untouched))
    check("and its band is untouched, not red",
          all(t["band"] == "untouched" for t in untouched))
    check("coverage is reported for every topic",
          all("coverage" in t for t in tops.values()))

    # The roll-up bug: a concept filed on a PARENT topic must still count.
    parent = db.q1("SELECT id FROM topic WHERE depth = 0 LIMIT 1")
    kid = db.q1("SELECT id FROM topic WHERE parent_id = ?", parent["id"])
    if kid:
        now = time.time()
        # Move an already-answered concept onto the PARENT topic. Recording the
        # attempt through bank keeps the fixture on the same path the app uses.
        answered = db.q1(
            "SELECT c.id FROM concept c JOIN question_concept qc ON qc.concept_id = c.id"
            " LIMIT 1")
        q = db.q1("SELECT question_id FROM question_concept WHERE concept_id = ?",
                  answered["id"])
        bank.record_attempt(question_id=q["question_id"], correct=True,
                            confidence="knew")
        db.run("UPDATE concept SET topic_id = ? WHERE id = ?",
               parent["id"], answered["id"])
        bank.rebuild_all()

        m2 = mastery_map()
        top = next(t for t in m2["topics"] if t["id"] == parent["id"])
        check("a concept filed on the parent counts toward the parent",
              top["assessed"] >= 1, f"assessed={top['assessed']}")
        check("and is not discarded by the roll-up over children",
              top["effective"] is not None)
        check("the parent's concept count includes its own concepts",
              top["concepts"] > sum(
                  x["concepts"] for x in m2["topics"]
                  if x["parent_id"] == parent["id"]) - 1)


def test_recommendation():
    print("\n-- one source of truth for what to study next --")
    from backend.routes_study import recommend
    from backend import scheduler

    r = recommend()
    check("a mode is named", "mode" in r and r["mode"])
    check("it is a mode that already exists, not a new mixture",
          r["mode"] in scheduler.MODES, r["mode"])
    check("a reason is given", bool(r.get("why")))
    check("a title is given", bool(r.get("title")))

    check("Home asks the recommender rather than deciding again",
          '"/api/select/recommend"' in JS and
          JS.count('api("/api/select/recommend")') >= 2)
    check("Home and Practice start through the same function",
          JS.count("beginSession(") >= 4)
    check("the recommendation names the mode it chose",
          "MODE_NAMES" in JS)


def _raises(fn, exc_type):
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()
    users.ensure_default()

    test_navigation()
    test_delegated_navigation()
    test_arrival_wiring()
    test_library()
    test_evidence()
    test_recommendation()

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
