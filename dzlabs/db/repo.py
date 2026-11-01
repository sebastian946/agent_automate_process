"""Acceso a Postgres con psycopg 3 + pool. Todas las consultas son parametrizadas (sin f-strings SQL)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from dzlabs.schemas import Canal, Etapa, Ficha, Incidencia, LeadCrudo, LeadScore

log = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Repo:
    """Repositorio de la ficha, leads e incidencias. Una instancia por proceso."""

    def __init__(self, conninfo: str, min_size: int = 1, max_size: int = 8) -> None:
        self.pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    # ------------------------------------------------------------------ ciclo de vida
    def open(self) -> None:
        self.pool.open()
        self.pool.wait()

    def close(self) -> None:
        self.pool.close()

    def ensure_schema(self) -> None:
        """Aplica schema.sql (idempotente). Útil en dev/tests; en prod lo hace el initdb de Docker."""
        with self.pool.connection() as conn:
            conn.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def ping(self) -> bool:
        with self.pool.connection() as conn:
            return conn.execute("SELECT 1").fetchone() is not None

    # ------------------------------------------------------------------ clientes / ficha
    def get_ficha(self, cliente_id: str) -> Ficha | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT cliente_id, canal_origen, etapa, ficha, identidades FROM clientes WHERE cliente_id = %s",
                (cliente_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row["ficha"] or {})
        data.update(
            cliente_id=row["cliente_id"],
            canal_origen=row["canal_origen"],
            etapa=row["etapa"],
            identidades=row["identidades"] or [],
        )
        return Ficha.model_validate(data)

    def resolver_cliente_id(self, identidad: str) -> str | None:
        """Si `identidad` es un alias registrado en identidades[], devuelve el cliente_id principal."""
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT cliente_id FROM clientes WHERE identidades @> %s LIMIT 1",
                (Jsonb([identidad]),),
            ).fetchone()
        return row["cliente_id"] if row else None

    def get_or_create_ficha(self, cliente_id: str, canal: Canal) -> Ficha:
        ficha = self.get_ficha(cliente_id)
        if ficha:
            return ficha
        ficha = Ficha(cliente_id=cliente_id, canal_origen=canal, identidades=[cliente_id])
        self.upsert_ficha(ficha)
        return ficha

    def upsert_ficha(self, ficha: Ficha) -> None:
        ficha.actualizado_en = datetime.now(UTC)
        payload = ficha.model_dump(mode="json", exclude={"cliente_id", "canal_origen", "identidades"})
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO clientes (cliente_id, canal_origen, etapa, ficha, identidades)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (cliente_id) DO UPDATE SET
                    etapa = EXCLUDED.etapa,
                    ficha = EXCLUDED.ficha,
                    identidades = EXCLUDED.identidades,
                    actualizado_en = now()
                """,
                (
                    ficha.cliente_id,
                    ficha.canal_origen.value,
                    ficha.etapa.value,
                    Jsonb(payload),
                    Jsonb(ficha.identidades),
                ),
            )

    def set_etapa(self, cliente_id: str, nueva: Etapa, origen: str) -> Etapa | None:
        """Cambio de etapa externo (Notion, Cal.com, manual). Devuelve la etapa anterior."""
        with self.pool.connection() as conn, conn.transaction():
            row = conn.execute("SELECT etapa FROM clientes WHERE cliente_id = %s FOR UPDATE", (cliente_id,)).fetchone()
            if not row:
                return None
            anterior = row["etapa"]
            conn.execute(
                "UPDATE clientes SET etapa = %s, ficha = ficha || %s, actualizado_en = now() WHERE cliente_id = %s",
                (nueva.value, Jsonb({"etapa": nueva.value}), cliente_id),
            )
            conn.execute(
                "INSERT INTO eventos_etapa (cliente_id, de, a, origen) VALUES (%s, %s, %s, %s)",
                (cliente_id, anterior, nueva.value, origen),
            )
        return Etapa(anterior)

    def log_evento_etapa(self, cliente_id: str, de: Etapa | None, a: Etapa, origen: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO eventos_etapa (cliente_id, de, a, origen) VALUES (%s, %s, %s, %s)",
                (cliente_id, de.value if de else None, a.value, origen),
            )

    def vincular_identidad(self, cliente_id: str, alias: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE clientes SET identidades = (SELECT jsonb_agg(DISTINCT x) FROM "
                "jsonb_array_elements(identidades || %s) AS x), actualizado_en = now() "
                "WHERE cliente_id = %s",
                (Jsonb([alias]), cliente_id),
            )

    # ------------------------------------------------------------------ idempotencia webhooks
    def marcar_mensaje_procesado(self, proveedor: str, mensaje_id: str) -> bool:
        """True si es la primera vez que vemos este mensaje (y lo registra)."""
        with self.pool.connection() as conn:
            cur = conn.execute(
                "INSERT INTO mensajes_procesados (proveedor, mensaje_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (proveedor, mensaje_id),
            )
            return cur.rowcount == 1

    # ------------------------------------------------------------------ incidencias
    def crear_incidencia(self, cliente_id: str, inc: Incidencia) -> int:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO incidencias (cliente_id, titulo, descripcion, bloqueante) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (cliente_id, inc.titulo, inc.descripcion, inc.bloqueante),
            ).fetchone()
        return int(row["id"])

    # ------------------------------------------------------------------ leads (marketing)
    def insertar_lead(self, lead: LeadCrudo) -> int | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO leads (nombre_negocio, sector, ciudad, telefono, email, web, fuente, notas)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (nombre_negocio, ciudad) DO NOTHING
                RETURNING id
                """,
                (
                    lead.nombre_negocio,
                    lead.sector,
                    lead.ciudad,
                    lead.telefono,
                    lead.email,
                    lead.web,
                    lead.fuente,
                    lead.notas,
                ),
            ).fetchone()
        return int(row["id"]) if row else None

    def leads_pendientes(self, limite: int = 20) -> list[LeadCrudo]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, nombre_negocio, sector, ciudad, telefono, email, web, fuente, notas "
                "FROM leads WHERE estado = 'crudo' ORDER BY id LIMIT %s",
                (limite,),
            ).fetchall()
        return [LeadCrudo.model_validate(dict(r)) for r in rows]

    def guardar_score(self, lead_id: int, score: LeadScore, umbral: int = 7) -> None:
        estado = "por_aprobar" if score.encaje >= umbral else "descartado"
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE leads SET encaje = %s, score = %s, estado = %s, actualizado_en = now() WHERE id = %s",
                (score.encaje, Jsonb(score.model_dump(mode="json")), estado, lead_id),
            )

    # ------------------------------------------------------------------ métricas
    def embudo(self) -> dict[str, Any]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT etapa, count(*) AS n FROM clientes GROUP BY etapa").fetchall()
        return {r["etapa"]: int(r["n"]) for r in rows}
