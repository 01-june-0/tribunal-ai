"""Is there a newer Tribunal AI? (docs/PACKAGING.md, phase 5)

Asks GitHub for the latest release of the public repository at most once a day and remembers the answer in
data/update-check.json. Nothing about the person or the machine is sent: a plain GET with a generic User-Agent.
It never blocks for long (a few seconds at most), never raises, and stays quiet in tests and CI
(TRIBUNAL_NO_UPDATE_CHECK=1).

The installers only ever get a release; the one-line installer installs the main branch, so for those copies "newer"
means a release with a higher number than the one they report.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

from core.paths import data_dir

REPO = "01-june-0/tribunal-ai"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
DAY = 24 * 3600


def current() -> str:
    try:
        from importlib.metadata import version
        return version("tribunal-ai")
    except Exception:
        found = re.search(r'^version\s*=\s*"([^"]+)"', _pyproject(), re.M)
        return found.group(1) if found else "0"


def _pyproject() -> str:
    from core.paths import CODE_ROOT
    try:
        return (CODE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""


def parse(text: str) -> Tuple:
    """A comparable key for "v3.2.0", "3.2.0", "3.2.0.dev0", "3.2.0rc1": a development or pre-release comes before
    the release of the same number."""
    found = re.match(r"v?(\d+(?:\.\d+)*)(?:[.-]?(dev|a|alpha|b|beta|rc)\.?(\d+)?)?", (text or "").strip(), re.I)
    if not found:
        return ()
    numbers = tuple(int(n) for n in found.group(1).split("."))
    numbers += (0,) * (4 - len(numbers))
    stage = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "rc": 3}.get((found.group(2) or "").lower(), 4)
    return numbers + (stage, int(found.group(3) or 0))


def newer(latest: str, mine: str) -> bool:
    a, b = parse(latest), parse(mine)
    return bool(a and b) and a > b


def _cache_path():
    return data_dir() / "update-check.json"


def _fetch(timeout: float) -> Optional[Dict[str, Any]]:
    request = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "tribunal-ai-update-check"})
    with urllib.request.urlopen(request, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = str(data.get("tag_name") or "").strip()
    url = str(data.get("html_url") or "")
    if not tag or not url.startswith(f"https://github.com/{REPO}/"):
        return None
    return {"latest": tag, "url": url}


def check(timeout: float = 4.0, now: Optional[float] = None) -> Dict[str, Any]:
    """{"current", "latest", "newer", "url", "checked_at"}; latest is None when nothing is known (no release yet,
    offline, switched off)."""
    mine = current()
    result: Dict[str, Any] = {"current": mine, "latest": None, "newer": False, "url": RELEASES, "checked_at": None}
    if os.environ.get("TRIBUNAL_NO_UPDATE_CHECK"):
        return result
    now = time.time() if now is None else now
    try:
        cached = json.loads(_cache_path().read_text(encoding="utf-8"))
        checked = float(cached["checked_at"])
    except (OSError, ValueError, TypeError, KeyError):
        cached, checked = {}, None                   # none yet, or damaged: ask again
    if not isinstance(cached, dict):
        cached, checked = {}, None
    if checked is None or now - checked > DAY:
        try:
            found = _fetch(timeout)
        except Exception:
            found = None                             # offline, rate-limited, no release yet (404): try again tomorrow
        # A failed check keeps what was known; only an answer replaces it.
        cached = {**{k: cached[k] for k in ("latest", "url") if k in cached}, **(found or {}), "checked_at": now}
        try:
            _cache_path().parent.mkdir(parents=True, exist_ok=True)
            _cache_path().write_text(json.dumps(cached), encoding="utf-8")
        except OSError:
            pass
    latest = cached.get("latest")
    if latest:
        result.update(latest=latest, url=cached.get("url") or RELEASES, newer=newer(latest, mine))
    result["checked_at"] = cached.get("checked_at")
    return result
