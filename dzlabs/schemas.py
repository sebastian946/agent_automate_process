"""Modelos Pydantic: ficha del cliente, salida del Perfilador, Diagnóstico y scoring de Marketing.

La ficha vive en Postgres (clientes.ficha JSONB). Estos modelos validan todo lo que entra y sale
del LLM, para que un JSON malformado nunca llegue a la base de datos.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Etapa(StrEnum):
    """Las 7 etapas del pipeline. El orden importa: nunca se retrocede automáticamente."""

    LEAD = "lead"
    CALIFICADO = "calificado"
    HANDOFF = "handoff"
    AGENDADO = "agendado"
    CERRADO = "cerrado"
    DIAGNOSTICO = "diagnostico"
    ENTREGA = "entrega"


ORDEN_ETAPAS: dict[Etapa, int] = {e: i for i, e in enumerate(Etapa)}


class Canal(StrEnum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class Agente(StrEnum):
    VENTAS = "ventas"
    DIAGNOSTICO = "diagnostico"
    SOPORTE = "soporte"


class Producto(StrEnum):
    DIAGNOSTICO_TECNICO = "diagnostico_tecnico"
    SPRINT = "sprint_automatizacion"
    RETAINER = "retainer_desarrollo"
    INDEFINIDO = "indefinido"


# ----------------------------------------------------------------------------- Perfilador


class PerfilOutput(BaseModel):
    """Lo que Haiku devuelve tras cada turno (structured output). Todo opcional salvo listas."""

    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(None, description="Nombre de la persona si lo dijo")
    empresa: str | None = Field(None, description="Nombre del negocio")
    sector: str | None = Field(None, description="Sector/vertical, ej. taller mecánico, clínica")
    rol: str | None = Field(None, description="Cargo o rol del contacto")
    tamano_equipo: str | None = Field(None, description="Personas o señal de tamaño")
    producto_interes: Producto = Field(Producto.INDEFINIDO)
    dolor: str | None = Field(None, description="Problema principal en 1 frase")
    # BANT
    presupuesto: Literal["si", "no", "desconocido"] = "desconocido"
    autoridad: Literal["si", "no", "desconocido"] = "desconocido"
    necesidad: Literal["si", "no", "desconocido"] = "desconocido"
    urgencia: Literal["alta", "media", "baja", "desconocido"] = "desconocido"
    objeciones: list[str] = Field(default_factory=list, max_length=10)
    sugerencias_cierre: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Exactamente 3 sugerencias concretas para que Sebas cierre",
    )
    resumen: str = Field("", description="Resumen de la conversación en 2 frases")


def es_calificado(p: PerfilOutput) -> bool:
    """Regla BANT determinista (fuente de verdad, testeable sin LLM).

    Calificado = necesidad confirmada + al menos 2 de: presupuesto, autoridad, urgencia alta/media.
    """
    if p.necesidad != "si":
        return False
    puntos = 0
    puntos += p.presupuesto == "si"
    puntos += p.autoridad == "si"
    puntos += p.urgencia in {"alta", "media"}
    return puntos >= 2


# ----------------------------------------------------------------------------- Diagnóstico

SECCIONES_DIAGNOSTICO: tuple[str, ...] = (
    "contexto_negocio",
    "procesos_actuales",
    "dolores_y_cuellos_de_botella",
    "sistemas_y_datos",
    "objetivos_y_metricas",
    "recomendacion_y_roadmap",
)

SeccionDiagnostico = Literal[
    "contexto_negocio",
    "procesos_actuales",
    "dolores_y_cuellos_de_botella",
    "sistemas_y_datos",
    "objetivos_y_metricas",
    "recomendacion_y_roadmap",
]


class Diagnostico(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contexto_negocio: str | None = None
    procesos_actuales: str | None = None
    dolores_y_cuellos_de_botella: str | None = None
    sistemas_y_datos: str | None = None
    objetivos_y_metricas: str | None = None
    recomendacion_y_roadmap: str | None = None
    resumen_ejecutivo: str | None = None
    cerrado: bool = False

    def secciones_completas(self) -> list[str]:
        return [s for s in SECCIONES_DIAGNOSTICO if getattr(self, s)]

    def secciones_pendientes(self) -> list[str]:
        return [s for s in SECCIONES_DIAGNOSTICO if not getattr(self, s)]

    def to_markdown(self, empresa: str | None) -> str:
        titulos = {
            "contexto_negocio": "1. Contexto del negocio",
            "procesos_actuales": "2. Procesos actuales",
            "dolores_y_cuellos_de_botella": "3. Dolores y cuellos de botella",
            "sistemas_y_datos": "4. Sistemas y datos",
            "objetivos_y_metricas": "5. Objetivos y métricas",
            "recomendacion_y_roadmap": "6. Recomendación y roadmap",
        }
        out = [f"# Diagnóstico técnico · {empresa or 'Cliente'}", ""]
        if self.resumen_ejecutivo:
            out += ["## Resumen ejecutivo", self.resumen_ejecutivo, ""]
        for key in SECCIONES_DIAGNOSTICO:
            out += [f"## {titulos[key]}", getattr(self, key) or "_Pendiente_", ""]
        return "\n".join(out)


# ----------------------------------------------------------------------------- Ficha


class Handoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: str
    resumen: str
    urgencia: Literal["alta", "media", "baja"] = "media"
    solicitado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Ficha(BaseModel):
    """Ficha del cliente = fuente de verdad en Postgres. Notion solo la refleja."""

    model_config = ConfigDict(extra="ignore")

    cliente_id: str
    canal_origen: Canal
    etapa: Etapa = Etapa.LEAD
    identidades: list[str] = Field(default_factory=list)
    perfil: PerfilOutput = Field(default_factory=PerfilOutput)
    handoff: Handoff | None = None
    diagnostico: Diagnostico = Field(default_factory=Diagnostico)
    turnos: int = 0
    creado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actualizado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def avanzar_etapa(self, nueva: Etapa) -> bool:
        """Solo avanza hacia adelante en el embudo. Devuelve True si cambió."""
        if ORDEN_ETAPAS[nueva] > ORDEN_ETAPAS[self.etapa]:
            self.etapa = nueva
            return True
        return False

    def agente_activo(self) -> Agente:
        if self.etapa in {Etapa.CERRADO, Etapa.DIAGNOSTICO}:
            return Agente.DIAGNOSTICO
        if self.etapa == Etapa.ENTREGA:
            return Agente.SOPORTE
        return Agente.VENTAS


# ----------------------------------------------------------------------------- Marketing


class LeadCrudo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    nombre_negocio: str
    sector: str | None = None
    ciudad: str | None = None
    telefono: str | None = None
    email: str | None = None
    web: str | None = None
    fuente: str = "manual"
    notas: str | None = None


class LeadScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encaje: int = Field(ge=0, le=10, description="0-10 qué tanto encaja con el ICP")
    razon: str = Field(description="Por qué ese puntaje, 1-2 frases")
    senales_detectadas: list[str] = Field(default_factory=list, max_length=6)
    mensaje_whatsapp: str = Field(description="Primer mensaje por WhatsApp, <= 400 caracteres")
    asunto_email: str = Field(description="Asunto del primer email, <= 60 caracteres")
    mensaje_email: str = Field(description="Cuerpo del primer email, <= 900 caracteres")


# ----------------------------------------------------------------------------- Soporte


class Incidencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(max_length=200)
    descripcion: str = Field(max_length=4000)
    bloqueante: bool = False
