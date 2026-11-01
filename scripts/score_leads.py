"""Día 37 · Marketing: puntúa leads crudos de la tabla `leads` y los deja en `por_aprobar` o `descartado`.

Uso:  .venv/bin/python scripts/score_leads.py [limite]
Antes: importa leads con scripts/import_leads.py (CSV de Apify/Apollo/manual).
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from dzlabs.config import get_settings  # noqa: E402
from dzlabs.db.repo import Repo  # noqa: E402
from dzlabs.llm import get_client  # noqa: E402
from dzlabs.marketing.scorer import score_lead  # noqa: E402

limite = int(sys.argv[1]) if len(sys.argv) > 1 else 10
s = get_settings()
repo = Repo(s.database_url.get_secret_value())
repo.open()
client = get_client()
for lead in repo.leads_pendientes(limite):
    try:
        score = score_lead(client, s.model_marketing, lead)
    except Exception as e:  # noqa: BLE001
        print(f"✗ {lead.nombre_negocio}: {e}")
        continue
    repo.guardar_score(lead.id, score)
    print(f"✓ {lead.nombre_negocio}: encaje {score.encaje}/10 · {score.razon}")
    print(f"   WA: {score.mensaje_whatsapp[:120]}...")
repo.close()
