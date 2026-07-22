"""
Email Service

Sends transactional emails via Google Workspace SMTP (preferred) or Resend.
Supports bilingual content (ES/EN) based on user.preferred_lang.
"""
import logging
import resend
from typing import Optional
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.email_verification import EmailVerificationToken
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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

    # ----- Billing: payment-failed dunning -----
    "payfail_subject": {
        "es": "Problema con tu pago — Family Task Manager",
        "en": "Payment problem — Family Task Manager",
    },
    "payfail_heading": {
        "es": "No pudimos cobrar tu suscripción",
        "en": "We couldn't charge your subscription",
    },
    "payfail_body": {
        "es": "Hola {name}, el pago recurrente de tu plan <strong>{plan_name}</strong> falló. Conservarás tus beneficios hasta el <strong>{grace_deadline}</strong>; después de esa fecha tu familia pasará al plan gratuito. Actualiza tu método de pago en PayPal para evitar la interrupción:",
        "en": "Hi {name}, the recurring payment for your <strong>{plan_name}</strong> plan failed. You'll keep your benefits until <strong>{grace_deadline}</strong>; after that date your family will move to the free plan. Update your payment method on PayPal to avoid the interruption:",
    },
    "payfail_btn": {
        "es": "Actualizar pago en PayPal",
        "en": "Update payment on PayPal",
    },
    "payfail_link_alt": {
        "es": "O copia y pega este enlace en tu navegador:",
        "en": "Or copy and paste this link into your browser:",
    },
    "payfail_expiry": {
        "es": "PayPal reintentará el cobro automáticamente; en cuanto se complete, tu plan se restaurará solo.",
        "en": "PayPal retries the charge automatically; as soon as it succeeds, your plan is restored automatically.",
    },
    "payfail_ignore": {
        "es": "Si ya actualizaste tu método de pago, puedes ignorar este correo.",
        "en": "If you already updated your payment method, you can ignore this email.",
    },

    # ----- Billing: subscription activated -----
    "subact_subject": {
        "es": "Suscripción activada — Family Task Manager",
        "en": "Subscription activated — Family Task Manager",
    },
    "subact_heading": {
        "es": "¡Tu suscripción está activa!",
        "en": "Your subscription is active!",
    },
    "subact_body": {
        "es": "Hola {name}, tu plan <strong>{plan_name}</strong> está activo. Ya tienes acceso a todas las funciones incluidas. ¡Gracias por apoyar a Family Task Manager!",
        "en": "Hi {name}, your <strong>{plan_name}</strong> plan is now active. You have access to everything it includes. Thanks for supporting Family Task Manager!",
    },
    "subact_btn": {
        "es": "Ver mi suscripción",
        "en": "View my subscription",
    },
    "subact_link_alt": {
        "es": "O copia y pega este enlace en tu navegador:",
        "en": "Or copy and paste this link into your browser:",
    },
    "subact_expiry": {
        "es": "PayPal te enviará el recibo de cada cargo por separado.",
        "en": "PayPal sends a separate receipt for each charge.",
    },
    "subact_ignore": {
        "es": "Si no reconoces esta suscripción, cancélala desde la app o contáctanos.",
        "en": "If you don't recognize this subscription, cancel it from the app or contact us.",
    },

    # ----- Billing: subscription cancelled -----
    "subcanc_subject": {
        "es": "Suscripción cancelada — Family Task Manager",
        "en": "Subscription cancelled — Family Task Manager",
    },
    "subcanc_heading": {
        "es": "Tu suscripción fue cancelada",
        "en": "Your subscription was cancelled",
    },
    "subcanc_body": {
        "es": "Hola {name}, confirmamos la cancelación de tu plan <strong>{plan_name}</strong>. No habrá más cargos. Conservas los beneficios hasta el <strong>{period_end}</strong>; después tu familia pasará al plan gratuito (tus datos no se borran).",
        "en": "Hi {name}, we've confirmed the cancellation of your <strong>{plan_name}</strong> plan. There will be no further charges. You keep your benefits until <strong>{period_end}</strong>; after that your family moves to the free plan (your data is not deleted).",
    },
    "subcanc_btn": {
        "es": "Reactivar mi plan",
        "en": "Reactivate my plan",
    },
    "subcanc_link_alt": {
        "es": "O copia y pega este enlace en tu navegador:",
        "en": "Or copy and paste this link into your browser:",
    },
    "subcanc_expiry": {
        "es": "Puedes volver a suscribirte en cualquier momento desde Configuración → Suscripción.",
        "en": "You can re-subscribe anytime from Settings → Subscription.",
    },
    "subcanc_ignore": {
        "es": "Si no solicitaste esta cancelación, contáctanos de inmediato.",
        "en": "If you did not request this cancellation, contact us right away.",
    },

    # ----- Billing: subscription ended (dunning grace elapsed) -----
    "subend_subject": {
        "es": "Tu suscripción ha terminado — Family Task Manager",
        "en": "Your subscription has ended — Family Task Manager",
    },
    "subend_heading": {
        "es": "Tu suscripción terminó",
        "en": "Your subscription has ended",
    },
    "subend_body": {
        "es": "Hola {name}, no pudimos cobrar tu plan <strong>{plan_name}</strong> y el período de gracia terminó, así que tu familia pasó al plan gratuito. Tus datos no se borran. Puedes volver a suscribirte cuando quieras:",
        "en": "Hi {name}, we couldn't collect the payment for your <strong>{plan_name}</strong> plan and the grace period has ended, so your family has moved to the free plan. Your data is not deleted. You can re-subscribe anytime:",
    },
    "subend_btn": {
        "es": "Volver a suscribirme",
        "en": "Re-subscribe",
    },
    "subend_link_alt": {
        "es": "O copia y pega este enlace en tu navegador:",
        "en": "Or copy and paste this link into your browser:",
    },
    "subend_expiry": {
        "es": "Si PayPal completa un cobro pendiente, tu plan se restaurará automáticamente.",
        "en": "If PayPal completes an outstanding charge, your plan is restored automatically.",
    },
    "subend_ignore": {
        "es": "Si preferías cancelar de todos modos, no necesitas hacer nada.",
        "en": "If you meant to let it lapse, no action is needed.",
    },
}


def _t(key: str, lang: str) -> str:
    """Return translation for key in given lang, fallback to 'en'."""
    lang = lang if lang in ("es", "en") else "en"
    return _COPY[key].get(lang, _COPY[key]["en"])


# ---------------------------------------------------------------------------
# HTML email template (AgentIA brand colours)
# ---------------------------------------------------------------------------

def _footer_host() -> tuple[str, str]:
    """Display host + URL for the email footer, from the public frontend origin."""
    from urllib.parse import urlparse
    base = settings.email_link_base
    host = urlparse(base).netloc or base.replace("https://", "").replace("http://", "")
    return base, host


def _build_html(*, heading: str, body: str, btn_text: str, btn_url: str,
                link_label: str, expiry_note: str, ignore_note: str) -> str:
    footer_url, footer_host = _footer_host()
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
  <div class="ftr">&copy; 2026 AgentIA &mdash; Family Task Manager &mdash; <a href="{footer_url}" style="color:#00D9FF;text-decoration:none">{footer_host}</a></div>
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

    footer_url, footer_host = _footer_host()
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
  <div class="ftr">&copy; 2026 AgentIA &mdash; Family Task Manager &mdash; <a href="{footer_url}" style="color:#00D9FF;text-decoration:none">{footer_host}</a></div>
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
        """Send a transactional email. Returns True on success.

        Prefers SMTP (Google Workspace via App Password) when SMTP_HOST /
        SMTP_USER / SMTP_PASSWORD are configured; otherwise falls back to the
        Resend SDK. This lets prod send from info@agent-ia.mx over Workspace
        SMTP while local/dev can still use Resend (or neither).
        """
        if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
            return await EmailService._send_smtp(to=to, subject=subject, html=html)

        if settings.RESEND_API_KEY:
            resend.api_key = settings.RESEND_API_KEY
            try:
                resend.Emails.send({
                    "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
                    "to": [to],
                    "subject": subject,
                    "html": html,
                })
                return True
            except Exception:
                logger.warning("Resend send failed (to=%s, subject=%r)", to, subject, exc_info=True)
                return False

        logger.warning(
            "No email transport configured (SMTP_* / RESEND_API_KEY); email not sent (to=%s, subject=%r)",
            to, subject,
        )
        return False

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Crude HTML→text fallback for the multipart text/plain part.

        Not a full renderer — strips tags and collapses whitespace so clients
        (and spam filters) that prefer text/plain get something readable.
        """
        import re
        from html import unescape

        text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", "", text)
        text = unescape(text)
        # Collapse runs of blank lines / trailing spaces.
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln) or " "

    @staticmethod
    async def _send_smtp(*, to: str, subject: str, html: str) -> bool:
        """Send via SMTP. Runs the blocking socket work off the event loop.

        Transport security follows the port: 465 → implicit TLS (SMTP_SSL),
        otherwise STARTTLS when SMTP_USE_TLS is set (587 / Gmail Workspace).

        Gmail/Workspace rewrites or rejects a From that isn't the authenticated
        mailbox or one of its verified aliases, so the From address must match
        SMTP_USER (set EMAIL_FROM=info@agent-ia.mx in prod). We fall back to
        SMTP_USER if EMAIL_FROM is left unset.
        """
        import asyncio
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formataddr

        from_addr = settings.EMAIL_FROM or settings.SMTP_USER

        def _blocking() -> None:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr((settings.EMAIL_FROM_NAME, from_addr))
            msg["To"] = to
            # text/plain must come first; clients pick the last part they can render.
            msg.attach(MIMEText(EmailService._html_to_text(html), "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            if settings.SMTP_PORT == 465:
                server_cm = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
            else:
                server_cm = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
            with server_cm as server:
                if settings.SMTP_PORT != 465 and settings.SMTP_USE_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

        try:
            await asyncio.to_thread(_blocking)
            return True
        except Exception:
            logger.warning("SMTP send failed (to=%s, subject=%r)", to, subject, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Gig approval notifications
    # ------------------------------------------------------------------

    @staticmethod
    async def notify_parents_gig_pending(
        db: AsyncSession,
        *,
        family_id,
        child_name: str,
        gig_title: str,
        proof_text: str,
        proof_image_url: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> int:
        """Email all parents in *family_id* that a gig is awaiting approval.

        Returns the number of parents successfully notified. Fire-and-forget by
        contract — exceptions on individual sends are swallowed so the API
        response is not blocked by a flaky upstream.
        """
        import logging
        from sqlalchemy import select
        from app.models.user import User as UserModel, UserRole

        logger = logging.getLogger(__name__)
        base_url = (base_url or settings.email_link_base).rstrip("/")
        approvals_url = f"{base_url}/parent/approvals"

        parents = (await db.execute(
            select(UserModel).where(
                UserModel.family_id == family_id,
                UserModel.role == UserRole.PARENT,
                UserModel.is_active == True,
            )
        )).scalars().all()

        proof_html = (
            f"<blockquote style='border-left:3px solid #ddd;padding-left:12px;"
            f"color:#444;margin:12px 0;'>"
            f"{(proof_text or '').replace(chr(10), '<br>')}</blockquote>"
        )
        # Proof images are private (auth + family-scoped) and cannot be hot-linked
        # into an email — an email client has no session, so an <img> embed would
        # just 401 and render broken. Note that a photo exists; the parent views it
        # in-app via the Review button below.
        image_html = (
            "<p style='color:#666;font-size:14px;'>📷 A photo was attached — "
            "open the app to view it.</p>"
            if proof_image_url
            else ""
        )

        html = (
            f"<div style='font-family:system-ui,sans-serif;color:#222;'>"
            f"<h2 style='margin:0 0 8px;'>{child_name} submitted a task for review</h2>"
            f"<p><strong>{gig_title}</strong></p>"
            f"{proof_html}"
            f"{image_html}"
            f"<p><a href='{approvals_url}' "
            f"style='display:inline-block;background:#0a7;color:#fff;padding:10px 18px;"
            f"border-radius:6px;text-decoration:none;'>Review &amp; approve</a></p>"
            f"</div>"
        )
        # Task-review queue (chores + bonus tasks) — "gig" is reserved for the
        # cash gig board, whose emails go out from the gig-claim flow.
        subject = f"Task waiting: {child_name} - {gig_title}"

        sent = 0
        for parent in parents:
            try:
                ok = await EmailService._send(to=parent.email, subject=subject, html=html)
                if ok:
                    sent += 1
            except Exception as exc:
                logger.warning(f"gig-pending email to {parent.email} failed: {exc}")
        return sent

    # ------------------------------------------------------------------
    # Billing lifecycle emails (dunning / activation / cancellation)
    # ------------------------------------------------------------------

    @staticmethod
    async def _family_parents(db: AsyncSession, family_id) -> list:
        """All active PARENT users in a family (billing email recipients)."""
        from sqlalchemy import select
        from app.models.user import User as UserModel, UserRole

        return (await db.execute(
            select(UserModel).where(
                UserModel.family_id == family_id,
                UserModel.role == UserRole.PARENT,
                UserModel.is_active == True,  # noqa: E712
            )
        )).scalars().all()

    @staticmethod
    def _fmt_date(dt: Optional[datetime], lang: str) -> str:
        """Human date for email copy, per locale."""
        if dt is None:
            return "—"
        if lang == "es":
            return dt.strftime("%d/%m/%Y")
        return dt.strftime("%B %d, %Y")

    @staticmethod
    async def _send_billing_email(
        db: AsyncSession,
        family_id,
        *,
        key_prefix: str,
        btn_url: str,
        body_vars: dict,
    ) -> int:
        """Send one of the billing emails to every parent in the family.

        *key_prefix* selects the _COPY group (payfail / subact / subcanc).
        *body_vars* may contain per-lang callables (value = fn(lang)) for
        locale-dependent substitutions like formatted dates.

        Fire-and-forget by contract: individual failures are logged and
        swallowed so billing state transitions never depend on SMTP.
        """
        sent = 0
        try:
            parents = await EmailService._family_parents(db, family_id)
        except Exception:
            logger.warning(
                "billing email (%s): parent lookup failed for family %s",
                key_prefix, family_id, exc_info=True,
            )
            return 0

        for parent in parents:
            lang = _welcome_lang(parent)
            resolved = {
                k: (v(lang) if callable(v) else v) for k, v in body_vars.items()
            }
            try:
                html = _build_html(
                    heading=_t(f"{key_prefix}_heading", lang),
                    body=_t(f"{key_prefix}_body", lang).format(
                        name=parent.name, **resolved
                    ),
                    btn_text=_t(f"{key_prefix}_btn", lang),
                    btn_url=btn_url,
                    link_label=_t(f"{key_prefix}_link_alt", lang),
                    expiry_note=_t(f"{key_prefix}_expiry", lang),
                    ignore_note=_t(f"{key_prefix}_ignore", lang),
                )
                ok = await EmailService._send(
                    to=parent.email,
                    subject=_t(f"{key_prefix}_subject", lang),
                    html=html,
                )
                if ok:
                    sent += 1
            except Exception:
                logger.warning(
                    "billing email (%s) to %s failed",
                    key_prefix, parent.email, exc_info=True,
                )
        return sent

    @staticmethod
    async def send_payment_failed_email(
        db: AsyncSession,
        family_id,
        *,
        plan_name: str,
        grace_deadline: Optional[datetime],
    ) -> int:
        """Dunning notice: payment failed, grace deadline, PayPal update link."""
        return await EmailService._send_billing_email(
            db, family_id,
            key_prefix="payfail",
            # PayPal's "manage automatic payments" page — where the buyer
            # updates the funding source behind the subscription.
            btn_url="https://www.paypal.com/myaccount/autopay/",
            body_vars={
                "plan_name": plan_name,
                "grace_deadline": lambda lang: EmailService._fmt_date(
                    grace_deadline, lang
                ),
            },
        )

    @staticmethod
    async def send_subscription_activated_email(
        db: AsyncSession,
        family_id,
        *,
        plan_name: str,
    ) -> int:
        """Confirmation that a subscription is active (new, upgraded, or recovered)."""
        base = settings.email_link_base.rstrip("/")
        return await EmailService._send_billing_email(
            db, family_id,
            key_prefix="subact",
            btn_url=f"{base}/parent/settings/subscription",
            body_vars={"plan_name": plan_name},
        )

    @staticmethod
    async def send_subscription_cancelled_email(
        db: AsyncSession,
        family_id,
        *,
        plan_name: str,
        period_end: Optional[datetime],
    ) -> int:
        """Confirmation of cancellation + benefits-until date."""
        base = settings.email_link_base.rstrip("/")
        return await EmailService._send_billing_email(
            db, family_id,
            key_prefix="subcanc",
            btn_url=f"{base}/parent/settings/subscription",
            body_vars={
                "plan_name": plan_name,
                "period_end": lambda lang: EmailService._fmt_date(
                    period_end, lang
                ),
            },
        )

    @staticmethod
    async def send_subscription_ended_email(
        db: AsyncSession,
        family_id,
        *,
        plan_name: str,
    ) -> int:
        """Final notice: dunning grace elapsed, family downgraded to free.

        Sent exactly once per dunning cycle — the sweep dispatches it from
        the one-shot payment_failed → grace_expired transition (see
        subscription_state.notify_subscription_ended).
        """
        base = settings.email_link_base.rstrip("/")
        return await EmailService._send_billing_email(
            db, family_id,
            key_prefix="subend",
            btn_url=f"{base}/parent/settings/subscription",
            body_vars={"plan_name": plan_name},
        )

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
        base_url: str = "",
    ) -> bool:
        """Create a verification token and send the email."""
        base_url = (base_url or settings.email_link_base).rstrip("/")
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
            user.email_verified_at = datetime.now(timezone.utc)

        await db.commit()

        # After successful verification, fire the welcome email
        # (idempotent — if the user was somehow verified previously we
        # would have already set welcome_email_sent=True and this is a
        # no-op). Any failure here is swallowed; verification must not
        # depend on welcome email delivery.
        if user and user.email_verified:
            try:
                await EmailService.send_welcome_if_not_sent(
                    db=db, user=user, base_url=settings.email_link_base
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
        base_url: str = "",
    ) -> bool:
        """Create a reset token and send the email."""
        base_url = (base_url or settings.email_link_base).rstrip("/")
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
        base_url: str = "",
    ) -> bool:
        """
        Send a role-aware, bilingual welcome email with quick-start + manual link.

        Variant (parent vs minor) is determined by user.role. Language
        comes from user.preferred_lang. The caller is responsible for
        deciding WHEN to send this — for the idempotent dispatch used
        by actual registration/OAuth/invitation flows, call
        send_welcome_if_not_sent instead.
        """
        base_url = (base_url or settings.email_link_base).rstrip("/")
        lang = _welcome_lang(user)
        variant = _welcome_variant(user)
        dashboard_url = f"{base_url}/dashboard"
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
    async def _notify_admin_new_signup(user: User, family_name: str) -> None:
        """Best-effort ops alert on every new-user welcome dispatch. Never
        raises — a failure here must not affect the signup/welcome flow."""
        if not settings.ADMIN_ALERT_EMAIL:
            return
        try:
            html = (
                f"<p>Nuevo usuario registrado:</p>"
                f"<ul>"
                f"<li><b>Nombre:</b> {user.name}</li>"
                f"<li><b>Email:</b> {user.email}</li>"
                f"<li><b>Rol:</b> {user.role.value}</li>"
                f"<li><b>Familia:</b> {family_name}</li>"
                f"</ul>"
            )
            await EmailService._send(
                to=settings.ADMIN_ALERT_EMAIL,
                subject=f"Nuevo usuario: {user.name} ({family_name})",
                html=html,
            )
        except Exception:
            logger.warning(
                "admin signup alert failed for %s", user.email, exc_info=True
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

        base_url = base_url or settings.email_link_base
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
                await EmailService._notify_admin_new_signup(user, family_name)
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
        base_url: str = "",
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

        # Build acceptance link — points at the frontend origin (the
        # /accept-invitation page is an Astro route, not a backend route).
        base_url = (base_url or settings.email_link_base).rstrip("/")
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

        from urllib.parse import urlparse
        site_host = urlparse(base_url).netloc or base_url
        html = html.replace("{{ site_url }}", base_url)
        html = html.replace("{{ site_host }}", site_host)

        return await EmailService._send(
            to=invitation.invited_email,
            subject=f"¡{inviting_user.name} te ha invitado a unirte a {family_name}!",
            html=html,
        )
