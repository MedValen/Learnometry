"""
The cognitive profile that every prompt in this app is built around.

The point of this module is that the *pedagogy* is derived from the scores, not
bolted on afterward: a profile is a set of channels, some wide and some narrow,
and the job is to route through the wide ones. Nothing here is a template - a
lever only appears when a score that implies it is actually present.

A fresh install ships with NO profile. There are three ways one gets built:

  * `build_from_report()`  - scores typed in from a formal evaluation
  * `build_from_screener()`- the in-app tasks, which produce settings, never
                             index scores or percentiles
  * `build_generic()`      - the honest fallback: write for a capable student
                             and invent nothing about them

Test scores are somebody's clinical record, so they live in that person's own
database and never in this file.
"""

# ---------------------------------------------------------------------------
# A fresh install has no scores. These stay empty on purpose: a shipped default
# would be either a made-up person, or a real one - and the second is a clinical
# record in a source file. Scores are entered on the Profile screen and stored
# in that user's own row.
#
# The names below are what the app understands when a report is typed in; see
# `levers_from()` for what each one is allowed to change.
# ---------------------------------------------------------------------------

KNOWN_INDEXES = ("FSIQ", "GAI", "NMI", "VCI", "FRI", "VSI", "WMI", "AWMI-R", "PSI")
KNOWN_SUBTESTS = (
    "Similarities", "Vocabulary", "Information", "Comprehension",
    "Matrix Reasoning", "Figure Weights", "Visual Puzzles", "Block Design",
    "Digits Forward", "Digit Sequencing", "Running Digits", "Symbol Span",
    "Letter-Number Sequencing", "Coding", "Symbol Search",
    "Word Reading", "Color Naming", "Inhibition", "Inhibition/Switching",
)

INDEXES: dict[str, float] = {}
SUBTESTS: dict[str, float] = {}
ACCOMMODATIONS: list[str] = []


# ---------------------------------------------------------------------------
# The design contract handed to Claude on every single request.
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """\
You are the tutor engine inside "Learnometry", a medical-school study tool built
around the cognitive profile of the student using it. You write board-level
(USMLE Step 1 / Step 2 CK) material that is accurate, current, and uncompromising
on content difficulty - and that is routed entirely through this student's strong
channels.

{profile}

# ACCURACY RULES

- This is medical education material. Accuracy is non-negotiable.
- Ground everything in the uploaded course material when it is provided. The
  course material is the syllabus; your outside knowledge is supporting context.
- If the source material conflicts with standard teaching, say so explicitly and
  flag it rather than silently picking one.
- If you are not confident in a fact, mark it and say what would settle it. Do
  not invent a citation, a study, a guideline number, or a URL.
- Never present a fact stated only in the uploaded slides as though it were an
  established guideline, and never the reverse.

# WHAT THIS TOOL IS NOT

This produces study material about medicine. It never gives medical advice about
a real person and never diagnoses anyone. If uploaded material contains real
patient identifiers, do not reproduce them in the output.
"""

def profile_digest(user: dict | None = None) -> dict:
    """Compact machine-readable version, rendered on the Profile screen.

    Defaults to the active user. The constants above are this module's worked
    example, not a global truth, so they are only the fallback for a database
    that has no users in it at all.
    """
    if user is None:
        try:
            from . import users
            user = users.active()
        except Exception:                              # noqa: BLE001
            user = None

    if not user or not user.get("profile"):
        return {
            "name": user["name"] if user else None,
            "kind": user["profile_kind"] if user else "none",
            "indexes": {}, "subtests": {}, "accommodations": [], "levers": [],
            "caveat": ("No scores on file. The app is running on its general "
                       "principles until a report or a screener run gives it "
                       "something about you."),
        }

    prof = user["profile"]
    return {
        "name": user["name"],
        "kind": user["profile_kind"],
        "indexes": prof.get("indexes", {}),
        "subtests": prof.get("subtests", {}),
        "accommodations": prof.get("accommodations", []),
        "levers": levers_from(prof),
        "caveat": prof.get("source") or prof.get("notes") or "",
    }


# ===========================================================================
# Per-user profiles
# ===========================================================================
#
# Everything above is one real person's report, kept as the canonical example
# because it is the case this app was designed around and the one place the
# reasoning is fully worked through.
#
# What follows builds the same shape of contract for anyone else - from their
# own report, from the in-app screener, or from nothing at all. The universal
# half (write visually, chunk, one idea per line, reason rather than memorise)
# is good practice for every learner; what changes per person is which channel
# gets emphasised and how hard.

UNIVERSAL = """\
## HOW TO WRITE, MECHANICALLY

1. VISUAL FIRST where you can. A markdown table, a compare/contrast pair, a
   short arrow chain. If you cannot make a visual for it, you have not yet
   understood it well enough to teach it.
2. ONE IDEA PER LINE. Short declarative sentences. No sentence should require
   holding one clause open while another resolves.
3. NO NAKED LISTS OF FIVE. Group into 2-3 named buckets. Chunking is the whole
   game.
4. REASON, DON'T MEMORISE. Give the *why* that lets the fact be rebuilt rather
   than stored.
5. CONTRAST PAIRS. Teach confusable things side by side in one table.
6. PLAIN ENGLISH AROUND THE JARGON. Keep the medical term; drop the fancy
   non-medical vocabulary around it.
"""

_ACTIVE_CACHE: str | None = None


def invalidate() -> None:
    """Drop the cached prompt. Called when the user or their profile changes."""
    global _ACTIVE_CACHE
    _ACTIVE_CACHE = None


def _band(value, low, high):
    """Where a score sits, without inventing precision about it."""
    if value is None:
        return None
    return "low" if value < low else "high" if value > high else "mid"


def build_from_report(profile: dict, name: str = "") -> str:
    """Contract from formally administered scores."""
    idx = {k: v for k, v in (profile.get("indexes") or {}).items() if v not in (None, "")}
    sub = {k: v for k, v in (profile.get("subtests") or {}).items() if v not in (None, "")}

    lines = ["# WHO YOU ARE WRITING FOR", ""]
    lines.append(
        f"{name or 'This student'} has a formal neuropsychological evaluation. "
        "The scores below are measured, not inferred, and every one of them is "
        "a constraint on how you write.")
    lines.append("")

    if idx:
        lines.append("## Index scores (mean 100, SD 15)")
        for k, v in idx.items():
            lines.append(f"  {k} = {v}")
        lines.append("")
    if sub:
        lines.append("## Subtest scaled scores (mean 10, SD 3)")
        for k, v in sub.items():
            lines.append(f"  {k} = {v}")
        lines.append("")

    # The contrasts that actually change how material should be written.
    findings = []
    vis = _num(sub.get("Symbol Span")) or _num(sub.get("Block Design"))
    verb = _num(sub.get("Digit Span")) or _num(sub.get("Digits Forward"))
    if vis is not None and verb is not None and vis - verb >= 2:
        findings.append(
            f"Visual working memory ({vis}) is well above auditory ({verb}). "
            "Route everything through what can be seen: tables, diagrams, "
            "spatial layouts. Never rely on a spoken or serially-listed chain.")
    elif vis is not None and verb is not None and verb - vis >= 2:
        findings.append(
            f"Auditory working memory ({verb}) is above visual ({vis}). "
            "Written and verbal explanation carries well; still use tables, but "
            "they are support rather than the main route.")

    wmi = _num(idx.get("WMI")) or _num(idx.get("AWMI-R"))
    if wmi is not None and wmi < 85:
        findings.append(
            f"Working memory is low (WMI {wmi}). Never require more than 3-4 new "
            "elements at once. Restate every premise inside the item. Assume "
            "nothing said aloud survives.")

    for key, label in (("Color Naming", "rapid naming"),):
        v = _num(sub.get(key))
        if v is not None and v <= 6:
            findings.append(
                f"Rapid lexical retrieval is slow ({label} = {v}). Use a "
                "retrieval ladder - recognition, then cued recall, then free "
                "recall. Never make speed of naming the skill being tested.")

    switch = _num(sub.get("Inhibition/Switching"))
    if switch is not None and switch >= 9:
        findings.append(
            f"Set-shifting is a strength (Inhibition/Switching = {switch}). "
            "Interleaved practice and look-alike discrimination play to it.")

    reasoning = _num(idx.get("VCI")) or _num(idx.get("FRI")) or _num(idx.get("GAI"))
    if reasoning is not None and reasoning >= 90:
        findings.append(
            f"Reasoning is intact ({reasoning}). Do NOT simplify the content. "
            "Simplify the load, never the level.")

    if findings:
        lines.append("## What these scores require of you")
        lines += [f"- {f}" for f in findings]
        lines.append("")

    accom = profile.get("accommodations") or []
    if accom:
        lines.append("## Formal accommodations")
        lines += [f"- {a}" for a in accom]
        lines.append("")
        lines.append(
            "Never add urgency language, countdowns, or speed pressure. An "
            "accommodation that the material fights is not an accommodation.")
        lines.append("")

    notes = (profile.get("notes") or "").strip()
    if notes:
        lines += ["## From the report", notes, ""]

    lines.append(UNIVERSAL)
    return "\n".join(lines)


def build_from_screener(profile: dict, name: str = "") -> str:
    """Contract from the in-app screener.

    Stated as preference rather than fact throughout, because that is what a
    fifteen-minute browser task supports.
    """
    settings = profile.get("settings", {})
    contrasts = profile.get("contrasts", [])

    lines = ["# WHO YOU ARE WRITING FOR", ""]
    lines.append(
        f"{name or 'This student'} completed the app's own screener - four short "
        "tasks compared against each other, not against any norm. Treat what "
        "follows as a working preference, not a measured fact about them: it is "
        "good enough to decide how to lay material out, and not good enough to "
        "conclude anything else.")
    lines.append("")

    if contrasts:
        lines.append("## What the screener found")
        for c in contrasts:
            lines.append(f"- {c.get('finding', '')} {c.get('means', '')}".strip())
        lines.append("")

    route = settings.get("route", "balanced")
    chunk = settings.get("chunk_at", 4)
    lines.append("## What that means for how you write")
    if route == "visual":
        lines.append(
            "- Lead with tables, diagrams and spatial layouts. A paragraph is "
            "the fallback, not the default.")
    elif route == "verbal":
        lines.append(
            "- Clear written explanation carries well here. Use tables for "
            "contrasts rather than for everything.")
    else:
        lines.append("- Mix formats. Neither channel is clearly stronger.")
    lines.append(f"- Never put more than {chunk} new elements on screen at once.")
    if settings.get("cue_ladder") == "prominent":
        lines.append(
            "- Word-finding is slow. Offer recognition before recall, accept "
            "near-misses, and never test speed of naming.")
    if settings.get("interleave") == "strong":
        lines.append(
            "- Rule-switching is comfortable. Interleave topics and use "
            "look-alike comparisons.")
    else:
        lines.append("- Signpost changes of topic rather than switching constantly.")
    lines.append("")
    lines.append(UNIVERSAL)
    return "\n".join(lines)


def build_generic() -> str:
    lines = ["# WHO YOU ARE WRITING FOR", ""]
    lines.append(
        "No cognitive profile has been set for this user, so write for a capable "
        "medical student and apply the general principles below. Do not invent "
        "characteristics they have not told you about.")
    lines.append("")
    lines.append(UNIVERSAL)
    return "\n".join(lines)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def levers_from(profile: dict) -> list[dict]:
    """The "why the app looks like this" table, for the Profile screen.

    Every row is derived from a score that is actually present. A report with
    three numbers in it produces three rows; nothing is filled in by assumption,
    because a row here is a claim about a real person's cognition and an invented
    one would be worse than a blank.

    The findings are written as directions rather than labels - "Max 3 elements
    on screen" is checkable against what the app does, where "low working
    memory" is not.
    """
    out = []
    sub = profile.get("subtests") or {}
    idx = profile.get("indexes") or {}
    settings = profile.get("settings") or {}
    accom = profile.get("accommodations") or []

    def s_of(*names):
        for n in names:
            v = _num(sub.get(n))
            if v is not None:
                return n, v
        return None, None

    def i_of(*names):
        for n in names:
            v = _num(idx.get(n))
            if v is not None:
                return n, v
        return None, None

    # --- the visual channel ---------------------------------------------
    vname, vis = s_of("Symbol Span")
    if vis is not None:
        band = _band(vis, 8, 12)
        out.append({
            "finding": ("Visual working memory intact" if band != "low"
                        else "Visual working memory reduced"),
            "score": f"{vname} = {vis:g}",
            "rule": ("Every concept ships with a table or diagram."
                     if band != "low"
                     else "Diagrams stay small — three or four parts, labelled."),
        })

    # --- the auditory channel -------------------------------------------
    aname, aud = i_of("AWMI-R", "WMI")
    if aud is not None:
        low = aud < 85
        pct = f" ({_percentile_word(aud)})" if low else ""
        out.append({
            "finding": ("Auditory working memory very low" if aud < 80
                        else "Auditory working memory low" if low
                        else "Auditory working memory workable"),
            "score": f"{aname} = {aud:g}{pct}",
            "rule": (f"Max {3 if aud < 80 else 4 if low else 5}-"
                     f"{4 if aud < 80 else 5 if low else 6} elements on screen. "
                     "Nothing held in the head."),
        })

    # --- registration, which is upstream of everything ------------------
    dname, dig = s_of("Digits Forward", "Digit Span")
    if dig is not None and dig <= 7:
        out.append({
            "finding": ("Registration itself reduced" if dig <= 6
                        else "Registration on the low side"),
            "score": f"{dname} = {dig:g}",
            "rule": "Premises are always restated inside the question.",
        })

    # --- reasoning, which decides the DIFFICULTY, not the presentation ---
    vci, fri = _num(idx.get("VCI")), _num(idx.get("FRI"))
    pair = [f"VCI {vci:g}" if vci is not None else None,
            f"FRI {fri:g}" if fri is not None else None]
    pair = [x for x in pair if x]
    if pair:
        best = max(x for x in (vci, fri) if x is not None)
        out.append({
            "finding": "Reasoning intact" if best >= 90 else "Reasoning is a target too",
            "score": " / ".join(pair),
            "rule": ("Full Step-1 difficulty. Mechanism over memorization."
                     if best >= 90
                     else "Build the mechanism explicitly before testing on it."),
        })

    # --- switching ------------------------------------------------------
    swname, sw = s_of("Inhibition/Switching", "Inhibition")
    if sw is not None:
        strong = sw >= 9
        out.append({
            "finding": "Switching is a strength" if strong else "Switching costs her",
            "score": f"{swname} = {sw:g}",
            "rule": ("Interleaving and look-alike discrimination drills."
                     if strong
                     else "One topic at a time. Blocks, not shuffles."),
        })

    # --- retrieval speed: recorded, never scored ------------------------
    cname, col = s_of("Color Naming", "Word Reading")
    if col is not None and col <= 7:
        out.append({
            "finding": "Naming is slow",
            "score": f"{cname} = {col:g}",
            "rule": "Recognition -> cued recall -> free recall. Never timed.",
        })

    if accom:
        out.append({
            "finding": "Formal accommodations",
            "score": ", ".join(str(a) for a in accom),
            "rule": "Untimed by default. One question per screen.",
        })

    # --- the screener says less, and says so -----------------------------
    if settings.get("route"):
        out.append({
            "finding": "Screener routing",
            "score": f"{settings['route']} (screener, not a report)",
            "rule": f"Group anything over {settings.get('chunk_at', 4)} items.",
        })
    if settings.get("generous_matching"):
        out.append({
            "finding": "Word-finding was slow on the screener",
            "score": "naming task",
            "rule": "Near-miss answers are accepted. Never timed.",
        })
    return out


def _percentile_word(standard_score: float) -> str:
    """Percentile for a standard score, rounded honestly.

    Standard scores are normed to mean 100, SD 15, so the percentile is a
    property of the number itself, not an extra claim about the person.
    """
    import math

    z = (standard_score - 100.0) / 15.0
    pct = 100.0 * 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    if pct < 1:
        return "below the 1st %ile"
    return f"{round(pct)}th %ile"


def for_user(user: dict | None) -> str:
    """The full system prompt for whoever is using the app."""
    if not user:
        # No account yet. Write for a capable student and claim nothing about
        # them - the app must not describe a person it has never measured.
        body = build_generic()
    elif user.get("profile_kind") == "report" and user.get("profile"):
        body = build_from_report(user["profile"], user.get("name", ""))
    elif user.get("profile_kind") == "screener" and user.get("profile"):
        body = build_from_screener(user["profile"], user.get("name", ""))
    else:
        body = build_generic()

    # Standing notes go inside the profile block, not after the template's
    # closing rules, so they are read as facts about her rather than as a
    # late instruction that could be taken to override the contract.
    if user and user.get("id"):
        try:
            from . import notes_memory
            body += notes_memory.for_prompt(user["id"])
        except Exception:               # noqa: BLE001 - notes are additive
            pass

    return SYSTEM_TEMPLATE.format(profile=body)


def active() -> str:
    """Cached system prompt for the active user."""
    global _ACTIVE_CACHE
    if _ACTIVE_CACHE is None:
        try:
            from . import users
            _ACTIVE_CACHE = for_user(users.active())
        except Exception:                              # noqa: BLE001
            # No database yet, or no users - fall back to the canonical profile
            # rather than failing a generation request.
            _ACTIVE_CACHE = SYSTEM_PROMPT
    return _ACTIVE_CACHE



# Built here rather than at the top of the module because it depends on
# build_generic(), and because there is no longer a canonical profile to
# format in.
SYSTEM_PROMPT = SYSTEM_TEMPLATE.format(profile=build_generic())
