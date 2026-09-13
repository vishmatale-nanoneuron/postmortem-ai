import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("postmortem_ai")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    # Optional -- when unset, drafting/extraction run on Gemini alone
    # (unchanged prior behavior). When set, Claude is used as a real
    # fallback provider for exactly the calls where Gemini's own call
    # fails (see ai/fallback_provider.py) -- never a second, independent
    # code path with its own bugs to keep in sync.
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-5", alias="ANTHROPIC_MODEL")
    session_secret: str = Field(alias="SESSION_SECRET")

    @field_validator("session_secret")
    @classmethod
    def _warn_if_session_secret_is_weak(cls, value: str) -> str:
        # A warning, not a hard failure -- this can't tell whether the
        # currently-deployed production secret is already weak (Vercel's
        # Sensitive env vars can never be read back to check), so refusing
        # to boot here risks turning "the secret might be weak" into a
        # guaranteed outage. 32 bytes matches PyJWT's own recommended
        # minimum for HMAC-SHA256 (RFC 7518 3.2), which our token signing
        # (security/tokens.py) uses.
        if len(value.encode()) < 32:
            logger.warning(
                "weak_session_secret",
                extra={"length_bytes": len(value.encode())},
            )
        return value
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    # Founder access is granted by email match against a real account in
    # `users` -- no separate account type or password. Defaults to the
    # operator's own address so registering/logging in with it is, by
    # default, the founder login; override via FOUNDER_EMAIL in production
    # if that should ever change.
    founder_email: str = Field(default="vish.matale@gmail.com", alias="FOUNDER_EMAIL")

    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    # Manual UPI payment: the client pays this UPI ID directly and submits
    # the transaction reference; the founder reviews and approves in the
    # founder dashboard. No gateway, no KYC -- real money, human-verified.
    founder_upi_id: str = Field(default="", alias="FOUNDER_UPI_ID")
    founder_upi_payee_name: str = Field(default="PostMortem AI", alias="FOUNDER_UPI_PAYEE_NAME")
    subscription_price_inr: int = Field(default=999, alias="SUBSCRIPTION_PRICE_INR")
    # Annual price is derived (monthly x this), not configured per currency:
    # four more price settings would be four more things to keep in sync,
    # and a mismatch between them is exactly the kind of pricing bug
    # nobody notices until a customer is charged wrongly. 10 = the
    # conventional "two months free" annual discount.
    annual_months_charged: int = Field(default=10, alias="ANNUAL_MONTHS_CHARGED")

    # Bank-alert auto-verification (bank_alerts.py): a client's bank alert
    # (forwarded by the founder from their real inbox to an email-routing
    # provider's inbound webhook) is the actual proof a payment happened --
    # no gateway, no KYC, and unlike a founder clicking "approve", it can't
    # be granted by mistake, since it requires text that only arrives after
    # a real credit. Unset means the endpoint is disabled (any request
    # rejected), same "unconfigured means off" stance as every other
    # not-yet-provisioned integration in this codebase.
    bank_alert_webhook_secret: str | None = Field(default=None, alias="BANK_ALERT_WEBHOOK_SECRET")

    # Vercel Cron's own convention: when a project has both a `crons` entry
    # in vercel.json and this env var set, Vercel automatically sends
    # `Authorization: Bearer <CRON_SECRET>` on the scheduled request -- no
    # separate webhook-signing scheme to invent. Unset means the endpoint
    # is disabled (any request rejected), same "unconfigured means off"
    # stance as bank_alert_webhook_secret above.
    cron_secret: str | None = Field(default=None, alias="CRON_SECRET")

    # Manual international wire (SWIFT) payment -- same pattern as UPI:
    # client wires the money directly, submits a reference, founder
    # approves. Beneficiary details are shared across currencies; the
    # correspondent bank differs per currency since that's how the
    # beneficiary bank actually routes each one.
    founder_bank_account_name: str = Field(default="", alias="FOUNDER_BANK_ACCOUNT_NAME")
    founder_bank_account_number: str = Field(default="", alias="FOUNDER_BANK_ACCOUNT_NUMBER")
    founder_bank_name: str = Field(default="", alias="FOUNDER_BANK_NAME")
    founder_bank_swift_code: str = Field(default="", alias="FOUNDER_BANK_SWIFT_CODE")
    # Who the invoice is from. A company outside India will not wire money
    # against an email that says "pay this account"; its finance team needs
    # a proforma invoice naming the seller, and a receipt afterwards to
    # expense it. All optional: unset, the invoice falls back to the bank
    # beneficiary name and omits the address and tax-id lines.
    seller_legal_name: str = Field(default="", alias="SELLER_LEGAL_NAME")
    seller_address: str = Field(default="", alias="SELLER_ADDRESS")
    seller_tax_id: str = Field(default="", alias="SELLER_TAX_ID")
    subscription_price_usd: int = Field(default=15, alias="SUBSCRIPTION_PRICE_USD")
    subscription_price_gbp: int = Field(default=12, alias="SUBSCRIPTION_PRICE_GBP")
    subscription_price_eur: int = Field(default=14, alias="SUBSCRIPTION_PRICE_EUR")

    # Airlock is sold as prepaid packs of scans, one price per currency,
    # bought over the same manual UPI/wire rails as the subscription. Per
    # currency rather than converted from one base price for the same reason
    # the subscription is: a customer pays a round number in their own money,
    # and the founder verifies a round number against a bank alert.
    airlock_pack_scans: int = Field(default=10_000, alias="AIRLOCK_PACK_SCANS")
    airlock_pack_price_inr: int = Field(default=999, alias="AIRLOCK_PACK_PRICE_INR")
    airlock_pack_price_usd: int = Field(default=15, alias="AIRLOCK_PACK_PRICE_USD")
    airlock_pack_price_gbp: int = Field(default=12, alias="AIRLOCK_PACK_PRICE_GBP")
    airlock_pack_price_eur: int = Field(default=14, alias="AIRLOCK_PACK_PRICE_EUR")
    # Bounds one claim. Ten packs is 100,000 scans -- past that, a customer
    # is talking to the founder anyway.
    airlock_max_packs_per_claim: int = Field(default=10, alias="AIRLOCK_MAX_PACKS_PER_CLAIM")

    wire_usd_correspondent_bank: str = Field(default="", alias="WIRE_USD_CORRESPONDENT_BANK")
    wire_usd_correspondent_swift: str = Field(default="", alias="WIRE_USD_CORRESPONDENT_SWIFT")
    wire_usd_nostro_account: str = Field(default="", alias="WIRE_USD_NOSTRO_ACCOUNT")
    wire_usd_aba: str = Field(default="", alias="WIRE_USD_ABA")

    wire_gbp_correspondent_bank: str = Field(default="", alias="WIRE_GBP_CORRESPONDENT_BANK")
    wire_gbp_correspondent_swift: str = Field(default="", alias="WIRE_GBP_CORRESPONDENT_SWIFT")
    wire_gbp_nostro_account: str = Field(default="", alias="WIRE_GBP_NOSTRO_ACCOUNT")
    wire_gbp_iban: str = Field(default="", alias="WIRE_GBP_IBAN")

    wire_eur_correspondent_bank: str = Field(default="", alias="WIRE_EUR_CORRESPONDENT_BANK")
    wire_eur_correspondent_swift: str = Field(default="", alias="WIRE_EUR_CORRESPONDENT_SWIFT")
    wire_eur_nostro_account: str = Field(default="", alias="WIRE_EUR_NOSTRO_ACCOUNT")
    wire_eur_iban: str = Field(default="", alias="WIRE_EUR_IBAN")

    # Real alerting for when the drafting model is actually broken (the
    # circuit breaker has opened after repeated failures) -- a plain HTTP
    # webhook (Slack incoming webhook, Discord webhook, or anything that
    # accepts a JSON POST). Optional: unset means no-op, same stance as
    # every other "not configured yet" setting above.
    alert_webhook_url: str | None = Field(default=None, alias="ALERT_WEBHOOK_URL")

    # Cloudflare Turnstile CAPTCHA on register/login -- optional, same
    # "unset means disabled" stance as everything else above. site_key is
    # public (shipped to the browser); secret_key stays server-only.
    turnstile_site_key: str | None = Field(default=None, alias="TURNSTILE_SITE_KEY")
    turnstile_secret_key: str | None = Field(default=None, alias="TURNSTILE_SECRET_KEY")

    # Password reset emails via Resend (see services/email.py) -- optional,
    # same "unset means disabled" stance as everything else above: the
    # request endpoint 503s rather than crashing when unconfigured, same
    # pattern as the manual-rail 'configured' checks in billing.py. resend_email_domain is
    # the real, verified sending domain provisioned via the Vercel
    # Marketplace Resend integration -- never a guessed/hardcoded domain.
    resend_api_key: str | None = Field(default=None, alias="RESEND_API_KEY")
    resend_email_domain: str | None = Field(default=None, alias="RESEND_EMAIL_DOMAIN")

    # The MCP SDK enforces DNS-rebinding protection (Host-header allowlist)
    # once TransportSecuritySettings is passed explicitly (mcp_server.py
    # does, deliberately, rather than leaving DNS-rebinding protection
    # disabled for "backwards compatibility" as the SDK does when left
    # unset) -- so the real production host must be a real default here,
    # not left to an env var that might never get set: an empty default
    # would 421 every legitimate MCP request the moment this deploys,
    # including from an authenticated, bearer-token-holding client, since
    # the SDK's Host check runs before this app's own auth middleware ever
    # does. Comma-separated, matching cors_origins_raw's shape; a bare host
    # (no scheme/port). Override via MCP_ALLOWED_HOSTS only if the API's
    # domain ever changes.
    mcp_allowed_hosts_raw: str = Field(
        default="postmortem-ai-api.vercel.app,127.0.0.1:8000,localhost:8000", alias="MCP_ALLOWED_HOSTS"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.mcp_allowed_hosts_raw.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
