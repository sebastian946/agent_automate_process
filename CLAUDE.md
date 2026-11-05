# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DZ Labs multi-agent sales engine: a LangGraph graph over the Anthropic SDK that answers leads on WhatsApp (Twilio) and email (Gmail via n8n). A **Ventas** agent qualifies leads and hands off to a human (Sebas), a **Perfilador** keeps a structured customer profile, **Diagnóstico** runs a 6-section technical diagnosis once the deal is closed, **Soporte** handles the delivery stage, and **Marketing** scores raw leads offline. Code, prompts, tests, and docs are written in Spanish; keep new identifiers and comments in Spanish for consistency.

## Commands

Setup uses `uv` and a local `.venv` (Windows: substitute `.venv\Scripts\` for `.venv/bin/`).

```bash
uv venv && uv pip install -e ".[dev]"
pre-commit install
cp .env.example .env            # ANTHROPIC_API_KEY, DATABASE_URL, INBOUND_API_TOKEN, N8N_WEBHOOK_SECRET, TWILIO_AUTH_TOKEN are required by Settings
docker compose up -d postgres
.venv/bin/python scripts/init_db.py       # applies dzlabs/db/schema.sql + LangGraph checkpointer tables

# Lint / format (ruff, line length 120; CI fails on either)
.venv/bin/ruff check . && .venv/bin/ruff format --check .

# Tests
.venv/bin/pytest -m "not integration"                       # unit suite: no network, no Postgres, scripted fake LLM
.venv/bin/pytest -m integration                             # real Postgres (and real Haiku if API key present)
.venv/bin/pytest tests/test_graph_flujo.py::test_handoff_cambia_etapa_y_emite_evento   # single test
.venv/bin/python -m evals.run_evals --min-score 0.8 [--solo ventas|diagnostico]        # LLM-as-judge, needs real API key

# Run
.venv/bin/uvicorn dzlabs.api.app:app --reload
.venv/bin/python scripts/chat.py +573001112233 whatsapp     # console REPL; `:ficha`, `:etapa cerrado`, `:salir`
docker compose up -d --build                                # API + Postgres + n8n
```

Unit tests need no `.env`: `tests/conftest.py` sets placeholder env vars before importing `dzlabs`. The `Settings` class fails at import time if the required vars are missing, so any new script or test entry point must set them (see `evals/run_evals.py` for the pattern).

## Architecture

### Request flow

`POST /inbound` (or the Twilio/Gmail webhooks) → `normalizar_cliente_id` → `Engine.handle_message` → `graph.invoke` with `thread_id = "cliente:<id>"` → text reply. The graph is synchronous (psycopg + sync SDK); FastAPI wraps it in `asyncio.to_thread`. `handle_message` never raises to the channel: refusals and API errors become canned replies.

Graph (`dzlabs/graph/build.py`):

```
START → cargar_ficha → router(etapa) ─► ventas → perfilador ─┐
                                      ├► diagnostico ────────┼─► guardar_ficha → END
                                      └► soporte ────────────┘
```

Routing is decided entirely by `Ficha.agente_activo()` in `dzlabs/schemas.py`, which maps the stage to an agent. The Perfilador runs only after Ventas.

### Two kinds of state

- **Ficha** (customer record): a Pydantic `Ficha` stored as JSONB in `clientes`. Postgres is the source of truth; Notion is only a mirror fed by n8n. Loaded in `cargar_ficha`, mutated by the agent node, persisted in `guardar_ficha`. Nodes work on a copy and return `ficha.model_dump(mode="json")`.
- **Conversation history**: `State.messages` (raw Messages API dicts, including `thinking` and `tool_use` blocks) persisted by the LangGraph `PostgresSaver` checkpointer per `thread_id`. `recortar_historial` trims to 40 messages but always cuts at a plain user text message so tool_use/tool_result pairs are never split.

### Stage machine

`lead → calificado → handoff → agendado → cerrado → diagnostico → entrega`. `Ficha.avanzar_etapa` only moves forward. The agent itself can only do `lead→calificado` (deterministic BANT rule `es_calificado`, applied after the Perfilador) and `→handoff` (via the `handoff_a_sebas` tool). `agendado`/`cerrado` are set by the human from Notion through n8n → `POST /webhooks/etapa` → `Repo.set_etapa`. `cerrado→diagnostico` happens automatically on the first Diagnóstico turn.

### LLM calls (`dzlabs/llm.py`)

- `crear_mensaje` is the single entry point for text agents. It sends `output_config={"effort": ...}` and never `temperature` (returns 400 on current models). It tries the server-side fallback beta first (`LLM_FALLBACKS`) and degrades to a plain call if the beta is rejected.
- System prompt is always two blocks (`_system` in `nodes.py`): a long stable block with `cache_control: ephemeral` (role + catálogo + reglas, assembled by `dzlabs/prompts/__init__.py` from the `.md` files) and a dynamic block (channel format + `<ficha_cliente>` JSON + optional per-turn hint).
- Tool calling is a manual loop (`_loop_con_tools`, max 3 rounds). Tool definitions in `dzlabs/graph/tools.py` all use `strict: true`; each node supplies an `ejecutar(nombre, args)` closure that mutates the in-memory `ficha` and appends to `eventos`. Tool exceptions are returned to the model as `is_error` results, not raised.
- The Perfilador and Marketing scorer use `client.messages.parse(output_format=<PydanticModel>)`. On failure the Perfilador silently keeps the previous profile.

### Events and edges

Nodes append dicts to `State.eventos` (`handoff`, `lead_calificado`, `etapa_cambiada`, `diagnostico_cerrado`, `incidencia`). `guardar_ficha` logs stage transitions to `eventos_etapa` and POSTs each event to n8n (`dzlabs/integrations/n8n.py`) signed with HMAC-SHA256 in `X-DZ-Signature`. If `N8N_WEBHOOK_URL` is unset the event is logged and dropped. The n8n workflows (`n8n/*.json`) handle notifying Sebas, mirroring to Notion, and Notion→Postgres stage changes; see `n8n/README.md`.

Inbound webhook security: `/webhooks/etapa` requires `X-DZ-Signature = HMAC(secret, ts + "." + body)` plus `X-DZ-Timestamp` within 5 minutes; `/webhooks/twilio` validates `X-Twilio-Signature` against `PUBLIC_BASE_URL` + path and dedupes by `MessageSid` in `mensajes_procesados`.

### Channels

`cliente_id` is always E.164 (`+57...`, Colombia assumed when no country code) or a lowercased email. `dzlabs/channels/formatters.py` injects a per-channel format instruction into the system prompt and `aplicar_formato_salida` strips markdown for WhatsApp after generation.

## Testing conventions

- `tests/conftest.py` provides `FakeAnthropic` (a scripted queue of `Message` objects built with `msg(texto, tool=(name, args))`) and `FakeRepo` (in-memory). The `make_graph(guion, perfil)` fixture builds a real compiled graph with `InMemorySaver`; drive it with `handle_message(graph, cliente_id, canal, texto)` and assert on `fake_repo.fichas[...]` and `client.messages.llamadas[...]`.
- Each scripted `msg` is consumed by one `create` call, so a turn that calls a tool needs two messages in the guion (the tool_use and the follow-up text).
- Patch `dzlabs.integrations.n8n.emitir_evento` with `monkeypatch` when asserting on emitted events; otherwise events are dropped because `N8N_WEBHOOK_URL` is unset in tests.
- Mark anything needing Postgres or a real API key with `@pytest.mark.integration`; CI runs only `-m "not integration"` on PRs and the evals job only on pushes to `main` when the API key secret exists.
- Ruff `S` (bandit) rules are on for `dzlabs/`; `tests/`, `scripts/`, `evals/` have them relaxed.

## Logging and PII

Never log message text or full identifiers. Use `mask_id` from `dzlabs/logging_setup.py` for any `cliente_id` in logs or LangSmith metadata. Prompts mark customer content and the ficha as DATA (prompt-injection defence); keep that framing when editing `dzlabs/prompts/*.md`.

## Docs worth reading before larger changes

`docs/RUNBOOK.md` (operations, key rotation, incidents), `docs/DESPLIEGUE.md` (zero-to-production), `docs/PRIVACIDAD.md` (retention rules), `docs/COSTOS.md` (per-conversation cost).
