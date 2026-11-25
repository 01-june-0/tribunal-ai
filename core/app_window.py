"""`tribunal app`: the console in a window of its own instead of a browser tab (docs/PACKAGING.md, phase 4).

The window shows the same page the browser does (http://127.0.0.1:<port>), through pywebview: WebKit on macOS, Edge
WebView2 on Windows. Linux needs GTK or Qt from the system, which an installed copy cannot see, so there the console
opens in the browser as before.

Who turns the console off:
- An app window that started the console is its owner (data/app-owner.json). When the last app window closes, the owner
  turns the console off. A console that was already running (opened in the browser, `tribunal start`) stays on.
- Closing that last window while work runs asks first; yes stops the work the way the 작업 정지 button does (the AI
  processes end, records and working copies stay, it can be continued later), then the console goes off.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.paths import data_dir

TITLE = "Tribunal AI"
SMOKE_TRIES, SMOKE_PAUSE = 40, 0.5              # the installer check waits up to 20 s for the console to draw
SMOKE_LIMIT = 180.0                              # ... and ends the process after 3 minutes whatever happens
CONFIRM = ("작업이 진행 중입니다. 창을 닫으면 작업을 정지하고 콘솔을 끕니다.\n"
           "기록과 작업 사본은 남고, 다음에 이어서 할 수 있습니다.\n\n"
           "Work is running. Closing the window stops it and turns the console off.\n"
           "Records and working copies stay; it can be continued later.")


def unavailable() -> Optional[str]:
    """Why a window cannot be shown here, or None when it can."""
    if sys.platform not in ("darwin", "win32"):
        return "이 운영체제에서는 창 대신 브라우저로 엽니다 / this system opens the console in the browser"
    try:
        import webview  # noqa: F401
        if sys.platform == "win32":
            # Without the Edge WebView2 runtime pywebview quietly falls back to Internet Explorer, where the console's
            # JavaScript does not run: the browser is better then.
            from webview.platforms import winforms
            if not getattr(winforms, "is_chromium", False):
                return "Edge WebView2가 없어 브라우저로 엽니다 / no Edge WebView2 runtime, opening the browser"
    except Exception as exc:                        # not installed, or its system parts are missing
        return f"창 기능을 불러오지 못했습니다 / the window library did not load: {type(exc).__name__}: {exc}"
    return None


# ---- who owns the console --------------------------------------------------------------------------------------------

def _owner_file() -> Path:
    return data_dir() / "app-owner.json"


def _windows_dir() -> Path:
    return data_dir() / "app-windows"


def _alive(pid: int) -> bool:
    """Whether that process is a running `tribunal app` (a reused number of some other program does not count)."""
    try:
        import psutil
        line = " ".join(psutil.Process(pid).cmdline())
        return "tribunal" in line and " app" in f" {line}"
    except Exception:
        return False


def register(pid: int) -> None:
    _windows_dir().mkdir(parents=True, exist_ok=True)
    (_windows_dir() / str(pid)).write_text("", encoding="utf-8")


def unregister(pid: int) -> None:
    (_windows_dir() / str(pid)).unlink(missing_ok=True)


def other_windows(pid: int) -> List[int]:
    """Other app windows that are still open (files of ended ones are cleared on the way)."""
    found = []
    folder = _windows_dir()
    for item in (folder.iterdir() if folder.is_dir() else []):
        try:
            other = int(item.name)
        except ValueError:
            continue
        if other == pid:
            continue
        if _alive(other):
            found.append(other)
        else:
            item.unlink(missing_ok=True)
    return found


def claim(console_pid: Optional[int]) -> None:
    """Record that an app window started this console."""
    if console_pid:
        _owner_file().write_text(json.dumps({"console_pid": console_pid}), encoding="utf-8")


def owned(console_pid: Optional[int]) -> bool:
    """Whether the running console is one an app window started."""
    try:
        return bool(console_pid) and json.loads(_owner_file().read_text(encoding="utf-8")).get("console_pid") == console_pid
    except (OSError, ValueError, AttributeError):
        return False


def release() -> None:
    _owner_file().unlink(missing_ok=True)


# ---- asking the console ----------------------------------------------------------------------------------------------

def _open(request, timeout: float):
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def busy(url: str) -> Optional[bool]:
    """Whether the console is working now: a live mission or an AI call in progress. None when it cannot be told
    (no answer in time, an error) - the callers treat that like busy, never like idle."""
    try:
        with _open(f"{url}/ops/activity", timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return bool(data.get("working_now")) or any(m.get("live") for m in data.get("missions") or [])


def stop_work(url: str) -> bool:
    """The 작업 정지 button: running missions stop and their AI processes end; records and working copies stay."""
    from core.companion_config import bridge_token_path
    from core.paths import home
    try:
        token = bridge_token_path(home()).read_text(encoding="utf-8").strip()
        request = urllib.request.Request(
            f"{url}/ops/missions/stop", method="POST",
            data=json.dumps({"reason": "앱 창을 닫음", "by": "앱 창"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Tribunal-Token": token, "Origin": url})
        with _open(request, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


# ---- the window --------------------------------------------------------------------------------------------------------

def _size(webview) -> Dict[str, int]:
    """A window that fits the screen: up to 1360 x 880, never past 92% of it."""
    width, height = 1360, 880
    try:
        screen = webview.screens[0]
        width, height = min(width, int(screen.width * 0.92)), min(height, int(screen.height * 0.9))
    except Exception:
        pass
    return {"width": max(width, 960), "height": max(height, 640)}


def _name_the_mac_app() -> None:
    """The menu bar says "Python" unless the running bundle is given a name (Python itself is the program here)."""
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = TITLE
    except Exception:
        pass


def show(url: str, will_stop_console: Callable[[], bool], smoke: bool = False,
         webview_module: Any = None) -> Dict[str, Any]:
    """Show the console in a window until it is closed. Returns {"stopped_work": bool, "smoke": result or None}.

    Runs on the main thread (the GUI toolkits need it). Closing while work runs is cancelled at first, then asked in a
    dialog from another thread: on macOS a dialog opened from inside the closing handler would wait on itself."""
    webview = webview_module
    if webview is None:
        import webview                               # noqa: F811
    state: Dict[str, Any] = {"confirmed": False, "asking": False, "stopped_work": False, "smoke": None}
    window = webview.create_window(TITLE, url, min_size=(960, 640), text_select=True, background_color="#04060c",
                                   **_size(webview))

    def decide() -> None:
        """Off the GUI thread: ask when closing would stop work (or when it cannot be told), then close for real."""
        try:
            if will_stop_console() and busy(url) is not False:
                if not window.create_confirmation_dialog(TITLE, CONFIRM):
                    return                           # "cancel": the window and the work stay
                state["stopped_work"] = stop_work(url)
            state["confirmed"] = True
            window.destroy()
        finally:
            state["asking"] = False

    def on_closing() -> Optional[bool]:
        """Every close - the red button, Cmd+Q, Alt+F4 - is cancelled once and decided by decide(); the close it then
        makes goes through. On macOS a quit that is not cancelled ends the process inside the GUI loop, before the
        console could be turned off."""
        if state["confirmed"]:
            return None
        if not state["asking"]:
            state["asking"] = True
            threading.Thread(target=decide, name="tribunal-app-close", daemon=True).start()
        return False

    window.events.closing += on_closing

    def smoke_check() -> None:
        """For the installer check: the page loads and the console draws, then the window closes by itself."""
        result = None
        try:
            if window.events.loaded.wait(60):
                for _ in range(SMOKE_TRIES):
                    try:
                        # run_js, not evaluate_js: evaluate_js wraps the code in eval(), which the console's
                        # Content-Security-Policy refuses. The window's own call is not bound by the page's policy.
                        result = window.run_js("document.querySelector('#ai-setup') ? document.title : ''")
                    except Exception:
                        result = None
                    if result and "TRIBUNAL" in str(result):
                        break
                    threading.Event().wait(SMOKE_PAUSE)
        finally:
            state["smoke"] = str(result) if result and "TRIBUNAL" in str(result) else ""
            state["confirmed"] = True
            window.destroy()

    if sys.platform == "darwin":
        _name_the_mac_app()
    storage = data_dir() / "app-window"              # the console keeps its settings in the page's storage
    storage.mkdir(parents=True, exist_ok=True)
    watchdog = None
    if smoke:                                        # a check must never hang the machine it runs on
        import os
        watchdog = threading.Timer(SMOKE_LIMIT, lambda: os._exit(4))
        watchdog.daemon = True
        watchdog.start()
    try:
        webview.start(smoke_check if smoke else None, private_mode=False, storage_path=str(storage))
    finally:
        if watchdog:
            watchdog.cancel()                        # the window ended: nothing left to guard
    return state
