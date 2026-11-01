import pytest
from dzlabs.channels.formatters import aplicar_formato_salida, limpiar_hilo_email, limpiar_markdown
from dzlabs.channels.identity import IdentidadInvalida, normalizar_email, normalizar_telefono
from dzlabs.schemas import Canal


@pytest.mark.parametrize(
    "raw,esperado",
    [
        ("whatsapp:+573001234567", "+573001234567"),
        ("+57 300 123-4567", "+573001234567"),
        ("3001234567", "+573001234567"),
        ("0057 300 1234567", "+573001234567"),
    ],
)
def test_normalizar_telefono(raw, esperado):
    assert normalizar_telefono(raw) == esperado


def test_telefono_invalido():
    with pytest.raises(IdentidadInvalida):
        normalizar_telefono("abc")


def test_normalizar_email():
    assert normalizar_email("Juan Pérez <Juan@Taller.CO>") == "juan@taller.co"
    with pytest.raises(IdentidadInvalida):
        normalizar_email("no-es-email")


def test_limpiar_markdown_para_whatsapp():
    txt = "## Hola\n**Sebas** te escribe. Mira [esto](https://dzlabs.co).\n- punto uno\n* punto dos"
    out = limpiar_markdown(txt)
    assert "**" not in out and "##" not in out and "](" not in out
    assert "esto: https://dzlabs.co" in out
    assert out.count("- punto") == 2


def test_formato_salida_recorta_whatsapp():
    assert len(aplicar_formato_salida("x" * 2000, Canal.WHATSAPP)) == 1500
    assert aplicar_formato_salida("  hola  ", Canal.EMAIL) == "hola"


def test_limpiar_hilo_email():
    cuerpo = "Sí, me interesa.\n\nEl mar, 3 de oct, Sebas escribió:\n> Hola Juan\n> ..."
    assert limpiar_hilo_email(cuerpo) == "Sí, me interesa."
