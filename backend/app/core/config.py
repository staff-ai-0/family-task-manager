from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Union
import os

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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

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

    # Frankie copilot daily message cap per family. Each user → assistant
    # exchange counts as one message. Prevents accidental spend overruns
    # on the LiteLLM proxy. 0 = unlimited.
    FRANKIE_DAILY_MESSAGE_CAP: int = 100

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
    
    # Email Configuration (Resend)
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@agent-ia.mx"
    EMAIL_FROM_NAME: str = "Family Task Manager"
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = 1440  # 24 hours
    
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
    
    # Redis (Optional)
    REDIS_URL: str = "redis://redis:6379/0"
    
    # LiteLLM Proxy (for auto-translation via mistral-nemo)
    LITELLM_API_BASE: str = "http://10.1.0.99:4000"
    LITELLM_API_KEY: str = ""
    LITELLM_MODEL: str = "mistral-nemo"

    # Anthropic API (for receipt scanning via Claude Vision)
    ANTHROPIC_API_KEY: str = ""
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
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
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra='ignore'
    )


# Create settings instance
settings = Settings()
