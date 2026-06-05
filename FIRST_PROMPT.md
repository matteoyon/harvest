# Primo prompt per la sessione Claude Code

Incolla questo prompt all'avvio di `claude` nella directory del progetto.

---

Leggi CLAUDE.md integralmente prima di scrivere qualsiasi codice.

Inizia con lo Step 1 descritto in CLAUDE.md: implementa il **LLM Router**.

I file da creare sono:

1. `src/reaper_agent/llm/providers.py`
   — Pydantic models: `ProviderConfig` (model, api_key, api_base, timeout)
     e `AppConfig` (default_provider, dict di ProviderConfig).
   — Funzione `load_config(path: Path) -> AppConfig` che legge `providers.toml`.

2. `src/reaper_agent/llm/router.py`
   — Classe `LLMRouter`:
     * costruttore accetta `AppConfig`
     * `current_provider` property (nome del provider attivo)
     * `switch_provider(name: str)` — switch a caldo, raise ValueError se non esiste
     * `async chat(messages: list[dict], tools: list[dict] | None) -> LLMResponse`
       chiama LiteLLM con il provider corrente, logga provider + latenza
     * `LLMResponse`: dataclass con `content: str | None`,
       `tool_calls: list[ToolCall] | None`, `provider: str`, `latency_ms: int`
   — Gestione errori: retry automatico 1 volta su errori di rete/timeout,
     poi propaga. Log chiaro su quale provider ha fallito.

3. `tests/test_router.py`
   — Test con mock di LiteLLM (non fare chiamate API reali):
     * caricamento config da TOML
     * switch provider valido
     * switch provider inesistente → ValueError
     * risposta testo normale
     * risposta con tool calls
     * retry su errore di rete

Requisiti tecnici:
- Tutto async (asyncio)
- Type hints completi
- Nessun print(), solo logging
- LiteLLM come unica dipendenza per le chiamate LLM (non importare SDK Anthropic/OpenAI direttamente nel router)

Dopo aver implementato e fatto passare i test, mostrami il router in azione
con un test manuale veloce: carica la config dall'example TOML, stampa i provider
disponibili, e fai girare un messaggio di test su Anthropic (se la chiave
ANTHROPIC_API_KEY è nell'env) o mocka la risposta se non c'è.
