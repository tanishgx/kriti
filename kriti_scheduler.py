"""
kriti_scheduler.py — In-process automation scheduler for Kriti.

Automations are declared in ~/.life_missions/automations.json.
Each automation specifies:
  - id:          unique slug (e.g. "morning_brain_check")
  - enabled:     true/false
  - trigger:     {"type": "interval"|"cron"|"perception", ...}
  - persona:     name of persona to run under (controls action allowlist + RAG scope)
  - actions:     list of action-tag strings to fire, e.g. ["[[DONE:workout]]"]
  - message:     optional text Kriti speaks/prints when firing (voice/terminal nudge)
  - description: human-readable label shown in the log viewer

Trigger types:
  interval  — {"type":"interval", "minutes":N}   or "hours":N / "seconds":N
  cron      — {"type":"cron", "hour":H, "minute":M, "day_of_week":"mon-fri"}
              uses APScheduler CronTrigger; any cron field can be set
  perception — {"type":"perception", "check":"battery_below", "value":20}
              checked every N minutes (configurable) against get_system_status()
              available checks: battery_below, cpu_above, ram_above

Whitelisting / permission gate:
  Scheduled runs pass through the SAME persona gate as manual runs.
  If an automation tries a tag outside its persona's allowlist, it is blocked
  and logged — NOT silently executed.
  If the action would require a human-approval step (not currently implemented),
  it is logged-as-skipped with reason "requires_human" in the run log.

Unattended run philosophy (explicit decision, logged here):
  Actions that are "always safe" (SET_VOLUME, LOCK_SCREEN, RAG_INDEX, DONE,
  UNDONE, ADD_TASK, ADD_RECURRING, ADD_QUEST, QUEST_DONE, START_POMODORO) will
  fire unattended IF they are in the persona's allowlist.
  Actions that open apps (OPEN_APP) or run scripts (RUN_SCRIPT) are gated at the
  UNATTENDED_BLOCKED set below — they will be SKIPPED with a clear log entry
  because a human is not present to verify the target launched correctly.
  This is deliberately more conservative than manual invocation.
"""

import json
import os
import datetime
import threading
import traceback
from typing import Callable

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval    import IntervalTrigger
    from apscheduler.triggers.cron        import CronTrigger
    _APS_AVAILABLE = True
except ImportError:
    _APS_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────

SAVE_DIR          = os.path.expanduser("~/.life_missions")
AUTOMATIONS_FILE  = os.path.join(SAVE_DIR, "automations.json")
RUN_LOG_FILE      = os.path.join(SAVE_DIR, "automation_log.json")

# Actions that will NOT fire in unattended/scheduled mode (requires human present)
UNATTENDED_BLOCKED = {"OPEN_APP", "RUN_SCRIPT"}

# How often perception-based triggers are polled (seconds)
PERCEPTION_POLL_SECS = 120

# Maximum log entries kept on disk
MAX_LOG_ENTRIES = 200

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_AUTOMATIONS: list[dict] = [
    {
        "id":          "morning_deep_work_nudge",
        "enabled":     True,
        "description": "Morning deep-work check-in — reminds about focus session via terminal",
        "trigger": {
            "type":   "cron",
            "hour":   9,
            "minute": 0,
        },
        "persona":  "deep_work",
        "actions":  [],          # no action-tag side-effects — nudge only
        "message":  (
            "Good morning, Tanish. It's 9am — deep work window is open. "
            "Prier or BRAIN? Pick one and lock in for 90 minutes."
        ),
    },
]


def load_automations() -> list[dict]:
    """Load automations from disk. Creates defaults if missing."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    if os.path.exists(AUTOMATIONS_FILE):
        try:
            with open(AUTOMATIONS_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    # First run: write defaults
    save_automations(DEFAULT_AUTOMATIONS)
    return list(DEFAULT_AUTOMATIONS)


def save_automations(automations: list[dict]) -> None:
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(AUTOMATIONS_FILE, "w") as f:
        json.dump(automations, f, indent=2)


# ── Run log ───────────────────────────────────────────────────────────────────

def _load_log() -> list[dict]:
    if not os.path.exists(RUN_LOG_FILE):
        return []
    try:
        with open(RUN_LOG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def _append_log(entry: dict) -> None:
    """Append a run log entry and trim to MAX_LOG_ENTRIES."""
    log = _load_log()
    log.append(entry)
    log = log[-MAX_LOG_ENTRIES:]
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(RUN_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def log_run(
    automation_id: str,
    persona_name: str | None,
    actions_attempted: list[str],
    actions_fired: list[str],
    actions_blocked: list[str],
    message: str,
    status: str,
    error: str = "",
) -> None:
    """Write one structured entry to the automation run log."""
    entry = {
        "ts":                datetime.datetime.now().isoformat(timespec="seconds"),
        "automation_id":     automation_id,
        "persona":           persona_name,
        "message":           message,
        "actions_attempted": actions_attempted,
        "actions_fired":     actions_fired,
        "actions_blocked":   actions_blocked,
        "status":            status,   # "ok" | "blocked" | "error" | "skipped"
        "error":             error,
    }
    _append_log(entry)


def get_recent_log(n: int = 20) -> list[dict]:
    """Return the most recent n log entries (newest first)."""
    return list(reversed(_load_log()[-n:]))


# ── Execution engine ──────────────────────────────────────────────────────────

def run_automation(
    auto: dict,
    state_loader: Callable[[], dict],
    state_saver:  Callable[[dict], None],
    notify_fn:    Callable[[str, str], None],
    speak_fn:     Callable[[str], None],
    output_fn:    Callable[[str], None],
    persona_gate: Callable[[str, object], tuple[bool, str]],
    get_persona:  Callable[[str], object],
    execute_tag:  Callable[[str, str, dict, dict], str],
) -> None:
    """
    Execute one automation job. Called by APScheduler in a background thread.

    Parameters are injected by the scheduler wrapper so this function stays
    decoupled from kriti.py's globals.

    execute_tag(action, payload, state, whitelist) → result_str
    """
    auto_id     = auto.get("id", "?")
    persona_name = auto.get("persona")
    msg_text    = auto.get("message", "")
    action_tags = auto.get("actions", [])  # e.g. ["[[DONE:workout]]"]
    import re
    TAG_RE = re.compile(r'\[\[([A-Z_]+)(?::([^\]]+))?\]\]')

    attempted = []
    fired     = []
    blocked   = []
    status    = "ok"
    err_str   = ""

    try:
        state = state_loader()
        wl    = {}  # whitelist loaded inside execute_tag
        persona_obj = get_persona(persona_name) if persona_name else None

        # ── Output the nudge message ──────────────────────────────────────────
        if msg_text:
            output_fn(f"\n  ── Automation: {auto.get('description', auto_id)} ──")
            output_fn(f"  kriti › {msg_text}")
            speak_fn(msg_text)
            notify_fn("Kriti", msg_text)

        # ── Execute each action tag ───────────────────────────────────────────
        for tag_str in action_tags:
            m = TAG_RE.search(tag_str)
            if not m:
                continue
            action  = m.group(1)
            payload = m.group(2) or ""
            attempted.append(action)

            # Unattended block — conservative gate
            if action in UNATTENDED_BLOCKED:
                blocked.append(action)
                reason = f"unattended runs cannot fire [{action}] — human not present"
                output_fn(f"  ✗ [{action}] skipped: {reason}")
                log_run(auto_id, persona_name, attempted, fired, blocked,
                        msg_text, "blocked", reason)
                continue

            # Persona gate — same logic as parse_kriti_actions
            permitted, reason = persona_gate(action, persona_obj)
            if not permitted:
                blocked.append(action)
                output_fn(f"  ✗ [{action}] blocked by persona '{persona_name}': {reason}")
                continue

            # Execute
            result = execute_tag(action, payload, state, wl)
            if result:
                fired.append(action)
                output_fn(f"  ✓ [{action}] {result}")
                state_saver(state)

        if blocked and not fired:
            status = "blocked"
        elif not attempted and not msg_text:
            status = "skipped"

    except Exception as e:
        status  = "error"
        err_str = traceback.format_exc()
        output_fn(f"  ✗ Automation '{auto_id}' error: {e}")

    log_run(auto_id, persona_name, attempted, fired, blocked, msg_text, status, err_str)


# ── Perception trigger checker ────────────────────────────────────────────────

PERCEPTION_CHECKS = {
    "battery_below": lambda status, value: (
        status.get("battery_pct") is not None
        and not status.get("plugged_in")
        and status["battery_pct"] < int(value)
    ),
    "cpu_above": lambda status, value: (
        status.get("cpu_pct") is not None and status["cpu_pct"] > int(value)
    ),
    "ram_above": lambda status, value: (
        status.get("ram_pct") is not None and status["ram_pct"] > int(value)
    ),
}


def check_perception_trigger(trigger: dict, get_system_status_fn) -> bool:
    """Return True if this perception trigger's condition is currently satisfied."""
    check = trigger.get("check", "")
    value = trigger.get("value", 0)
    fn = PERCEPTION_CHECKS.get(check)
    if not fn:
        return False
    try:
        status = get_system_status_fn()
        return fn(status, value)
    except Exception:
        return False


# ── Scheduler ─────────────────────────────────────────────────────────────────

class KritiScheduler:
    """
    Thin wrapper around APScheduler's BackgroundScheduler.
    Lives for the lifetime of the Kriti process (started in main(), stopped on exit).
    """

    def __init__(self):
        self._scheduler: "BackgroundScheduler | None" = None
        self._callbacks: dict = {}   # injected by kriti.py on start
        self._perception_firing: set = set()   # IDs of perception autos that last fired

    def configure(self, **callbacks):
        """
        Inject kriti.py callbacks so the scheduler stays decoupled.
        Required keys: state_loader, state_saver, notify_fn, speak_fn,
                       output_fn, persona_gate, get_persona, execute_tag,
                       get_system_status_fn
        """
        self._callbacks = callbacks

    def start(self, automations: list[dict] | None = None) -> None:
        """Start the scheduler and register all enabled automations."""
        if not _APS_AVAILABLE:
            return
        if self._scheduler and self._scheduler.running:
            return

        self._scheduler = BackgroundScheduler(
            job_defaults={"misfire_grace_time": 60, "coalesce": True},
            timezone="UTC",
        )

        if automations is None:
            automations = load_automations()

        for auto in automations:
            if not auto.get("enabled", True):
                continue
            self._register(auto)

        # Perception poller — runs every PERCEPTION_POLL_SECS
        self._scheduler.add_job(
            self._perception_poll,
            trigger=IntervalTrigger(seconds=PERCEPTION_POLL_SECS),
            id="__perception_poller__",
            replace_existing=True,
        )

        self._scheduler.start()

    def reload(self) -> None:
        """Hot-reload automations from disk without restarting the process."""
        if not self._scheduler:
            return
        # Remove all user jobs (keep __perception_poller__)
        for job in self._scheduler.get_jobs():
            if job.id != "__perception_poller__":
                job.remove()
        for auto in load_automations():
            if auto.get("enabled", True):
                self._register(auto)

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _register(self, auto: dict) -> None:
        trigger_cfg = auto.get("trigger", {})
        ttype = trigger_cfg.get("type", "interval")
        auto_id = auto.get("id", f"auto_{id(auto)}")

        try:
            if ttype == "interval":
                kwargs = {k: v for k, v in trigger_cfg.items()
                          if k in ("weeks", "days", "hours", "minutes", "seconds")}
                kwargs.setdefault("minutes", 60)
                trigger = IntervalTrigger(**kwargs)
            elif ttype == "cron":
                kwargs = {k: v for k, v in trigger_cfg.items()
                          if k in ("year", "month", "day", "week", "day_of_week",
                                   "hour", "minute", "second")}
                trigger = CronTrigger(**kwargs)
            elif ttype == "perception":
                # Perception triggers are handled by _perception_poll, not as APScheduler jobs
                return
            else:
                return

            self._scheduler.add_job(
                self._fire_auto,
                trigger=trigger,
                id=auto_id,
                args=[auto],
                replace_existing=True,
            )
        except Exception as e:
            # Bad trigger config — log and skip
            log_run(auto_id, auto.get("persona"), [], [], [],
                    auto.get("message", ""), "error", str(e))

    def _fire_auto(self, auto: dict) -> None:
        """Called by APScheduler in a background thread."""
        cb = self._callbacks
        if not cb:
            return
        run_automation(
            auto,
            state_loader = cb["state_loader"],
            state_saver  = cb["state_saver"],
            notify_fn    = cb["notify_fn"],
            speak_fn     = cb["speak_fn"],
            output_fn    = cb["output_fn"],
            persona_gate = cb["persona_gate"],
            get_persona  = cb["get_persona"],
            execute_tag  = cb["execute_tag"],
        )

    def _perception_poll(self) -> None:
        """Poll perception triggers every PERCEPTION_POLL_SECS seconds."""
        cb = self._callbacks
        if not cb:
            return
        for auto in load_automations():
            if not auto.get("enabled", True):
                continue
            trigger = auto.get("trigger", {})
            if trigger.get("type") != "perception":
                continue
            auto_id = auto.get("id", "?")
            fires = check_perception_trigger(trigger, cb["get_system_status_fn"])
            was_firing = auto_id in self._perception_firing
            if fires and not was_firing:
                # Rising edge — fire once when condition first becomes true
                self._perception_firing.add(auto_id)
                threading.Thread(
                    target=self._fire_auto, args=[auto], daemon=True
                ).start()
            elif not fires and was_firing:
                self._perception_firing.discard(auto_id)

    def running_jobs(self) -> list[str]:
        """Return IDs of currently scheduled jobs."""
        if not self._scheduler:
            return []
        return [j.id for j in self._scheduler.get_jobs()
                if j.id != "__perception_poller__"]


# ── Module-level singleton ────────────────────────────────────────────────────

_kriti_scheduler = KritiScheduler()


def get_scheduler() -> KritiScheduler:
    return _kriti_scheduler
