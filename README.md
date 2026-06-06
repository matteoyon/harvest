# harvest

A conversational agent that controls REAPER DAW in natural language.
You type in a chat; the agent translates your intent into concrete operations on the open project.

```
> Add tracks Kick, Snare, HiHat, Bass, Lead. Color the percussion red and the melodic ones blue.

  → list_tracks({})
  ← {"tracks": []}
  → add_track({"name": "Kick", "color": "#FF4444"})
  ← {"id": 0, "name": "Kick"}
  → add_track({"name": "Snare", "color": "#FF4444"})
  ...
  Done. Created 5 tracks: Kick, Snare, HiHat (red) and Bass, Lead (blue).
```

---

## Table of contents

1. [How LLM agents work — the core ideas](#1-how-llm-agents-work--the-core-ideas)
2. [Harvest architecture](#2-harvest-architecture)
3. [Quick start](#3-quick-start)
4. [Running without REAPER (fake simulator)](#4-running-without-reaper-fake-simulator)
5. [CLI reference](#5-cli-reference)
6. [The three POC scenarios](#6-the-three-poc-scenarios)
7. [Project structure](#7-project-structure)
8. [Adding a new tool](#8-adding-a-new-tool)

---

## 1. How LLM agents work — the core ideas

This section is a short primer on the concepts behind harvest.
Skip it if you already know what tool calling and the agent loop are.

### 1.1 A chatbot vs an agent

A plain chatbot generates text.
An **agent** generates text *and* takes actions in the world — it can call functions, read files, run code, call APIs.

The key ingredient that enables this is **tool calling** (also called function calling).

### 1.2 Tool calling

You describe a set of functions to the model in its system prompt, in a structured JSON format:

```json
{
  "name": "add_track",
  "description": "Add a new track to the REAPER project.",
  "parameters": {
    "type": "object",
    "properties": {
      "name":  { "type": "string", "description": "Track name" },
      "color": { "type": "string", "description": "Hex color, e.g. #FF4444" }
    },
    "required": ["name"]
  }
}
```

The model doesn't execute the function — it just decides *when* to call it and *what arguments* to pass, and returns that decision as structured JSON instead of prose:

```json
{ "tool": "add_track", "arguments": { "name": "Kick", "color": "#FF4444" } }
```

Your code receives that, executes the real function, and sends the result back to the model.
The model then decides what to do next.

### 1.3 The agent loop

This back-and-forth creates a loop:

```
┌─────────────────────────────────────────────────────┐
│                    AGENT LOOP                       │
│                                                     │
│  User message                                       │
│       │                                             │
│       ▼                                             │
│  LLM decides:  ──── text response? ──► print & stop │
│                │                                    │
│                └── tool call?  ──► execute tool     │
│                                         │           │
│                                    result back      │
│                                    to LLM  ◄────────┘
│                                    (loop again)     │
└─────────────────────────────────────────────────────┘
```

A single user message might trigger 5-10 tool calls before the model produces a final text response.
That is what makes it an *agent* rather than a single-shot completion.

### 1.4 The conversation history

Everything — user messages, model responses, tool calls, tool results — is accumulated in a list called the **conversation history** (or context window):

```python
messages = [
    {"role": "system",    "content": "You are Harvest, you control REAPER..."},
    {"role": "user",      "content": "Add a Kick track colored red"},
    {"role": "assistant", "content": None, "tool_calls": [{"name": "add_track", ...}]},
    {"role": "tool",      "tool_call_id": "...", "content": '{"id": 0, "name": "Kick"}'},
    {"role": "assistant", "content": "Done. Added a red Kick track (id 0)."},
]
```

This list grows with every turn and is sent to the LLM with every request.
The model has no memory of its own — it re-reads the full history each time.

### 1.5 The system prompt

The first message in the history, `role: "system"`, is the **system prompt**.
It is the instruction set you give the model before the user says anything:
- what it is ("You are Harvest, a REAPER agent")
- what tools it has
- constraints and domain knowledge (MIDI pitch numbers, color codes, etc.)

This is where you program the agent's personality and capabilities.

---

## 2. Harvest architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI  (src/harvest/ui/cli.py)                                    │
│  • reads user input                                              │
│  • runs the agent loop                                           │
│  • displays tool calls and responses in real time                │
└──────────────────────┬───────────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │   LLM Router            │
          │   (llm/router.py)       │
          │                         │
          │  LiteLLM abstracts all  │
          │  providers behind one   │
          │  identical interface    │
          │                         │
          │  ┌──────────────────┐   │
          │  │ Anthropic Claude │   │
          │  │ Ollama (local)   │   │
          │  │ OpenAI           │   │
          │  │ Groq             │   │
          │  └──────────────────┘   │
          └────────────┬────────────┘
                       │  tool call decision
          ┌────────────▼────────────┐
          │   Tool Registry         │
          │   (mcp/registry.py)     │
          │                         │
          │  holds 10 tool schemas  │
          │  dispatches to bridge   │
          └────────────┬────────────┘
                       │  bridge.call("add_track", {...})
          ┌────────────▼────────────┐
          │   REAPER Bridge         │
          │   (bridge/reaper.py)    │
          │                         │
          │  writes JSON command    │
          │  to /tmp/harvest_cmd    │
          │  polls for result       │
          └────────────┬────────────┘
                       │  file IPC
          ┌────────────▼────────────┐
          │  REAPER + Lua script    │       OR       Fake simulator
          │  (reaper_ipc_bridge.lua)│               (bridge/fake_reaper.py)
          │                         │
          │  polls cmd file         │
          │  calls reaper.* API     │
          │  writes result file     │
          └─────────────────────────┘
```

### Why file-based IPC instead of WebSocket?

REAPER's Lua environment is single-threaded and runs alongside the audio engine.
A WebSocket would require a separate thread and careful locking.
A polling loop reading a JSON file is simpler, robust under load, and needs zero external dependencies inside REAPER.

### Why LiteLLM?

Every LLM provider has a slightly different SDK and API format.
[LiteLLM](https://github.com/BerriAI/litellm) normalises them all to the OpenAI interface.
We write the tool definitions once; any provider works without code changes.
Switching from Claude to a local Ollama model is a one-line config change.

### The IPC protocol

Two files, one command at a time:

```
Python writes →   /tmp/harvest_cmd.json
                  { "id": "uuid", "tool": "add_track", "params": {"name": "Kick"} }

Lua reads, acts, writes →   /tmp/harvest_result.json
                             { "id": "uuid", "ok": true, "result": {"id": 0, "name": "Kick"} }

Python reads ← result matched by id
```

The `id` field prevents Python from reading a stale result from a previous command.

---

## 3. Quick start

### Prerequisites

- Python 3.11+
- One of:
  - An Anthropic API key (cloud, paid) — fastest setup
  - [Ollama](https://ollama.com) installed locally with `gemma3:4b` pulled (offline, free)

### Install

```bash
git clone <repo>
cd harvest

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

### Configure

```bash
cp config/providers.example.toml config/providers.toml
```

Then edit `config/providers.toml`.

**Option A — Anthropic (cloud)**

```toml
[default]
provider = "anthropic"

[providers.anthropic]
model   = "claude-sonnet-4-5"
api_key = "sk-ant-..."          # or set ANTHROPIC_API_KEY env var
```

**Option B — Ollama (local, offline)**

```bash
ollama pull gemma3:4b           # ~3.3 GB, one-time download
```

```toml
[default]
provider = "ollama"

[providers.ollama]
model    = "ollama/gemma3:4b"
api_base = "http://localhost:11434"
api_key  = "ollama"
```

### Run tests

```bash
pytest -q
# 40 passed
```

---

## 4. Running without REAPER (fake simulator)

The **fake simulator** replays the same IPC protocol as the Lua script,
but entirely in Python with an in-memory project state.
This lets you test the full agent loop without ever opening REAPER.

Open **two terminals**:

**Terminal A — start the simulator**

```bash
source .venv/bin/activate
python -m harvest.bridge.fake_reaper
```

```
[fake-reaper] listening on /tmp/harvest_cmd.json
[fake-reaper] Ctrl-C to stop
```

**Terminal B — start the agent**

```bash
source .venv/bin/activate
reaper-agent
```

```
╭─────────────────────────────────────────────────╮
│ harvest — REAPER conversational agent           │
│ Commands: /provider <name>  /state  /help /quit │
╰─────────────────────────────────────────────────╯
Provider: anthropic   Available: anthropic, ollama, openai, groq, llamacpp
>
```

Type anything. The agent will call tools, the simulator will execute them,
and you can inspect the live project state with `/state` at any time.

---

## 5. CLI reference

| Command | What it does |
|---------|-------------|
| `> your message` | Send a message to the agent |
| `/provider <name>` | Switch LLM provider without restarting (hot-swap) |
| `/state` | Pretty-print the current REAPER project state as JSON |
| `/help` | Show available commands |
| `/quit` | Exit |

**Hot-swap example:**

```
> /provider ollama
Switched to provider: ollama

> /provider anthropic
Switched to provider: anthropic
```

The conversation history is preserved across provider switches.
The new model picks up exactly where the previous one left off.

---

## 6. The three POC scenarios

These are the three scenarios that define a complete POC.
Run them in order with the fake simulator to verify the full stack.

### Scenario 1 — Track setup

Tests: multi-tool sequencing, categorical reasoning

```
> Create tracks Kick, Snare, HiHat, Bass, Lead.
  Color the percussion red and the melodic instruments blue.
```

Expected: 5 tracks created with correct names and colors.
Verify with `/state`.

### Scenario 2 — MIDI creation

Tests: MIDI item creation, musical knowledge (note name → pitch number)

```
> On the Bass track insert a 4-bar MIDI item and add a C-E-G-B chord in the central octave.
```

Expected: one MIDI item on the Bass track containing 4 notes
(C4=60, E4=64, G4=67, B4=71) at beat 0.

### Scenario 3 — FX on multiple tracks

Tests: iteration over a list of tracks, targeted by name

```
> Add ReaComp to the Kick, and ReaEQ to all other tracks.
```

Expected: Kick gets ReaComp; Snare, HiHat, Bass, Lead each get ReaEQ.

---

## 7. Project structure

```
harvest/
├── config/
│   ├── providers.example.toml   ← commit this (template)
│   └── providers.toml           ← your local keys (gitignored)
│
├── scripts/
│   └── reaper_ipc_bridge.lua    ← load this inside REAPER
│
├── src/harvest/
│   │
│   ├── llm/
│   │   ├── router.py            ← LLMRouter: wraps LiteLLM, hot-swap, latency log
│   │   └── providers.py         ← Pydantic config models + TOML loader
│   │
│   ├── bridge/
│   │   ├── reaper.py            ← ReaperBridge: async file IPC client
│   │   └── fake_reaper.py       ← FakeReaperState + file-polling simulator
│   │
│   ├── mcp/
│   │   ├── registry.py          ← ToolRegistry: schemas + dispatcher
│   │   └── tools/
│   │       ├── tracks.py        ← get_project_state, list_tracks, add/delete/rename_track, set_track_volume
│   │       ├── items.py         ← insert_midi_item
│   │       ├── midi.py          ← add_midi_note
│   │       ├── fx.py            ← add_fx
│   │       └── transport.py     ← play, stop
│   │
│   └── ui/
│       └── cli.py               ← agent loop, Rich display, slash commands
│
└── tests/
    ├── test_router.py           ← LLM router + config loading
    ├── test_bridge.py           ← ReaperBridge round-trip, timeout, error handling
    └── test_tools.py            ← registry schemas, dispatcher, all 10 tools
```

**Data flow in code terms:**

```
cli.py          agent_loop()
  │               messages.append(user_msg)
  │               router.chat(messages, tools=registry.openai_schemas())
  │                 └─► litellm.acompletion(model, messages, tools)  ← network call
  │               if response.tool_calls:
  │                 registry.execute(name, args, bridge)
  │                   └─► bridge.call(tool, params)
  │                         └─► write /tmp/harvest_cmd.json
  │                             poll /tmp/harvest_result.json
  │                 messages.append(tool_result)
  │               loop ──► router.chat() again
  └─► print final text
```

---

## 8. Adding a new tool

Here is the full checklist for adding a tool, e.g. `set_track_color`.

**1. Add the Python tool spec** in the right module under `src/harvest/mcp/tools/`:

```python
# tracks.py — append to TOOLS list
{
    "type": "function",
    "bridge_tool": "set_track_color",        # name sent over IPC
    "function": {
        "name": "set_track_color",           # name the LLM uses
        "description": "Change the color of a track.",
        "parameters": {
            "type": "object",
            "properties": {
                "track_id": {"type": "integer", "description": "Numeric track id"},
                "color":    {"type": "string",  "description": "Hex color e.g. #FF4444"},
            },
            "required": ["track_id", "color"],
        },
    },
},
```

**2. Add the handler to `FakeReaperState`** in `bridge/fake_reaper.py`:

```python
def set_track_color(self, track_id: int, color: str, **_):
    track = self._get_track(track_id)
    track["color"] = color
    return {"id": track_id, "color": color}
```

And register it in `dispatch()`:

```python
"set_track_color": self.set_track_color,
```

**3. Add the handler to the Lua script** in `scripts/reaper_ipc_bridge.lua`:

```lua
local function set_track_color(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then error("Track not found") end
    local r = tonumber("0x"..params.color:sub(2,3)) or 0
    local g = tonumber("0x"..params.color:sub(4,5)) or 0
    local b = tonumber("0x"..params.color:sub(6,7)) or 0
    reaper.SetTrackColor(tr, reaper.ColorToNative(r,g,b))
    reaper.UpdateArrange()
    return {id=params.track_id, color=params.color}
end
```

And add it to `HANDLERS`:

```lua
HANDLERS["set_track_color"] = set_track_color
```

**4. Write a test** in `tests/test_tools.py` and run `pytest -q`.

That's it. The tool registry auto-discovers anything in the `TOOLS` lists,
so no wiring is needed beyond steps 1–3.

---

## Running with real REAPER

1. Open REAPER.
2. Go to **Actions → Load ReaScript** and select `scripts/reaper_ipc_bridge.lua`.
3. Run it. The script starts polling in the background.
4. Start the agent in a terminal (no fake simulator needed):

```bash
reaper-agent
```

The agent now controls your live REAPER session.
