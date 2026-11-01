"""Configuración centralizada. Todo secreto entra por variables de entorno (nunca hardcodeado)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    anthropic_api_key: SecretStr = Field(alias="ANTHROPIC_API_KEY")
    model_ventas: str = Field(default="claude-sonnet-5-5", alias="MODEL_VENTAS")
    model_diagnostico: str = Field(default="claude-sonnet-5-5", alias="MODEL_DIAGNOSTICO")
    model_marketing: str = Field(default="claude-sonnet-5-5", alias="MODEL_MARKETING")
    model_perfilador: str = Field(default="claude-haiku-5-5", alias="MODEL_PERFILADOR")
    llm_fallbacks: bool = Field(default=True, alias="LLM_FALLBACKS")
    llm_timeout_s: float = Field(default=25.0, alias="LLM_TIMEOUT_S")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")

    # Postgres
    database_url: SecretStr = Field(alias="DATABASE_URL")

    # API
    inbound_api_token: SecretStr = Field(alias="INBOUND_API_TOKEN")
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    env: str = Field(default="dev", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    rate_limit_per_minute: int = Field(default=12, alias="RATE_LIMIT_PER_MINUTE")

    # n8n
    n8n_webhook_url: str | None = Field(default=None, alias="N8N_WEBHOOK_URL")
    n8n_webhook_secret: SecretStr = Field(alias="N8N_WEBHOOK_SECRET")

    # Twilio
    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: SecretStr = Field(alias="TWILIO_AUTH_TOKEN")
    twilio_whatsapp_from: str | None = Field(default=None, alias="TWILIO_WHATSAPP_FROM")

    # Agenda
    cal_booking_url: str | None = Field(default=None, alias="CAL_BOOKING_URL")

    # Observabilidad (LangSmith lee LANGSMITH_API_KEY / LANGSMITH_PROJECT por su cuenta)
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"prod", "production"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
