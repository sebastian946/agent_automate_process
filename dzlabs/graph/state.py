"""State del grafo: lo que viaja entre nodos y se persiste por thread_id en el checkpointer."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class State(TypedDict, total=False):
    # Historial en formato Messages API (dicts). Reducer: se van agregando.
    messages: Annotated[list[dict[str, Any]], operator.add]
    cliente_id: str
    canal: str  # 'whatsapp' | 'email'
    texto: str  # mensaje entrante de este turno
    ficha: dict[str, Any]  # Ficha.model_dump(mode="json") cargada de Postgres
    agente: str  # 'ventas' | 'diagnostico' | 'soporte'
    respuesta: str  # texto final para el cliente, ya formateado por canal
    eventos: list[dict[str, Any]]  # eventos emitidos este turno (handoff, etapa, ...)


MAX_HISTORIAL = 40


def recortar_historial(msgs: list[dict[str, Any]], max_n: int = MAX_HISTORIAL) -> list[dict[str, Any]]:
    """Mantiene los últimos N mensajes empezando siempre en un mensaje de usuario con texto.

    Así nunca partimos un par tool_use/tool_result ni empezamos con un turno de assistant.
    """
    if len(msgs) <= max_n:
        return msgs
    recorte = msgs[-max_n:]
    for i, m in enumerate(recorte):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return recorte[i:]
    return recorte
