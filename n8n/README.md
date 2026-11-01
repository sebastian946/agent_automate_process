# Workflows de n8n (bordes del sistema)

Importa cada JSON en n8n (menú ⋯ → *Import from file*). Todos leen variables de entorno definidas en
`docker-compose.yml` (`DZ_API_URL`, `DZ_INBOUND_TOKEN`, `DZ_WEBHOOK_SECRET`, `DZ_SEBAS_WHATSAPP`, `DZ_TWILIO_FROM`, `DZ_CAL_URL`).

| Archivo | Día | Qué hace |
| --- | --- | --- |
| `01_eventos_dzlabs.json` | 15-16, 18, 31, 32 | Webhook `POST /webhook/dzlabs-eventos`. Verifica la firma HMAC `X-DZ-Signature`, y según `tipo`: **handoff** → formatea y manda WhatsApp a Sebas (Twilio) con link de Cal.com; **lead_calificado / etapa_cambiada** → upsert en la database de Notion «Pipeline comercial»; **diagnostico_cerrado** → crea página «Diagnóstico · {empresa}» en Notion; **incidencia** bloqueante → aviso a Sebas. |
| `02_notion_a_postgres.json` | 19 | Trigger de Notion (página actualizada en «Pipeline comercial»). Si la Etapa cambió a `cerrado` o `agendado`, firma el body y llama `POST /webhooks/etapa` de la API. |
| `03_gmail_entrante.json` | 24 | Gmail Trigger (bandeja `hola@dzlabs.co`): extrae remitente y texto, limpia hilo citado, llama `POST /inbound` con `canal=email` y responde en el mismo hilo. |

## Seguridad
- **Entrante a n8n:** el nodo *Code · Verificar firma* recalcula `HMAC-SHA256(secret, body)` y compara con `X-DZ-Signature`. Si no coincide, el flujo termina con 403.
- **Saliente a la API (`/webhooks/etapa`):** el nodo *Code · Firmar* genera `X-DZ-Timestamp` (epoch) y `X-DZ-Signature = HMAC-SHA256(secret, ts + "." + body)`. La API rechaza firmas viejas (>5 min).
- Credenciales de Twilio, Notion y Gmail se guardan en el gestor de credenciales de n8n (cifradas con `N8N_ENCRYPTION_KEY`), nunca en el JSON.

## Database «Pipeline comercial» en Notion (Día 17)
Propiedades: `Cliente` (title), `Empresa` (text), `Canal` (select), `Etapa` (select: lead, calificado, handoff, agendado, cerrado, diagnostico, entrega), `Producto` (select), `Dolor` (text), `Sugerencias` (text), `Última sesión` (date), `cliente_id` (text, único).
Pega el ID de la database en el nodo *Notion · Upsert* de `01_eventos_dzlabs.json`.
