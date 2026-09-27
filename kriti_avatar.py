"""
kriti_avatar.py — Kriti's face in the terminal.

Renders the character art (assets/kriti.png) as truecolor
half-block pixels: each terminal cell is one "▀" whose foreground is the top
pixel and background is the bottom pixel, so a 30-column avatar is 30×(2·rows)
real pixels. Works in any truecolor terminal (Terminal.app on macOS 26+,
iTerm2, kitty, WezTerm, VS Code…) with no image protocol needed; falls back to
the xterm-256 palette otherwise.

Like a HUD, the avatar carries a state ring — idle / listening / thinking /
speaking / alert — drawn as a colored frame with a status label, so you can see
at a glance what she's doing.

Requires Pillow (pip install Pillow). Without it every function degrades to
returning [] and the host prints nothing.
"""

import os

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

AVATAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "kriti.png")

# Crop box (left, top, right, bottom) in source pixels: face, headphones, mug.
# Tuned for the 1408×768 source; scaled proportionally if the image changes size.
_SRC_SIZE = (1408, 768)
_CROP     = (755, 70, 985, 350)

# state -> (ring RGB, label)
STATES = {
    "idle":      ((255, 140, 190), "online"),
    "listening": ((120, 220, 255), "listening"),
    "thinking":  ((200, 160, 255), "thinking"),
    "speaking":  ((170, 240, 120), "speaking"),
    "alert":     ((255, 110, 90),  "alert"),
}

_cache = {}   # (width, variant) -> list[list[(top_rgb, bottom_rgb)]]

# Animation frames are painted onto the source art (so they downsample like
# the rest of her): eyes closed for blinks, mouth open for talking. Boxes are
# in source pixels of the 1408×768 image; strokes are thick on purpose — the
# avatar is drawn ~7× smaller, and thin lines would average away.
VARIANTS = ("base", "blink", "talk")
_SKIN  = (252, 200, 162)
_LASH  = (40, 16, 16)
_EYES  = [(799, 178, 833, 208), (861, 177, 902, 208)]
_MOUTH = (837, 231, 862, 245)


def available() -> bool:
    return _PIL_OK and os.path.exists(AVATAR_PATH)


def _truecolor() -> bool:
    ct = os.environ.get("COLORTERM", "").lower()
    return ct in ("truecolor", "24bit")


def _rgb_to_256(r, g, b) -> int:
    # Nearest in the 6×6×6 cube or the 24-step grayscale ramp.
    if abs(r - g) < 10 and abs(g - b) < 10:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)
    q = lambda v: 0 if v < 48 else 1 if v < 115 else (v - 35) // 40
    return 16 + 36 * q(r) + 6 * q(g) + q(b)


def _fg(rgb, tc):
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m" if tc else f"\x1b[38;5;{_rgb_to_256(r, g, b)}m"


def _bg(rgb, tc):
    r, g, b = rgb
    return f"\x1b[48;2;{r};{g};{b}m" if tc else f"\x1b[48;5;{_rgb_to_256(r, g, b)}m"


_RESET = "\x1b[0m"


def _paint_variant(im, variant, sx, sy):
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    S = lambda box: (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)
    if variant == "blink":
        for box in _EYES:
            l, t, r, b = S(box)
            d.rectangle((l, t, r, b), fill=_SKIN)
            mid = t + (b - t) * 0.62
            # A soft downward arc — the classic closed-eye curve.
            d.arc((l, mid - (b - t) * 0.35, r, mid + (b - t) * 0.25), 20, 160,
                  fill=_LASH, width=max(2, int(6 * sy)))
    elif variant == "talk":
        l, t, r, b = S(_MOUTH)
        d.ellipse((l, t, r, b), fill=(110, 30, 40))
        d.ellipse((l + (r - l) * 0.25, t + (b - t) * 0.5, r - (r - l) * 0.25, b),
                  fill=(225, 110, 120))   # tongue


def _pixels(width: int, variant: str = "base"):
    """Downsampled pixel pairs for `width` columns, cached per (width, variant)."""
    key = (width, variant)
    if key in _cache:
        return _cache[key]
    im = Image.open(AVATAR_PATH).convert("RGB")
    sx, sy = im.width / _SRC_SIZE[0], im.height / _SRC_SIZE[1]
    if variant != "base":
        _paint_variant(im, variant, sx, sy)
    l, t, r, b = _CROP
    im = im.crop((int(l * sx), int(t * sy), int(r * sx), int(b * sy)))
    # Half-block cells are ~square per half, so keep the aspect ratio 1:1 in
    # pixels and round the height to an even number (two pixels per row).
    h = max(2, round(im.height * width / im.width / 2) * 2)
    # BOX keeps pixel-art edges crisper than LANCZOS at these tiny sizes.
    im = im.resize((width, h), Image.BOX)
    px = im.load()
    rows = [[(px[x, y], px[x, y + 1]) for x in range(width)] for y in range(0, h, 2)]
    _cache[key] = rows
    return rows


def render(width: int = 34, state: str = "idle", frame: bool = True,
           variant: str = "base") -> list[str]:
    """
    Return the avatar as a list of printable lines (ANSI-colored).

    Every line has the same visible width: `width`, or `width + 2` with the
    frame. Returns [] when Pillow or the image is missing.
    """
    if not available():
        return []
    tc = _truecolor()
    ring_rgb, label = STATES.get(state, STATES["idle"])
    ring = _fg(ring_rgb, tc)

    body = []
    for row in _pixels(width, variant):
        line = "".join(_fg(top, tc) + _bg(bot, tc) + "▀" for top, bot in row)
        body.append(line + _RESET)

    if not frame:
        return body

    tag = f" KRITI · {label} "
    top_fill = max(0, width - len(tag))
    top = ring + "╭" + tag[:width] + "─" * top_fill + "╮" + _RESET
    bottom = ring + "╰" + "─" * width + "╯" + _RESET
    return [top] + [ring + "│" + _RESET + ln + ring + "│" + _RESET for ln in body] + [bottom]


def visible_width(width: int = 34, frame: bool = True) -> int:
    return width + 2 if frame else width


def side_by_side(avatar_lines: list[str], right_lines: list[str],
                 avatar_width: int, gap: int = 2) -> list[str]:
    """
    Zip the avatar (left) with arbitrary text lines (right). `avatar_width` is
    the avatar's visible width, used to pad rows where the avatar has run out.
    """
    n = max(len(avatar_lines), len(right_lines))
    pad = " " * avatar_width
    out = []
    for i in range(n):
        left = avatar_lines[i] if i < len(avatar_lines) else pad
        right = right_lines[i] if i < len(right_lines) else ""
        out.append(left + " " * gap + right)
    return out


# ── Live HUD ───────────────────────────────────────────────────────────────────
# Pins the avatar + a status panel to the top of the terminal with a DECSTBM
# scroll region, so ordinary print()/input() below keep scrolling underneath
# while the avatar stays put. State changes redraw only the frame; "thinking"
# and "speaking" pulse the frame from a small background thread.
#
# Every HUD write is one sys.stdout.write wrapped in DECSC/DECRC (ESC 7 / ESC 8),
# which saves and restores the cursor *and* colour attributes — so a redraw
# landing between two chunks of a streamed reply, or while you're typing at an
# input() prompt, puts everything back exactly where it was.

import math
import random
import shutil
import sys
import threading
import time

_PULSING = ("thinking", "speaking")
_MIN_WIDTH, _MAX_WIDTH = 16, 34
_MIN_CHAT_ROWS = 10   # rows kept free for the scrolling chat below the HUD
_MIN_PANEL_COLS = 40  # right-hand status panel


def _rows_for_width(width: int) -> int:
    l, t, r, b = _CROP
    h = max(2, round((b - t) * width / (r - l) / 2) * 2)
    return h // 2


def fit_width(cols: int, rows: int):
    """Largest avatar width whose framed pane fits the terminal, or None."""
    for w in range(_MAX_WIDTH, _MIN_WIDTH - 1, -2):
        pane_h = _rows_for_width(w) + 2
        if pane_h + 1 + _MIN_CHAT_ROWS <= rows and w + 4 + _MIN_PANEL_COLS <= cols:
            return w
    return None


class HUD:
    def __init__(self, info_fn, out=None):
        """
        info_fn(max_lines, max_cols) -> list[str]: the status panel's lines,
        already truncated to max_cols visible columns. Called on every full
        redraw, so it can show live values.
        """
        self.info_fn = info_fn
        self.out = out or sys.stdout
        self.state = "idle"
        self.active = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._size = None
        self.width = None
        self.pane_h = 0
        self._variant = "base"   # frame currently on screen: base / blink / talk

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Clear the screen and pin the HUD. False if it doesn't fit/unavailable."""
        if not available() or not self.out.isatty():
            return False
        cols, rows = shutil.get_terminal_size()
        self.width = fit_width(cols, rows)
        if self.width is None:
            return False
        self.active = True
        self._layout(clear=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if not self.active:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        with self._lock:
            self.active = False
            # Drop the scroll region and clear.
            self.out.write("\x1b[r\x1b[2J\x1b[H")
            self.out.flush()

    # ── public updates ───────────────────────────────────────────────────────
    def set_state(self, state: str):
        if state not in STATES:
            state = "idle"
        if state == self.state:
            return   # called per streamed token — don't redraw every time
        self.state = state
        if self.active:
            self._check_resize()
            self._draw_frame(1.0)

    def refresh(self):
        """Redraw the whole pane (avatar + status panel)."""
        if self.active:
            if not self._check_resize():
                self._draw_pane()

    # ── drawing ────────────────────────────────────────────────────────────
    def _layout(self, clear=False):
        cols, rows = shutil.get_terminal_size()
        self._size = (cols, rows)
        self.pane_h = _rows_for_width(self.width) + 2
        with self._lock:
            seq = "\x1b[2J" if clear else ""
            # Scroll region = everything below the pane and its separator line.
            seq += f"\x1b[{self.pane_h + 2};{rows}r"
            seq += f"\x1b[{self.pane_h + 2};1H"
            self.out.write(seq)
            self.out.flush()
        self._draw_pane()

    def _check_resize(self) -> bool:
        """Re-pin after a terminal resize. Returns True if it redrew."""
        cols, rows = shutil.get_terminal_size()
        if (cols, rows) == self._size:
            return False
        w = fit_width(cols, rows)
        if w is None:
            # Too small now — drop the pin but keep the chat usable.
            self._stop.set()
            with self._lock:
                self.active = False
                self.out.write("\x1b[r")
                self.out.flush()
            return True
        self.width = w
        # Clearing is the only reliable option: the old pane/region is gone.
        self._layout(clear=True)
        return True

    def _draw_pane(self):
        cols, _ = self._size
        aw = visible_width(self.width)
        avatar = render(self.width, self.state, variant=self._variant)
        panel_cols = cols - aw - 3
        info = self.info_fn(self.pane_h, panel_cols)[: self.pane_h]
        buf = ["\x1b7\x1b[?25l"]
        for i in range(self.pane_h):
            right = info[i] if i < len(info) else ""
            buf.append(f"\x1b[{i + 1};1H\x1b[2K{avatar[i]}  {right}\x1b[0m")
        sep_rgb = STATES[self.state][0]
        buf.append(f"\x1b[{self.pane_h + 1};1H\x1b[2K"
                   + _fg(tuple(c // 3 for c in sep_rgb), _truecolor())
                   + "─" * cols + _RESET)
        buf.append("\x1b[?25h\x1b8")
        with self._lock:
            if self.active:
                self.out.write("".join(buf))
                self.out.flush()

    def _draw_frame(self, level: float):
        """Redraw only the frame, its colour scaled by `level` (0..1)."""
        rgb, label = STATES[self.state]
        tc = _truecolor()
        ring = _fg(tuple(int(c * level) for c in rgb), tc)
        w = self.width
        tag = f" KRITI · {label} "
        top = "╭" + tag[:w] + "─" * max(0, w - len(tag)) + "╮"
        buf = ["\x1b7\x1b[?25l", f"\x1b[1;1H{ring}{top}"]
        for i in range(2, self.pane_h):
            buf.append(f"\x1b[{i};1H│\x1b[{i};{w + 2}H│")
        buf.append(f"\x1b[{self.pane_h};1H╰{'─' * w}╯{_RESET}\x1b[?25h\x1b8")
        with self._lock:
            if self.active:
                self.out.write("".join(buf))
                self.out.flush()

    def _show_variant(self, variant):
        """Swap the portrait to another frame, redrawing only rows that differ."""
        if variant == self._variant or not self.active:
            return
        old = render(self.width, frame=False, variant=self._variant)
        new = render(self.width, frame=False, variant=variant)
        self._variant = variant
        buf = ["\x1b7\x1b[?25l"]
        for i, (a, b) in enumerate(zip(old, new)):
            if a != b:
                buf.append(f"\x1b[{i + 2};2H{b}")
        buf.append("\x1b[?25h\x1b8")
        with self._lock:
            if self.active:
                self.out.write("".join(buf))
                self.out.flush()

    def _animate(self):
        t0 = time.monotonic()
        was_pulsing = False
        next_blink = time.monotonic() + random.uniform(2.5, 5.5)
        blink_until = 0.0
        next_mouth = 0.0
        mouth_open = False
        while not self._stop.wait(0.12):
            now = time.monotonic()
            # Blink every few seconds; while speaking, flap the mouth at a
            # slightly irregular rhythm so it reads as talking, not a metronome.
            if now >= next_blink:
                blink_until = now + 0.16
                next_blink = now + random.uniform(2.5, 5.5)
            if self.state == "speaking":
                if now >= next_mouth:
                    mouth_open = not mouth_open
                    next_mouth = now + random.uniform(0.12, 0.26)
            else:
                mouth_open = False
            self._show_variant("blink" if now < blink_until else "talk" if mouth_open else "base")
            if self.state in _PULSING:
                # Thinking breathes slowly; speaking flickers faster, like a voice meter.
                hz = 0.8 if self.state == "thinking" else 2.2
                phase = (time.monotonic() - t0) * hz * 2 * math.pi
                self._draw_frame(0.55 + 0.45 * (0.5 + 0.5 * math.sin(phase)))
                was_pulsing = True
            elif was_pulsing:
                self._draw_frame(1.0)
                was_pulsing = False
