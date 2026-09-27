"""
kriti_personas.py — Swappable persona system for Kriti.

Each persona is a JSON file in ~/.life_missions/personas/.
A persona defines:
  - name:            display name (and filename key)
  - system_prompt:   replaces / prepends to KRITI_CONTEXT for this persona
  - knowledge_dirs:  list of absolute folder paths (or []) — scopes RAG retrieval
                     [] means "use full index" (default general-assistant behaviour)
                     A non-empty list restricts retrieval to those dirs only
  - allowed_actions: list of action tag names this persona may invoke, e.g.
                     ["DONE","UNDONE","ADD_TASK","START_POMODORO","OPEN_APP"]
                     Use ["*"] as a shorthand for "all actions"
  - keywords:        optional list of strings for context-based auto-inference
                     (checked against user message if no explicit selection is set)

Persona selection priority:
  1. Explicit — user typed `/persona <name>` or Kriti emitted [[SET_PERSONA:name]]
  2. Inferred  — first persona whose keywords match the current user message
  3. Default   — falls back to "general" persona if one exists, else no persona

The persona enforcement point for action tags lives in parse_kriti_actions
(called from kriti.py) — a persona literally cannot fire a tag outside its
allowed_actions list, even if the model emits it.
"""

import json
import os
import re

SAVE_DIR      = os.path.expanduser("~/.life_missions")
PERSONAS_DIR  = os.path.join(SAVE_DIR, "personas")
ACTIVE_FILE   = os.path.join(SAVE_DIR, "active_persona.json")

# The full set of action tags recognised by kriti.py (used for wildcard expand)
ALL_KRITI_ACTIONS = [
    "DONE", "UNDONE", "ADD_TASK", "ADD_RECURRING",
    "ADD_QUEST", "QUEST_DONE", "START_POMODORO",
    "OPEN_APP", "RUN_SCRIPT", "SET_VOLUME", "LOCK_SCREEN",
    "RAG_INDEX", "SET_PERSONA",
    # Jarvis-tier additions
    "SPOTIFY", "BRIEFING", "CALENDAR_REFRESH",
    # System control / perception — must be listed here or a "*" persona
    # (e.g. general) silently blocks them.
    "CLOSE_APP", "LIST_APPS", "FOCUS_WINDOW", "FILE_SEARCH", "FILE_OPEN",
    "CLIPBOARD_READ", "CLIPBOARD_WRITE", "OPEN_URL", "DESCRIBE_SCREEN",
    "WEB_SEARCH", "AUTOMATION_RELOAD", "REMEMBER",
]

# ── Schema ────────────────────────────────────────────────────────────────────

PERSONA_SCHEMA = {
    "name":            str,     # required — also the file key
    "display_name":    str,     # optional — human-readable label
    "system_prompt":   str,     # required
    "knowledge_dirs":  list,    # [] = full index; [...paths] = scoped
    "allowed_actions": list,    # ["*"] = all; list of tag names = allowlist
    "keywords":        list,    # for auto-inference matching
}

REQUIRED_KEYS = {"name", "system_prompt", "allowed_actions"}


# ── IO ────────────────────────────────────────────────────────────────────────

def personas_dir() -> str:
    os.makedirs(PERSONAS_DIR, exist_ok=True)
    return PERSONAS_DIR


def list_personas() -> list[str]:
    """Return sorted list of persona names (from filenames, without .json)."""
    d = personas_dir()
    return sorted(
        f[:-5] for f in os.listdir(d)
        if f.endswith(".json") and not f.startswith("_")
    )


def load_persona(name: str) -> dict | None:
    """Load a persona by name. Returns None if not found or malformed."""
    path = os.path.join(personas_dir(), f"{name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            p = json.load(f)
        # Back-fill optional keys
        p.setdefault("display_name",    p.get("name", name))
        p.setdefault("knowledge_dirs",  [])
        p.setdefault("keywords",        [])
        # Validate required keys
        for k in REQUIRED_KEYS:
            if k not in p:
                return None
        return p
    except (json.JSONDecodeError, ValueError):
        return None


def save_persona(persona: dict) -> None:
    """Write a persona dict to disk."""
    name = persona["name"]
    os.makedirs(personas_dir(), exist_ok=True)
    path = os.path.join(personas_dir(), f"{name}.json")
    with open(path, "w") as f:
        json.dump(persona, f, indent=2)


def delete_persona(name: str) -> bool:
    """Delete a persona file. Returns True if deleted."""
    path = os.path.join(personas_dir(), f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ── Active persona state ──────────────────────────────────────────────────────

def get_active_persona_name() -> str | None:
    """Read the currently selected persona name from disk. None = no persona."""
    if not os.path.exists(ACTIVE_FILE):
        return None
    try:
        with open(ACTIVE_FILE) as f:
            d = json.load(f)
        return d.get("active") or None
    except (json.JSONDecodeError, ValueError):
        return None


def set_active_persona(name: str | None) -> None:
    """Persist the active persona selection. Pass None to clear."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(ACTIVE_FILE, "w") as f:
        json.dump({"active": name}, f)


def get_active_persona() -> dict | None:
    """Load and return the full active persona dict, or None."""
    name = get_active_persona_name()
    if not name:
        return None
    return load_persona(name)


# ── Inference ─────────────────────────────────────────────────────────────────

def infer_persona(message: str) -> dict | None:
    """
    Try to match a persona by keywords in the user message.
    Returns the first matching persona dict, or None.
    Keywords are case-insensitive substring matches.
    Personas with no keywords are never auto-inferred.
    """
    msg_lower = message.lower()
    for name in list_personas():
        p = load_persona(name)
        if not p:
            continue
        keywords = p.get("keywords", [])
        if not keywords:
            continue
        if any(kw.lower() in msg_lower for kw in keywords):
            return p
    return None


# ── Action allowlist enforcement ──────────────────────────────────────────────

def expand_allowed_actions(allowed: list[str]) -> set[str]:
    """Expand ["*"] to the full action set; otherwise return as a set."""
    if "*" in allowed:
        return set(ALL_KRITI_ACTIONS)
    return set(allowed)


def action_permitted(action_name: str, persona: dict | None) -> tuple[bool, str]:
    """
    Check whether action_name is allowed under the given persona.

    Returns (permitted: bool, reason: str).
    If persona is None, all actions are permitted (no persona = no restrictions).
    """
    if persona is None:
        return True, ""
    allowed = expand_allowed_actions(persona.get("allowed_actions", ["*"]))
    if action_name in allowed:
        return True, ""
    pname = persona.get("display_name") or persona.get("name", "?")
    return False, (
        f"Action [{action_name}] is not in the '{pname}' persona's allowlist. "
        f"Allowed: {', '.join(sorted(allowed)) or '(none)'}."
    )


# ── System-prompt composition ─────────────────────────────────────────────────

def compose_system_prompt(base_context: str, persona: dict | None) -> str:
    """
    Merge KRITI_CONTEXT with the active persona's system_prompt.

    Strategy: persona prompt is PREPENDED as a context block, then the base
    context follows. This means base rules (action tags, whitelist, live status)
    always win at the end — the persona shapes tone/scope, not core safety rules.
    """
    if not persona:
        return base_context
    pname  = persona.get("display_name") or persona.get("name", "persona")
    pprompt = persona.get("system_prompt", "").strip()
    if not pprompt:
        return base_context
    persona_block = (
        f"[ACTIVE PERSONA: {pname}]\n"
        f"{pprompt}\n"
        f"[END PERSONA]\n\n"
    )
    return persona_block + base_context


# ── RAG scope ─────────────────────────────────────────────────────────────────

def persona_knowledge_dirs(persona: dict | None) -> list[str] | None:
    """
    Return the allowed_dirs filter to pass to rag_retrieve().

    None  → no filter (search full index)
    []    → persona has knowledge_dirs=[] → no filter (general access)
    [...]  → list of absolute paths → restrict retrieval to these dirs
    """
    if not persona:
        return None
    dirs = persona.get("knowledge_dirs", [])
    if not dirs:
        return None  # empty list = full index access
    # Expand ~ in paths
    return [os.path.expanduser(d) for d in dirs]


# ── Default persona bootstrapping ─────────────────────────────────────────────

DEFAULT_PERSONAS = [
    {
        "name":         "general",
        "display_name": "General Assistant",
        "system_prompt": (
            "You are in General Assistant mode. You have full access to all of "
            "Tanish's indexed notes and can use any action tag. Behave as normal — "
            "warm, direct, no-nonsense. This is the default mode."
        ),
        "knowledge_dirs":     [],
        "allowed_actions":    ["*"],
        "keywords":           [],
        "web_search_enabled": True,
        "web_search_domains": [],   # no restriction
    },
    {
        "name":         "deep_work",
        "display_name": "Deep Work / Coding",
        "system_prompt": (
            "You are in Deep Work mode. Tanish is in a focused coding session. "
            "Keep responses short and tactical — no life-coaching, no small talk. "
            "Answer technical questions directly. Only access project-related docs. "
            "Don't suggest breaks unless the Pomodoro timer fires. "
            "If he asks you to open something or run a script, do it immediately "
            "without preamble. Stay in engineer mode."
        ),
        "knowledge_dirs":  [],   # set to your project docs folder path
        "allowed_actions": [
            "DONE", "UNDONE", "ADD_TASK", "ADD_RECURRING",
            "ADD_QUEST", "QUEST_DONE", "START_POMODORO",
            "OPEN_APP", "RUN_SCRIPT", "SET_VOLUME", "RAG_INDEX",
            "BRIEFING", "CALENDAR_REFRESH",
        ],
        "keywords": [
            "code", "coding", "prier", "brain", "alpha", "debug",
            "commit", "deploy", "function", "bug", "kotlin", "supabase",
            "next.js", "nextjs", "worldquant", "deep work", "focus",
        ],
        "web_search_enabled": True,
        "web_search_domains": [],   # no restriction in deep work
    },
    {
        "name":         "brain_research",
        "display_name": "WorldQuant BRAIN",
        "system_prompt": (
            "You are in BRAIN Research mode — laser-focused on WorldQuant alpha research. "
            "Only answer questions about quantitative finance, alpha construction, "
            "BRAIN platform constraints, and IQC strategies. "
            "Recall these hard constraints: use min()/max() not &/|, "
            "group_mean needs 3 args, ts_rank takes 2 args. "
            "Be concise and precise. Cite sources from the indexed docs when available. "
            "Don't discuss other projects unless directly relevant to a signal idea."
        ),
        "knowledge_dirs":  [],   # set to your BRAIN notes folder path
        "allowed_actions": [
            "DONE", "UNDONE", "ADD_TASK", "ADD_QUEST", "QUEST_DONE",
            "RAG_INDEX",
        ],
        "keywords": [
            "brain", "worldquant", "alpha", "iqc", "signal", "ffo",
            "ebitda", "dcf", "volatility", "skew", "ts_rank",
            "group_mean", "quantitative", "quant",
        ],
        "web_search_enabled": True,
        "web_search_domains": [
            "worldquant.com", "arxiv.org", "ssrn.com",
            "quantopian.com", "quantlib.org",
        ],
    },
]


def bootstrap_default_personas() -> None:
    """
    Write the default persona files if missing, and forward-migrate existing
    ones to pick up any new fields added in DEFAULT_PERSONAS (non-destructive).
    """
    os.makedirs(personas_dir(), exist_ok=True)
    for p in DEFAULT_PERSONAS:
        path = os.path.join(personas_dir(), f"{p['name']}.json")
        if not os.path.exists(path):
            save_persona(p)
        else:
            # Forward-migrate: add new keys without overwriting existing values
            existing = load_persona(p["name"])
            if existing:
                changed = False
                for k, v in p.items():
                    if k not in existing:
                        existing[k] = v
                        changed = True
                if changed:
                    save_persona(existing)


# ── Persona summary (for display) ─────────────────────────────────────────────

def persona_summary(p: dict) -> str:
    """One-line summary of a persona for the settings/chat UI."""
    name    = p.get("display_name") or p.get("name", "?")
    actions = expand_allowed_actions(p.get("allowed_actions", ["*"]))
    is_all  = "*" in p.get("allowed_actions", []) or actions == set(ALL_KRITI_ACTIONS)
    act_str = "all actions" if is_all else f"{len(actions)} actions"
    dirs    = p.get("knowledge_dirs", [])
    dir_str = "full index" if not dirs else f"{len(dirs)} dir(s)"
    return f"{name}  ·  {act_str}  ·  {dir_str}"
