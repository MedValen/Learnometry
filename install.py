"""
Make Learnometry behave like an installed application.

Creates Start Menu and Desktop shortcuts that launch the app with pythonw.exe -
no console window, no browser, no command to remember. Nothing is copied or
moved: the shortcuts point at this folder, so `git pull` or an edit here updates
the installed app immediately.

    python install.py            add shortcuts
    python install.py --remove   take them away again

This is the lightweight route and it works today. `build_desktop.py` produces a
standalone .exe if you'd rather not depend on this folder staying put.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "Learnometry"


def venv_pythonw() -> Path:
    """pythonw.exe runs without a console window - that's the whole trick."""
    candidates = [
        ROOT / ".venv" / "Scripts" / "pythonw.exe",
        Path(sys.executable).with_name("pythonw.exe"),
        Path(sys.executable),
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path(sys.executable)


def make_icon() -> Path | None:
    """Draw an icon if Pillow is around; skip quietly if not."""
    ico = ROOT / "assets" / "learnometry.ico"
    if ico.exists():
        return ico
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    ico.parent.mkdir(parents=True, exist_ok=True)
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, size - 8, size - 8], radius=52, fill=(47, 111, 143, 255))
    # Fallback mark, only used when the real icon asset is missing.
    d.rectangle([76, 76, size - 76, size - 76], outline=(255, 255, 255, 255), width=14)
    d.rectangle([112, 112, size - 112, size - 112], fill=(255, 255, 255, 255))
    img.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ico


# The app was called this before the rename. Its shortcuts point at the same
# desktop.py, so leaving them behind gives one app two icons under two names -
# and the old one still carries the old picture.
FORMER_NAMES = ["Symbol Span"]


def shortcut_folders() -> list[Path]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    return [f for f in (
        appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("USERPROFILE", home)) / "Desktop",
    ) if f.exists()]


def retire_former_names() -> int:
    """Remove shortcuts left by an earlier name, but only ours.

    A .lnk is checked against our own desktop.py before it is touched. Someone
    else's shortcut that happens to share the name is left alone.
    """
    script = str(ROOT / "desktop.py").lower()
    gone = 0
    for folder in shortcut_folders():
        for name in FORMER_NAMES:
            old = folder / f"{name}.lnk"
            if not old.exists():
                continue
            if script not in _shortcut_target(old).lower():
                print(f"  leaving {old} alone - it points somewhere else")
                continue
            old.unlink()
            print(f"Removing old shortcut {old}")
            gone += 1
    return gone


def _shortcut_target(path: Path) -> str:
    import subprocess
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "$w = New-Object -ComObject WScript.Shell; "
         f"$s = $w.CreateShortcut('{str(path)}'); "
         "Write-Output ($s.TargetPath + ' ' + $s.Arguments)"],
        capture_output=True, text=True)
    return r.stdout or ""


def shortcut_paths() -> list[Path]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    start_menu = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    desktop = Path(os.environ.get("USERPROFILE", home)) / "Desktop"

    out = []
    for folder in (start_menu, desktop):
        if folder.exists():
            out.append(folder / f"{APP_NAME}.lnk")
    return out


def write_shortcut(path: Path, target: Path, args: str, icon: Path | None) -> bool:
    """Create a .lnk via PowerShell's WScript.Shell COM object.

    The script goes to a temp .ps1 and runs with -File rather than -Command.
    Passing it inline means the quotes survive cmd, then PowerShell, then the
    string literal - and the argument here is itself a quoted path, so one of
    those layers always eats a quote. A file has no such layers.
    """
    import subprocess
    import tempfile

    def ps_quote(value: str) -> str:
        # Single-quoted PowerShell strings are literal; '' escapes a quote.
        return "'" + str(value).replace("'", "''") + "'"

    lines = [
        "$w = New-Object -ComObject WScript.Shell",
        f"$s = $w.CreateShortcut({ps_quote(path)})",
        f"$s.TargetPath = {ps_quote(target)}",
        f"$s.Arguments = {ps_quote(args)}",
        f"$s.WorkingDirectory = {ps_quote(ROOT)}",
        f"$s.Description = {ps_quote('Adaptive study app built around your WAIS-5 profile')}",
    ]
    if icon:
        lines.append(f"$s.IconLocation = {ps_quote(icon)}")
    lines.append("$s.Save()")

    tmp = Path(tempfile.mkdtemp()) / "shortcut.ps1"
    tmp.write_text("\n".join(lines), encoding="utf-8")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
            capture_output=True, text=True,
        )
    finally:
        tmp.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  failed: {(result.stderr or result.stdout).strip()[:200]}")
        return False
    return True


def install() -> int:
    if os.name != "nt":
        print("This installer is Windows-only. On macOS or Linux, run "
              "`python desktop.py` or add it to your launcher yourself.")
        return 1

    target = venv_pythonw()
    script = ROOT / "desktop.py"
    if not script.exists():
        print("desktop.py is missing.")
        return 1

    icon = make_icon()
    if icon is None:
        print("  (no icon — install Pillow for one: pip install pillow)")

    retire_former_names()

    made = 0
    for path in shortcut_paths():
        print(f"Creating {path}")
        if write_shortcut(path, target, f'"{script}"', icon):
            made += 1

    # A second shortcut that skips the native window. The embedded webview
    # depends on WebView2 and on the graphics stack behaving; when it doesn't,
    # the app is still perfectly good in a browser tab, and having that as a
    # one-click option beats being told to open a terminal.
    for path in shortcut_paths():
        alt = path.with_name(f"{APP_NAME} (browser).lnk")
        print(f"Creating {alt}")
        if write_shortcut(alt, target, f'"{script}" --browser', icon):
            made += 1

    if not made:
        print("\nNo shortcuts were created.")
        return 1

    print(f"\n{made} shortcut(s) created.")
    print(f"Launcher: {target}")
    print("\nSearch the Start Menu for 'Learnometry', or use the desktop icon.")
    print("It opens in its own window — no terminal, no browser tab.")
    print("\nIf that window comes up blank or never appears, use the")
    print("'Learnometry (browser)' shortcut instead — same app, in a tab.")
    print(f"Anything that goes wrong is logged to {ROOT / 'data' / 'crash.log'}.")
    return 0


def remove() -> int:
    n = retire_former_names()
    for path in [p for base in shortcut_paths()
                 for p in (base, base.with_name(f"{APP_NAME} (browser).lnk"))]:
        if path.exists():
            path.unlink()
            print(f"Removed {path}")
            n += 1
    print(f"{n} shortcut(s) removed." if n else "Nothing to remove.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--remove", action="store_true", help="delete the shortcuts")
    args = ap.parse_args()
    return remove() if args.remove else install()


if __name__ == "__main__":
    sys.exit(main())
