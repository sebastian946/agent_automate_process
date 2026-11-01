from dzlabs.schemas import Canal, Diagnostico, Etapa, Ficha, PerfilOutput, es_calificado


def test_etapa_solo_avanza():
    f = Ficha(cliente_id="+573001234567", canal_origen=Canal.WHATSAPP)
    assert f.avanzar_etapa(Etapa.CALIFICADO)
    assert not f.avanzar_etapa(Etapa.LEAD)
    assert f.etapa == Etapa.CALIFICADO


def test_agente_activo_por_etapa():
    f = Ficha(cliente_id="a@b.co", canal_origen=Canal.EMAIL)
    assert f.agente_activo().value == "ventas"
    f.etapa = Etapa.CERRADO
    assert f.agente_activo().value == "diagnostico"
    f.etapa = Etapa.ENTREGA
    assert f.agente_activo().value == "soporte"


def test_diagnostico_markdown_y_pendientes():
    d = Diagnostico(contexto_negocio="Taller de 5 personas")
    assert d.secciones_completas() == ["contexto_negocio"]
    assert len(d.secciones_pendientes()) == 5
    md = d.to_markdown("Taller Pérez")
    assert md.startswith("# Diagnóstico técnico · Taller Pérez")
    assert "_Pendiente_" in md


def test_perfil_rechaza_campos_extra():
    import pytest

    with pytest.raises(Exception):  # noqa: B017
        PerfilOutput.model_validate({"nombre": "x", "campo_raro": 1})


def test_es_calificado_regla_bant():
    assert not es_calificado(PerfilOutput(necesidad="desconocido", presupuesto="si", autoridad="si"))
    assert not es_calificado(PerfilOutput(necesidad="si", presupuesto="si"))
    assert es_calificado(PerfilOutput(necesidad="si", presupuesto="si", autoridad="si"))
    assert es_calificado(PerfilOutput(necesidad="si", autoridad="si", urgencia="media"))
    assert not es_calificado(PerfilOutput(necesidad="si", autoridad="si", urgencia="baja"))
