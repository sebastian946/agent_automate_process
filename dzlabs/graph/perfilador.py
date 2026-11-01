"""Perfilador (Haiku): structured output → PerfilOutput, actualiza la ficha y aplica la regla BANT."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from dzlabs import prompts
from dzlabs.schemas import Etapa, Ficha, PerfilOutput, es_calificado

log = logging.getLogger(__name__)


def transcript(messages: list[dict[str, Any]], ultimos: int = 12) -> str:
    """Convierte el historial (bloques Messages API) a texto plano 'Cliente:/Asistente:'."""
    lineas: list[str] = []
    for m in messages[-ultimos:]:
        role = "Cliente" if m["role"] == "user" else "Asistente"
        content = m["content"]
        if isinstance(content, str):
            lineas.append(f"{role}: {content}")
            continue
        for b in content:
            if b.get("type") == "text" and b.get("text"):
                lineas.append(f"{role}: {b['text']}")
            elif b.get("type") == "tool_use":
                lineas.append(f"[Asistente llamó la herramienta {b.get('name')}]")
    return "\n".join(lineas)


def perfilar(client: anthropic.Anthropic, model: str, ficha: Ficha, messages: list[dict[str, Any]]) -> PerfilOutput:
    """Una llamada a Haiku con esquema Pydantic. Si falla, conserva el perfil anterior."""
    system = [{"type": "text", "text": prompts.load("perfilador"), "cache_control": {"type": "ephemeral"}}]
    user = (
        f"<ficha_actual>\n{ficha.perfil.model_dump_json()}\n</ficha_actual>\n\n"
        f"<conversacion>\n{transcript(messages)}\n</conversacion>"
    )
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=PerfilOutput,
            output_config={"effort": "low"},
        )
        if resp.parsed_output is None:
            raise ValueError("parsed_output vacío")
        return resp.parsed_output
    except (anthropic.APIError, ValueError) as e:
        log.warning("Perfilador falló (%s); se conserva el perfil anterior", e)
        return ficha.perfil


def aplicar_perfil(ficha: Ficha, perfil: PerfilOutput) -> Etapa | None:
    """Actualiza perfil y, si aplica la regla BANT, avanza a calificado. Devuelve la etapa nueva."""
    ficha.perfil = perfil
    if ficha.etapa == Etapa.LEAD and es_calificado(perfil) and ficha.avanzar_etapa(Etapa.CALIFICADO):
        return Etapa.CALIFICADO
    return None
