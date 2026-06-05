# harvest — CLAUDE.md

Questo file è il contesto permanente del progetto per Claude Code.
Leggilo sempre integralmente prima di scrivere qualsiasi codice.

---

## Vision

Un agente conversazionale che controlla REAPER DAW in linguaggio naturale.
L'utente scrive in chat; l'agente traduce in operazioni concrete sul progetto aperto.

**Differenziatori rispetto ai competitor (Reagent, reaper-mcp su GitHub):**
- Multi-LLM con switch a caldo: Claude API, OpenAI, Groq, Ollama, LLaMA.cpp
- Local-first: funziona completamente offline con modelli locali
- UI dedicata e curata — non si appoggia a Claude Desktop o Cursor
- Zero crediti, zero subscription obbligatoria

---

## Architettura (decisione definitiva, non ridiscutere)

```
[Chat UI — floating panel, hotkey globale]
        ↓ testo libero
[Agent Core]
        ├── LLM Router  →  LiteLLM (astrae tutti i provider)
        │                    ├── Anthropic  (claude-sonnet-4-5 etc.)
        │                    ├── OpenAI     (gpt-4o etc.)
        │                    ├── Groq       (llama3-70b-8192 etc.)
        │                    ├── Ollama     → localhost:11434
        │                    └── LLaMA.cpp  → localhost:8080
        └── Tool Executor
                └── REAPER Bridge  →  Lua IPC file-based (dentro REAPER)
                        └── REAPER process
```

**REAPER Bridge**: file-based Lua IPC, non reapy/WebSocket.
Motivazione: più stabile sotto carico (LLM locale + REAPER), nessuna dipendenza WebSocket.
Il bridge scrive comandi JSON in un file di input, legge risultati da un file di output.
Il Lua script dentro REAPER fa polling ogni ~50ms.

**LLM Router**: LiteLLM come libreria di astrazione.
Tutti i provider espongono la stessa interfaccia OpenAI-compatible.
Tool calling normalizzato: le definizioni tool vengono scritte una volta sola.
Switch a caldo = cambio di `model` + `api_base` + `api_key` in runtime.

---

## Stack tecnologico

- **Python 3.11+**
- `litellm` — LLM router multi-provider
- `mcp` — Anthropic MCP SDK (per esporre i tool all'agent)
- `anthropic` — SDK diretto (backup / typed responses)
- `pydantic` — validazione configurazione e stato
- `rich` — output CLI leggibile durante sviluppo
- `toml` / `tomllib` — configurazione provider (built-in Python 3.11)
- `pytest` + `pytest-asyncio` — test
- UI in seguito: Tauri (Rust + WebView) o Electron — **da decidere dopo la POC**

---

## Struttura del progetto

```
harvest/
├── CLAUDE.md                        ← questo file
├── pyproject.toml
├── config/
│   └── providers.example.toml       ← template configurazione LLM
├── scripts/
│   └── reaper_ipc_bridge.lua        ← script Lua che gira dentro REAPER
├── src/harvest/
│   ├── llm/
│   │   ├── router.py                ← LLMRouter: switch a caldo tra provider
│   │   └── providers.py             ← dataclass per ogni provider
│   ├── mcp/
│   │   ├── server.py                ← MCP server con tool registrations
│   │   └── tools/
│   │       ├── tracks.py            ← add_track, delete_track, list_tracks, ...
│   │       ├── items.py             ← insert_midi_item, insert_audio, move_item, ...
│   │       ├── fx.py                ← add_fx, set_fx_param, list_fx, ...
│   │       ├── midi.py              ← add_midi_note, quantize, transpose, ...
│   │       └── transport.py         ← play, stop, set_tempo, get_cursor, ...
│   ├── state/
│   │   └── manager.py               ← snapshot progetto → JSON compatto per LLM
│   ├── bridge/
│   │   └── reaper.py                ← IPC client: scrive/legge file di comando
│   └── ui/
│       └── cli.py                   ← chat loop CLI con streaming (POC UI)
└── tests/
    ├── test_router.py
    ├── test_tools.py
    └── fixtures/
        └── sample_state.json
```

---

## Scope della POC (fase attuale)

**Obiettivo**: validare il loop completo end-to-end.
`testo utente → LLM → tool call → REAPER → risposta`

### Step 1 — LLM Router (PRIMO DA IMPLEMENTARE)
File: `src/harvest/llm/router.py` e `providers.py`

Il router deve:
- Accettare una lista di messaggi + definizioni tool (formato OpenAI)
- Chiamare il provider configurato via LiteLLM
- Restituire la risposta o la lista di tool calls
- Permettere switch del provider in runtime senza perdere la conversation history
- Loggare provider attivo + latenza ad ogni chiamata

Provider minimi per la POC:
1. Anthropic Claude (claude-sonnet-4-5)
2. Ollama locale (qualsiasi modello con tool calling: qwen2.5, mistral-nemo)

Config via file TOML in `config/providers.toml` (non in codice, non in env vars hardcoded).

### Step 2 — REAPER Bridge (IPC Lua)
File: `scripts/reaper_ipc_bridge.lua` + `src/harvest/bridge/reaper.py`

Protocollo IPC file-based:
- Python scrive in `/tmp/harvest_cmd.json`
- Lua legge, esegue, scrive risultato in `/tmp/harvest_result.json`
- Python legge il risultato con timeout (default 5s)
- Struttura comando: `{"id": "uuid", "tool": "add_track", "params": {...}}`
- Struttura risposta: `{"id": "uuid", "ok": true, "result": {...}}` o `{"ok": false, "error": "..."}`

### Step 3 — Tool layer (10 tool per POC)
```
get_project_state   list_tracks         add_track
delete_track        rename_track        set_track_volume
insert_midi_item    add_midi_note       add_fx
play / stop
```

### Step 4 — CLI chat loop
File: `src/harvest/ui/cli.py`

- Input testo utente
- Passa a router → agent loop con tool execution
- Streamma risposta token by token (rich Live display)
- Mostra quale tool viene chiamato e con quali parametri
- Comando speciale `/provider <nome>` per switch a caldo
- Comando speciale `/state` per stampare snapshot corrente

---

## State model (JSON compatto — non cambiare struttura senza motivo)

```json
{
  "project": {
    "name": "Session01",
    "bpm": 120,
    "time_sig": "4/4",
    "sample_rate": 48000,
    "cursor": 8.0,
    "length": 120.0
  },
  "tracks": [
    {
      "id": 0,
      "name": "Kick",
      "type": "audio",
      "vol_db": 0.0,
      "pan": 0.0,
      "muted": false,
      "soloed": false,
      "color": "#FF4444",
      "fx": [{"idx": 0, "name": "ReaComp", "enabled": true}],
      "sends": [{"to": 15, "vol_db": -6.0}],
      "items": [{"id": "i0", "start": 0.0, "len": 4.0, "type": "audio"}]
    }
  ]
}
```

Parametri FX dettagliati NON inclusi nello snapshot base (troppi token).
Si aggiungono solo tramite `get_fx_params(track_id, fx_idx)` esplicito.

---

## Scenari di test per la POC

Questi tre scenari devono funzionare end-to-end prima di considerare la POC completata:

1. **Setup struttura**: *"Crea tracce Kick, Snare, HiHat, Bass, Lead.
   Colora le percussioni di rosso e gli strumenti melodici di blu."*
   → testa: multi-tool sequenziale, ragionamento categorico

2. **Creazione MIDI**: *"Sulla traccia Bass inserisci un item MIDI di 4 battute
   e aggiungi un giro di Do-Mi-Sol-Si in ottava centrale."*
   → testa: MIDI creation, conoscenza musicale (note name → pitch number)

3. **FX su più tracce**: *"Aggiungi un ReaComp sulla Kick e un ReaEQ su tutte le altre."*
   → testa: iterazione su lista tracce, targeting per nome

---

## Convenzioni di codice

- Async ovunque (`asyncio`): tutte le chiamate LLM e IPC sono async
- Type hints completi su tutte le funzioni pubbliche
- Pydantic per tutti i modelli di dati (config, stato, messaggi IPC)
- Nessun `print()` diretto: usare `logging` nel codice di libreria, `rich` solo nella UI
- Errori LLM: retry automatico 1 volta, poi propaga l'eccezione
- Errori IPC REAPER: timeout esplicito, messaggio chiaro all'utente
- File di config non in version control (`config/providers.toml` in `.gitignore`),
  solo `config/providers.example.toml` committato

---

## Decisioni già prese — non riaprire

| Decisione | Scelta | Motivazione |
|-----------|--------|-------------|
| LLM abstraction | LiteLLM | supporto nativo Ollama + 100+ provider |
| REAPER bridge | Lua IPC file-based | stabilità sotto carico, no WebSocket |
| Config format | TOML | built-in Python 3.11, leggibile |
| POC UI | CLI con Rich | zero overhead, focus sul core |
| Async runtime | asyncio | streaming LLM richiede async |

---

## Contesto competitivo (per riferimento)

- **Reagent** (reaperagent.com): SaaS $8-65/mese, richiede internet, modello non scelto dall'utente
- **reaper-mcp / reaper-daw-mcp-server** (GitHub): backend MCP senza UI propria,
  si appoggiano a Claude Desktop — nessun multi-LLM, nessuna UX dedicata
- **Gap che stiamo coprendo**: UI standalone + multi-LLM + local-first
