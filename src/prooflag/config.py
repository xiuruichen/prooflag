"""Typed settings from environment / .env. Never commit secrets."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
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

    @property
    def user_agent(self) -> str:
        return f"Prooflag {self.contact_email}"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "prooflag.db"

    @property
    def locker_dir(self) -> Path:
        return self.data_dir / "locker"

    def require_real_contact(self) -> None:
        if self.contact_email in PLACEHOLDER_CONTACTS:
            raise ValueError("set PROOFLAG_CONTACT_EMAIL (SEC requires a real contact in the UA)")
