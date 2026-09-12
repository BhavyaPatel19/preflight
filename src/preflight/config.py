"""Runtime configuration. Everything comes from the environment; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    anthropic_api_key: str | None = None
    model_synth: str = Field(default="claude-opus-5", alias="PREFLIGHT_MODEL_SYNTH")
    model_fast: str = Field(default="claude-haiku-4-5-20251001", alias="PREFLIGHT_MODEL_FAST")

    # Sources
    aviationweather_base: str = "https://aviationweather.gov/api/data"
    # NASA DIP redistributes the FAA NOTAM feed; access by request (ADR 0002).
    nasa_dip_base_url: str | None = Field(default=None, alias="PREFLIGHT_NASA_DIP_BASE_URL")
    nasa_dip_token: str | None = Field(default=None, alias="PREFLIGHT_NASA_DIP_TOKEN")

    # Raw-payload archive root (see preflight.archive).
    archive_dir: Path = Path("data/raw")

    # Infra
    database_url: str = "postgresql://preflight:preflight@localhost:5432/preflight"
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # Decoder routing: below this the rule parse is escalated to the model.
    decode_escalation_threshold: float = 0.6

    # Briefing: a METAR older than this is stale — the system abstains rather than cite it.
    metar_stale_after_minutes: int = 120
    # Without a flight time, destination/alternate hazards are checked across a
    # conservative window after off-block. Sprint 6 replaces this with a real ETE.
    default_ete_window_hours: int = 8


@lru_cache
def settings() -> Settings:
    return Settings()
