"""
Threadback backend configuration.

All settings are loaded from environment variables (or .env file).
No secrets are hard-coded here.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application-wide settings.

    Values are resolved in priority order:
      1. Real environment variables
      2. .env file (if present)
      3. Defaults defined below
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------
    # Application
    # ---------------------------------------------------------------
    app_name: str = "Threadback"
    app_version: str = "0.1.0"
    app_env: str = "development"  # development | production
    debug: bool = False

    # ---------------------------------------------------------------
    # Server
    # ---------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000

    # ---------------------------------------------------------------
    # CORS — extend this list in later milestones as needed
    # ---------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ---------------------------------------------------------------
    # Frontend Static Files (M16 Production Serving)
    # ---------------------------------------------------------------
    frontend_dist_dir: str | None = None

    # ---------------------------------------------------------------
    # M8 — Agent & Bedrock Settings
    # ---------------------------------------------------------------
    threadback_agent_provider: str = "mock"  # mock | bedrock
    threadback_mcp_url: str = "http://localhost:8000/mcp"
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # ---------------------------------------------------------------
    # M9 — Remote MCP, AgentCore Runtime & Alexa+ Auth Settings
    # ---------------------------------------------------------------
    auth_enabled: bool = False
    auth_issuer: str = (
        "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_threadback"
    )
    auth_audience: str = "threadback-mcp"
    auth_jwks_uri: str | None = None
    auth_secret_key: str | None = None
    agentcore_runtime_id: str | None = None
    agentcore_endpoint_url: str | None = None
    mcp_stateless: bool = True

    # ---------------------------------------------------------------
    # M10 — Intent Memory & SQLite Persistence
    # ---------------------------------------------------------------
    sqlite_db_path: str = "threadback.db"


def get_settings() -> Settings:
    """Return the application settings singleton."""
    return Settings()


# Module-level singleton — import this throughout the app
settings: Settings = get_settings()
