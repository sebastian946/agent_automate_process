import time

from dzlabs.channels.twilio import firma_valida
from dzlabs.integrations.n8n import firmar, verificar_firma


def test_firma_twilio_ok_y_mal():
    # Vector verificado contra twilio.request_validator.RequestValidator (URL + params ordenados, HMAC-SHA1, b64)
    token = "12345"
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    firma = "0/KCTR6DLpKmkAf8muzZqo1nDgQ="
    assert firma_valida(token, url, params, firma)
    assert not firma_valida(token, url, params, "mala")
    assert not firma_valida(token, url, {**params, "Digits": "0000"}, firma)
    assert not firma_valida(token, url, params, None)


def test_firma_n8n_con_timestamp():
    secret = "s3cr3t"
    cuerpo = b'{"cliente_id":"+573001234567","etapa":"cerrado"}'
    ts = str(int(time.time()))
    import hashlib
    import hmac

    firma = hmac.new(secret.encode(), ts.encode() + b"." + cuerpo, hashlib.sha256).hexdigest()
    assert verificar_firma(secret, cuerpo, firma, ts)
    assert not verificar_firma(secret, cuerpo + b" ", firma, ts)
    assert not verificar_firma(secret, cuerpo, firma, str(int(time.time()) - 1000))  # replay viejo
    assert not verificar_firma(secret, cuerpo, None, ts)


def test_firma_saliente_es_determinista():
    assert firmar("k", b"abc") == firmar("k", b"abc")
    assert firmar("k", b"abc") != firmar("k2", b"abc")
