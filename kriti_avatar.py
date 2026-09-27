"""
kriti_avatar.py — Kriti's animated face in the terminal.

Everything is derived from one piece of art (assets/kriti.png) — no sprite
files. Each frame is built in a few milliseconds:

  1. expression  — eyes/mouth/headphones repainted on the full-res art
                   (blink, happy ^^, thinking, worried, two talking mouths,
                   listening glow)
  2. breathing   — her shoulders/chest rise a few source pixels under a soft
                   silhouette mask; head and background stay put
  3. downscale   — "ink-weighted": dark outline pixels (lashes, pupils, face
                   edge) count 3× so they survive the ~5× shrink
  4. overlays    — petals (idle), scan line (thinking), sparkles (happy)
  5. terminal    — truecolor half-blocks: each cell is "▀" with fg = top
                   pixel, bg = bottom pixel; falls back to xterm-256

The HUD pins her above the chat and animates at ~10 fps, redrawing only the
rows that changed.

Requires Pillow and numpy (pip install Pillow numpy). Without them every
function degrades to returning [] and the host prints nothing.
"""

import math
import os
import random
import shutil
import sys
import threading
import time

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False

AVATAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "kriti.png")

# All geometry below is in pixels of the 1408×768 source art; it's scaled if
# the image is swapped for a different size.
_SRC_SIZE = (1408, 768)
_CROP     = (755, 70, 985, 350)       # face, headphones, shoulders

# state -> (ring RGB, label)
STATES = {
    "idle":      ((255, 140, 190), "ONLINE"),
    "listening": ((120, 220, 255), "LISTENING"),
    "thinking":  ((200, 160, 255), "THINKING"),
    "speaking":  ((170, 240, 120), "SPEAKING"),
    "alert":     ((255, 110, 90),  "ALERT"),
    "happy":     ((255, 200, 90),  "YAY"),
}

VARIANTS = ("base", "blink", "happy", "think", "worried", "talk1", "talk2", "listen")

_SKIN, _LASH = (252, 203, 165), (38, 12, 16)
_EYES  = [(804, 178, 832, 206), (864, 178, 900, 206)]
_MOUTH = (833, 229, 866, 243)
_GLOW  = (110, 215, 255)
# Her outline (hair crown → shoulders), used to breathe her without the bookshelf.
_SILHOUETTE = [(755, 350), (760, 320), (780, 295), (790, 275), (795, 255), (780, 235),
               (775, 200), (775, 150), (780, 130), (795, 105), (815, 85), (840, 74),
               (875, 72), (905, 82), (930, 105), (950, 135), (965, 165), (972, 200),
               (972, 240), (985, 250), (985, 352), (755, 352)]

BREATH_PX = 6.0    # peak shoulder lift in source pixels (~1 terminal half-row at 50 cols)


def available() -> bool:
    return _DEPS_OK and os.path.exists(AVATAR_PATH)


# ── colour escapes ─────────────────────────────────────────────────────────────

def _truecolor() -> bool:
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


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
    r, g, b = (int(v) for v in rgb)
    return f"\x1b[38;2;{r};{g};{b}m" if tc else f"\x1b[38;5;{_rgb_to_256(r, g, b)}m"


def _bg(rgb, tc):
    r, g, b = (int(v) for v in rgb)
    return f"\x1b[48;2;{r};{g};{b}m" if tc else f"\x1b[48;5;{_rgb_to_256(r, g, b)}m"


_RESET = "\x1b[0m"


# ── the art: expressions, breathing, downscale ─────────────────────────────────

_art = {}          # variant -> painted full-res PIL image
_mask = None       # soft silhouette mask (float array, full-res)
_px_cache = {}     # (width, variant, breath) -> uint8 array (H, W, 3)


def _scale():
    im = _art["base"]
    return im.width / _SRC_SIZE[0], im.height / _SRC_SIZE[1]


def _S(box):
    sx, sy = _scale()
    return tuple(v * (sx if i % 2 == 0 else sy) for i, v in enumerate(box))


def _paint(variant):
    """Return the full-res art with `variant`'s expression painted on."""
    im = _art["base"].copy()
    d = ImageDraw.Draw(im)
    sx, sy = _scale()
    lw = lambda px: max(2, int(px * sy))
    if variant == "blink":                          # relaxed closed eyes ︶ ︶
        for box in _EYES:
            l, t, r, b = _S(box)
            d.rectangle((l, t, r, b), fill=_SKIN)
            d.arc((l, t + 4 * sy, r, b + 2 * sy), 15, 165, fill=_LASH, width=lw(6))
    elif variant == "happy":                        # ^ ^ and a big smile
        for box in _EYES:
            l, t, r, b = _S(box)
            d.rectangle((l, t, r, b), fill=_SKIN)
            d.arc((l + 2 * sx, t + 6 * sy, r - 2 * sx, b + 22 * sy), 205, 335, fill=_LASH, width=lw(7))
        l, t, r, b = _S(_MOUTH)
        d.rectangle((l, t, r, b), fill=_SKIN)
        d.chord((l + 2 * sx, t - 6 * sy, r - 2 * sx, b + 2 * sy), 20, 160, fill=(150, 45, 55))
        d.chord((l + 9 * sx, t + 4 * sy, r - 9 * sx, b + 2 * sy), 20, 160, fill=(235, 120, 130))
    elif variant == "think":                        # half-lidded, glancing aside — "hmm…"
        for box in _EYES:
            l, t, r, b = (int(v) for v in _S(box))
            mid = int(t + (b - t) * 0.45)
            lower = im.crop((l, mid, r, b))
            d.rectangle((l, t - 1, r, mid), fill=_SKIN)
            d.line([(l, mid), (r, mid - 1)], fill=_LASH, width=lw(6))
            im.paste(lower.transform(lower.size, Image.AFFINE, (1, 0, -3 * sx, 0, 1, 0)),
                     (l, mid + int(3 * sy)))
            d = ImageDraw.Draw(im)
    elif variant == "worried":                      # sweat drop + small frown
        d.rectangle(_S(_MOUTH), fill=_SKIN)
        d.arc(_S((840, 236, 859, 250)), 200, 340, fill=(150, 60, 50), width=lw(4))
        d.polygon([_S((921, 148)), _S((913, 166)), _S((929, 166))], fill=(150, 210, 255))
        d.ellipse(_S((911, 158, 931, 178)), fill=(150, 210, 255))
        d.rectangle(_S((915, 163, 918, 169)), fill=(245, 252, 255))
    elif variant in ("talk1", "talk2"):             # two mouth openings
        l, t, r, b = _S(_MOUTH)
        d.rectangle((l, t, r, b), fill=_SKIN)
        if variant == "talk1":
            d.ellipse((l + 8 * sx, t + 4 * sy, r - 8 * sx, b - 3 * sy), fill=(120, 35, 45))
        else:
            d.ellipse((l + 3 * sx, t + sy, r - 3 * sx, b + sy), fill=(110, 30, 40))
            d.ellipse((l + 10 * sx, t + 7 * sy, r - 10 * sx, b + sy), fill=(230, 115, 125))
    elif variant == "listen":                       # headphones light up
        a = np.asarray(im).astype(float)
        l, t, r, b = (int(v) for v in _S((755, 275, 985, 352)))
        reg = a[t:b, l:r]
        yy, xx = np.mgrid[t:b, l:r]
        cx1, cy1, cx2, cy2 = _S((812, 302, 893, 306))
        cups = (((xx - cx1) / (34 * sx)) ** 2 + ((yy - cy1) / (36 * sy)) ** 2 < 1) | \
               (((xx - cx2) / (44 * sx)) ** 2 + ((yy - cy2) / (38 * sy)) ** 2 < 1)
        lum = reg @ [0.3, 0.59, 0.11]
        accent = cups & (reg[..., 0] > 120) & (reg[..., 2] > 90) & (lum < 170)   # pink rings
        shell = cups & (lum < 70)                                               # dark cups
        reg[accent] = reg[accent] * 0.25 + np.array(_GLOW) * 0.75
        reg[shell] = reg[shell] * 0.78 + np.array(_GLOW) * 0.22
        a[t:b, l:r] = reg
        im = Image.fromarray(a.astype(np.uint8))
    return im


def _load():
    global _mask
    if "base" not in _art:
        _art["base"] = Image.open(AVATAR_PATH).convert("RGB")
        m = Image.new("L", _art["base"].size, 0)
        ImageDraw.Draw(m).polygon([_S(p) for p in _SILHOUETTE], fill=255)
        _mask = np.asarray(m.filter(ImageFilter.GaussianBlur(3))).astype(float) / 255


def _breathe(im, amount):
    """Lift her shoulders/chest by `amount` source px; head and background stay."""
    sx, sy = _scale()
    l, t, r, b = (int(v) for v in _S(_CROP))
    a = np.asarray(im).astype(float)
    if abs(amount) < 0.05:
        return a[t:b, l:r]
    y0, y1 = max(0, t - 12), min(a.shape[0], b + 12)
    ys = np.arange(y0, y1, dtype=float)[:, None]
    # Shoulders/chest rise; the head stays level (fades in from the chin down).
    weight = np.clip((ys - 235 * sy) / (45 * sy), 0, 1)
    dy = amount * sy * weight * _mask[y0:y1, l:r]
    src = np.clip(ys + dy, 0, a.shape[0] - 1)
    lo = np.floor(src).astype(int)
    hi = np.minimum(lo + 1, a.shape[0] - 1)
    f = (src - lo)[..., None]
    xs = np.broadcast_to(np.arange(l, r), lo.shape)
    region = a[lo, xs] * (1 - f) + a[hi, xs] * f
    return region[t - y0: b - y0]


def _ink_resize(a, W, H, weight=3.0, thresh=65):
    """Block-average where dark 'ink' pixels count `weight`×, so outlines survive."""
    w = np.where(a @ [0.3, 0.59, 0.11] < thresh, weight, 1.0)
    ys = np.linspace(0, a.shape[0], H + 1).astype(int)[:-1]
    xs = np.linspace(0, a.shape[1], W + 1).astype(int)[:-1]
    num = np.add.reduceat(np.add.reduceat(a * w[..., None], ys, 0), xs, 1)
    den = np.add.reduceat(np.add.reduceat(w, ys, 0), xs, 1)
    return (num / den[..., None]).clip(0, 255).astype(np.uint8)


def _height_for(width: int) -> int:
    l, t, r, b = _CROP
    return max(2, round((b - t) * width / (r - l) / 2) * 2)


def pixels(width: int, variant: str = "base", breath: float = 0.0):
    """The portrait as an (H, width, 3) uint8 array. Cached per (width, variant, breath)."""
    key = (width, variant, round(breath * 2) / 2)
    if key not in _px_cache:
        _load()
        if variant not in _art:
            _art[variant] = _paint(variant)
        region = _breathe(_art[variant], key[2])
        im = Image.fromarray(region.astype(np.uint8))
        im = ImageEnhance.Color(ImageEnhance.Contrast(im).enhance(1.06)).enhance(1.06)
        _px_cache[key] = _ink_resize(np.asarray(im).astype(float), width, _height_for(width))
    return _px_cache[key]


# ── overlays ───────────────────────────────────────────────────────────────────

_PETAL = [((0, 0), (255, 200, 212), 1.0), ((0, 1), (255, 175, 195), 0.9),
          ((1, 0), (250, 160, 185), 0.8), ((1, 1), (235, 135, 165), 0.55)]


def overlay(px, ring_rgb, scan=None, petals=(), sparkles=()):
    """Draw HUD effects onto a copy of a pixel frame."""
    out = px.astype(float)
    H, W = out.shape[:2]

    def put(y, x, col, a):
        if 0 <= y < H and 0 <= x < W:
            out[y, x] = out[y, x] * (1 - a) + np.asarray(col, float) * a

    if scan is not None:              # bright leading line + fading trail
        tint = np.asarray(ring_rgb, float) * 0.6 + 255 * 0.4
        for k, a in ((0, 0.55), (-1, 0.28), (-2, 0.12)):
            if 0 <= scan + k < H:
                out[scan + k] = out[scan + k] * (1 - a) + tint * a
    for (y, x) in petals:
        for (dy, dx), col, a in _PETAL:
            put(y + dy, x + dx, col, a)
    for (y, x) in sparkles:           # 4-point twinkle
        put(y, x, (255, 245, 200), 1.0)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            put(y + dy, x + dx, (255, 235, 170), 0.5)
    return out.clip(0, 255).astype(np.uint8)


# ── terminal rendering ─────────────────────────────────────────────────────────

def _cells(top_row, bot_row, tc):
    """Half-block cells for one terminal row, emitting colour codes only when they change."""
    parts, last_f, last_b = [], None, None
    for top, bot in zip(top_row.tolist(), bot_row.tolist()):
        if top != last_f:
            parts.append(_fg(top, tc))
            last_f = top
        if bot != last_b:
            parts.append(_bg(bot, tc))
            last_b = bot
        parts.append("▀")
    return "".join(parts) + _RESET


def body_lines(px) -> list[str]:
    """Half-block lines for a whole pixel frame."""
    tc = _truecolor()
    return [_cells(px[y], px[y + 1], tc) for y in range(0, px.shape[0] - 1, 2)]


def diff_spans(old, new, threshold=10):
    """Terminal writes that turn frame `old` into `new`: per row, only the
    stretch of cells whose colour changed visibly (any channel by more than
    `threshold`). Returns (row_index, first_col, last_col_exclusive, text)."""
    tc = _truecolor()
    delta = np.abs(old.astype(np.int16) - new.astype(np.int16)).max(axis=2)
    changed = delta > threshold                              # (H, W) pixel changed
    cell = changed[0::2] | changed[1::2]                     # (rows, W) cell changed
    out = []
    for r in np.nonzero(cell.any(axis=1))[0]:
        cols = np.nonzero(cell[r])[0]
        c0, c1 = int(cols[0]), int(cols[-1]) + 1
        out.append((int(r), c0, c1, _cells(new[2 * r, c0:c1], new[2 * r + 1, c0:c1], tc)))
    return out


def _frame_parts(width, state, level=1.0):
    """(top line, bottom line, [side chars per body row]) for the bracket frame."""
    rgb, label = STATES.get(state, STATES["idle"])
    tc = _truecolor()
    ring = _fg(tuple(c * level for c in rgb), tc)
    dim = _fg(tuple(c * 0.4 * level for c in rgb), tc)
    tag = f" ◈ KRITI · {label} "
    if len(tag) > width - 2:
        tag = f" ◈ {label} "[: max(0, width - 2)]
    top = ring + "┏━" + tag + dim + "─" * max(0, width - 2 - len(tag)) + ring + "━┓" + _RESET
    bottom = ring + "┗━" + dim + "─" * max(0, width - 2) + ring + "━┛" + _RESET
    n = _height_for(width) // 2
    sides = [(ring + "┃" if i < 2 or i >= n - 2 else dim + "│") + _RESET for i in range(n)]
    return top, bottom, sides


def render(width: int = 34, state: str = "idle", frame: bool = True,
           variant: str = "base") -> list[str]:
    """
    A still portrait as printable lines (ANSI-coloured). Every line has the
    same visible width: `width`, or `width + 2` with the frame. Returns []
    when Pillow/numpy or the image is missing.
    """
    if not available():
        return []
    body = body_lines(pixels(width, variant))
    if not frame:
        return body
    top, bottom, sides = _frame_parts(width, state)
    return [top] + [s + ln + s for s, ln in zip(sides, body)] + [bottom]


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
# while the avatar stays put. A background thread animates her at ~10 fps.
#
# Every HUD write is one sys.stdout.write wrapped in DECSC/DECRC (ESC 7 / ESC 8),
# which saves and restores the cursor *and* colour attributes — so a redraw
# landing between two chunks of a streamed reply, or while you're typing at an
# input() prompt, puts everything back exactly where it was.

_MIN_WIDTH, _MAX_WIDTH = 16, 50
_MIN_CHAT_ROWS = 10   # rows kept free for the scrolling chat below the HUD
_MIN_PANEL_COLS = 40  # right-hand status panel
_FPS = 10


def _rows_for_width(width: int) -> int:
    return _height_for(width) // 2


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
        self._lock = threading.Lock()      # guards writes to the terminal
        self._rlock = threading.RLock()    # guards frame state (_shown, timers)
        self._stop = threading.Event()
        self._thread = None
        self._size = None
        self.width = None
        self.pane_h = 0
        self._shown = None                 # pixel frame currently on screen
        self._frame_key = None             # (state, level) of the frame on screen
        self._t0 = time.monotonic()
        self._state_since = self._t0
        self._happy_until = 0.0
        self._next_blink = self._t0 + random.uniform(2.5, 5.5)
        self._blink_until = 0.0
        self._mouth, self._next_mouth = "base", 0.0
        self._petals = []

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
        if state not in STATES or state == "happy":
            state = "idle"   # "happy" is a moment, not a state — use celebrate()
        if state == self.state:
            return           # called per streamed token — don't redraw every time
        with self._rlock:
            self.state = state
            self._state_since = time.monotonic()
        if self.active and not self._check_resize():
            self._tick()

    def celebrate(self, seconds: float = 2.5):
        """Show her happy face (bounce + sparkles) for a moment — e.g. a task done."""
        with self._rlock:
            self._happy_until = time.monotonic() + seconds
            self._state_since = time.monotonic()
        if self.active:
            self._tick()

    def refresh(self):
        """Redraw the whole pane (avatar + status panel)."""
        if self.active:
            if not self._check_resize():
                self._draw_pane()

    # ── layout ─────────────────────────────────────────────────────────────
    def _layout(self, clear=False):
        cols, rows = shutil.get_terminal_size()
        self._size = (cols, rows)
        self.pane_h = _rows_for_width(self.width) + 2
        self._petals = []
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

    # ── animation ──────────────────────────────────────────────────────────
    def _compose(self, now):
        """(effective state, pixel frame, frame pulse level) for this instant."""
        W = self.width
        H = _height_for(W)
        state = "happy" if now < self._happy_until else self.state
        t = now - self._t0
        # 4 s breathing cycle, snapped to 3 positions: each step repaints most of
        # her, so fewer steps keeps terminal traffic low (~1 change a second).
        breath = BREATH_PX * (0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0))
        if BREATH_PX > 0:
            breath = round(breath / (BREATH_PX / 2)) * (BREATH_PX / 2)
        ring = STATES[state][0]

        if now >= self._next_blink:
            self._blink_until = now + 0.18
            self._next_blink = now + random.uniform(2.5, 5.5)
        blinking = now < self._blink_until

        ov, level = {}, 1.0
        if state == "happy":
            since = now - self._state_since
            if since < 1.4:
                breath = 5.0 * abs(math.sin(math.pi * since * 1.5))         # little bounces
            px = pixels(W, "happy", breath)
            rnd = random.Random(int(now * 6))
            ov["sparkles"] = [(rnd.randrange(2, max(3, H // 3)), rnd.randrange(1, max(2, W // 4))),
                              (rnd.randrange(2, max(3, H // 3)), rnd.randrange(3 * W // 4, W - 1))]
        elif state == "speaking":
            if now >= self._next_mouth:
                self._mouth = random.choice([m for m in ("talk1", "talk2", "base") if m != self._mouth])
                self._next_mouth = now + random.uniform(0.1, 0.22)
            px = pixels(W, self._mouth, breath)
            level = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 2.2 * 2 * math.pi))
        elif state == "thinking":
            px = pixels(W, "blink" if blinking else "think", breath)
            ov["scan"] = int(((now - self._state_since) % 1.6) / 1.6 * (H + 6)) - 2
            level = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 0.8 * 2 * math.pi))
        elif state == "listening":
            p = round((0.5 + 0.5 * math.sin(t * 3)) * 3) / 3               # glow pulses, 4 steps
            base = pixels(W, "blink" if blinking else "base", breath)
            glow = pixels(W, "listen", breath)
            px = (base * (1 - p) + glow * p).astype(np.uint8)
        elif state == "alert":
            px = pixels(W, "worried", breath)
        else:  # idle
            px = pixels(W, "blink" if blinking else "base", breath)
            ov["petals"] = self._step_petals(W, H)
        if ov:
            px = overlay(px, ring, **ov)
        return state, px, round(level, 2)

    def _step_petals(self, W, H):
        while len(self._petals) < 4:
            left = len(self._petals) % 2 == 0
            self._petals.append({
                "x": random.randint(0, 2) if left else W - 3 - random.randint(0, 1),
                "y": random.uniform(0, H) if len(self._petals) < 2 else random.uniform(-H, 0),
                "speed": random.uniform(0.7, 1.2), "sway": random.uniform(0, 6.3)})
        pts = []
        for p in self._petals:
            p["y"] += p["speed"]
            if p["y"] > H + 2:
                p["y"] = random.uniform(-8, -2)
            p["sway"] += 0.2
            pts.append((int(p["y"]), p["x"] + round(math.sin(p["sway"]))))
        return pts

    def _tick(self):
        """Render the current instant and write whatever changed."""
        with self._rlock:
            if not self.active:
                return
            state, px, level = self._compose(time.monotonic())
            buf = []
            if self._shown is None or self._shown.shape != px.shape:
                buf += [f"\x1b[{i + 2};2H{ln}" for i, ln in enumerate(body_lines(px))]
                self._shown = px.copy()
            else:
                # Track what's actually on screen: only the spans we send change,
                # so sub-threshold drift can never accumulate.
                for r, c0, c1, text in diff_spans(self._shown, px):
                    buf.append(f"\x1b[{r + 2};{c0 + 2}H{text}")
                    self._shown[2 * r:2 * r + 2, c0:c1] = px[2 * r:2 * r + 2, c0:c1]
            if (state, level) != self._frame_key:
                self._frame_key = (state, level)
                buf.append(self._frame_seq(state, level))
            if not buf:
                return
            with self._lock:
                if self.active:
                    self.out.write("\x1b7\x1b[?25l" + "".join(buf) + "\x1b[?25h\x1b8")
                    self.out.flush()

    def _frame_seq(self, state, level):
        top, bottom, sides = _frame_parts(self.width, state, level)
        w = self.width
        seq = [f"\x1b[1;1H{top}"]
        for i, s in enumerate(sides):
            seq.append(f"\x1b[{i + 2};1H{s}\x1b[{i + 2};{w + 2}H{s}")
        seq.append(f"\x1b[{self.pane_h};1H{bottom}")
        return "".join(seq)

    def _draw_pane(self):
        cols, _ = self._size
        aw = visible_width(self.width)
        info = self.info_fn(self.pane_h, cols - aw - 3)[: self.pane_h]
        with self._rlock:
            state, px, level = self._compose(time.monotonic())
            body = body_lines(px)
            self._shown, self._frame_key = px.copy(), (state, level)
            top, bottom, sides = _frame_parts(self.width, state, level)
            avatar = [top] + [s + ln + s for s, ln in zip(sides, body)] + [bottom]
            buf = ["\x1b7\x1b[?25l"]
            for i in range(self.pane_h):
                right = info[i] if i < len(info) else ""
                buf.append(f"\x1b[{i + 1};1H\x1b[2K{avatar[i]}  {right}\x1b[0m")
            sep = tuple(c // 3 for c in STATES[state][0])
            buf.append(f"\x1b[{self.pane_h + 1};1H\x1b[2K" + _fg(sep, _truecolor()) + "─" * cols + _RESET)
            buf.append("\x1b[?25h\x1b8")
            with self._lock:
                if self.active:
                    self.out.write("".join(buf))
                    self.out.flush()

    def _animate(self):
        while not self._stop.wait(1 / _FPS):
            try:
                self._tick()
            except Exception:
                pass   # a bad frame must never take down the chat
