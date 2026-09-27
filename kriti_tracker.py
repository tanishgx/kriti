"""
kriti_tracker.py — Daily activity logger for Kriti.

Appends structured events to the current day's JSON file throughout
the day. On day lock, an LLM-generated narrative summary is written.

Event types:
  voice_query    — user spoke/typed to Kriti
  action_fired   — [[ACTION]] tag executed
  app_focus      — foreground app changed (ambient monitor)
  ambient_context — ambient screen description captured
  briefing       — morning briefing delivered
  automation     — scheduled automation fired

This data is used by:
  build_live_context()  — inject TODAY'S ACTIVITY block
  screen_history()      — richer per-day view with narrative summary
  _show_analytics()     — productivity pattern analysis
"""

import datetime
import json
import os
import threading

SAVE_DIR = os.path.expanduser("~/.life_missions")

_log_lock = threading.Lock()

SUMMARY_PROMPT_TEMPLATE = """\
You are Kriti. Write a 100-word narrative summary of Tanish's day — in past
tense, spoken like a caring friend recapping what happened. No bullet points.
Just flowing sentences. Cover: what he worked on, tasks completed, any
notable patterns or wins you can infer.

Date: {date}
Tasks completed: {tasks_done}
Total earned: ₹{earned}
Activity log:
{log_entries}

Write the summary now."""


def log_event(event_type: str, value: str, date_str: str = None) -> None:
    """
    Append one event to the day's activity log.

    Thread-safe. Silently swallows all errors so it never blocks the main flow.

    Args:
        event_type: one of voice_query, action_fired, app_focus,
                    ambient_context, briefing, automation.
        value:      human-readable description, capped at 500 chars.
        date_str:   ISO date string (default: today).
    """
    try:
        date_str = date_str or datetime.date.today().isoformat()
        path = os.path.join(SAVE_DIR, f"{date_str}.json")
        os.makedirs(SAVE_DIR, exist_ok=True)

        entry = {
            "ts":    datetime.datetime.now().isoformat(timespec="seconds"),
            "type":  event_type,
            "value": str(value)[:500],
        }

        with _log_lock:
            data = {}
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        data = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    data = {}

            data.setdefault("activity_log", []).append(entry)

            with open(path, "w") as f:
                json.dump(data, f, indent=2)
    except Exception:
        pass  # never block caller


def get_today_log(date_str: str = None) -> list:
    """
    Return the activity log for a given day.

    Returns [] on any error or missing file.
    """
    date_str = date_str or datetime.date.today().isoformat()
    path = os.path.join(SAVE_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f).get("activity_log", [])
    except Exception:
        return []


def format_log_for_context(log: list, max_entries: int = 10) -> str:
    """
    Compact log for injection into LIVE STATUS (last max_entries events).

    Returns empty string if log is empty.
    """
    if not log:
        return ""
    recent = log[-max_entries:]
    lines = ["TODAY'S ACTIVITY (recent events):"]
    for e in recent:
        ts   = e.get("ts", "")[11:16]  # HH:MM
        kind = e.get("type", "").replace("_", " ")
        val  = e.get("value", "")[:80]
        lines.append(f"  {ts}  [{kind}]  {val}")
    return "\n".join(lines)


def format_timeline(log: list) -> str:
    """
    Full timeline string for the activity timeline subscreen.
    """
    if not log:
        return "  (no activity recorded)"
    lines = []
    for e in log:
        ts   = e.get("ts", "")[11:16]
        kind = e.get("type", "").replace("_", " ")
        val  = e.get("value", "")
        lines.append(f"  {ts}  [{kind:<16}]  {val}")
    return "\n".join(lines)


def get_productivity_patterns(log: list) -> dict:
    """
    Derive simple patterns from the day's activity log.

    Returns:
        {
          "most_active_hour": int | None,
          "action_count": int,
          "query_count": int,
          "top_apps": list[str],
        }
    """
    hour_counts = {}
    action_count = 0
    query_count  = 0
    app_counts   = {}

    for e in log:
        ts = e.get("ts", "")
        try:
            hour = int(ts[11:13])
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        except (ValueError, IndexError):
            pass

        etype = e.get("type", "")
        if etype == "action_fired":
            action_count += 1
        elif etype == "voice_query":
            query_count += 1
        elif etype in ("app_focus", "ambient_context"):
            app = e.get("value", "")[:40]
            app_counts[app] = app_counts.get(app, 0) + 1

    most_active = max(hour_counts, key=hour_counts.get) if hour_counts else None
    top_apps = sorted(app_counts, key=app_counts.get, reverse=True)[:3]

    return {
        "most_active_hour": most_active,
        "action_count":     action_count,
        "query_count":      query_count,
        "top_apps":         top_apps,
    }


def generate_daily_summary(date_str, state, host, model, call_stream_fn) -> str:
    """
    Generate a 100-word narrative daily summary via Ollama.
    Called when the day is locked. Returns the summary string.
    """
    log = get_today_log(date_str)
    tk  = date_str

    hist = state.get("history", {}).get(tk, {})
    earned    = hist.get("earned", 0) if hist else 0
    tasks_raw = hist.get("tasks", []) if hist else []
    tasks_done = [t["label"] for t in tasks_raw if t.get("done")]
    tasks_done_str = ", ".join(tasks_done) if tasks_done else "none"

    log_lines = []
    for e in log[-20:]:  # last 20 events
        ts   = e.get("ts", "")[11:16]
        kind = e.get("type", "").replace("_", " ")
        val  = e.get("value", "")[:80]
        log_lines.append(f"  {ts} [{kind}] {val}")
    log_str = "\n".join(log_lines) if log_lines else "  (no activity logged)"

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        date       = date_str,
        tasks_done = tasks_done_str,
        earned     = earned,
        log_entries = log_str,
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user",   "content": "Write the summary."},
    ]

    try:
        full = call_stream_fn(messages, host, model,
                              on_sentence=None, print_output=False)
        return full.strip()
    except Exception:
        return ""


def save_daily_summary(date_str: str, summary: str) -> None:
    """Persist the daily summary into the day's JSON file."""
    if not summary:
        return
    path = os.path.join(SAVE_DIR, f"{date_str}.json")
    with _log_lock:
        data = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["daily_summary"] = summary
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def get_daily_summary(date_str: str) -> str:
    """Load the saved daily summary for a given date."""
    path = os.path.join(SAVE_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return ""
    try:
        with open(path) as f:
            return json.load(f).get("daily_summary", "")
    except Exception:
        return ""
