"""Runtime configuration. Everything comes from the environment; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_WATCHLIST = [
    "KATL", "KLAX", "KORD", "KDFW", "KDEN", "KJFK", "KSFO", "KSEA", "KLAS", "KMCO",
    "KEWR", "KCLT", "KPHX", "KIAH", "KMIA", "KBOS", "KMSP", "KFLL", "KDTW", "KPHL",
    "KLGA", "KBWI", "KSLC", "KSAN", "KIAD", "KDCA", "KMDW", "KTPA", "KPDX", "KHNL",
]


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

    # Airports the scheduler keeps current. Comma-separated in the environment.
    watchlist: Annotated[list[str], NoDecode] = Field(
        default=DEFAULT_WATCHLIST, alias="PREFLIGHT_WATCHLIST"
    )

    # Infra
    database_url: str = "postgresql://preflight:preflight@localhost:5433/preflight"
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # Retrieval models (ADR 0003). Dev defaults are the fast pair; bge-m3 and
    # bge-reranker-v2-m3 are the measured upgrade path once the golden set exists.
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    reranker_model: str = "BAAI/bge-reranker-base"
    device: str = Field(default="auto", alias="PREFLIGHT_DEVICE")  # auto | cpu | mps | cuda
    retrieval_candidates: int = 40   # per channel, before fusion
    rrf_k: int = 60

    # Grounding verifier (NLI). A claim passes when P(entailment) against any of its
    # citations clears the threshold. See src/preflight/verify.
    nli_model: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    grounding_threshold: float = 0.5

    # Precedent in briefings: top-k prior reports per finding, kept only above this
    # reranker score (the retrieval eval put relevant hits at 0.6–0.98, noise at 0.0–0.1;
    # 0.5 is deliberately conservative for a safety-adjacent output).
    precedent_k: int = 3
    precedent_min_score: float = 0.5

    # Decoder routing: below this the rule parse is escalated to the model.
    decode_escalation_threshold: float = 0.6

    # Briefing: a METAR older than this is stale — the system abstains rather than cite it.
    metar_stale_after_minutes: int = 120
    # Without a flight time, destination/alternate hazards are checked across a
    # conservative window after off-block. Sprint 6 replaces this with a real ETE.
    default_ete_window_hours: int = 8

    @field_validator("watchlist", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [x.strip().upper() for x in v.split(",") if x.strip()] or DEFAULT_WATCHLIST
        return v or DEFAULT_WATCHLIST


@lru_cache
def settings() -> Settings:
    return Settings()
