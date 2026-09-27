<div align="center">

```
╔══════════════════════════════════════╗
║  SYSTEM: ACTIVE                      ║
║  WELCOME, TANISH                     ║
║  KRITI.PY LOADED ████████████ 100%  ║
╚══════════════════════════════════════╝
```

<img src="assets/kriti.png" width="480" alt="Kriti — your pixel AI"/>

# ✿ kriti.py

**your personal terminal AI · life OS · mission commander**

*she knows your projects. she tracks your fund. she will not let you slack.*

---

[![Python](https://img.shields.io/badge/python-3.10+-pink?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/runs%20on-ollama-ff69b4?style=flat-square)](https://ollama.com)
[![vibe](https://img.shields.io/badge/vibe-cozy%20terminal-c8f064?style=flat-square)]()
[![voice](https://img.shields.io/badge/voice-yes%20she%20talks-magenta?style=flat-square)]()
[![knowledge](https://img.shields.io/badge/knowledge-local%20RAG-9370db?style=flat-square)]()
[![personas](https://img.shields.io/badge/personas-gated%20by%20design-orange?style=flat-square)]()

</div>

---

## ˗ˏˋ what is this? ´ˎ˗

Kriti is a **terminal-based life gamification system** with a built-in AI assistant that actually knows who you are. Complete daily missions → earn real money → save it toward your wishlist. Ask Kriti anything. She'll talk back.

No SaaS. No subscription. No cloud. Just you, your terminal, and a very opinionated AI running locally on Ollama.

She now also has a local knowledge base of your own notes, swappable personas with their own permissions, scheduled nudges, and optional live web search — all gated through the same permission system, all still fully local unless you explicitly ask her to look something up.

She can also open/close/focus apps, search and open whitelisted files, read/write your clipboard, open URLs, react to conditions (idle time, foreground app) instead of just a clock, listen for a wake word so you don't have to be sitting in the chat screen, and look at your screen via a local vision model. Same permission system throughout — voice and proactive triggers go through the exact same whitelist/persona gates as typing a request.

---

## ˗ˏˋ features ´ˎ˗

```
 ✦ missions      daily tasks with ₹ rewards, fixed + AI-generated bonus
 ✦ kriti chat    persistent AI with full context of your life & projects  
 ✦ voice i/o     she listens. she speaks. toggle with [v]
 ✦ wishlist      track savings toward real items, allocate your fund
 ✦ quests        multi-day goals with milestones + bonus rewards
 ✦ pomodoro      focus timer, auto-marks study task on completion
 ✦ history       per-day json logs + analytics + streak tracking
 ✦ journal       auto-exports daily summary to journal.md on lock
 ✦ actions       kriti can mark tasks, add habits, create quests mid-chat
 ✦ knowledge     RAG over your own notes — local embeddings, cited as [R1] [R2]
 ✦ personas      swap knowledge scope + allowed actions per persona, enforced at dispatch
 ✦ automations   scheduled OR condition-based nudges (idle time, foreground app, battery/cpu/ram)
 ✦ web search    optional live grounding, gated per-persona, rate-limited, cited as [W1] [W2]
 ✦ wake word     always-on voice — say the wake phrase from anywhere, no need to be in the chat screen
 ✦ screen sight  local vision model describes what's on your screen, on request
 ✦ live avatar    her portrait pinned above the chat — blinks, talks, glows by state
 ✦ barge-in       cut her off mid-sentence: any key, or just start talking
 ✦ memory         remembers lasting facts across weeks — /memory, /forget N
 ✦ tool calling   native Ollama tools for actions, with automatic [[TAG]] fallback
 ✦ neural voice   optional local Piper voice (Settings › Voice)
```

---

## ˗ˏˋ setup ´ˎ˗

**1. install dependencies**
```bash
pip install blessed requests psutil   # psutil powers CLOSE_APP/LIST_APPS + system status

# voice support (optional but recommended)
brew install portaudio          # macOS only
pip install pyaudio SpeechRecognition

# fully offline STT (optional)
pip install faster-whisper

# natural neural voice (optional) — then Settings › [9] Voice, point it at the .onnx
pip install piper-tts
# voices: https://huggingface.co/rhasspy/piper-voices (download .onnx AND .onnx.json)

# knowledge base (RAG)
pip install sqlite-vec
ollama pull nomic-embed-text    # local embedding model, ~274MB

# scheduled automations
pip install apscheduler

# web search grounding (optional — no API key needed)
pip install ddgs

# wake word (optional — see kriti_wakeword.py docstring before relying on it)
pip install openwakeword pyaudio numpy
python3 -c "import openwakeword; openwakeword.utils.download_models()"

# screen awareness + Kriti's on-screen avatar (optional)
pip install Pillow
ollama pull moondream    # or llava — a vision-capable model, separate from your main chat model
```

**2. start ollama with CORS open**
```bash
OLLAMA_ORIGINS=* ollama serve
```

**3. run**
```bash
python3 kriti.py
```

---

## ˗ˏˋ menu ´ˎ˗

```
  ──────────────────────────────────────────────────
  TANISH.EXE  ·  Life OS         Fund: ₹2,450
  Tuesday, 01 Jul 2026
  Today: ₹55/100  [██████████████░░░░░░░░░░░░░░░░░░░░░░░░░░]
  ──────────────────────────────────────────────────
  🔥 4-day streak

  [1] Missions
  [2] Wishlist
  [3] History
  [4] Quests
  [5] Pomodoro
  [6] My Tasks
  [7] Kriti          ← the good one
  [8] Settings
  [q] Quit
```

---

## ˗ˏˋ talking to kriti ´ˎ˗

Kriti knows your active projects, your fund, every task's status, your quests, and the current time. She can also **do things** mid-conversation:

| say something like | what she does |
|---|---|
| `"done with my workout"` | marks workout ✓, plays sound |
| `"add a daily task to read 20 pages"` | creates recurring habit |
| `"create a quest to ship Prier v2"` | builds a quest with milestones |
| `"finished the OTP flow"` | marks quest milestone done |
| `"let's focus for 25 mins"` | starts pomodoro inline |
| `"close spotify"` | closes a whitelisted running app |
| `"what's running right now"` | lists currently running apps |
| `"switch to vscode"` | brings an already-open whitelisted app to front |
| `"find that resume pdf"` | searches whitelisted directories by filename |
| `"copy this to clipboard: ..."` | writes to the system clipboard |
| `"open github in the browser"` | opens a URL in your default browser |
| `"what's on my screen right now"` | screenshots + describes it via a local vision model |
| *(say the wake phrase, then speak)* | works from anywhere — no need to be in the Kriti chat screen |
| `"re-index my notes"` | rebuilds the RAG index (incremental — only new/changed files) |
| `/persona deep_work` or `[[SET_PERSONA:deep_work]]` | switches active persona mid-chat |
| anything with `"latest"`, `"current"`, `"today"`, etc. | auto-triggers a live web search (if the active persona allows it) |

**live avatar** — in a terminal of at least ~62×24 (truecolor recommended), the chat screen pins Kriti's portrait and a status panel to the top while the conversation scrolls underneath. Her frame shows what she's doing: pink = online, blue = listening, purple (slow pulse) = thinking, green (fast pulse) = speaking, red = something went wrong. Smaller terminals fall back to the plain header. Needs `Pillow`.

**interrupting her** — press any key while she's replying to stop her (generation and speech both stop, and any actions in the cut-off reply are *not* run). In voice mode you can also just start talking over her; that works best with headphones, since on laptop speakers the mic can hear her own voice.

**long-term memory** — beyond the last 40 messages, she keeps short lasting facts (deadlines, preferences, people, project status) in `~/.life_missions/memories.json`. Say "remember that…" to store one explicitly; every few exchanges a background pass also picks new ones out of what *you* said (never from web results or screen text). `/memory` lists them, `/forget N` removes one.

**tool calling** — Settings › [1]: `hybrid` (default) offers actions as native Ollama tools while keeping the `[[TAG]]` instructions, so it's never worse than tags alone; `strict` swaps the tag tutorial for a short tools section (half the prompt, faster) — use it with models that reliably call tools, e.g. `llama3.2`; `off` is tags only. Models without tool support fall back to tags automatically. Tool calls go through exactly the same persona/whitelist gates as tags.

**untrusted content** — web results and screen descriptions are fenced as untrusted data in her context. On a turn that included them, actions that touch your system or send data out (open URL/app, clipboard, files, scripts, remember…) need a `y` from you first; the wake-word path simply skips them.

**voice mode** — type `v` to toggle. She listens via mic (Whisper/Google STT), speaks via macOS `say` (Tara voice by default) or a local Piper neural voice (Settings › [9] Voice). Streams sentences as they're generated so it feels live.

**memory** — chat history persists across sessions (last 40 messages). She remembers where you left off.

---

## ˗ˏˋ knowledge base (RAG) ´ˎ˗

Point Kriti at a folder of your own notes and she'll answer questions grounded in them instead of guessing.

```
Settings [8] → [4] RAG / Knowledge index
  [1] Set docs directory
  [2] Change embedding model / top-K
  [3] Run incremental re-index
  [4] Force full re-index
  [5] Clear index
```

- Supports markdown and plaintext today (PDF later).
- Chunked by heading/paragraph, embedded locally via `nomic-embed-text` through Ollama, stored in SQLite (`sqlite-vec`) — nothing leaves the machine.
- Incremental re-index only re-embeds files that changed.
- Answers cite their source chunks as `[R1]`, `[R2]`, etc.

---

## ˗ˏˋ personas ´ˎ˗

Kriti can run as different personas — each with its own system prompt, its own slice of the knowledge base, and its own allowlist of actions. A persona can only **narrow** what's normally allowed (via `whitelist.json`), never widen it.

| persona | allowed actions | knowledge scope | auto-triggers on |
|---|---|---|---|
| `general` | all actions | full index | default — not auto-inferred |
| `deep_work` | 11 actions (no `LOCK_SCREEN`, `ADD_RECURRING`) | project docs | code, prier, brain, debug, focus… |
| `brain_research` | 6 actions (`DONE`, `ADD_TASK`, `ADD_QUEST`, `QUEST_DONE`, `UNDONE`, `RAG_INDEX`) | WorldQuant BRAIN notes | brain, worldquant, alpha, iqc… |

Switch explicitly with `/persona <name>` (or `[[SET_PERSONA:name]]` mid-chat), or just talk naturally — keyword matches will transiently narrow scope for that turn without persisting a switch. Manage, edit, or create personas under **Settings [5]**.

---

## ˗ˏˋ automations ´ˎ˗

An in-process scheduler (APScheduler) lets personas fire actions on a timer or condition instead of waiting for you to ask. Defined declaratively in `automations.json` — no code changes needed to add one.

Every scheduled action goes through the **same permission gate** a manual chat message would: a persona's allowlist, intersected with `whitelist.json`. A scheduled job never has more authority than you'd have typing the same request yourself. Run history is viewable from the terminal so you can see what fired, when, and under which persona.

Trigger types: `interval`, `cron`, and `perception` (condition-based, polled every couple minutes). Perception checks: `battery_below`, `cpu_above`, `ram_above`, `idle_above` (seconds since last input), `foreground_app_is` / `foreground_app_not` (substring match on the active window). This is what makes her *proactive* instead of just scheduled — e.g. an idle-based auto-lock ships as a disabled-by-default example in `automations.json`.

Actions that need a human present to verify them (`OPEN_APP`, `CLOSE_APP`, `FOCUS_WINDOW`, `RUN_SCRIPT`, `FILE_OPEN`) are always skipped in unattended runs, logged with reason `requires_human`. Everything else — including `DESCRIBE_SCREEN` — is safe to fire on a schedule.

---

## ˗ˏˋ wake word ´ˎ˗

Always-on voice via [openWakeWord](https://github.com/dscripka/openWakeWord) (lightweight, CPU-only — no GPU needed). Say the wake phrase from anywhere, and she'll listen for your query and answer through the exact same brain, action tags, and whitelist gates as the chat screen — a wake-word exchange and a manual chat session share one continuous memory.

Off by default. Turn it on from **Settings [8]**, and **read the module docstring in `kriti_wakeword.py` first** — the exact wake-phrase model name shipped by openwakeword can vary by version, and the module logs every model name it sees the first time it runs so you can confirm/correct it.

**Known limitation:** the terminal UI (`blessed`) owns the screen. A wake-word reply prints/speaks from a background thread, so if you're mid-screen elsewhere it can visually interleave with that screen's own output. Cleanest when idling at the main menu — this is a voice channel bolted onto the existing TUI, not a full background-service rewrite.

---

## ˗ˏˋ screen awareness ´ˎ˗

`[[DESCRIBE_SCREEN]]` (or `[[DESCRIBE_SCREEN:a specific question]]`) screenshots your display and describes it via a **local** Ollama vision model — configured separately from your main chat model in **Settings [1]** (default `moondream`; `llava` also works). Runs on CPU like the rest of Ollama here, so it's slow (seconds) without a GPU — but nothing leaves the machine.

Always allowed, no whitelist needed — it only observes. The description lands in her context on the **next** turn, same delayed pattern as web search: she can't react to it in the same reply that fired the tag.

---

## ˗ˏˋ web search ´ˎ˗

Optional live grounding via DuckDuckGo (`ddgs` — no API key, no account). Off by default per-persona.

- Gated the same way as any other action: a persona needs `web_search_enabled` (and, for `brain_research`, is further restricted to `arxiv.org`, `worldquant.com`, `ssrn.com`, `quantopian.com`, `quantlib.org`).
- Auto-triggers on recency-flavored questions ("latest", "current", "today"…), or explicitly via `[[WEB_SEARCH:query]]`.
- Results are cited as `[W1]`, `[W2]` — kept visually distinct from local `[R#]` note citations so you always know what's local vs. live.
- Rate-limited. Configurable under **Settings [7]**.

---

## ˗ˏˋ file structure ´ˎ˗

**project root**
```
kriti.py                # app: state, screens, chat loop, action parsing
kriti_ui.py              # shared terminal helpers
kriti_voice.py           # TTS (Piper / say / pyttsx3), STT, barge-in, sfx, notifications
kriti_system.py          # machine perception + every whitelisted action
kriti_avatar.py          # pixel-art avatar + live HUD (blink, talk, state glow)
kriti_tools.py           # native Ollama tool definitions → [[TAG]] lines
kriti_memory.py          # long-term memory store + background fact extraction
kriti_rag.py             # knowledge base: chunker, embedder, indexer, retriever
kriti_personas.py        # persona schema, CRUD, action-gate enforcement
kriti_scheduler.py       # in-process automation scheduler
kriti_websearch.py       # DuckDuckGo search, gating, citation formatting
kriti_wakeword.py        # always-on wake-word listener (openWakeWord)
```

**data dir**
```
~/.life_missions/
  ├── global.json              # fund, wishlist, quests, settings
  ├── whitelist.json           # the hard ceiling — no persona can exceed this
  ├── automations.json         # scheduled jobs: trigger + persona + action(s)
  ├── websearch_config.json    # web search toggle, rate limit, safe-search level
  ├── personas/                # one JSON file per persona (general, deep_work, brain_research, …)
  ├── 2026-07-01.json          # today's tasks, completions, ai mission
  ├── 2026-06-30.json          # yesterday
  ├── ...                      # one file per day, forever
  ├── kriti_chat.json          # last 40 messages of chat history
  ├── memories.json            # long-term facts (/memory, /forget N)
  └── journal.md               # auto-appended on every day lock
```

---

## ˗ˏˋ ollama model ´ˎ˗

Default model is `gemma4`. Change in **Settings [8]** or set any model you have pulled:

```bash
ollama pull gemma4       # default, good balance
ollama pull llama3.2     # lighter, faster
ollama pull mistral      # also solid
```

---

## ˗ˏˋ perfect day = ₹100 ´ˎ˗

| task | area | ₹ |
|---|---|---|
| Complete PPL workout | Fitness | 20 |
| 2hr focused study session | Academics | 15 |
| Sleep before 1am | Habits | 10 |
| No phone first 30min after waking | Habits | 5 |
| Daily review / journal | Habits | 5 |
| AI bonus mission | varies | 10–25 |

Miss tasks → earn less. Simple.

---

## ˗ˏˋ wishlist ´ˎ˗

Pre-loaded with the actual build list:

```
PC Build  ·  Ryzen 5 7500F · MSI B850M · RTX 5060 Ti · DDR5 RAM
            Crucial T700 SSD · CM 360L Cooler · Deepcool 750W · CM Elite 490
            MSI QD-OLED 34"

Games     ·  Tekken 8 · Helldivers 2 · GTA 6

Wishlist  ·  iPhone Mini · Console
```

Every rupee you earn goes into the fund. Allocate it toward items whenever you want.

---

## ˗ˏˋ requirements ´ˎ˗

```
python      3.10+
blessed     terminal UI
requests    ollama API calls
ollama      running locally (any model)

knowledge base:
sqlite-vec          vector storage for RAG
nomic-embed-text    local embedding model (via ollama)

automations:
apscheduler         in-process scheduler

optional:
pyaudio             mic input
SpeechRecognition   STT fallback
faster-whisper      offline STT (recommended)
pyttsx3             TTS fallback (non-macOS)
ddgs                web search grounding (no API key required)

system control (OPEN_APP/CLOSE_APP/LIST_APPS always work via psutil — install it):
psutil              process listing/closing, cross-platform
pycaw, comtypes     SET_VOLUME on Windows only (pip install pycaw comtypes)
wmctrl              FOCUS_WINDOW on Linux X11 only (system package, not pip — Wayland unsupported)
xdotool             foreground-app perception on Linux X11 only (system package)
xprintidle          idle-time perception on Linux X11 only (system package)
pyperclip           CLIPBOARD_READ/CLIPBOARD_WRITE, cross-platform

wake word (optional — see kriti_wakeword.py docstring):
openwakeword        wake-phrase detection, CPU-only
pyaudio, numpy      mic streaming + audio frames

screen awareness (optional):
Pillow              screenshot capture (Windows/macOS; Linux needs grim/scrot too)
                     + a vision-capable Ollama model: ollama pull moondream
```

---

<div align="center">

```
╔══════════════════════╗
║  made with ♡         ║
║  by tanish & kriti   ║
╚══════════════════════╝
```

*₹0 in fund is a character arc, not a failure.*

</div>
