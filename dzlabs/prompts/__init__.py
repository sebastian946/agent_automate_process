"""Carga de prompts versionados (archivos .md en este directorio)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load(nombre: str) -> str:
    """Devuelve el contenido de prompts/<nombre>.md (cacheado en memoria)."""
    path = _DIR / f"{nombre}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt no encontrado: {path.name}")
    return path.read_text(encoding="utf-8").strip()


def bloque_estable_ventas() -> str:
    """Bloque largo y estable (rol + catálogo + reglas) → se cachea en la API (prompt caching)."""
    return "\n\n---\n\n".join([load("ventas"), load("catalogo"), load("reglas_ventas")])


def bloque_estable_diagnostico() -> str:
    return "\n\n---\n\n".join([load("diagnostico"), load("catalogo")])


def bloque_estable_soporte() -> str:
    return load("soporte")


def bloque_estable_marketing() -> str:
    return "\n\n---\n\n".join([load("marketing"), load("icp"), load("catalogo")])
