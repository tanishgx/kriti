"""
kriti_system.py — Kriti's hands and eyes on the machine: read-only system
perception (battery, CPU/RAM, foreground app, idle time…), the action
whitelist, and every whitelisted action (apps, volume, lock, files, clipboard,
URLs, Spotify, scripts, screen description, ambient screen monitor).

Nothing here decides *whether* to act — persona and untrusted-content gates
live in kriti.parse_kriti_actions. This module only knows how.
"""

import json, os, sys, datetime, textwrap, requests, subprocess, shutil, threading, time, re
import platform

from kriti_ui import color
from kriti_voice import notify, sfx

try:
    import kriti_tracker
    _TRACKER_AVAILABLE = True
except ImportError:
    _TRACKER_AVAILABLE = False

_PLATFORM = platform.system()   # "Darwin" | "Windows" | "Linux"
SAVE_DIR  = os.path.expanduser("~/.life_missions")
WHITELIST_FILE = os.path.join(SAVE_DIR, "whitelist.json")

# ── System perception ─────────────────────────────────────────────────────────
# Gives Kriti read-only awareness of the machine: battery, CPU/RAM, foreground
# app, volume, network. Cross-platform where possible; macOS gets the richest
# data via osascript. Everything here is READ-ONLY — no side effects.

_pycaw_available = False
try:
    from ctypes import cast as _cast, POINTER as _POINTER
    from comtypes import CLSCTX_ALL as _CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities as _AudioUtilities, IAudioEndpointVolume as _IAudioEndpointVolume
    _pycaw_available = True
except ImportError:
    pass

_pyperclip_available = False
try:
    import pyperclip
    _pyperclip_available = True
except ImportError:
    pass

_psutil_available = False
try:
    import psutil
    _psutil_available = True
    psutil.cpu_percent(interval=None)   # prime the non-blocking CPU counter
except ImportError:
    pass

def _get_foreground_app():
    """Name of the frontmost application, or None if unavailable."""
    if _PLATFORM == "Darwin":
        try:
            script = 'tell application "System Events" to get name of first application process whose frontmost is true'
            out = subprocess.run(["osascript", "-e", script],
                                  capture_output=True, text=True, timeout=3)
            return out.stdout.strip() or None
        except Exception:
            return None
    elif _PLATFORM == "Windows":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return None
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or None
        except Exception:
            return None
    elif _PLATFORM == "Linux":
        # X11 only — best-effort, no reliable equivalent on Wayland without
        # compositor-specific protocols.
        if shutil.which("xdotool"):
            try:
                out = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=3)
                return out.stdout.strip() or None
            except Exception:
                return None
        return None
    return None

def _get_battery():
    """(percent, plugged_in) or (None, None) if unavailable."""
    if _psutil_available:
        try:
            b = psutil.sensors_battery()
            if b:
                return round(b.percent), b.power_plugged
        except Exception:
            pass
    # macOS fallback via pmset
    if _PLATFORM == "Darwin":
        try:
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3)
            m = re.search(r'(\d+)%', out.stdout)
            plugged = "AC Power" in out.stdout
            if m:
                return int(m.group(1)), plugged
        except Exception:
            pass
    return None, None

def _get_cpu_ram():
    """(cpu_percent, ram_percent) or (None, None)."""
    if _psutil_available:
        try:
            # Non-blocking: average since the previous call (primed at import).
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            return round(cpu), round(ram)
        except Exception:
            pass
    return None, None

def _get_volume():
    """System volume 0-100, or None."""
    if _PLATFORM == "Darwin":
        try:
            out = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                  capture_output=True, text=True, timeout=3)
            return int(out.stdout.strip())
        except Exception:
            return None
    elif _PLATFORM == "Windows":
        if not _pycaw_available:
            return None
        try:
            devices = _AudioUtilities.GetSpeakers()
            iface   = devices.Activate(_IAudioEndpointVolume._iid_, _CLSCTX_ALL, None)
            volume  = _cast(iface, _POINTER(_IAudioEndpointVolume))
            return round(volume.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return None
    elif _PLATFORM == "Linux":
        if shutil.which("pactl"):
            try:
                out = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                                      capture_output=True, text=True, timeout=3)
                m = re.search(r'(\d+)%', out.stdout)
                return int(m.group(1)) if m else None
            except Exception:
                return None
        return None
    return None

def _get_wifi_ssid():
    """Current WiFi network name, or None."""
    if _PLATFORM == "Darwin":
        try:
            out = subprocess.run(
                ["networksetup", "-getairportnetwork", "en0"],
                capture_output=True, text=True, timeout=3)
            if ":" in out.stdout:
                return out.stdout.split(":", 1)[1].strip()
        except Exception:
            pass
        return None
    elif _PLATFORM == "Windows":
        try:
            out = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                                  capture_output=True, text=True, timeout=5)
            m = re.search(r'^\s*SSID\s*:\s*(.+)$', out.stdout, re.MULTILINE)
            return m.group(1).strip() if m else None
        except Exception:
            return None
    elif _PLATFORM == "Linux":
        if shutil.which("nmcli"):
            try:
                out = subprocess.run(
                    ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                    capture_output=True, text=True, timeout=5)
                for line in out.stdout.splitlines():
                    if line.startswith("yes:"):
                        return line.split(":", 1)[1].strip() or None
            except Exception:
                return None
        return None
    return None

def _get_idle_seconds():
    """Seconds since last keyboard/mouse input, or None if unavailable.
    Backs the idle_above perception trigger and idle-based auto-lock."""
    if _PLATFORM == "Darwin":
        try:
            out = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=3)
            m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out.stdout)
            if m:
                return int(int(m.group(1)) / 1_000_000_000)  # nanoseconds → seconds
        except Exception:
            pass
        return None
    elif _PLATFORM == "Windows":
        try:
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis_idle = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0, millis_idle // 1000)
        except Exception:
            return None
    elif _PLATFORM == "Linux":
        # X11 only — needs the 'xprintidle' package; no universal Wayland equivalent.
        if shutil.which("xprintidle"):
            try:
                out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=3)
                return int(out.stdout.strip()) // 1000
            except Exception:
                return None
        return None
    return None

def _get_disk_free():
    """Free disk space in GB on home volume, or None."""
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return None

def get_system_status():
    """Snapshot of machine state. Returns a dict; missing fields are None.

    Probes run in parallel — several shell out (osascript, ioreg), and this is
    called on every chat turn, so serial would add ~0.3s per reply.
    """
    from concurrent.futures import ThreadPoolExecutor
    probes = {
        "battery": _get_battery, "cpu_ram": _get_cpu_ram,
        "foreground_app": _get_foreground_app, "volume": _get_volume,
        "wifi": _get_wifi_ssid, "disk_free_gb": _get_disk_free,
        "idle_secs": _get_idle_seconds,
    }
    with ThreadPoolExecutor(max_workers=len(probes)) as ex:
        futs = {k: ex.submit(fn) for k, fn in probes.items()}
        r = {k: f.result() for k, f in futs.items()}
    battery_pct, plugged = r["battery"]
    cpu, ram = r["cpu_ram"]
    return {
        "platform":       _PLATFORM,
        "foreground_app": r["foreground_app"],
        "battery_pct":    battery_pct,
        "plugged_in":     plugged,
        "cpu_pct":        cpu,
        "ram_pct":        ram,
        "volume":         r["volume"],
        "wifi":           r["wifi"],
        "disk_free_gb":   r["disk_free_gb"],
        "idle_secs":      r["idle_secs"],
    }

def format_system_status(status):
    """Human-readable one-block summary for Kriti's live context."""
    lines = []
    if status.get("foreground_app"):
        lines.append(f"- Currently in: {status['foreground_app']}")
    if status.get("battery_pct") is not None:
        plug = "charging" if status.get("plugged_in") else "on battery"
        lines.append(f"- Battery: {status['battery_pct']}% ({plug})")
    if status.get("cpu_pct") is not None:
        lines.append(f"- CPU: {status['cpu_pct']}%  ·  RAM: {status['ram_pct']}%")
    if status.get("volume") is not None:
        lines.append(f"- Volume: {status['volume']}%")
    if status.get("wifi"):
        lines.append(f"- WiFi: {status['wifi']}")
    if status.get("disk_free_gb") is not None:
        lines.append(f"- Disk free: {status['disk_free_gb']} GB")
    if status.get("idle_secs") is not None:
        lines.append(f"- Idle: {status['idle_secs']}s since last input")
    return "\n".join(lines) if lines else "- (system status unavailable on this platform)"

# ── Action whitelist ──────────────────────────────────────────────────────────
# Kriti can ONLY open, close, focus, or run apps/scripts explicitly listed
# here (same list covers all four — trusting her to open something means
# trusting her to close/focus it too). She can never invent a shell command
# or act on anything outside this file. You edit this list yourself
# (directly, or via Settings → Manage Whitelist).
#
# apps:    {"name": "Visual Studio Code"}  — must be the exact macOS app name
# scripts: {"name": "backup_prier", "path": "/Users/tanish/scripts/backup.sh"}
#          path must be an absolute path to a file that already exists.
# dirs:    ["/Users/tanish/Documents"]  — absolute directory paths.
#          FILE_SEARCH/FILE_OPEN can only ever touch files under these,
#          checked via realpath so ../ and symlink tricks can't escape them.

DEFAULT_WHITELIST = {
    "apps": [
        {"name": "Visual Studio Code"},
        {"name": "Spotify"},
        {"name": "Terminal"},
    ],
    "scripts": [],
    "dirs": []   # absolute directory paths — FILE_SEARCH/FILE_OPEN can only
                 # ever touch files under these. Empty = feature off until configured.
}

def load_whitelist():
    os.makedirs(SAVE_DIR, exist_ok=True)
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    save_whitelist(DEFAULT_WHITELIST)
    return dict(DEFAULT_WHITELIST)

def save_whitelist(wl):
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(WHITELIST_FILE, "w") as f:
        json.dump(wl, f, indent=2)

def whitelisted_app_names(wl):
    return [a["name"] for a in wl.get("apps", [])]

def whitelisted_script_names(wl):
    return [s["name"] for s in wl.get("scripts", [])]

def whitelisted_dirs(wl):
    return [d for d in wl.get("dirs", []) if os.path.isdir(d)]

def _path_in_whitelisted_dirs(path, wl):
    """True if `path` resolves to somewhere inside a whitelisted dir. Blocks
    path traversal (../, symlinks) via realpath comparison."""
    try:
        real = os.path.realpath(path)
    except Exception:
        return False
    for d in whitelisted_dirs(wl):
        droot = os.path.realpath(d)
        if real == droot or real.startswith(droot + os.sep):
            return True
    return False

def find_script(wl, name):
    for s in wl.get("scripts", []):
        if s["name"].lower() == name.lower():
            return s
    return None

# ── Whitelisted action execution ──────────────────────────────────────────────
# These are the ONLY system side-effects Kriti can trigger. Each function
# validates against the whitelist before doing anything. No raw shell strings
# from the LLM ever reach subprocess — only pre-approved names are matched.

def action_open_app(name, wl):
    """Launch a whitelisted app by exact name. Returns (ok, message)."""
    valid_names = whitelisted_app_names(wl)
    match = next((n for n in valid_names if n.lower() == name.lower()), None)
    if not match:
        return False, f"'{name}' isn't in the app whitelist. Allowed: {', '.join(valid_names) or '(none configured)'}"
    if _PLATFORM == "Darwin":
        try:
            subprocess.run(["open", "-a", match], check=True, timeout=10)
            return True, f"Opened {match}"
        except Exception as e:
            return False, f"Failed to open {match}: {e}"
    elif _PLATFORM == "Windows":
        try:
            os.startfile(match)
            return True, f"Opened {match}"
        except Exception as e:
            return False, f"Failed to open {match}: {e}"
    else:
        try:
            subprocess.Popen([match.lower()])
            return True, f"Opened {match}"
        except Exception as e:
            return False, f"Failed to open {match}: {e}"

def action_set_volume(level, wl):
    """Set system volume 0-100. Always allowed (read-safe, no whitelist needed)."""
    try:
        level = max(0, min(100, int(level)))
    except (ValueError, TypeError):
        return False, "Invalid volume level"
    if _PLATFORM == "Darwin":
        try:
            subprocess.run(["osascript", "-e", f"set volume output volume {level}"],
                           check=True, timeout=5)
            return True, f"Volume set to {level}%"
        except Exception as e:
            return False, f"Failed to set volume: {e}"
    elif _PLATFORM == "Windows":
        if not _pycaw_available:
            return False, "Volume control on Windows needs pycaw — pip install pycaw comtypes"
        try:
            devices  = _AudioUtilities.GetSpeakers()
            iface    = devices.Activate(_IAudioEndpointVolume._iid_, _CLSCTX_ALL, None)
            volume   = _cast(iface, _POINTER(_IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return True, f"Volume set to {level}%"
        except Exception as e:
            return False, f"Failed to set volume: {e}"
    elif _PLATFORM == "Linux":
        if shutil.which("pactl"):
            try:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                               check=True, timeout=5)
                return True, f"Volume set to {level}%"
            except Exception as e:
                return False, f"Failed to set volume: {e}"
        elif shutil.which("amixer"):
            try:
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{level}%"],
                               check=True, timeout=5)
                return True, f"Volume set to {level}%"
            except Exception as e:
                return False, f"Failed to set volume: {e}"
        return False, "Volume control needs 'pactl' (pipewire-pulse/pulseaudio) or 'amixer' installed"
    return False, "Volume control not supported on this platform"

def action_lock_screen(wl):
    """Lock the screen. Always allowed — it's a safety action, not a risk."""
    if _PLATFORM == "Darwin":
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "q" using {control down, command down}'],
                check=True, timeout=5)
            return True, "Screen locked"
        except Exception as e:
            return False, f"Failed to lock: {e}"
    elif _PLATFORM == "Windows":
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return True, "Screen locked"
        except Exception as e:
            return False, f"Failed to lock: {e}"
    elif _PLATFORM == "Linux":
        for cmd in (["loginctl", "lock-session"],
                    ["xdg-screensaver", "lock"],
                    ["dm-tool", "lock"]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, check=True, timeout=5)
                    return True, "Screen locked"
                except Exception:
                    continue
        return False, "No supported lock tool found (tried loginctl, xdg-screensaver, dm-tool)"
    return False, "Lock screen not supported on this platform"

# ── Process helpers (psutil-based, cross-platform) ────────────────────────────
# Backing CLOSE_APP and LIST_APPS. Listing is read-only (no whitelist needed);
# closing is a real side effect, gated by the SAME app whitelist as OPEN_APP —
# if Tanish approved opening it, closing it back is the same trust level.

_NOISE_PROC_NAMES = {
    "svchost.exe", "explorer.exe", "dwm.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "system", "registry",
    "systemd", "kthreadd", "kworker", "rcu_sched", "migration",
    "windowserver", "launchd", "kernel_task", "backgroundtaskhost.exe",
    "runtimebroker.exe", "searchindexer.exe", "searchhost.exe",
    "textinputhost.exe", "shellexperiencehost.exe", "sihost.exe",
    "ctfmon.exe", "dllhost.exe", "conhost.exe", "fontdrvhost.exe",
    "applicationframehost.exe",
}

def _running_processes():
    """Return sorted, deduped, user-facing running process names."""
    if not _psutil_available:
        return []
    names = set()
    for p in psutil.process_iter(["name"]):
        try:
            n = (p.info.get("name") or "").strip()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not n or n.lower() in _NOISE_PROC_NAMES:
            continue
        names.add(n)
    return sorted(names, key=str.lower)

def _find_process_by_name(name):
    """psutil.Process objects whose name/exe contains `name` (case-insensitive)."""
    if not _psutil_available:
        return []
    target = name.lower()
    matches = []
    for p in psutil.process_iter(["name", "exe"]):
        try:
            pname = (p.info.get("name") or "").lower()
            exe   = (p.info.get("exe") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if target in pname or target in exe:
            matches.append(p)
    return matches

def action_close_app(name, wl):
    """Close a whitelisted app by name. Graceful terminate, force-kill after 3s."""
    valid_names = whitelisted_app_names(wl)
    match = next((n for n in valid_names if n.lower() == name.lower()), None)
    if not match:
        return False, f"'{name}' isn't in the app whitelist. Allowed: {', '.join(valid_names) or '(none configured)'}"
    if not _psutil_available:
        return False, "CLOSE_APP needs psutil — pip install psutil"
    procs = _find_process_by_name(match)
    if not procs:
        return False, f"'{match}' doesn't appear to be running"
    closed = 0
    for p in procs:
        try:
            p.terminate()
            closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(procs, timeout=3)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return (True, f"Closed {match}") if closed else (False, f"Couldn't close {match} (permission denied)")

def action_list_apps(wl):
    """List currently running user-facing apps. Read-safe, no whitelist needed."""
    names = _running_processes()
    if not names:
        return False, "Couldn't read process list (psutil not available)"
    shown = names[:40]
    more = f" (+{len(names) - 40} more)" if len(names) > 40 else ""
    return True, f"Running: {', '.join(shown)}{more}"

def action_focus_window(name, wl):
    """Bring a whitelisted, already-running app's window to the front."""
    valid_names = whitelisted_app_names(wl)
    match = next((n for n in valid_names if n.lower() == name.lower()), None)
    if not match:
        return False, f"'{name}' isn't in the app whitelist. Allowed: {', '.join(valid_names) or '(none configured)'}"
    if _PLATFORM == "Darwin":
        try:
            subprocess.run(["osascript", "-e", f'tell application "{match}" to activate'],
                           check=True, timeout=5)
            return True, f"Focused {match}"
        except Exception as e:
            return False, f"Failed to focus {match}: {e}"
    elif _PLATFORM == "Windows":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            target = match.lower()
            found = {"hwnd": None}

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _enum(hwnd, lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if target in buf.value.lower():
                    found["hwnd"] = hwnd
                    return False
                return True

            user32.EnumWindows(_enum, 0)
            if not found["hwnd"]:
                return False, f"No open window found for {match}"
            user32.ShowWindow(found["hwnd"], 9)  # SW_RESTORE
            user32.SetForegroundWindow(found["hwnd"])
            return True, f"Focused {match}"
        except Exception as e:
            return False, f"Failed to focus {match}: {e}"
    elif _PLATFORM == "Linux":
        if shutil.which("wmctrl"):
            try:
                subprocess.run(["wmctrl", "-a", match], check=True, timeout=5)
                return True, f"Focused {match}"
            except Exception as e:
                return False, f"Failed to focus {match}: {e}"
        return False, "Focus needs 'wmctrl' (X11 only — not supported on Wayland yet)"
    return False, "Focus window not supported on this platform"

# ── File / clipboard / browser control ─────────────────────────────────────────
# FILE_SEARCH and FILE_OPEN are hard-scoped to whitelisted dirs (whitelist.json
# "dirs" list) — never the whole filesystem, no matter how the request is
# phrased. Clipboard and URL-open carry no destructive risk (worst case: a
# browser tab, or clipboard text overwritten) so they're always allowed,
# same trust tier as SET_VOLUME.

_FILE_SEARCH_NOISE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

def action_file_search(query, wl):
    """Search filenames (substring, case-insensitive) inside whitelisted dirs only."""
    dirs = whitelisted_dirs(wl)
    if not dirs:
        return False, "No search directories configured — add one in Settings → Whitelist"
    q = query.strip().lower()
    if not q:
        return False, "Empty search query"
    matches = []
    for root in dirs:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _FILE_SEARCH_NOISE_DIRS]
            for fn in filenames:
                if q in fn.lower():
                    matches.append(os.path.join(dirpath, fn))
                    if len(matches) >= 20:
                        break
            if len(matches) >= 20:
                break
        if len(matches) >= 20:
            break
    if not matches:
        return False, f"No files matching '{query}' found in whitelisted directories"
    shown = "\n".join(f"    {m}" for m in matches)
    return True, f"Found {len(matches)} match(es):\n{shown}"

def action_file_open(path, wl):
    """Open a file with its OS default app — only if it resolves inside a whitelisted dir."""
    try:
        real = os.path.realpath(os.path.expanduser(path.strip()))
    except Exception:
        return False, f"Invalid path: {path}"
    if not os.path.isfile(real):
        return False, f"File not found: {real}"
    if not _path_in_whitelisted_dirs(real, wl):
        return False, f"'{real}' is outside whitelisted directories — nothing opened"
    try:
        if _PLATFORM == "Darwin":
            subprocess.run(["open", real], check=True, timeout=10)
        elif _PLATFORM == "Windows":
            os.startfile(real)
        else:
            subprocess.run(["xdg-open", real], check=True, timeout=10)
        return True, f"Opened {os.path.basename(real)}"
    except Exception as e:
        return False, f"Failed to open {real}: {e}"

def action_clipboard_read(wl):
    """Read current clipboard text. Always allowed — read-safe, local only."""
    if not _pyperclip_available:
        return False, "Clipboard needs pyperclip — pip install pyperclip"
    try:
        text = pyperclip.paste()
    except Exception as e:
        return False, f"Failed to read clipboard: {e}"
    if not text:
        return True, "Clipboard is empty"
    snippet = text if len(text) <= 300 else text[:300] + "…"
    return True, f"Clipboard: {snippet}"

def action_clipboard_write(text, wl):
    """Write text to the clipboard. Always allowed — no destructive risk."""
    if not _pyperclip_available:
        return False, "Clipboard needs pyperclip — pip install pyperclip"
    try:
        pyperclip.copy(text)
        return True, "Copied to clipboard"
    except Exception as e:
        return False, f"Failed to write clipboard: {e}"


# ── Screen/visual awareness (local Ollama vision model) ────────────────────────
# DESCRIBE_SCREEN captures a screenshot and describes it via a small Ollama
# vision model (moondream, llava, etc — configured separately from the main
# text model in Settings, so you don't have to run a heavy vision model for
# ordinary chat). Runs on CPU like the rest of Ollama here — slower without
# a GPU, but real: nothing leaves this machine. Always allowed, no whitelist
# needed — it observes, it doesn't act, same trust tier as LIST_APPS.

_PIL_AVAILABLE = False
try:
    from PIL import ImageGrab
    _PIL_AVAILABLE = True
except ImportError:
    pass

def _capture_screenshot_b64():
    """Screenshot the primary display, return base64-encoded PNG, or None."""
    import io, base64
    img = None
    if _PIL_AVAILABLE:
        try:
            img = ImageGrab.grab()
        except Exception:
            img = None
    if img is not None:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # Linux fallback — PIL's ImageGrab support there is inconsistent, so try
    # common screenshot tools directly. First one found wins.
    if _PLATFORM == "Linux":
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        try:
            for cmd in (["grim", tmp.name],                        # Wayland
                        ["gnome-screenshot", "-f", tmp.name],       # GNOME
                        ["scrot", tmp.name],                        # X11
                        ["import", "-window", "root", tmp.name]):   # ImageMagick/X11
                if shutil.which(cmd[0]):
                    try:
                        subprocess.run(cmd, check=True, timeout=10,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        with open(tmp.name, "rb") as f:
                            data = f.read()
                        if data:
                            return base64.b64encode(data).decode()
                    except Exception:
                        continue
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    return None

def action_describe_screen(question, state):
    """Screenshot the display and describe it via a local Ollama vision model.

    NOTE: unlike the wl-gated action_* functions above, this takes `state`
    (not `wl`) — it needs to stash the description on state for injection
    into the NEXT turn, same delayed-context pattern WEB_SEARCH uses (the
    tag fires after the current reply already streamed, so Kriti can't
    reference the description until asked again).
    """
    b64 = _capture_screenshot_b64()
    if not b64:
        if _PLATFORM == "Linux":
            return False, "Screenshot failed — install grim (Wayland) or scrot (X11)"
        return False, "Screenshot failed — install Pillow: pip install Pillow"

    host  = state.get("ollama_host", "http://localhost:11434")
    model = state.get("vision_model", "moondream")
    prompt_text = question.strip() if question.strip() else "Describe what's on this screen, concisely."

    try:
        resp = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": prompt_text, "images": [b64], "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        desc = resp.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return False, f"Couldn't reach Ollama at {host}"
    except Exception as e:
        return False, f"Vision model error ({model}): {e} — is it pulled? Try: ollama pull {model}"

    if not desc:
        return False, "Vision model returned an empty description"
    state["_screen_desc"] = desc
    return True, desc[:200] + ("…" if len(desc) > 200 else "")

# ── Ambient screen monitor ─────────────────────────────────────────────────────
# Background thread: every N seconds, silently screencap → vision model →
# stores description in state["_ambient_screen"] for injection into the
# next Kriti turn. Off by default (Settings [1]). No whitelist needed —
# observation only, same trust tier as DESCRIBE_SCREEN.

class AmbientMonitor:
    """Periodically captures a screenshot and describes it via the vision model.

    Result stored in the shared state dict as:
        state["_ambient_screen"] = {"desc": str, "ts": float}

    build_live_context() reads this and injects it into LIVE STATUS.
    """

    def __init__(self, state_ref: dict, interval_secs: int = 300):
        self._state    = state_ref
        self._interval = interval_secs
        self._thread   = None
        self._stop     = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="KritiAmbientMonitor")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        """Poll loop — waits self._interval between captures."""
        while not self._stop.wait(self._interval):
            self._capture_once()

    def _capture_once(self):
        b64 = _capture_screenshot_b64()
        if not b64:
            return
        host  = self._state.get("ollama_host",  "http://localhost:11434")
        model = self._state.get("vision_model", "moondream")
        try:
            resp = requests.post(
                f"{host}/api/generate",
                json={
                    "model":  model,
                    "prompt": ("In one sentence: what app or task is the user "
                               "focused on right now? Be specific."),
                    "images": [b64],
                    "stream": False,
                },
                timeout=60,
            )
            resp.raise_for_status()
            desc = resp.json().get("response", "").strip()
            if desc:
                self._state["_ambient_screen"] = {
                    "desc": desc,
                    "ts":   time.time(),
                }
                if _TRACKER_AVAILABLE:
                    try:
                        kriti_tracker.log_event("ambient_context", desc)
                    except Exception:
                        pass
        except Exception:
            pass


# Module-level singleton — created in main(), started if ambient mode is enabled


def action_open_url(url, wl):
    """Open a URL in the default browser. Always allowed — worst case is a browser tab."""
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    try:
        import webbrowser
        webbrowser.open(url)
        return True, f"Opened {url}"
    except Exception as e:
        return False, f"Failed to open URL: {e}"

# ── Spotify control (macOS AppleScript, desktop app only) ─────────────────────

_SPOTIFY_SCRIPTS = {
    "play":   'tell application "Spotify" to play',
    "pause":  'tell application "Spotify" to pause',
    "next":   'tell application "Spotify" to next track',
    "prev":   'tell application "Spotify" to previous track',
    "status": ('tell application "Spotify" to '
               'get (name of current track) & " \u2014 " & (artist of current track)'),
}

def action_spotify(command: str, wl):
    """Control Spotify via AppleScript (macOS only, requires desktop app).

    command: 'play' | 'pause' | 'next' | 'prev' | 'status'
             'volume:N' (0-100)
             'search:query'
    """
    if _PLATFORM != "Darwin":
        return False, "Spotify AppleScript control is macOS-only"
    if not shutil.which("osascript"):
        return False, "osascript not found"
    if "Spotify" not in whitelisted_app_names(wl):
        return False, "Spotify isn't in your app whitelist — add it in Settings → Whitelist"

    cmd = command.strip().lower()

    if cmd.startswith("volume:"):
        try:
            level = max(0, min(100, int(cmd.split(":", 1)[1].strip())))
        except ValueError:
            return False, "Invalid volume level — use [[SPOTIFY:volume:50]]"
        script = f'tell application "Spotify" to set sound volume to {level}'
    elif cmd.startswith("search:"):
        query  = cmd.split(":", 1)[1].strip()
        # Spotify AppleScript search: open search view with query
        escaped = query.replace('"', '\\"')
        script  = (
            f'tell application "Spotify" to activate\n'
            f'tell application "System Events" to tell process "Spotify" to '
            f'keystroke "l" using {{command down}}\n'
            f'delay 0.4\n'
            f'tell application "System Events" to keystroke "{escaped}"\n'
            f'tell application "System Events" to key code 36'  # Return
        )
    else:
        script = _SPOTIFY_SCRIPTS.get(cmd)
        if script is None:
            return False, (f"Unknown Spotify command '{cmd}'. "
                           "Use: play / pause / next / prev / status / volume:N / search:query")

    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        result = out.stdout.strip()
        if out.returncode != 0 and not result:
            err = out.stderr.strip()[:100]
            return False, f"Spotify error: {err or 'unknown error'}"
        return True, result or f"Spotify: {cmd}"
    except Exception as e:
        return False, f"Spotify error: {e}"


def action_run_script(name, wl):
    """Run a whitelisted script by name. Path must exist and be in whitelist."""
    script = find_script(wl, name)
    if not script:
        valid = whitelisted_script_names(wl)
        return False, f"'{name}' isn't in the script whitelist. Allowed: {', '.join(valid) or '(none configured)'}"
    path = script["path"]
    if not os.path.isfile(path):
        return False, f"Script path no longer exists: {path}"
    try:
        result = subprocess.run(
            [path], capture_output=True, text=True, timeout=60, shell=False)
        out = (result.stdout or "").strip()[-300:]  # cap output shown
        if result.returncode == 0:
            return True, f"Ran '{name}'" + (f" — {out}" if out else "")
        else:
            return False, f"'{name}' exited with code {result.returncode}" + (f": {out}" if out else "")
    except subprocess.TimeoutExpired:
        return False, f"'{name}' timed out after 60s"
    except Exception as e:
        return False, f"Failed to run '{name}': {e}"

