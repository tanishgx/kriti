"""
kriti_calendar.py — Read macOS Calendar.app events via AppleScript.

No OAuth, no API key, no Python dependencies beyond stdlib.
Reads local / iCloud / Exchange calendars that Calendar.app already sees.

First run: macOS shows a one-time permission dialog:
  "Terminal wants to access Calendar"
Click Allow. Required once per Terminal/Python binary.

Gracefully returns [] on: non-macOS, permission denied, parse failure,
or Calendar.app not installed.
"""

import os
import re
import shutil
import subprocess
import platform

_PLATFORM = platform.system()

# AppleScript: outputs one pipe-delimited line per event:
#   CalendarName|EventTitle|StartDateString
# Using a simple string output avoids parsing AppleScript record syntax.
_CALENDAR_SCRIPT = '''
tell application "Calendar"
    set todayDate to current date
    set time of todayDate to 0
    set todayEnd to todayDate + 86399
    set outputLines to ""
    repeat with cal in calendars
        try
            set calEvents to (every event of cal whose start date >= todayDate and start date <= todayEnd)
            repeat with evt in calEvents
                set evtTitle to summary of evt
                set evtStart to start date of evt
                set startHour to hours of evtStart
                set startMin to minutes of evtStart
                set hourStr to startHour as string
                set minStr to startMin as string
                if (count of hourStr) = 1 then set hourStr to "0" & hourStr
                if (count of minStr) = 1 then set minStr to "0" & minStr
                set timeStr to hourStr & ":" & minStr
                set outputLines to outputLines & (name of cal) & "|" & evtTitle & "|" & timeStr & "\n"
            end repeat
        end try
    end repeat
    return outputLines
end tell
'''


def get_todays_events() -> list:
    """
    Return today's calendar events.

    Returns:
        list of {"title": str, "start": str (HH:MM), "calendar": str}
        Empty list on any failure.
    """
    if _PLATFORM != "Darwin":
        return []
    if not shutil.which("osascript"):
        return []

    try:
        result = subprocess.run(
            ["osascript", "-e", _CALENDAR_SCRIPT],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        return _parse_output(result.stdout)
    except Exception:
        return []


def _parse_output(raw: str) -> list:
    """Parse pipe-delimited output lines into event dicts."""
    events = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        cal_name, title, start_time = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not title:
            continue
        events.append({
            "calendar": cal_name,
            "title":    title,
            "start":    start_time,
        })
    # Sort by start time
    events.sort(key=lambda e: e.get("start", "99:99"))
    return events


def format_for_context(events: list) -> str:
    """
    Format events as a compact block for injection into LIVE STATUS.

    Returns empty string if no events.
    """
    if not events:
        return ""
    lines = ["CALENDAR (today):"]
    for e in events:
        lines.append(f"  - {e['start']}  {e['title']}  ({e['calendar']})")
    return "\n".join(lines)
