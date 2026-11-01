"""Día 10 · Calificación BANT: 6 conversaciones sintéticas (3 calificadas, 3 no).

La parte determinista corre siempre. La parte con LLM real (Haiku) se marca `integration` y solo
corre con ANTHROPIC_API_KEY real: `pytest -m integration tests/test_calificacion.py`.
"""

import json
import os
from pathlib import Path

import pytest
from dzlabs.schemas import PerfilOutput, es_calificado

FIXTURES = Path(__file__).parent / "fixtures" / "conversaciones_bant.json"
CASOS = json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
def test_regla_bant_sobre_perfil_esperado(caso):
    perfil = PerfilOutput.model_validate(caso["perfil_esperado"])
    assert es_calificado(perfil) is caso["calificado"]


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("ANTHROPIC_API_KEY", "").startswith("test") or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requiere ANTHROPIC_API_KEY real",
)
@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
def test_haiku_extrae_bant_y_califica(caso):
    from dzlabs.config import get_settings
    from dzlabs.graph.perfilador import perfilar
    from dzlabs.llm import get_client
    from dzlabs.schemas import Canal, Ficha

    ficha = Ficha(cliente_id="+573000000000", canal_origen=Canal.WHATSAPP)
    perfil = perfilar(get_client(), get_settings().model_perfilador, ficha, caso["mensajes"])
    assert es_calificado(perfil) is caso["calificado"], perfil.model_dump()
    assert len(perfil.sugerencias_cierre) == 3
