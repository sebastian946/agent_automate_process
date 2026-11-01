"""Cliente Anthropic compartido + helpers de llamada con timeout, reintentos y fallbacks.

Puntos clave (API 2026):
- Sonnet 5.5 / Haiku 5.5 traen *adaptive thinking* encendido; se controla con output_config.effort.
  No se envía `temperature` (devuelve 400 en los modelos actuales).
- `tool_choice` forzado no existe en Sonnet 5.5: se guía desde el prompt con tool_choice=auto.
- Los bloques `thinking` de la respuesta se devuelven intactos en el historial (misma conversación).
- Fallbacks server-side (beta): si un clasificador de seguridad rechaza, la API reintenta con otro
  modelo dentro de la misma llamada. Se desactiva con LLM_FALLBACKS=false.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import anthropic

from dzlabs.config import get_settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    s = get_settings()
    client = anthropic.Anthropic(
        api_key=s.anthropic_api_key.get_secret_value(),
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,  # el SDK ya reintenta 429/5xx/conexión con backoff
    )
    if s.langsmith_tracing:
        # Cada llamada (messages, beta.messages, parse) aparece en LangSmith con tokens, caché y costo.
        from langsmith.wrappers import wrap_anthropic

        client = wrap_anthropic(client)
        log.info("LangSmith activo: trazas del LLM habilitadas")
    return client


def crear_mensaje(
    *,
    model: str,
    system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 1024,
    effort: str = "low",
    client: anthropic.Anthropic | None = None,
) -> anthropic.types.Message:
    """Llamada al Messages API con prompt caching en el system y fallbacks opcionales."""
    client = client or get_client()
    s = get_settings()
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "output_config": {"effort": effort},
    }
    if tools:
        kwargs["tools"] = tools

    if s.llm_fallbacks:
        try:
            return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        except anthropic.BadRequestError as e:
            # Si la cuenta/plataforma no soporta la beta, degradamos sin fallbacks y avisamos.
            if "fallback" in str(e).lower() or "beta" in str(e).lower():
                log.warning("Fallbacks no disponibles (%s); reintento sin fallbacks", e.message)
            else:
                raise
    return client.messages.create(**kwargs)


def texto_de(response: anthropic.types.Message) -> str:
    """Concatena los bloques de texto de una respuesta."""
    return "".join(b.text for b in response.content if b.type == "text").strip()


def contenido_a_dicts(response: anthropic.types.Message) -> list[dict[str, Any]]:
    """Serializa response.content para guardarlo en el state (incluye thinking/tool_use intactos)."""
    return [b.model_dump(mode="json", exclude_none=True) for b in response.content]


def verificar_stop(response: anthropic.types.Message) -> None:
    """Lanza si el modelo fue rechazado por seguridad o se cortó por max_tokens."""
    if response.stop_reason == "refusal":
        detalle = getattr(response, "stop_details", None)
        cat = getattr(detalle, "category", None) if detalle else None
        raise RefusalError(f"El modelo rechazó la petición (categoría={cat})")
    if response.stop_reason == "max_tokens":
        log.warning("Respuesta cortada por max_tokens; considera subir el límite")


class RefusalError(RuntimeError):
    pass
