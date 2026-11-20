"""Per-CLI model, reasoning effort, plan and limit-warning threshold chosen in the console, plus how often the
limits are looked up.

Kept in <data>/cli_settings.json (next to the database, so a demo or test data set has its own). It wins over the
hand-edited config.local.yaml `cli_options` / `cli_models`, which remain as the fallback; an empty choice means
"whatever the CLI itself would use".

    {"claude": {"model": "sonnet", "effort": "medium", "plan": "max_5x", "warn_percent": 80}, "openai": {...},
     "antigravity": {...}, "usage_poll_minutes": 5}

"warn_percent": the console warns when a limit (5-hour or weekly) of that CLI is used this much or more.
"usage_poll_minutes": how often the three CLIs are asked for their limits.

"plan" is only what the operator says they subscribe to, for the CLIs that do not report it; it is shown as
their own choice and changes nothing about how a CLI is called.

Values end up on a command line, so only plain model names and the known effort words are accepted.
"""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CLIS = ("claude", "openai", "antigravity")
EFFORTS = {"claude": ["low", "medium", "high", "xhigh", "max"],
           "openai": ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"],
           "antigravity": ["low", "medium", "high", "xhigh", "max"]}
# Shown when a CLI does not report its plan. Names change over time: "other" is always offered, and an unknown
# saved value is dropped rather than shown as fact.
PLANS = {"claude": [("free", "Free"), ("pro", "Pro"), ("max_5x", "Max 5x"), ("max_20x", "Max 20x"), ("team", "Team"),
                    ("enterprise", "Enterprise"), ("other", "Other")],
         "openai": [("free", "Free"), ("go", "Go"), ("plus", "Plus"), ("pro", "Pro"), ("business", "Business"),
                    ("enterprise", "Enterprise"), ("edu", "Edu"), ("other", "Other")],
         "antigravity": [("free", "Free"), ("ai_pro", "Google AI Pro"), ("ai_ultra", "Google AI Ultra"),
                         ("enterprise", "Gemini Enterprise"), ("other", "Other")]}
POLL_MINUTES = [1, 5, 10, 30]
DEFAULT_POLL_MINUTES, DEFAULT_WARN_PERCENT = 5, 80
CLAUDE_MODELS = ["fable", "opus", "sonnet", "haiku"]                 # the CLI's own aliases for "latest of that tier"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,99}$")       # the same rule core.cli_models applies
_LOCK = threading.Lock()
_AGY_MODELS: Dict[str, Any] = {"at": 0.0, "models": [], "busy": False}
AGY_MODELS_TTL = 6 * 3600


def path() -> Path:
    from core.db_path import get_db_path
    return get_db_path().parent / "cli_settings.json"


def _empty() -> Dict[str, Any]:
    return {**{cli: {"model": None, "effort": None, "plan": None, "warn_percent": DEFAULT_WARN_PERCENT} for cli in CLIS},
            "usage_poll_minutes": DEFAULT_POLL_MINUTES}


def validate(payload: Any, forgiving: bool = False) -> Dict[str, Any]:
    """A complete, clean settings object from whatever was sent; raises ValueError naming the bad field.
    forgiving=True (reading the saved file): a plan name this version no longer lists is dropped, nothing else is lost."""
    if not isinstance(payload, dict):
        raise ValueError("settings must be an object")
    out = _empty()
    for cli in CLIS:
        chosen = payload.get(cli) or {}
        if not isinstance(chosen, dict):
            raise ValueError(f"{cli}: must be an object")
        model, effort, plan = chosen.get("model") or None, chosen.get("effort") or None, chosen.get("plan") or None
        if plan is not None and (not isinstance(plan, str) or plan not in {ident for ident, _ in PLANS[cli]}):
            if not forgiving:
                raise ValueError(f"{cli}: unknown plan")
            plan = None
        if model is not None and (not isinstance(model, str) or not _MODEL_RE.match(model)):
            raise ValueError(f"{cli}: model name is not valid")
        if effort is not None and effort not in EFFORTS[cli]:
            raise ValueError(f"{cli}: effort must be one of {', '.join(EFFORTS[cli])}")
        if cli == "antigravity" and model and not forgiving:    # saving: a full id ("…-high") becomes base model + level
            base, level = split_agy_model(model)                # (not on load: a stored base name is never split again)
            if level and (not _AGY_MODELS["models"] or any(m["id"] == model for m in _AGY_MODELS["models"])):
                model, effort = base, effort or level
        warn = chosen.get("warn_percent", DEFAULT_WARN_PERCENT)
        if isinstance(warn, bool) or not isinstance(warn, int) or not 1 <= warn <= 100:
            if not forgiving:
                raise ValueError(f"{cli}: warning threshold must be a whole number from 1 to 100")
            warn = DEFAULT_WARN_PERCENT
        out[cli] = {"model": model, "effort": effort, "plan": plan, "warn_percent": warn}
    minutes = payload.get("usage_poll_minutes", DEFAULT_POLL_MINUTES)
    if isinstance(minutes, bool) or minutes not in POLL_MINUTES:
        if not forgiving:
            raise ValueError(f"usage_poll_minutes must be one of {POLL_MINUTES}")
        minutes = DEFAULT_POLL_MINUTES
    out["usage_poll_minutes"] = minutes
    return out


def load() -> Dict[str, Any]:
    try:
        return validate(json.loads(path().read_text(encoding="utf-8")), forgiving=True)
    except (OSError, ValueError, TypeError):
        return _empty()                           # missing or damaged file: CLI defaults


def save(payload: Any) -> Dict[str, Any]:
    settings = validate(payload)
    with _LOCK:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, target)
    return settings


def choice(cli: str) -> Dict[str, Optional[str]]:
    """{"model", "effort"} for one CLI; both None under unit tests so commands stay as upstream built them."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return {"model": None, "effort": None, "plan": None, "warn_percent": DEFAULT_WARN_PERCENT}
    return load().get(cli) or {"model": None, "effort": None, "plan": None, "warn_percent": DEFAULT_WARN_PERCENT}


# ------------------------------------------------------------------ what can be chosen
def _codex_models() -> List[Dict[str, Any]]:
    base = os.environ.get("CODEX_HOME")
    cache = (Path(base).expanduser() if base else Path.home() / ".codex") / "models_cache.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = data.get("models") if isinstance(data, dict) else data
    out = []
    for model in models if isinstance(models, list) else []:
        slug = model.get("slug") or model.get("id") if isinstance(model, dict) else None
        if isinstance(slug, str) and _MODEL_RE.match(slug) and model.get("visibility", "list") != "hide":
            levels = model.get("supported_reasoning_levels") or []
            efforts = [e.get("effort") if isinstance(e, dict) else e for e in levels if isinstance(levels, list)]
            entry = {"id": slug, "name": model.get("display_name") or slug}
            efforts = [e for e in efforts if e in EFFORTS["openai"]]
            if efforts:
                entry["efforts"] = efforts          # the console offers only what this model accepts
            out.append(entry)
    return out[:40]


AGY_LEVEL_RE = re.compile(r"^(.+)-(low|medium|high|xhigh|max)$")


def split_agy_model(model: Optional[str]):
    """'gemini-4-neon-high' -> ('gemini-4-neon', 'high'); a name without a level -> (name, None).
    Antigravity lists every model once per thinking level. The CLI takes either that full id, or the base name
    plus --effort — but refuses a full id together with --effort, so the two are kept apart here."""
    match = AGY_LEVEL_RE.match(model or "")
    return (match.group(1), match.group(2)) if match else (model or None, None)


def group_agy_models(models: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """One entry per base model with the levels it comes in: [{"id": base, "name": ..., "efforts": [...]}]."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for model in models:
        base, level = split_agy_model(model["id"])
        entry = grouped.setdefault(base, {"id": base, "name": re.sub(r"\s*\((?:Low|Medium|High|XHigh|Max)\)\s*$", "", model["name"]) or base,
                                          "efforts": []})
        if level and level not in entry["efforts"]:
            entry["efforts"].append(level)
    for entry in grouped.values():
        entry["efforts"].sort(key=EFFORTS["antigravity"].index)
    return list(grouped.values())


def parse_agy_models(text: str) -> List[Dict[str, str]]:
    """`agy models` prints one `id<TAB>name` per line after a status line."""
    out = []
    for line in text.splitlines():
        ident, _, name = line.partition("\t")
        ident = ident.strip()
        if name.strip() and _MODEL_RE.match(ident):
            out.append({"id": ident, "name": name.strip()})
    return out[:80]


def _refresh_agy_models() -> None:
    try:
        from core.env_utils import get_sanitized_env, resolve_cli
        exe = resolve_cli("agy")
        if exe:
            done = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=40, env=get_sanitized_env(),
                                  stdin=subprocess.DEVNULL)
            models = parse_agy_models(done.stdout)
            if models:
                _AGY_MODELS["models"] = models
    except Exception:
        pass
    finally:
        _AGY_MODELS.update(at=time.time(), busy=False)


def _agy_models() -> List[Dict[str, str]]:
    """Asked from the CLI in the background (it goes to the network); the panel shows the list once it is there."""
    stale = time.time() - _AGY_MODELS["at"] > AGY_MODELS_TTL
    if stale and not _AGY_MODELS["busy"] and os.environ.get("DIRECTOR_TESTING") != "1":
        _AGY_MODELS["busy"] = True
        threading.Thread(target=_refresh_agy_models, name="agy-models", daemon=True).start()
    return list(_AGY_MODELS["models"])


def agy_levels(model: Optional[str]) -> Optional[List[str]]:
    """The levels the CLI lists for this base model; None when the list is not known (yet) or does not have it."""
    for entry in group_agy_models(_AGY_MODELS["models"]):
        if entry["id"] == model:
            return entry["efforts"]
    return None


def options() -> Dict[str, Any]:
    plans = {cli: [{"id": ident, "name": name} for ident, name in PLANS[cli]] for cli in CLIS}
    return {"poll_minutes": POLL_MINUTES,
            "claude": {"models": [{"id": m, "name": m} for m in CLAUDE_MODELS], "efforts": EFFORTS["claude"], "plans": plans["claude"]},
            "openai": {"models": _codex_models(), "efforts": EFFORTS["openai"], "plans": plans["openai"]},
            "antigravity": {"models": group_agy_models(_agy_models()), "efforts": EFFORTS["antigravity"], "plans": plans["antigravity"]}}
