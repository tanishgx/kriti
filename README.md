<div align="center">

```
╔══════════════════════════════════════╗
║  SYSTEM: ACTIVE                      ║
║  WELCOME, TANISH                     ║
║  KRITI.PY LOADED ████████████ 100%  ║
╚══════════════════════════════════════╝
```

<img src="Gemini_Generated_Image_9nyld29nyld29nyl.png" width="480" alt="Kriti — your pixel AI"/>

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
 ✦ automations   scheduled nudges that run through the exact same permission gate as chat
 ✦ web search    optional live grounding, gated per-persona, rate-limited, cited as [W1] [W2]
```

---

## ˗ˏˋ setup ´ˎ˗

**1. install dependencies**
```bash
pip install blessed requests

# voice support (optional but recommended)
brew install portaudio          # macOS only
pip install pyaudio SpeechRecognition

# fully offline STT (optional)
pip install faster-whisper

# knowledge base (RAG)
pip install sqlite-vec
ollama pull nomic-embed-text    # local embedding model, ~274MB

# scheduled automations
pip install apscheduler

# web search grounding (optional — no API key needed)
pip install ddgs
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
| `"re-index my notes"` | rebuilds the RAG index (incremental — only new/changed files) |
| `/persona deep_work` or `[[SET_PERSONA:deep_work]]` | switches active persona mid-chat |
| anything with `"latest"`, `"current"`, `"today"`, etc. | auto-triggers a live web search (if the active persona allows it) |

**voice mode** — type `v` to toggle. She listens via mic (Whisper/Google STT), speaks via macOS `say` (Samantha voice). Streams sentences as they're generated so it feels live.

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
kriti.py                # host — wires everything together
kriti_rag.py             # knowledge base: chunker, embedder, indexer, retriever
kriti_personas.py        # persona schema, CRUD, action-gate enforcement
kriti_scheduler.py       # in-process automation scheduler
kriti_websearch.py       # DuckDuckGo search, gating, citation formatting
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
