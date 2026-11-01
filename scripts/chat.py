"""Día 8 · Conversación en consola con el motor completo (grafo + Postgres + checkpointer).

Uso:  .venv/bin/python scripts/chat.py [cliente_id] [whatsapp|email]
      Escribe mensajes; ':ficha' muestra la ficha; ':etapa cerrado' cambia etapa; ':salir' termina.
La transcripción se guarda en tests/fixtures/transcripciones/<cliente>_<fecha>.md
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from dzlabs.graph.build import Engine  # noqa: E402
from dzlabs.logging_setup import setup_logging  # noqa: E402
from dzlabs.schemas import Canal, Etapa  # noqa: E402

cliente_id = sys.argv[1] if len(sys.argv) > 1 else "+573001112233"
canal = Canal(sys.argv[2]) if len(sys.argv) > 2 else Canal.WHATSAPP
setup_logging("WARNING")
engine = Engine().start(ensure_schema=True)
out_dir = Path("tests/fixtures/transcripciones")
out_dir.mkdir(parents=True, exist_ok=True)
log_path = out_dir / f"{cliente_id.replace('+', '').replace('@', '_at_')}_{datetime.now():%Y%m%d_%H%M}.md"
lineas = [f"# Transcripción {cliente_id} ({canal.value})", ""]

print(f"Chat con el motor como {cliente_id} por {canal.value}. ':salir' para terminar.\n")
try:
    while True:
        texto = input("Tú > ").strip()
        if not texto:
            continue
        if texto == ":salir":
            break
        if texto == ":ficha":
            print(engine.repo.get_ficha(cliente_id).model_dump_json(indent=2))
            continue
        if texto.startswith(":etapa "):
            engine.repo.set_etapa(cliente_id, Etapa(texto.split()[1]), "manual")
            print("etapa cambiada")
            continue
        respuesta = engine.handle_message(cliente_id, canal, texto)
        ficha = engine.repo.get_ficha(cliente_id)
        print(f"Agente [{ficha.etapa.value}] > {respuesta}\n")
        lineas += [f"**Cliente:** {texto}", "", f"**Agente ({ficha.etapa.value}):** {respuesta}", ""]
finally:
    log_path.write_text("\n".join(lineas), encoding="utf-8")
    engine.stop()
    print(f"\nTranscripción guardada en {log_path}")
