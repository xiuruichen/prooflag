"""Typed settings from environment / .env. Never commit secrets."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_CONTACTS = {"you@example.com", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROOFLAG_", env_file=".env", extra="ignore")

    contact_email: str = "you@example.com"
    data_dir: Path = Path("data")
    llm_endpoint: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:8b"
    # SEC hard cap is 10 req/s; stay well under (plan target <= 2).
    sec_max_rps: float = Field(default=2.0, gt=0, le=5.0)
    fedreg_max_rps: float = Field(default=1.0, gt=0, le=5.0)
    # Venue (Kalshi / Polymarket) access: public data, unpublished unauthenticated limits.
    kalshi_base: str = "https://external-api.kalshi.com/trade-api/v2"
    gamma_base: str = "https://gamma-api.polymarket.com"
    clob_base: str = "https://clob.polymarket.com"
    venue_max_rps: float = Field(default=4.0, gt=0, le=10.0)
    # "Meaningful" = estimated 24h dollar volume (Kalshi: contracts x last price). OI alone and
    # Polymarket liquidity never count.
    min_vol24_usd: float = Field(default=1000.0, ge=0)
    # Curated watch allow-list seed (append-only table is the source of truth once loaded).
    allowlist_seed_path: Path = (
        Path(__file__).resolve().parents[2] / "config" / "watch_allowlist_seed.json"
    )
    # Reviewed company aliases (e.g. former names) layered over the SEC ticker file.
    entity_aliases_seed_path: Path = (
        Path(__file__).resolve().parents[2] / "config" / "entity_aliases.json"
    )
    # EDGAR window (America/New_York, weekdays) drives the price-snapshot cadence.
    edgar_window_start: str = "06:00"
    edgar_window_end: str = "22:00"
    snapshot_fast_minutes: int = Field(default=5, ge=1)
    snapshot_slow_minutes: int = Field(default=30, ge=1)
    catalog_interval_minutes: int = Field(default=60, ge=5)

    @model_validator(mode="after")
    def _check_cadence(self) -> Settings:
        if self.snapshot_fast_minutes > self.snapshot_slow_minutes:
            raise ValueError("snapshot_fast_minutes must be <= snapshot_slow_minutes")
        return self

    @property
    def user_agent(self) -> str:
        """SEC / EDGAR only. Never send this (it carries the contact email) to other hosts."""
        return f"Prooflag {self.contact_email}"

    @property
    def venue_user_agent(self) -> str:
        """Generic UA for Kalshi, Polymarket and other non-SEC hosts (no personal contact)."""
        return "Prooflag/0.1 (research; read-only)"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "prooflag.db"

    @property
    def locker_dir(self) -> Path:
        return self.data_dir / "locker"

    def require_real_contact(self) -> None:
        if self.contact_email in PLACEHOLDER_CONTACTS:
            raise ValueError("set PROOFLAG_CONTACT_EMAIL (SEC requires a real contact in the UA)")
