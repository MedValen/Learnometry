"""
Whole-surface checks on the HTTP layer.

These exist because two bugs got in that no feature test would ever catch:

  * `/api/notes/{nid}` was registered twice - once for note reviews, once for
    standing notes. FastAPI matches the first, so deleting a standing note
    returned 200 and deleted nothing. A silent success is the worst failure
    mode there is.
  * Three modules had their own `_guard`, and they had drifted. app.py's copy
    caught neither KeyError nor ValueError, so any missing id in the library,
    importer or support routes answered with a 500 and a stack trace.

Run:  python tests/test_routes.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import apierr, library, notes_memory, organizer, users  # noqa: E402
from backend.app import app  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def main():
    c = TestClient(app, raise_server_exceptions=False)

    # ======================== no route collisions ======================
    print("\n-- route registration --")
    seen: dict[tuple[str, str], int] = {}
    for r in app.routes:
        for m in getattr(r, "methods", set()) or set():
            key = (m, getattr(r, "path", ""))
            seen[key] = seen.get(key, 0) + 1
    dupes = sorted(k for k, n in seen.items() if n > 1)
    check("no two routes share a method and path", not dupes, str(dupes))

    # A path that differs only by parameter NAME is still the same route to
    # the router, and that is exactly how the notes collision happened.
    shapes: dict[tuple[str, str], list[str]] = {}
    for (m, path) in seen:
        shape = (m, re.sub(r"\{[^}]+\}", "{}", path))
        shapes.setdefault(shape, []).append(path)
    shadowed = {k: v for k, v in shapes.items() if len(set(v)) > 1}
    check("no route is shadowed by another with a differently-named param",
          not shadowed, str(shadowed))

    # ========================= one guard only ==========================
    print("\n-- error handling --")
    guards = []
    for f in sorted((ROOT / "backend").glob("*.py")):
        if f.name == "apierr.py":
            continue
        src = f.read_text(encoding="utf-8")
        if re.search(r"^def _guard\(", src, re.M):
            guards.append(f.name)
    check("no module defines its own _guard any more", not guards, str(guards))

    check("KeyError unwraps its quotes",
          apierr.detail(KeyError("no such upload: x")) == "no such upload: x")
    check("ValueError passes through unchanged",
          apierr.detail(ValueError("bad input")) == "bad input")

    # An unknown exception must NOT be tidied into a 4xx - it is a real bug and
    # has to keep reaching the 500 handler with its traceback.
    def boom():
        raise RuntimeError("genuine fault")
    raised = False
    try:
        apierr.guard(boom)
    except RuntimeError:
        raised = True
    check("an unexpected exception is not swallowed", raised)

    # ==================== missing ids answer cleanly ===================
    print("\n-- missing ids --")
    for path in ("/api/library/nope/text", "/api/library/nope/download"):
        r = c.get(path)
        check(f"{path} is a 404", r.status_code == 404, str(r.status_code))
        check(f"{path} has an unquoted message",
              "'" not in str(r.json().get("detail", "")),
              str(r.json().get("detail")))

    # ============= standing-note delete actually deletes ===============
    print("\n-- standing notes, end to end --")
    uid = users.active()["id"]
    n = notes_memory.add(uid, "route test probe", kind="context")

    r = c.patch(f"/api/standing-notes/{n['id']}", json={"active": False})
    check("mute reaches the right route", r.status_code == 200, str(r.status_code))
    check("and actually mutes",
          notes_memory.get(n["id"])["active"] is False)

    r = c.delete(f"/api/standing-notes/{n['id']}")
    check("delete returns 200", r.status_code == 200, str(r.status_code))
    gone = not any(x["id"] == n["id"] for x in notes_memory.listing(uid))
    check("and the note is REALLY gone", gone)

    # The old path must no longer be a way to reach standing notes at all.
    n2 = notes_memory.add(uid, "second probe", kind="context")
    c.delete(f"/api/notes/{n2['id']}")
    check("the old /api/notes path does not touch standing notes",
          any(x["id"] == n2["id"] for x in notes_memory.listing(uid)))
    notes_memory.remove(n2["id"])

    # ======================= theme round-trips =========================
    print("\n-- theme --")
    before = c.get("/api/theme").json()["theme"]
    r = c.post("/api/theme", json={"theme": "mono"})
    check("a valid theme is accepted", r.status_code == 200)
    check("it is read back", c.get("/api/theme").json()["theme"] == "mono")

    html = c.get("/").text
    check("the theme is injected into the served HTML",
          'data-theme="mono"' in html, html[:120])

    r = c.post("/api/theme", json={"theme": "chartreuse"})
    check("an unknown theme is refused", r.status_code == 400, str(r.status_code))

    c.post("/api/theme", json={"theme": "auto"})
    html = c.get("/").text
    check("auto injects nothing, so the media query decides",
          "data-theme" not in html)
    c.post("/api/theme", json={"theme": before})

    # =================== the finished-session trap =====================
    # After "End & review" the summary showed and the launcher stayed hidden,
    # with no control returning to it - and the Practice tab only swaps VIEWS,
    # not the panels inside one, so navigating away and back did not help
    # either. These assert the escape routes exist in the shipped files.
    print("\n-- escaping a finished session --")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    check("the summary offers a way back to the pickers",
          'id="newSessionBtn"' in html)
    check("that button is wired", 'newSessionBtn' in js and 'backToLauncher' in js)
    check("backToLauncher reveals the launcher",
          re.search(r"function backToLauncher\(\)[^}]*quizEmpty\"\)\.hidden = false",
                    js, re.S) is not None)
    check("and hides the summary",
          re.search(r"function backToLauncher\(\)[^}]*quizDone\"\)\.hidden = true",
                    js, re.S) is not None)
    # The recovery lives in the ENTER table beside the navigation now; it used
    # to be a fourth pass of querySelectorAll(".tab"), which stopped covering
    # anything once the nav was rendered rather than hard-coded.
    check("returning to Practice recovers a finished session",
          "ENTER" in js and re.search(r"quiz:\s*\(\)\s*=>", js) is not None)
    check("but only when finished - mid-session must keep her place",
          re.search(r"quiz:\s*\(\)\s*=>.{0,220}?backToLauncher", js, re.S)
          is not None
          and re.search(r"quiz:\s*\(\)\s*=>.{0,220}?quizDone", js, re.S)
          is not None)

    failed = len([c_ for c_ in checks if not c_])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
