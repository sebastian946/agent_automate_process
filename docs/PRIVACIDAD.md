# Política de retención de datos y aviso de privacidad (borrador operativo)

> Borrador para revisión legal. Aplica Ley 1581 de 2012 (Habeas Data, Colombia) y, para contactos en la UE, GDPR.

## Qué datos tratamos
| Dato | Dónde | Finalidad | Base |
| --- | --- | --- | --- |
| Número de WhatsApp / email (cliente_id) | Postgres `clientes`, checkpoints; Notion (espejo) | Atender la consulta comercial y continuar la conversación | Ejecución de medidas precontractuales / consentimiento al escribirnos |
| Contenido de la conversación | Postgres `checkpoints*` | Contexto del asistente, ficha comercial | Idem |
| Ficha (empresa, rol, dolor, BANT, sugerencias) | Postgres `clientes.ficha`; Notion | Calificación y seguimiento comercial | Interés legítimo |
| Diagnóstico técnico | Postgres; página Notion | Entrega del servicio contratado | Contrato |
| Leads de marketing (nombre negocio, teléfono/email público, web) | Postgres `leads`; Notion «Outreach» | Prospección B2B semi-automática con revisión humana | Interés legítimo (datos públicos de negocio) |

Los mensajes se envían a la API de Anthropic para generar respuestas. No se usan para entrenar modelos
(términos comerciales de Anthropic). No tratamos datos sensibles; el agente tiene prohibido pedirlos.

## Retención
| Dato | Plazo | Acción |
| --- | --- | --- |
| Conversaciones (checkpoints) de leads que no avanzaron de `lead` | 90 días sin actividad | Borrar checkpoints y fila `clientes` |
| Fichas en `calificado`/`handoff`/`agendado` sin cierre | 12 meses | Anonimizar (`cliente_id` → hash) o borrar |
| Clientes (`cerrado` en adelante) | Duración del contrato + 5 años (obligaciones contables) | Conservar ficha y diagnóstico; borrar conversaciones a los 24 meses |
| Leads de marketing descartados o sin respuesta | 6 meses | Borrar |
| Logs de la API | 30 días | Rotación automática (no contienen texto de mensajes) |

Job sugerido (cron mensual):
```sql
DELETE FROM checkpoints WHERE thread_id IN (
  SELECT 'cliente:'||cliente_id FROM clientes WHERE etapa='lead' AND actualizado_en < now() - interval '90 days');
DELETE FROM clientes WHERE etapa='lead' AND actualizado_en < now() - interval '90 days';
DELETE FROM leads WHERE estado IN ('descartado','contactado') AND actualizado_en < now() - interval '6 months';
```

## Derechos de los titulares
Acceso, rectificación, supresión y revocación escribiendo a **privacidad@dzlabs.co**. Plazo de respuesta: 10 días
hábiles (Habeas Data) / 1 mes (GDPR). Procedimiento técnico de borrado: `docs/RUNBOOK.md` → «Borrar un cliente».
En email saliente de marketing siempre hay una línea para dejar de recibir correos (CAN-SPAM/GDPR).

## Aviso corto para el primer mensaje (WhatsApp/email)
> «Hola, soy el asistente de DZ Labs. Esta conversación la atiende un sistema automatizado y la revisa Sebas.
> Guardamos tus datos solo para responderte; puedes pedir que los borremos en privacidad@dzlabs.co.»

## Medidas de seguridad
Cifrado en tránsito (HTTPS), secretos fuera del código, autenticación en todos los endpoints, firma HMAC en
webhooks, acceso a Postgres solo desde la red interna, backups cifrados, logs sin PII, principio de mínimo dato.
