"""Agente de Marketing (Fase 5, día 37): lead crudo → encaje 0-10 + primer mensaje por canal.

Usa el server tool web_fetch para leer la web del negocio (si tiene) y structured outputs para el JSON.
Nunca envía nada: deja el lead en estado `por_aprobar` para la revisión humana de Sebas.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from dzlabs import prompts
from dzlabs.schemas import LeadCrudo, LeadScore

log = logging.getLogger(__name__)

WEB_FETCH_TOOL: dict[str, Any] = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
    "max_uses": 2,
    "max_content_tokens": 20000,
}


def score_lead(client: anthropic.Anthropic, model: str, lead: LeadCrudo) -> LeadScore:
    system = [
        {
            "type": "text",
            "text": prompts.bloque_estable_marketing(),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    datos = lead.model_dump(mode="json", exclude={"id"})
    user = (
        "Analiza este lead y devuelve el JSON del esquema.\n"
        f"<lead>\n{json.dumps(datos, ensure_ascii=False)}\n</lead>\n"
        + (f"Lee su web antes de puntuar: {lead.web}" if lead.web else "No tiene web: puntúa con lo que hay.")
    )
    resp = client.messages.parse(
        model=model,
        max_tokens=2500,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[WEB_FETCH_TOOL] if lead.web else None,
        output_format=LeadScore,
        output_config={"effort": "medium"},
    )
    if resp.parsed_output is None:
        raise ValueError("El modelo no devolvió JSON válido")
    return resp.parsed_output
