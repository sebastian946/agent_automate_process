"""API con el engine sustituido por dobles (sin Postgres ni LLM)."""

import hashlib
import hmac
import time

import pytest
from dzlabs.api import app as app_module
from dzlabs.api.ratelimit import RateLimiter
from dzlabs.graph.build import Deps, build_graph
from dzlabs.schemas import Etapa
from fastapi.testclient import TestClient

from tests.conftest import FakeAnthropic, msg


class FakeEngine:
    def __init__(self, repo, settings):
        self.repo = repo
        self.client = FakeAnthropic([msg("Hola, ¿qué negocio tienes?")] * 20)
        self.graph = build_graph(Deps(repo, self.client, settings))

    def handle_message(self, cliente_id, canal, texto):
        from dzlabs.graph.build import handle_message

        return handle_message(self.graph, cliente_id, canal, texto)

    def start(self, ensure_schema=False):
        return self

    def stop(self):
        pass


@pytest.fixture
def client(fake_repo, settings, monkeypatch):
    engine = FakeEngine(fake_repo, settings)
    monkeypatch.setattr(app_module, "Engine", lambda s: engine)
    with TestClient(app_module.app) as c:
        c.app.state.limiter = RateLimiter(3)
        yield c


AUTH = {"Authorization": "Bearer test-token"}


def test_inbound_requiere_token(client):
    r = client.post("/inbound", json={"cliente_id": "+573001234567", "canal": "whatsapp", "texto": "hola"})
    assert r.status_code == 401
    r = client.post(
        "/inbound",
        json={"cliente_id": "+573001234567", "canal": "whatsapp", "texto": "hola"},
        headers={"Authorization": "Bearer malo"},
    )
    assert r.status_code == 401


def test_inbound_ok_normaliza_id_y_rate_limit(client):
    body = {"cliente_id": "whatsapp:+57 300 123 4567", "canal": "whatsapp", "texto": "hola"}
    r = client.post("/inbound", json=body, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["cliente_id"] == "+573001234567"
    assert "negocio" in r.json()["respuesta"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    client.post("/inbound", json=body, headers=AUTH)
    client.post("/inbound", json=body, headers=AUTH)
    assert client.post("/inbound", json=body, headers=AUTH).status_code == 429


def test_inbound_valida_payload(client):
    r = client.post("/inbound", json={"cliente_id": "x", "canal": "fax", "texto": ""}, headers=AUTH)
    assert r.status_code == 422
    r = client.post("/inbound", json={"cliente_id": "no-email", "canal": "email", "texto": "hola"}, headers=AUTH)
    assert r.status_code == 422


def test_twilio_rechaza_sin_firma(client):
    r = client.post(
        "/webhooks/twilio",
        data={"From": "whatsapp:+573001234567", "Body": "hola", "MessageSid": "SM1"},
    )
    assert r.status_code == 403


def test_twilio_con_firma_ok_e_idempotente(client, fake_repo, settings):
    import base64

    form = {"From": "whatsapp:+573001234567", "Body": "hola", "MessageSid": "SM1"}
    url = "https://api.test/webhooks/twilio"
    data = url + "".join(f"{k}{form[k]}" for k in sorted(form))
    firma = base64.b64encode(hmac.new(b"test-twilio", data.encode(), hashlib.sha1).digest()).decode()
    r = client.post("/webhooks/twilio", data=form, headers={"X-Twilio-Signature": firma})
    assert r.status_code == 200 and r.text == "<Response/>"
    # La tarea en background corrió (TestClient las ejecuta) y la ficha existe
    assert "+573001234567" in fake_repo.fichas
    # Reintento del mismo MessageSid: 200 pero no se procesa de nuevo
    turnos = fake_repo.fichas["+573001234567"].turnos
    client.post("/webhooks/twilio", data=form, headers={"X-Twilio-Signature": firma})
    assert fake_repo.fichas["+573001234567"].turnos == turnos


def _firma_n8n(cuerpo: bytes, ts: str, secret: str = "test-secret") -> str:
    return hmac.new(secret.encode(), ts.encode() + b"." + cuerpo, hashlib.sha256).hexdigest()


def test_webhook_etapa_firmado(client, fake_repo):
    client.post("/inbound", json={"cliente_id": "a@b.co", "canal": "email", "texto": "hola"}, headers=AUTH)
    cuerpo = b'{"cliente_id":"a@b.co","etapa":"cerrado","origen":"notion"}'
    ts = str(int(time.time()))
    r = client.post(
        "/webhooks/etapa",
        content=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-DZ-Signature": _firma_n8n(cuerpo, ts),
            "X-DZ-Timestamp": ts,
        },
    )
    assert r.status_code == 200 and r.json()["a"] == "cerrado"
    assert fake_repo.fichas["a@b.co"].etapa == Etapa.CERRADO
    r = client.post(
        "/webhooks/etapa",
        content=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-DZ-Signature": "mala",
            "X-DZ-Timestamp": ts,
        },
    )
    assert r.status_code == 403
    cuerpo2 = b'{"cliente_id":"nadie@b.co","etapa":"cerrado"}'
    r = client.post(
        "/webhooks/etapa",
        content=cuerpo2,
        headers={
            "Content-Type": "application/json",
            "X-DZ-Signature": _firma_n8n(cuerpo2, ts),
            "X-DZ-Timestamp": ts,
        },
    )
    assert r.status_code == 404


def test_get_cliente_y_embudo(client):
    client.post("/inbound", json={"cliente_id": "a@b.co", "canal": "email", "texto": "hola"}, headers=AUTH)
    assert client.get("/clientes/a@b.co", headers=AUTH).json()["etapa"] == "lead"
    assert client.get("/clientes/zz@b.co", headers=AUTH).status_code == 404
    assert client.get("/metricas/embudo", headers=AUTH).json() == {"lead": 1}
    assert client.get("/health").json()["status"] == "ok"
