"""Native folder dialog (tkinter on Windows/Linux, osascript on macOS) for the 8081 console. A browser never reveals a folder's absolute path, so the local
companion server runs this helper and reads the choice from stdout: one JSON line {"path": "..."} ("" = cancelled)."""
import json
import sys


TITLE = "TRIBUNAL AI - 작업할 폴더 선택"


def pick_macos(initial: str):
    """macOS: the system folder dialog through osascript, so no python-tk is needed (Homebrew python ships without
    it). Returns the chosen path, '' when cancelled, or None when the dialog could not be shown."""
    import os
    import subprocess
    # The console runs in the background, where macOS refuses a dialog of osascript's own ("user interaction is not
    # allowed", -1713). System Events shows it instead, in front of the other windows. The first time, macOS may ask
    # to let this program control System Events.
    script = [
        "on run argv",
        "  set startDir to item 1 of argv",
        "  set dialogTitle to item 2 of argv",
        "  tell application \"System Events\"",
        "    activate",
        "    if startDir is \"\" then",
        "      set chosen to choose folder with prompt dialogTitle",
        "    else",
        "      set chosen to choose folder with prompt dialogTitle default location (POSIX file startDir)",
        "    end if",
        "  end tell",
        "  return POSIX path of chosen",
        "end run",
    ]
    argv = ["osascript"]
    for line in script:
        argv += ["-e", line]
    start = initial if initial and os.path.isdir(initial) else ""
    try:
        out = subprocess.run(argv + [start, TITLE], capture_output=True)
    except OSError:
        return None
    if out.returncode != 0:
        if b"-1743" in out.stderr:                           # not allowed to control System Events
            sys.stderr.write("automation not allowed\n")
            sys.exit(3)
        return "" if b"-128" in out.stderr else None          # -128 = the user pressed Cancel
    chosen = out.stdout.decode("utf-8", "replace").strip()
    return chosen.rstrip("/") or "/"


def main() -> int:
    if sys.platform == "darwin":
        chosen = pick_macos(sys.argv[1] if len(sys.argv) > 1 else "")
        if chosen is not None:
            sys.stdout.buffer.write(json.dumps({"path": chosen}).encode("ascii"))
            return 0
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:          # e.g. Homebrew python on macOS without python-tk: type the path in the console instead
        sys.stderr.write("tkinter unavailable\n")
        return 1
    initial = sys.argv[1] if len(sys.argv) > 1 else ""
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)          # the dialog must not open behind the browser
    root.update()
    chosen = filedialog.askdirectory(parent=root, initialdir=initial or None, mustexist=True,
                                     title=TITLE)
    root.destroy()
    sys.stdout.buffer.write(json.dumps({"path": chosen or ""}).encode("ascii"))   # ensure_ascii: safe on any codepage
    return 0


if __name__ == "__main__":
    sys.exit(main())
