#!/usr/bin/env python3
"""
life_missions.py — Tanish's terminal life OS
Run: python3 life_missions.py
Ollama: OLLAMA_ORIGINS=* ollama serve (in a separate terminal)
"""

import json, os, sys, datetime, textwrap, requests, subprocess, shutil, threading, time, re
from blessed import Terminal

# ── RAG layer (optional — graceful degradation if kriti_rag.py missing) ───────
try:
    import kriti_rag
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

# ── Personas layer (optional — graceful degradation) ──────────────────────────
try:
    import kriti_personas
    _PERSONAS_AVAILABLE = True
except ImportError:
    _PERSONAS_AVAILABLE = False

# ── Scheduler layer (optional — graceful degradation) ──────────────────────
try:
    import kriti_scheduler
    _SCHEDULER_AVAILABLE = True
except ImportError:
    _SCHEDULER_AVAILABLE = False

# ── Web search layer (optional — graceful degradation) ────────────────────────
try:
    import kriti_websearch
    _WEBSEARCH_AVAILABLE = True
except ImportError:
    _WEBSEARCH_AVAILABLE = False

# ── Voice layer ───────────────────────────────────────────────────────────────
# TTS:  pyttsx3 (cross-platform). pip install pyttsx3
#       macOS also tries `say -v Tara` first (zero deps, better quality).
# STT:  pyaudio + SpeechRecognition.
#         macOS:   pip install pyaudio SpeechRecognition  (macOS: brew install portaudio first)
#         Windows: pip install pyaudio SpeechRecognition  (no brew needed)
#         Linux:   sudo apt install portaudio19-dev && pip install pyaudio SpeechRecognition
# Toggle voice on/off with [v] inside Kriti chat.

import platform
_PLATFORM = platform.system()   # "Darwin" | "Windows" | "Linux"

VOICE_ENABLED = False   # toggled at runtime
_whisper_model = None    # cached WhisperModel instance

def _tts_say(text):
    """Speak text. Strips ANSI, blocks until speech finishes.
    Priority: macOS `say` (best quality on Mac) → pyttsx3 (cross-platform) → silent.
    On Windows, pyttsx3 uses SAPI5 voices built into the OS — no extra install.
    """
    import re
    clean = re.sub(r'\x1b\[[0-9;]*m', '', text).strip()
    if not clean:
        return
    # macOS: `say` with Indian English voice (built-in, zero deps)
    if _PLATFORM == "Darwin" and shutil.which("say"):
        subprocess.run(["say", "-v", "Tara", "-r", "200", clean],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    # Windows / Linux / macOS fallback: pyttsx3
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 185)
        # On Windows, pick a female SAPI5 voice if one is available
        if _PLATFORM == "Windows":
            voices = engine.getProperty("voices")
            female = next((v for v in voices if "zira" in v.name.lower()
                           or "female" in (v.gender or "").lower()), None)
            if female:
                engine.setProperty("voice", female.id)
        engine.say(clean)
        engine.runAndWait()
    except Exception:
        pass  # silent fallback

def speak(text):
    """Speak text in a background thread. Returns the thread (or None)."""
    if VOICE_ENABLED:
        t = threading.Thread(target=_tts_say, args=(text,), daemon=True)
        t.start()
        return t
    return None

# ── System perception ─────────────────────────────────────────────────────────
# Gives Kriti read-only awareness of the machine: battery, CPU/RAM, foreground
# app, volume, network. Cross-platform where possible; macOS gets the richest
# data via osascript. Everything here is READ-ONLY — no side effects.

_psutil_available = False
try:
    import psutil
    _psutil_available = True
except ImportError:
    pass

def _get_foreground_app():
    """Name of the frontmost application. macOS only (osascript); else None."""
    if _PLATFORM != "Darwin":
        return None
    try:
        script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        out = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=3)
        name = out.stdout.strip()
        return name or None
    except Exception:
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
            cpu = psutil.cpu_percent(interval=0.3)
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

def _get_disk_free():
    """Free disk space in GB on home volume, or None."""
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return None

def get_system_status():
    """Snapshot of machine state. Returns a dict; missing fields are None."""
    battery_pct, plugged = _get_battery()
    cpu, ram = _get_cpu_ram()
    return {
        "platform":       _PLATFORM,
        "foreground_app": _get_foreground_app(),
        "battery_pct":    battery_pct,
        "plugged_in":     plugged,
        "cpu_pct":        cpu,
        "ram_pct":        ram,
        "volume":         _get_volume(),
        "wifi":           _get_wifi_ssid(),
        "disk_free_gb":   _get_disk_free(),
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
    return "\n".join(lines) if lines else "- (system status unavailable on this platform)"

# ── Sound effects & notifications ─────────────────────────────────────────────

# macOS system sound paths
_SFX_MAC = {
    "done":     "/System/Library/Sounds/Glass.aiff",
    "lock":     "/System/Library/Sounds/Hero.aiff",
    "quest":    "/System/Library/Sounds/Purr.aiff",
    "pomodoro": "/System/Library/Sounds/Submarine.aiff",
    "error":    "/System/Library/Sounds/Basso.aiff",
}

# Windows MessageBeep constants (from winsound)
# MB_OK=0, MB_ICONHAND=16, MB_ICONQUESTION=32, MB_ICONEXCLAMATION=48, MB_ICONASTERISK=64
_SFX_WIN = {
    "done":     64,   # asterisk / info
    "lock":     48,   # exclamation
    "quest":    32,   # question
    "pomodoro": 64,
    "error":    16,   # hand / error
}

def sfx(event):
    """Play a short system sound (async, fire-and-forget). Cross-platform."""
    if _PLATFORM == "Darwin":
        path = _SFX_MAC.get(event)
        if path and os.path.exists(path) and shutil.which("afplay"):
            subprocess.Popen(["afplay", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif _PLATFORM == "Windows":
        beep_type = _SFX_WIN.get(event, 64)
        def _beep():
            try:
                import winsound
                winsound.MessageBeep(beep_type)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()
    else:
        # Linux: try paplay/aplay with a system sound, else silent
        candidates = [
            "/usr/share/sounds/freedesktop/stereo/complete.oga",
            "/usr/share/sounds/ubuntu/stereo/bell.ogg",
        ]
        player = shutil.which("paplay") or shutil.which("aplay")
        if player:
            for c in candidates:
                if os.path.exists(c):
                    subprocess.Popen([player, c],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break

def notify(title, message):
    """Send a desktop notification. Cross-platform: macOS / Windows / Linux."""
    if _PLATFORM == "Darwin" and shutil.which("osascript"):
        script = f'display notification "{message}" with title "{title}" sound name "default"'
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif _PLATFORM == "Windows":
        def _notify_win():
            try:
                # win10toast: pip install win10toast
                from win10toast import ToastNotifier
                ToastNotifier().show_toast(title, message, duration=5, threaded=True)
            except ImportError:
                try:
                    # plyer fallback: pip install plyer
                    from plyer import notification
                    notification.notify(title=title, message=message, timeout=5)
                except ImportError:
                    pass  # no notifier installed — silent
        threading.Thread(target=_notify_win, daemon=True).start()
    else:
        # Linux: notify-send (usually pre-installed)
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def listen_mic(timeout=12, phrase_limit=45):
    """Record from mic → transcribed text, '' on timeout, None on failure.

    Strategy: stream raw audio in chunks, track RMS energy to detect speech vs
    silence. Stop only after SILENCE_STOP seconds of consecutive quiet AFTER
    speech has begun. This means mid-sentence pauses never cut the recording —
    only a deliberate long pause at the end does.
    Falls back to SpeechRecognition+Google if faster-whisper isn't installed.
    """
    CHUNK          = 1024          # frames per read
    RATE           = 16000         # sample rate (Hz)
    SILENCE_STOP   = 2.2           # seconds of quiet after speech → stop
    SILENCE_START  = timeout       # seconds to wait for speech to begin
    MAX_DURATION   = phrase_limit  # hard cap in seconds
    # RMS threshold: below this = silence. Calibrated after 0.4 s of ambient.
    AMBIENT_SECS   = 0.4
    THRESHOLD_MULT = 1.8           # silence threshold = ambient_rms * this

    try:
        import pyaudio, struct, math, tempfile, wave as wavemod
    except ImportError:
        # pyaudio not available — fall back to SpeechRecognition path
        return _listen_mic_sr_fallback(timeout, phrase_limit)

    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                         input=True, frames_per_buffer=CHUNK)
    except OSError as e:
        pa.terminate()
        if "Bad CPU type" in str(e) or "flac" in str(e).lower():
            print(color("  [FLAC error — macOS: brew install flac  |  Windows: download from https://xiph.org/flac]", "red"))
        else:
            print(color(f"  [mic error: {e}]", "red"))
            if _PLATFORM == "Darwin":
                print(color("  Tip: check System Settings › Privacy › Microphone for Terminal", "dim"))
            elif _PLATFORM == "Windows":
                print(color("  Tip: check Settings › Privacy › Microphone and allow Terminal / Python", "dim"))
            else:
                print(color("  Tip: check mic permissions and that portaudio is installed", "dim"))
        return None

    def rms(data):
        count = len(data) // 2
        if count == 0:
            return 0
        shorts = struct.unpack(f"{count}h", data)
        s = sum(x * x for x in shorts)
        return math.sqrt(s / count)

    try:
        # ── Calibrate ambient noise ───────────────────────────────────────────
        ambient_frames = int(RATE / CHUNK * AMBIENT_SECS)
        ambient_samples = []
        for _ in range(ambient_frames):
            ambient_samples.append(rms(stream.read(CHUNK, exception_on_overflow=False)))
        ambient_rms = max(30, sum(ambient_samples) / len(ambient_samples))
        threshold = ambient_rms * THRESHOLD_MULT

        # ── Stream until speech then silence ─────────────────────────────────
        frames        = []
        speech_begun  = False
        silent_chunks = 0
        chunks_ps     = RATE // CHUNK   # chunks per second
        silence_stop_chunks  = int(SILENCE_STOP  * chunks_ps)
        silence_start_chunks = int(SILENCE_START * chunks_ps)
        max_chunks           = int(MAX_DURATION  * chunks_ps)
        waited_chunks        = 0

        while True:
            data  = stream.read(CHUNK, exception_on_overflow=False)
            level = rms(data)

            if not speech_begun:
                if level > threshold:
                    speech_begun = True
                    frames.append(data)
                    silent_chunks = 0
                else:
                    waited_chunks += 1
                    if waited_chunks >= silence_start_chunks:
                        return ""   # timeout waiting for speech to start
            else:
                frames.append(data)
                if level <= threshold:
                    silent_chunks += 1
                    if silent_chunks >= silence_stop_chunks:
                        break       # done — long enough pause after speech
                else:
                    silent_chunks = 0  # reset: still talking

                if len(frames) >= max_chunks:
                    break           # hard cap

    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

    if not frames:
        return ""

    # ── Write to temp WAV ─────────────────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        fname = f.name
    with wavemod.open(fname, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))

    # ── Transcribe: faster-whisper → Google fallback ──────────────────────────
    try:
        global _whisper_model
        from faster_whisper import WhisperModel
        if _whisper_model is None:
            _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = _whisper_model.transcribe(fname, beam_size=1)
        os.unlink(fname)
        return " ".join(s.text for s in segments).strip()
    except ImportError:
        pass

    # Google STT fallback
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(fname) as source:
            audio = recognizer.record(source)
        os.unlink(fname)
        return recognizer.recognize_google(audio)
    except Exception:
        try:
            os.unlink(fname)
        except OSError:
            pass
        return ""


def _listen_mic_sr_fallback(timeout=12, phrase_limit=45):
    """SpeechRecognition-only fallback when pyaudio raw streaming isn't available."""
    try:
        import speech_recognition as sr
    except ImportError:
        return None
    sys_flac = shutil.which("flac")
    try:
        r = sr.Recognizer()
        r.pause_threshold        = 2.5
        r.non_speaking_duration  = 2.0
        r.energy_threshold       = 150
        r.dynamic_energy_threshold = False   # disable — it creeps up in quiet rooms
        with sr.Microphone() as src:
            r.adjust_for_ambient_noise(src, duration=0.4)
            r.energy_threshold = min(r.energy_threshold, 300)
            try:
                audio = r.listen(src, timeout=timeout, phrase_time_limit=phrase_limit)
            except sr.WaitTimeoutError:
                return ""
        if sys_flac:
            sr.audio.FLAC_CONVERTER = sys_flac
        try:
            global _whisper_model
            from faster_whisper import WhisperModel
            import tempfile
            if _whisper_model is None:
                _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            wav_data = audio.get_wav_data()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_data)
                fname = f.name
            segments, _ = _whisper_model.transcribe(fname, beam_size=1)
            os.unlink(fname)
            return " ".join(s.text for s in segments).strip()
        except ImportError:
            pass
        try:
            return r.recognize_google(audio)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            return None
    except OSError as e:
        if "Bad CPU type" in str(e) or "flac" in str(e).lower():
            print(color("  [FLAC error — macOS: brew install flac  |  Windows: download from https://xiph.org/flac]", "red"))
        else:
            print(color(f"  [mic error: {e}]", "red"))
            if _PLATFORM == "Darwin":
                print(color("  Tip: check System Settings › Privacy › Microphone for Terminal", "dim"))
            elif _PLATFORM == "Windows":
                print(color("  Tip: check Settings › Privacy › Microphone and allow Terminal / Python", "dim"))
            else:
                print(color("  Tip: check mic permissions and that portaudio is installed", "dim"))
        return None
    except Exception as e:
        print(color(f"  [mic error: {e}]", "red"))
        return None

# ── Data ──────────────────────────────────────────────────────────────────────

SAVE_DIR  = os.path.expanduser("~/.life_missions")
SAVE_FILE = os.path.join(SAVE_DIR, "global.json")   # wishlist, fund, settings
WHITELIST_FILE = os.path.join(SAVE_DIR, "whitelist.json")

# ── Action whitelist ──────────────────────────────────────────────────────────
# Kriti can ONLY trigger apps/scripts that are explicitly listed here. She can
# never invent a shell command or run anything outside this file. You edit
# this list yourself (directly, or via Settings → Manage Whitelist).
#
# apps:    {"name": "Visual Studio Code"}  — must be the exact macOS app name
# scripts: {"name": "backup_prier", "path": "/Users/tanish/scripts/backup.sh"}
#          path must be an absolute path to a file that already exists.

DEFAULT_WHITELIST = {
    "apps": [
        {"name": "Visual Studio Code"},
        {"name": "Spotify"},
        {"name": "Terminal"},
    ],
    "scripts": []
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
    return False, "Volume control only supported on macOS currently"

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
    return False, "Lock screen only supported on macOS currently"

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

SYSTEM_CONTEXT = """You are the mission commander for Tanish Gupta's life gamification system.

WHO HE IS:
- First-year B.Tech ECE student at NSUT Dwarka, New Delhi (batch 2025-2029)
- Founder of Prier (priers.studio) - MSME intern talent intermediary placing pre-vetted candidates with early-stage startups
- Research Consultant at WorldQuant, Gold rank on BRAIN, reached Stage 2 of IQC 2026
- Building a Wear OS app (Samsung Galaxy Watch) using Jetpack Compose/Kotlin
- HR lead: Nidhi Panwala handles candidate screening

ACTIVE PROJECTS:
- Prier: Supabase backend (PostgreSQL + RLS), hirer verification via company email OTP, Next.js App Router, hirer matches carousel
- WorldQuant BRAIN: IQC Stage 2 alphas - FFO/debt signals, stochastic DCF mispricing (EV/cashflow, EV/ebitda), volatility skew. Constraints: use min()/max() not &/|, group_mean needs 3 args, ts_rank takes 2 args
- IFSA chapter at NSUT (president succession on seniors' graduation)
- Wear OS biometric app (Gradle/KSP resolved)
- PC build fund: Ryzen 5 7500F + RTX 5060 Ti 16GB + MSI B850M

FIXED DAILY TASKS (already assigned, DO NOT repeat):
- Complete PPL workout
- 2hr focused study session
- Sleep before 1am
- No phone first 30 min after waking
- Daily review / journal

Generate ONE specific, high-impact bonus mission. Ekdum concrete — not "work on Prier" but "write the hirer onboarding email sequence for Prier's OTP flow". Value: Rs10-25. The "why" should be punchy and direct — like a Delhi friend telling him what actually matters today.

Respond ONLY with raw JSON, no markdown:
{"label":"<task>","area":"<Prier|BRAIN|Fitness|Academics|Habits|Wear OS>","value":<10|15|20|25>,"why":"<one punchy sentence>"}"""

FIXED_TASKS = [
    {"id": "workout",  "label": "Complete PPL workout",               "area": "Fitness",   "value": 20},
    {"id": "study",    "label": "2hr focused study session",          "area": "Academics", "value": 15},
    {"id": "sleep",    "label": "Sleep before 1am",                   "area": "Habits",    "value": 10},
    {"id": "nophone",  "label": "No phone first 30min after waking",  "area": "Habits",    "value": 5},
    {"id": "review",   "label": "Daily review / journal",             "area": "Habits",    "value": 5},
]

WISHLIST = [
    {"id": "cpu",      "name": "Ryzen 5 7500F",                   "cost": 14399,  "saved": 0, "cat": "PC Build"},
    {"id": "mobo",     "name": "MSI B850M Gaming WiFi",           "cost": 12999,  "saved": 0, "cat": "PC Build"},
    {"id": "gpu",      "name": "RTX 5060 Ti Eagle OC ICE 16GB",   "cost": 62499,  "saved": 0, "cat": "PC Build"},
    {"id": "ram",      "name": "ADATA XPG Lancer 32GB DDR5-6000", "cost": 36999,  "saved": 0, "cat": "PC Build"},
    {"id": "ssd",      "name": "Crucial T700 1TB PCIe 5.0",       "cost": 19395,  "saved": 0, "cat": "PC Build"},
    {"id": "cooler",   "name": "CM MasterLiquid 360L ARGB",       "cost": 6999,   "saved": 0, "cat": "PC Build"},
    {"id": "psu",      "name": "Deepcool PN750M 750W Gold",        "cost": 8048,   "saved": 0, "cat": "PC Build"},
    {"id": "case",     "name": "CM Elite 490 White",               "cost": 4658,   "saved": 0, "cat": "PC Build"},
    {"id": "monitor",  "name": 'MSI MAG 341CQP QD-OLED 34"',      "cost": 67999,  "saved": 0, "cat": "PC Build"},
    {"id": "tekken",   "name": "Tekken 8",                         "cost": 1500,   "saved": 0, "cat": "Games"},
    {"id": "hd2",      "name": "Helldivers 2",                     "cost": 1874,   "saved": 0, "cat": "Games"},
    {"id": "gta6",     "name": "GTA 6",                            "cost": 7500,   "saved": 0, "cat": "Games"},
    {"id": "iphone",   "name": "iPhone Mini (latest pls)",         "cost": 90000,  "saved": 0, "cat": "Wishlist"},
    {"id": "console",  "name": "Console",                          "cost": 70000,  "saved": 0, "cat": "Wishlist"},
]

AREA_COLOR_MAP = {
    "Fitness":   "green",
    "Academics": "cyan",
    "Prier":     "yellow",
    "BRAIN":     "magenta",
    "Habits":    "bright_green",
    "Wear OS":   "bright_red",
}

# ── Persistence ───────────────────────────────────────────────────────────────

def today_key():
    return datetime.date.today().isoformat()

def day_file(date_str=None):
    os.makedirs(SAVE_DIR, exist_ok=True)
    return os.path.join(SAVE_DIR, f"{date_str or today_key()}.json")

def load_day(date_str=None):
    path = day_file(date_str)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}

def save_day(day_data, date_str=None):
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(day_file(date_str), "w") as f:
        json.dump(day_data, f, indent=2)

def load_global():
    os.makedirs(SAVE_DIR, exist_ok=True)
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}

def save_global(g):
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(SAVE_FILE, "w") as f:
        json.dump(g, f, indent=2)

def load_state():
    """Merge global state + today's day file into one state dict (backward compat)."""
    g = load_global()
    d = load_day()
    tk = today_key()
    # Splice today's day file fields into state
    state = dict(g)
    if d:
        state.setdefault("completed", {})[tk] = d.get("completed", {})
        state.setdefault("locked_days", {})[tk] = d.get("locked", False)
        state.setdefault("ai_tasks", {})[tk] = d.get("ai_task")
        state.setdefault("custom_tasks", {})[tk] = d.get("custom_tasks", [])
        # Merge history entry
        if d.get("locked") and d.get("history"):
            state.setdefault("history", {})[tk] = d["history"]
    return state

def save_state(state):
    """Write global fields to global.json and today's fields to YYYY-MM-DD.json."""
    tk = today_key()

    # Global: fund, wishlist, settings, history (all days), etc.
    g = {k: v for k, v in state.items()
         if k not in ("completed", "locked_days", "ai_tasks", "custom_tasks")}
    # Keep full history in global too for the history screen
    save_global(g)

    # Per-day file
    d = {
        "date":         tk,
        "completed":    state.get("completed", {}).get(tk, {}),
        "locked":       state.get("locked_days", {}).get(tk, False),
        "ai_task":      state.get("ai_tasks", {}).get(tk),
        "custom_tasks": state.get("custom_tasks", {}).get(tk, []),
        "history":      state.get("history", {}).get(tk),
    }
    save_day(d)

# ── Ollama ────────────────────────────────────────────────────────────────────

def call_ollama(context="", host="http://localhost:11434", model="gemma4"):
    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_CONTEXT},
            {"role": "user",   "content": context or "Generate a focused bonus mission for today."},
        ]
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    text = r.json()["message"]["content"]
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

KRITI_CONTEXT = """You are Kriti, Tanish Gupta's personal AI assistant — his sharp, caring, no-nonsense best friend. Think the girl who actually reads your essays before you submit them and tells you the truth. You know everything about him:

IDENTITY:
- First-year B.Tech ECE at NSUT Dwarka, Delhi (2025-2029)
- Founder of Prier (priers.studio) — MSME intern talent intermediary
- WorldQuant Research Consultant, Gold rank on BRAIN, IQC 2026 Stage 2
- Building Wear OS app (Samsung Galaxy Watch, Jetpack Compose/Kotlin)
- PPL training split, into gaming, anime, Pokémon, PC building

ACTIVE PROJECTS:
- Prier: Supabase (PostgreSQL + RLS), company email OTP hirer verification, Next.js App Router, hirer matches carousel. HR: Nidhi Panwala
- BRAIN: IQC Stage 2 — FFO/debt signals, stochastic DCF mispricing (EV/cashflow, EV/ebitda), volatility skew. Constraints: min()/max() not &/|, group_mean needs 3 args, ts_rank 2 args
- IFSA chapter at NSUT (president on seniors' graduation)
- Wear OS biometric sensor app (Gradle/KSP resolved)
- PC build: Ryzen 5 7500F + RTX 5060 Ti 16GB + MSI B850M

WISHLIST: Ryzen 5 7500F (₹14,399), MSI B850M (₹12,999), RTX 5060 Ti (₹62,499), RAM DDR5-6000 (₹36,999), Crucial T700 SSD (₹19,395), CM 360L cooler (₹6,999), Deepcool 750W PSU (₹8,048), CM Elite 490 case (₹4,658), MSI QD-OLED 34" (₹67,999), Tekken 8 (₹1,500), Helldivers 2 (₹1,874), GTA 6 (₹7,500), iPhone Mini (₹90,000), Console (₹70,000)

PERSONALITY:
- English only. Warm, direct, real — never robotic or corporate.
- You are his best female friend who genuinely loves him but will NOT let him slide. The energy: soft hug in one hand, reality check in the other.
- Affectionate but firm. You call him "Tanish" when you're proud, and also when you're disappointed — the difference is the tone. Use "honey", "love", "darling" sparingly but naturally, the way a close friend does.
- Celebrate his wins with full heart — "Tanish, I'm actually so proud of you right now", "okay THAT is huge, don't downplay it", "you worked for this, own it"
- When he's slacking, name it clearly but without cruelty — "hey, we both know that's not good enough", "I'm not going to pretend that's okay, come on", "you're better than this and you know it" — one callout, then move forward
- No lectures, no repeating yourself. Say it once, mean it, then help him fix it.
- If he seems stressed or overwhelmed, lead with care — "okay, slow down, talk to me" — then get practical once he's grounded
- Sarcasm and playful teasing are fine, but always punching up, never down. She teases because she believes in him.
- Never sycophantic. If something is genuinely great, say so. If it's not, don't pretend it is.
- Keep responses tight. You don't ramble. You say what needs saying and stop.

ACTIONS:
You can perform actions by including tags in your response. Write your conversational reply AND the action tag(s) together.
- Mark a task done:    [[DONE:task_id]]
- Unmark a task:       [[UNDONE:task_id]]
- Add a one-time task: [[ADD_TASK:label|area|value]]
- Add recurring task:  [[ADD_RECURRING:label|area|value|days]]
  days = daily, weekdays, weekends, or comma-separated like mon,wed,fri
- Create a quest:      [[ADD_QUEST:title|milestone1;milestone2;milestone3|bonus|deadline]]
  deadline format: YYYY-MM-DD
- Complete quest milestone: [[QUEST_DONE:quest_id:milestone_index]]
  milestone_index is 0-based
- Start a pomodoro timer: [[START_POMODORO:minutes]]
  Use this when the user wants to focus or you suggest a work session.
  Example: "Let's do a 25-min session!"
  [[START_POMODORO:25]]

SYSTEM ACTIONS (only work for whitelisted apps/scripts — see WHITELIST below):
- Open an app:        [[OPEN_APP:exact app name]]
- Run a script:       [[RUN_SCRIPT:exact script name]]
- Set volume:         [[SET_VOLUME:0-100]]
- Lock the screen:    [[LOCK_SCREEN]]
  Only use OPEN_APP / RUN_SCRIPT with names that appear EXACTLY in the WHITELIST
  section below. If he asks for an app or script not on the list, tell him it's
  not whitelisted and that he can add it from Settings — do NOT pretend it worked
  and do NOT emit the tag for something off the list.

KNOWLEDGE ACTIONS:
- Re-index notes:     [[RAG_INDEX]]
  Use when the user says they've added new notes/docs and wants to re-index.
  The RELEVANT NOTES section at the bottom of LIVE STATUS (if present) shows
  chunks retrieved from his indexed notes. Cite the source file when referencing them.
  If no notes section appears, either no docs are indexed yet or the query didn't
  match anything — don't make up answers in that case.
- Switch persona:     [[SET_PERSONA:name]]
  Use when the user explicitly asks to switch mode, e.g. "switch to deep work mode"
  or "go into BRAIN research mode". Valid names come from the ACTIVE PERSONA section
  (if shown). To clear the active persona use [[SET_PERSONA:clear]].
  The user can also type /persona <name> directly at any time.
  IMPORTANT: If a persona is active, you can ONLY use action tags listed under it.
  Attempting actions outside the persona's allowlist will be blocked and shown as an
  error — so don't try them.
- Reload automations: [[AUTOMATION_RELOAD]]
  Use when the user says they edited automations.json and wants it picked up live.
  Automations fire on a schedule in the background while Kriti is running — they
  are NOT triggered by the user talking. They can: print a nudge message, speak
  it (if voice is on), fire action tags (gated by persona + unattended rules).
  OPEN_APP and RUN_SCRIPT never fire in unattended mode for safety.
- Web search:         [[WEB_SEARCH:your query here]]
  Use when you need live or recent information that your local notes don't cover.
  Results will appear as WEB SEARCH RESULTS in your context for the NEXT turn.
  Web search also fires automatically when a user query contains recency signals
  (today, latest, current, price, news, etc.) — you don't need to emit the tag
  for those. Cite web sources as [W1], [W2] etc. Never cite a web source you
  haven't actually seen in the WEB SEARCH RESULTS block.
  If a persona has web search disabled, this tag will be silently skipped.


area must be one of: Prier, BRAIN, Fitness, Academics, Habits, Wear OS
value must be 5, 10, 15, 20, or 25

Examples:
- User: "done with my workout" → "Look at you! Proud.
[[DONE:workout]]"
- User: "add a task to review Prier PRs" → "Good call, adding it now.
[[ADD_TASK:Review open Prier PRs|Prier|15]]"
- User: "I want to read 20 pages every day" → "That's actually a great habit. I'm adding it as a daily.
[[ADD_RECURRING:Read 20 pages|Academics|10|daily]]"
- User: "create a quest to ship prier v2" → "Finally. Let's break it down properly.
[[ADD_QUEST:Ship Prier v2|Finish OTP flow;Deploy to prod;Get 5 hirer signups|100|2026-07-15]]"
- User: "finished the OTP flow for the prier quest" → "Tanish. That was the hard one. I'm genuinely proud — now don't stop.
[[QUEST_DONE:quest_1:0]]"
- User: "open vscode" (VS Code is whitelisted) → "On it.
[[OPEN_APP:Visual Studio Code]]"
- User: "open photoshop" (not whitelisted) → "Photoshop isn't on your whitelist — add it from Settings if you want me to be able to open it."
- User: "turn the volume down to like 20" → "Done.
[[SET_VOLUME:20]]"
- User: "lock my screen, I'm stepping out" → "Locking it now. Go.
[[LOCK_SCREEN]]"

Rules:
- ONLY use task IDs from the LIVE STATUS below. Never guess IDs.
- ALWAYS include the action tag when the user asks to mark/add tasks. Don't just say you'll do it.
- CRITICAL: Action tags MUST be on their own separate line, NEVER embedded inside a sentence.
  WRONG: "Get some sleep ([[DONE:sleep]])"  ← this will NOT fire
  RIGHT: Write your message first, then put the tag alone on a new line:
    Get some sleep, seriously.
    [[DONE:sleep]]
- If you are suggesting an action but NOT doing it yet, describe it in plain text. Only emit the tag when you are actually performing the action right now.
- If the day is locked, tell the user you can't modify tasks.
- You can include multiple action tags, each on its own line.
- CRITICAL SAFETY RULE: Never emit OPEN_APP or RUN_SCRIPT for a name that is not listed verbatim in the WHITELIST section of LIVE STATUS. If unsure whether something is whitelisted, don't emit the tag — ask or tell him to check Settings. You have no ability to run anything outside this whitelist, no matter how he phrases the request."""

def call_kriti_stream(messages, host, model, on_sentence=None):
    """Stream Kriti's response token by token.

    If on_sentence is provided, it's called with each complete sentence
    as it arrives (for streaming TTS). Returns the full response text.
    """
    url = f"{host}/api/chat"
    payload = {
        "model":  model,
        "stream": True,
        "messages": messages,
    }
    SENTENCE_END = re.compile(r'(?<=[.!?\n])\s+')
    buf = ""
    full = ""

    with requests.post(url, json=payload, stream=True, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                print(token, end="", flush=True)
                full += token
                buf  += token

                if on_sentence:
                    # Fire TTS on each sentence boundary as it arrives
                    parts = SENTENCE_END.split(buf)
                    if len(parts) > 1:
                        for sentence in parts[:-1]:
                            sentence = sentence.strip()
                            if sentence:
                                on_sentence(sentence)
                        buf = parts[-1]  # keep incomplete tail

                if chunk.get("done"):
                    break
            except json.JSONDecodeError:
                continue

        # Speak any remaining buffer tail
        if on_sentence and buf.strip():
            on_sentence(buf.strip())

        print()  # newline after stream ends
        return full

# ── Terminal UI ───────────────────────────────────────────────────────────────

term = Terminal()

def clr():
    print(term.clear(), end="")

def color(text, c):
    mapping = {
        "green":        term.green,
        "cyan":         term.cyan,
        "yellow":       term.yellow,
        "magenta":      term.magenta,
        "bright_green": term.bright_green,
        "bright_red":   term.bright_red,
        "lime":         term.bright_green,
        "dim":          term.dim,
        "bold":         term.bold,
        "red":          term.red,
    }
    fn = mapping.get(c, lambda x: x)
    return fn(text) + term.normal

def header(state):
    fund = state.get("fund", 0)
    tk   = today_key()
    done = state.get("completed", {}).get(tk, {})
    tasks = get_all_tasks(state, tk)
    earned = sum(t["value"] for t in tasks if done.get(t["id"]))
    maxv   = sum(t["value"] for t in tasks)

    dt  = datetime.date.today()
    date_str = dt.strftime("%A, %d %b %Y")   # e.g. Tuesday, 01 Jul 2026

    print(color("─" * 50, "dim"))
    print(color("  TANISH.EXE  ·  Life OS", "bold") +
          "   " + color(f"Fund: ₹{fund:,}", "lime"))
    print(color(f"  {date_str}", "yellow"))
    pct = int((earned / maxv * 40)) if maxv else 0
    bar = color("█" * pct, "bright_green") + color("░" * (40 - pct), "dim")
    print(f"  Today: ₹{earned}/{maxv}  [{bar}]")
    print(color("─" * 50, "dim"))

def prompt(msg, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(color(f"  {msg}{suffix}: ", "dim")).strip()
    return val if val else default

def pause():
    input(color("\n  Press Enter to continue...", "dim"))

def get_all_tasks(state, tk):
    tasks = list(FIXED_TASKS)
    ai = state.get("ai_tasks", {}).get(tk)
    if ai:
        tasks.append(ai)
    for ct in state.get("custom_tasks", {}).get(tk, []):
        tasks.append(ct)
    # Recurring custom tasks (filtered by day of week)
    today_dow = datetime.date.today().strftime("%a").lower()[:3]  # mon, tue, ...
    is_weekday = today_dow in ("mon", "tue", "wed", "thu", "fri")
    for rt in state.get("recurring_tasks", []):
        days = rt.get("days", "daily")
        include = False
        if days == "daily":
            include = True
        elif days == "weekdays":
            include = is_weekday
        elif days == "weekends":
            include = not is_weekday
        elif isinstance(days, str):
            include = today_dow in [d.strip().lower()[:3] for d in days.split(",")]
        elif isinstance(days, list):
            include = today_dow in [d.lower()[:3] for d in days]
        if include:
            tasks.append(rt)
    return tasks

# ── Journal export & streak ───────────────────────────────────────────────────

JOURNAL_FILE = os.path.join(SAVE_DIR, "journal.md")
CHAT_FILE    = os.path.join(SAVE_DIR, "kriti_chat.json")

def _calc_streak(state):
    """Count consecutive days with at least 1 task completed (ending today or yesterday)."""
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
    return streak

def _export_journal(state, tk, tasks, done, earned):
    """Append today's summary to journal.md."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    dt = datetime.date.fromisoformat(tk)
    dow = dt.strftime("%a %d %b %Y")
    streak = _calc_streak(state)
    fund = state.get("fund", 0)

    lines = [f"\n## {dow} \u2014 \u20b9{earned} earned\n"]
    for t in tasks:
        tick = "\u2713" if done.get(t["id"]) else "\u2717"
        lines.append(f"- {tick} {t['label']} [{t['area']}] +\u20b9{t['value']}")
    lines.append(f"\n**Fund: \u20b9{fund:,}** \u00b7 Streak: {streak} day{'s' if streak != 1 else ''}\n")
    lines.append("---\n")

    with open(JOURNAL_FILE, "a") as f:
        f.write("\n".join(lines))

def _save_chat(messages):
    """Save chat history to disk."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(CHAT_FILE, "w") as f:
        json.dump(messages[-40:], f, indent=2)  # keep last 40 messages

def _load_chat():
    """Load chat history from disk."""
    if os.path.exists(CHAT_FILE):
        try:
            with open(CHAT_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []
    return []

# ── Screens ───────────────────────────────────────────────────────────────────

def screen_missions(state):
    tk   = today_key()
    done = state.setdefault("completed", {}).setdefault(tk, {})
    locked = state.get("locked_days", {}).get(tk, False)
    tasks  = get_all_tasks(state, tk)

    while True:
        clr()
        header(state)
        print(color("  MISSIONS", "bold"))
        print()

        for i, t in enumerate(tasks):
            c    = AREA_COLOR_MAP.get(t["area"], "dim")
            tick = color("✓", "bright_green") if done.get(t["id"]) else color("○", "dim")
            num  = color(f"[{i+1}]", "dim")
            tag  = color(f"[{t['area']}]", c)
            val  = color(f"+₹{t['value']}", "bright_green" if done.get(t["id"]) else "dim")
            label = color(t["label"], "bold") if not done.get(t["id"]) else color(t["label"], "dim")
            print(f"  {tick} {num} {label}  {tag}  {val}")
            if t.get("why"):
                print(color(f"       ↳ {t['why']}", "dim"))

        earned = sum(t["value"] for t in tasks if done.get(t["id"]))

        print()
        if locked:
            print(color(f"  ✓ Day locked · ₹{earned} added to fund", "bright_green"))
        else:
            print(color("  [1-N] Toggle task  [a] AI mission  [e] End day  [q] Back", "dim"))

        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "e" and not locked:
            if earned == 0:
                print(color("\n  Complete at least one task first.", "red"))
                pause()
                continue
            state["fund"] = state.get("fund", 0) + earned
            state.setdefault("locked_days", {})[tk] = True
            state.setdefault("history", {})[tk] = {
                "earned": earned,
                "tasks": [{"label": t["label"], "area": t["area"], "value": t["value"], "done": bool(done.get(t["id"]))} for t in tasks]
            }
            save_state(state)
            sfx("lock")
            notify("TANISH.EXE", f"₹{earned} earned today. Total fund: ₹{state['fund']:,}")
            # Daily journal export
            _export_journal(state, tk, tasks, done, earned)
            print(color(f"\n  ₹{earned} added to fund. Total: ₹{state['fund']:,}", "bright_green"))
            pause()
            locked = True
        elif ch == "a" and not locked:
            screen_generate_ai(state, tk)
            tasks = get_all_tasks(state, tk)
        elif ch.isdigit():
            idx = int(ch) - 1
            if 0 <= idx < len(tasks) and not locked:
                tid = tasks[idx]["id"]
                done[tid] = not done.get(tid, False)
                if done[tid]:
                    sfx("done")
                save_state(state)

def screen_generate_ai(state, tk):
    clr()
    header(state)
    print(color("  AI BONUS MISSION  ·  via Ollama", "bold"))
    print()
    host  = state.get("ollama_host",  "http://localhost:11434")
    model = state.get("ollama_model", "gemma4")
    print(color(f"  Model: {model}  Host: {host}", "dim"))
    print()
    ctx = prompt("Focus for today (optional, Enter to skip)", "")
    print()
    print(color("  Calling Ollama...", "dim"))
    try:
        task = call_ollama(ctx, host, model)
        task["id"] = "ai_task"
        state.setdefault("ai_tasks", {})[tk] = task
        save_state(state)
        c = AREA_COLOR_MAP.get(task.get("area", ""), "dim")
        print(color(f"\n  ✦ {task['label']}", "bold"))
        print(color(f"    {task.get('why','')}", "dim"))
        print(color(f"    [{task.get('area','')}]  +₹{task.get('value',0)}", c))
    except Exception as e:
        print(color(f"\n  Error: {e}", "red"))
        print(color("  Make sure Ollama is running: OLLAMA_ORIGINS=* ollama serve", "dim"))
    pause()

def screen_wishlist(state):
    show_purchased = False
    while True:
        clr()
        header(state)
        wl   = state.get("wishlist", WISHLIST)
        fund = state.get("fund", 0)
        total_cost  = sum(w["cost"] for w in wl if not w.get("purchased"))
        total_saved = sum(w["saved"] for w in wl if not w.get("purchased"))
        purchased_count = sum(1 for w in wl if w.get("purchased"))
        print(color("  WISHLIST", "bold"))
        print(color(f"  ₹{total_saved:,} saved  ·  ₹{total_cost - total_saved:,} to go", "dim"))
        if purchased_count:
            toggle_key = "h" if show_purchased else "s"
            toggle_label = "hide" if show_purchased else "show"
            print(color(f"  {purchased_count} item(s) purchased", "bright_green") +
                  color(f"  [{toggle_key}] {toggle_label} purchased", "dim"))
        print()

        cats = {}
        for w in wl:
            if w.get("purchased") and not show_purchased:
                continue
            cats.setdefault(w["cat"], []).append(w)

        idx_map = {}
        i = 1
        for cat, items in cats.items():
            print(color(f"  {cat}", "yellow"))
            for item in items:
                bought = item.get("purchased", False)
                pct  = min(20, int(item["saved"] / item["cost"] * 20))
                bar  = color("█" * pct, "bright_green") + color("░" * (20 - pct), "dim")
                done = item["saved"] >= item["cost"]
                if bought:
                    tick = color("✓✓", "bright_green")
                elif done:
                    tick = color("✓ ", "bright_green")
                else:
                    tick = "  "
                num  = color(f"[{i}]", "dim")
                if bought:
                    name = color(f"{item['name']} · BOUGHT", "dim")
                else:
                    name = color(item["name"], "dim" if done else "bold")
                pstr = f"₹{item['saved']:,}/₹{item['cost']:,}"
                print(f"  {tick}{num} {name}")
                print(f"      [{bar}] {color(pstr, 'dim')}")
                idx_map[str(i)] = item
                i += 1
            print()

        print(color("  [1-N] Allocate fund  [s/h] Show/hide purchased  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch in ("s", "h"):
            show_purchased = not show_purchased
        elif ch in idx_map:
            item = idx_map[ch]
            if item.get("purchased"):
                yn = prompt("Unmark as purchased? (y/n)", "n")
                if yn.lower() == "y":
                    item["purchased"] = False
                    state["wishlist"] = wl
                    save_state(state)
                    print(color(f"\n  {item['name']} unmarked.", "yellow"))
                pause()
                continue
            if item["saved"] >= item["cost"]:
                print(color(f"\n  {item['name']} is fully funded!", "bright_green"))
                yn = prompt("Mark as purchased? (y/n)", "n")
                if yn.lower() == "y":
                    item["purchased"] = True
                    state["wishlist"] = wl
                    save_state(state)
                    print(color(f"\n  ✓✓ {item['name']} marked as purchased!", "bright_green"))
                    pause()
                    continue
            print(color(f"\n  Allocating to: {item['name']}", "bold"))
            print(color(f"  Available fund: ₹{fund:,}  ·  Still needed: ₹{item['cost'] - item['saved']:,}", "dim"))
            raw = prompt("Amount to allocate (₹)", "")
            if raw and raw.isdigit():
                amt = int(raw)
                if amt > fund:
                    print(color(f"\n  Not enough fund (₹{fund:,} available).", "red"))
                elif amt <= 0:
                    print(color("\n  Enter a positive amount.", "red"))
                else:
                    item["saved"] = min(item["cost"], item["saved"] + amt)
                    state["fund"] = fund - amt
                    state["wishlist"] = wl
                    save_state(state)
                    print(color(f"\n  ₹{amt:,} allocated. {item['name']}: ₹{item['saved']:,}/₹{item['cost']:,}", "bright_green"))
            elif raw:
                print(color("\n  Enter a valid number.", "red"))
            pause()

def screen_history(state):
    page = 0
    page_size = 5
    while True:
        clr()
        header(state)
        hist = state.get("history", {})
        print(color("  HISTORY", "bold"))
        print()

        if not hist:
            print(color("  No history yet. Lock your first day.", "dim"))
            pause()
            return

        all_days = sorted(hist.items(), reverse=True)
        total_all = sum(d["earned"] for _, d in all_days)
        avg = total_all // len(all_days) if all_days else 0
        total_pages = (len(all_days) + page_size - 1) // page_size
        page = min(page, total_pages - 1)

        start = page * page_size
        end   = start + page_size
        days  = all_days[start:end]

        print(color(f"  {len(all_days)}-day total: ₹{total_all:,}  ·  avg ₹{avg}/day", "yellow"))
        print(color(f"  Page {page + 1}/{total_pages}", "dim"))
        print()

        for date_str, day in days:
            dt  = datetime.date.fromisoformat(date_str)
            dow = dt.strftime("%a %d %b")
            print(color(f"  {dow}", "bold") + color(f"  +₹{day['earned']}", "bright_green"))
            for t in day.get("tasks", []):
                tick = color("✓", "bright_green") if t["done"] else color("✗", "red")
                c    = AREA_COLOR_MAP.get(t["area"], "dim")
                print(f"    {tick} {color(t['label'], 'dim')}  {color('+₹'+str(t['value']), c if t['done'] else 'dim')}")
            print()

        nav = []
        if page > 0:
            nav.append("[p] Prev")
        if page < total_pages - 1:
            nav.append("[n] Next")
        nav.append("[a] Analytics")
        nav.append("[q] Back")
        print(color(f"  {'  ·  '.join(nav)}", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "p" and page > 0:
            page -= 1
        elif ch == "n" and page < total_pages - 1:
            page += 1
        elif ch == "a":
            _show_analytics(state, hist)

def parse_kriti_actions(text, state):
    """Parse [[ACTION]] tags from Kriti's reply.

    Returns (clean_text, confirmations, pending_actions).
    pending_actions is a list of dicts for deferred execution (e.g. pomodoro).
    Only tags on their OWN LINE are executed. Inline tags are stripped only.
    """
    confirmations  = []
    pending_actions = []
    tk = today_key()
    done = state.setdefault("completed", {}).setdefault(tk, {})
    locked = state.get("locked_days", {}).get(tk, False)

    ALL_ACTION_NAMES = (r'DONE|UNDONE|ADD_TASK|ADD_RECURRING|ADD_QUEST|QUEST_DONE|'
                         r'START_POMODORO|OPEN_APP|RUN_SCRIPT|SET_VOLUME|LOCK_SCREEN|'
                         r'RAG_INDEX|SET_PERSONA|AUTOMATION_RELOAD|WEB_SEARCH')
    STRIP_RE = re.compile(r'\[\[(?:' + ALL_ACTION_NAMES + r')(?::[^\]]+)?\]\]')

    # Active persona for this parse call — enforced at dispatch time
    _active_persona = kriti_personas.get_active_persona() if _PERSONAS_AVAILABLE else None

    if locked:
        clean = STRIP_RE.sub('', text).strip()
        return clean, [], []

    tasks = get_all_tasks(state, tk)
    task_ids = {t["id"]: t for t in tasks}
    wl = load_whitelist()

    # Matches both [[ACTION:payload]] and bare [[ACTION]] (e.g. LOCK_SCREEN)
    ACTION_RE      = re.compile(r'\[\[([A-Z_]+)(?::([^\]]+))?\]\]')
    action_line_re = re.compile(r'^\s*(\[\[[A-Z_]+(?::[^\]]+)?\]\]\s*)+$')

    for line in text.splitlines():
        if not action_line_re.match(line):
            continue
        for match in ACTION_RE.finditer(line):
            action  = match.group(1)
            payload = match.group(2) or ""

            # ── Persona gate — enforce BEFORE any side-effect ────────────────
            if _PERSONAS_AVAILABLE and action != "SET_PERSONA":
                permitted, reason = kriti_personas.action_permitted(action, _active_persona)
                if not permitted:
                    pname = (_active_persona or {}).get("display_name") or (_active_persona or {}).get("name", "?")
                    confirmations.append(color(
                        f"  ✗ [{action}] blocked by '{pname}' persona — {reason}",
                        "red"
                    ))
                    continue  # skip execution entirely — NOT a crash

            if action == "DONE":
                tid = payload.strip()
                if tid in task_ids:
                    done[tid] = True
                    t = task_ids[tid]
                    sfx("done")
                    confirmations.append(color(f"  \u2713 Marked '{t['label']}' as done (+\u20b9{t['value']})", "bright_green"))

            elif action == "UNDONE":
                tid = payload.strip()
                if tid in task_ids:
                    done[tid] = False
                    t = task_ids[tid]
                    confirmations.append(color(f"  \u25cb Unmarked '{t['label']}'", "yellow"))

            elif action == "ADD_TASK":
                parts = payload.split("|")
                if len(parts) >= 3:
                    label = parts[0].strip()
                    area  = parts[1].strip()
                    try:   value = int(parts[2].strip())
                    except ValueError: value = 10
                    custom_list = state.setdefault("custom_tasks", {}).setdefault(tk, [])
                    cid = f"custom_{len(custom_list) + 1}"
                    custom_list.append({"id": cid, "label": label, "area": area, "value": value})
                    confirmations.append(color(f"  \u2726 Added task: '{label}' [{area}] +\u20b9{value}", "magenta"))

            elif action == "ADD_RECURRING":
                parts = payload.split("|")
                if len(parts) >= 4:
                    label = parts[0].strip()
                    area  = parts[1].strip()
                    try:   value = int(parts[2].strip())
                    except ValueError: value = 10
                    days = parts[3].strip().lower()
                    rec_list = state.setdefault("recurring_tasks", [])
                    rid = f"rec_{len(rec_list) + 1}"
                    rec_list.append({"id": rid, "label": label, "area": area, "value": value, "days": days})
                    confirmations.append(color(f"  \u21bb Added recurring: '{label}' [{area}] +\u20b9{value} ({days})", "magenta"))

            elif action == "ADD_QUEST":
                parts = payload.split("|")
                if len(parts) >= 4:
                    title      = parts[0].strip()
                    milestones = [{"label": m.strip(), "done": False} for m in parts[1].split(";")]
                    try:   bonus = int(parts[2].strip())
                    except ValueError: bonus = 50
                    deadline = parts[3].strip()
                    quests = state.setdefault("quests", [])
                    qid = f"quest_{len(quests) + 1}"
                    quests.append({
                        "id": qid, "title": title, "milestones": milestones,
                        "bonus": bonus, "created": today_key(), "deadline": deadline, "status": "active"
                    })
                    sfx("quest")
                    confirmations.append(color(f"  \u2726 Quest created: '{title}' \u2014 {len(milestones)} milestones, +\u20b9{bonus} bonus", "magenta"))

            elif action == "QUEST_DONE":
                parts = payload.split(":")
                if len(parts) == 2:
                    qid = parts[0].strip()
                    try:   midx = int(parts[1].strip())
                    except ValueError: continue
                    for q in state.get("quests", []):
                        if q["id"] == qid and q["status"] == "active":
                            if 0 <= midx < len(q["milestones"]):
                                q["milestones"][midx]["done"] = True
                                sfx("quest")
                                confirmations.append(color(f"  \u2713 Quest '{q['title']}': '{q['milestones'][midx]['label']}' done!", "bright_green"))
                                if all(m["done"] for m in q["milestones"]):
                                    q["status"] = "completed"
                                    state["fund"] = state.get("fund", 0) + q["bonus"]
                                    sfx("lock")
                                    notify("QUEST COMPLETE!", f"{q['title']} \u2014 +\u20b9{q['bonus']} bonus!")
                                    confirmations.append(color(f"  \u2605 QUEST COMPLETE: '{q['title']}' \u2014 +\u20b9{q['bonus']} added!", "bright_green"))
                            break

            elif action == "START_POMODORO":
                try:   minutes = max(1, min(90, int(payload.strip())))
                except ValueError: minutes = 25
                pending_actions.append({"type": "pomodoro", "minutes": minutes})
                confirmations.append(color(f"  \u25cf Starting {minutes}-min Pomodoro...", "bright_green"))

            elif action == "OPEN_APP":
                ok, msg = action_open_app(payload.strip(), wl)
                confirmations.append(color(f"  {'⏻' if ok else '✗'} {msg}", "bright_green" if ok else "red"))

            elif action == "RUN_SCRIPT":
                ok, msg = action_run_script(payload.strip(), wl)
                confirmations.append(color(f"  {'⚙' if ok else '✗'} {msg}", "bright_green" if ok else "red"))

            elif action == "SET_VOLUME":
                ok, msg = action_set_volume(payload.strip(), wl)
                confirmations.append(color(f"  {'🔊' if ok else '✗'} {msg}", "bright_green" if ok else "red"))

            elif action == "LOCK_SCREEN":
                ok, msg = action_lock_screen(wl)
                confirmations.append(color(f"  {'\U0001f512' if ok else '\u2717'} {msg}", "bright_green" if ok else "red"))

            elif action == "RAG_INDEX":
                if _RAG_AVAILABLE:
                    cfg = kriti_rag.rag_load_config()
                    docs_dir = cfg.get("docs_dir", "")
                    host     = state.get("ollama_host",  "http://localhost:11434")
                    emodel   = cfg.get("embed_model", "nomic-embed-text")
                    if not docs_dir or not os.path.isdir(docs_dir):
                        confirmations.append(color("  ✗ RAG: docs_dir not configured — use Settings [8] → RAG", "red"))
                    else:
                        msgs = []
                        try:
                            stats = kriti_rag.rag_index(
                                docs_dir, host, emodel,
                                min_chars=cfg.get("min_chunk_chars", 80),
                                max_chars=cfg.get("max_chunk_chars", 1200),
                                progress_cb=lambda m: msgs.append(m),
                            )
                            confirmations.append(color(
                                f"  ✓ RAG re-indexed: {stats['indexed']} files, "
                                f"{stats['chunks']} chunks (skipped {stats['skipped']})",
                                "bright_green"
                            ))
                        except Exception as e:
                            confirmations.append(color(f"  ✗ RAG index error: {e}", "red"))
                else:
                    confirmations.append(color("  ✗ RAG module not found (kriti_rag.py missing)", "red"))

            elif action == "WEB_SEARCH":
                if _WEBSEARCH_AVAILABLE:
                    query = payload.strip() if payload.strip() else ""
                    if not query:
                        confirmations.append(color("  ✗ WEB_SEARCH needs a query: [[WEB_SEARCH:your query]]", "red"))
                    else:
                        ws_cfg = kriti_websearch.load_config()
                        if not ws_cfg.get("enabled", True):
                            confirmations.append(color("  ✗ Web search is disabled in Settings", "dim"))
                        else:
                            try:
                                results = kriti_websearch.web_search(
                                    query,
                                    max_results      = ws_cfg.get("max_results", 5),
                                    snippet_max_chars = ws_cfg.get("snippet_max_chars", 400),
                                    safe_search      = ws_cfg.get("safe_search", "moderate"),
                                )
                                if results:
                                    confirmations.append(color(
                                        f"  ✓ Web search: {len(results)} result(s) for \"{query[:50]}\"",
                                        "bright_green"
                                    ))
                                    # Store results on state so screen_kriti can inject them
                                    state["_web_results"] = results
                                    state["_web_query"]   = query
                                else:
                                    confirmations.append(color(f"  Web search returned no results for \"{query}\"", "dim"))
                            except Exception as e:
                                confirmations.append(color(f"  ✗ Web search error: {e}", "red"))
                else:
                    confirmations.append(color("  ✗ Web search module not found (kriti_websearch.py missing)", "red"))

            elif action == "SET_PERSONA":
                if _PERSONAS_AVAILABLE:
                    pname = payload.strip().lower()
                    if pname in ("", "none", "off", "clear"):
                        kriti_personas.set_active_persona(None)
                        confirmations.append(color("  ✦ Persona cleared — back to default mode", "magenta"))
                    else:
                        p = kriti_personas.load_persona(pname)
                        if p:
                            kriti_personas.set_active_persona(pname)
                            pdisp = p.get("display_name") or pname
                            confirmations.append(color(f"  ✦ Persona set: {pdisp}", "magenta"))
                        else:
                            available = ", ".join(kriti_personas.list_personas()) or "(none)"
                            confirmations.append(color(
                                f"  ✗ Persona '{pname}' not found. Available: {available}",
                                "red"
                            ))
                else:
                    confirmations.append(color("  ✗ Personas module not found (kriti_personas.py missing)", "red"))

            elif action == "AUTOMATION_RELOAD":
                if _SCHEDULER_AVAILABLE:
                    try:
                        sched = kriti_scheduler.get_scheduler()
                        sched.reload()
                        jobs = sched.running_jobs()
                        confirmations.append(color(
                            f"  ✓ Automations reloaded — {len(jobs)} job(s): {', '.join(jobs) or '(none)'}",
                            "bright_green"
                        ))
                    except Exception as e:
                        confirmations.append(color(f"  ✗ Automation reload error: {e}", "red"))
                else:
                    confirmations.append(color("  ✗ Scheduler module not found", "red"))

    if confirmations:
        save_state(state)

    clean = STRIP_RE.sub('', text).strip()
    return clean, confirmations, pending_actions

def screen_kriti(state):
    """Persistent chat session with Kriti — streams responses, optional voice I/O."""
    global VOICE_ENABLED

    host  = state.get("ollama_host",  "http://localhost:11434")
    model = state.get("ollama_model", "gemma4")

    # Bootstrap default personas on first run
    if _PERSONAS_AVAILABLE:
        kriti_personas.bootstrap_default_personas()

    # Inject live context into system prompt
    tk      = today_key()
    done    = state.get("completed", {}).get(tk, {})
    tasks   = get_all_tasks(state, tk)
    earned  = sum(t["value"] for t in tasks if done.get(t["id"]))
    maxv    = sum(t["value"] for t in tasks)
    locked  = state.get("locked_days", {}).get(tk, False)
    fund    = state.get("fund", 0)

    task_lines = []
    for t in tasks:
        status = "DONE" if done.get(t["id"]) else "PENDING"
        task_lines.append(f"  - id={t['id']}  [{t['area']}]  +₹{t['value']}  {status}  \"{t['label']}\"")

    # Quest context
    quest_lines = []
    for q in state.get("quests", []):
        if q["status"] == "active":
            done_count = sum(1 for m in q["milestones"] if m["done"])
            total_m = len(q["milestones"])
            quest_lines.append(f"  - id={q['id']}  \"{q['title']}\"  {done_count}/{total_m} milestones  bonus=₹{q['bonus']}  deadline={q.get('deadline','')}")
            for mi, m in enumerate(q["milestones"]):
                mstatus = "DONE" if m["done"] else "TODO"
                quest_lines.append(f"    milestone[{mi}]: {mstatus} \"{m['label']}\"")

    streak = _calc_streak(state)

    # Time awareness
    now = datetime.datetime.now()
    now_str = now.strftime("%H:%M")
    # Time until 1am sleep deadline
    sleep_deadline = now.replace(hour=1, minute=0, second=0, microsecond=0)
    if now.hour >= 1:
        sleep_deadline += datetime.timedelta(days=1)
    mins_left = int((sleep_deadline - now).total_seconds() / 60)
    hrs_left = mins_left // 60
    mins_rem = mins_left % 60
    time_left_str = f"{hrs_left}h {mins_rem}m"

    live_ctx = f"""
LIVE STATUS ({today_key()}):
- Current time: {now_str}  |  Time until 1am sleep deadline: {time_left_str}
- Fund: ₹{fund:,}  |  Streak: {streak} days
- Today earned: ₹{earned}/₹{maxv}  |  Day locked: {locked}
- Tasks:
{chr(10).join(task_lines)}
"""
    if quest_lines:
        live_ctx += "- Active Quests:\n" + chr(10).join(quest_lines) + "\n"

    # System perception — read-only snapshot of the machine
    sys_status = get_system_status()
    live_ctx += "\nMACHINE STATUS:\n" + format_system_status(sys_status) + "\n"

    # RAG config loaded once per session (used in the per-turn retrieval below)
    _rag_cfg   = kriti_rag.rag_load_config() if _RAG_AVAILABLE else {}
    _rag_ready = (
        _RAG_AVAILABLE
        and bool(_rag_cfg.get("docs_dir"))
        and os.path.exists(kriti_rag.RAG_DB_PATH)
    )

    # Whitelist — the ONLY apps/scripts Kriti is allowed to trigger
    wl = load_whitelist()
    wl_apps    = whitelisted_app_names(wl)
    wl_scripts = whitelisted_script_names(wl)
    live_ctx += "\nWHITELIST (only these may be opened/run — nothing else, ever):\n"
    live_ctx += f"- Apps: {', '.join(wl_apps) if wl_apps else '(none configured)'}\n"
    live_ctx += f"- Scripts: {', '.join(wl_scripts) if wl_scripts else '(none configured)'}\n"

    # ── Persona — compose system prompt and scope RAG ──────────────────────
    _persona      = kriti_personas.get_active_persona() if _PERSONAS_AVAILABLE else None
    _persona_dirs = kriti_personas.persona_knowledge_dirs(_persona) if _PERSONAS_AVAILABLE else None
    _system_prompt = (
        kriti_personas.compose_system_prompt(KRITI_CONTEXT, _persona)
        if _PERSONAS_AVAILABLE else KRITI_CONTEXT
    )

    # Inject persona status into live_ctx (model can see which persona is active)
    if _PERSONAS_AVAILABLE:
        if _persona:
            from kriti_personas import expand_allowed_actions, ALL_KRITI_ACTIONS
            acts = expand_allowed_actions(_persona.get("allowed_actions", ["*"]))
            is_all = acts == set(ALL_KRITI_ACTIONS)
            act_str = "all" if is_all else ", ".join(sorted(acts))
            pdisp = _persona.get("display_name") or _persona.get("name", "?")
            dirs  = _persona.get("knowledge_dirs", [])
            dir_str = "(full index)" if not dirs else ", ".join(dirs)
            live_ctx += (
                f"\nACTIVE PERSONA: {pdisp}\n"
                f"- Allowed actions: {act_str}\n"
                f"- Knowledge scope: {dir_str}\n"
                f"- Available personas: {', '.join(kriti_personas.list_personas())}\n"
            )
        else:
            live_ctx += (
                f"\nACTIVE PERSONA: (none — full access mode)\n"
                f"- Available personas: {', '.join(kriti_personas.list_personas())}\n"
            )

    # Load chat history for memory persistence
    past_messages = _load_chat()
    messages = [{"role": "system", "content": _system_prompt + live_ctx}]
    if past_messages:
        # Re-inject past exchanges (skip old system messages)
        for m in past_messages:
            if m["role"] in ("user", "assistant"):
                messages.append(m)

    # Check mic availability once
    mic_available = False
    try:
        import speech_recognition as sr
        import pyaudio  # noqa: just checking availability
        mic_available = True
    except ImportError:
        pass

    def voice_status():
        if not mic_available:
            tips = {
                "Darwin":  "pip install pyaudio SpeechRecognition  # macOS: brew install portaudio first",
                "Windows": "pip install pyaudio SpeechRecognition  # no extra deps needed",
            }
            tip = tips.get(_PLATFORM, "pip install pyaudio SpeechRecognition")
            return color(f"  [mic unavailable — {tip}]", "red")
        state_str = color("ON  [v] to toggle", "bright_green") if VOICE_ENABLED else color("OFF [v] to toggle", "dim")
        return color("  voice ", "dim") + state_str

    clr()
    print(color("─" * 50, "dim"))
    _persona_label = ""
    if _persona:
        pdisp = _persona.get("display_name") or _persona.get("name", "?")
        _persona_label = color(f"  [{pdisp}]", "yellow")
    print(color("  KRITI", "magenta") + color("  ·  your AI", "bold") + color(f"  [{model}]", "dim") + _persona_label)
    print(color(f"  ₹{fund:,} in fund  ·  ₹{earned}/{maxv} today", "dim"))
    print(color("─" * 50, "dim"))
    print(voice_status())
    print(color("  [v] voice  [c] clear history  [q] back  or just type", "dim"))
    print(color("  /persona <name|clear>  to switch persona", "dim") + "\n")

    # Greet on entry
    if past_messages:
        greet = f"Hey, you're back. Fund's at ₹{fund:,} and you've earned ₹{earned} today. I remember where we left off — what are we working on?"
    else:
        greet = f"Hey Tanish! Fund's sitting at ₹{fund:,} and you've earned ₹{earned} today. Talk to me — what do you need?"
    print(color("  kriti › ", "magenta") + color(greet, "bold"))
    tts = speak(greet)
    messages.append({"role": "assistant", "content": greet})
    if tts:
        tts.join()  # wait for speech to finish before listening
    print()

    while True:
        # Input prompt
        if VOICE_ENABLED and mic_available:
            print(color("  you  › ", "cyan") + color("🎙  listening...", "dim"), end="\r", flush=True)
            user_input = listen_mic()
            if user_input is None:
                # Real mic failure — disable voice and fall back
                print(color("  you  › ", "cyan") + color("[mic unavailable — switching to keyboard] ", "red"))
                VOICE_ENABLED = False
                try:
                    user_input = input(color("  you  › ", "cyan")).strip()
                except (EOFError, KeyboardInterrupt):
                    break
            elif user_input == "":
                # Timeout or inaudible — silently fall back to typing this once
                print(color("  you  › ", "cyan") + color("[no speech detected] ", "dim"), end="", flush=True)
                try:
                    user_input = input("").strip()
                except (EOFError, KeyboardInterrupt):
                    break
            else:
                # Echo what was heard
                print(color("  you  › ", "cyan") + color(user_input, "bold") + "          ")
        else:
            try:
                user_input = input(color("  you  › ", "cyan")).strip()
            except (EOFError, KeyboardInterrupt):
                break

        if not user_input:
            continue

        # Commands
        if user_input.lower() in ("q", "quit", "exit", "back"):
            # Save chat on exit
            _save_chat([m for m in messages if m["role"] in ("user", "assistant")])
            break
        if user_input.lower() == "c":
            messages = [{"role": "system", "content": _system_prompt + live_ctx}]
            _save_chat([])
            print(color("  ✦ Chat history cleared.", "magenta"))
            print()
            continue

        # /persona command — explicit persona selection from chat
        if user_input.lower().startswith("/persona"):
            parts = user_input.split(None, 1)
            arg   = parts[1].strip().lower() if len(parts) > 1 else ""
            if _PERSONAS_AVAILABLE:
                if arg in ("", "clear", "none", "off"):
                    kriti_personas.set_active_persona(None)
                    _persona      = None
                    _persona_dirs = None
                    _system_prompt = KRITI_CONTEXT
                    messages[0]   = {"role": "system", "content": _system_prompt + live_ctx}
                    print(color("  ✦ Persona cleared.", "magenta"))
                elif arg == "list":
                    names = kriti_personas.list_personas()
                    if names:
                        for n in names:
                            p = kriti_personas.load_persona(n)
                            marker = color(" ◀ active", "yellow") if n == kriti_personas.get_active_persona_name() else ""
                            print(color(f"  {kriti_personas.persona_summary(p)}", "dim") + marker)
                    else:
                        print(color("  No personas found in ~/.life_missions/personas/", "dim"))
                else:
                    p = kriti_personas.load_persona(arg)
                    if p:
                        kriti_personas.set_active_persona(arg)
                        _persona      = p
                        _persona_dirs = kriti_personas.persona_knowledge_dirs(p)
                        _system_prompt = kriti_personas.compose_system_prompt(KRITI_CONTEXT, p)
                        messages[0]   = {"role": "system", "content": _system_prompt + live_ctx}
                        pdisp = p.get("display_name") or arg
                        print(color(f"  ✦ Switched to persona: {pdisp}", "magenta"))
                    else:
                        available = ", ".join(kriti_personas.list_personas()) or "(none)"
                        print(color(f"  ✗ Persona '{arg}' not found. Available: {available}", "red"))
            else:
                print(color("  ✗ Personas module not available (kriti_personas.py missing)", "red"))
            print()
            continue

        if user_input.lower() == "v":
            if not mic_available:
                tips = {
                    "Darwin":  "pip install pyaudio SpeechRecognition  # macOS: brew install portaudio first",
                    "Windows": "pip install pyaudio SpeechRecognition  # no extra deps needed",
                }
                tip = tips.get(_PLATFORM, "pip install pyaudio SpeechRecognition")
                print(color(f"  Install pyaudio first: {tip}", "red"))
            else:
                VOICE_ENABLED = not VOICE_ENABLED
                status = "ON" if VOICE_ENABLED else "OFF"
                msg = f"Voice {status}."
                print(color(f"  ✦ {msg}", "magenta"))
                speak(msg)
            print()
            continue

        # ── RAG retrieval — inject relevant notes before each Ollama call ──────
        # Infer persona from message if none is explicitly set
        if _PERSONAS_AVAILABLE and _persona is None:
            inferred = kriti_personas.infer_persona(user_input)
            if inferred:
                _persona_dirs  = kriti_personas.persona_knowledge_dirs(inferred)
                # Don't persist inferred persona — only affects this turn's RAG scope

        if _rag_ready:
            try:
                rag_host   = state.get("ollama_host", "http://localhost:11434")
                rag_emodel = _rag_cfg.get("embed_model", "nomic-embed-text")
                rag_top_k  = _rag_cfg.get("top_k", 5)
                rag_chunks = kriti_rag.rag_retrieve(
                    user_input, rag_top_k, rag_host, rag_emodel,
                    allowed_dirs=_persona_dirs,
                )
                if rag_chunks:
                    rag_block = (
                        "\nRELEVANT NOTES FROM YOUR INDEXED DOCS "
                        "(cite the source file when referencing these):\n"
                        + kriti_rag.rag_format_context(rag_chunks, _rag_cfg.get("docs_dir", ""))
                        + "\n"
                    )
                    # Re-build system message with fresh RAG context for this turn
                    messages[0] = {
                        "role":    "system",
                        "content": KRITI_CONTEXT + live_ctx + rag_block,
                    }
            except Exception:
                pass  # RAG errors never block the conversation

        # ── Web search grounding — inject live results when relevant ─────────
        if _WEBSEARCH_AVAILABLE:
            try:
                _ws_cfg     = kriti_websearch.load_config()
                _ws_persona = _persona if _PERSONAS_AVAILABLE else None

                # Pick up explicit results stored by [[WEB_SEARCH:query]] action tag
                _explicit_results = state.pop("_web_results", None)
                _explicit_query   = state.pop("_web_query", "")

                # Auto-trigger: recency keywords + persona allows + global enabled
                _auto_results = None
                if (not _explicit_results and
                        kriti_websearch.should_search(user_input, _ws_cfg, _ws_persona)):
                    _allowed_domains = (
                        kriti_websearch.persona_allowed_domains(_ws_persona)
                        if _ws_persona else []
                    )
                    _auto_results = kriti_websearch.web_search(
                        user_input,
                        max_results       = _ws_cfg.get("max_results", 5),
                        snippet_max_chars = _ws_cfg.get("snippet_max_chars", 400),
                        safe_search       = _ws_cfg.get("safe_search", "moderate"),
                        allowed_domains   = _allowed_domains or None,
                    )

                _ws_results = _explicit_results or _auto_results
                if _ws_results:
                    _ws_block = (
                        "\nWEB SEARCH RESULTS (live — cite [W1], [W2] etc.):\n"
                        + kriti_websearch.format_web_results(_ws_results)
                        + "\n"
                    )
                    # Merge with existing system message content
                    _existing = messages[0]["content"]
                    messages[0] = {
                        "role":    "system",
                        "content": _existing + _ws_block,
                    }
            except Exception:
                pass  # web search errors never block the conversation

        messages.append({"role": "user", "content": user_input})

        # Stream Kriti's reply
        print(color("\n  kriti › ", "magenta"), end="", flush=True)
        try:
            # For voice mode: speak sentence-by-sentence as tokens arrive
            sentence_tts_thread = None
            if VOICE_ENABLED:
                def _on_sentence(sentence):
                    nonlocal sentence_tts_thread
                    # Clean action tags from spoken text
                    clean_s = re.sub(r'\[\[[A-Z_]+:[^\]]+\]\]', '', sentence).strip()
                    if clean_s:
                        # Wait for previous sentence to finish (if still speaking)
                        if sentence_tts_thread and sentence_tts_thread.is_alive():
                            sentence_tts_thread.join()
                        sentence_tts_thread = speak(clean_s)
                reply = call_kriti_stream(messages, host, model, on_sentence=_on_sentence)
            else:
                reply = call_kriti_stream(messages, host, model)

            clean_reply, actions, pending = parse_kriti_actions(reply, state)
            messages.append({"role": "assistant", "content": clean_reply})
            if actions:
                print()
                for a in actions:
                    print(a)

            # Wait for last sentence's TTS to finish
            if sentence_tts_thread and sentence_tts_thread.is_alive():
                sentence_tts_thread.join()

            # Execute deferred actions (e.g. pomodoro)
            for pa in pending:
                if pa["type"] == "pomodoro":
                    _run_pomodoro_session(pa["minutes"], state)

        except requests.exceptions.ConnectionError:
            err = "Can't reach Ollama. Run: OLLAMA_ORIGINS=* ollama serve"
            print(color(err, "red"))
        except Exception as e:
            print(color(f"Error: {e}", "red"))
        print()

    clr()


def _show_analytics(state, hist):
    clr()
    print(color("─" * 50, "dim"))
    print(color("  ANALYTICS", "bold"))
    print()

    all_days = sorted(hist.items())
    if not all_days:
        print(color("  No data yet.", "dim"))
        pause()
        return

    # Streak
    streak = _calc_streak(state)
    print(color(f"  Current streak: {streak} day{'s' if streak != 1 else ''} 🔥", "bright_green" if streak >= 3 else "yellow"))

    # Totals
    total = sum(d["earned"] for _, d in all_days)
    avg   = total // len(all_days)
    best_date, best_day = max(all_days, key=lambda x: x[1]["earned"])
    best_dt = datetime.date.fromisoformat(best_date).strftime("%a %d %b")
    print(color(f"  Total earned: ₹{total:,}  ·  avg ₹{avg}/day  ·  {len(all_days)} days tracked", "yellow"))
    print(color(f"  Best day: {best_dt} — ₹{best_day['earned']}", "dim"))
    print()

    # Area breakdown
    area_totals = {}
    for _, day in all_days:
        for t in day.get("tasks", []):
            if t.get("done"):
                area = t.get("area", "Other")
                area_totals[area] = area_totals.get(area, 0) + t["value"]

    if area_totals:
        print(color("  Earnings by area:", "bold"))
        max_val = max(area_totals.values())
        for area, val in sorted(area_totals.items(), key=lambda x: -x[1]):
            c   = AREA_COLOR_MAP.get(area, "dim")
            bar_len = max(1, int(val / max_val * 24))
            bar = color("█" * bar_len, c) + color("░" * (24 - bar_len), "dim")
            pct = int(val / total * 100) if total else 0
            print(f"  {color(f'{area:<10}', c)} [{bar}] ₹{val:,} ({pct}%)")
        print()

    # Last 7 days mini chart
    print(color("  Last 7 days:", "bold"))
    today = datetime.date.today()
    for i in range(6, -1, -1):
        d   = today - datetime.timedelta(days=i)
        key = d.isoformat()
        day = hist.get(key)
        dow = d.strftime("%a")
        if day:
            earned = day["earned"]
            bar_len = min(20, int(earned / 5))
            bar = color("█" * bar_len, "bright_green")
            print(f"  {color(dow, 'dim')}  {bar}  ₹{earned}")
        else:
            print(f"  {color(dow, 'dim')}  {color('—', 'dim')}  missed")
    print()
    pause()


def screen_custom_tasks(state):
    """Manage recurring custom tasks."""
    while True:
        clr()
        header(state)
        print(color("  RECURRING TASKS", "bold"))
        print()

        rec = state.get("recurring_tasks", [])
        if not rec:
            print(color("  No recurring tasks yet. Ask Kriti to add one!", "dim"))
            print(color('  e.g. "add a daily task to read 20 pages"', "dim"))
        else:
            for i, rt in enumerate(rec):
                c   = AREA_COLOR_MAP.get(rt["area"], "dim")
                tag = color(f"[{rt['area']}]", c)
                day_str = rt.get("days", "daily")
                print(f"  {color(f'[{i+1}]', 'dim')} {color(rt['label'], 'bold')}  {tag}  "
                      f"{color('+₹' + str(rt['value']), 'bright_green')}  {color(day_str, 'dim')}")
        print()
        print(color("  [1-N] Delete  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch.isdigit():
            idx = int(ch) - 1
            rec = state.get("recurring_tasks", [])
            if 0 <= idx < len(rec):
                removed = rec.pop(idx)
                state["recurring_tasks"] = rec
                save_state(state)
                print(color(f"\n  Removed: '{removed['label']}'", "yellow"))
                pause()


def screen_quests(state):
    """View and manage multi-day quests."""
    while True:
        clr()
        header(state)
        quests = state.get("quests", [])
        print(color("  QUESTS", "bold"))
        print()

        active   = [q for q in quests if q["status"] == "active"]
        complete = [q for q in quests if q["status"] == "completed"]

        if not quests:
            print(color('  No quests yet. Tell Kriti to create one!', "dim"))
            print(color('  e.g. "create a quest to ship Prier v2"', "dim"))
            print()
        else:
            if active:
                print(color("  ACTIVE", "yellow"))
                for q in active:
                    done_m = sum(1 for m in q["milestones"] if m["done"])
                    total_m = len(q["milestones"])
                    pct = done_m / total_m if total_m else 0
                    bar_len = int(pct * 20)
                    bar = color("█" * bar_len, "bright_green") + color("░" * (20 - bar_len), "dim")
                    days_left = ""
                    if q.get("deadline"):
                        try:
                            dl = datetime.date.fromisoformat(q["deadline"])
                            delta = (dl - datetime.date.today()).days
                            days_left = color(f"  {delta}d left", "yellow" if delta > 3 else "red")
                        except ValueError:
                            pass
                    print(f"  {color(q['id'], 'dim')} {color(q['title'], 'bold')}  +₹{q['bonus']} bonus{days_left}")
                    print(f"    [{bar}] {done_m}/{total_m} milestones")
                    for mi, m in enumerate(q["milestones"]):
                        tick = color("✓", "bright_green") if m["done"] else color("○", "dim")
                        print(f"    {tick} [{mi}] {color(m['label'], 'dim' if m['done'] else 'bold')}")
                    print()
            if complete:
                print(color("  COMPLETED", "bright_green"))
                for q in complete:
                    print(f"  {color('★', 'bright_green')} {color(q['title'], 'dim')}  +₹{q['bonus']}")
                print()

        print(color("  [q] Back", "dim"))
        print(color("  Tip: ask Kriti to create quests or mark milestones", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()
        if ch == "q":
            break


def _run_pomodoro_session(minutes, state):
    """Run a single Pomodoro work session inline (called by Kriti via [[START_POMODORO:N]])."""
    tk = today_key()
    total_secs = minutes * 60
    start = time.time()
    print(color(f"\n  ● POMODORO  {minutes}min  —  Ctrl+C to cancel\n", "bright_green"))
    interrupted = False
    try:
        while True:
            elapsed   = int(time.time() - start)
            remaining = total_secs - elapsed
            if remaining <= 0:
                break
            mins, secs = divmod(remaining, 60)
            bar_done = int((elapsed / total_secs) * 30)
            bar = color("█" * bar_done, "bright_green") + color("░" * (30 - bar_done), "dim")
            print(f"\r  [{bar}]  {mins:02d}:{secs:02d}  ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True

    print()
    if not interrupted:
        sfx("pomodoro")
        notify("Pomodoro done!", f"{minutes}min session complete.")
        print(color(f"\n  ✓ {minutes}min session done!", "bright_green"))
        # Offer to mark study task
        done = state.setdefault("completed", {}).setdefault(tk, {})
        if not done.get("study"):
            yn = prompt("Mark study task as done? (y/n)", "y")
            if yn and yn.lower() == "y":
                done["study"] = True
                save_state(state)
                sfx("done")
                print(color("  ✓ Study task marked!", "bright_green"))
    else:
        print(color("  Session cancelled.", "dim"))
    print()


def screen_pomodoro(state):
    """Pomodoro timer with auto-mark of study task on completion."""
    WORK_MIN  = 25
    BREAK_MIN = 5
    sessions  = 0
    tk = today_key()

    while True:
        clr()
        header(state)
        print(color("  POMODORO", "bold"))
        print(color(f"  {WORK_MIN}min work / {BREAK_MIN}min break  ·  {sessions} sessions today", "dim"))
        print()
        print(color("  [s] Start  [c] Config  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "c":
            try:
                w = int(prompt("Work minutes", str(WORK_MIN)))
                b = int(prompt("Break minutes", str(BREAK_MIN)))
                if 1 <= w <= 90: WORK_MIN = w
                if 1 <= b <= 30: BREAK_MIN = b
            except (ValueError, TypeError):
                pass
        elif ch == "s":
            # Work phase
            total_secs = WORK_MIN * 60
            start = time.time()
            interrupted = False
            try:
                while True:
                    elapsed = int(time.time() - start)
                    remaining = total_secs - elapsed
                    if remaining <= 0:
                        break
                    mins, secs = divmod(remaining, 60)
                    bar_done = int((elapsed / total_secs) * 30)
                    bar = color("█" * bar_done, "bright_green") + color("░" * (30 - bar_done), "dim")
                    print(f"\r  {color('● FOCUS', 'bright_green')}  [{bar}]  {mins:02d}:{secs:02d}  ", end="", flush=True)
                    time.sleep(1)
            except KeyboardInterrupt:
                interrupted = True

            print()
            if not interrupted:
                sessions += 1
                sfx("pomodoro")
                notify("Pomodoro done!", f"Session {sessions} complete. Take a {BREAK_MIN}min break.")
                print(color(f"\n  ✓ Session {sessions} done! Take a {BREAK_MIN}min break.", "bright_green"))

                # Offer to mark study task
                done = state.setdefault("completed", {}).setdefault(tk, {})
                if not done.get("study"):
                    yn = prompt("Mark '2hr focused study session' as done? (y/n)", "y")
                    if yn.lower() == "y":
                        done["study"] = True
                        save_state(state)
                        sfx("done")
                        print(color("  ✓ Study task marked!", "bright_green"))

                # Break phase
                print(color(f"  Break starting...", "dim"))
                total_break = BREAK_MIN * 60
                start_break = time.time()
                try:
                    while True:
                        elapsed = int(time.time() - start_break)
                        remaining = total_break - elapsed
                        if remaining <= 0:
                            break
                        mins, secs = divmod(remaining, 60)
                        bar_done = int((elapsed / total_break) * 30)
                        bar = color("█" * bar_done, "cyan") + color("░" * (30 - bar_done), "dim")
                        print(f"\r  {color('○ BREAK', 'cyan')}   [{bar}]  {mins:02d}:{secs:02d}  ", end="", flush=True)
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
                print()
                sfx("done")
                notify("Break over!", "Time to focus again.")
                print(color("  Break done. Ready for the next one?", "dim"))
            else:
                print(color("  Session interrupted.", "dim"))
            pause()


def screen_whitelist(state):
    """Manage which apps/scripts Kriti is allowed to open/run."""
    while True:
        wl = load_whitelist()
        clr()
        header(state)
        print(color("  WHITELIST", "bold"))
        print(color("  Kriti can ONLY open/run what's listed here. Nothing else, ever.", "dim"))
        print()

        idx_map = {}
        i = 1
        print(color("  Apps", "yellow"))
        if not wl.get("apps"):
            print(color("    (none)", "dim"))
        for a in wl.get("apps", []):
            print(f"  {color(f'[{i}]', 'dim')} {a['name']}")
            idx_map[str(i)] = ("app", a)
            i += 1
        print()
        print(color("  Scripts", "yellow"))
        if not wl.get("scripts"):
            print(color("    (none)", "dim"))
        for s in wl.get("scripts", []):
            exists = "✓" if os.path.isfile(s["path"]) else color("missing!", "red")
            print(f"  {color(f'[{i}]', 'dim')} {s['name']}  {color(s['path'], 'dim')}  {exists}")
            idx_map[str(i)] = ("script", s)
            i += 1

        print()
        print(color("  [a] Add app  [s] Add script  [1-N] Remove  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "a":
            name = prompt("Exact app name (e.g. 'Visual Studio Code')", "")
            if name:
                wl.setdefault("apps", []).append({"name": name})
                save_whitelist(wl)
                print(color(f"\n  Added '{name}' to app whitelist.", "bright_green"))
                pause()
        elif ch == "s":
            name = prompt("Script nickname (e.g. 'backup_prier')", "")
            path = prompt("Absolute path to script", "")
            if name and path:
                if not os.path.isfile(path):
                    print(color(f"\n  Warning: '{path}' doesn't exist yet — added anyway.", "yellow"))
                wl.setdefault("scripts", []).append({"name": name, "path": path})
                save_whitelist(wl)
                print(color(f"\n  Added '{name}' to script whitelist.", "bright_green"))
                pause()
        elif ch in idx_map:
            kind, item = idx_map[ch]
            yn = prompt(f"Remove '{item['name']}'? (y/n)", "n")
            if yn and yn.lower() == "y":
                if kind == "app":
                    wl["apps"] = [a for a in wl["apps"] if a["name"] != item["name"]]
                else:
                    wl["scripts"] = [s for s in wl["scripts"] if s["name"] != item["name"]]
                save_whitelist(wl)
                print(color(f"\n  Removed.", "yellow"))
                pause()


def screen_system_status(state):
    """Live read-only view of machine state, refreshable."""
    while True:
        clr()
        header(state)
        print(color("  SYSTEM STATUS", "bold"))
        print(color("  (read-only — what Kriti can see)", "dim"))
        print()
        status = get_system_status()
        print(color(format_system_status(status), "dim"))
        print()
        print(color("  [r] Refresh  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()
        if ch == "q":
            break
        # 'r' just loops and refreshes


def screen_rag_settings(state):
    """Configure and manage the local RAG / knowledge index."""
    if not _RAG_AVAILABLE:
        print(color("  kriti_rag.py not found — place it next to kriti.py.", "red"))
        pause()
        return

    while True:
        clr()
        header(state)
        cfg  = kriti_rag.rag_load_config()
        stats = kriti_rag.rag_stats()
        print(color("  RAG / KNOWLEDGE INDEX", "bold"))
        print(color("  Ground Kriti's answers in your own notes & docs.", "dim"))
        print()
        print(color(f"  Docs dir:     {cfg.get('docs_dir') or '(not set)'}", "dim"))
        print(color(f"  Embed model:  {cfg.get('embed_model', 'nomic-embed-text')}", "dim"))
        print(color(f"  Top-K chunks: {cfg.get('top_k', 5)}", "dim"))
        print(color(f"  Index:        {stats['files']} files · {stats['chunks']} chunks", "bright_green" if stats['chunks'] else "dim"))
        print()
        print(color("  [1] Set docs directory", "bold"))
        print(color("  [2] Change embed model", "bold"))
        print(color("  [3] Change top-K", "bold"))
        print(color("  [4] Run incremental re-index", "bold"))
        print(color("  [5] Force full re-index (re-embeds everything)", "bold"))
        print(color("  [6] Clear index", "bold"))
        print(color("  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break

        elif ch == "1":
            d = prompt("Absolute path to docs folder", cfg.get("docs_dir", ""))
            if d:
                d = os.path.expanduser(d)
                if not os.path.isdir(d):
                    print(color(f"\n  Warning: '{d}' doesn't exist yet — saved anyway.", "yellow"))
                cfg["docs_dir"] = d
                kriti_rag.rag_save_config(cfg)
                print(color("\n  Saved.", "bright_green"))
            pause()

        elif ch == "2":
            m = prompt("Embedding model (must be pulled via ollama pull)", cfg.get("embed_model", "nomic-embed-text"))
            if m:
                cfg["embed_model"] = m
                kriti_rag.rag_save_config(cfg)
                print(color("\n  Saved. Run a re-index to apply the new model.", "bright_green"))
            pause()

        elif ch == "3":
            k = prompt("Top-K chunks to inject per query", str(cfg.get("top_k", 5)))
            try:
                cfg["top_k"] = max(1, min(20, int(k)))
                kriti_rag.rag_save_config(cfg)
                print(color("\n  Saved.", "bright_green"))
            except (ValueError, TypeError):
                print(color("\n  Enter a number.", "red"))
            pause()

        elif ch in ("4", "5"):
            docs_dir = cfg.get("docs_dir", "")
            if not docs_dir or not os.path.isdir(docs_dir):
                print(color("\n  Set a docs directory first ([1]).", "red"))
                pause()
                continue
            host    = state.get("ollama_host",  "http://localhost:11434")
            emodel  = cfg.get("embed_model", "nomic-embed-text")
            force   = (ch == "5")
            print(color(f"\n  {'Force re-indexing' if force else 'Incremental re-index'}: {docs_dir}", "dim"))
            print(color(f"  Embed model: {emodel}", "dim"))
            print()
            try:
                stats = kriti_rag.rag_index(
                    docs_dir, host, emodel,
                    min_chars=cfg.get("min_chunk_chars", 80),
                    max_chars=cfg.get("max_chunk_chars", 1200),
                    force=force,
                    progress_cb=lambda m: print(color(m, "dim")),
                )
                print(color(
                    f"\n  Done. {stats['indexed']} files indexed · {stats['chunks']} chunks · "
                    f"{stats['skipped']} skipped · {stats['deleted']} old chunks removed.",
                    "bright_green"
                ))
            except Exception as e:
                print(color(f"\n  Error: {e}", "red"))
                print(color("  Make sure Ollama is running and the embed model is pulled.", "dim"))
            pause()

        elif ch == "6":
            yn = prompt("Clear the entire RAG index? This can't be undone. (y/n)", "n")
            if yn and yn.lower() == "y":
                kriti_rag.rag_clear_index()
                print(color("\n  Index cleared.", "yellow"))
            pause()


def screen_personas(state):
    """Browse and manage Kriti personas from Settings."""
    if not _PERSONAS_AVAILABLE:
        print(color("  kriti_personas.py not found — place it next to kriti.py.", "red"))
        pause()
        return

    kriti_personas.bootstrap_default_personas()

    while True:
        clr()
        header(state)
        print(color("  PERSONAS", "bold"))
        print(color("  Each persona sets tone, knowledge scope, and action permissions.", "dim"))
        print()

        names  = kriti_personas.list_personas()
        active = kriti_personas.get_active_persona_name()

        if not names:
            print(color("  No personas found. Creating defaults...", "dim"))
            kriti_personas.bootstrap_default_personas()
            names = kriti_personas.list_personas()

        idx_map = {}
        for i, n in enumerate(names, 1):
            p = kriti_personas.load_persona(n)
            if not p:
                continue
            is_active = (n == active)
            marker = color(" ◀ ACTIVE", "yellow") if is_active else ""
            pdisp  = p.get("display_name") or n
            dirs   = p.get("knowledge_dirs", [])
            acts   = p.get("allowed_actions", ["*"])
            act_str = "all actions" if "*" in acts else f"{len(acts)} actions"
            dir_str = "full index"  if not dirs else f"{len(dirs)} dir(s)"
            print(f"  {color(f'[{i}]', 'dim')} {color(pdisp, 'bold')}{marker}")
            print(color(f"       {act_str}  ·  {dir_str}  ·  {len(p.get('keywords',[]))} keywords", "dim"))
            idx_map[str(i)] = n
        print()
        print(color("  [1-N] View/edit  [n] New persona  [a] Set active  [c] Clear active  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break

        elif ch == "c":
            kriti_personas.set_active_persona(None)
            print(color("\n  Active persona cleared.", "yellow"))
            pause()

        elif ch == "a":
            names2 = kriti_personas.list_personas()
            for i, n in enumerate(names2, 1):
                print(f"  {color(f'[{i}]', 'dim')} {n}")
            raw = prompt("Enter number to activate", "")
            if raw and raw.isdigit():
                idx2 = int(raw) - 1
                if 0 <= idx2 < len(names2):
                    chosen = names2[idx2]
                    kriti_personas.set_active_persona(chosen)
                    p = kriti_personas.load_persona(chosen)
                    pdisp = (p or {}).get("display_name") or chosen
                    print(color(f"\n  ✓ Active persona set to: {pdisp}", "bright_green"))
            pause()

        elif ch == "n":
            # Create a new blank persona
            nm = prompt("Internal name (no spaces, e.g. 'finance_mode')", "")
            if not nm:
                continue
            nm = nm.strip().lower().replace(" ", "_")
            if kriti_personas.load_persona(nm):
                print(color(f"\n  A persona named '{nm}' already exists.", "yellow"))
                pause()
                continue
            dn  = prompt("Display name", nm.replace("_", " ").title())
            sp  = prompt("System prompt (one line, edit file for full text)", f"You are in {dn} mode.")
            new_p = {
                "name":         nm,
                "display_name": dn,
                "system_prompt": sp,
                "knowledge_dirs":  [],
                "allowed_actions": ["*"],
                "keywords":        [],
            }
            kriti_personas.save_persona(new_p)
            path = os.path.join(kriti_personas.PERSONAS_DIR, f"{nm}.json")
            print(color(f"\n  ✓ Created '{nm}'. Edit {path} for full configuration.", "bright_green"))
            pause()

        elif ch in idx_map:
            pname = idx_map[ch]
            _persona_detail_screen(pname, active)

    clr()


def _persona_detail_screen(pname: str, current_active: str | None):
    """View / edit a single persona's fields."""
    while True:
        clr()
        p = kriti_personas.load_persona(pname)
        if not p:
            print(color(f"  Persona '{pname}' could not be loaded.", "red"))
            pause()
            return

        is_active = (pname == kriti_personas.get_active_persona_name())
        pdisp = p.get("display_name") or pname
        acts  = p.get("allowed_actions", ["*"])
        dirs  = p.get("knowledge_dirs",  [])
        kwds  = p.get("keywords",        [])

        print(color("─" * 50, "dim"))
        print(color(f"  PERSONA: {pdisp}", "bold") + (color("  [ACTIVE]", "yellow") if is_active else ""))
        print()
        print(color("  system_prompt:", "yellow"))
        for line in textwrap.wrap(p.get("system_prompt", ""), 60):
            print(color(f"    {line}", "dim"))
        print()
        print(color(f"  allowed_actions: ", "yellow") + color(
            "all" if "*" in acts else ", ".join(acts), "dim"))
        print(color(f"  knowledge_dirs:  ", "yellow") + color(
            "(full index)" if not dirs else "\n    " + "\n    ".join(dirs), "dim"))
        print(color(f"  keywords:        ", "yellow") + color(
            ", ".join(kwds) if kwds else "(none — not auto-inferred)", "dim"))
        print()
        path = os.path.join(kriti_personas.PERSONAS_DIR, f"{pname}.json")
        print(color(f"  File: {path}", "dim"))
        print()
        print(color("  [1] Edit display name  [2] Edit system prompt  [3] Edit allowed_actions", "bold"))
        print(color("  [4] Edit knowledge_dirs  [5] Edit keywords  [6] Set as active  [d] Delete  [q] Back", "bold"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            return

        elif ch == "1":
            dn = prompt("New display name", p.get("display_name", pname))
            if dn:
                p["display_name"] = dn
                kriti_personas.save_persona(p)
                print(color("\n  Saved.", "bright_green"))
            pause()

        elif ch == "2":
            print(color(f"\n  Current: {p.get('system_prompt','')[:100]}...", "dim"))
            print(color("  (For long prompts, edit the JSON file directly.)", "dim"))
            sp = prompt("New system prompt", "")
            if sp:
                p["system_prompt"] = sp
                kriti_personas.save_persona(p)
                print(color("\n  Saved.", "bright_green"))
            pause()

        elif ch == "3":
            from kriti_personas import ALL_KRITI_ACTIONS
            print(color(f"\n  All available actions: {', '.join(ALL_KRITI_ACTIONS)}", "dim"))
            print(color("  Enter comma-separated action names, or * for all:", "dim"))
            raw = prompt("allowed_actions", "*" if "*" in acts else ", ".join(acts))
            if raw:
                if raw.strip() == "*":
                    p["allowed_actions"] = ["*"]
                else:
                    p["allowed_actions"] = [a.strip().upper() for a in raw.split(",") if a.strip()]
                kriti_personas.save_persona(p)
                print(color("\n  Saved.", "bright_green"))
            pause()

        elif ch == "4":
            print(color("\n  Current dirs: " + (", ".join(dirs) or "(none — full index)"), "dim"))
            print(color("  Enter comma-separated absolute paths, or leave blank for full index:", "dim"))
            raw = prompt("knowledge_dirs", ", ".join(dirs))
            if raw is not None:
                p["knowledge_dirs"] = [d.strip() for d in raw.split(",") if d.strip()] if raw.strip() else []
                kriti_personas.save_persona(p)
                print(color("\n  Saved.", "bright_green"))
            pause()

        elif ch == "5":
            print(color("\n  Enter comma-separated keywords for auto-inference (or blank for none):", "dim"))
            raw = prompt("keywords", ", ".join(kwds))
            if raw is not None:
                p["keywords"] = [k.strip().lower() for k in raw.split(",") if k.strip()] if raw.strip() else []
                kriti_personas.save_persona(p)
                print(color("\n  Saved.", "bright_green"))
            pause()

        elif ch == "6":
            kriti_personas.set_active_persona(pname)
            print(color(f"\n  ✓ '{pdisp}' is now the active persona.", "bright_green"))
            pause()

        elif ch == "d":
            yn = prompt(f"Delete persona '{pname}'? This cannot be undone. (y/n)", "n")
            if yn and yn.lower() == "y":
                if is_active:
                    kriti_personas.set_active_persona(None)
                kriti_personas.delete_persona(pname)
                print(color(f"\n  Deleted '{pname}'.", "yellow"))
                pause()
                return


def screen_websearch_settings(state):
    """View and configure web search grounding settings."""
    if not _WEBSEARCH_AVAILABLE:
        print(color("  kriti_websearch.py not found.", "red"))
        pause()
        return

    while True:
        clr()
        header(state)
        print(color("  WEB SEARCH", "bold"))
        print(color("  Live DuckDuckGo grounding — no API key, privacy-first.", "dim"))
        print()

        cfg = kriti_websearch.load_config()
        enabled    = cfg.get("enabled", True)
        auto       = cfg.get("auto_trigger", True)
        max_res    = cfg.get("max_results", 5)
        snip_chars = cfg.get("snippet_max_chars", 400)
        safe       = cfg.get("safe_search", "moderate")
        rate       = cfg.get("rate_limit_secs", 4.0)

        print(color(f"  Enabled:          ", "yellow") + color("yes" if enabled else "no", "bright_green" if enabled else "dim"))
        print(color(f"  Auto-trigger:     ", "yellow") + color("yes (recency keywords)" if auto else "no", "dim"))
        print(color(f"  Max results:      ", "yellow") + color(str(max_res), "dim"))
        print(color(f"  Snippet max chars:", "yellow") + color(str(snip_chars), "dim"))
        print(color(f"  Safe search:      ", "yellow") + color(safe, "dim"))
        print(color(f"  Rate limit (secs):", "yellow") + color(str(rate), "dim"))
        print()
        print(color("  Persona overrides: set web_search_enabled=false or web_search_domains=[...] per persona.", "dim"))
        print()
        print(color("  [1] Toggle enabled  [2] Toggle auto-trigger  [3] Max results", "bold"))
        print(color("  [4] Snippet length  [5] Safe search  [6] Rate limit  [q] Back", "bold"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "1":
            cfg["enabled"] = not enabled
            kriti_websearch.save_config(cfg)
            state_str = "enabled" if cfg["enabled"] else "disabled"
            print(color(f"\n  Web search {state_str}.", "bright_green"))
            pause()
        elif ch == "2":
            cfg["auto_trigger"] = not auto
            kriti_websearch.save_config(cfg)
            print(color(f"\n  Auto-trigger {'on' if cfg['auto_trigger'] else 'off'}.", "bright_green"))
            pause()
        elif ch == "3":
            raw = prompt("Max results (1-20)", str(max_res))
            try:
                cfg["max_results"] = max(1, min(20, int(raw)))
                kriti_websearch.save_config(cfg)
                print(color(f"\n  Max results set to {cfg['max_results']}.", "bright_green"))
            except ValueError:
                print(color("\n  Invalid number.", "red"))
            pause()
        elif ch == "4":
            raw = prompt("Snippet max chars (100-1000)", str(snip_chars))
            try:
                cfg["snippet_max_chars"] = max(100, min(1000, int(raw)))
                kriti_websearch.save_config(cfg)
                print(color(f"\n  Snippet length set to {cfg['snippet_max_chars']}.", "bright_green"))
            except ValueError:
                print(color("\n  Invalid number.", "red"))
            pause()
        elif ch == "5":
            print(color("\n  Options: on / moderate / off", "dim"))
            raw = prompt("Safe search", safe)
            if raw.lower() in ("on", "moderate", "off"):
                cfg["safe_search"] = raw.lower()
                kriti_websearch.save_config(cfg)
                print(color(f"\n  Safe search set to '{cfg['safe_search']}'.", "bright_green"))
            else:
                print(color("\n  Invalid. Choose: on / moderate / off", "red"))
            pause()
        elif ch == "6":
            raw = prompt("Rate limit seconds (1-30)", str(rate))
            try:
                cfg["rate_limit_secs"] = max(1.0, min(30.0, float(raw)))
                kriti_websearch.save_config(cfg)
                print(color(f"\n  Rate limit set to {cfg['rate_limit_secs']}s.", "bright_green"))
            except ValueError:
                print(color("\n  Invalid number.", "red"))
            pause()

    clr()


def screen_automations(state):
    """View and manage scheduled automations."""
    if not _SCHEDULER_AVAILABLE:
        print(color("  kriti_scheduler.py not found.", "red"))
        pause()
        return

    while True:
        clr()
        header(state)
        print(color("  AUTOMATIONS", "bold"))
        print(color("  Scheduled nudges and actions — run without you asking.", "dim"))
        print()

        autos = kriti_scheduler.load_automations()
        sched = kriti_scheduler.get_scheduler()
        active_jobs = sched.running_jobs()

        if not autos:
            print(color("  No automations configured.", "dim"))
            print(color(f"  Edit: ~/.life_missions/automations.json", "dim"))
        else:
            for i, a in enumerate(autos, 1):
                enabled = a.get("enabled", True)
                aid     = a.get("id", f"auto_{i}")
                desc    = a.get("description", aid)
                persona = a.get("persona", "(none)")
                trig    = a.get("trigger", {})
                ttype   = trig.get("type", "?")
                is_live = aid in active_jobs
                status  = color("LIVE", "bright_green") if is_live else color("OFF ", "dim")
                en_str  = color("enabled", "bright_green") if enabled else color("disabled", "dim")
                print(f"  {color(f'[{i}]', 'dim')} {color(desc, 'bold')}  [{status}]  [{en_str}]")
                print(color(f"       trigger={ttype}  persona={persona}", "dim"))
                print(color(f"       actions={a.get('actions', [])}", "dim"))
                print()

        print(color("  [l] View run log  [r] Reload from disk  [e] Edit automations.json  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "l":
            _screen_automation_log()
        elif ch == "r":
            sched.reload()
            jobs = sched.running_jobs()
            print(color(f"\n  Reloaded. {len(jobs)} job(s) active.", "bright_green"))
            pause()
        elif ch == "e":
            path = kriti_scheduler.AUTOMATIONS_FILE
            print(color(f"\n  Automations file: {path}", "dim"))
            print(color("  Edit it in any text editor, then press [r] to reload.", "dim"))
            if os.path.exists(path) and shutil.which("open"):
                yn = prompt("Open in default editor? (y/n)", "y")
                if yn and yn.lower() == "y":
                    subprocess.Popen(["open", path])
            pause()


def _screen_automation_log():
    """Show recent automation run history."""
    clr()
    print(color("─" * 50, "dim"))
    print(color("  AUTOMATION RUN LOG", "bold"))
    print()

    entries = kriti_scheduler.get_recent_log(30)
    if not entries:
        print(color("  No runs recorded yet.", "dim"))
        pause()
        return

    for e in entries:
        ts      = e.get("ts", "?")
        aid     = e.get("automation_id", "?")
        persona = e.get("persona", "(none)")
        status  = e.get("status", "?")
        fired   = e.get("actions_fired", [])
        blocked = e.get("actions_blocked", [])
        msg     = e.get("message", "")

        status_color = {
            "ok": "bright_green", "blocked": "yellow",
            "error": "red", "skipped": "dim"
        }.get(status, "dim")

        print(color(f"  {ts}  [{aid}]", "dim") + "  " + color(status, status_color))
        if persona:
            print(color(f"    persona: {persona}", "dim"))
        if msg:
            print(color(f"    msg: {msg[:80]}", "dim"))
        if fired:
            print(color(f"    fired:   {', '.join(fired)}", "bright_green"))
        if blocked:
            print(color(f"    blocked: {', '.join(blocked)}", "yellow"))
        if e.get("error"):
            print(color(f"    error:   {e['error'][:120]}", "red"))
        print()

    pause()


def screen_settings(state):
    while True:
        clr()
        header(state)
        print(color("  SETTINGS", "bold"))
        print()
        print(color(f"  Ollama host:  {state.get('ollama_host',  'http://localhost:11434')}", "dim"))
        print(color(f"  Ollama model: {state.get('ollama_model', 'gemma4')}", "dim"))
        if _RAG_AVAILABLE:
            cfg   = kriti_rag.rag_load_config()
            st    = kriti_rag.rag_stats()
            rline = f"{cfg.get('docs_dir') or '(not set)'}  ·  {st['files']} files / {st['chunks']} chunks"
            print(color(f"  RAG index:    {rline}", "dim"))
        if _PERSONAS_AVAILABLE:
            active_pname = kriti_personas.get_active_persona_name()
            pdisp = f" (active: {active_pname})" if active_pname else ""
            print(color(f"  Persona:{pdisp}", "dim"))
        print()
        print(color("  [1] Edit Ollama host/model", "bold"))
        print(color("  [2] Manage whitelist (apps & scripts Kriti can trigger)", "bold"))
        print(color("  [3] View system status", "bold"))
        if _RAG_AVAILABLE:
            print(color("  [4] RAG / Knowledge index", "bold"))
        if _PERSONAS_AVAILABLE:
            active_pname = kriti_personas.get_active_persona_name()
            persona_hint = color(f" (active: {active_pname})", "yellow") if active_pname else ""
            print(color("  [5] Personas", "bold") + persona_hint)
        if _SCHEDULER_AVAILABLE:
            print(color("  [6] Automations", "bold"))
        if _WEBSEARCH_AVAILABLE:
            ws_cfg = kriti_websearch.load_config()
            ws_status = color("on", "bright_green") if ws_cfg.get("enabled") else color("off", "dim")
            print(color("  [7] Web search", "bold") + color(f" ({ws_status})", "dim"))
        print(color("  [q] Back", "dim"))
        print()
        ch = input(color("  > ", "bright_green")).strip().lower()

        if ch == "q":
            break
        elif ch == "1":
            h = prompt("Ollama host", state.get("ollama_host", "http://localhost:11434"))
            m = prompt("Ollama model", state.get("ollama_model", "gemma4"))
            state["ollama_host"]  = h
            state["ollama_model"] = m
            save_state(state)
            print(color("\n  Saved.", "bright_green"))
            pause()
        elif ch == "2":
            screen_whitelist(state)
        elif ch == "3":
            screen_system_status(state)
        elif ch == "4" and _RAG_AVAILABLE:
            screen_rag_settings(state)
        elif ch == "5" and _PERSONAS_AVAILABLE:
            screen_personas(state)
        elif ch == "6" and _SCHEDULER_AVAILABLE:
            screen_automations(state)
        elif ch == "7" and _WEBSEARCH_AVAILABLE:
            screen_websearch_settings(state)


# ── Main menu ─────────────────────────────────────────────────────────────────


def _make_execute_tag_adapter():
    """Thin execute_tag(action, payload, state, wl) for the scheduler background runner."""
    def _execute_tag(action: str, payload: str, state: dict, wl: dict) -> str:
        tk       = today_key()
        done     = state.setdefault("completed", {}).setdefault(tk, {})
        tasks    = get_all_tasks(state, tk)
        task_ids = {t["id"]: t for t in tasks}
        real_wl  = load_whitelist()

        if action == "DONE":
            tid = payload.strip()
            if tid in task_ids:
                done[tid] = True
                t = task_ids[tid]
                return f"Marked '{t['label']}' done"
            return f"Task '{tid}' not found"

        elif action == "UNDONE":
            tid = payload.strip()
            if tid in task_ids:
                done[tid] = False
                return f"Unmarked '{task_ids[tid]['label']}'"
            return f"Task '{tid}' not found"

        elif action == "ADD_TASK":
            parts = payload.split("|")
            if len(parts) >= 3:
                label, area = parts[0].strip(), parts[1].strip()
                try:
                    value = int(parts[2].strip())
                except ValueError:
                    value = 10
                clist = state.setdefault("custom_tasks", {}).setdefault(tk, [])
                cid   = f"custom_{len(clist)+1}"
                clist.append({"id": cid, "label": label, "area": area, "value": value})
                return f"Added task '{label}'"
            return "ADD_TASK: bad payload"

        elif action == "RAG_INDEX":
            if _RAG_AVAILABLE:
                cfg      = kriti_rag.rag_load_config()
                docs_dir = cfg.get("docs_dir", "")
                host     = state.get("ollama_host", "http://localhost:11434")
                emodel   = cfg.get("embed_model", "nomic-embed-text")
                if docs_dir and os.path.isdir(docs_dir):
                    stats = kriti_rag.rag_index(docs_dir, host, emodel)
                    return f"RAG indexed {stats['indexed']} files, {stats['chunks']} chunks"
                return "RAG: docs_dir not configured"
            return "RAG module not available"

        elif action == "SET_VOLUME":
            ok, msg = action_set_volume(payload.strip(), real_wl)
            return msg

        elif action == "LOCK_SCREEN":
            ok, msg = action_lock_screen(real_wl)
            return msg

        return f"[{action}] not handled by scheduler adapter"

    return _execute_tag


def main():
    state = load_state()
    if "wishlist" not in state:
        state["wishlist"] = WISHLIST

    # Start in-process scheduler
    if _SCHEDULER_AVAILABLE:
        sched = kriti_scheduler.get_scheduler()
        sched.configure(
            state_loader         = load_state,
            state_saver          = save_state,
            notify_fn            = notify,
            speak_fn             = speak,
            output_fn            = print,
            persona_gate         = (
                kriti_personas.action_permitted
                if _PERSONAS_AVAILABLE else (lambda a, p: (True, ""))
            ),
            get_persona          = (
                kriti_personas.load_persona
                if _PERSONAS_AVAILABLE else (lambda n: None)
            ),
            execute_tag          = _make_execute_tag_adapter(),
            get_system_status_fn = get_system_status,
        )
        sched.start()

    try:
        while True:
            clr()
            header(state)
            streak = _calc_streak(state)
            streak_str = color(f"  {chr(128293)} {streak}-day streak", "bright_green") if streak > 0 else ""
            if streak_str:
                print(streak_str)
                print()
            print(color("  [1] Missions",  "bold"))
            print(color("  [2] Wishlist",  "bold"))
            print(color("  [3] History",   "bold"))
            print(color("  [4] Quests",    "bold"))
            print(color("  [5] Pomodoro",  "bold"))
            print(color("  [6] My Tasks",  "bold"))
            print(color("  [7] Kriti",     "magenta"))
            print(color("  [8] Settings",  "dim"))
            print(color("  [q] Quit",      "dim"))
            print()
            ch = input(color("  > ", "bright_green")).strip().lower()

            if   ch == "1": screen_missions(state)
            elif ch == "2": screen_wishlist(state)
            elif ch == "3": screen_history(state)
            elif ch == "4": screen_quests(state)
            elif ch == "5": screen_pomodoro(state)
            elif ch == "6": screen_custom_tasks(state)
            elif ch == "7": screen_kriti(state)
            elif ch == "8": screen_settings(state)
            elif ch == "q": break
    finally:
        if _SCHEDULER_AVAILABLE:
            kriti_scheduler.get_scheduler().stop()

    clr()
    print(color("  See you tomorrow.\n", "dim"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(color("\n\n  Ctrl+C -- bye.\n", "dim"))
        sys.exit(0)

