"""
Email Service

Handles sending emails for verification, password reset, etc.
"""
import aiosmtplib
from email.message import EmailMessage
from typing import Optional
from datetime import datetime, timedelta

from app.core.config import settings
from app.models.email_verification import EmailVerificationToken
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession


class EmailService:
    """Service for email operations"""
    
    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """Send an email"""
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            print("WARNING: SMTP credentials not configured. Email not sent.")
            print(f"Would send to: {to_email}")
            print(f"Subject: {subject}")
            print(f"Content: {html_content}")
            return False
        
        try:
            message = EmailMessage()
            message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
            message["To"] = to_email
            message["Subject"] = subject
            
            if text_content:
                message.set_content(text_content)
            
            message.add_alternative(html_content, subtype="html")
            
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                start_tls=True,
            )
            
            return True
            
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    @staticmethod
    async def create_verification_token(
        db: AsyncSession,
        user: User
    ) -> EmailVerificationToken:
        """Create a new email verification token"""
        token = EmailVerificationToken(
            token=EmailVerificationToken.generate_token(),
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(
                minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES
            )
        )
        
        db.add(token)
        await db.commit()
        await db.refresh(token)
        
        return token
    
    @staticmethod
    async def send_verification_email(
        db: AsyncSession,
        user: User,
        base_url: str = "http://localhost:8000"
    ) -> bool:
        """Send email verification email"""
        # Create verification token
        token = await EmailService.create_verification_token(db, user)
        
        # Generate verification link
        verification_link = f"{base_url}/auth/verify-email?token={token.token}"
        
        # Create email content
        subject = "Verify your email - Family Task Manager"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background-color: #3b82f6; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Welcome to Family Task Manager!</h2>
                <p>Hi {user.name},</p>
                <p>Thank you for registering. Please verify your email address by clicking the button below:</p>
                <a href="{verification_link}" class="button">Verify Email</a>
                <p>Or copy and paste this link into your browser:</p>
                <p>{verification_link}</p>
                <p>This link will expire in 24 hours.</p>
                <div class="footer">
                    <p>If you didn't create this account, please ignore this email.</p>
                    <p>&copy; 2025 Family Task Manager. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Welcome to Family Task Manager!
        
        Hi {user.name},
        
        Thank you for registering. Please verify your email address by visiting:
        {verification_link}
        
        This link will expire in 24 hours.
        
        If you didn't create this account, please ignore this email.
        """
        
        return await EmailService.send_email(
            to_email=user.email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
    
    @staticmethod
    async def verify_email_token(
        db: AsyncSession,
        token_string: str
    ) -> Optional[User]:
        """Verify email token and mark user as verified"""
        from sqlalchemy import select
        
        # Find the token
        result = await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token == token_string
            )
        )
        token = result.scalar_one_or_none()
        
        if not token or not token.is_valid:
            return None
        
        # Mark token as used
        token.mark_as_used()
        
        # Get and update user
        result = await db.execute(
            select(User).where(User.id == token.user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.email_verified = True
            user.email_verified_at = datetime.utcnow()
        
        await db.commit()
        
        return user
    
    @staticmethod
    async def create_password_reset_token(
        db: AsyncSession,
        user: User
    ) -> PasswordResetToken:
        """Create a new password reset token"""
        token = PasswordResetToken.create_for_user(user.id, hours_valid=1)
        
        db.add(token)
        await db.commit()
        await db.refresh(token)
        
        return token
    
    @staticmethod
    async def send_password_reset_email(
        db: AsyncSession,
        user: User,
        base_url: str = "http://localhost:8000"
    ) -> bool:
        """Send password reset email"""
        # Create reset token
        token = await EmailService.create_password_reset_token(db, user)
        
        # Generate reset link
        reset_link = f"{base_url}/auth/reset-password?token={token.token}"
        
        # Create email content
        subject = "Reset your password - Family Task Manager"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background-color: #ef4444; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
                .warning {{ padding: 12px; background-color: #fef2f2; border-left: 4px solid #ef4444; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Reset Your Password</h2>
                <p>Hi {user.name},</p>
                <p>We received a request to reset your password for your Family Task Manager account.</p>
                <a href="{reset_link}" class="button">Reset Password</a>
                <p>Or copy and paste this link into your browser:</p>
                <p>{reset_link}</p>
                <div class="warning">
                    <strong>Security Notice:</strong> This link will expire in 1 hour for your security.
                </div>
                <div class="footer">
                    <p>If you didn't request this password reset, please ignore this email. Your password will remain unchanged.</p>
                    <p>&copy; 2025 Family Task Manager. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Reset Your Password
        
        Hi {user.name},
        
        We received a request to reset your password for your Family Task Manager account.
        
        Please visit this link to reset your password:
        {reset_link}
        
        This link will expire in 1 hour for your security.
        
        If you didn't request this password reset, please ignore this email.
        """
        
        return await EmailService.send_email(
            to_email=user.email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
    
    @staticmethod
    async def verify_password_reset_token(
        db: AsyncSession,
        token_string: str
    ) -> Optional[PasswordResetToken]:
        """Verify password reset token"""
        from sqlalchemy import select
        
        # Find the token
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token_string
            )
        )
        token = result.scalar_one_or_none()
        
        if not token or not token.is_valid():
            return None
        
        return token
    
    @staticmethod
    async def reset_password(
        db: AsyncSession,
        token: PasswordResetToken,
        new_password_hash: str
    ) -> Optional[User]:
        """Reset user password using token"""
        from sqlalchemy import select
        
        # Mark token as used
        token.is_used = True
        
        # Get and update user
        result = await db.execute(
            select(User).where(User.id == token.user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.password_hash = new_password_hash
        
        await db.commit()
        
        return user
