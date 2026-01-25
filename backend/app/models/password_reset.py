"""
Password Reset Token Model
"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import secrets

from app.core.database import Base


class PasswordResetToken(Base):
    """Password reset token for password recovery"""
    __tablename__ = "password_reset_tokens"
    
    token = Column(String(64), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="password_reset_tokens")
    
    @staticmethod
    def generate_token() -> str:
        """Generate a secure random token"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def create_for_user(user_id, hours_valid: int = 24):
        """Create a new password reset token"""
        token = PasswordResetToken.generate_token()
        expires_at = datetime.utcnow() + timedelta(hours=hours_valid)
        
        return PasswordResetToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at
        )
    
    def is_valid(self) -> bool:
        """Check if token is still valid"""
        return not self.is_used and datetime.utcnow() < self.expires_at
