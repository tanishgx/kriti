"""
kriti_briefing.py — Daily spoken briefing for Kriti.

Generates a Jarvis-style morning summary spoken out loud.
Called via the [[BRIEFING]] action tag dispatched by parse_kriti_actions(),
or by the APScheduler morning_briefing cron automation.

Design: all task/quest data is passed in pre-formatted (from kriti.py's
calling code) to avoid circular imports. This module only builds the
prompt and calls back through the injected call_stream_fn.
"""

import datetime
import os

SAVE_DIR = os.path.expanduser("~/.life_missions")

BRIEFING_PROMPT_TEMPLATE = """\
You are Kriti, giving Tanish his morning briefing. 100 words maximum.
No markdown, no bullet points, no headers. Natural spoken sentences only.
Cover: what matters today (tasks + quests + any calendar events), what to
prioritise first, and one motivating line at the end.
Sound like his sharp best friend who did the prep work for him — not a
corporate assistant reading a report.

Today is {date} at {time}.
Fund: ₹{fund}  |  Streak: {streak} days

Tasks today:
{task_list}

Active quests:
{quest_list}
{calendar_block}
Give the briefing now. Speak directly to him."""


def build_briefing_prompt(state, task_list_str, quest_list_str, calendar_events=None):
    """
    Build the filled briefing prompt.

    Args:
        state:          Kriti merged state dict (for fund, history).
        task_list_str:  pre-formatted task list string from kriti.py.
        quest_list_str: pre-formatted quest summary string from kriti.py.
        calendar_events: list of {"title": str, "start": str} dicts or None.

    Returns:
        str — filled prompt ready to send to Ollama.
    """
    now = datetime.datetime.now()

    # Streak (inlined to avoid circular import from kriti)
    hist = state.get("history", {})
    streak = 0
    d = datetime.date.today()
    while True:
        key = d.isoformat()
        if key in hist and hist[key].get("earned", 0) > 0:
            streak += 1
            d -= datetime.timedelta(days=1)
        else:
            break

    calendar_block = ""
    if calendar_events:
        lines = ["Calendar today:"]
        for e in sorted(calendar_events, key=lambda x: x.get("start", "")):
            lines.append(f"  - {e['start']}  {e['title']}")
        calendar_block = "\n" + "\n".join(lines) + "\n"

    return BRIEFING_PROMPT_TEMPLATE.format(
        date           = now.strftime("%A, %d %B %Y"),
        time           = now.strftime("%H:%M"),
        fund           = f"{state.get('fund', 0):,}",
        streak         = streak,
        task_list      = task_list_str,
        quest_list     = quest_list_str,
        calendar_block = calendar_block,
    )


def generate_briefing(state, host, model, call_stream_fn, task_list_str,
                      quest_list_str, calendar_events=None,
                      speak_fn=None, output_fn=print):
    """
    Generate and deliver the morning briefing.

    Args:
        state:          Kriti merged state dict.
        host:           Ollama host URL.
        model:          Ollama model name.
        call_stream_fn: kriti.call_kriti_stream (injected to avoid circular import).
        task_list_str:  pre-formatted task list.
        quest_list_str: pre-formatted quest summary.
        calendar_events: from kriti_calendar or None.
        speak_fn:       per-sentence TTS callback or None.
        output_fn:      print destination (default: built-in print).

    Returns:
        str — full briefing text.
    """
    prompt_text = build_briefing_prompt(state, task_list_str, quest_list_str, calendar_events)
    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user",   "content": "Go ahead."},
    ]

    output_fn("\n  ── Morning Briefing ─────────────────────────────────────")

    try:
        full = call_stream_fn(
            messages, host, model,
            on_sentence  = speak_fn,
            print_output = True,
        )
    except Exception as e:
        output_fn(f"  [Briefing error: {e}]")
        return ""

    output_fn("  ──────────────────────────────────────────────────────────\n")
    return full
