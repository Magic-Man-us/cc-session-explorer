from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cc_session_explorer.types import IdleSeconds


class ExplorerSettings(BaseSettings):
    """Explorer HTTP configuration, loaded from `CC_SESSION_EXPLORER_*` env vars and an
    optional `.env`."""

    model_config = SettingsConfigDict(env_prefix="CC_SESSION_EXPLORER_", env_file=".env")

    home_dir: Path = Field(default_factory=Path.home)
    export_path: Path | None = None
    idle_exit_seconds: IdleSeconds = 600.0
