"""Flujo completo del grafo con LLM guionado: ventas → handoff → cerrado → diagnóstico → entrega."""

from dzlabs.graph.build import handle_message
from dzlabs.integrations import n8n
from dzlabs.schemas import Etapa, PerfilOutput

from tests.conftest import msg


def test_turno_ventas_basico_persiste_ficha_y_historial(make_graph, fake_repo):
    graph, client = make_graph([msg("¡Hola! ¿Qué tipo de negocio tienes?")])
    out = handle_message(graph, "+573001234567", "whatsapp", "Hola, quiero automatizar mi taller")
    assert "negocio" in out
    ficha = fake_repo.fichas["+573001234567"]
    assert ficha.etapa == Etapa.LEAD and ficha.turnos == 1
    # El system va en 2 bloques: estable con cache_control + dinámico con la ficha
    sys_blocks = client.messages.llamadas[0]["system"]
    assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "<ficha_cliente>" in sys_blocks[1]["text"]
    assert "WhatsApp" in sys_blocks[1]["text"]
    # Sin temperature (400 en modelos actuales) y con effort
    assert "temperature" not in client.messages.llamadas[0]
    assert client.messages.llamadas[0]["output_config"] == {"effort": "low"}


def test_historial_persiste_entre_turnos_mismo_thread(make_graph):
    graph, client = make_graph([msg("Turno 1"), msg("Turno 2")])
    handle_message(graph, "+573001234567", "whatsapp", "primero")
    handle_message(graph, "+573001234567", "whatsapp", "segundo")
    mensajes_turno2 = client.messages.llamadas[1]["messages"]
    assert [m["role"] for m in mensajes_turno2] == ["user", "assistant", "user"]
    assert mensajes_turno2[0]["content"] == "primero"


def test_handoff_cambia_etapa_y_emite_evento(make_graph, fake_repo, monkeypatch):
    eventos = []
    monkeypatch.setattr(n8n, "emitir_evento", lambda tipo, cid, datos: eventos.append((tipo, datos)) or True)
    guion = [
        msg(
            tool=(
                "handoff_a_sebas",
                {
                    "motivo": "pide_precio",
                    "resumen": "Taller, 5 personas, agenda manual",
                    "urgencia": "alta",
                },
            )
        ),
        msg("Perfecto, Sebas te escribe pronto."),
    ]
    graph, client = make_graph(guion)
    out = handle_message(graph, "+573001234567", "whatsapp", "¿Cuánto cuesta?")
    assert "Sebas" in out
    ficha = fake_repo.fichas["+573001234567"]
    assert ficha.etapa == Etapa.HANDOFF
    assert ficha.handoff and ficha.handoff.motivo == "pide_precio"
    assert eventos[0][0] == "handoff"
    assert eventos[0][1]["link_hilo"].endswith("/clientes/+573001234567")
    # Segunda llamada incluye el tool_result
    tr = client.messages.llamadas[1]["messages"][-1]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "toolu_1"


def test_handoff_no_se_repite(make_graph, fake_repo):
    guion = [
        msg(tool=("handoff_a_sebas", {"motivo": "calificado", "resumen": "r", "urgencia": "media"})),
        msg("ok"),
        msg(tool=("handoff_a_sebas", {"motivo": "calificado", "resumen": "r", "urgencia": "media"})),
        msg("ok 2"),
    ]
    graph, client = make_graph(guion)
    handle_message(graph, "+573001234567", "whatsapp", "a")
    handle_message(graph, "+573001234567", "whatsapp", "b")
    tr = client.messages.llamadas[3]["messages"][-1]["content"][0]
    assert "ya se había hecho" in tr["content"]
    assert fake_repo.fichas["+573001234567"].handoff.motivo == "calificado"


def test_perfilador_califica_con_bant(make_graph, fake_repo):
    perfil = PerfilOutput(
        empresa="Taller Pérez",
        necesidad="si",
        autoridad="si",
        urgencia="alta",
        sugerencias_cierre=["a", "b", "c"],
    )
    graph, client = make_graph([msg("Entiendo.")], perfil=perfil)
    handle_message(graph, "+573001234567", "whatsapp", "Soy el dueño y lo necesito este mes")
    ficha = fake_repo.fichas["+573001234567"]
    assert ficha.etapa == Etapa.CALIFICADO
    assert ficha.perfil.empresa == "Taller Pérez"
    assert client.messages.parse_llamadas[0]["output_format"] is PerfilOutput
    assert any(e[2] == Etapa.CALIFICADO for e in fake_repo.eventos)


def test_cerrado_enruta_a_diagnostico_y_guarda_secciones(make_graph, fake_repo):
    graph, client = make_graph([msg("Hola")])
    handle_message(graph, "a@taller.co", "email", "hola")
    fake_repo.set_etapa("a@taller.co", Etapa.CERRADO, "notion")  # Sebas marca cerrado en Notion

    client.messages.guion = [
        msg(
            tool=(
                "guardar_diagnostico",
                {"seccion": "contexto_negocio", "contenido": "Taller de 5 personas en Bogotá."},
            )
        ),
        msg("Gracias. ¿Cómo funciona hoy el proceso de agendar?"),
    ]
    out = handle_message(graph, "a@taller.co", "email", "Somos un taller de 5 personas en Bogotá")
    assert "agendar" in out
    ficha = fake_repo.fichas["a@taller.co"]
    assert ficha.etapa == Etapa.DIAGNOSTICO
    assert ficha.diagnostico.contexto_negocio.startswith("Taller")
    # El system del diagnóstico no es el de ventas
    assert "Diagnóstico técnico de DZ Labs" in client.messages.llamadas[1]["system"][0]["text"]
    assert "SECCIONES PENDIENTES" in client.messages.llamadas[1]["system"][1]["text"]


def test_cerrar_diagnostico_requiere_6_secciones_y_emite_markdown(make_graph, fake_repo, monkeypatch):
    eventos = []
    monkeypatch.setattr(n8n, "emitir_evento", lambda tipo, cid, datos: eventos.append((tipo, datos)) or True)
    graph, client = make_graph([msg("Hola")])
    handle_message(graph, "a@taller.co", "email", "hola")
    f = fake_repo.fichas["a@taller.co"]
    f.etapa = Etapa.DIAGNOSTICO
    for sec in (
        "contexto_negocio",
        "procesos_actuales",
        "dolores_y_cuellos_de_botella",
        "sistemas_y_datos",
        "objetivos_y_metricas",
    ):
        setattr(f.diagnostico, sec, "texto")

    client.messages.guion = [
        msg(tool=("cerrar_diagnostico", {"resumen_ejecutivo": "Resumen"})),  # falta la sección 6 → error al modelo
        msg(
            tool=(
                "guardar_diagnostico",
                {"seccion": "recomendacion_y_roadmap", "contenido": "Fase 1..."},
            )
        ),
        msg(tool=("cerrar_diagnostico", {"resumen_ejecutivo": "Resumen ejecutivo final."})),
    ]
    handle_message(graph, "a@taller.co", "email", "listo")
    primer_result = client.messages.llamadas[2]["messages"][-1]["content"][0]["content"]
    assert "No se puede cerrar" in primer_result
    ficha = fake_repo.fichas["a@taller.co"]
    assert ficha.diagnostico.cerrado and ficha.diagnostico.resumen_ejecutivo == "Resumen ejecutivo final."
    tipos = [e[0] for e in eventos]
    assert "diagnostico_cerrado" in tipos
    md = next(d for t, d in eventos if t == "diagnostico_cerrado")["markdown"]
    assert "## Resumen ejecutivo" in md and "Fase 1" in md


def test_entrega_registra_incidencia_bloqueante(make_graph, fake_repo, monkeypatch):
    eventos = []
    monkeypatch.setattr(n8n, "emitir_evento", lambda tipo, cid, datos: eventos.append((tipo, datos)) or True)
    graph, client = make_graph([msg("Hola")])
    handle_message(graph, "+573001234567", "whatsapp", "hola")
    fake_repo.fichas["+573001234567"].etapa = Etapa.ENTREGA
    client.messages.guion = [
        msg(
            tool=(
                "registrar_incidencia",
                {
                    "titulo": "No carga el panel",
                    "descripcion": "Error 500 al abrir",
                    "bloqueante": True,
                },
            )
        ),
        msg("Registrado, el equipo lo revisa."),
    ]
    out = handle_message(graph, "+573001234567", "whatsapp", "no puedo entrar al panel")
    assert "revisa" in out
    assert fake_repo.incidencias[0].bloqueante
    assert eventos[0][0] == "incidencia" and eventos[0][1]["bloqueante"] is True


def test_error_del_llm_devuelve_fallback_sin_romper(make_graph, fake_repo):
    import anthropic
    import httpx

    graph, client = make_graph()

    def boom(**kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    client.messages.create = boom
    out = handle_message(graph, "+573001234567", "whatsapp", "hola")
    assert "momento" in out
    # El turno fallido no deja el mensaje huérfano en el historial
    client.messages.create = lambda **kw: msg("ok")
    client.messages.llamadas.clear()
    handle_message(graph, "+573001234567", "whatsapp", "hola otra vez")


def test_refusal_devuelve_mensaje_neutro(make_graph):
    graph, client = make_graph([msg("", stop="refusal")])
    out = handle_message(graph, "+573001234567", "whatsapp", "x")
    assert "Prefiero no responder" in out
