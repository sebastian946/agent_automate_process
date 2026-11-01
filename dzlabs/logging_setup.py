"""Logging estructurado y sin PII: nunca registramos el texto de los mensajes de clientes."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s", "%Y-%m-%dT%H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(level.upper())
    # El SDK y httpx son ruidosos en INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def mask_id(cliente_id: str) -> str:
    """Enmascara un cliente_id para logs: +57300***4567 / jo***@dominio.com."""
    if "@" in cliente_id:
        user, _, dom = cliente_id.partition("@")
        return f"{user[:2]}***@{dom}"
    if len(cliente_id) > 7:
        return f"{cliente_id[:6]}***{cliente_id[-4:]}"
    return "***"
