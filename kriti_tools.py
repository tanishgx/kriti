"""
kriti_tools.py — Kriti's actions as native Ollama tools.

Models with tool support get these structured function definitions instead of
having to hand-write `[[TAG:payload]]` lines, which small models often get
subtly wrong (inline tags, wrong separators, missing fields).

Every tool call is converted back into the exact `[[TAG:payload]]` line the
parser already understands (`tool_call_to_tag`). That keeps a single execution
path: persona gates, the whitelist, and the untrusted-content confirmation in
parse_kriti_actions apply to tool calls exactly as they do to typed tags.

Models without tool support keep working in tag mode — kriti.py falls back
automatically when Ollama says the model doesn't support tools.
"""

# name -> (description, [(arg, json_type, description, required)], to_payload)
# to_payload(args) -> payload string ("" for bare tags like [[LOCK_SCREEN]])
_SPECS = {
    "DONE": ("Mark one of today's tasks done.",
             [("task_id", "string", "Task id from LIVE STATUS, e.g. 'workout'", True)],
             lambda a: a["task_id"]),
    "UNDONE": ("Unmark a task that was marked done.",
               [("task_id", "string", "Task id from LIVE STATUS", True)],
               lambda a: a["task_id"]),
    "ADD_TASK": ("Add a one-time task for today.",
                 [("label", "string", "What to do", True),
                  ("area", "string", "Area, e.g. Fitness, Academics, Prier", True),
                  ("value", "integer", "Reward in rupees", True)],
                 lambda a: f"{a['label']}|{a['area']}|{a['value']}"),
    "ADD_RECURRING": ("Add a recurring habit/task.",
                      [("label", "string", "What to do", True),
                       ("area", "string", "Area", True),
                       ("value", "integer", "Reward in rupees", True),
                       ("days", "string", "'daily', 'weekdays', or e.g. 'mon,wed,fri'", True)],
                      lambda a: f"{a['label']}|{a['area']}|{a['value']}|{a['days']}"),
    "ADD_QUEST": ("Create a multi-day quest with milestones.",
                  [("title", "string", "Quest title", True),
                   ("milestones", "array", "Milestone labels, in order", True),
                   ("bonus", "integer", "Bonus reward in rupees on completion", True),
                   ("deadline", "string", "YYYY-MM-DD", True)],
                  lambda a: f"{a['title']}|{';'.join(a['milestones'])}|{a['bonus']}|{a['deadline']}"),
    "QUEST_DONE": ("Mark a quest milestone complete.",
                   [("quest_id", "string", "Quest id from LIVE STATUS", True),
                    ("milestone_index", "integer", "0-based milestone index", True)],
                   lambda a: f"{a['quest_id']}:{a['milestone_index']}"),
    "START_POMODORO": ("Start a focus timer.",
                       [("minutes", "integer", "Length in minutes (default 25)", True)],
                       lambda a: str(a["minutes"])),
    "OPEN_APP": ("Open a whitelisted app.",
                 [("name", "string", "Exact app name from the WHITELIST", True)],
                 lambda a: a["name"]),
    "CLOSE_APP": ("Close a whitelisted running app.",
                  [("name", "string", "Exact app name from the WHITELIST", True)],
                  lambda a: a["name"]),
    "FOCUS_WINDOW": ("Bring an already-open whitelisted app to the front.",
                     [("name", "string", "Exact app name from the WHITELIST", True)],
                     lambda a: a["name"]),
    "RUN_SCRIPT": ("Run a whitelisted script.",
                   [("name", "string", "Exact script name from the WHITELIST", True)],
                   lambda a: a["name"]),
    "SET_VOLUME": ("Set system volume.",
                   [("level", "integer", "0-100", True)],
                   lambda a: str(a["level"])),
    "LOCK_SCREEN": ("Lock the screen.", [], lambda a: ""),
    "LIST_APPS": ("List currently running apps.", [], lambda a: ""),
    "FILE_SEARCH": ("Search whitelisted directories by filename.",
                    [("query", "string", "Filename or part of it", True)],
                    lambda a: a["query"]),
    "FILE_OPEN": ("Open a file inside a whitelisted directory.",
                  [("path", "string", "Absolute path", True)],
                  lambda a: a["path"]),
    "CLIPBOARD_READ": ("Read the clipboard.", [], lambda a: ""),
    "CLIPBOARD_WRITE": ("Copy text to the clipboard.",
                        [("text", "string", "Text to copy", True)],
                        lambda a: a["text"]),
    "OPEN_URL": ("Open a URL in the default browser.",
                 [("url", "string", "Full http(s) URL", True)],
                 lambda a: a["url"]),
    "DESCRIBE_SCREEN": ("Screenshot the screen and describe it (result arrives next turn).",
                        [("question", "string", "Optional specific question about the screen", False)],
                        lambda a: a.get("question", "")),
    "RAG_INDEX": ("Re-index the user's notes.", [], lambda a: ""),
    "SET_PERSONA": ("Switch persona, or 'clear' to reset.",
                    [("name", "string", "Persona name or 'clear'", True)],
                    lambda a: a["name"]),
    "AUTOMATION_RELOAD": ("Reload automations.json.", [], lambda a: ""),
    "WEB_SEARCH": ("Search the web (results arrive next turn).",
                   [("query", "string", "Search query", True)],
                   lambda a: a["query"]),
    "SPOTIFY": ("Control Spotify: play, pause, next, previous, volume:N, search:QUERY.",
                [("command", "string", "e.g. 'pause', 'volume:30', 'search:lo-fi chill'", True)],
                lambda a: a["command"]),
    "BRIEFING": ("Give the morning briefing.", [], lambda a: ""),
    "CALENDAR_REFRESH": ("Refresh calendar events.", [], lambda a: ""),
    "REMEMBER": ("Store a durable fact about him in long-term memory.",
                 [("fact", "string", "One short third-person sentence", True)],
                 lambda a: a["fact"]),
}


def _schema(name, desc, params):
    props, required = {}, []
    for arg, typ, adesc, req in params:
        props[arg] = {"type": typ, "description": adesc}
        if typ == "array":
            props[arg]["items"] = {"type": "string"}
        if req:
            required.append(arg)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


TOOLS = [_schema(n, d, p) for n, (d, p, _) in _SPECS.items()]

TOOLS_NOTE = (
    "\nTOOLS: native tools are available for every action above. Call the tool "
    "instead of writing a [[TAG]] line — never both for the same action. "
    "Still reply to the user in plain text alongside any tool call.\n"
)

_TOOL_MODE_ACTIONS = """ACTIONS:
You act by CALLING THE PROVIDED TOOLS (native function calls). Do not write [[TAG]]
lines in your text. Reply to him in plain text AND call the tool(s) in the same turn.
- Task area must be one of: Prier, BRAIN, Fitness, Academics, Habits, Wear OS
- Task value must be 5, 10, 15, 20, or 25
- Results of WEB_SEARCH and DESCRIBE_SCREEN arrive on the NEXT turn.
In the rules below, "emit the tag" means "call the tool".
"""


def to_tool_mode(system_prompt: str) -> str:
    """Swap the long [[TAG]] tutorial in Kriti's prompt for a short tool-mode
    section. Models follow whichever format the prompt drills hardest, so with
    the tutorial left in they keep writing tags and ignore the tools."""
    start = system_prompt.find("ACTIONS:\n")
    end = system_prompt.find("\nRules:\n", start)
    if start == -1 or end == -1:
        return system_prompt + TOOLS_NOTE
    return system_prompt[:start] + _TOOL_MODE_ACTIONS + system_prompt[end:]


def _clean(v) -> str:
    # Payloads live inside [[...]] on one line: no brackets (so an argument
    # can't open or close a tag of its own) and no newlines.
    return str(v).replace("[", "(").replace("]", ")").replace("\n", " ").strip()


def tool_call_to_tag(name, args):
    """Convert one Ollama tool call to a `[[TAG:payload]]` line, or None if unknown/malformed."""
    spec = _SPECS.get(name)
    if spec is None or not isinstance(args, dict):
        return None
    try:
        payload = spec[2]({k: (v if isinstance(v, list) else _clean(v)) for k, v in args.items()})
    except (KeyError, TypeError):
        return None
    payload = _clean(payload)
    return f"[[{name}:{payload}]]" if payload else f"[[{name}]]"
