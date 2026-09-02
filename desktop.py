"""
Learnometry as a desktop application.

Starts the server on a free local port in a background thread and opens it in a
native window. No terminal, no browser tabs, no localhost URL to remember.

Three things this has to get right, because they are what make a local web app
feel like a real application rather than a dev server in a costume:

  * It must not fight over a port. It asks the OS for a free one.
  * It must not lose her data when packaged. A frozen executable lives in a
    read-only folder, so the database moves to %LOCALAPPDATA%.
  * It must degrade rather than fail. If no native webview is available it
    opens the default browser and says so, instead of showing a blank window.

Run directly:      python desktop.py
Build an .exe:     python build_desktop.py
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Learnometry"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def data_dir() -> Path:
    """Where the database and vault live.

    A packaged app sits in Program Files or a temp extraction directory, both of
    which are the wrong place for the only copy of her study history - so when
    frozen, everything goes to LOCALAPPDATA and stays there across reinstalls.
    """
    override = os.environ.get("LEARNOMETRY_DATA") or os.environ.get("SYMBOLSPAN_DATA")
    if override:
        return Path(override)
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        return Path(base) / "Learnometry"
    return Path(__file__).resolve().parent / "data"


def ensure_streams() -> None:
    """Give the process a stdout and stderr, because pythonw.exe does not.

    A GUI launcher runs pythonw.exe so no console window flashes up. That
    leaves sys.stdout and sys.stderr set to None, and anything that touches
    them raises. uvicorn's log formatter calls sys.stdout.isatty() while it is
    building its config, so the SERVER never starts, main() exits before the
    window is created, and clicking the desktop icon does nothing whatsoever -
    no window, no error, nothing to act on.

    Pointing them at a log file rather than os.devnull costs nothing and means
    the next failure leaves evidence instead of silence.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    sink = None
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        sink = open(d / "desktop.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        try:
            sink = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return
    for name in ("stdout", "stderr", "__stdout__", "__stderr__"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, sink)


# Magic bytes, so a file that is merely NAMED .ico is still rejected.
_ICON_MAGIC = {".ico": b"\x00\x00\x01\x00", ".png": b"\x89PNG"}


def window_icon() -> str | None:
    """Path to an icon this platform's webview backend can actually load.

    Windows Forms wants a real .ico and throws on anything else; the GTK and
    Cocoa backends want a .png. Returns None rather than a wrong guess.
    """
    assets = Path(__file__).resolve().parent / "assets"
    want = ".ico" if sys.platform == "win32" else ".png"
    candidate = assets / f"learnometry{want}"
    try:
        if candidate.is_file():
            with candidate.open("rb") as fh:
                if fh.read(4) == _ICON_MAGIC[want]:
                    return str(candidate)
    except OSError:
        pass
    return None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_up(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def start_server(port: int):
    import uvicorn

    from backend import app as app_module

    config = uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="learnometry-server")
    thread.start()
    return server, thread


def serve_in_browser(url: str, thread) -> int:
    """Keep serving and hand the page to the default browser.

    The same app, in a tab instead of a frame. This is the path that works
    everywhere, so it is also the escape hatch when the native window will not
    cooperate on a particular machine.
    """
    import webbrowser

    print(f"{APP_NAME} is running at {url}")
    webbrowser.open(url)
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    return 0


def want_browser() -> bool:
    """Skip the native window: `python desktop.py --browser`, or the env var."""
    return "--browser" in sys.argv or bool(os.environ.get("LEARNOMETRY_BROWSER"))


def main() -> int:
    os.environ.setdefault("LEARNOMETRY_DATA", str(data_dir()))
    ensure_streams()
    data_dir().mkdir(parents=True, exist_ok=True)

    # Bundled resources sit next to the executable when frozen.
    if is_frozen():
        os.chdir(Path(sys._MEIPASS))       # type: ignore[attr-defined]
        sys.path.insert(0, str(Path(sys._MEIPASS)))   # type: ignore[attr-defined]

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    server, thread = start_server(port)

    if not wait_until_up(port):
        print("The server did not start. Run `python -m uvicorn backend.app:app` "
              "to see the error.", file=sys.stderr)
        return 1

    if want_browser():
        return serve_in_browser(url, thread)

    try:
        import webview          # pywebview

        window = webview.create_window(
            APP_NAME, url,
            width=1280, height=880, min_size=(900, 640),
            confirm_close=False,
        )
        # The icon is decoration. It gets its own careful handling because
        # handing Windows Forms a PNG throws an unhandled .NET exception on the
        # GUI thread, which kills the process outright - no Python `except`
        # anywhere can catch it, and under pythonw.exe there is no console to
        # print to, so the user clicks the icon and simply nothing happens.
        # The only workable guard is to never pass a file the backend can't use.
        icon = window_icon()
        try:
            webview.start(icon=icon) if icon else webview.start()
        except TypeError:
            # Older pywebview has no icon= parameter at all.
            webview.start()
        return 0
    except ImportError:
        # No native webview installed. Better to open her browser and say so
        # than to fail with an import error she has no way to act on.
        print("(Native window unavailable - install pywebview for the app window.)")
        return serve_in_browser(url, thread)
    except Exception as exc:                # noqa: BLE001
        print(f"Native window failed ({type(exc).__name__}: {exc}).")
        return serve_in_browser(url, thread)


def _log_crash(exc: BaseException) -> Path:
    """pythonw.exe has no stderr, so a crash otherwise leaves nothing at all."""
    import traceback

    path = data_dir() / "crash.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    except OSError:
        pass
    return path


if __name__ == "__main__":
    ensure_streams()
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:            # noqa: BLE001
        where = _log_crash(exc)
        print(f"{APP_NAME} failed to start: {exc}", file=sys.stderr)
        print(f"Details written to {where}", file=sys.stderr)
        sys.exit(1)
