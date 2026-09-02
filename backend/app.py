"""
Learnometry - local study server.

Runs on 127.0.0.1 only. Course files and generated sessions stay on this
machine except for the content sent to the Anthropic API to generate material.
"""

from __future__ import annotations

import json
import os
import time
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from .apierr import detail as _detail, guard as _guard
from . import (                                    # noqa: E402
    backup, claude, db, generate, resources, routes_account, routes_org,
    routes_study, taxonomy, users,
)
from . import evaluations, importer, library, preread, support, whereto
from .ingest import (                              # noqa: E402
    Source, ingest, UnsupportedFile, FileTooLarge, SUPPORTED,
)
from .learner_profile import profile_digest        # noqa: E402

# When packaged as a desktop app the executable's folder is read-only and its
# extraction directory is temporary, so the only copy of her study history has
# to live somewhere stable. desktop.py sets this; running from source ignores it.
DATA = Path(os.environ.get("LEARNOMETRY_DATA")
            or os.environ.get("SYMBOLSPAN_DATA")   # pre-rename installs
            or (ROOT / "data"))
UPLOADS = DATA / "uploads"
SESSIONS = DATA / "sessions"
for d in (UPLOADS, SESSIONS):
    d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

app = FastAPI(title="Learnometry")

# Persistence comes up before any route can touch it.
db.configure(DATA / "symbolspan.db")

# Files uploaded before the library existed have bytes on disk and no row.
# Give them one, so they reappear instead of staying invisible forever.
try:
    _adopted = library.adopt_orphans()
    if _adopted:
        print(f"library: adopted {_adopted} previously untracked upload(s)")
except Exception as _exc:                              # noqa: BLE001
    print(f"library: could not adopt orphans: {_exc}")
# Materialise the concept links and cached counts the Library reads. Before
# this, "which concepts came from this file" was a scan of the whole question
# bank, per file, on every render.
try:
    _counted = library.reconcile()
    if _counted:
        print(f"library: reconciled {_counted} file(s)")
except Exception as _exc:                              # noqa: BLE001
    print(f"library: could not reconcile: {_exc}")
taxonomy.seed()
users.ensure_default()
# Her answer history cannot be regenerated, so a rolling copy is taken on
# every start. Failure here is swallowed - it must never block the app.
backup.auto()
app.include_router(routes_study.router)
app.include_router(routes_org.router)
app.include_router(routes_account.router)

# In-memory registry of ingested files for this run. The uploads themselves and
# the saved sessions are on disk; this just holds the parsed form.
_sources: dict[str, Source] = {}


# ---------------------------------------------------------------------------
# Error handling - surface real messages, the UI shows them verbatim.
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled(request, exc):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@app.get("/api/profile")
def get_profile():
    return profile_digest()


@app.get("/api/health")
def health():
    try:
        claude.client()
        return {"ok": True, "model": claude.MODEL}
    except claude.NotConfigured as exc:
        return {"ok": False, "detail": str(exc)}


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Record the file first, then try to ingest it.

    The order matters. Ingestion talks to the Files API, and it used to be the
    only thing that produced a record - so a failure there, or simply a
    restart, left the bytes on disk with nothing in the app pointing at them.
    The library row is written from the bytes alone, so a file she uploaded is
    visible and re-usable even if every subsequent step fails.
    """
    out, errors = [], []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append(f"{f.filename}: over 100 MB.")
            continue
        if Path(f.filename).suffix.lower() not in SUPPORTED:
            errors.append(f"{f.filename}: unsupported file type.")
            continue

        try:
            entry = library.add(data, Path(f.filename).name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{f.filename}: could not be stored: {exc}")
            continue

        # Ingestion is best-effort. Without an API key, or with a key that is
        # refused, she still has the file and can extract its text locally.
        try:
            src = ingest(library.path_of(entry["id"]), claude.client())
            _sources[src.sha] = src
            library.update(entry["id"], file_id=src.file_id)
            entry = library.get(entry["id"])
            entry["ready"] = True
        except Exception as exc:  # noqa: BLE001
            entry["ready"] = False
            entry["note"] = (
                f"Stored, but not prepared for the API ({type(exc).__name__}). "
                "You can still open it and copy its text.")
        out.append(entry)

    if not out and errors:
        raise HTTPException(status_code=400, detail=" | ".join(errors))
    return {"sources": out, "errors": errors, "supported": sorted(SUPPORTED)}


# ------------------------------------------------------------------ library

@app.get("/api/library")
def library_list(q: str = "", term_id: str = "", course_id: str = "",
                 exam_id: str = "", kind: str = "", status: str = "",
                 tag: str = "", sort: str = "added",
                 limit: int = 50, offset: int = 0):
    """One page of the library.

    Returning every row was fine at four files. The page is the unit now, and
    the totals the filter bar needs come back with it so the client never has
    to fetch the whole library to render a count.
    """
    limit = max(1, min(int(limit), 500))
    out = library.query(q=q, term_id=term_id, course_id=course_id,
                        exam_id=exam_id, kind=kind, status=status, tag=tag,
                        sort=sort, limit=limit, offset=max(0, int(offset)))
    out["supported"] = sorted(SUPPORTED)
    return out


@app.get("/api/library/search")
def library_search(q: str = "", limit: int = 8):
    """Files, concepts and questions matching one string."""
    return library.search(q, limit=max(1, min(int(limit), 30)))


@app.get("/api/library/{uid}/detail")
def library_detail(uid: str):
    """One file, joined to what it taught and how well it is known."""
    return _guard(library.detail, uid)


@app.post("/api/library/bulk")
def library_bulk(body: dict = Body(...)):
    """One change applied to many files at once."""
    ids = [str(i) for i in (body.get("ids") or []) if i]
    if not ids:
        raise HTTPException(status_code=400, detail="No files selected.")
    action = body.get("action") or ""
    result = _guard(library.bulk, ids, action, body.get("value"))

    # Filing under an exam has to move the concepts too, or the assignment is
    # cosmetic - see library_set_exam for the single-file version of this.
    if action == "exam" and body.get("value"):
        moved = 0
        for uid in ids:
            cids = library.concepts_of(uid)
            if cids:
                moved += importer.attach_to_exam(body["value"], cids)
        result["concepts_attached"] = moved
    return result


@app.get("/api/library/{uid}/text")
def library_text(uid: str):
    """Plain text, extracted locally. Costs nothing at the API."""
    return _guard(library.extract_text, uid)


@app.get("/api/library/{uid}/download")
def library_download(uid: str):
    entry = _guard(library.get, uid)
    path = library.path_of(uid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{entry['name']} is missing from disk.")
    return FileResponse(path, filename=entry["name"])


@app.patch("/api/library/{uid}")
def library_patch(uid: str, body: dict = Body(...)):
    fields = {k: v for k, v in body.items()
              if k in ("kind", "original_name", "exam_id", "term_id",
                       "course_id")}
    if "tags" in body:
        fields["tags"] = db.js([str(t) for t in (body["tags"] or [])])
    return _guard(library.update, uid, **fields)


@app.post("/api/library/{uid}/exam")
def library_set_exam(uid: str, body: dict = Body(...)):
    """File a lecture under an exam, and move its existing concepts with it.

    Assigning the file alone would be cosmetic: what makes exam-scoped practice
    work is the concepts being on the exam. So anything already imported from
    this file is attached too, rather than only future imports.
    """
    exam_id = body.get("exam_id") or None
    _guard(library.update, uid, exam_id=exam_id)

    attached = 0
    if exam_id:
        cids = library.concepts_of(uid)
        if cids:
            attached = importer.attach_to_exam(exam_id, cids)
    return {"file": library.recount(uid), "concepts_attached": attached}


@app.delete("/api/library/{uid}")
def library_delete(uid: str):
    entry = _guard(library.remove, uid)
    _sources.pop(entry["id"], None)
    return {"ok": True, "removed": entry["name"]}


@app.get("/api/whereto/{question_id}")
def api_whereto(question_id: str):
    """Where to re-read after getting a question wrong."""
    return _guard(whereto.for_question, question_id)


@app.post("/api/preread")
def api_preread(body: dict = Body(...)):
    """Adler's inspectional read of an uploaded file, or of pasted text.

    Text is extracted locally and sent as text rather than shipping the PDF
    through the Files API - cheaper, and it works with no Files beta enabled.
    """
    uid = body.get("upload_id")
    title = body.get("title", "")
    if uid:
        got = _guard(library.extract_text, uid)
        text, title = got["text"], title or got["name"]
    else:
        text = body.get("text", "")
    return _guard(preread.run, text, title=title)


@app.post("/api/preread/export")
def api_preread_export(body: dict = Body(...)):
    """Download a pre-read already produced. Makes no API call."""
    from fastapi.responses import Response as _Response

    md = preread.as_markdown(body)
    name = (body.get("title") or "pre-read").rsplit(".", 1)[0][:60]
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip()
    return _Response(
        content=md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="Pre-read - {safe or "material"}.md"'})


@app.get("/api/evaluations")
def get_evaluations():
    """Where to get properly assessed, and what to avoid."""
    return evaluations.payload()


@app.get("/api/support")
def get_support():
    """How to use the app, and how to donate. Includes locally-made QR codes."""
    return {**support.payload(), "first_run": support.first_run()}


@app.post("/api/support/seen")
def support_seen():
    """Dismiss the welcome. Recorded per install, so it shows exactly once."""
    support.mark_seen()
    return {"ok": True}


@app.post("/api/support/config")
def support_config(body: dict = Body(...)):
    """Correct the donation details without editing code."""
    support.save_config(body)
    return support.payload()


@app.get("/api/import/spec")
def import_spec():
    """The authoring instructions, including her standing notes."""
    user = users.active()
    return {"spec": importer.spec_text(user["id"] if user else None)}


@app.post("/api/import/check")
def import_check(body: dict = Body(...)):
    """Validate a pasted payload without writing anything."""
    analysis = body.get("analysis") or {}
    questions = body.get("questions") or []
    errs = importer.validate(analysis, questions)
    return {"ok": not errs, "errors": errs,
            "summary": importer.summarise(analysis, questions)}


@app.post("/api/import/lecture")
def import_lecture(body: dict = Body(...)):
    """Bank a hand-authored lecture. No API call is made."""
    try:
        return importer.import_payload(
            body, label=body.get("label"),
            exam_id=body.get("exam_id") or None,
            upload_id=body.get("upload_id") or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/sources")
def list_sources():
    return {"sources": [s.to_dict() for s in _sources.values()]}


@app.delete("/api/sources/{sha}")
def drop_source(sha: str):
    _sources.pop(sha, None)
    return {"ok": True}


def _resolve(shas: list[str]) -> list[Source]:
    picked = [_sources[s] for s in shas if s in _sources]
    if not picked:
        raise HTTPException(
            status_code=400,
            detail="No course files selected. Drop a file first - the server "
                   "forgets uploads when it restarts.",
        )
    return picked


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
def api_analyze(body: dict = Body(...)):
    sources = _resolve(body.get("shas", []))
    result = _guard(generate.analyze, sources)
    result["shas"] = [s.sha for s in sources]
    return result


@app.post("/api/questions")
def api_questions(body: dict = Body(...)):
    """Generate one batch. The browser drives the loop so it can show progress."""
    sources = _resolve(body.get("shas", []))
    concepts = body.get("concepts") or []
    budget = int(body.get("budget") or 0)
    if not concepts or budget < 1:
        raise HTTPException(status_code=400, detail="Nothing to generate in this batch.")
    return {"questions": _guard(generate.questions, sources, concepts, budget)}


@app.post("/api/plan")
def api_plan(body: dict = Body(...)):
    """Split concepts into batches for a chosen total. Pure arithmetic."""
    concepts = body.get("concepts") or []
    total = int(body.get("total") or 0)
    if not concepts or total < 1:
        raise HTTPException(status_code=400, detail="Need concepts and a total.")
    return {
        "batches": [
            {"concepts": chunk, "budget": budget}
            for chunk, budget in generate.batches(concepts, total)
        ]
    }


@app.post("/api/sheet")
def api_sheet(body: dict = Body(...)):
    sources = _resolve(body.get("shas", []))
    return {"markdown": _guard(generate.study_sheet, sources, body.get("focus"))}


@app.post("/api/review")
def api_review(body: dict = Body(...)):
    results = body.get("results") or []
    if not results:
        raise HTTPException(status_code=400, detail="No answered questions to review.")
    return _guard(generate.review, results)


@app.post("/api/resources")
def api_resources(body: dict = Body(...)):
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Give a topic to search for.")
    return _guard(resources.find, topic, body.get("context", ""))


# ---------------------------------------------------------------------------
# Saved sessions
# ---------------------------------------------------------------------------

@app.post("/api/sessions")
def save_session(body: dict = Body(...)):
    sid = body.get("id") or f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    body["id"] = sid
    body["saved_at"] = time.time()
    (SESSIONS / f"{sid}.json").write_text(
        json.dumps(body, indent=2), encoding="utf-8"
    )
    return {"id": sid}


@app.get("/api/sessions")
def list_sessions():
    out = []
    for p in sorted(SESSIONS.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "id": d.get("id", p.stem),
            "title": d.get("title", "Untitled"),
            "saved_at": d.get("saved_at"),
            "count": len(d.get("questions", [])),
            "score": d.get("score"),
        })
    return {"sessions": out}


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    p = SESSIONS / f"{Path(sid).name}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="No such session.")
    return json.loads(p.read_text(encoding="utf-8"))


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    (SESSIONS / f"{Path(sid).name}.json").unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Static front end (mounted last so it doesn't shadow /api)
# ---------------------------------------------------------------------------

FRONTEND = ROOT / "frontend"


@app.middleware("http")
async def no_stale_assets(request, call_next):
    """Never serve a cached front end.

    This app gets edited in place. A browser holding yesterday's app.js against
    today's API fails in ways that look like real bugs, and on localhost the
    revalidation costs nothing.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


THEMES = ("auto", "light", "dark", "mono")
THEME_KEY = "theme"


def current_theme() -> str:
    row = db.q1("SELECT value FROM meta WHERE key = ?", THEME_KEY)
    value = row["value"] if row else "auto"
    return value if value in THEMES else "auto"


@app.get("/api/theme")
def get_theme():
    return {"theme": current_theme(), "options": list(THEMES)}


@app.post("/api/theme")
def set_theme(body: dict = Body(...)):
    theme = body.get("theme", "auto")
    if theme not in THEMES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown theme: {theme}. One of {list(THEMES)}.")
    db.run("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
           THEME_KEY, theme)
    return {"theme": theme}


@app.get("/")
def index():
    """Serve the shell with the chosen theme already on <html>.

    Injected server-side rather than applied by script, so there is no flash of
    the wrong theme. It cannot come from localStorage either: the desktop
    launcher picks a free port on every start, so the origin changes and
    per-origin storage would be empty nearly every time.
    """
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    theme = current_theme()
    if theme != "auto":
        html = html.replace('<html lang="en">',
                            f'<html lang="en" data-theme="{theme}">', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=str(FRONTEND)), name="static")
