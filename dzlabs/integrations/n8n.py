"""Eventos hacia n8n (bordes): handoff a Sebas, cambios de etapa, diagnóstico cerrado, incidencias.

Cada POST va firmado con HMAC-SHA256 del cuerpo (header X-DZ-Signature) con N8N_WEBHOOK_SECRET.
n8n debe verificar esa firma antes de actuar (ver n8n/README.md). Si n8n no está configurado,
los eventos se loguean y se descartan: el agente nunca se cae por un borde.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Literal

import httpx

from dzlabs.config import get_settings
from dzlabs.logging_setup import mask_id

log = logging.getLogger(__name__)

TipoEvento = Literal["handoff", "etapa_cambiada", "diagnostico_cerrado", "incidencia", "lead_calificado"]


def firmar(secret: str, cuerpo: bytes) -> str:
    return hmac.new(secret.encode(), cuerpo, hashlib.sha256).hexdigest()


def verificar_firma(secret: str, cuerpo: bytes, firma: str | None, ts: str | None, tolerancia_s: int = 300) -> bool:
    """Verifica firma HMAC y antigüedad (anti-replay) de un webhook entrante firmado por n8n."""
    if not firma or not ts:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerancia_s:
            return False
    except ValueError:
        return False
    esperado = hmac.new(secret.encode(), ts.encode() + b"." + cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, firma)


def emitir_evento(tipo: TipoEvento, cliente_id: str, datos: dict[str, Any]) -> bool:
    """Envío síncrono (se usa dentro de nodos del grafo). Devuelve True si n8n respondió 2xx."""
    s = get_settings()
    if not s.n8n_webhook_url:
        log.info("n8n no configurado; evento %s para %s descartado", tipo, mask_id(cliente_id))
        return False
    payload = {"tipo": tipo, "cliente_id": cliente_id, "ts": int(time.time()), **datos}
    cuerpo = json.dumps(payload, ensure_ascii=False, default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "X-DZ-Signature": firmar(s.n8n_webhook_secret.get_secret_value(), cuerpo),
        "X-DZ-Event": tipo,
    }
    try:
        r = httpx.post(s.n8n_webhook_url, content=cuerpo, headers=headers, timeout=8)
        if r.status_code >= 300:
            log.warning("n8n respondió %s al evento %s", r.status_code, tipo)
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("No se pudo entregar evento %s a n8n: %s", tipo, e)
        return False
