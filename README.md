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

</div>

---

## ˗ˏˋ what is this? ´ˎ˗

Kriti is a **terminal-based life gamification system** with a built-in AI assistant that actually knows who you are. Complete daily missions → earn real money → save it toward your wishlist. Ask Kriti anything. She'll talk back.

No SaaS. No subscription. No cloud. Just you, your terminal, and a very opinionated AI running locally on Ollama.

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

**voice mode** — type `v` to toggle. She listens via mic (Whisper/Google STT), speaks via macOS `say` (Samantha voice). Streams sentences as they're generated so it feels live.

**memory** — chat history persists across sessions (last 40 messages). She remembers where you left off.

---

## ˗ˏˋ file structure ´ˎ˗

```
~/.life_missions/
  ├── global.json          # fund, wishlist, quests, settings
  ├── 2026-07-01.json      # today's tasks, completions, ai mission
  ├── 2026-06-30.json      # yesterday
  ├── ...                  # one file per day, forever
  ├── kriti_chat.json      # last 40 messages of chat history
  └── journal.md           # auto-appended on every day lock
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

optional:
pyaudio             mic input
SpeechRecognition   STT fallback
faster-whisper      offline STT (recommended)
pyttsx3             TTS fallback (non-macOS)
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
