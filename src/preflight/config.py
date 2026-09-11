"""Runtime configuration. Everything comes from the environment; see .env.example."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    anthropic_api_key: str | None = None
    model_synth: str = Field(default="claude-opus-5", alias="PREFLIGHT_MODEL_SYNTH")
    model_fast: str = Field(default="claude-haiku-4-5-20251001", alias="PREFLIGHT_MODEL_FAST")

    # Sources
    faa_notam_client_id: str | None = None
    faa_notam_client_secret: str | None = None
    aviationweather_base: str = "https://aviationweather.gov/api/data"

    # Infra
    database_url: str = "postgresql://preflight:preflight@localhost:5432/preflight"
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # Decoder routing: below this the rule parse is escalated to the model.
    decode_escalation_threshold: float = 0.6


@lru_cache
def settings() -> Settings:
    return Settings()
