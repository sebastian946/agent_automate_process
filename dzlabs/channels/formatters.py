"""Formato por canal: WhatsApp corto y sin markdown; email con saludo y firma."""

from __future__ import annotations

import re

from dzlabs.schemas import Canal

FORMATO_WHATSAPP = (
    "FORMATO: Estás respondiendo por WhatsApp. Máximo 3 frases cortas. Sin markdown, sin listas "
    "con viñetas, sin negritas, sin encabezados. Puedes separar ideas con saltos de línea."
)

FORMATO_EMAIL = (
    "FORMATO: Estás respondiendo por email. Empieza con un saludo breve con el nombre si lo sabes, "
    "párrafos cortos, y termina con la firma exacta:\n\nSebas · DZ Labs\nhola@dzlabs.co"
)

_MD_PATTERNS = [
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),  # encabezados
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),  # negritas
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)"), r"\1"),  # cursivas con *
    (re.compile(r"`{1,3}([^`]*)`{1,3}"), r"\1"),  # código
    (re.compile(r"^\s*[-*•]\s+", re.M), "- "),  # viñetas → guion simple
    (re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)"), r"\1: \2"),  # links
]


def formato_para(canal: Canal) -> str:
    return FORMATO_WHATSAPP if canal == Canal.WHATSAPP else FORMATO_EMAIL


def limpiar_markdown(texto: str) -> str:
    out = texto
    for pat, rep in _MD_PATTERNS:
        out = pat.sub(rep, out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def limpiar_hilo_email(cuerpo: str) -> str:
    """Quita el texto citado del hilo anterior y las firmas típicas para no reprocesarlo."""
    lineas: list[str] = []
    for ln in cuerpo.splitlines():
        s = ln.strip()
        if s.startswith(">"):
            continue
        if re.match(r"^(el|on) .+ (escribió|wrote):?$", s, re.I):
            break
        if re.match(r"^-{2,}\s*$", s) or s.lower().startswith("enviado desde mi"):
            break
        lineas.append(ln)
    return "\n".join(lineas).strip()


def aplicar_formato_salida(texto: str, canal: Canal) -> str:
    if canal == Canal.WHATSAPP:
        txt = limpiar_markdown(texto)
        # Twilio corta mensajes > 1600 chars
        return txt[:1500]
    return texto.strip()
