from __future__ import annotations

import functools
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    api_key: str = ""

    anthropic_api_key: str = ""
    model_name: str = "claude-sonnet-4-5"
    langsmith_api_key: str = ""
    langsmith_tracing: bool = True
    langsmith_project: str = "openemr-agent"

    cors_origins: str = "http://localhost:8300,https://localhost:9300"

    agent_base_url: str = "http://localhost:8000"
    openemr_base_url: str = "http://openemr:80"
    openemr_client_id: str = ""
    openemr_client_secret: str = ""
    openemr_username: str = "admin"
    openemr_password: str = "pass"

    # Deprecated: DB fields are used only by the server's internal billing
    # endpoint. Agent tools should use the /internal/billing HTTP endpoint
    # instead of connecting to the database directly.
    db_host: str = "mysql"
    db_port: int = 3306
    db_name: str = "openemr"
    db_user: str = "openemr"
    db_password: str = "openemr"
    db_unix_socket: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@functools.lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance. Reads .env from ai-agent/ dir if present."""
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.isfile(env_file):
        return Settings(_env_file=env_file)
    return Settings()
