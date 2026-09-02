"""
Find outside material for a topic - and rank it by whether it fits *this*
profile, not just by whether it's popular.

The profile-aware part matters. The most-recommended Step 1 resource in some
years has been an audio-only podcast. For a student low on
auditory working memory with intact visual working memory, that is close to the
worst possible delivery format, however good the content is. So the ranking here
is explicitly two-axis: reputation AND channel fit.

Reputation claims come from live web search with citations. Nothing about
ratings, review counts, or popularity is asserted from the model's own memory.
"""

from __future__ import annotations

from . import claude
from . import learner_profile

WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 8,
}

# Widely used in US-style basic sciences. Not a ranking - a starting point for
# the search, so the model checks current standing rather than assuming it.
SEED_RESOURCES = [
    "Boards and Beyond", "Sketchy Medical", "Pathoma", "Ninja Nerd",
    "Dirty Medicine", "Osmosis", "AMBOSS", "UWorld", "AnKing Anki deck",
    "Physeo", "Armando Hasudungan", "Randy Neil biostatistics",
    "Divine Intervention podcast", "Mehlman Medical", "First Aid for the USMLE",
]

PROMPT = """\
Find the best outside study resources for this topic, for a St. George's
University medical student:

TOPIC: {topic}
{context}

## Step 1 - search

Use web search to find what is actually being recommended right now. Check both
general Step 1 / Step 2 CK communities and anything SGU-specific you can find
(SGU subreddits, SGU student forums, SGU study guides). These are the resources
most commonly named in that space, so use them as a starting point and verify
rather than assume: {seeds}.

Gather real signals - ratings, review counts, subscriber counts, upvotes, "most
recommended" threads. Cite where each signal came from.

## Step 2 - rank on TWO axes, and show both

**Axis A - reputation.** What the search actually found. Report only signals you
found. If you could not find review or rating data for something, say "no review
data found" - never estimate a number.

**Axis B - channel fit for this student.** This is the axis a generic
recommendation list gets wrong, so weight it heavily:

  STRONG FIT - visually dense. Diagram-driven whiteboard teaching, image
    mnemonics, annotated tables, anything where the screen carries the content
    and the narration is secondary. Visual working memory here is average
    and, for many profiles, this is the channel that works.

  WEAK FIT - audio-carried. Podcasts, talking-head lectures, anything where the
    information exists only in the spoken track. Auditory working memory is at
    the narrower channel. A well-loved audio resource is still a bad
    resource *for her*, and you should say so directly and without hedging - and
    then say what to pair it with (transcript, printed outline, her own table)
    if she wants to use it anyway.

Also note, per resource: whether captions/transcripts exist, whether video
lengths are short enough to sit inside one 3-4 element chunk (roughly: under
15 minutes is good, over 40 is a problem), and whether playback speed is
adjustable - extended time is a formal accommodation here, so being able to
slow a video down matters.

## Step 3 - write it up

Output GitHub-flavored markdown, in this order:

1. A ranked table. Columns: Resource | What it is | Reputation signal (with
   source) | Channel fit | Why for her.
2. "Start here" - the single best pick, and 2-3 sentences on exactly how to use
   it for this topic.
3. "Specific videos" - direct links to individual videos or chapters covering
   THIS topic, not just the channel homepage. Only real URLs you actually found
   in search results. If you could not find a specific video, say so rather than
   guessing at a URL.
4. "Skip or adapt" - what's popular but a poor channel fit for her, and how to
   adapt it if she wants it anyway.

Keep every table cell to one line. No paragraphs longer than three lines.
"""


def find(topic: str, context: str = "") -> dict:
    prompt = PROMPT.format(
        topic=topic,
        context=f"COURSE CONTEXT: {context}" if context else "",
        seeds=", ".join(SEED_RESOURCES),
    )

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": prompt}],
        tools=[WEB_SEARCH_TOOL],
        max_tokens=24000,
        effort="high",
        task="resource_search",
    )

    if msg.stop_reason == "refusal":
        raise RuntimeError("The search request was declined. Try a narrower topic.")

    markdown = claude.text_of(msg)
    return {
        "markdown": markdown,
        "sources": _collect_sources(msg),
        "usage": claude.usage_of(msg),
    }


def _collect_sources(msg) -> list[dict]:
    """Pull the pages web search actually returned, de-duplicated by URL."""
    seen: dict[str, dict] = {}
    for block in msg.content:
        if block.type != "web_search_tool_result":
            continue
        content = block.content
        # A successful result is a LIST of results; an error is a single object.
        if not isinstance(content, list):
            code = getattr(content, "error_code", "unknown")
            seen.setdefault(f"error:{code}", {"title": f"search error: {code}", "url": ""})
            continue
        for r in content:
            url = getattr(r, "url", "")
            if url and url not in seen:
                seen[url] = {"title": getattr(r, "title", url), "url": url}
    return list(seen.values())
