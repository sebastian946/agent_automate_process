# Despliegue paso a paso · de cero a «el sistema me trae clientes»

Objetivo final: el motor **busca** negocios del ICP, **tú apruebas** el primer mensaje, el sistema lo **envía**,
el agente de Ventas **conversa y califica**, y te **avisa por WhatsApp** con la ficha y 3 sugerencias de cierre.
Tú solo entras al final: agendar y cerrar.

Tiempo estimado: 4 sesiones de 1-2 h (A: local · B: servidor · C: canales · D: captación).

---

## Sesión A · Local funcionando con LLM real (1 h)

1. **Clave de Anthropic.** console.anthropic.com → API Keys → crear. En `.env`: `ANTHROPIC_API_KEY=sk-ant-...`.
2. **LangSmith** (trazas, tokens, costo). smith.langchain.com → crea cuenta gratis → Settings → API Keys.
   En `.env`: `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=lsv2_...`, `LANGSMITH_PROJECT=dzlabs-sales-engine`.
3. **Arrancar y hablar con el agente:**
   ```bash
   docker compose up -d postgres
   .venv/bin/python scripts/init_db.py
   .venv/bin/python scripts/chat.py +573001112233 whatsapp
   ```
   Haz de cliente (taller mecánico, dueño, urgente). Verifica: pregunta una cosa a la vez, no da precio,
   llama `handoff_a_sebas` cuando pides precio. `:ficha` muestra BANT y sugerencias. `:etapa cerrado` y
   sigue hablando → ahora responde el agente de Diagnóstico.
4. **Revisa LangSmith:** proyecto `dzlabs-sales-engine` → pestaña **Threads**: verás un hilo por cliente
   (`cliente:+5730...`), y dentro cada turno con los nodos `cargar_ficha → ventas → perfilador → guardar_ficha`,
   cada llamada al LLM con tokens, `cache_read` y costo. Filtra por metadata `etapa` o `agente`.
5. **Evals con LLM real:**
   ```bash
   .venv/bin/pytest -m integration
   .venv/bin/python -m evals.run_evals --min-score 0.8
   ```
   Si un caso falla, ajusta `dzlabs/prompts/*.md` y repite. Checkpoint de la sesión: score ≥ 80 %.
6. **Commit inicial:** `pre-commit install && git add -A && git commit -m "feat: motor comercial v0.1"`, crea el repo en
   GitHub, `git push`. En GitHub → Settings → Secrets → `ANTHROPIC_API_KEY` (para los evals en CI).

---

## Sesión B · Servidor con HTTPS (1-2 h)

Recomendación: **un VPS con Docker** (Hetzner CX22 ~€6/mes o equivalente en DigitalOcean/Vultr) con Caddy como
proxy HTTPS. Railway/Fly son más simples pero salen 3-5× más caros con Postgres + n8n. Postgres nunca se expone.

1. **VPS Ubuntu 24.04** → `curl -fsSL https://get.docker.com | sh`, usuario no root con `docker` group, `ufw allow 22,80,443`.
2. **DNS:** `api.dzlabs.co` y `n8n.dzlabs.co` → IP del VPS.
3. **Clona el repo** y crea `.env` de producción:
   `ENV=prod`, `PUBLIC_BASE_URL=https://api.dzlabs.co`, `N8N_PUBLIC_URL=https://n8n.dzlabs.co/`,
   contraseñas nuevas (no reutilices las locales), `LANGSMITH_TRACING=true`.
4. **Caddy** (archivo `Caddyfile` junto al compose; añade el servicio al `docker-compose.yml` o córrelo aparte):
   ```
   api.dzlabs.co { reverse_proxy api:8000 }
   n8n.dzlabs.co { reverse_proxy n8n:5678 }
   ```
   Caddy saca y renueva certificados Let's Encrypt solo.
5. `docker compose up -d --build` → `curl https://api.dzlabs.co/health` → `{"status":"ok"}`.
6. **Backups:** cron diario `pg_dump` (ver RUNBOOK) a un bucket (Backblaze B2 / S3) cifrado.
7. **n8n:** entra a `https://n8n.dzlabs.co` (basic auth del `.env`), crea tu usuario, importa los 3 JSON de `n8n/`
   y crea las credenciales: Twilio, Notion, Gmail (OAuth), Header Auth (`Authorization: Bearer <INBOUND_API_TOKEN>`).

---

## Sesión C · Canales reales y aviso a Sebas (1-2 h)

### WhatsApp (Twilio)
1. Twilio → Messaging → **WhatsApp Sandbox** para probar hoy mismo. `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`, `SEBAS_WHATSAPP=whatsapp:+57300...`.
2. Sandbox → *When a message comes in*: `https://api.dzlabs.co/webhooks/twilio` (POST). `docker compose restart api`.
3. Desde tu celular manda el código del sandbox y luego «Hola, tengo un taller». Debes recibir respuesta en < 10 s.
4. **Para producción** (números reales de clientes): Twilio → WhatsApp Senders → registra tu número de empresa con
   Meta Business verificado (1-3 días). Los **mensajes que inicia el negocio** (outreach) exigen **plantillas
   aprobadas por Meta**; las respuestas dentro de las 24 h desde que el cliente escribe son libres.

### Email (Gmail vía n8n)
1. Google Cloud → proyecto → habilita Gmail API → credencial OAuth (tipo web) con redirect de n8n.
2. En n8n, credencial Gmail OAuth2 con la cuenta `hola@dzlabs.co`. Activa el workflow `03_gmail_entrante`.
3. Envíate un correo de prueba desde otra cuenta → responde en el mismo hilo.

### Aviso de handoff + Notion + Cal.com
1. Cal.com → evento «Llamada de 15 min · DZ Labs» → `.env`: `CAL_BOOKING_URL`.
2. Notion → database «Pipeline comercial» (propiedades en `n8n/README.md`) → copia su ID en los nodos `REEMPLAZAR`
   del workflow `01_eventos_dzlabs` → activa.
3. Prueba de fuego: conversa por WhatsApp hasta pedir precio → llega a tu celular el aviso con nombre, empresa, dolor,
   3 sugerencias de cierre, link a la ficha y link de Cal.com. La fila aparece en Notion.
4. Cuando cierres, cambia **Etapa = cerrado** en Notion → workflow `02_notion_a_postgres` → la siguiente conversación
   la lleva Diagnóstico. Comprueba en `https://api.dzlabs.co/clientes/<id>` (con Bearer).

---

## Sesión D · Captación: que el sistema busque y contacte (2 h)

### D1. Fuente de leads (Google Maps vía Apify)
1. apify.com → actor **Google Maps Scraper** (`compass/crawler-google-places`, pago por resultado, ~$2-4 por 1.000
   lugares). Búsqueda: «taller mecánico Bogotá» (o tu vertical), 100-200 resultados, exporta CSV con
   `title, phone, website, address, categoryName`.
2. Renombra columnas a `nombre_negocio,telefono,web,ciudad,sector` e importa:
   ```bash
   .venv/bin/python scripts/import_leads.py leads_talleres_bogota.csv
   ```
3. (Perfil B, EU/US) Apollo.io: búsqueda manual en la UI → exporta → enriquece emails con la API `people/match`
   (`x-api-key`; 1 crédito por email, 900 créditos gratis/año). Importa igual.

### D2. Puntuar y redactar (agente de Marketing)
```bash
.venv/bin/python scripts/score_leads.py 50
```
Cada lead queda con `encaje 0-10`, razón, señales y **mensaje de WhatsApp + email** personalizados. Los ≥ 7 pasan a
`por_aprobar`; el resto a `descartado`. Costo aproximado: $0,02-0,05 por lead (lee la web con `web_fetch`).

### D3. Tú apruebas (revisión humana obligatoria)
Hoy: `SELECT id, nombre_negocio, encaje, score->>'mensaje_whatsapp' FROM leads WHERE estado='por_aprobar';` y
`UPDATE leads SET estado='aprobado' WHERE id IN (...)`. **Propuesta (ver abajo, decisión pendiente):** cola de
aprobación en Notion con checkbox + workflow n8n que envía los aprobados.

### D4. Envío
- **Email:** dominio secundario (`dzlabs-contact.co`), warm-up 2 semanas, máximo 20-30/día al inicio, siempre con
  línea de baja. Secuencia de 3 correos (día 0, +3, +7). Herramienta: Smartlead (~$39/mes, API completa) o
  Instantly (~$47/mes); o Gmail API vía n8n si son < 20/día.
- **WhatsApp:** solo negocios con número público, **plantilla aprobada por Meta** para el primer mensaje
  (ej. «Hola {{1}}, soy Sebas de DZ Labs. Vi que {{2}}. ¿Te interesa que te cuente cómo lo automatizamos?»).
  Máximo 10-20/día al inicio; Meta vigila la tasa de bloqueos.
- **LinkedIn:** semi-manual (la IA redacta, tú envías), 20-30 acciones/día.

### D5. El ciclo se cierra solo
Cuando el lead **responde**, su mensaje entra por `/webhooks/twilio` o Gmail → `/inbound` → el agente de Ventas lo
atiende como `lead` → califica → `handoff_a_sebas` → **aviso a tu celular** → tú agendas y cierras → Notion
`cerrado` → Diagnóstico.

---

## Checklist antes de dejarlo solo
- [ ] Evals ≥ 80 % con LLM real y 10 conversaciones de prueba tuyas sin precios/agenda.
- [ ] `/health` en verde, backups diarios probados (restaura uno).
- [ ] Twilio firma OK (un POST sin firma devuelve 403 en producción).
- [ ] Aviso de handoff llega a tu celular en < 1 min.
- [ ] LangSmith: alerta si el costo diario supera X (Settings → Usage) y revisas los hilos con `etapa=handoff` cada día.
- [ ] Aviso de privacidad en el primer mensaje (ver `docs/PRIVACIDAD.md`) y línea de baja en los emails.
- [ ] Límite de gasto en console.anthropic.com (Usage limits) para no tener sorpresas.
