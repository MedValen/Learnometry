"""
Several API keys, tried in order.

One key runs out mid-session and the app stops working. That is a bad failure
for a study tool: she is three questions into a set at eleven at night and it
dies. So keys are a list, not a value.

  * PRIORITY decides the order. Lower first.
  * A key that is out of credit or rate-limited gets a COOLDOWN and the next
    one is tried immediately, in the same request.
  * A key that is actually invalid is disabled, because retrying a bad key on
    every call just makes everything slower.
  * The .env key still works and is used as a fallback when the list is empty,
    so nothing breaks for an existing install.

Keys are stored in the local database in plain text, the same way a .env file
stores one. This is a single-user desktop app and the database lives in her own
profile directory; the meaningful protection is the machine login, not
encryption we would have to keep the key for anyway. Keys are never sent to the
browser - the UI only ever sees a masked hint.
"""

from __future__ import annotations

import os
import time
import uuid

from . import db

# How long a key sits out after being rate-limited or running dry.
COOLDOWN_SECONDS = 15 * 60


def mask(secret: str) -> str:
    """Enough to tell two keys apart, not enough to use one.

    Every Anthropic key starts `sk-ant-api03-`, so a leading fragment says
    nothing about WHICH key this is - the whole job of the hint. The tail is the
    part that differs, so that is the part shown.
    """
    if not secret:
        return ""
    if len(secret) <= 12:
        return secret[:2] + "…"
    return f"…{secret[-8:]}"


def add(label: str, secret: str, priority: int | None = None,
        workspace_id: str | None = None) -> dict:
    secret = (secret or "").strip()
    if not secret:
        raise ValueError("Paste the key itself, not just a name for it.")
    if not label.strip():
        label = f"Key {mask(secret)}"

    if priority is None:
        row = db.q1("SELECT COALESCE(MAX(priority), -1) m FROM api_key")
        # `or` is wrong here: a max of 0 is falsy, so the second key would fall
        # back to -1 and land on priority 0 alongside the first.
        current = row["m"] if row and row["m"] is not None else -1
        priority = int(current) + 1

    kid = f"key_{uuid.uuid4().hex[:8]}"
    db.run(
        "INSERT INTO api_key (id, label, secret, priority, enabled, created_at, "
        "workspace_id) VALUES (?,?,?,?,1,?,?)",
        kid, label.strip(), secret, priority, time.time(),
        (workspace_id or "").strip() or None,
    )
    return get(kid)


def get(kid: str) -> dict:
    row = db.q1("SELECT * FROM api_key WHERE id = ?", kid)
    if row is None:
        raise KeyError(f"no such key: {kid}")
    return _public(row)


def _public(row) -> dict:
    """Everything about a key except the key."""
    now = time.time()
    cooling = bool(row["cooldown_until"] and row["cooldown_until"] > now)
    return {
        "id": row["id"], "label": row["label"], "hint": mask(row["secret"]),
        "workspace_id": row["workspace_id"],
        "priority": row["priority"], "enabled": bool(row["enabled"]),
        "uses": row["uses"], "last_ok": row["last_ok"],
        "last_error": row["last_error"],
        "cooling_down": cooling,
        "cooldown_remaining": int(row["cooldown_until"] - now) if cooling else 0,
        "status": ("disabled" if not row["enabled"]
                   else "cooling down" if cooling
                   else "ready"),
    }


def listing() -> list[dict]:
    return [_public(r) for r in db.q(
        "SELECT * FROM api_key ORDER BY priority, created_at")]


def usable() -> list[tuple[str, str, str | None]]:
    """(id, secret, workspace_id) in the order they should be tried."""
    now = time.time()
    out = []
    for r in db.q("SELECT * FROM api_key WHERE enabled = 1 ORDER BY priority, created_at"):
        if r["cooldown_until"] and r["cooldown_until"] > now:
            continue
        out.append((r["id"], r["secret"], r["workspace_id"]))

    if not out:
        # Nothing configured, or everything is cooling down. Fall back to the
        # environment so an existing .env install keeps working untouched.
        env = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
        if env:
            out.append(("env", env, os.getenv("ANTHROPIC_WORKSPACE_ID") or None))
    return out


def update(kid: str, **fields) -> dict:
    sets, vals = [], []
    for k in ("label", "priority", "enabled", "workspace_id"):
        if k in fields:
            sets.append(f"{k} = ?")
            if k in ("priority", "enabled"):
                vals.append(int(fields[k]))
            elif k == "workspace_id":
                vals.append((fields[k] or "").strip() or None)
            else:
                vals.append(fields[k])
    if "secret" in fields and (fields["secret"] or "").strip():
        sets.append("secret = ?")
        vals.append(fields["secret"].strip())
        # A replaced key deserves a clean slate.
        sets += ["last_error = NULL", "cooldown_until = NULL", "enabled = 1"]
    if sets:
        db.run(f"UPDATE api_key SET {', '.join(sets)} WHERE id = ?", *vals, kid)
    return get(kid)


def remove(kid: str) -> None:
    db.run("DELETE FROM api_key WHERE id = ?", kid)


def reorder(ids: list[str]) -> list[dict]:
    for i, kid in enumerate(ids):
        db.run("UPDATE api_key SET priority = ? WHERE id = ?", i, kid)
    return listing()


# ------------------------------------------------------------- outcomes

def mark_ok(kid: str) -> None:
    if kid == "env":
        return
    db.run(
        "UPDATE api_key SET last_ok = ?, uses = uses + 1, last_error = NULL, "
        "cooldown_until = NULL WHERE id = ?", time.time(), kid)


def mark_exhausted(kid: str, reason: str) -> None:
    """Out of credit or rate-limited: rest it, don't disable it."""
    if kid == "env":
        return
    db.run(
        "UPDATE api_key SET cooldown_until = ?, last_error = ? WHERE id = ?",
        time.time() + COOLDOWN_SECONDS, reason[:300], kid)


def mark_invalid(kid: str, reason: str) -> None:
    """Genuinely bad key. Retrying it on every call only adds latency."""
    if kid == "env":
        return
    db.run(
        "UPDATE api_key SET enabled = 0, last_error = ? WHERE id = ?",
        reason[:300], kid)


def clear_cooldowns() -> int:
    cur = db.run(
        "UPDATE api_key SET cooldown_until = NULL WHERE cooldown_until IS NOT NULL")
    return cur.rowcount


def status() -> dict:
    keys = listing()
    ready = [k for k in keys if k["status"] == "ready"]
    env = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    return {
        "keys": keys,
        "ready": len(ready),
        "total": len(keys),
        "env_fallback": env,
        "usable": bool(ready or env),
        "cooldown_minutes": COOLDOWN_SECONDS // 60,
    }
