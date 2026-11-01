"""Día 4/5 · Aplica schema.sql, crea tablas del checkpointer y prueba la conexión.

Uso:  .venv/bin/python scripts/init_db.py
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from dzlabs.config import get_settings  # noqa: E402
from dzlabs.db.repo import Repo  # noqa: E402
from dzlabs.graph.build import postgres_checkpointer  # noqa: E402

url = get_settings().database_url.get_secret_value()
repo = Repo(url)
repo.open()
repo.ensure_schema()
print("schema.sql aplicado ✓  (ping:", repo.ping(), ")")
with postgres_checkpointer(url):
    print("tablas checkpoints* de LangGraph listas ✓")
with repo.pool.connection() as conn:
    tablas = [
        r["table_name"]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
        ).fetchall()
    ]
print("tablas:", ", ".join(tablas))
repo.close()
