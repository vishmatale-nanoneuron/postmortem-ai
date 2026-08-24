from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-5", alias="ANTHROPIC_MODEL")
    session_secret: str = Field(alias="SESSION_SECRET")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
