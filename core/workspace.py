"""Starting over in the console: a clean screen, a new project folder, or the current project put in the trash.

The console's stage shows the newest task. "새로 시작" records when the person asked for a clean screen; a task that
is not running and was last touched before that is no longer the one the stage shows (its records stay). A new
project is an empty folder under Documents/Tribunal Projects by default. Discarding a project moves its folder to the
operating system's trash (it can be restored from there), never deletes it outright.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

NAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,80}$")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _screen_path() -> Path:
    from core.paths import data_dir
    return data_dir() / "screen.json"


def cleared_at() -> str:
    """UTC ISO time of the last clean screen ('' when never)."""
    try:
        data = json.loads(_screen_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("cleared_at") or "") if isinstance(data, dict) else ""


def clear_screen() -> str:
    stamp = datetime.utcnow().isoformat()
    path = _screen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"screen.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps({"cleared_at": stamp}), encoding="utf-8")
    os.replace(tmp, path)
    return stamp


def default_parent() -> Path:
    """Where a new project goes unless the person picks another place: Documents/Tribunal Projects."""
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "Tribunal Projects"


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME.match(name) or name in (".", "..") or name.endswith((".", " ")) or name.split(".")[0].lower() in RESERVED:
        raise ValueError('폴더 이름으로 쓸 수 없습니다. \\ / : * ? " < > | 는 빼고, 점이나 공백으로 끝나지 않게 써 주세요.')
    return name


def create_project_folder(name: str, parent: Optional[str] = None) -> Path:
    """An empty new folder for a project. An existing folder of that name is refused, never reused."""
    base = Path(parent).expanduser() if parent else default_parent()
    if not base.is_absolute():
        raise ValueError("만들 위치는 절대 경로여야 합니다.")
    target = base / check_name(name)
    if target.exists():
        raise ValueError(f"이미 있는 이름입니다: {target}")
    target.mkdir(parents=True)
    return target


def _unique(folder: Path, name: str) -> Path:
    candidate = folder / name
    n = 2
    while candidate.exists():
        candidate = folder / f"{name} {n}"
        n += 1
    return candidate


def move_to_trash(path: Path) -> Dict[str, str]:
    """Moves a folder to the operating system's trash, where the person can restore it. Returns {"where": ...}."""
    path = Path(path).resolve()
    if not path.is_dir():
        raise ValueError("폴더가 없습니다.")
    if sys.platform == "darwin":
        trash = Path.home() / ".Trash"
        target = _unique(trash, path.name)
        shutil.move(str(path), str(target))
        return {"where": str(target)}
    if os.name == "nt":
        # Only a local fixed drive has a Recycle Bin that takes the folder. With AllDialogs, Windows itself shows the
        # progress and - when the folder does not fit in the Recycle Bin - asks before deleting it for good; cancelling
        # there stops everything (an exception, a non-zero exit). Never OnlyErrorDialogs: that deletes such a folder
        # without asking (critic, 2026-11-26).
        if not _fixed_local_drive(path):
            raise ValueError("네트워크나 이동식 드라이브의 폴더는 휴지통으로 옮길 수 없습니다. 파일 탐색기에서 직접 지워 주세요.")
        script = ("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
                  "$env:TRIBUNAL_TRASH_PATH, 'AllDialogs', 'SendToRecycleBin', 'ThrowException')")
        env = {**os.environ, "TRIBUNAL_TRASH_PATH": str(path)}           # the path never goes into the script text
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                             capture_output=True, text=True, timeout=3600, stdin=subprocess.DEVNULL)
        if out.returncode != 0 or path.exists():
            raise OSError("휴지통으로 옮기지 못했습니다: " + (out.stderr or out.stdout).strip()[:300])
        return {"where": "휴지통 (Recycle Bin)"}
    gio = shutil.which("gio")
    if gio and subprocess.run([gio, "trash", str(path)], capture_output=True, timeout=300).returncode == 0:
        return {"where": "휴지통 (Trash)"}
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Trash"   # freedesktop.org trash
    (base / "files").mkdir(parents=True, exist_ok=True)
    (base / "info").mkdir(parents=True, exist_ok=True)
    target = _unique(base / "files", path.name)
    from urllib.parse import quote
    (base / "info" / (target.name + ".trashinfo")).write_text(
        f"[Trash Info]\nPath={quote(str(path))}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n", encoding="utf-8")
    shutil.move(str(path), str(target))
    return {"where": str(target)}


def _fixed_local_drive(path: Path) -> bool:
    if str(path).startswith("\\\\"):
        return False                                            # a UNC (network) path
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 3     # DRIVE_FIXED
    except Exception:
        return False


def _same(a: Path, b: Path) -> bool:
    """The same folder on disk. Compared by the file system itself: macOS and Windows ignore case, so
    /users/edm/developer IS ~/Developer, which a path comparison does not see (critic, 2026-11-26)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _protected_folders() -> list:
    home = Path.home()
    names = ("Documents", "Desktop", "Downloads", "Library", "Pictures", "Music", "Movies", "Videos", "Public",
             "Applications", "AppData", "OneDrive", "Dropbox", "iCloud Drive", "Google Drive", ".Trash", "Developer",
             "Projects", "src", "code", "workspace", "repos")
    out = [home, Path(home.anchor), default_parent()] + [home / n for n in names]
    out += [p for p in home.glob("OneDrive*")] + [Path(os.environ[k]) for k in ("USERPROFILE", "APPDATA", "LOCALAPPDATA",
                                                                              "PROGRAMFILES", "SYSTEMROOT") if os.environ.get(k)]
    return [p for p in out if p.exists()]


def discardable(path: Path, other_projects=()) -> Optional[str]:
    """Why this folder may not be put in the trash as a project (None when it may). Refused: a broad or standard
    folder, a mount point, anything that holds Tribunal AI or is inside it, and a folder that holds another project
    Tribunal knows (`other_projects`). Every comparison asks the file system, so a path spelled in another case is the
    same folder."""
    from core.paths import home as tribunal_home, CODE_ROOT
    try:
        p = Path(path).resolve()
    except OSError:
        return "폴더를 읽을 수 없습니다."
    if not p.is_dir():
        return "폴더가 없습니다."
    if len(p.parts) < 3 or os.path.ismount(p) or any(_same(p, broad) for broad in _protected_folders()):
        return "이 폴더는 프로젝트 폴더로 버릴 수 없습니다."
    chain = [p, *p.parents]
    for keep in (Path(tribunal_home()), Path(CODE_ROOT)):
        keep_chain = [keep, *keep.parents]
        if any(_same(a, keep) for a in chain) or any(_same(p, k) for k in keep_chain):
            return "Tribunal AI 자신이 들어 있는 폴더는 버릴 수 없습니다."
    for other in other_projects:
        try:
            o = Path(other)
            if o.exists() and not _same(o, p) and any(_same(a, p) for a in o.parents):
                return f"이 폴더 안에 다른 프로젝트가 있습니다: {o.name}"
        except OSError:
            continue
    return None
