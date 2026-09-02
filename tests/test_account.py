"""
Tests for users, per-user profiles, the screener, and API key failover.

All offline. Run:  python tests/test_account.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import (  # noqa: E402
    claude, db, keys, learner_profile, screener, taxonomy, users,
)

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()

    # ============================== users ==============================
    print("\n-- users --")
    first = users.ensure_default()
    check("an account is created on an empty install", first is not None)
    check("but it ships with NO profile - a shipped one would be either "
          "invented or somebody's real clinical record",
          first["profile_kind"] == "none" and not first["profile"])
    check("seeding is idempotent", users.ensure_default() is None)

    blank = learner_profile.for_user(first)
    check("so a fresh install claims nothing about the person using it",
          "Do not invent characteristics" in blank)

    # A synthetic report with the shape these checks are really about: visual
    # working memory intact, auditory working memory well below it.
    seeded = users.update(first["id"], profile=SYNTHETIC_REPORT,
                          profile_kind="report")

    her_prompt = learner_profile.for_user(seeded)
    check("a visual-over-auditory report routes visually",
          "Route everything through what can be seen" in her_prompt)
    check("and caps elements",
          "3-4 new elements" in her_prompt)
    check("and forbids simplifying the level",
          "Simplify the load, never the level" in her_prompt)

    second = users.create("Sam")
    check("a second user can be added", second["name"] == "Sam")
    check("adding a user makes them active", second["active"] is True)
    check("only one user is active at a time",
          sum(1 for u in users.listing() if u["active"]) == 1)
    check("a new user starts with no profile", second["profile_kind"] == "none")

    generic = learner_profile.for_user(second)
    check("no profile means no invented characteristics",
          "Do not invent characteristics" in generic)
    check("a profile-less user still gets the universal rules",
          "NO NAKED LISTS OF FIVE" in generic)

    check("an unnamed user is refused", _raises(lambda: users.create("  "), ValueError))

    users.set_active(seeded["id"])
    check("switching back works", users.active()["id"] == seeded["id"])

    # Deleting a person must never delete answers.
    before = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    users.remove(second["id"])
    check("deleting a user leaves study history alone",
          db.q1("SELECT COUNT(*) n FROM attempt")["n"] == before)
    check("deleting the active user promotes another",
          users.active() is not None)

    # --- report entry ---------------------------------------------------
    u = users.create("Report User")
    users.update(u["id"], profile_kind="report", profile={
        "indexes": {"WMI": 118, "VCI": 96},
        "subtests": {"Symbol Span": 7, "Digits Forward": 13},
        "accommodations": [],
    })
    prompt = learner_profile.for_user(users.get(u["id"]))
    check("a different report produces a different routing",
          "Auditory working memory" in prompt and
          "Route everything through what can be seen" not in prompt,
          prompt[:0])
    check("a high WMI is not told to cap at 3-4 elements",
          "Never require more than 3-4" not in prompt)

    # --- the Profile screen reads from whoever is signed in -------------
    print("\n-- profile digest --")
    users.set_active(seeded["id"])
    dig = learner_profile.profile_digest(seeded)
    check("the digest names the person it describes",
          dig["name"] == users.DEFAULT_NAME)
    check("the digest carries their scores", dig["subtests"]["Symbol Span"] == 11)

    # The seven rows used to be a hard-coded list. They now regenerate from the
    # stored scores, and the point of this check is that nothing was lost when
    # they stopped being hard-coded.
    findings = {l["finding"] for l in dig["levers"]}
    for expected in ("Visual working memory intact",
                     "Auditory working memory very low",
                     "Registration itself reduced",
                     "Reasoning intact",
                     "Switching is a strength",
                     "Naming is slow",
                     "Formal accommodations"):
        check(f"still derived: {expected.lower()}", expected in findings)
    scores = {l["finding"]: l["score"] for l in dig["levers"]}
    check("the percentile is computed, not copied",
          scores["Auditory working memory very low"] == "AWMI-R = 78 (7th %ile)",
          scores["Auditory working memory very low"])
    check("the accommodations reach the table",
          "Extended time" in scores["Formal accommodations"])

    # A different report must produce a different table.
    other = users.create("Other Student", profile_kind="report", profile={
        "indexes": {"WMI": 118, "VCI": 88},
        "subtests": {"Symbol Span": 5, "Inhibition/Switching": 4},
    })
    od = learner_profile.profile_digest(other)
    of = {l["finding"]: l["rule"] for l in od["levers"]}
    check("a low Symbol Span is not called intact",
          "Visual working memory reduced" in of)
    check("a high WMI is not called very low",
          "Auditory working memory workable" in of)
    check("weak switching is not sold as a strength",
          "Switching costs her" in of and
          "One topic at a time" in of["Switching costs her"])
    check("a score that is absent produces no row",
          not any("Naming" in f for f in of))

    blank = users.create("Blank Student")
    bd = learner_profile.profile_digest(blank)
    check("no scores means no rows at all", bd["levers"] == [])
    check("and the screen says why", "No scores on file" in bd["caveat"])
    users.remove(other["id"])
    users.remove(blank["id"])
    users.set_active(seeded["id"])

    # ============================= screener ============================
    print("\n-- screener --")
    cat = screener.catalogue()
    check("four tasks offered", len(cat["tasks"]) == 4)
    check("the disclaimer says what this is not",
          "not the WAIS-5" in cat["disclaimer"])
    check("the disclaimer refuses IQ and percentiles",
          "IQ" in cat["disclaimer"] and "percentile" in cat["disclaimer"])
    check("it points at a real evaluation as better evidence",
          "neuropsychological evaluation" in cat["disclaimer"])

    vis = screener.build("visual_span", span=4, rounds=5, seed=1)
    check("visual span builds rounds", len(vis["rounds"]) == 5)
    check("visual span sequences match the span",
          all(len(r["sequence"]) == 4 for r in vis["rounds"]))
    check("visual span indexes are inside the grid",
          all(max(r["sequence"]) < len(r["grid"]) for r in vis["rounds"]))

    spo = screener.build("spoken_span", span=4, rounds=5, seed=1)
    check("spoken span builds words",
          all(len(r["words"]) == 4 for r in spo["rounds"]))
    check("spoken words are never repeated within a round",
          all(len(set(r["words"])) == len(r["words"]) for r in spo["rounds"]))

    nam = screener.build("naming", rounds=6, seed=1)
    check("naming items carry an answer",
          all(r["answer"] for r in nam["rounds"]))

    swi = screener.build("switching", rounds=12, seed=1)
    check("switching builds rounds", len(swi["rounds"]) >= 12)
    check("the rule actually changes",
          len({r["rule"] for r in swi["rounds"]}) > 1)
    check("switch trials are flagged",
          any(r["switched"] for r in swi["rounds"]))
    check("every answer is one of the offered options",
          all(r["answer"] in r["options"] for r in swi["rounds"]))

    check("an unknown task is refused",
          _raises(lambda: screener.build("telepathy"), ValueError))

    # --- scoring is within-person only ----------------------------------
    scored = screener.score({
        "visual_span": {"best_span": 6, "rounds": 6, "accuracy": 0.8},
        "spoken_span": {"best_span": 3, "rounds": 6, "accuracy": 0.5},
        "naming": {"median_ms": 5200, "accuracy": 0.9, "rounds": 8},
        "switching": {"accuracy": 0.85, "switch_accuracy": 0.82,
                      "stay_accuracy": 0.87, "rounds": 12},
    })
    check("the modality gap is found", scored["settings"]["route"] == "visual")
    check("chunking follows the weaker span",
          scored["settings"]["chunk_at"] == 3, str(scored["settings"]))
    check("slow naming turns on generous matching",
          scored["settings"]["generous_matching"] is True)
    check("low switch cost is recognised as a strength",
          scored["settings"]["interleave"] == "strong")
    check("nothing is timed by default",
          scored["settings"]["timed_by_default"] is False)

    # The disclaimer names IQ and percentiles in order to disclaim them, so
    # check the payload itself rather than the prose around it.
    payload = str({"tasks": scored["tasks"], "contrasts": scored["contrasts"],
                   "settings": scored["settings"]}).lower()
    check("no IQ is reported", "iq" not in payload)
    check("no percentile is reported", "percentile" not in payload)
    check("no norm comparison is reported",
          "average" not in payload and "standard score" not in payload)
    check("the disclaimer travels with the result",
          any("not the WAIS-5" in n for n in scored["notes"]))

    flipped = screener.score({
        "visual_span": {"best_span": 3}, "spoken_span": {"best_span": 6}})
    check("the reverse gap routes verbally",
          flipped["settings"]["route"] == "verbal")
    close = screener.score({
        "visual_span": {"best_span": 5}, "spoken_span": {"best_span": 5}})
    check("a small gap claims no preference",
          close["settings"]["route"] == "balanced")

    # Skipping a task must never make the app harsher. These two are policy.
    bare = screener.score({})
    check("nothing is timed even with no tasks done",
          bare["settings"]["timed_by_default"] is False)
    check("near-misses count even with no tasks done",
          bare["settings"]["generous_matching"] is True)
    fast = screener.score({"naming": {"median_ms": 900, "accuracy": 1.0, "rounds": 8}})
    check("fast retrieval keeps the cue ladder out of the way",
          fast["settings"]["cue_ladder"] == "available")
    slow = screener.score({"naming": {"median_ms": 6000, "accuracy": 0.7, "rounds": 8}})
    check("slow retrieval brings the cue ladder forward",
          slow["settings"]["cue_ladder"] == "prominent")

    partial = screener.score({"visual_span": {"best_span": 5}})
    check("a partial run says it is partial",
          any("partial picture" in n for n in partial["notes"]))

    # --- a screener profile produces a hedged contract -------------------
    su = users.create("Screener User")
    users.update(su["id"], profile_kind="screener", profile=scored)
    sp = learner_profile.for_user(users.get(su["id"]))
    check("the screener contract is hedged as preference",
          "working preference, not a measured fact" in sp)
    check("it still gives concrete instructions",
          "Lead with tables" in sp)

    # =============================== keys ==============================
    print("\n-- api keys --")
    import os
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

    st = keys.status()
    check("no keys means unusable", st["usable"] is False and st["total"] == 0)

    a = keys.add("Main", "sk-ant-aaaaaaaaaaaaaaaaaaaaaaaa")
    b = keys.add("Backup", "sk-ant-bbbbbbbbbbbbbbbbbbbbbbbb")
    check("keys are added in order", a["priority"] < b["priority"])
    check("the secret is never returned", "secret" not in a and "…" in a["hint"])
    check("the hint distinguishes two keys", a["hint"] != b["hint"])
    # Real keys all begin `sk-ant-api03-`, so a hint built from the front is the
    # same string for every key anyone will ever paste in.
    check("two real-shaped keys are still told apart",
          keys.mask("sk-ant-api03-" + "x" * 80 + "AAAA") !=
          keys.mask("sk-ant-api03-" + "x" * 80 + "BBBB"))
    check("the hint never leaks a usable prefix",
          not keys.mask("sk-ant-api03-" + "x" * 84).startswith("sk-ant"))
    check("an empty secret is refused",
          _raises(lambda: keys.add("x", "  "), ValueError))

    order = [k[0] for k in keys.usable()]
    check("priority decides the order", order == [a["id"], b["id"]], str(order))

    keys.reorder([b["id"], a["id"]])
    check("reordering changes which is tried first",
          [k[0] for k in keys.usable()] == [b["id"], a["id"]])
    keys.reorder([a["id"], b["id"]])

    keys.mark_exhausted(a["id"], "rate limit")
    check("an exhausted key steps aside",
          [k[0] for k in keys.usable()] == [b["id"]])
    check("but it is not disabled", keys.get(a["id"])["enabled"] is True)
    check("and it says it is cooling down",
          keys.get(a["id"])["status"] == "cooling down")

    keys.clear_cooldowns()
    check("cooldowns can be cleared",
          [k[0] for k in keys.usable()] == [a["id"], b["id"]])

    keys.mark_invalid(a["id"], "authentication_error")
    check("an invalid key is disabled", keys.get(a["id"])["enabled"] is False)
    check("a disabled key is skipped",
          [k[0] for k in keys.usable()] == [b["id"]])

    keys.update(a["id"], secret="sk-ant-cccccccccccccccccccccccc")
    check("replacing the secret re-enables the key",
          keys.get(a["id"])["enabled"] is True)
    check("and clears its error", keys.get(a["id"])["last_error"] is None)

    keys.mark_ok(b["id"])
    check("a successful call is counted", keys.get(b["id"])["uses"] == 1)

    # Environment fallback, so an existing .env install keeps working.
    keys.remove(a["id"])
    keys.remove(b["id"])
    check("no keys and no env means nothing usable", keys.usable() == [])
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-env"
    # (id, secret, workspace_id) - identity-linked keys need the workspace,
    # and a .env key carries one only if ANTHROPIC_WORKSPACE_ID is set.
    check("the .env key is the fallback",
          keys.usable() == [("env", "sk-ant-env", None)])
    check("env keys are not written to the database",
          keys.status()["total"] == 0 and keys.status()["env_fallback"] is True)
    keys.mark_invalid("env", "x")     # must be a no-op, not a crash
    check("marking the env key is harmless", keys.usable()[0][0] == "env")
    os.environ.pop("ANTHROPIC_API_KEY")

    # --- error classification -------------------------------------------

    class E(Exception):
        def __init__(self, msg, status=None):
            super().__init__(msg)
            self.status_code = status

    check("a 401 is an invalid key",
          claude._classify(E("authentication_error", 401)) == "invalid")
    check("a 429 is exhaustion",
          claude._classify(E("rate limit exceeded", 429)) == "exhausted")
    check("a credit message is exhaustion",
          claude._classify(E("Your credit balance is too low")) == "exhausted")
    check("a 500 is worth trying another key",
          claude._classify(E("internal", 500)) == "exhausted")
    check("a bad request is not the key's fault",
          claude._classify(E("invalid schema", 400)) == "request")

    # An identity-linked key is valid but refused until the request names its
    # workspace. Calling that "invalid" would have the user rotating a key that
    # is fine; calling it "request" sends them to check their connection.
    ws = E("anthropic-workspace-id is required when authenticating with an "
           "identity-linked API key", 400)
    check("a missing workspace id is its own kind",
          claude._classify(ws) == "workspace")
    check("it is not mistaken for an invalid key",
          claude._classify(ws) != "invalid")
    from backend import routes_account as ra
    msg = ra._key_message("workspace", "Main")
    check("the message names the fix, not the connection",
          "Workspace ID" in msg and "connection" not in msg, msg[:70])
    check("and says where to find it", "Console" in msg)

    # usable() returns 3-tuples since workspaces arrived. Anything unpacking
    # two blew up with "too many values to unpack" at runtime.
    import inspect
    for name in ("test_key",):
        src = inspect.getsource(getattr(ra, name))
        check(f"{name} does not unpack usable() as a pair",
              "for key_id, sec in keys.usable()" not in src)

    # ========================== model routing ==========================
    print("\n-- model routing --")
    check("the teaching model is Sonnet", claude.MODEL == "claude-sonnet-5")
    check("an untagged call stays on the teaching model",
          claude.model_for(None) == claude.MODEL)
    check("an unrecognised task stays on the teaching model",
          claude.model_for("some_future_task") == claude.MODEL)
    check("a mechanical task drops to the cheaper model",
          claude.model_for("anki_cards") == claude.MODEL_MECHANICAL)
    check("proving a key works does not need a frontier model",
          claude.model_for("key_test") == claude.MODEL_TRIVIAL)
    # MODEL and MODEL_MECHANICAL both point at Sonnet now that the teaching
    # work is authored offline. What still has to hold is that the trivial
    # tier stays separate - a key test must never cost a frontier call.
    check("the key test is on its own cheaper model",
          claude.MODEL_TRIVIAL not in (claude.MODEL, claude.MODEL_MECHANICAL))
    check("the mechanical tier is never more expensive than teaching",
          claude.MODEL_MECHANICAL == claude.MODEL
          or claude.MODEL_MECHANICAL == "claude-sonnet-5")

    # Which call site runs on which model is a pedagogical decision, not a
    # performance one, so it is pinned. Anything that decides WHAT she learns
    # stays on the teaching model; moving one of these to save tokens should
    # break a test rather than quietly change what she is taught.
    import re
    expected = {
        "generate.analyze": "teaching",       # what the concepts even are
        "generate.questions": "teaching",     # the items themselves
        "generate.study_sheet": "teaching",   # the one-screen accommodation
        "generate.review": "teaching",
        "notes.critique": "teaching",         # judging her own work
        "coach.send": "teaching",             # open-ended reasoning
        "vault.analyse": "teaching",          # reading her handwriting
        "anki.build_cards": "mechanical",
        "book.extract_section": "mechanical",
        "coach.link_note": "mechanical",
        "planner.strategy": "mechanical",
        "resources.find": "mechanical",
        "tactics.explain": "mechanical",
        # A map of a document's structure, not its content - the analytical
        # read is the rest of the app.
        "preread.run": "mechanical",
    }
    tiers = {"teaching": claude.MODEL, "mechanical": claude.MODEL_MECHANICAL}
    found = {}
    for f in sorted((Path(__file__).resolve().parent.parent / "backend").glob("*.py")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "claude.call(" not in line:
                continue
            m = re.search(r'task="([a-z_]+)"', "\n".join(lines[i:i + 10]))
            fn = next((lines[j].split("(")[0].split()[-1]
                       for j in range(i, -1, -1)
                       if lines[j].startswith(("def ", "async def "))), "?")
            found[f"{f.stem}.{fn}"] = claude.model_for(m.group(1) if m else None)

    check("every Claude call site is accounted for",
          set(found) == set(expected),
          f"unlisted: {set(found) - set(expected)}, missing: {set(expected) - set(found)}")
    for site, tier in expected.items():
        if site in found:
            check(f"{site} runs on the {tier} model",
                  found[site] == tiers[tier], f"got {found[site]}")

    # ======================= response handling =========================
    print("\n-- response handling --")

    class _Blk:
        type = "text"

        def __init__(self, text):
            self.text = text

    class _Usage:
        output_tokens = 24000

    class _Msg:
        def __init__(self, text, stop_reason="end_turn"):
            self.content = [_Blk(text)]
            self.stop_reason = stop_reason
            self.usage = _Usage()

    ok = claude.json_of(_Msg('{"concepts": [1, 2]}'))
    check("valid JSON parses", ok == {"concepts": [1, 2]})

    # Truncation is not corruption. Telling her it is sends her retrying a call
    # that will be cut off at exactly the same place every time.
    truncated = _Msg('{"concepts": [{"name": "Chol', stop_reason="max_tokens")
    check("a cut-off reply is reported as truncation, not corruption",
          _raises(lambda: claude.json_of(truncated), claude.Truncated))
    try:
        claude.json_of(truncated)
    except claude.Truncated as exc:
        check("and it says retrying will not help", "not help" in str(exc))
        check("and it names the real fix", "fewer items" in str(exc))

    check("genuinely bad JSON is Malformed",
          _raises(lambda: claude.json_of(_Msg("not json at all")),
                  claude.Malformed))
    check("Malformed is not raised for truncation",
          not _raises(lambda: claude.json_of(truncated), claude.Malformed))

    # The route layer used to catch bare JSONDecodeError, so a corrupt database
    # column blamed Claude for a bug Claude had no part in.
    import json as _json
    from backend import app as app_mod

    def _unrelated():
        return _json.loads("{oops")

    check("an unrelated JSON error is no longer blamed on Claude",
          _raises(lambda: app_mod._guard(_unrelated), _json.JSONDecodeError))

    check("Malformed and Truncated are distinct types",
          not issubclass(claude.Truncated, claude.Malformed)
          and not issubclass(claude.Malformed, claude.Truncated))

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


# A synthetic report, not a real one. Shape rather than person: visual working
# memory at the population mean, auditory working memory roughly 1.5 SD below
# it, reasoning intact. Every assertion above is about that shape.
SYNTHETIC_REPORT = {
    "indexes": {"NMI": 97, "VCI": 106, "FRI": 101, "WMI": 80, "AWMI-R": 78},
    "subtests": {
        "Similarities": 12, "Vocabulary": 11, "Matrix Reasoning": 10,
        "Figure Weights": 11, "Visual Puzzles": 8,
        "Digits Forward": 6, "Digit Sequencing": 7, "Running Digits": 7,
        "Symbol Span": 11,
        "Word Reading": 10, "Color Naming": 6,
        "Inhibition": 9, "Inhibition/Switching": 12,
    },
    "accommodations": ["Extended time", "Reduced-distraction testing"],
    "source": "Synthetic fixture, not a real evaluation. Block Design, "
              "Coding and Symbol Search were not administered, so VSI, "
              "PSI and FSIQ are not derived.",
    "notes": "",
}


def _raises(fn, exc_type):
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
