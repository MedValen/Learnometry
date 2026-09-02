"""
Routes for who is using the app, which keys it uses, and the profile builder.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .apierr import detail as _detail, guard as _guard
from . import keys, learner_profile, notes_memory, screener, users

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ users

@router.get("/users")
def list_users():
    return {"users": users.listing(), "active": users.active()}


@router.post("/users")
def create_user(body: dict = Body(...)):
    return _guard(users.create, body.get("name", ""),
                  profile=body.get("profile"),
                  profile_kind=body.get("profile_kind", "none"))


@router.get("/users/me")
def me():
    """Whoever is active, plus how their profile is shaping the app."""
    user = users.active()
    return {"user": user, "profile": users.profile_summary(user),
            "report_fields": users.REPORT_FIELDS}


@router.post("/users/{uid}/active")
def activate(uid: str):
    return _guard(users.set_active, uid)


@router.patch("/users/{uid}")
def patch_user(uid: str, body: dict = Body(...)):
    return _guard(users.update, uid, **body)


@router.delete("/users/{uid}")
def delete_user(uid: str):
    _guard(users.remove, uid)
    return {"ok": True}


@router.post("/users/{uid}/photo")
async def upload_photo(uid: str, file: UploadFile = File(...)):
    tmp = Path(tempfile.mkdtemp()) / Path(file.filename or "photo.png").name
    try:
        with tmp.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        return _guard(users.set_photo, uid, tmp, file.filename or tmp.name)
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/users/{uid}/photo")
def get_photo(uid: str):
    try:
        path = users.photo_path(uid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_detail(exc))
    if not path.exists():
        raise HTTPException(status_code=404, detail="That photo is missing from disk.")
    return FileResponse(path)


@router.delete("/users/{uid}/photo")
def delete_photo(uid: str):
    return _guard(users.clear_photo, uid)


# ------------------------------------------------------------- profile

@router.post("/users/{uid}/profile/report")
def save_report(uid: str, body: dict = Body(...)):
    """Scores from a real neuropsychological evaluation."""
    indexes = {k: v for k, v in (body.get("indexes") or {}).items()
               if str(v).strip() != ""}
    subtests = {k: v for k, v in (body.get("subtests") or {}).items()
                if str(v).strip() != ""}
    if not indexes and not subtests:
        raise HTTPException(
            status_code=400,
            detail="Enter at least one score. Blank is better than guessed, but "
                   "an empty report tells the app nothing.")

    profile = {
        "indexes": indexes, "subtests": subtests,
        "accommodations": body.get("accommodations") or [],
        "notes": body.get("notes", ""),
        "source": body.get("source", "Entered from a formal evaluation."),
    }
    return _guard(users.update, uid, profile=profile, profile_kind="report")


@router.post("/users/{uid}/profile/clear")
def clear_profile(uid: str):
    return _guard(users.update, uid, profile={}, profile_kind="none")


@router.get("/users/{uid}/profile/preview")
def preview_prompt(uid: str):
    """The contract this profile actually hands the model. Nothing hidden."""
    user = _guard(users.get, uid)
    return {"prompt": learner_profile.for_user(user),
            "kind": user["profile_kind"]}


# ------------------------------------------------------------- screener

@router.get("/screener")
def screener_catalogue():
    return screener.catalogue()


@router.post("/screener/start")
def screener_start(body: dict = Body(default={})):
    return {"run_id": screener.start(body.get("user_id"))}


@router.post("/screener/build")
def screener_build(body: dict = Body(...)):
    return _guard(screener.build, body.get("task", ""),
                  span=int(body.get("span") or 3),
                  rounds=int(body.get("rounds") or 6),
                  seed=body.get("seed"))


@router.post("/screener/record")
def screener_record(body: dict = Body(...)):
    return _guard(screener.record, body.get("run_id", ""),
                  body.get("task", ""), body.get("result") or {})


@router.get("/screener/{run_id}")
def screener_get(run_id: str):
    return _guard(screener.get, run_id)


@router.post("/screener/{run_id}/apply")
def screener_apply(run_id: str, body: dict = Body(default={})):
    """Turn a finished screener run into the active user's profile."""
    run = _guard(screener.get, run_id)
    if not run["profile"].get("tasks"):
        raise HTTPException(
            status_code=400,
            detail="No tasks completed yet — there is nothing to build a profile from.")

    uid = body.get("user_id")
    if not uid:
        user = users.active()
        if not user:
            raise HTTPException(status_code=400, detail="No active user.")
        uid = user["id"]
    return _guard(users.update, uid, profile=run["profile"], profile_kind="screener")


# --------------------------------------------------------------- notes

@router.get("/users/{uid}/notes")
def list_notes(uid: str):
    return {"notes": _guard(notes_memory.listing, uid),
            "kinds": notes_memory.KINDS,
            "prompt_kinds": list(notes_memory.PROMPT_KINDS)}


@router.post("/users/{uid}/notes")
def add_note(uid: str, body: dict = Body(...)):
    note = _guard(notes_memory.add, uid, body.get("text", ""),
                  kind=body.get("kind", "context"))
    learner_profile.invalidate()
    return note


@router.patch("/standing-notes/{nid}")
def patch_note(nid: str, body: dict = Body(...)):
    note = _guard(notes_memory.update, nid, **{
        k: v for k, v in body.items() if k in ("text", "kind", "active")})
    learner_profile.invalidate()
    return note


@router.delete("/standing-notes/{nid}")
def delete_note(nid: str):
    _guard(notes_memory.remove, nid)
    learner_profile.invalidate()
    return {"ok": True}


# ---------------------------------------------------------------- keys

@router.get("/keys")
def list_keys():
    return keys.status()


@router.post("/keys")
def add_key(body: dict = Body(...)):
    return _guard(keys.add, body.get("label", ""), body.get("secret", ""))


@router.patch("/keys/{kid}")
def patch_key(kid: str, body: dict = Body(...)):
    return _guard(keys.update, kid, **body)


@router.delete("/keys/{kid}")
def delete_key(kid: str):
    keys.remove(kid)
    return {"ok": True}


@router.post("/keys/order")
def order_keys(body: dict = Body(...)):
    return {"keys": keys.reorder(body.get("ids") or [])}


@router.post("/keys/wake")
def wake_keys():
    """Clear every cooldown — for when she has topped up and doesn't want to wait."""
    return {"cleared": keys.clear_cooldowns(), "status": keys.status()}


@router.post("/keys/{kid}/test")
def test_key(kid: str):
    """Smallest possible real call, to check a key works before relying on it."""
    from . import claude

    row = _guard(keys.get, kid)

    # Read the row directly rather than searching usable(): a key that is
    # disabled or cooling down is exactly the one you most want to test, and
    # usable() filters both out.
    from . import db as db_mod
    r = db_mod.q1("SELECT secret, workspace_id FROM api_key WHERE id = ?", kid)
    if not r or not r["secret"]:
        raise HTTPException(status_code=404, detail="No such key.")
    secret, workspace_id = r["secret"], r["workspace_id"]

    try:
        client = claude.client(secret, workspace_id)
        client.messages.create(
            model=claude.model_for("key_test"), max_tokens=4,
            messages=[{"role": "user", "content": "hi"}])
        keys.mark_ok(kid)
        return {"ok": True, "label": row["label"],
                "message": "Key works."}
    except Exception as exc:                           # noqa: BLE001
        kind = claude._classify(exc)
        if kind == "invalid":
            keys.mark_invalid(kid, str(exc))
        elif kind == "exhausted":
            keys.mark_exhausted(kid, str(exc))
        return {"ok": False, "label": row["label"], "kind": kind,
                "message": _key_message(kind, row["label"]),
                "detail": str(exc)[:400]}


def _key_message(kind: str, label: str) -> str:
    """A raw SDK traceback is not an answer to "does my key work?".

    The full exception still travels as `detail` - it is the only thing that
    helps when the cause is not one of these three - but the sentence the person
    reads first should say what to do next.
    """
    if kind == "invalid":
        return (f"{label} was rejected. Check it was pasted whole — they are "
                "long, and a copy that stops early looks exactly like this.")
    if kind == "exhausted":
        return (f"{label} reached the API but has no credit or is rate-limited. "
                "It will be skipped for a while, then tried again.")
    if kind == "workspace":
        # Nothing is wrong with the key. It authenticated fine and was refused
        # for a missing field, so "check the connection" would send someone
        # looking in exactly the wrong place.
        return (f"{label} is valid, but it is an identity-linked key: every "
                "request has to name the workspace it acts in. Click "
                "'Workspace…' on this key and paste its Workspace ID from the "
                "Anthropic Console (Settings → Workspaces). It looks like "
                "wrkspc_…")
    return (f"{label} could not be checked — the request itself failed. "
            "That is usually the connection, not the key.")

