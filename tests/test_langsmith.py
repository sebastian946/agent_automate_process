"""LangSmith: el cliente se envuelve solo si LANGSMITH_TRACING=true y los turnos llevan metadata de hilo."""

import inspect

from dzlabs import llm
from dzlabs.config import Settings


def _client_con(monkeypatch, tracing: str):
    monkeypatch.setenv("LANGSMITH_TRACING", tracing)
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")  # el wrapper no envía nada en tests: tracing_context
    llm.get_client.cache_clear()
    monkeypatch.setattr(llm, "get_settings", lambda: Settings())  # type: ignore[call-arg]
    try:
        return llm.get_client()
    finally:
        llm.get_client.cache_clear()


def test_sin_tracing_cliente_plano(monkeypatch):
    c = _client_con(monkeypatch, "false")
    # El SDK expone métodos ligados; el wrapper de LangSmith los sustituye por funciones trazadas
    assert inspect.ismethod(c.messages.create)


def test_con_tracing_cliente_envuelto(monkeypatch):
    c = _client_con(monkeypatch, "true")
    assert not inspect.ismethod(c.messages.create)
    assert not inspect.ismethod(c.beta.messages.create)


def test_turno_lleva_metadata_de_hilo(make_graph, monkeypatch):
    from dzlabs.graph import build
    from langsmith import tracing_context

    from tests.conftest import msg

    capturado = {}

    def fake_invocar(graph, inputs, config, langsmith_extra=None):
        capturado.update(config["metadata"])
        capturado["extra"] = langsmith_extra["metadata"]
        return graph.invoke(inputs, config={"configurable": config["configurable"]})

    monkeypatch.setattr(build, "_invocar", fake_invocar)
    graph, _ = make_graph([msg("hola")])
    with tracing_context(enabled=False):
        build.handle_message(graph, "+573001234567", "whatsapp", "hola")
    assert capturado["thread_id"] == "cliente:+573001234567"
    assert capturado["session_id"] == capturado["thread_id"]
    assert capturado["cliente"] == "+57300***4567"  # enmascarado, sin PII completa
    assert capturado["extra"]["canal"] == "whatsapp"
