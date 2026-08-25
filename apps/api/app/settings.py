from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    session_secret: str = Field(alias="SESSION_SECRET")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    # Founder access is granted by email match against a real account in
    # `users` -- no separate account type or password. Defaults to the
    # operator's own address so registering/logging in with it is, by
    # default, the founder login; override via FOUNDER_EMAIL in production
    # if that should ever change.
    founder_email: str = Field(default="vish.matale@gmail.com", alias="FOUNDER_EMAIL")

    # Stripe subscription billing -- built and tested (sandbox), but
    # optional at startup: going live needs Indian business KYC (PAN) that
    # isn't done yet, so these are unset in production for now and the
    # /v1/billing/* Stripe routes 503 rather than the app failing to boot.
    # Real payment today goes through the UPI flow below instead.
    stripe_secret_key: str | None = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    stripe_price_id: str | None = Field(default=None, alias="STRIPE_PRICE_ID")
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    # Manual UPI payment: the client pays this UPI ID directly and submits
    # the transaction reference; the founder reviews and approves in the
    # founder dashboard. No gateway, no KYC -- real money, human-verified.
    founder_upi_id: str = Field(default="", alias="FOUNDER_UPI_ID")
    founder_upi_payee_name: str = Field(default="PostMortem AI", alias="FOUNDER_UPI_PAYEE_NAME")
    subscription_price_inr: int = Field(default=999, alias="SUBSCRIPTION_PRICE_INR")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
