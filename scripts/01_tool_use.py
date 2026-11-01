"""Día 2 · Tool calling con Anthropic en Python puro (sin LangChain).

Muestra cómo Claude devuelve un bloque `tool_use` para `handoff_a_sebas` y cómo se le responde.
Uso:  .venv/bin/python scripts/01_tool_use.py
"""

from __future__ import annotations

import json

import anthropic
from dotenv import load_dotenv

load_dotenv()

TOOL = {
    "name": "handoff_a_sebas",
    "description": "Pasa el lead a Sebas (humano) cuando pide precio, agenda o está calificado.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "motivo": {"type": "string", "enum": ["calificado", "pide_precio", "pide_agenda", "pide_humano"]},
            "resumen": {"type": "string"},
        },
        "required": ["motivo", "resumen"],
        "additionalProperties": False,
    },
}

client = anthropic.Anthropic()
messages = [
    {"role": "user", "content": "Hola, tengo un taller mecánico y quiero saber cuánto cuesta automatizar las citas."}
]

# Nota: en Sonnet 5.5 no existe tool_choice forzado; se guía desde el system prompt.
resp = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=600,
    system=(
        "Eres el asistente comercial de DZ Labs. No das precios. Si piden precio, llama handoff_a_sebas y despídete."
    ),
    tools=[TOOL],
    messages=messages,
    output_config={"effort": "low"},
)
print("stop_reason:", resp.stop_reason)
for b in resp.content:
    if b.type == "tool_use":
        print("TOOL_USE →", b.name, json.dumps(b.input, ensure_ascii=False))
    elif b.type == "text":
        print("TEXT →", b.text)

tool_uses = [b for b in resp.content if b.type == "tool_use"]
if tool_uses:
    # 2ª vuelta: devolvemos el tool_result y Claude redacta la despedida
    messages.append({"role": "assistant", "content": resp.content})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tu.id, "content": "Handoff registrado. Sebas escribirá pronto."}
                for tu in tool_uses
            ],
        }
    )
    final = client.messages.create(
        model="claude-sonnet-5-5", max_tokens=300, tools=[TOOL], messages=messages, output_config={"effort": "low"}
    )
    print("\nRespuesta final al cliente:")
    print("".join(b.text for b in final.content if b.type == "text"))
    print("\nTokens:", final.usage.input_tokens, "in /", final.usage.output_tokens, "out")
