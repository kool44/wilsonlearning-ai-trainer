# Counselor Salesperson AI Trainer (POC)

Interactive, voice-enabled AI facilitator for one Wilson Learning module:
**The Counselor Salesperson, Module 2: Learning and Applying the Skills of Relating.**

The facilitator teaches each concept, asks a question, assesses the answer against a rubric taken from the
Leader Guide, gives spoken feedback, and moves to the next step. Step 11 is a live role-play where the AI plays
a guarded customer and the learner opens a first meeting using the full Relating protocol.

## Run in 60 seconds

```bash
cp .env.example .env          # put your ANTHROPIC_API_KEY in .env
docker compose up --build
```

Open http://localhost:8000. Use Chrome or Edge for microphone input (Web Speech API). Voice output works in any
modern browser.

Without Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --port 8000
```

## No API key? Demo the flow with the mock provider

```bash
LLM_PROVIDER=mock .venv/bin/uvicorn app.main:app --port 8000
```

The mock provider returns canned teaching text and grades by answer length. It exists to verify the UI and
session flow, not to train anyone.

## How it works

```
content/<module>.json        what to teach, what to ask, rubric, model answer, role-play persona
        |
app/engine.py                owns the step sequence and session state (SQLite)
        |
app/llm.py                   Claude fills each step: teach / grade / play customer / grade role-play
        |
static/                      single-page chat UI, browser text-to-speech and speech-to-text
```

The LLM never chooses what comes next. The engine passes it one step at a time. Grading uses structured JSON
output (`score`, `met`, `missed`, `feedback`) so the UI can show rubric ticks.

Step types: `teach` (concept + check question), `apply` (learner builds their own PPP / Ben Duffy),
`roleplay` (multi-turn simulation, graded at the end), `reflect` (closing, always advances).

## Learner controls (UX)

- Lessons are delivered as short spoken "beats" (20 to 45 words each), one at a time. The learner says
  "go on" (or taps **Go on**) to continue, or asks a question mid-lesson and the facilitator answers it,
  then resumes. The last beat is always the step's question.
- Captions appear word by word as the voice speaks, so it reads like someone talking, not a page of text.

- **Stop** button, `Esc`, tapping the mic, or starting to type all interrupt the bot's voice (barge-in).
- Status line: Speaking / Listening / Thinking / Your turn.
- **Hands-free** toggle: auto-sends about 2 seconds after you stop talking.
- Role-play: persona card with turn counter, **Teach me** (pauses the customer, facilitator gives a hint, resume),
  **End call** (stops and grades).
- Repeat (explain differently), Skip, Restart, resume previous session on reload.
- Scorecard per step at the end.

## Adding another module

1. Copy `content/csp-module-2-relating.json`, change `id`, `title`, `steps`.
2. Restart the server (or `docker compose restart`). The content folder is mounted read-only into the container.

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | | Required for `LLM_PROVIDER=anthropic` |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `mock` |
| `MODEL` | `claude-opus-5-5` | Any current Claude model id |
| `TEACH_EFFORT` / `GRADE_EFFORT` | `medium` / `low` | Reasoning effort per call type |
| `LLM_FALLBACKS` | `1` | Server-side refusal fallback. Auto-disables if the platform rejects it |
| `PORT` | `8000` | HTTP port |
| `DB_PATH` | `data/trainer.db` | SQLite file |
| `CONTENT_DIR` | `content/` | Module packs |

## API

| Method | Path | Body |
|---|---|---|
| GET | `/api/health` | |
| GET | `/api/modules` | |
| POST | `/api/session` | `{module_id, learner_name?}` |
| GET | `/api/session/{id}` | resume |
| POST | `/api/session/{id}/message` | `{text}` |
| POST | `/api/session/{id}/command` | `{cmd: skip \| repeat \| restart \| hint \| end_call \| continue}` |

## Tests

```bash
LLM_PROVIDER=mock .venv/bin/python -m tests.smoke_session
```

## Known limits (POC)

- Voice uses the browser's built-in speech engines. For a studio-quality voice add a cloud TTS behind an endpoint.
- Sessions are anonymous; no login.
- Content for Module 2 was transcribed from the Leader and Participant Guides by hand into JSON. Videos
  (Ben Duffy story, Dave Martin model call) are summarized as text.
