# Runbook · Motor comercial DZ Labs

## Servicios
| Servicio | Puerto local | Cómo saber si está bien |
| --- | --- | --- |
| `postgres` | 5432 | `docker compose exec postgres pg_isready` |
| `api` (FastAPI) | 8000 | `curl localhost:8000/health` → `{"status":"ok"}` |
| `n8n` | 5678 | abrir http://localhost:5678 (basic auth del `.env`) |

## Operaciones frecuentes
```bash
docker compose up -d --build          # arrancar / actualizar
docker compose restart api            # reiniciar solo la API
docker compose logs -f api            # ver logs (sin PII: ids enmascarados)
docker compose down                   # parar (los datos quedan en volúmenes pgdata, n8n_data)
```

### Cambiar la etapa de un cliente a mano
```sql
-- docker compose exec postgres psql -U dzlabs dzlabs
UPDATE clientes SET etapa='cerrado', ficha = ficha || '{"etapa":"cerrado"}' WHERE cliente_id='+573001234567';
INSERT INTO eventos_etapa (cliente_id, de, a, origen) VALUES ('+573001234567','handoff','cerrado','manual');
```
O desde el chat de consola: `scripts/chat.py` → `:etapa cerrado`.

### Ver cómo evoluciona una ficha (Día 9)
```sql
SELECT cliente_id, etapa, ficha->'perfil'->>'producto_interes' AS producto,
       ficha->'perfil'->'objeciones' AS objeciones, ficha->'perfil'->'sugerencias_cierre' AS sugerencias,
       actualizado_en
FROM clientes ORDER BY actualizado_en DESC LIMIT 10;

SELECT * FROM eventos_etapa ORDER BY creado_en DESC LIMIT 20;      -- embudo / auditoría
SELECT thread_id, count(*) FROM checkpoints GROUP BY 1;             -- historial por cliente
```

### Borrar un cliente (derecho de supresión)
```sql
DELETE FROM checkpoints WHERE thread_id = 'cliente:+573001234567';
DELETE FROM checkpoint_blobs WHERE thread_id = 'cliente:+573001234567';
DELETE FROM checkpoint_writes WHERE thread_id = 'cliente:+573001234567';
DELETE FROM clientes WHERE cliente_id = '+573001234567';   -- cascada a eventos_etapa e incidencias
```
Y borra la fila en la database de Notion.

## Rotación de claves
| Clave | Dónde se usa | Cómo rotar |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | API | Crear nueva en console.anthropic.com → `.env` → `docker compose restart api` → revocar la vieja. |
| `INBOUND_API_TOKEN` | API ↔ n8n | `python -c "import secrets;print(secrets.token_urlsafe(32))"` → `.env` + credencial Header Auth en n8n → reiniciar ambos. |
| `N8N_WEBHOOK_SECRET` | API ↔ n8n (HMAC) | Igual que arriba; es variable de entorno de n8n (`DZ_WEBHOOK_SECRET`) → `docker compose up -d`. |
| `TWILIO_AUTH_TOKEN` | firma webhooks + envío | Rotar en consola Twilio (tiene «secondary token» para rotar sin corte) → `.env`. |
| `POSTGRES_PASSWORD` | todos | `ALTER USER dzlabs PASSWORD '...'` → `.env` → `docker compose up -d`. |
| `N8N_ENCRYPTION_KEY` | n8n | **No rotar** sin exportar credenciales: cifra las credenciales guardadas. |

## Observabilidad
- **Logs**: cada turno escribe `turno ok cliente=+5730***4567 canal=whatsapp etapa=lead agente=ventas eventos=0`.
- **LangSmith** (Día 12): exporta `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` en `.env`;
  LangGraph traza cada nodo automáticamente. Alternativa open source: Langfuse.
- **Tokens/costo**: `response.usage` (incluye `cache_read_input_tokens`). Si `cache_read_input_tokens` es 0
  en llamadas repetidas, algo cambia en el bloque estable del system (ver `docs/COSTOS.md`).
- **Request IDs** de Anthropic: `response._request_id`; se ven en los logs de error del SDK.

## Incidentes típicos
| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| Cliente recibe «Dame un momento y te respondo enseguida» | Error/timeout del LLM (se devuelve el fallback) | `docker compose logs api` → buscar `Error LLM`. Revisar clave, cuota, status.anthropic.com. |
| Twilio responde 403 | `PUBLIC_BASE_URL` no coincide con la URL pública del webhook (ngrok/túnel) | Debe ser exactamente el host:puerto que Twilio llama (https). |
| Twilio reintenta y hay respuestas dobles | Más de 15 s sin 200 | Ya respondemos 200 de inmediato y enviamos por REST; revisar que `TWILIO_ACCOUNT_SID`/`FROM` estén en `.env`. |
| `/webhooks/etapa` 403 | Reloj desfasado o secreto distinto en n8n | Comparar `N8N_WEBHOOK_SECRET` con `DZ_WEBHOOK_SECRET`; timestamp ±5 min. |
| 400 «fallbacks» en logs | La beta de fallbacks no está disponible en la cuenta | Se degrada solo; para silenciar `LLM_FALLBACKS=false`. |
| 400 por `temperature` / `tool_choice` | Código viejo | Los modelos actuales no aceptan `temperature` ni `tool_choice` forzado; usar `output_config.effort` y prompt. |
| Historial muy largo / tokens altos | Conversación de muchos turnos | El grafo recorta a 40 mensajes al llamar al LLM; el checkpoint completo sigue en Postgres. |

## Deploy a VPS (Día 27)
1. VPS (Hetzner CX22 basta) con Docker. Clonar repo, `.env` con `ENV=prod`, `PUBLIC_BASE_URL=https://api.tudominio.co`.
2. Reverse proxy con HTTPS (Caddy): `api.tudominio.co → api:8000`, `n8n.tudominio.co → n8n:5678`. Nunca expongas 5432.
3. `docker compose up -d --build`. En prod `ensure_schema` no corre: aplica `dzlabs/db/schema.sql` una vez con psql.
4. Backups: `docker compose exec postgres pg_dump -U dzlabs dzlabs | gzip > backup_$(date +%F).sql.gz` (cron diario, guardar fuera del VPS).
5. Twilio webhook → `https://api.tudominio.co/webhooks/twilio`. n8n `WEBHOOK_URL=https://n8n.tudominio.co/`.
