-- DZ Labs · esquema de la fuente de verdad. Idempotente (puede correrse varias veces).
-- Las tablas de checkpoints de LangGraph las crea PostgresSaver.setup() (checkpoints, checkpoint_blobs, checkpoint_writes).

CREATE TABLE IF NOT EXISTS clientes (
    cliente_id      TEXT PRIMARY KEY,                 -- E.164 (+57300...) o email normalizado
    canal_origen    TEXT NOT NULL CHECK (canal_origen IN ('whatsapp', 'email')),
    etapa           TEXT NOT NULL DEFAULT 'lead'
                    CHECK (etapa IN ('lead','calificado','handoff','agendado','cerrado','diagnostico','entrega')),
    ficha           JSONB NOT NULL DEFAULT '{}'::jsonb,
    identidades     JSONB NOT NULL DEFAULT '[]'::jsonb, -- otros identificadores del mismo cliente
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS clientes_etapa_idx ON clientes (etapa);
CREATE INDEX IF NOT EXISTS clientes_actualizado_idx ON clientes (actualizado_en DESC);
CREATE INDEX IF NOT EXISTS clientes_identidades_gin ON clientes USING GIN (identidades);

-- Historial de cambios de etapa (auditoría + métricas del embudo)
CREATE TABLE IF NOT EXISTS eventos_etapa (
    id          BIGSERIAL PRIMARY KEY,
    cliente_id  TEXT NOT NULL REFERENCES clientes(cliente_id) ON DELETE CASCADE,
    de          TEXT,
    a           TEXT NOT NULL,
    origen      TEXT NOT NULL,            -- 'agente', 'notion', 'cal', 'manual'
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eventos_etapa_cliente_idx ON eventos_etapa (cliente_id, creado_en DESC);

-- Incidencias de soporte (etapa entrega)
CREATE TABLE IF NOT EXISTS incidencias (
    id          BIGSERIAL PRIMARY KEY,
    cliente_id  TEXT NOT NULL REFERENCES clientes(cliente_id) ON DELETE CASCADE,
    titulo      TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    bloqueante  BOOLEAN NOT NULL DEFAULT false,
    estado      TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta','en_progreso','cerrada')),
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Leads crudos de Marketing (Google Maps / Apollo / manual)
CREATE TABLE IF NOT EXISTS leads (
    id              BIGSERIAL PRIMARY KEY,
    nombre_negocio  TEXT NOT NULL,
    sector          TEXT,
    ciudad          TEXT,
    telefono        TEXT,
    email           TEXT,
    web             TEXT,
    fuente          TEXT NOT NULL DEFAULT 'manual',
    notas           TEXT,
    encaje          SMALLINT CHECK (encaje BETWEEN 0 AND 10),
    score           JSONB,                -- salida completa del agente de Marketing (LeadScore)
    estado          TEXT NOT NULL DEFAULT 'crudo'
                    CHECK (estado IN ('crudo','calificado','por_aprobar','aprobado','contactado','descartado')),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (nombre_negocio, ciudad)
);
CREATE INDEX IF NOT EXISTS leads_estado_idx ON leads (estado);

-- Idempotencia de webhooks entrantes (Twilio reintenta): guardamos MessageSid ya procesados
CREATE TABLE IF NOT EXISTS mensajes_procesados (
    proveedor   TEXT NOT NULL,
    mensaje_id  TEXT NOT NULL,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (proveedor, mensaje_id)
);

-- Esquema propio para n8n (lo usa docker-compose)
CREATE SCHEMA IF NOT EXISTS n8n;
