import logging
from email.message import EmailMessage

import aiosmtplib

from .config import get_settings

logger = logging.getLogger("auth_service.email")
settings = get_settings()


async def _send(to: str, subject: str, html: str) -> bool:
    if not settings.smtp_host:
        logger.info("SMTP not configured — email to %s:\nSubject: %s\n%s", to, subject, html)
        return True

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


async def send_verification_email(to: str, username: str, token: str) -> bool:
    url = f"{settings.frontend_url}/verify-email?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px">
      <h2>TG News Analytics</h2>
      <p>Здравствуйте, <b>{username}</b>!</p>
      <p>Подтвердите ваш email, перейдя по ссылке:</p>
      <a href="{url}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
        Подтвердить email
      </a>
      <p style="margin-top:16px;font-size:12px;color:#666">Ссылка действительна 24 часа.</p>
    </div>
    """
    return await _send(to, "Подтверждение email — TG News Analytics", html)


async def send_password_reset_email(to: str, username: str, token: str) -> bool:
    url = f"{settings.frontend_url}/reset-password?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px">
      <h2>TG News Analytics</h2>
      <p>Здравствуйте, <b>{username}</b>!</p>
      <p>Вы запросили сброс пароля. Перейдите по ссылке:</p>
      <a href="{url}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
        Сбросить пароль
      </a>
      <p style="margin-top:16px;font-size:12px;color:#666">Ссылка действительна 1 час. Если вы не запрашивали сброс — проигнорируйте это письмо.</p>
    </div>
    """
    return await _send(to, "Сброс пароля — TG News Analytics", html)
