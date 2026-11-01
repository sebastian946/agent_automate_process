# DZ Labs · Motor comercial multi-agente

Sistema donde un **agente de Ventas** atiende leads por WhatsApp y email, un **Perfilador** mantiene la ficha
del cliente con sugerencias de cierre, **Sebas** agenda y cierra, y al marcar «cerrado» la siguiente conversación
la lleva el **agente de Diagnóstico**. En etapa «entrega» responde **Soporte**. **Marketing** alimenta el embudo.

Implementa el plan de Notion «Motor comercial multi-agente · Plan 1% diario (cascada)».

```
WhatsApp (Twilio) ─┐                         ┌─ n8n ─► aviso a Sebas (WhatsApp) + Cal.com
Email (Gmail/n8n) ─┴─► FastAPI /inbound ─► LangGraph ─┤  n8n ─► espejo Notion «Pipeline comercial»
                                      │               └─ n8n ─► página Notion «Diagnóstico · {empresa}»
                                      ▼
                     Postgres: clientes (ficha JSONB) + checkpoints (historial)
```

## Arquitectura

| Capa | Dónde | Qué hace |
| --- | --- | --- |
| Grafo | `dzlabs/graph/` | `START → cargar_ficha → router(etapa) → ventas→perfilador / diagnostico / soporte → guardar_ficha → END` |
| Agentes (prompts) | `dzlabs/prompts/*.md` | Rol + catálogo + reglas duras. Versionados en git. El bloque estable se cachea (prompt caching). |
| Herramientas | `dzlabs/graph/tools.py` | `handoff_a_sebas`, `guardar_diagnostico`, `cerrar_diagnostico`, `registrar_incidencia` (todas `strict`). |
| Ficha | `dzlabs/schemas.py` + `dzlabs/db/` | Pydantic valida todo lo que sale del LLM. Postgres = fuente de verdad. Notion = espejo. |
| Canales | `dzlabs/channels/` | Identidad (E.164 / email), formato por canal, firma de Twilio. |
| API | `dzlabs/api/app.py` | `/inbound`, `/webhooks/twilio`, `/webhooks/etapa`, `/clientes/{id}`, `/metricas/embudo`, `/health`. |
| Bordes | `n8n/*.json` | Avisos, espejo Notion, Notion→Postgres, Gmail entrante. |
| Marketing | `dzlabs/marketing/scorer.py` | Lead crudo → encaje 0-10 + primer mensaje (revisión humana antes de enviar). |

**Modelos:** Sonnet 5.5 para Ventas/Diagnóstico/Soporte/Marketing, Haiku 5.5 para el Perfilador (structured
outputs con esquema Pydantic). Configurables por `.env`.

**Observabilidad:** con `LANGSMITH_TRACING=true` cada turno es un trace en LangSmith agrupado por cliente (vista
Threads), con los nodos del grafo y cada llamada al LLM (tokens, caché, costo). El `cliente_id` va enmascarado.

**Etapas:** `lead → calificado → handoff → agendado → cerrado → diagnostico → entrega`. El agente solo avanza
(`lead→calificado` por regla BANT determinista; `→handoff` por la herramienta). `cerrado`/`agendado` los pone Sebas
desde Notion (n8n → `/webhooks/etapa`).

## Puesta en marcha (local)

```bash
# 1. Dependencias
uv venv && uv pip install -e ".[dev]"
pre-commit install

# 2. Secretos
cp .env.example .env     # rellena ANTHROPIC_API_KEY, contraseñas y tokens (ver comentarios)

# 3. Postgres + esquema + checkpointer
docker compose up -d postgres
.venv/bin/python scripts/init_db.py

# 4. Hablar con el agente en consola (guarda transcripción en tests/fixtures/transcripciones/)
.venv/bin/python scripts/chat.py +573001112233 whatsapp

# 5. API
.venv/bin/uvicorn dzlabs.api.app:app --reload
curl -s -X POST localhost:8000/inbound -H "Authorization: Bearer $INBOUND_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cliente_id":"+573001112233","canal":"whatsapp","texto":"Hola, tengo un taller mecánico"}'

# 6. Todo junto (API + Postgres + n8n)
docker compose up -d --build
```

## Pruebas

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not integration"            # 48 tests, sin red ni Postgres (LLM guionado)
.venv/bin/pytest -m integration                   # Postgres real (+ Haiku real si hay API key)
.venv/bin/python -m evals.run_evals --min-score 0.8   # LLM-as-judge: ¿dio precio? ¿agendó? ¿una pregunta?
```

CI (`.github/workflows/ci.yml`): ruff + pytest en cada push/PR; evals solo en `push` si existe el secreto
`ANTHROPIC_API_KEY`.

## Scripts por día del plan

| Script | Día | Para qué |
| --- | --- | --- |
| `scripts/draw_graph.py` | 1 | Mermaid del grafo. |
| `scripts/01_tool_use.py` | 2 | Tool calling en Python puro (`handoff_a_sebas`). |
| `scripts/02_perfilador_json.py` | 3 | Haiku + structured outputs → `PerfilOutput`. |
| `scripts/init_db.py` | 4-5 | Esquema + tablas del checkpointer. |
| `scripts/chat.py` | 8-10, 30 | Conversar con el motor; `:ficha`, `:etapa cerrado`. |
| `scripts/import_leads.py` / `scripts/score_leads.py` | 35-37 | Importar CSV de leads y puntuarlos. |

## Seguridad (resumen; detalle en `docs/RUNBOOK.md`)

- Secretos solo en `.env` (gitignored) y en el gestor de credenciales de n8n. `gitleaks` en pre-commit.
- `/inbound`, `/clientes`, `/metricas`: Bearer token comparado en tiempo constante.
- `/webhooks/twilio`: firma `X-Twilio-Signature` (HMAC-SHA1) obligatoria + idempotencia por `MessageSid`.
- `/webhooks/etapa` y eventos a n8n: HMAC-SHA256 con timestamp (anti-replay 5 min).
- Rate limit por `cliente_id`, límite de 4000 caracteres por mensaje, validación Pydantic de todo.
- Prompts: el contenido del cliente y de la ficha se marca como DATOS; reglas anti prompt-injection.
- SQL parametrizado, `strict: true` en herramientas, contenedor sin root y de solo lectura.
- Logs sin PII (ids enmascarados, nunca el texto de los mensajes).

## Documentación

- `docs/DESPLIEGUE.md` · paso a paso de cero a producción y a captación de clientes (4 sesiones).
- `docs/RUNBOOK.md` · operación: arrancar, reiniciar, rotar claves, revisar trazas, incidentes.
- `docs/PRIVACIDAD.md` · retención de datos y aviso de privacidad (Habeas Data / GDPR).
- `docs/COSTOS.md` · costo estimado por conversación y cómo medirlo.
- `n8n/README.md` · workflows y database de Notion.
