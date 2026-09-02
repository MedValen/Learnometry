"""
Thin wrapper over the Anthropic SDK.

Everything in this app goes through `call()`, which handles the two things the
rest of the code shouldn't have to think about:

  * streaming (quiz batches run long and would otherwise hit HTTP timeouts)
  * graceful degradation when an optional beta isn't enabled on the account
"""

from __future__ import annotations

import json
import os

import anthropic

# The model that teaches. Everything that decides WHAT she learns - what the
# concepts are, what the questions ask, whether her notes are any good.
#
# This was Opus. It is Sonnet now because the teaching work moved OUT of the
# app: the concepts and questions are authored in a Claude Code session and
# imported with `tools/import_lecture.py`, which spends nothing here. What is
# left for the API is the incidental work - a note critique, an exam chat - and
# paying Opus rates for that was the expensive half of the bill for the half
# that mattered least. Set LEARNOMETRY_MODEL to put a call site back on Opus.
MODEL = os.getenv("LEARNOMETRY_MODEL") or "claude-sonnet-5"

# The model that reformats. These tasks take material that has already been
# reasoned about and move it into a different shape against a fixed schema.
# With MODEL on Sonnet this is the same model - the split is kept because the
# tiers are a statement about which calls MAY be cheapened, and that judgement
# survives the two happening to point at one model today.
MODEL_MECHANICAL = os.getenv("LEARNOMETRY_MODEL_MECHANICAL") or "claude-sonnet-5"

# Proving a key authenticates does not need a frontier model to say "hi".
MODEL_TRIVIAL = os.getenv("LEARNOMETRY_MODEL_TRIVIAL") or "claude-haiku-4-5-20251001"

# Which tasks are allowed off the teaching model. Anything not named here stays
# on MODEL, so a new call site has to opt IN to the cheaper path rather than
# being quietly demoted by a default.
MECHANICAL_TASKS = {
    "anki_cards",      # concepts are already analysed; this reshapes them
    "book_section",    # pulling a named section out of a PDF
    "note_link",       # matching one note to one concept
    "plan_strategy",   # dates, ordering, and phrasing around them
    "question_tactics",  # marking up a question that already exists
    "resource_search",   # mostly orchestrating web-search results
    "preread",           # a map of a document's structure, not its content
}


def model_for(task: str | None) -> str:
    """Which model runs this call.

    One table, so the cost/quality split is a thing you can read rather than
    something spread across thirteen call sites.
    """
    if task == "key_test":
        return MODEL_TRIVIAL
    return MODEL_MECHANICAL if task in MECHANICAL_TASKS else MODEL

FILES_BETA = "files-api-2025-04-14"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# One client per key, so switching keys does not rebuild an HTTP pool.
_clients: dict[tuple[str, str | None], anthropic.Anthropic] = {}

# Set to False permanently the first time the account rejects the beta, so we
# stop paying a failed round-trip on every request.
_fallbacks_available = True


class NotConfigured(Exception):
    pass


class Malformed(Exception):
    """Claude's reply really was unparseable.

    A distinct type because the route layer used to catch bare JSONDecodeError
    and blame Claude for it. Any JSON parsed anywhere inside a request - a
    column read back from the database, a request body - could raise that, and
    the user was told "Claude returned malformed JSON" about a bug that had
    nothing to do with Claude, which sends them retrying instead of reporting.
    """


class Truncated(Exception):
    """The reply hit max_tokens. Incomplete, not corrupt - retrying won't fix it."""


class NeedsWorkspace(Exception):
    """An identity-linked key that did not say which workspace it acts in."""


def client(secret: str | None = None,
           workspace_id: str | None = None) -> anthropic.Anthropic:
    """Client for a specific key, or for whichever key is next in line."""
    from . import keys

    if secret is None:
        available = keys.usable()
        if not available:
            raise NotConfigured(
                "No API key configured. Add one under Profile → API keys, or "
                "put ANTHROPIC_API_KEY in a .env file. "
                "Keys: https://console.anthropic.com/settings/keys")
        secret = available[0][1]
        workspace_id = workspace_id or available[0][2]

    # Keyed on the workspace too. The headers differ per workspace, so a cache
    # keyed on the secret alone would keep serving the old client after someone
    # corrects the workspace id, and the correction would look like it failed.
    ck = (secret, workspace_id)
    if ck not in _clients:
        headers = {}
        if workspace_id:
            # Required for identity-linked keys; harmless on organisation keys.
            headers["anthropic-workspace-id"] = workspace_id
        # 15 minutes: a 40-question generation at high effort is a long turn.
        _clients[ck] = anthropic.Anthropic(
            api_key=secret, timeout=900.0, max_retries=2,
            default_headers=headers or None)
    return _clients[ck]


def _classify(exc: Exception) -> str:
    """Is this key out of credit, invalid, or is the request itself bad?"""
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)

    # An identity-linked key is refused until the request names the workspace
    # it acts in. It is not a bad key and not a bad request in any way the user
    # can fix by retrying - it needs one more field, so it gets its own kind.
    if "anthropic-workspace-id" in text or "identity-linked" in text:
        return "workspace"
    if status == 401 or "authentication" in text or "invalid x-api-key" in text:
        return "invalid"
    if status == 429 or "rate limit" in text or "rate_limit" in text:
        return "exhausted"
    if status == 402 or "credit balance" in text or "insufficient" in text \
            or "quota" in text or "billing" in text:
        return "exhausted"
    if status is not None and status >= 500:
        return "exhausted"        # server-side; another key may be on another shard
    return "request"              # our problem, not the key's


def call(
    *,
    system: str,
    messages: list[dict],
    max_tokens: int = 32000,
    effort: str = "high",
    schema: dict | None = None,
    tools: list[dict] | None = None,
    task: str | None = None,
):
    """One streamed request. Returns the final Message object.

    `schema` turns on structured output (JSON matching that schema).
    `tools` is for server-side tools such as web search.
    `task` names the job so `model_for` can route it; omitting it keeps the
    call on the teaching model, which is the safe direction to be wrong in.
    """
    global _fallbacks_available

    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    kwargs: dict = {
        "model": model_for(task),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": output_config,
        # The course material and the profile prompt are identical across every
        # request in a session, so cache the prefix.
        "cache_control": {"type": "ephemeral"},
    }
    if tools:
        kwargs["tools"] = tools

    betas = [FILES_BETA]
    if _fallbacks_available:
        betas.append(FALLBACK_BETA)
        kwargs["fallbacks"] = "default"

    from . import keys as key_store

    available = key_store.usable()
    if not available:
        raise NotConfigured(
            "No API key configured. Add one under Profile → API keys, or put "
            "ANTHROPIC_API_KEY in a .env file. "
            "Keys: https://console.anthropic.com/settings/keys")

    last: Exception | None = None
    for key_id, secret, workspace_id in available:
        try:
            with client(secret, workspace_id).beta.messages.stream(
                    betas=betas, **kwargs) as stream:
                message = stream.get_final_message()
            key_store.mark_ok(key_id)
            return message

        except anthropic.BadRequestError as exc:
            if _classify(exc) == "workspace":
                raise NeedsWorkspace(
                    "This API key is identity-linked, so every request must say "
                    "which workspace it acts in. Open Profile → API keys, edit "
                    "this key, and paste its Workspace ID. You can find it in the "
                    "Anthropic Console: Settings → Workspaces, or in the URL "
                    "when that workspace is open - it looks like wrkspc_…") from exc
            # Refusal fallbacks are opt-in per account. If this org lacks the
            # beta, drop it once and retry on the same key rather than
            # burning through the whole list for a request-shape problem.
            if _fallbacks_available and "fallback" in str(exc).lower():
                _fallbacks_available = False
                kwargs.pop("fallbacks", None)
                with client(secret, workspace_id).beta.messages.stream(
                        betas=[FILES_BETA], **kwargs) as stream:
                    message = stream.get_final_message()
                key_store.mark_ok(key_id)
                return message
            raise

        except Exception as exc:                       # noqa: BLE001
            kind = _classify(exc)
            if kind == "request":
                raise            # a bad request fails on every key; don't retry
            if kind == "invalid":
                key_store.mark_invalid(key_id, str(exc))
            else:
                key_store.mark_exhausted(key_id, str(exc))
            last = exc
            continue             # next key, same request

    raise NotConfigured(
        "Every API key failed. Last error: "
        f"{type(last).__name__}: {last}. "
        "Check them under Profile → API keys.") from last


def text_of(message) -> str:
    """Concatenate the text blocks of a response."""
    return "".join(b.text for b in message.content if b.type == "text")


def json_of(message) -> dict:
    """Parse a structured-output response.

    `output_config.format` guarantees valid JSON in the text blocks, but a
    refusal can still end the turn with no text at all.
    """
    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        category = getattr(detail, "category", None) or "unspecified"
        raise RuntimeError(
            f"The request was declined (category: {category}). "
            "Try rephrasing the topic or removing patient identifiers from the file."
        )
    raw = text_of(message).strip()
    if not raw:
        raise RuntimeError(f"Empty response (stop_reason={message.stop_reason}).")

    # Truncation produces JSON that is malformed only because it stops early.
    # Reported as "malformed, usually transient" it invites a retry that will
    # fail identically every time; the fix is a smaller batch, not patience.
    if message.stop_reason == "max_tokens":
        raise Truncated(
            f"The answer was cut off at the {message.usage.output_tokens}-token "
            "limit, so it is incomplete rather than corrupt. Retrying will not "
            "help - generate fewer items per batch, or split the material.")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Malformed(
            f"Claude's reply was not valid JSON ({exc}). This is usually "
            "transient - try again.") from exc


def usage_of(message) -> dict:
    u = message.usage
    return {
        "input": u.input_tokens,
        "output": u.output_tokens,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }
