"""Dobles de prueba: cliente Anthropic falso (guionado) y repo en memoria. Sin red, sin Postgres."""

from __future__ import annotations

import os
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost:5432/x")
os.environ.setdefault("INBOUND_API_TOKEN", "test-token")
os.environ.setdefault("N8N_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-twilio")
os.environ.setdefault("LLM_FALLBACKS", "false")
os.environ.setdefault("PUBLIC_BASE_URL", "https://api.test")

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage  # noqa: E402
from dzlabs.config import Settings  # noqa: E402
from dzlabs.schemas import Canal, Etapa, Ficha, Incidencia, LeadCrudo, LeadScore, PerfilOutput  # noqa: E402


def msg(
    texto: str | None = None,
    tool: tuple[str, dict[str, Any]] | None = None,
    stop: str | None = None,
) -> Message:
    content: list[Any] = []
    if texto:
        content.append(TextBlock(type="text", text=texto))
    if tool:
        content.append(ToolUseBlock(type="tool_use", id="toolu_1", name=tool[0], input=tool[1]))
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5-5",
        content=content,
        stop_reason=stop or ("tool_use" if tool else "end_turn"),
        usage=Usage(input_tokens=10, output_tokens=10),
    )


class _Parsed:
    def __init__(self, obj: Any) -> None:
        self.parsed_output = obj


class FakeMessages:
    def __init__(self, guion: list[Message], perfil: PerfilOutput | None, score: LeadScore | None = None):
        self.guion = list(guion)
        self.perfil = perfil or PerfilOutput()
        self.score = score
        self.llamadas: list[dict[str, Any]] = []
        self.parse_llamadas: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        kwargs.pop("betas", None)
        kwargs.pop("fallbacks", None)
        self.llamadas.append(kwargs)
        if not self.guion:
            return msg("Respuesta por defecto.")
        return self.guion.pop(0)

    def parse(self, **kwargs: Any) -> _Parsed:
        self.parse_llamadas.append(kwargs)
        if kwargs.get("output_format") is LeadScore:
            return _Parsed(self.score)
        return _Parsed(self.perfil)


class FakeAnthropic:
    def __init__(
        self,
        guion: list[Message] | None = None,
        perfil: PerfilOutput | None = None,
        score: LeadScore | None = None,
    ):
        self.messages = FakeMessages(guion or [], perfil, score)
        # client.beta.messages comparte el mismo doble (ruta con fallbacks server-side)
        self.beta = SimpleNamespace(messages=self.messages)


class FakeRepo:
    def __init__(self) -> None:
        self.fichas: dict[str, Ficha] = {}
        self.eventos: list[tuple] = []
        self.incidencias: list[Incidencia] = []
        self.leads: list[LeadCrudo] = []
        self.procesados: set[tuple[str, str]] = set()

    def open(self) -> None: ...
    def close(self) -> None: ...
    def ensure_schema(self) -> None: ...
    def ping(self) -> bool:
        return True

    def get_ficha(self, cliente_id: str) -> Ficha | None:
        f = self.fichas.get(cliente_id)
        return f.model_copy(deep=True) if f else None

    def get_or_create_ficha(self, cliente_id: str, canal: Canal) -> Ficha:
        if cliente_id not in self.fichas:
            self.fichas[cliente_id] = Ficha(cliente_id=cliente_id, canal_origen=canal, identidades=[cliente_id])
        return self.fichas[cliente_id].model_copy(deep=True)

    def upsert_ficha(self, ficha: Ficha) -> None:
        self.fichas[ficha.cliente_id] = ficha.model_copy(deep=True)

    def set_etapa(self, cliente_id: str, nueva: Etapa, origen: str) -> Etapa | None:
        f = self.fichas.get(cliente_id)
        if not f:
            return None
        anterior, f.etapa = f.etapa, nueva
        self.eventos.append((cliente_id, anterior, nueva, origen))
        return anterior

    def log_evento_etapa(self, cliente_id: str, de: Etapa | None, a: Etapa, origen: str) -> None:
        self.eventos.append((cliente_id, de, a, origen))

    def marcar_mensaje_procesado(self, proveedor: str, mensaje_id: str) -> bool:
        clave = (proveedor, mensaje_id)
        if clave in self.procesados:
            return False
        self.procesados.add(clave)
        return True

    def crear_incidencia(self, cliente_id: str, inc: Incidencia) -> int:
        self.incidencias.append(inc)
        return len(self.incidencias)

    def embudo(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.fichas.values():
            out[f.etapa.value] = out.get(f.etapa.value, 0) + 1
        return out


@pytest.fixture
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@pytest.fixture
def fake_repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def make_graph(settings: Settings, fake_repo: FakeRepo) -> Callable[..., Any]:
    from dzlabs.graph.build import Deps, build_graph

    def _make(guion: list[Message] | None = None, perfil: PerfilOutput | None = None):
        client = FakeAnthropic(guion, perfil)
        graph = build_graph(Deps(fake_repo, client, settings))  # type: ignore[arg-type]
        return graph, client

    return _make
