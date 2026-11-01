"""Integración con Postgres real (Día 4, 5 y 9). Corre si DATABASE_URL apunta a un Postgres accesible.

Local:  docker compose up -d postgres && pytest -m integration tests/test_postgres_integration.py
"""

from __future__ import annotations

import os
import uuid

import pytest
from dzlabs.schemas import Canal, Etapa, Incidencia, LeadCrudo, LeadScore, PerfilOutput

pytestmark = pytest.mark.integration


def _pg_disponible() -> bool:
    try:
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _pg_disponible(), reason="sin Postgres")]


@pytest.fixture(scope="module")
def repo():
    from dzlabs.db.repo import Repo

    r = Repo(os.environ["DATABASE_URL"])
    r.open()
    r.ensure_schema()
    yield r
    r.close()


def test_ficha_roundtrip_y_evolucion(repo):
    cid = f"+5730{uuid.uuid4().int % 10**7:07d}"
    ficha = repo.get_or_create_ficha(cid, Canal.WHATSAPP)
    assert ficha.etapa == Etapa.LEAD and ficha.identidades == [cid]
    ficha.perfil = PerfilOutput(empresa="Taller X", necesidad="si", autoridad="si", urgencia="alta")
    ficha.avanzar_etapa(Etapa.CALIFICADO)
    repo.upsert_ficha(ficha)
    leida = repo.get_ficha(cid)
    assert leida.etapa == Etapa.CALIFICADO and leida.perfil.empresa == "Taller X"
    # Cambio externo (Notion) y auditoría
    assert repo.set_etapa(cid, Etapa.CERRADO, "notion") == Etapa.CALIFICADO
    assert repo.get_ficha(cid).etapa == Etapa.CERRADO
    assert repo.get_ficha(cid).agente_activo().value == "diagnostico"
    assert repo.set_etapa("+570000000000", Etapa.CERRADO, "notion") is None
    # Identidades
    alias = f"{uuid.uuid4().hex[:8]}@y.co"
    repo.vincular_identidad(cid, alias)
    assert repo.resolver_cliente_id(alias) == cid
    assert sorted(repo.get_ficha(cid).identidades) == sorted([cid, alias])


def test_idempotencia_incidencias_leads(repo):
    sid = f"SM{uuid.uuid4().hex}"
    assert repo.marcar_mensaje_procesado("twilio", sid)
    assert not repo.marcar_mensaje_procesado("twilio", sid)
    cid = f"+5731{uuid.uuid4().int % 10**7:07d}"
    repo.get_or_create_ficha(cid, Canal.WHATSAPP)
    assert repo.crear_incidencia(cid, Incidencia(titulo="t", descripcion="d", bloqueante=True)) > 0
    nombre = f"Taller {uuid.uuid4().hex[:6]}"
    lid = repo.insertar_lead(LeadCrudo(nombre_negocio=nombre, ciudad="Bogotá", web="https://ex.co"))
    assert lid and repo.insertar_lead(LeadCrudo(nombre_negocio=nombre, ciudad="Bogotá")) is None
    assert any(lead.id == lid for lead in repo.leads_pendientes(500))
    repo.guardar_score(lid, LeadScore(encaje=8, razon="r", mensaje_whatsapp="w", asunto_email="a", mensaje_email="e"))
    assert all(lead.id != lid for lead in repo.leads_pendientes(500))
    assert isinstance(repo.embudo(), dict)


def test_checkpointer_postgres_persiste_historial(repo, settings):
    """Día 5: el historial sobrevive a un grafo nuevo (otro proceso) con el mismo thread_id."""
    from dzlabs.graph.build import Deps, build_graph, handle_message, postgres_checkpointer

    from tests.conftest import FakeAnthropic, msg

    cid = f"+5732{uuid.uuid4().int % 10**7:07d}"
    with postgres_checkpointer(os.environ["DATABASE_URL"]) as saver:
        c1 = FakeAnthropic([msg("Hola, ¿qué negocio tienes?")])
        handle_message(build_graph(Deps(repo, c1, settings), saver), cid, "whatsapp", "primero")
    with postgres_checkpointer(os.environ["DATABASE_URL"]) as saver:
        c2 = FakeAnthropic([msg("Entiendo.")])
        handle_message(build_graph(Deps(repo, c2, settings), saver), cid, "whatsapp", "segundo")
        roles = [m["role"] for m in c2.messages.llamadas[0]["messages"]]
        assert roles == ["user", "assistant", "user"]
        assert c2.messages.llamadas[0]["messages"][0]["content"] == "primero"
    with repo.pool.connection() as conn:
        n = conn.execute("SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s", (f"cliente:{cid}",)).fetchone()[
            "n"
        ]
    assert n >= 2
    assert repo.get_ficha(cid).turnos == 2
