"""Normalización de identidad: mismo cliente_id = número E.164 o email en minúsculas."""

from __future__ import annotations

import re

from dzlabs.schemas import Canal

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_EMAIL = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


class IdentidadInvalida(ValueError):
    pass


def normalizar_telefono(raw: str, default_cc: str = "+57") -> str:
    """'whatsapp:+57 300 123 4567' → '+573001234567'. Sin código de país asume Colombia."""
    s = raw.strip().lower().removeprefix("whatsapp:").removeprefix("tel:")
    s = re.sub(r"[\s\-().]", "", s)
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+"):
        s = default_cc + s.lstrip("0")
    if not _E164.match(s):
        raise IdentidadInvalida("Teléfono no válido en E.164")
    return s


def normalizar_email(raw: str) -> str:
    """Extrae y normaliza el email: 'Juan <Juan@Taller.CO>' → 'juan@taller.co'."""
    s = raw.strip().lower()
    m = re.search(r"<([^>]+)>", s)
    if m:
        s = m.group(1).strip()
    if not _EMAIL.match(s):
        raise IdentidadInvalida("Email no válido")
    return s


def normalizar_cliente_id(raw: str, canal: Canal) -> str:
    if canal == Canal.WHATSAPP:
        return normalizar_telefono(raw)
    return normalizar_email(raw)


def thread_id(cliente_id: str) -> str:
    """thread_id del checkpointer de LangGraph: una conversación continua por cliente."""
    return f"cliente:{cliente_id}"
