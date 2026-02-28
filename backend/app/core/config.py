from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Union
import os


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = "Family Task Manager"
    DEBUG: bool = True
    VERSION: str = "1.0.0"
    BASE_URL: str = "http://localhost:8000"  # Used for OAuth callbacks and email links
    
    # Database
    DATABASE_URL: str = "postgresql://familyapp:familyapp123@db:5432/familyapp"
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    
    # PayPal Configuration
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_MODE: str = "sandbox"  # sandbox or live
    PAYPAL_WEBHOOK_ID: str = ""
    
    # Email Configuration
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Family Task Manager"
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
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    @field_validator('ALLOWED_ORIGINS', mode='before')
    @classmethod
    def parse_allowed_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',')]
        return v
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra='ignore'
    )


# Create settings instance
settings = Settings()
