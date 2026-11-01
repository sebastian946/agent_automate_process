"""Nodos del grafo. Cada nodo recibe el State y devuelve solo lo que cambia."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic
from langsmith import get_current_run_tree

from dzlabs import prompts
from dzlabs.channels.formatters import aplicar_formato_salida, formato_para
from dzlabs.config import Settings
from dzlabs.db.repo import Repo
from dzlabs.graph import perfilador
from dzlabs.graph.state import State, recortar_historial
from dzlabs.graph.tools import TOOLS_DIAGNOSTICO, TOOLS_SOPORTE, TOOLS_VENTAS
from dzlabs.integrations import n8n
from dzlabs.llm import RefusalError, contenido_a_dicts, crear_mensaje, texto_de, verificar_stop
from dzlabs.logging_setup import mask_id
from dzlabs.schemas import Agente, Canal, Etapa, Ficha, Handoff, Incidencia

log = logging.getLogger(__name__)

MAX_ITERACIONES_TOOLS = 3
RESPUESTA_FALLBACK = "Gracias por escribir. Dame un momento y te respondo enseguida."


@dataclass
class Deps:
    """Dependencias inyectadas a los nodos (facilita tests con dobles)."""

    repo: Repo
    client: anthropic.Anthropic
    settings: Settings


# --------------------------------------------------------------------------- helpers


def _ficha(state: State) -> Ficha:
    return Ficha.model_validate(state["ficha"])


def _system(bloque_estable: str, ficha: Ficha, canal: Canal, extra: str = "") -> list[dict[str, Any]]:
    """System en 2 bloques: estable (cacheado) + dinámico (ficha, formato)."""
    ficha_json = json.dumps(
        ficha.model_dump(mode="json", include={"etapa", "perfil", "diagnostico", "turnos"}),
        ensure_ascii=False,
    )
    dinamico = f"{formato_para(canal)}\n\n<ficha_cliente>\n{ficha_json}\n</ficha_cliente>"
    if extra:
        dinamico += f"\n\n{extra}"
    return [
        {"type": "text", "text": bloque_estable, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dinamico},
    ]


def _loop_con_tools(
    deps: Deps,
    *,
    model: str,
    system: list[dict[str, Any]],
    historial: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    ejecutar: Any,
    max_tokens: int = 700,
) -> tuple[str, list[dict[str, Any]]]:
    """Bucle manual tool_use → tool_result (máx. 3 vueltas). Devuelve (texto, mensajes_nuevos)."""
    nuevos: list[dict[str, Any]] = []
    texto_acumulado = ""
    for _ in range(MAX_ITERACIONES_TOOLS):
        resp = crear_mensaje(
            model=model,
            system=system,
            messages=recortar_historial(historial + nuevos),
            tools=tools,
            max_tokens=max_tokens,
            effort="low",
            client=deps.client,
        )
        verificar_stop(resp)
        nuevos.append({"role": "assistant", "content": contenido_a_dicts(resp)})
        texto_acumulado = texto_de(resp) or texto_acumulado
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            break
        resultados = []
        for tu in tool_uses:
            try:
                out = ejecutar(tu.name, dict(tu.input))
                resultados.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
            except Exception as e:  # noqa: BLE001 - el error vuelve al modelo, no tumba el turno
                log.exception("Herramienta %s falló", tu.name)
                resultados.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    }
                )
        nuevos.append({"role": "user", "content": resultados})
    return texto_acumulado, nuevos


# --------------------------------------------------------------------------- nodos


def make_nodes(deps: Deps) -> dict[str, Any]:
    s = deps.settings

    def cargar_ficha(state: State) -> dict[str, Any]:
        canal = Canal(state["canal"])
        ficha = deps.repo.get_or_create_ficha(state["cliente_id"], canal)
        run = get_current_run_tree()
        if run is not None:  # solo cuando LangSmith está activo
            run.add_metadata({"etapa": ficha.etapa.value, "agente": ficha.agente_activo().value})
        return {
            "ficha": ficha.model_dump(mode="json"),
            "agente": ficha.agente_activo().value,
            "eventos": [],
        }

    # ---------------------------------------------------------------- Ventas
    def ventas(state: State) -> dict[str, Any]:
        ficha = _ficha(state)
        canal = Canal(state["canal"])
        eventos: list[dict[str, Any]] = []
        extra = ""
        if ficha.etapa in {Etapa.HANDOFF, Etapa.AGENDADO}:
            extra = (
                "ESTADO: este lead YA fue pasado a Sebas. No vendas ni vuelvas a llamar la herramienta; "
                "responde breve y recuerda que Sebas le escribe."
            )

        def ejecutar(nombre: str, args: dict[str, Any]) -> str:
            if nombre != "handoff_a_sebas":
                return f"Herramienta desconocida: {nombre}"
            if ficha.handoff is not None:
                return "El handoff ya se había hecho antes. No lo repitas; solo responde al cliente."
            ficha.handoff = Handoff(**args)
            anterior = ficha.etapa
            ficha.avanzar_etapa(Etapa.HANDOFF)
            eventos.append({"tipo": "handoff", "de": anterior.value, "a": ficha.etapa.value})
            return "Handoff registrado. Sebas recibirá el aviso. Despídete indicando que él le escribe pronto."

        historial = state.get("messages", []) + [{"role": "user", "content": state["texto"]}]
        texto, nuevos = _loop_con_tools(
            deps,
            model=s.model_ventas,
            system=_system(prompts.bloque_estable_ventas(), ficha, canal, extra),
            historial=historial,
            tools=TOOLS_VENTAS,
            ejecutar=ejecutar,
        )
        ficha.turnos += 1
        return {
            "messages": [{"role": "user", "content": state["texto"]}, *nuevos],
            "respuesta": texto or RESPUESTA_FALLBACK,
            "ficha": ficha.model_dump(mode="json"),
            "eventos": eventos,
        }

    # ---------------------------------------------------------------- Perfilador
    def perfilador_node(state: State) -> dict[str, Any]:
        ficha = _ficha(state)
        perfil = perfilador.perfilar(deps.client, s.model_perfilador, ficha, state.get("messages", []))
        anterior = ficha.etapa
        nueva = perfilador.aplicar_perfil(ficha, perfil)
        eventos = list(state.get("eventos", []))
        if nueva:
            eventos.append({"tipo": "lead_calificado", "de": anterior.value, "a": nueva.value})
        return {"ficha": ficha.model_dump(mode="json"), "eventos": eventos}

    # ---------------------------------------------------------------- Diagnóstico
    def diagnostico(state: State) -> dict[str, Any]:
        ficha = _ficha(state)
        canal = Canal(state["canal"])
        eventos: list[dict[str, Any]] = []
        if ficha.etapa == Etapa.CERRADO:
            ficha.avanzar_etapa(Etapa.DIAGNOSTICO)
            eventos.append({"tipo": "etapa_cambiada", "de": "cerrado", "a": "diagnostico"})

        def ejecutar(nombre: str, args: dict[str, Any]) -> str:
            if nombre == "guardar_diagnostico":
                setattr(ficha.diagnostico, args["seccion"], args["contenido"].strip())
                pend = ficha.diagnostico.secciones_pendientes()
                return f"Sección guardada. Pendientes: {', '.join(pend) if pend else 'ninguna'}."
            if nombre == "cerrar_diagnostico":
                pend = ficha.diagnostico.secciones_pendientes()
                if pend:
                    return f"No se puede cerrar: faltan secciones {', '.join(pend)}."
                ficha.diagnostico.resumen_ejecutivo = args["resumen_ejecutivo"].strip()
                ficha.diagnostico.cerrado = True
                eventos.append({"tipo": "diagnostico_cerrado"})
                return "Diagnóstico cerrado. Despídete: Sebas revisará el documento y lo enviará."
            return f"Herramienta desconocida: {nombre}"

        pend = ficha.diagnostico.secciones_pendientes()
        extra = f"SECCIONES PENDIENTES (en orden): {', '.join(pend) if pend else 'ninguna, cierra el diagnóstico'}."
        historial = state.get("messages", []) + [{"role": "user", "content": state["texto"]}]
        texto, nuevos = _loop_con_tools(
            deps,
            model=s.model_diagnostico,
            system=_system(prompts.bloque_estable_diagnostico(), ficha, canal, extra),
            historial=historial,
            tools=TOOLS_DIAGNOSTICO,
            ejecutar=ejecutar,
            max_tokens=1200,
        )
        ficha.turnos += 1
        return {
            "messages": [{"role": "user", "content": state["texto"]}, *nuevos],
            "respuesta": texto or RESPUESTA_FALLBACK,
            "ficha": ficha.model_dump(mode="json"),
            "eventos": eventos,
        }

    # ---------------------------------------------------------------- Soporte
    def soporte(state: State) -> dict[str, Any]:
        ficha = _ficha(state)
        canal = Canal(state["canal"])
        eventos: list[dict[str, Any]] = []

        def ejecutar(nombre: str, args: dict[str, Any]) -> str:
            if nombre != "registrar_incidencia":
                return f"Herramienta desconocida: {nombre}"
            inc = Incidencia(**args)
            inc_id = deps.repo.crear_incidencia(ficha.cliente_id, inc)
            eventos.append({"tipo": "incidencia", "incidencia_id": inc_id, **inc.model_dump()})
            return f"Incidencia #{inc_id} registrada{' (BLOQUEANTE, Sebas avisado)' if inc.bloqueante else ''}."

        historial = state.get("messages", []) + [{"role": "user", "content": state["texto"]}]
        texto, nuevos = _loop_con_tools(
            deps,
            model=s.model_ventas,
            system=_system(prompts.bloque_estable_soporte(), ficha, canal),
            historial=historial,
            tools=TOOLS_SOPORTE,
            ejecutar=ejecutar,
        )
        ficha.turnos += 1
        return {
            "messages": [{"role": "user", "content": state["texto"]}, *nuevos],
            "respuesta": texto or RESPUESTA_FALLBACK,
            "ficha": ficha.model_dump(mode="json"),
            "eventos": eventos,
        }

    # ---------------------------------------------------------------- Persistir + bordes
    def guardar_ficha(state: State) -> dict[str, Any]:
        ficha = _ficha(state)
        canal = Canal(state["canal"])
        deps.repo.upsert_ficha(ficha)
        hilo = f"{s.public_base_url}/clientes/{ficha.cliente_id}"
        for ev in state.get("eventos", []):
            tipo = ev.get("tipo")
            if tipo in {"handoff", "lead_calificado", "etapa_cambiada"}:
                deps.repo.log_evento_etapa(ficha.cliente_id, Etapa(ev["de"]), Etapa(ev["a"]), "agente")
            datos: dict[str, Any] = {
                "ficha": ficha.model_dump(mode="json"),
                "canal": canal.value,
                "link_hilo": hilo,
                "cal_url": s.cal_booking_url,
                **{k: v for k, v in ev.items() if k != "tipo"},
            }
            if tipo == "diagnostico_cerrado":
                datos["markdown"] = ficha.diagnostico.to_markdown(ficha.perfil.empresa)
            n8n.emitir_evento(tipo, ficha.cliente_id, datos)
        log.info(
            "turno ok cliente=%s canal=%s etapa=%s agente=%s eventos=%d",
            mask_id(ficha.cliente_id),
            canal.value,
            ficha.etapa.value,
            state.get("agente"),
            len(state.get("eventos", [])),
        )
        return {"respuesta": aplicar_formato_salida(state.get("respuesta", RESPUESTA_FALLBACK), canal)}

    return {
        "cargar_ficha": cargar_ficha,
        "ventas": ventas,
        "perfilador": perfilador_node,
        "diagnostico": diagnostico,
        "soporte": soporte,
        "guardar_ficha": guardar_ficha,
    }


def router(state: State) -> str:
    """Edge condicional: decide el agente según la etapa de la ficha."""
    return Agente(state["agente"]).value


__all__ = ["Deps", "RefusalError", "make_nodes", "router"]
