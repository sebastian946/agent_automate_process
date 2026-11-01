"""Día 3 · Structured outputs: Haiku devuelve el JSON del Perfilador validado con Pydantic.

Corre 3 conversaciones de prueba y muestra el perfil + si califica por BANT.
Uso:  .venv/bin/python scripts/02_perfilador_json.py
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from dzlabs.config import get_settings  # noqa: E402
from dzlabs.graph.perfilador import perfilar  # noqa: E402
from dzlabs.llm import get_client  # noqa: E402
from dzlabs.schemas import Canal, Ficha, es_calificado  # noqa: E402

casos = json.loads(Path("tests/fixtures/conversaciones_bant.json").read_text(encoding="utf-8"))[:3]
client = get_client()
for caso in casos:
    ficha = Ficha(cliente_id="+573000000000", canal_origen=Canal.WHATSAPP)
    perfil = perfilar(client, get_settings().model_perfilador, ficha, caso["mensajes"])
    print(f"\n=== {caso['id']} (esperado calificado={caso['calificado']}) ===")
    print(perfil.model_dump_json(indent=2))
    print("→ es_calificado:", es_calificado(perfil))
