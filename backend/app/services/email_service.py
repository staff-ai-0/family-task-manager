"""
Email Service

Sends transactional emails via Resend (resend.com).
Supports bilingual content (ES/EN) based on user.preferred_lang.
"""
import resend
from typing import Optional
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.email_verification import EmailVerificationToken
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Bilingual copy
# ---------------------------------------------------------------------------

_COPY = {
    "verify_subject": {
        "es": "Verifica tu correo — Family Task Manager",
        "en": "Verify your email — Family Task Manager",
    },
    "verify_heading": {
        "es": "¡Bienvenido a Family Task Manager!",
        "en": "Welcome to Family Task Manager!",
    },
    "verify_body": {
        "es": "Hola {name}, gracias por registrarte. Por favor verifica tu correo electrónico haciendo clic en el botón de abajo:",
        "en": "Hi {name}, thanks for signing up. Please verify your email address by clicking the button below:",
    },
    "verify_btn": {
        "es": "Verificar correo",
        "en": "Verify email",
    },
    "verify_link_alt": {
        "es": "O copia y pega este enlace en tu navegador:",
        "en": "Or copy and paste this link into your browser:",
    },
    "verify_expiry": {
        "es": "Este enlace vence en 24 horas.",
        "en": "This link expires in 24 hours.",
    },
    "verify_ignore": {
        "es": "Si no creaste esta cuenta, puedes ignorar este correo.",
        "en": "If you did not create this account, you can ignore this email.",
    },
    "reset_subject": {
        "es": "Restablece tu contraseña — Family Task Manager",
        "en": "Reset your password — Family Task Manager",
    },
    "reset_heading": {
        "es": "Restablecer contraseña",
        "en": "Reset your password",
    },
    "reset_body": {
        "es": "Hola {name}, recibimos una solicitud para restablecer la contraseña de tu cuenta en Family Task Manager.",
        "en": "Hi {name}, we received a request to reset the password for your Family Task Manager account.",
    },
    "reset_btn": {
        "es": "Restablecer contraseña",
        "en": "Reset password",
    },
    "reset_link_alt": {
        "es": "O copia y pega este enlace en tu navegador:",
        "en": "Or copy and paste this link into your browser:",
    },
    "reset_expiry": {
        "es": "Por seguridad, este enlace vence en 1 hora.",
        "en": "For your security, this link expires in 1 hour.",
    },
    "reset_ignore": {
        "es": "Si no solicitaste este cambio, ignora este correo. Tu contraseña no cambiará.",
        "en": "If you did not request this, ignore this email. Your password will remain unchanged.",
    },
    "welcome_subject": {
        "es": "¡Bienvenido a Family Task Manager!",
        "en": "Welcome to Family Task Manager!",
    },
    "welcome_heading": {
        "es": "¡Te damos la bienvenida a tu familia!",
        "en": "Welcome to your family!",
    },
    "welcome_body": {
        "es": "Hola {name}, ¡te has unido exitosamente a {family_name}! Ahora puedes colaborar con tu familia en tareas, recompensas y finanzas.",
        "en": "Hi {name}, you've successfully joined {family_name}! You can now collaborate with your family on tasks, rewards, and finances.",
    },
    "welcome_btn": {
        "es": "Ir al Dashboard",
        "en": "Go to Dashboard",
    },
    "welcome_features": {
        "es": "Aquí hay algunas cosas que puedes hacer:",
        "en": "Here are some things you can do:",
    },
}


def _t(key: str, lang: str) -> str:
    """Return translation for key in given lang, fallback to 'en'."""
    lang = lang if lang in ("es", "en") else "en"
    return _COPY[key].get(lang, _COPY[key]["en"])


# ---------------------------------------------------------------------------
# HTML email template (AgentIA brand colours)
# ---------------------------------------------------------------------------

def _build_html(*, heading: str, body: str, btn_text: str, btn_url: str,
                link_label: str, expiry_note: str, ignore_note: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  body{{margin:0;padding:0;background:#030B1F;font-family:Arial,Helvetica,sans-serif;color:#e2e8f0}}
  .wrap{{max-width:580px;margin:40px auto;background:#0B1E4A;border-radius:12px;overflow:hidden;border:1px solid rgba(0,217,255,.15)}}
  .hdr{{background:linear-gradient(135deg,#05102A 0%,#0B1E4A 100%);padding:32px 40px;border-bottom:1px solid rgba(0,217,255,.2)}}
  .hdr-logo{{font-size:20px;font-weight:700;color:#00D9FF;letter-spacing:.5px}}
  .body{{padding:36px 40px}}
  h2{{margin:0 0 16px;font-size:22px;color:#fff}}
  p{{margin:0 0 14px;font-size:15px;line-height:1.6;color:#cbd5e1}}
  .btn{{display:inline-block;margin:8px 0 20px;padding:14px 32px;background:linear-gradient(135deg,#00D9FF,#B000FF);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;font-size:15px}}
  .link-box{{background:rgba(0,217,255,.06);border:1px solid rgba(0,217,255,.15);border-radius:6px;padding:10px 14px;word-break:break-all;font-size:12px;color:#94a3b8;margin-bottom:20px}}
  .note{{font-size:13px;color:#64748b;margin-bottom:8px}}
  .ftr{{background:#05102A;padding:20px 40px;font-size:12px;color:#475569;border-top:1px solid rgba(0,217,255,.1)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr"><span class="hdr-logo">Family Task Manager</span></div>
  <div class="body">
    <h2>{heading}</h2>
    <p>{body}</p>
    <a href="{btn_url}" class="btn">{btn_text}</a>
    <p class="note">{link_label}</p>
    <div class="link-box">{btn_url}</div>
    <p class="note">{expiry_note}</p>
    <p class="note">{ignore_note}</p>
  </div>
  <div class="ftr">&copy; 2026 AgentIA &mdash; Family Task Manager &mdash; <a href="https://family.agent-ia.mx" style="color:#00D9FF;text-decoration:none">family.agent-ia.mx</a></div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# EmailService
# ---------------------------------------------------------------------------

class EmailService:
    """Handles all transactional email sending via Resend."""

    # ------------------------------------------------------------------
    # Core sender
    # ------------------------------------------------------------------

    @staticmethod
    async def _send(*, to: str, subject: str, html: str) -> bool:
        """Send email via Resend SDK. Returns True on success."""
        if not settings.RESEND_API_KEY:
            print("WARNING: RESEND_API_KEY not configured. Email not sent.")
            print(f"  To: {to}  |  Subject: {subject}")
            return False

        resend.api_key = settings.RESEND_API_KEY
        try:
            resend.Emails.send({
                "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
                "to": [to],
                "subject": subject,
                "html": html,
            })
            return True
        except Exception as exc:
            print(f"Resend error: {exc}")
            return False

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    @staticmethod
    async def create_verification_token(
        db: AsyncSession,
        user: User,
    ) -> EmailVerificationToken:
        """Create (and persist) a new email verification token."""
        token = EmailVerificationToken(
            token=EmailVerificationToken.generate_token(),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(
                minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES
            ),
        )
        db.add(token)
        await db.commit()
        await db.refresh(token)
        return token

    @staticmethod
    async def send_verification_email(
        db: AsyncSession,
        user: User,
        base_url: str = "https://family.agent-ia.mx",
    ) -> bool:
        """Create a verification token and send the email."""
        lang = getattr(user, "preferred_lang", "en") or "en"
        token = await EmailService.create_verification_token(db, user)
        link = f"{base_url}/verify-email?token={token.token}"

        html = _build_html(
            heading=_t("verify_heading", lang),
            body=_t("verify_body", lang).format(name=user.name),
            btn_text=_t("verify_btn", lang),
            btn_url=link,
            link_label=_t("verify_link_alt", lang),
            expiry_note=_t("verify_expiry", lang),
            ignore_note=_t("verify_ignore", lang),
        )
        return await EmailService._send(
            to=user.email,
            subject=_t("verify_subject", lang),
            html=html,
        )

    @staticmethod
    async def verify_email_token(
        db: AsyncSession,
        token_string: str,
    ) -> Optional[User]:
        """Validate token, mark user as verified. Returns User or None."""
        from sqlalchemy import select

        result = await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token == token_string
            )
        )
        token = result.scalar_one_or_none()

        if not token or not token.is_valid:
            return None

        token.mark_as_used()

        result = await db.execute(select(User).where(User.id == token.user_id))
        user = result.scalar_one_or_none()

        if user:
            user.email_verified = True
            user.email_verified_at = datetime.utcnow()

        await db.commit()
        return user

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    @staticmethod
    async def create_password_reset_token(
        db: AsyncSession,
        user: User,
    ) -> PasswordResetToken:
        """Create (and persist) a new password reset token."""
        token = PasswordResetToken.create_for_user(user.id, hours_valid=1)
        db.add(token)
        await db.commit()
        await db.refresh(token)
        return token

    @staticmethod
    async def send_password_reset_email(
        db: AsyncSession,
        user: User,
        base_url: str = "https://family.agent-ia.mx",
    ) -> bool:
        """Create a reset token and send the email."""
        lang = getattr(user, "preferred_lang", "en") or "en"
        token = await EmailService.create_password_reset_token(db, user)
        link = f"{base_url}/reset-password?token={token.token}"

        html = _build_html(
            heading=_t("reset_heading", lang),
            body=_t("reset_body", lang).format(name=user.name),
            btn_text=_t("reset_btn", lang),
            btn_url=link,
            link_label=_t("reset_link_alt", lang),
            expiry_note=_t("reset_expiry", lang),
            ignore_note=_t("reset_ignore", lang),
        )
        return await EmailService._send(
            to=user.email,
            subject=_t("reset_subject", lang),
            html=html,
        )

    @staticmethod
    async def verify_password_reset_token(
        db: AsyncSession,
        token_string: str,
    ) -> Optional[PasswordResetToken]:
        """Return the valid PasswordResetToken, or None."""
        from sqlalchemy import select

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
        new_password_hash: str,
    ) -> Optional[User]:
        """Mark token used and set new password hash. Returns updated User."""
        from sqlalchemy import select

        token.is_used = True

        result = await db.execute(select(User).where(User.id == token.user_id))
        user = result.scalar_one_or_none()

        if user:
            user.password_hash = new_password_hash

        await db.commit()
        return user

    # ------------------------------------------------------------------
    # Welcome email (sent when invitation is accepted)
    # ------------------------------------------------------------------

    @staticmethod
    async def send_welcome_email(
        db: AsyncSession,
        user: User,
        family_name: str,
        base_url: str = "https://family.agent-ia.mx",
    ) -> bool:
        """Send a welcome email to a newly onboarded family member."""
        lang = getattr(user, "preferred_lang", "en") or "en"
        dashboard_link = f"{base_url}/dashboard"
        
        html = _build_html(
            heading=_t("welcome_heading", lang),
            body=_t("welcome_body", lang).format(name=user.name, family_name=family_name),
            btn_text=_t("welcome_btn", lang),
            btn_url=dashboard_link,
            link_label=_t("welcome_features", lang),
            expiry_note="",
            ignore_note="",
        )
        
        # Customize HTML to show features instead of expiry
        if lang == "es":
            features = """
            <ul style="margin: 15px 0; padding-left: 20px; color: #cbd5e1;">
                <li style="margin-bottom: 8px;">📋 Gestiona tareas familiares y asignaciones</li>
                <li style="margin-bottom: 8px;">🎁 Gana y canjea recompensas</li>
                <li style="margin-bottom: 8px;">💰 Colabora en presupuesto familiar</li>
                <li style="margin-bottom: 8px;">👥 Conecta con tu familia</li>
            </ul>
            """
        else:
            features = """
            <ul style="margin: 15px 0; padding-left: 20px; color: #cbd5e1;">
                <li style="margin-bottom: 8px;">📋 Manage family tasks and assignments</li>
                <li style="margin-bottom: 8px;">🎁 Earn and redeem rewards</li>
                <li style="margin-bottom: 8px;">💰 Collaborate on family budget</li>
                <li style="margin-bottom: 8px;">👥 Connect with your family</li>
            </ul>
            """
        
        html = html.replace('<p class="note">' + _t("welcome_features", lang) + '</p>', features)
        
        return await EmailService._send(
            to=user.email,
            subject=_t("welcome_subject", lang),
            html=html,
        )

    @staticmethod
    async def send_invitation_email(
        db: AsyncSession,
        invitation,  # FamilyInvitation model
        inviting_user: User,
        base_url: str = "https://family.agent-ia.mx",
    ) -> bool:
        """Send a family invitation email."""
        from app.models.family import Family
        from sqlalchemy import select
        
        # Get family name
        family_result = await db.execute(
            select(Family).where(Family.id == invitation.family_id)
        )
        family = family_result.scalar_one_or_none()
        family_name = family.name if family else "Tu Familia"
        
        # Build acceptance link
        acceptance_link = f"{base_url}/accept-invitation?code={invitation.invitation_code}"
        
        # Format expiration date
        expiration_date = invitation.expires_at.strftime("%d de %B de %Y")
        
        # Load and render HTML template
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            "email_templates",
            "invitation.html"
        )
        
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                html_template = f.read()
        except FileNotFoundError:
            # Fallback if template not found
            html_template = """<html><body>
            <h2>¡Te han invitado a unirte a una familia!</h2>
            <p>{{ invited_by_name }} te ha invitado a unirte a {{ family_name }}</p>
            <p><a href="{{ acceptance_link }}">Aceptar invitación</a></p>
            </body></html>"""
        
        # Replace template variables
        html = html_template.replace("{{ invited_by_name }}", inviting_user.name)
        html = html.replace("{{ family_name }}", family_name)
        html = html.replace("{{ acceptance_link }}", acceptance_link)
        html = html.replace("{{ invitation_code }}", invitation.invitation_code)
        html = html.replace("{{ expiration_date }}", expiration_date)
        
        return await EmailService._send(
            to=invitation.invited_email,
            subject=f"¡{inviting_user.name} te ha invitado a unirte a {family_name}!",
            html=html,
        )
