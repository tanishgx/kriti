"""
kriti_memory.py — long-term memory: durable facts about the user.

Chat history keeps only the last 40 messages. This keeps the things worth
remembering for weeks — preferences, deadlines, people, how projects are
going — as short facts in ~/.life_missions/memories.json, and puts them in
Kriti's context every turn.

Two ways in:
  - explicit: "remember that ..." → [[REMEMBER:fact]] (or the REMEMBER tool)
  - automatic: every few exchanges, a background pass asks the model to pull
    new durable facts out of the recent conversation (extract_facts).

The automatic pass reads only the USER's own messages — never the system
prompt, web results, or screen text — so injected external content can't
plant itself in long-term memory.

Manage from chat: /memory lists, /forget N removes one.
"""

import datetime
import json
import os
import threading

MEMORY_FILE = os.path.expanduser("~/.life_missions/memories.json")
MAX_FACTS   = 200   # oldest automatic facts are dropped past this
CONTEXT_MAX = 40    # most recent facts shown to the model each turn

_lock = threading.Lock()


def load() -> list[dict]:
    try:
        with open(MEMORY_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(facts: list[dict]):
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    tmp = MEMORY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(facts, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MEMORY_FILE)


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".")


def add(fact: str, source: str = "explicit") -> bool:
    """Store a fact. Returns False if empty or already known (case/space-insensitive)."""
    fact = " ".join(str(fact).split()).strip()
    if not fact:
        return False
    with _lock:
        facts = load()
        n = _norm(fact)
        if any(_norm(f["fact"]) == n for f in facts):
            return False
        facts.append({
            "fact": fact[:300],
            "date": datetime.date.today().isoformat(),
            "source": source,
        })
        # Over the cap: drop the oldest *automatic* fact first; explicit ones
        # were asked for and only go if nothing else is left.
        while len(facts) > MAX_FACTS:
            idx = next((i for i, f in enumerate(facts) if f.get("source") == "auto"), 0)
            facts.pop(idx)
        _save(facts)
        return True


def forget(index: int) -> str | None:
    """Remove fact #index (1-based, as shown by /memory). Returns its text."""
    with _lock:
        facts = load()
        if not 1 <= index <= len(facts):
            return None
        gone = facts.pop(index - 1)
        _save(facts)
        return gone["fact"]


def format_for_context() -> str:
    facts = load()[-CONTEXT_MAX:]
    if not facts:
        return ""
    lines = "\n".join(f"- {f['fact']} ({f['date']})" for f in facts)
    return (
        "\nLONG-TERM MEMORY (things he told you in past conversations — use them "
        "naturally, don't recite them; newer facts win over older ones):\n"
        + lines + "\n"
    )


_EXTRACT_PROMPT = """You maintain long-term memory for a personal assistant.
From the user's messages below, extract NEW durable facts worth remembering for
weeks: preferences, goals, deadlines, people, ongoing projects and their status,
habits, constraints. Skip small talk, one-off requests, and anything already in
KNOWN FACTS. Each fact: one short third-person sentence ("He prefers ...").

KNOWN FACTS:
{known}

USER MESSAGES:
{messages}

Respond with JSON only: {{"facts": ["...", "..."]}} — an empty list if nothing new."""


def extract_facts(user_messages: list[str], host: str, model: str, timeout=180) -> list[str]:
    """Ask the model for new durable facts in the user's messages; store them.
    Returns the facts that were actually added. Never raises."""
    import requests
    msgs = [m.strip() for m in user_messages if m and m.strip() and not m.startswith("/")]
    if not msgs:
        return []
    known = "\n".join(f"- {f['fact']}" for f in load()[-CONTEXT_MAX:]) or "(none)"
    prompt = _EXTRACT_PROMPT.format(known=known, messages="\n".join(f"- {m}" for m in msgs))
    try:
        r = requests.post(f"{host}/api/chat", json={
            "model": model, "stream": False, "format": "json",
            "messages": [{"role": "user", "content": prompt}],
        }, timeout=timeout)
        r.raise_for_status()
        data = json.loads(r.json().get("message", {}).get("content", "") or "{}")
        facts = data.get("facts", []) if isinstance(data, dict) else []
    except Exception:
        return []
    return [f for f in facts if isinstance(f, str) and add(f, source="auto")]


def extract_in_background(user_messages, host, model):
    threading.Thread(target=extract_facts, args=(list(user_messages), host, model),
                     daemon=True).start()
