"""Definiciones de herramientas (tool calling) para cada agente. Todas con strict=True."""

from __future__ import annotations

from dzlabs.schemas import SECCIONES_DIAGNOSTICO

HANDOFF_A_SEBAS = {
    "name": "handoff_a_sebas",
    "description": (
        "Pasa el lead a Sebas (humano) cuando está calificado, pide precio, agenda o hablar con una "
        "persona. Úsala UNA sola vez por conversación. Después de llamarla, dile al cliente que Sebas "
        "le escribirá pronto."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "motivo": {
                "type": "string",
                "description": "Por qué se pasa ahora (ver enum).",
                "enum": [
                    "calificado",
                    "pide_precio",
                    "pide_agenda",
                    "pide_humano",
                    "fuera_de_alcance",
                ],
            },
            "resumen": {
                "type": "string",
                "description": "Resumen para Sebas en 3-5 frases: quién es, qué negocio, qué dolor, qué quiere.",
            },
            "urgencia": {"type": "string", "enum": ["alta", "media", "baja"]},
        },
        "required": ["motivo", "resumen", "urgencia"],
        "additionalProperties": False,
    },
}

GUARDAR_DIAGNOSTICO = {
    "name": "guardar_diagnostico",
    "description": "Guarda el contenido de una sección del diagnóstico cuando tengas información suficiente.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "seccion": {"type": "string", "enum": list(SECCIONES_DIAGNOSTICO)},
            "contenido": {"type": "string", "description": "Texto claro de 3 a 8 frases."},
        },
        "required": ["seccion", "contenido"],
        "additionalProperties": False,
    },
}

CERRAR_DIAGNOSTICO = {
    "name": "cerrar_diagnostico",
    "description": "Cierra el diagnóstico cuando las 6 secciones están guardadas. Genera el documento.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "resumen_ejecutivo": {
                "type": "string",
                "description": "5 frases para el dueño del negocio.",
            }
        },
        "required": ["resumen_ejecutivo"],
        "additionalProperties": False,
    },
}

REGISTRAR_INCIDENCIA = {
    "name": "registrar_incidencia",
    "description": "Registra una incidencia de soporte. bloqueante=true si el cliente no puede operar.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {"type": "string", "maxLength": 200},
            "descripcion": {"type": "string", "maxLength": 4000},
            "bloqueante": {"type": "boolean"},
        },
        "required": ["titulo", "descripcion", "bloqueante"],
        "additionalProperties": False,
    },
}

TOOLS_VENTAS = [HANDOFF_A_SEBAS]
TOOLS_DIAGNOSTICO = [GUARDAR_DIAGNOSTICO, CERRAR_DIAGNOSTICO]
TOOLS_SOPORTE = [REGISTRAR_INCIDENCIA]
