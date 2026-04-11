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
    # ----- Welcome email, PARENT variant (5-step quick-start) -----
    "welcome_parent_subject": {
        "es": "¡Bienvenido a Family Task Manager, {name}!",
        "en": "Welcome to Family Task Manager, {name}!",
    },
    "welcome_parent_heading": {
        "es": "¡Bienvenido, {name}!",
        "en": "Welcome, {name}!",
    },
    "welcome_parent_opening": {
        "es": "Hola {name}, bienvenido a <strong>{family_name}</strong> en Family Task Manager. Como padre/madre en esta familia, tienes acceso completo para crear tareas, configurar recompensas, llevar el presupuesto y administrar a todos los miembros.",
        "en": "Hi {name}, welcome to <strong>{family_name}</strong> on Family Task Manager. As a parent in this family, you have full access to create tasks, configure rewards, track budgets, and manage all members.",
    },
    "welcome_parent_steps_heading": {
        "es": "🚀 Tus primeros 5 pasos",
        "en": "🚀 Your first 5 steps",
    },
    "welcome_parent_step1": {
        "es": "📋 <strong>Crea tu primera tarea</strong> — ve a <em>Dashboard → Nueva tarea</em>, asígnala a ti o a otro miembro, ponle puntos como premio.",
        "en": "📋 <strong>Create your first task</strong> — go to <em>Dashboard → New task</em>, assign it to yourself or another member, set points as the reward.",
    },
    "welcome_parent_step2": {
        "es": "👨‍👩‍👧 <strong>Invita a tu familia</strong> — desde <em>Settings → Miembros</em> genera un código de invitación y compártelo con tu pareja, hijos o adolescentes.",
        "en": "👨‍👩‍👧 <strong>Invite your family</strong> — from <em>Settings → Members</em> generate an invitation code and share it with your partner, kids, or teens.",
    },
    "welcome_parent_step3": {
        "es": "🎁 <strong>Configura recompensas</strong> — en <em>Rewards</em> define los premios que los miembros pueden canjear con los puntos que ganen.",
        "en": "🎁 <strong>Set up rewards</strong> — in <em>Rewards</em>, define the prizes members can redeem with the points they earn.",
    },
    "welcome_parent_step4": {
        "es": "💰 <strong>Conecta tu presupuesto</strong> — en <em>Budget</em> crea cuentas, categorías y empieza a registrar ingresos/gastos (o escanea un recibo con la cámara).",
        "en": "💰 <strong>Connect your budget</strong> — in <em>Budget</em> create accounts, categories, and start logging income/expenses (or scan a receipt with your camera).",
    },
    "welcome_parent_step5": {
        "es": "⚙️ <strong>Ajusta el idioma y las notificaciones</strong> — en <em>Profile</em> elige español/inglés y revisa tus preferencias.",
        "en": "⚙️ <strong>Adjust language and notifications</strong> — in <em>Profile</em> pick English/Spanish and review your preferences.",
    },
    "welcome_parent_cta": {
        "es": "Abrir mi dashboard →",
        "en": "Open my dashboard →",
    },
    "welcome_parent_guide_link": {
        "es": "📘 Ver manual completo →",
        "en": "📘 View full user guide →",
    },

    # ----- Welcome email, MINOR variant (CHILD/TEEN, 4-step quick-start) -----
    "welcome_minor_subject": {
        "es": "¡Bienvenido a {family_name}, {name}!",
        "en": "Welcome to {family_name}, {name}!",
    },
    "welcome_minor_heading": {
        "es": "¡Bienvenido, {name}!",
        "en": "Welcome, {name}!",
    },
    "welcome_minor_opening": {
        "es": "Hola {name}, ya eres parte de <strong>{family_name}</strong> en Family Task Manager. Aquí puedes ver tus tareas, completarlas para ganar puntos, y canjear esos puntos por recompensas.",
        "en": "Hi {name}, you're now part of <strong>{family_name}</strong> on Family Task Manager. Here you can see your tasks, complete them to earn points, and redeem those points for rewards.",
    },
    "welcome_minor_steps_heading": {
        "es": "🚀 Cómo empezar",
        "en": "🚀 Getting started",
    },
    "welcome_minor_step1": {
        "es": "📋 <strong>Revisa tus tareas del día</strong> — abre <em>Dashboard</em> y verás todo lo que te toca hacer hoy, con cuántos puntos vale cada una.",
        "en": "📋 <strong>Check today's tasks</strong> — open <em>Dashboard</em> and you'll see everything assigned to you today, with the points each one is worth.",
    },
    "welcome_minor_step2": {
        "es": "✅ <strong>Marca las tareas como completadas</strong> — cuando termines algo, ponle check. Tus papás revisarán y recibirás los puntos.",
        "en": "✅ <strong>Mark tasks as done</strong> — when you finish something, check it off. Your parents will review and you'll get the points.",
    },
    "welcome_minor_step3": {
        "es": "🎁 <strong>Canjea tus puntos por recompensas</strong> — en <em>Rewards</em> ves la lista de premios disponibles. Elige y canjea.",
        "en": "🎁 <strong>Redeem points for rewards</strong> — in <em>Rewards</em> you'll see the list of available prizes. Pick one and redeem.",
    },
    "welcome_minor_step4": {
        "es": "🌐 <strong>Elige tu idioma</strong> — en <em>Profile</em> puedes cambiar entre español e inglés cuando quieras.",
        "en": "🌐 <strong>Pick your language</strong> — in <em>Profile</em> you can switch between English and Spanish anytime.",
    },
    "welcome_minor_cta": {
        "es": "Ver mis tareas →",
        "en": "See my tasks →",
    },
    "welcome_minor_guide_link": {
        "es": "📘 Ver guía para miembros →",
        "en": "📘 View members' guide →",
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
# Welcome email helpers
# ---------------------------------------------------------------------------

def _welcome_variant(user: User) -> str:
    """Return 'parent' for PARENT users, 'minor' for CHILD and TEEN."""
    from app.models.user import UserRole

    return "parent" if user.role == UserRole.PARENT else "minor"


def _guide_url(base_url: str, lang: str) -> str:
    """Return the URL for the hosted user guide in the user's language."""
    base = base_url.rstrip("/")
    return f"{base}/ayuda" if lang == "es" else f"{base}/help"


def _welcome_lang(user: User) -> str:
    """Normalize user.preferred_lang to one of our supported locales."""
    lang = getattr(user, "preferred_lang", "en") or "en"
    return "es" if lang == "es" else "en"


def _build_welcome_html(
    *,
    variant: str,
    lang: str,
    user_name: str,
    family_name: str,
    dashboard_url: str,
    guide_url: str,
) -> str:
    """
    Construct the full welcome email HTML.

    Unlike _build_html (the generic heading+body+button template used by
    verify/reset/invitation emails), this helper owns the entire body
    because the welcome structure is richer: greeting, role-aware
    opening paragraph, numbered quick-start list (5 steps for parent,
    4 for minor), primary CTA to the dashboard, and a secondary link
    to the hosted user guide. No html.replace tricks — every piece is
    substituted explicitly.
    """
    opening = _t(f"welcome_{variant}_opening", lang).format(
        name=user_name, family_name=family_name
    )
    heading = _t(f"welcome_{variant}_heading", lang).format(name=user_name)
    steps_heading = _t(f"welcome_{variant}_steps_heading", lang)
    cta = _t(f"welcome_{variant}_cta", lang)
    guide_link_label = _t(f"welcome_{variant}_guide_link", lang)

    step_count = 5 if variant == "parent" else 4
    step_items = "\n".join(
        f"      <li style=\"margin-bottom:12px\">{_t(f'welcome_{variant}_step{i}', lang)}</li>"
        for i in range(1, step_count + 1)
    )

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  body{{margin:0;padding:0;background:#030B1F;font-family:Arial,Helvetica,sans-serif;color:#e2e8f0}}
  .wrap{{max-width:600px;margin:40px auto;background:#0B1E4A;border-radius:12px;overflow:hidden;border:1px solid rgba(0,217,255,.15)}}
  .hdr{{background:linear-gradient(135deg,#05102A 0%,#0B1E4A 100%);padding:32px 40px;border-bottom:1px solid rgba(0,217,255,.2)}}
  .hdr-logo{{font-size:20px;font-weight:700;color:#00D9FF;letter-spacing:.5px}}
  .body{{padding:36px 40px}}
  h2{{margin:0 0 20px;font-size:26px;color:#fff}}
  p.opening{{margin:0 0 24px;font-size:15px;line-height:1.6;color:#cbd5e1}}
  h3.steps-heading{{margin:28px 0 16px;font-size:18px;color:#fff}}
  ol.steps{{margin:0 0 28px;padding-left:22px;color:#cbd5e1;font-size:14px;line-height:1.55}}
  ol.steps li strong{{color:#fff}}
  .btn{{display:inline-block;margin:0 0 20px;padding:14px 32px;background:linear-gradient(135deg,#00D9FF,#B000FF);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;font-size:15px}}
  .guide-link{{display:block;margin-top:14px;font-size:14px;color:#00D9FF;text-decoration:none;font-weight:500}}
  .ftr{{background:#05102A;padding:20px 40px;font-size:12px;color:#475569;border-top:1px solid rgba(0,217,255,.1)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr"><span class="hdr-logo">Family Task Manager</span></div>
  <div class="body">
    <h2>{heading}</h2>
    <p class="opening">{opening}</p>
    <h3 class="steps-heading">{steps_heading}</h3>
    <ol class="steps">
{step_items}
    </ol>
    <a href="{dashboard_url}" class="btn">{cta}</a>
    <a href="{guide_url}" class="guide-link">{guide_link_label}</a>
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

        # After successful verification, fire the welcome email
        # (idempotent — if the user was somehow verified previously we
        # would have already set welcome_email_sent=True and this is a
        # no-op). Any failure here is swallowed; verification must not
        # depend on welcome email delivery.
        if user and user.email_verified:
            try:
                await EmailService.send_welcome_if_not_sent(
                    db=db, user=user, base_url=settings.BASE_URL
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    f"welcome dispatch after verify failed for {user.email}",
                    exc_info=True,
                )

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
        """
        Send a role-aware, bilingual welcome email with quick-start + manual link.

        Variant (parent vs minor) is determined by user.role. Language
        comes from user.preferred_lang. The caller is responsible for
        deciding WHEN to send this — for the idempotent dispatch used
        by actual registration/OAuth/invitation flows, call
        send_welcome_if_not_sent instead.
        """
        lang = _welcome_lang(user)
        variant = _welcome_variant(user)
        dashboard_url = f"{base_url.rstrip('/')}/dashboard"
        guide_url = _guide_url(base_url, lang)

        html = _build_welcome_html(
            variant=variant,
            lang=lang,
            user_name=user.name,
            family_name=family_name,
            dashboard_url=dashboard_url,
            guide_url=guide_url,
        )

        subject = _t(f"welcome_{variant}_subject", lang).format(
            name=user.name, family_name=family_name
        )

        return await EmailService._send(
            to=user.email,
            subject=subject,
            html=html,
        )

    @staticmethod
    async def send_welcome_if_not_sent(
        db: AsyncSession,
        user: User,
        base_url: Optional[str] = None,
    ) -> bool:
        """
        Idempotent welcome dispatcher.

        Short-circuits if user.welcome_email_sent is already True.
        Resolves family_name lazily (fallback to a generic label if the
        family row can't be loaded, so a missing family never blocks the
        welcome from being recorded as sent). Marks welcome_email_sent
        True on successful Resend call and commits. Catches all
        exceptions: Resend failures, missing Family, template errors,
        DB commit errors. Returns True on success or already-sent,
        False on any failure. Never raises — this is fire-and-forget
        by contract and must not block the caller flow.
        """
        import logging
        from sqlalchemy import select

        logger = logging.getLogger(__name__)

        if getattr(user, "welcome_email_sent", False):
            logger.debug(f"welcome already sent to {user.email}, skipping")
            return True

        base_url = base_url or settings.BASE_URL
        lang = _welcome_lang(user)

        try:
            # Resolve family_name — fall back gracefully if the relation
            # is not loadable for any reason (orphan row, missing FK, ...).
            from app.models.family import Family
            family_name: str
            try:
                result = await db.execute(
                    select(Family).where(Family.id == user.family_id)
                )
                family = result.scalar_one_or_none()
                family_name = (
                    family.name
                    if family and family.name
                    else ("tu familia" if lang == "es" else "your family")
                )
            except Exception as fe:
                logger.warning(
                    f"welcome email: could not resolve family for user "
                    f"{user.email}: {fe}"
                )
                family_name = "tu familia" if lang == "es" else "your family"

            sent = await EmailService.send_welcome_email(
                db=db,
                user=user,
                family_name=family_name,
                base_url=base_url,
            )

            if sent:
                user.welcome_email_sent = True
                await db.commit()
                await db.refresh(user)
                logger.info(f"welcome email sent to {user.email} ({lang}, {_welcome_variant(user)})")
                return True

            logger.warning(f"welcome email dispatch returned False for {user.email}")
            return False

        except Exception as e:
            logger.warning(
                f"welcome email dispatch failed for {user.email}: {e}",
                exc_info=True,
            )
            return False

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
