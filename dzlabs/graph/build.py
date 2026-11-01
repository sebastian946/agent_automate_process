"""Construcción del grafo y punto de entrada handle_message()."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langsmith import traceable
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from dzlabs.channels.identity import thread_id
from dzlabs.config import Settings, get_settings
from dzlabs.db.repo import Repo
from dzlabs.graph.nodes import RESPUESTA_FALLBACK, Deps, make_nodes, router
from dzlabs.graph.state import State
from dzlabs.llm import RefusalError, get_client
from dzlabs.logging_setup import mask_id
from dzlabs.schemas import Canal

log = logging.getLogger(__name__)


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver | None = None):
    """START → cargar_ficha → (router) → ventas→perfilador | diagnostico | soporte → guardar_ficha → END"""
    nodes = make_nodes(deps)
    g = StateGraph(State)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "cargar_ficha")
    g.add_conditional_edges(
        "cargar_ficha",
        router,
        {"ventas": "ventas", "diagnostico": "diagnostico", "soporte": "soporte"},
    )
    g.add_edge("ventas", "perfilador")
    g.add_edge("perfilador", "guardar_ficha")
    g.add_edge("diagnostico", "guardar_ficha")
    g.add_edge("soporte", "guardar_ficha")
    g.add_edge("guardar_ficha", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


@contextmanager
def postgres_checkpointer(conninfo: str) -> Iterator[PostgresSaver]:
    """PostgresSaver con pool propio (autocommit + prepare_threshold=0 como exige LangGraph)."""
    pool = ConnectionPool(
        conninfo,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    try:
        saver = PostgresSaver(pool)
        saver.setup()  # crea tablas checkpoints* si no existen (idempotente)
        yield saver
    finally:
        pool.close()


class Engine:
    """Agrupa repo + grafo + checkpointer para la API y los scripts."""

    def __init__(self, settings: Settings | None = None, client: anthropic.Anthropic | None = None):
        self.settings = settings or get_settings()
        self.repo = Repo(self.settings.database_url.get_secret_value())
        self.client = client or get_client()
        self._cp_ctx = None
        self.graph = None

    def start(self, ensure_schema: bool = False) -> Engine:
        self.repo.open()
        if ensure_schema:
            self.repo.ensure_schema()
        self._cp_ctx = postgres_checkpointer(self.settings.database_url.get_secret_value())
        saver = self._cp_ctx.__enter__()
        self.graph = build_graph(Deps(self.repo, self.client, self.settings), saver)
        return self

    def stop(self) -> None:
        if self._cp_ctx:
            self._cp_ctx.__exit__(None, None, None)
        self.repo.close()

    def handle_message(self, cliente_id: str, canal: Canal | str, texto: str) -> str:
        return handle_message(self.graph, cliente_id, canal, texto)


@traceable(name="turno_conversacion", run_type="chain")
def _invocar(graph, inputs: dict, config: dict) -> dict:
    """Trace raíz de un turno. Con LANGSMITH_TRACING=false el decorador no hace nada."""
    return graph.invoke(inputs, config=config)


def handle_message(graph, cliente_id: str, canal: Canal | str, texto: str) -> str:
    """Un turno de conversación. Siempre devuelve un texto (nunca propaga la excepción al canal)."""
    canal = Canal(canal)
    tid = thread_id(cliente_id)
    # thread_id/session_id en metadata agrupan los turnos de un cliente como hilo en LangSmith.
    # Nunca enviamos el cliente_id completo a la traza (PII); solo la versión enmascarada.
    metadata = {"thread_id": tid, "session_id": tid, "canal": canal.value, "cliente": mask_id(cliente_id)}
    config = {"configurable": {"thread_id": tid}, "metadata": metadata}
    try:
        out = _invocar(
            graph,
            {"cliente_id": cliente_id, "canal": canal.value, "texto": texto[:4000]},
            config,
            langsmith_extra={"metadata": metadata},
        )
        return out["respuesta"]
    except RefusalError as e:
        log.warning("Refusal para %s: %s", mask_id(cliente_id), e)
        return "Prefiero no responder a eso. ¿Te puedo ayudar con algo de tu negocio?"
    except anthropic.APIError as e:
        log.error("Error LLM para %s: %s", mask_id(cliente_id), e)
        return RESPUESTA_FALLBACK
