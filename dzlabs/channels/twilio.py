"""WhatsApp vía Twilio: validación de firma del webhook y envío de mensajes por REST.

Seguridad: todo POST a /webhooks/twilio se verifica con HMAC-SHA1 (X-Twilio-Signature) usando el
Auth Token. Sin firma válida → 403. Referencia: https://www.twilio.com/docs/usage/webhooks/webhooks-security
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping

import httpx

log = logging.getLogger(__name__)


def firma_valida(auth_token: str, url: str, params: Mapping[str, str], firma: str | None) -> bool:
    """Reproduce el algoritmo de Twilio: URL + params ordenados por clave, HMAC-SHA1, base64."""
    if not firma:
        return False
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    esperado = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()  # noqa: S324 (lo exige Twilio)
    ).decode()
    return hmac.compare_digest(esperado, firma)


async def enviar_whatsapp(
    *,
    account_sid: str,
    auth_token: str,
    desde: str,
    para: str,
    cuerpo: str,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Envía un mensaje saliente. Devuelve el MessageSid o None si falló (ya logueado)."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    para = para if para.startswith("whatsapp:") else f"whatsapp:{para}"
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        r = await client.post(
            url,
            data={"From": desde, "To": para, "Body": cuerpo[:1600]},
            auth=(account_sid, auth_token),
        )
        if r.status_code >= 300:
            log.error("Twilio rechazó el envío: %s %s", r.status_code, r.text[:200])
            return None
        return r.json().get("sid")
    except httpx.HTTPError as e:
        log.error("Error de red enviando a Twilio: %s", e)
        return None
    finally:
        if own:
            await client.aclose()
