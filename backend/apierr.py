"""
One translation from exception to HTTP response.

There were three `_guard` implementations. `routes_org` and `routes_account`
turned KeyError and ValueError into clean 4xx messages; `app.py` did not - so
every route added there later (the file library, the importer, the support
page) answered a missing id with a 500 and a raw traceback. Asking for a file
that had been deleted produced a stack trace instead of "no such upload".

They also disagreed about the message. `str(KeyError("no such upload: x"))`
renders as `"'no such upload: x'"` - Python quotes the argument - and that
quoted form leaked to the UI once already in this project. `detail()` is the
single place that unwraps it.

So: one guard, imported everywhere, and a test that asserts no route module
defines its own.
"""

from __future__ import annotations

import json

from fastapi import HTTPException


def detail(exc: Exception) -> str:
    """The message a user should see.

    KeyError stringifies with quotes around its argument, which is right for a
    dict lookup and wrong for a sentence. Unwrap it.
    """
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def guard(fn, *args, **kwargs):
    """Call `fn`, translating the exceptions routes are allowed to raise.

    Anything not listed here is a genuine bug and must keep reaching the
    500 handler with its traceback intact - swallowing unknown exceptions into
    a tidy 400 is how a real fault gets mistaken for bad input.
    """
    from . import claude

    try:
        return fn(*args, **kwargs)
    except claude.NotConfigured as exc:
        raise HTTPException(status_code=503, detail=detail(exc)) from exc
    except claude.Truncated as exc:
        # 502 would invite a retry, and a retry truncates identically.
        raise HTTPException(status_code=413, detail=detail(exc)) from exc
    except claude.NeedsWorkspace as exc:
        # 400: the request really is missing something, and the message says
        # exactly what and where to put it.
        raise HTTPException(status_code=400, detail=detail(exc)) from exc
    except claude.Malformed as exc:
        raise HTTPException(status_code=502, detail=detail(exc)) from exc
    except KeyError as exc:
        # "No such thing" is a 404, not a malformed request.
        raise HTTPException(status_code=404, detail=detail(exc)) from exc
    except json.JSONDecodeError:
        # A subclass of ValueError, and it must NOT be caught as one. Reaching
        # here means something we parsed was corrupt - a database column, a
        # config file - which is a server fault, not bad input from the caller.
        # Dressing it as a 400 would hide real data corruption behind a message
        # blaming the user. It goes to the 500 handler with its traceback.
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=detail(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=detail(exc)) from exc
