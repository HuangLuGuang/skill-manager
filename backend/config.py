from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Agent Manager Admin Starter"
    API_PREFIX: str = "/api"
    DEBUG: bool = True

    SECRET_KEY: str = Field("change-me-in-production", description="JWT signing key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8

    DATA_DIR: str = Field(default=str(BASE_DIR / "data"))
    UPLOADS_DIR: str = Field(default=str(BASE_DIR / "uploads"))
    SQLITE_PATH: str = Field(default=str(BASE_DIR / "sqlite" / "admin_starter.db"))


settings = Settings()
