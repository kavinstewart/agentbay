from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    """Runtime configuration for the PTY-based conductor service."""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/conductor"
    workspace_root: Path = Path(".workers")
    status_db_path: Path = Path(".workers/status.db")
    tmux_bin: str = "tmux"
    ttyd_bin: str = "ttyd"
    ttyd_host: str = "http://localhost"
    ttyd_port_start: int = 7680
    sentinel_start: str = "<<<AGENT_RESULT_START>>>"
    sentinel_end: str = "<<<AGENT_RESULT_END>>>"
    monitor_interval: float = 1.0
    critic_min_score: int = 9
    watcher_interval: float = 5.0
    watcher_default_stability: int = 3
    classifier_packs_dir: Path = Path("design/classifier_packs")
    default_cli_type: str = "codex"
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="openrouter/auto", validation_alias="OPENROUTER_MODEL")

    class Config:
        env_file = ".env"
        env_prefix = "CONDUCTOR_"
        extra = "ignore"


settings = Settings()
