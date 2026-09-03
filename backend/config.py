from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Agent Manager Admin Starter"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    SECRET_KEY: str = Field("change-me-in-production", description="JWT signing key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    ENFORCE_SECURE_STARTUP: bool = False
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: str | None = None

    DATA_DIR: str = Field(default=str(BASE_DIR / "data"))
    UPLOADS_DIR: str = Field(default=str(BASE_DIR / "uploads"))
    SQLITE_PATH: str = Field(default=str(BASE_DIR / "sqlite" / "admin_starter.db"))

    MCP_ALLOW_HTTP: bool = False
    MCP_OUTBOUND_ALLOWLIST: str = ""
    MCP_MAX_RESPONSE_KB: int = 1024
    AUDIT_SIGNING_PRIVATE_KEY_PATH: str | None = None
    SECURITY_AUDIT_EXPORT_PATH: str | None = None

    # Baseline pages are enabled by default. Operators may still override these
    # settings as emergency kill switches outside the normal Compose workflow.
    AGENT_SECURITY_SCANNING_ENABLED: bool = True
    RUNTIME_TRACE_ENABLED: bool = True
    AGENT_SECURITY_UPSTREAM_LOCK_PATH: str = Field(
        default=str(BASE_DIR / "deploy" / "agent-security" / "upstreams.lock.json")
    )
    AGENT_SECURITY_WORKER_TOKEN: str | None = None
    AIG_SERVICE_URL: str = ""
    AIG_SERVICE_TOKEN: str | None = None

    # Headroom 智能压缩全局默认
    HEADROOM_COMPRESSION_ENABLED_BY_DEFAULT: bool = False
    HEADROOM_COMPRESSION_LEVEL: str = "auto"  # auto | conservative | aggressive


settings = Settings()
