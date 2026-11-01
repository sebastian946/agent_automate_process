"""Día 35/36 · Importa leads desde un CSV a la tabla `leads`.

CSV con cabeceras: nombre_negocio,sector,ciudad,telefono,email,web,fuente,notas (las que falten quedan vacías).
Uso:  .venv/bin/python scripts/import_leads.py leads.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from dzlabs.config import get_settings  # noqa: E402
from dzlabs.db.repo import Repo  # noqa: E402
from dzlabs.schemas import LeadCrudo  # noqa: E402

path = Path(sys.argv[1])
repo = Repo(get_settings().database_url.get_secret_value())
repo.open()
nuevos = 0
with path.open(encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        datos = {k: (v.strip() or None) for k, v in row.items() if k}
        if not datos.get("nombre_negocio"):
            continue
        datos.setdefault("fuente", path.stem)
        if repo.insertar_lead(LeadCrudo.model_validate(datos)) is not None:
            nuevos += 1
repo.close()
print(f"{nuevos} leads nuevos importados desde {path.name}")
