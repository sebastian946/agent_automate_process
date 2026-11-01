"""Día 1 · Dibuja el grafo en Mermaid (pégalo en https://mermaid.live).

Uso:  .venv/bin/python scripts/draw_graph.py
"""

from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "x")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/x")
os.environ.setdefault("INBOUND_API_TOKEN", "x")
os.environ.setdefault("N8N_WEBHOOK_SECRET", "x")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "x")

from dzlabs.config import Settings  # noqa: E402
from dzlabs.graph.build import Deps, build_graph  # noqa: E402

graph = build_graph(Deps(repo=None, client=None, settings=Settings()))  # type: ignore[arg-type]
print(graph.get_graph().draw_mermaid())
