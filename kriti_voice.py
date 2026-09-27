"""
kriti_voice.py — Kriti's voice: text-to-speech (Piper / macOS say / pyttsx3),
speech-to-text (faster-whisper / Google), barge-in, sound effects and
desktop notifications.

VOICE_ENABLED is the chat screen's voice toggle; read and set it as
kriti_voice.VOICE_ENABLED (not a `from` import) so every module sees the change.
"""

import json, os, sys, datetime, textwrap, requests, subprocess, shutil, threading, time, re
import platform

from kriti_ui import color

# ── Voice layer ───────────────────────────────────────────────────────────────
# TTS:  pyttsx3 (cross-platform). pip install pyttsx3
#       macOS also tries `say -v Tara` first (zero deps, better quality).
# STT:  pyaudio + SpeechRecognition.
#         macOS:   pip install pyaudio SpeechRecognition  (macOS: brew install portaudio first)
#         Windows: pip install pyaudio SpeechRecognition  (no brew needed)
#         Linux:   sudo apt install portaudio19-dev && pip install pyaudio SpeechRecognition
# Toggle voice on/off with [v] inside Kriti chat.

_PLATFORM = platform.system()   # "Darwin" | "Windows" | "Linux"

VOICE_ENABLED = False   # toggled at runtime
_whisper_model = None    # cached WhisperModel instance
_tts_stop = threading.Event()   # set → cut off current speech, skip the rest
_tts_proc = None                # the running `say` process, so it can be killed

# TTS settings — set from global state by configure_tts() (Settings › Voice).
#   engine: "auto" (Piper if a voice file is set, else the OS voice) | "piper" | "say"
#   Piper: pip install piper-tts, then download a voice (.onnx + .onnx.json), e.g.
#   https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium
_tts_cfg = {"engine": "auto", "say_voice": "Tara", "piper_model": ""}
_piper_voice = None        # loaded PiperVoice, cached
_piper_error = None        # why Piper couldn't load, shown in Settings
_piper_lock  = threading.Lock()


def configure_tts(state):
    global _piper_voice, _piper_error
    _tts_cfg["engine"]      = state.get("tts_engine", "auto")
    _tts_cfg["say_voice"]   = state.get("tts_say_voice", "Tara")
    _tts_cfg["piper_model"] = os.path.expanduser(state.get("tts_piper_model", ""))
    with _piper_lock:
        _piper_voice, _piper_error = None, None   # reload on next use


def _get_piper():
    """The loaded Piper voice, or None if not configured / unavailable."""
    global _piper_voice, _piper_error
    model = _tts_cfg["piper_model"]
    if _tts_cfg["engine"] == "say" or not model:
        return None
    with _piper_lock:
        if _piper_voice is None and _piper_error is None:
            try:
                from piper import PiperVoice
                if not os.path.exists(model):
                    raise FileNotFoundError(model)
                _piper_voice = PiperVoice.load(model)
            except ImportError:
                _piper_error = "piper-tts not installed (pip install piper-tts)"
            except Exception as e:
                _piper_error = f"couldn't load voice: {e}"
        return _piper_voice


def _play_wav(path):
    """Play a wav through a killable subprocess (so barge-in can cut it off)."""
    global _tts_proc
    if _PLATFORM == "Windows":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
        return
    player = ["afplay", path] if _PLATFORM == "Darwin" else (
        ["paplay", path] if shutil.which("paplay") else ["aplay", "-q", path])
    _tts_proc = subprocess.Popen(player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _tts_proc.wait()
    _tts_proc = None


def _tts_say(text):
    """Speak text. Strips ANSI, blocks until speech finishes.
    Priority: Piper neural voice (if configured) → macOS `say` → pyttsx3 → silent.
    On Windows, pyttsx3 uses SAPI5 voices built into the OS — no extra install.
    """
    import re
    clean = re.sub(r'\x1b\[[0-9;]*m', '', text).strip()
    if not clean or _tts_stop.is_set():
        return
    voice = _get_piper()
    if voice is not None:
        import tempfile, wave as wavemod
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            fname = f.name
        try:
            with wavemod.open(fname, "wb") as wf:
                voice.synthesize_wav(clean, wf)
            if not _tts_stop.is_set():
                _play_wav(fname)
        finally:
            os.unlink(fname)
        return
    # macOS: built-in `say` (zero deps). Default voice Tara (Indian English).
    if _PLATFORM == "Darwin" and shutil.which("say"):
        global _tts_proc
        _tts_proc = subprocess.Popen(["say", "-v", _tts_cfg["say_voice"], "-r", "200", clean],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _tts_proc.wait()
        _tts_proc = None
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
    """Speak text in a background thread. Returns the thread (or None).
    Gated by the TUI's VOICE_ENABLED toggle."""
    if VOICE_ENABLED:
        t = threading.Thread(target=_tts_say, args=(text,), daemon=True)
        t.start()
        return t
    return None

def stop_speaking():
    """Cut Kriti off mid-sentence (barge-in). Queued sentences are dropped."""
    _tts_stop.set()
    p = _tts_proc
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass


class SpeechQueue:
    """Speaks sentences in order on a single worker thread.

    Lets a reply stream to the screen at full speed while speech follows
    behind, and makes the whole reply interruptible via stop_speaking().
    """
    def __init__(self):
        import queue
        _tts_stop.clear()
        self._q = queue.Queue()
        self._pending = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text):
        with self._lock:
            self._pending += 1
        self._q.put(text)

    def busy(self):
        with self._lock:
            return self._pending > 0

    def wait(self):
        while self.busy():
            time.sleep(0.05)

    def close(self):
        self._q.put(None)

    def _run(self):
        while True:
            text = self._q.get()
            if text is None:
                return
            try:
                if not _tts_stop.is_set():
                    _tts_say(text)
            finally:
                with self._lock:
                    self._pending -= 1


class InterruptWatcher:
    """While Kriti is replying, watch for a key press (any key) or — in voice
    mode — the user starting to talk over her. On either, stop_speaking().

    Voice detection is energy-based: calibrate for ~0.3s while she's already
    talking (so her own voice through the speakers sets the baseline), then
    trigger on ~0.4s of sustained sound well above it. Headphones make this
    far more reliable; on laptop speakers raise VOICE_MULT if she cuts herself off.
    """
    VOICE_MULT = 3.0

    def __init__(self, use_mic):
        self.reason = None
        self._done = threading.Event()
        self._threads = [threading.Thread(target=self._watch_keys, daemon=True)]
        if use_mic:
            self._threads.append(threading.Thread(target=self._watch_mic, daemon=True))

    def start(self):
        for t in self._threads:
            t.start()
        return self

    def stop(self):
        self._done.set()
        for t in self._threads:
            t.join(timeout=1)

    def _fire(self, reason):
        if self.reason is None:
            self.reason = reason
            stop_speaking()
        self._done.set()

    def _watch_keys(self):
        try:
            import termios, tty, select
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
        except Exception:
            return   # Windows / not a tty: voice interrupt only
        try:
            tty.setcbreak(fd)
            while not self._done.is_set():
                r, _, _ = select.select([fd], [], [], 0.05)
                if r:
                    os.read(fd, 64)   # swallow the key(s)
                    self._fire("key")
                    return
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _watch_mic(self):
        try:
            import pyaudio, struct, math
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                             input=True, frames_per_buffer=1024)
        except Exception:
            return
        def rms(data):
            n = len(data) // 2
            shorts = struct.unpack(f"{n}h", data)
            return math.sqrt(sum(x * x for x in shorts) / n) if n else 0
        try:
            base = [rms(stream.read(1024, exception_on_overflow=False)) for _ in range(5)]
            threshold = max(300, sum(base) / len(base) * self.VOICE_MULT)
            loud = 0
            while not self._done.is_set():
                level = rms(stream.read(1024, exception_on_overflow=False))
                loud = loud + 1 if level > threshold else 0
                if loud >= 6:   # 6 × 64ms ≈ 0.4s of sustained speech
                    self._fire("voice")
                    return
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()


def speak_always(text):
    """Speak text in a background thread regardless of VOICE_ENABLED. For
    channels that are voice-only by definition — e.g. a wake-word reply.
    You spoke the query; you get a spoken answer, independent of whatever
    the interactive TUI's toggle currently says."""
    t = threading.Thread(target=_tts_say, args=(text,), daemon=True)
    t.start()
    return t

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

