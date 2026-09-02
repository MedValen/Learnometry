"""
Phase 3 routes: organisation, vault, pinboard, exam intel, study plans.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from .apierr import detail as _detail, guard as _guard
from . import db  # noqa: E402

from . import (anki, backup, book, claude, coach, drills, notes, organizer,
               pinboard, planner, scope as scope_mod, tactics, vault)

router = APIRouter(prefix="/api")


# _detail and _guard now live in backend/apierr.py, imported above. They were
# duplicated in three modules and had drifted: app.py's copy handled neither
# KeyError nor ValueError, so its routes answered a missing id with a 500.


# ------------------------------------------------------- terms & courses

@router.get("/terms")
def get_terms():
    return {"terms": organizer.list_terms()}


@router.post("/terms")
def post_term(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the term a name.")
    return organizer.create_term(
        name, body.get("starts", ""), body.get("ends", ""),
        bool(body.get("active", True)))


@router.get("/terms/{tid}")
def get_term(tid: str):
    return _guard(organizer.get_term, tid)


@router.post("/terms/{tid}/active")
def activate_term(tid: str):
    organizer.set_active_term(tid)
    return {"ok": True}


@router.delete("/terms/{tid}")
def del_term(tid: str):
    organizer.delete_term(tid)
    return {"ok": True}


@router.get("/courses")
def get_courses(term_id: str | None = None):
    return {"courses": organizer.list_courses(term_id)}


@router.post("/courses")
def post_course(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the course a name.")
    return organizer.create_course(body.get("term_id"), name, body.get("code", ""))


@router.delete("/courses/{cid}")
def del_course(cid: str):
    organizer.delete_course(cid)
    return {"ok": True}


# ------------------------------------------------------------------ exams

@router.get("/exams")
def get_exams(term_id: str | None = None, upcoming: bool = False):
    return {"exams": organizer.list_exams(term_id, upcoming_only=upcoming)}


@router.post("/exams")
def post_exam(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    when = (body.get("date") or "").strip()
    if not name or not when:
        raise HTTPException(status_code=400, detail="An exam needs a name and a date.")
    if organizer.days_until(when) is None:
        raise HTTPException(status_code=400, detail="Use a date like 2026-09-14.")
    return organizer.create_exam(
        name, when,
        term_id=body.get("term_id"), course_id=body.get("course_id"),
        kind=body.get("kind", "exam"),
        topic_ids=body.get("topic_ids"), concept_ids=body.get("concept_ids"),
        notes=body.get("notes", ""))


@router.get("/exams/{eid}")
def get_exam(eid: str):
    return _guard(organizer.get_exam, eid)


@router.patch("/exams/{eid}")
def patch_exam(eid: str, body: dict = Body(...)):
    return _guard(organizer.update_exam, eid, **body)


@router.delete("/exams/{eid}")
def del_exam(eid: str):
    organizer.delete_exam(eid)
    return {"ok": True}


@router.get("/exams/{eid}/readiness")
def exam_readiness(eid: str):
    return _guard(organizer.readiness, eid)


@router.get("/exams/{eid}/concepts")
def exam_concepts(eid: str):
    return {"concepts": _guard(organizer.exam_concepts, eid)}


@router.get("/topic-search")
def topic_search(q: str = "", limit: int = 12):
    return {"results": organizer.suggest_topics(q, limit)}


# ------------------------------------------------------------------ vault

@router.post("/vault/upload")
async def vault_upload(
    files: list[UploadFile] = File(...),
    kind: str = Form("photo"),
    caption: str = Form(""),
    link_kind: str = Form(""),
    link_target: str = Form(""),
):
    out, errors = [], []
    links = ([{"kind": link_kind, "target_id": link_target}]
             if link_kind and link_target else [])

    for f in files:
        tmp = Path(tempfile.mkdtemp()) / Path(f.filename or "upload").name
        try:
            with tmp.open("wb") as fh:
                shutil.copyfileobj(f.file, fh)
            out.append(vault.add(tmp, original_name=f.filename or tmp.name,
                                 kind=kind, caption=caption, links=links))
        except vault.Rejected as exc:
            errors.append(str(exc))
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"{f.filename}: {type(exc).__name__}: {exc}")
        finally:
            tmp.unlink(missing_ok=True)

    if not out and errors:
        raise HTTPException(status_code=400, detail=" | ".join(errors))
    return {"assets": out, "errors": errors}


@router.get("/vault")
def vault_list(kind: str | None = None, link_kind: str | None = None,
               target_id: str | None = None):
    return {"assets": vault.listing(kind=kind, link_kind=link_kind,
                                    target_id=target_id)}


@router.get("/vault/{aid}/file")
def vault_file(aid: str):
    try:
        path = vault.file_path(aid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not path.exists():
        raise HTTPException(status_code=404, detail="That file is missing from disk.")
    return FileResponse(path)


@router.patch("/vault/{aid}")
def vault_update(aid: str, body: dict = Body(...)):
    return _guard(vault.update, aid, caption=body.get("caption"), kind=body.get("kind"))


@router.post("/vault/{aid}/link")
def vault_link(aid: str, body: dict = Body(...)):
    vault.attach(aid, body.get("kind", ""), body.get("target_id", ""))
    return _guard(vault.get, aid)


@router.delete("/vault/{aid}/link")
def vault_unlink(aid: str, body: dict = Body(...)):
    vault.detach(aid, body.get("kind", ""), body.get("target_id", ""))
    return _guard(vault.get, aid)


@router.post("/vault/{aid}/analyse")
def vault_analyse(aid: str):
    """Read a whiteboard or question photo. Explicitly requested, never automatic."""
    return _guard(vault.analyse, aid)


@router.delete("/vault/{aid}")
def vault_delete(aid: str):
    vault.remove(aid)
    return {"ok": True}


# --------------------------------------------------------------- pinboard

@router.get("/pins")
def get_pins(kind: str | None = None, exam_id: str | None = None,
             tag: str | None = None, starred: bool = False,
             archived: bool = False):
    return {
        "pins": pinboard.listing(kind=kind, exam_id=exam_id, tag=tag,
                                 starred_only=starred, include_archived=archived),
        "tags": pinboard.all_tags(),
    }


@router.post("/pins")
def post_pin(body: dict = Body(...)):
    return _guard(
        pinboard.create,
        kind=body.get("kind", "note"), title=body.get("title", ""),
        body=body.get("body", ""), asset_id=body.get("asset_id"),
        concept_id=body.get("concept_id"), exam_id=body.get("exam_id"),
        course_id=body.get("course_id"), tags=body.get("tags"),
        starred=bool(body.get("starred")))


@router.patch("/pins/{pid}")
def patch_pin(pid: str, body: dict = Body(...)):
    return _guard(pinboard.update, pid, **body)


@router.delete("/pins/{pid}")
def del_pin(pid: str):
    pinboard.remove(pid)
    return {"ok": True}


# ------------------------------------------------------------ exam intel

@router.get("/emphasis")
def get_emphasis(exam_id: str | None = None, course_id: str | None = None):
    return {"notes": coach.list_notes(exam_id, course_id),
            "said_by": coach.SAID_BY,
            "strengths": list(coach.STRENGTH_BOOST)}


@router.post("/emphasis")
def post_emphasis(body: dict = Body(...)):
    return _guard(
        coach.add_note, body.get("text", ""),
        exam_id=body.get("exam_id"), course_id=body.get("course_id"),
        said_by=body.get("said_by", "professor"),
        strength=body.get("strength", "mentioned"),
        auto_link=bool(body.get("auto_link", True)))


@router.post("/emphasis/{nid}/link")
def relink_emphasis(nid: str):
    return _guard(coach.link_note, nid)


@router.post("/emphasis/{nid}/apply")
def apply_emphasis(nid: str, body: dict = Body(default={})):
    return _guard(coach.apply_note, nid, bool(body.get("apply", True)))


@router.delete("/emphasis/{nid}")
def del_emphasis(nid: str):
    _guard(coach.delete_note, nid)
    return {"ok": True}


# ------------------------------------------------------------ conversation

@router.get("/chats")
def get_chats(exam_id: str | None = None):
    return {"chats": coach.list_conversations(exam_id)}


@router.post("/chats")
def post_chat(body: dict = Body(...)):
    return coach.start_conversation(body.get("exam_id"), body.get("title", ""))


@router.get("/chats/{cid}")
def get_chat(cid: str):
    return _guard(coach.get_conversation, cid)


@router.post("/chats/{cid}/send")
def send_chat(cid: str, body: dict = Body(...)):
    return _guard(coach.send, cid, body.get("text", ""))


@router.delete("/chats/{cid}")
def del_chat(cid: str):
    coach.delete_conversation(cid)
    return {"ok": True}


# ------------------------------------------------------------ study plans

@router.post("/plan/build")
def build_plan(body: dict = Body(...)):
    eid = body.get("exam_id")
    if not eid:
        raise HTTPException(status_code=400, detail="Pick an exam first.")
    return _guard(
        planner.build, eid,
        minutes_per_day=int(body.get("minutes_per_day") or 60),
        days_off=body.get("days_off"))


@router.post("/plan/strategy")
def plan_strategy(body: dict = Body(...)):
    """Narrative advice for an already-computed plan. Never recomputes numbers."""
    plan = body.get("plan")
    if not plan:
        eid = body.get("exam_id")
        plan = planner.latest(eid) if eid else None
    if not plan:
        raise HTTPException(status_code=400, detail="Build a plan first.")
    return _guard(planner.strategy, plan)


@router.get("/plan/latest")
def latest_plan(exam_id: str):
    plan = planner.latest(exam_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan built for this exam yet.")
    return plan


# ------------------------------------------------------------------ drills

@router.post("/drills")
def list_drills(body: dict = Body(default={})):
    """Which drills can be built from what's currently in scope."""
    sc = scope_mod.Scope.from_dict(body.get("scope")) if body.get("scope") else None
    return drills.available(sc)


@router.post("/drills/build")
def build_drill(body: dict = Body(...)):
    name = body.get("drill") or ""
    sc = scope_mod.Scope.from_dict(body.get("scope")) if body.get("scope") else None
    return _guard(
        drills.build, name,
        rounds=max(1, min(20, int(body.get("rounds") or 6))),
        scope=sc,
        span=int(body.get("span") or 3))


@router.post("/drills/result")
def post_drill_result(body: dict = Body(...)):
    return _guard(
        drills.record, body.get("drill") or "",
        score=float(body.get("score") or 0),
        rounds=int(body.get("rounds") or 0),
        correct=int(body.get("correct") or 0),
        span=body.get("span"), ms=body.get("ms"),
        concept_ids=body.get("concept_ids"), detail=body.get("detail"))


@router.get("/drills/history")
def drill_history(drill: str | None = None):
    return drills.history(drill)


# ------------------------------------------------------------------- notes

@router.post("/notes/review")
def review_notes(body: dict = Body(...)):
    """Measure her notes, then critique them. Measurement works offline."""
    return _guard(
        notes.review, body.get("body", ""),
        title=body.get("title", ""),
        source=body.get("source", "paste"),
        asset_id=body.get("asset_id"),
        want_critique=bool(body.get("critique", True)))


@router.post("/notes/{rid}/critique")
def critique_notes(rid: str):
    return _guard(notes.critique, rid)


@router.get("/notes")
def notes_history():
    return notes.history()


@router.get("/notes/sources")
def note_sources():
    """Vault files that can be critiqued as notes."""
    return {"assets": notes.reviewable_assets()}


@router.post("/notes/from-asset")
def note_from_asset(body: dict = Body(...)):
    aid = body.get("asset_id")
    if not aid:
        raise HTTPException(status_code=400, detail="Pick a file first.")
    return _guard(notes.from_asset, aid,
                  want_critique=bool(body.get("critique", True)))


@router.post("/notes/upload")
async def note_upload(file: UploadFile = File(...), critique: str = Form("true")):
    """Read a document straight into a review without storing it in the vault."""
    tmp = Path(tempfile.mkdtemp()) / Path(file.filename or "notes.txt").name
    try:
        with tmp.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        body = _guard(notes.text_from_file, tmp, file.filename or tmp.name)
        return _guard(notes.review, body, title=file.filename or "",
                      source="upload",
                      want_critique=critique.lower() not in ("false", "0"))
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/notes/{rid}")
def get_note_review(rid: str):
    return _guard(notes.get, rid)


@router.delete("/notes/{rid}")
def delete_note_review(rid: str):
    notes.delete(rid)
    return {"ok": True}


# ----------------------------------------------------------------- tactics

@router.post("/tactics/dissect")
def dissect(body: dict = Body(...)):
    """Split a stem into ask / signal / padding. Pure heuristics, no API."""
    stem = body.get("stem") or ""
    if not stem.strip() and body.get("question_id"):
        row = db.q1("SELECT stem, premise_table FROM question WHERE id = ?",
                    body["question_id"])
        if row:
            stem = row["stem"]
            if row["premise_table"]:
                stem += chr(10) * 2 + row["premise_table"]
    if not stem.strip():
        raise HTTPException(status_code=400, detail="Nothing to dissect.")
    return tactics.dissect(stem)


@router.post("/tactics/explain")
def explain_question(body: dict = Body(...)):
    qid = body.get("question_id")
    if not qid:
        raise HTTPException(status_code=400, detail="question_id is required.")
    return _guard(tactics.explain, qid)


@router.get("/tactics/playbook")
def playbook():
    return {"playbook": tactics.PLAYBOOK,
            "timers": tactics.TIMER_PRESETS,
            "base_seconds": tactics.BASE_SECONDS_PER_QUESTION}


@router.post("/tactics/timing")
def timing(body: dict = Body(default={})):
    return tactics.timing_guidance(body.get("seconds"))


# ------------------------------------------------------------- textbook

# A full scan walks 849 pages and takes a while, so the result is cached per
# path. She scans once and then ingests sections at her own pace.
_SCANS: dict[str, dict] = {}


@router.post("/book/scan")
def book_scan(body: dict = Body(...)):
    """Segment a textbook locally. No upload, no API call, no network."""
    raw = (body.get("path") or "").strip().strip('"')
    if not raw:
        raise HTTPException(status_code=400, detail="Give the path to the PDF.")
    pdf = Path(raw)
    if not pdf.exists():
        raise HTTPException(status_code=404, detail=f"No file at {pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="That isn't a PDF.")

    try:
        result = book.scan(pdf)
    except Exception as exc:                          # noqa: BLE001
        raise HTTPException(status_code=400,
                            detail=f"Couldn't read that PDF: {exc}")

    result["signals"] = book.yield_signals(result, pdf)
    result["path"] = str(pdf)
    result["title"] = body.get("title") or pdf.stem
    _SCANS[str(pdf)] = result

    existing = db.q1("SELECT id FROM source WHERE filename = ? AND kind = 'textbook'",
                     pdf.name)
    result["source_id"] = existing["id"] if existing else book.register(
        pdf, result["title"], result["pages"])
    result["already_ingested"] = book.ingested(result["source_id"])

    # The signals payload is large and only the counts are useful in the UI.
    result["signals"] = {
        "rapid_review_ranges": len(result["signals"]["rapid_pages"]),
        "recurring_disciplines": len(result["signals"]["recurrence"]),
    }
    return result


@router.post("/book/ingest")
def book_ingest(body: dict = Body(...)):
    """Extract concepts from ONE section. The browser drives the loop."""
    path = (body.get("path") or "").strip()
    index = body.get("section_index")
    scan = _SCANS.get(path)
    if scan is None:
        raise HTTPException(status_code=409,
                            detail="Scan the book first - the segmentation is "
                                   "held per session.")
    try:
        section = scan["sections"][int(index)]
    except (TypeError, ValueError, IndexError):
        raise HTTPException(status_code=400, detail="No such section.")

    pdf = Path(path)
    signals = book.yield_signals(scan, pdf)
    return _guard(book.extract_section, pdf, section, signals, scan["source_id"])


@router.get("/book/sources")
def book_sources():
    return {"sources": book.sources()}


# ---------------------------------------------------------------- anki

@router.get("/anki/selections")
def anki_selections():
    """The named selections, with live counts so empty ones are visible."""
    return {"selections": [{"id": k, "label": v} for k, v in anki.SELECTIONS.items()],
            "counts": anki.preview_counts()}


@router.post("/anki/export")
def anki_export(body: dict = Body(...)):
    sc = scope_mod.Scope.from_dict(body.get("scope")) if body.get("scope") else None
    return _guard(
        anki.export, body.get("selection") or "red_orange",
        concept_ids=body.get("concept_ids"),
        limit=max(1, min(300, int(body.get("limit") or 60))),
        scope=sc,
        use_claude=bool(body.get("use_claude", True)))


@router.post("/anki/rebuild")
def anki_rebuild(body: dict = Body(...)):
    """Re-render the TSV after she edits cards in the preview."""
    cards = body.get("cards") or []
    concepts = body.get("concept_list") or []
    if not cards:
        raise HTTPException(status_code=400, detail="No cards to export.")
    return {"tsv": anki.rebuild_tsv(cards, concepts), "cards": len(cards)}


# ------------------------------------------------------------------ backup

@router.get("/backups")
def list_backups():
    return {"backups": backup.listing(), "keep": backup.KEEP}


@router.post("/backups")
def make_backup():
    return _guard(backup.take, "manual")


@router.post("/backups/restore")
def restore_backup(body: dict = Body(...)):
    """Swap in a backup. The current database is snapshotted first."""
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Pick a backup to restore.")
    return _guard(backup.restore, name)


@router.get("/backups/download")
def download_db():
    """The live database as a file she can put somewhere else."""
    data = backup.db_bytes()
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"Content-Disposition":
                 'attachment; filename="learnometry.db"'})


@router.get("/backups/export.json")
def export_json():
    """Portable export that does not need this app to be readable."""
    return Response(
        content=backup.export_bytes(), media_type="application/json",
        headers={"Content-Disposition":
                 'attachment; filename="learnometry-export.json"'})
