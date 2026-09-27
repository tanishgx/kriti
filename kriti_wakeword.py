"""
kriti_wakeword.py — Always-on wake-word listener for Kriti.

Runs a background thread that continuously listens to the mic via
openWakeWord (lightweight ONNX models — runs fine on CPU, no GPU needed,
unlike a full speech model listening continuously). On detection: plays a
sound, captures the spoken query via kriti.py's existing listen_mic(), and
routes it through kriti.py's run_kriti_turn_headless() — the SAME brain,
SAME action tags, SAME whitelist/persona gates as typing into the Kriti
chat screen. Nothing about the safety model changes because the request
arrived by voice instead of by keyboard.

Setup:
    pip install openwakeword pyaudio numpy
    python3 -c "import openwakeword; openwakeword.utils.download_models()"

IMPORTANT — verify the model name:
  The exact bundled model names ship with the openwakeword package itself
  and can vary by version. This module logs every model name it sees
  scores for the first time it runs (look for a
  "wake-word models loaded: ..." line) — check that list and set
  WAKE model_name in Settings to whichever one you actually want as your
  wake phrase. The default guess below ("hey_jarvis") may not match what
  got downloaded on your machine — this is flagged deliberately rather
  than assumed, since getting it wrong just means silence, not a crash.

Known limitation: kriti.py renders with `blessed`, which owns the
terminal. A wake-word reply prints/speaks from a background thread — if
you're mid-screen elsewhere (Settings, Missions...) the reply can visually
interleave with that screen's own output. Works cleanest when idling at
the main menu. This is a voice channel bolted onto an existing TUI, not a
full daemon rewrite — a real "runs as a service, no terminal at all"
version is a separate, bigger project (systemd/Task Scheduler packaging).
"""

import json
import os
import threading
import time

SAVE_DIR = os.path.expanduser("~/.life_missions")
CFG_PATH = os.path.join(SAVE_DIR, "wakeword_config.json")

DEFAULT_CONFIG = {
    "enabled":               False,        # opt-in — off until turned on in Settings
    "model_name":            "hey_jarvis", # VERIFY against your installed models — see docstring
    "threshold":             0.5,
    "cooldown_secs":         3.0,          # ignore re-triggers for this long after firing
    "max_follow_ups":        3,            # additional turns after initial wake (0 = single-shot)
    "followup_timeout_secs": 6,           # seconds of silence before ending follow-up listening
}

RATE          = 16000
CHUNK_SAMPLES = 1280   # ~80ms @ 16kHz — openWakeWord's typical expected frame
                        # size. If detection never fires, check your installed
                        # openwakeword version's expected chunk size and adjust.

_OWW_AVAILABLE = False
try:
    from openwakeword.model import Model as _OWWModel
    _OWW_AVAILABLE = True
except ImportError:
    pass

_PYAUDIO_AVAILABLE = False
try:
    import pyaudio
    _PYAUDIO_AVAILABLE = True
except ImportError:
    pass

_NUMPY_AVAILABLE = False
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    pass


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    os.makedirs(SAVE_DIR, exist_ok=True)
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH) as f:
                cfg = json.load(f)
            changed = False
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
                    changed = True
            if changed:
                save_config(cfg)
            return cfg
        except (json.JSONDecodeError, ValueError):
            pass
    save_config(dict(DEFAULT_CONFIG))
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    os.makedirs(SAVE_DIR, exist_ok=True)
    with open(CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def available() -> bool:
    """True if every dependency needed to actually run is installed."""
    return _OWW_AVAILABLE and _PYAUDIO_AVAILABLE and _NUMPY_AVAILABLE


def missing_deps() -> list[str]:
    missing = []
    if not _OWW_AVAILABLE:
        missing.append("openwakeword")
    if not _PYAUDIO_AVAILABLE:
        missing.append("pyaudio")
    if not _NUMPY_AVAILABLE:
        missing.append("numpy")
    return missing


# ── Listener ──────────────────────────────────────────────────────────────────

class WakeWordListener:
    """Background thread: mic → openWakeWord → on_wake callback."""

    def __init__(self, on_wake, output_fn=print):
        """on_wake: called (in its own thread) with no args when the wake
        phrase fires. output_fn: where status/debug lines go."""
        self.on_wake   = on_wake
        self.output_fn = output_fn
        self._thread   = None
        self._stop     = threading.Event()
        self._logged_models = False

    def start(self) -> bool:
        if not available():
            self.output_fn(f"  ✗ Wake-word needs: pip install {' '.join(missing_deps())}")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        cfg = load_config()
        try:
            oww = _OWWModel()
        except Exception as e:
            self.output_fn(f"  ✗ Wake-word model failed to load: {e}")
            return

        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                              input=True, frames_per_buffer=CHUNK_SAMPLES)
        except Exception as e:
            self.output_fn(f"  ✗ Wake-word mic open failed: {e}")
            pa.terminate()
            return

        last_fire  = 0.0
        target     = cfg.get("model_name", "hey_jarvis")
        threshold  = cfg.get("threshold", 0.5)
        cooldown   = cfg.get("cooldown_secs", 3.0)

        try:
            while not self._stop.is_set():
                try:
                    data = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.1)
                    continue

                audio = np.frombuffer(data, dtype=np.int16)
                try:
                    scores = oww.predict(audio)
                except Exception:
                    continue

                if not self._logged_models:
                    self.output_fn(f"  (wake-word models loaded: {', '.join(scores.keys())})")
                    self._logged_models = True

                score = scores.get(target, 0.0)
                now = time.time()
                if score > threshold and (now - last_fire) > cooldown:
                    last_fire = now
                    threading.Thread(target=self.on_wake, daemon=True).start()
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()


# ── Module-level singleton ────────────────────────────────────────────────────

_listener: "WakeWordListener | None" = None


def start_listener(on_wake, output_fn=print) -> bool:
    """Start the singleton listener if enabled in config. Returns True if
    actually started (False if disabled in config, or deps missing)."""
    global _listener
    cfg = load_config()
    if not cfg.get("enabled", False):
        return False
    if _listener and _listener.is_running():
        return True
    _listener = WakeWordListener(on_wake, output_fn=output_fn)
    return _listener.start()


def stop_listener() -> None:
    global _listener
    if _listener:
        _listener.stop()


def is_listening() -> bool:
    return bool(_listener and _listener.is_running())
