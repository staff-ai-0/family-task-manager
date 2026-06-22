from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from typing import List, Union
import os

# SECRET_KEY values that must never be used in production (forgeable JWTs/cookies).
_INSECURE_SECRET_KEYS = {"", "your-secret-key-change-this-in-production"}

# Fold Vault KV secrets into os.environ before Settings() is instantiated.
# This is a no-op if VAULT_ADDR/VAULT_TOKEN aren't set or if Vault is
# unreachable, in which case pydantic falls back to .env / shell env as before.
from app.core.vault_bootstrap import populate_env_from_vault

populate_env_from_vault()


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = "Family Task Manager"
    DEBUG: bool = True
    VERSION: str = "1.0.0"
    BASE_URL: str = "http://localhost:8000"  # Used for OAuth callbacks and email links
    PUBLIC_URL: str = ""  # Public-facing frontend origin (e.g. https://gcp-family.agent-ia.mx); used for PayPal return/cancel URLs
    
    # Database
    DATABASE_URL: str = "postgresql://familyapp:familyapp123@db:5432/familyapp"
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour (was 10080 / 7 days)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Separate signing key for Starlette SessionMiddleware cookies so it does
    # not share the JWT signing key. Defaults to SECRET_KEY when unset so dev
    # and existing envs keep working; production .env sets a distinct value.
    SESSION_SECRET_KEY: str = ""

    # Trust-score auto-approval: once a user has this many consecutive
    # approved gigs, subsequent gig completions auto-approve and credit
    # points immediately. A parent rejection resets the streak to 0.
    GIG_AUTO_APPROVE_STREAK: int = 3

    # AI photo validation: when a gig is submitted with a proof image and
    # the user has NOT yet earned trust-streak auto-approval, the photo is
    # sent to the vision model for cross-check against the template title.
    # Score >= GIG_AI_AUTO_APPROVE_THRESHOLD → auto-approve. Set to 1.1 to
    # disable AI auto-approval (forces manual review when no trust streak).
    GIG_AI_AUTO_APPROVE_THRESHOLD: float = 0.8

    # Jarvis copilot daily message cap per family. Each user → assistant
    # exchange counts as one message. Prevents accidental spend overruns
    # on the LiteLLM proxy. 0 = unlimited.
    JARVIS_DAILY_MESSAGE_CAP: int = 100
    # LiteLLM model alias for Jarvis chat. gemini-2.5-flash is the only model
    # the FTM virtual key can actually reach end-to-end right now — the granted
    # Anthropic (haiku/claude-sonnet) + OpenAI (gpt-4o) routes 401 upstream and
    # qwen2.5/mistral aliases 400 as invalid (see jctux/platform#86). It's also
    # the receipt scanner's model, so the proxy path is proven. Override via
    # JARVIS_MODEL env once platform fixes the other upstreams.
    JARVIS_MODEL: str = "gemini-2.5-flash"

    # Stripe settings removed 2026-05-24. PayPal is the canonical
    # billing path. See feedback_no_stripe memory entry.

    # Web Push (VAPID). Generate keys with:
    #   python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.private_pem(), v.public_key.to_string())"
    # If unset, PushService.send no-ops with a warning log; the app
    # otherwise runs normally (email still fires).
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_CLAIM_EMAIL: str = "admin@agent-ia.mx"
    
    # Google OAuth
    # GOOGLE_CLIENT_ID is the primary Web client (legacy single-value field,
    # kept so existing code that reads settings.GOOGLE_CLIENT_ID directly
    # still works). GOOGLE_CLIENT_IDS is a comma-separated list of additional
    # accepted audiences (e.g. mobile app client IDs issued under the same
    # Google project). Token verification accepts any aud in the union of
    # both — see app.services.google_oauth_service.verify_google_token.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_IDS: Union[List[str], str] = []
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"

    @property
    def google_accepted_audiences(self) -> List[str]:
        """Union of GOOGLE_CLIENT_ID and GOOGLE_CLIENT_IDS, empty strings removed."""
        ids: List[str] = []
        if self.GOOGLE_CLIENT_ID:
            ids.append(self.GOOGLE_CLIENT_ID)
        if isinstance(self.GOOGLE_CLIENT_IDS, list):
            ids.extend([x for x in self.GOOGLE_CLIENT_IDS if x])
        # de-dupe while preserving order
        seen: set[str] = set()
        out: List[str] = []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out
    
    # PayPal Configuration
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_MODE: str = "sandbox"  # sandbox or live
    PAYPAL_WEBHOOK_ID: str = ""

    # PayPal Subscription Plan IDs
    PAYPAL_PLAN_ID_PLUS_MONTHLY: str = ""
    PAYPAL_PLAN_ID_PLUS_ANNUAL: str = ""
    PAYPAL_PLAN_ID_PRO_MONTHLY: str = ""
    PAYPAL_PLAN_ID_PRO_ANNUAL: str = ""
    
    # Email Configuration
    # Transport priority in EmailService._send: SMTP (when SMTP_HOST/USER/PASSWORD
    # set) → Resend (when RESEND_API_KEY set) → no-op warning.
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@agent-ia.mx"
    EMAIL_FROM_NAME: str = "Family Task Manager"
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = 1440  # 24 hours

    # SMTP (Google Workspace via App Password). When set, takes precedence over
    # Resend. EMAIL_FROM must match SMTP_USER (or one of its verified aliases),
    # else Gmail rewrites/rejects the From header.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True  # STARTTLS on the SMTP_PORT
    
    # CORS
    ALLOWED_ORIGINS: Union[List[str], str] = [
        "http://localhost:8000",
        "http://localhost:3000",
        "https://fam.a-ai4all.com",
    ]
    
    @property
    def google_redirect_uri(self) -> str:
        """Generate Google redirect URI from BASE_URL"""
        if self.GOOGLE_REDIRECT_URI:
            return self.GOOGLE_REDIRECT_URI
        return f"{self.BASE_URL}/auth/google/callback"

    @property
    def email_link_base(self) -> str:
        """Origin for links embedded in transactional emails.

        Every page an email links to (accept-invitation, verify-email,
        reset-password, dashboard, parent/approvals) is a *frontend* route,
        so links must point at the public frontend origin (PUBLIC_URL), NOT
        BASE_URL — which is the API origin used for OAuth callbacks. Falls
        back to BASE_URL when PUBLIC_URL is unset (e.g. local dev).
        """
        return (self.PUBLIC_URL or self.BASE_URL).rstrip("/")

    # Redis (Optional)
    REDIS_URL: str = "redis://redis:6379/0"

    # Storage backend for the slowapi rate limiter. Empty -> in-memory (per
    # worker). Set to a redis:// URL in multi-worker / multi-instance deploys so
    # the limit window is shared across workers. (Pydantic extra='ignore' means an
    # env var must have a matching field here to take effect — hence this field.)
    RATE_LIMIT_STORAGE_URI: str = ""

    # Rate-limit master switch. When unset (None) it follows DEBUG: off in local
    # dev / E2E (DEBUG=true), on in prod (DEBUG=false). Set explicitly to
    # decouple from DEBUG — e.g. an internet-facing staging box that runs
    # DEBUG=true should still enforce limits: set RATE_LIMIT_ENABLED=true there.
    RATE_LIMIT_ENABLED: Union[bool, None] = None

    # LiteLLM Proxy (for auto-translation via mistral-nemo)
    LITELLM_API_BASE: str = "http://10.1.0.99:4000"
    LITELLM_API_KEY: str = ""
    LITELLM_MODEL: str = "mistral-nemo"

    # Vision model used for receipt scanning. Must be a registered alias in
    # litellm_config.yaml. Per-family override stored in Redis takes precedence
    # when set via /api/budget/ai-settings/models.
    RECEIPT_MODEL: str = "gemini-2.5-flash"

    # Anthropic API (for receipt scanning via Claude Vision)
    ANTHROPIC_API_KEY: str = ""

    # Google Cloud Storage bucket for receipt image persistence. When
    # empty (default in local dev / tests), the scanner skips the
    # upload step and transactions are stored without an image.
    # In production the VM .env sets this to `family-prod-receipts`.
    GCS_RECEIPT_BUCKET: str = ""

    # Internal service-to-service token (for /api/internal/* endpoints).
    # If empty, all internal endpoints reject with 403.
    INTERNAL_API_TOKEN: str = ""
    
    # Logging
    LOG_LEVEL: str = "INFO"

    # Error monitoring — set SENTRY_DSN to activate; empty string = disabled
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    
    @field_validator('ALLOWED_ORIGINS', mode='before')
    @classmethod
    def parse_allowed_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v

    @field_validator('GOOGLE_CLIENT_IDS', mode='before')
    @classmethod
    def parse_google_client_ids(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [i.strip() for i in v.split(',') if i.strip()]
        return v

    @model_validator(mode='after')
    def _enforce_production_secrets(self):
        """Fail fast in production (DEBUG=false) if SECRET_KEY is unset or still
        the shipped placeholder — that would mean forgeable JWTs and session
        cookies. Local/dev (DEBUG=true) is allowed to keep the default."""
        if not self.DEBUG and self.SECRET_KEY in _INSECURE_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY is unset or still the insecure default while DEBUG is "
                "false. Set a strong SECRET_KEY in the environment before running "
                "in production."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra='ignore'
    )


# Create settings instance
settings = Settings()
