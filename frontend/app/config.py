"""
Frontend configuration
"""
import os
from typing import List

class Settings:
    """Frontend application settings"""
    
    # API Configuration
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    
    # Server
    PORT: int = int(os.getenv("PORT", "3000"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    
    # Application
    APP_NAME: str = "Family Task Manager"
    APP_VERSION: str = "1.0.0"


settings = Settings()
