from __future__ import annotations
import smtplib
from email.message import EmailMessage
from app.core.config import settings

def send_password_reset(email: str, reset_url: str) -> bool:
    if not settings.smtp_host or not settings.smtp_from:
        return False
    message = EmailMessage()
    message["Subject"] = "Reset your RCAA password"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(
        "We received a request to reset your RCAA password.\n\n"
        f"Reset your password using this one-time link:\n{reset_url}\n\n"
        f"The link expires in {settings.password_reset_expire_minutes} minutes. "
        "If you did not request this, you can ignore this email."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
    return True
