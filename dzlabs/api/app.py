"""FastAPI: entrada única del motor.

Endpoints:
- POST /inbound             {cliente_id, canal, texto}   (Bearer INBOUND_API_TOKEN) → {respuesta}
- POST /webhooks/twilio     form Twilio (firma X-Twilio-Signature) → 200 TwiML vacío + respuesta async
- POST /webhooks/etapa      {cliente_id, etapa, origen} firmado HMAC por n8n → cambia etapa (Notion/Cal)
- GET  /clientes/{id}       ficha (Bearer)
- GET  /metricas/embudo     conteo por etapa (Bearer)
- GET  /health
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from dzlabs.api.ratelimit import RateLimiter
from dzlabs.channels import twilio
from dzlabs.channels.identity import IdentidadInvalida, normalizar_cliente_id
from dzlabs.config import get_settings
from dzlabs.graph.build import Engine
from dzlabs.integrations.n8n import verificar_firma
from dzlabs.logging_setup import mask_id, setup_logging
from dzlabs.schemas import Canal, Etapa

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    engine = Engine(s).start(ensure_schema=not s.is_prod)
    app.state.engine = engine
    app.state.limiter = RateLimiter(s.rate_limit_per_minute)
    log.info("API lista (env=%s)", s.env)
    try:
        yield
    finally:
        engine.stop()


app = FastAPI(
    title="DZ Labs · Motor comercial",
    version="0.1.0",
    docs_url=None if get_settings().is_prod else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# --------------------------------------------------------------------------- auth


def require_bearer(authorization: Annotated[str | None, Header()] = None) -> None:
    s = get_settings()
    esperado = f"Bearer {s.inbound_api_token.get_secret_value()}"
    if not authorization or not hmac.compare_digest(authorization, esperado):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")


# --------------------------------------------------------------------------- modelos


class InboundIn(BaseModel):
    cliente_id: str = Field(min_length=3, max_length=254)
    canal: Canal
    texto: str = Field(min_length=1, max_length=4000)


class InboundOut(BaseModel):
    cliente_id: str
    respuesta: str


class EtapaIn(BaseModel):
    cliente_id: str = Field(min_length=3, max_length=254)
    etapa: Etapa
    origen: Literal["notion", "cal", "manual"] = "notion"


# --------------------------------------------------------------------------- helpers


def _engine(request: Request) -> Engine:
    return request.app.state.engine


def _limitar(request: Request, clave: str) -> None:
    if not request.app.state.limiter.permitir(clave):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados mensajes, intenta en un minuto")


async def _responder(engine: Engine, cliente_id: str, canal: Canal, texto: str) -> str:
    # El grafo es síncrono (psycopg + SDK sync): lo corremos en un hilo para no bloquear el event loop
    return await asyncio.to_thread(engine.handle_message, cliente_id, canal, texto)


# --------------------------------------------------------------------------- endpoints


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    ok = await asyncio.to_thread(_engine(request).repo.ping)
    return {"status": "ok" if ok else "degraded"}


@app.post("/inbound", response_model=InboundOut, dependencies=[Depends(require_bearer)])
async def inbound(body: InboundIn, request: Request) -> InboundOut:
    try:
        cliente_id = normalizar_cliente_id(body.cliente_id, body.canal)
    except IdentidadInvalida as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    _limitar(request, cliente_id)
    respuesta = await _responder(_engine(request), cliente_id, body.canal, body.texto)
    return InboundOut(cliente_id=cliente_id, respuesta=respuesta)


@app.post("/webhooks/twilio")
async def twilio_webhook(request: Request, background: BackgroundTasks) -> Response:
    """Twilio corta a 15 s: respondemos 200 vacío de inmediato y enviamos la respuesta por REST."""
    s = get_settings()
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = f"{s.public_base_url.rstrip('/')}{request.url.path}"
    if not twilio.firma_valida(
        s.twilio_auth_token.get_secret_value(), url, form, request.headers.get("X-Twilio-Signature")
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Firma Twilio inválida")

    engine = _engine(request)
    sid = form.get("MessageSid", "")
    texto = (form.get("Body") or "").strip()
    desde = form.get("From", "")
    if not texto or not desde:
        return Response(content="<Response/>", media_type="application/xml")
    if sid and not await asyncio.to_thread(engine.repo.marcar_mensaje_procesado, "twilio", sid):
        return Response(content="<Response/>", media_type="application/xml")  # reintento duplicado
    try:
        cliente_id = normalizar_cliente_id(desde, Canal.WHATSAPP)
    except IdentidadInvalida:
        return Response(content="<Response/>", media_type="application/xml")
    _limitar(request, cliente_id)

    async def procesar() -> None:
        respuesta = await _responder(engine, cliente_id, Canal.WHATSAPP, texto)
        if not (s.twilio_account_sid and s.twilio_whatsapp_from):
            log.error("Twilio no configurado; no se pudo responder a %s", mask_id(cliente_id))
            return
        await twilio.enviar_whatsapp(
            account_sid=s.twilio_account_sid,
            auth_token=s.twilio_auth_token.get_secret_value(),
            desde=s.twilio_whatsapp_from,
            para=cliente_id,
            cuerpo=respuesta,
        )

    background.add_task(procesar)
    return Response(content="<Response/>", media_type="application/xml")


@app.post("/webhooks/etapa")
async def etapa_webhook(
    request: Request,
    x_dz_signature: Annotated[str | None, Header()] = None,
    x_dz_timestamp: Annotated[str | None, Header()] = None,
) -> dict[str, str | None]:
    """n8n (Notion → Postgres, Cal.com → agendado) cambia la etapa. Firma HMAC + timestamp anti-replay."""
    s = get_settings()
    cuerpo = await request.body()
    if not verificar_firma(s.n8n_webhook_secret.get_secret_value(), cuerpo, x_dz_signature, x_dz_timestamp):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Firma inválida")
    body = EtapaIn.model_validate_json(cuerpo)
    anterior = await asyncio.to_thread(_engine(request).repo.set_etapa, body.cliente_id, body.etapa, body.origen)
    if anterior is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente no existe")
    log.info(
        "etapa %s → %s para %s (origen=%s)",
        anterior.value,
        body.etapa.value,
        mask_id(body.cliente_id),
        body.origen,
    )
    return {"cliente_id": body.cliente_id, "de": anterior.value, "a": body.etapa.value}


@app.get("/clientes/{cliente_id}", dependencies=[Depends(require_bearer)])
async def get_cliente(cliente_id: str, request: Request) -> dict:
    ficha = await asyncio.to_thread(_engine(request).repo.get_ficha, cliente_id)
    if not ficha:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente no existe")
    return ficha.model_dump(mode="json")


@app.get("/metricas/embudo", dependencies=[Depends(require_bearer)])
async def embudo(request: Request) -> dict:
    return await asyncio.to_thread(_engine(request).repo.embudo)
