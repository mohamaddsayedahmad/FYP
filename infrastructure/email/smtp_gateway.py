"""
SMTP email gateway — concrete implementation of IEmailGateway.

Configuration is read from environment variables. The gateway is stateless;
each send() call opens and closes an SMTP connection. For high-volume sending,
a connection pool or async SMTP library (aiosmtplib) would be preferable.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional, Tuple

from core.interfaces import IEmailGateway


def _load_config() -> Optional[dict]:
    """
    Return SMTP config dict or None if required env vars are missing.

    Required: ATTENDANCE_SMTP_HOST, ATTENDANCE_SMTP_PORT,
              ATTENDANCE_SMTP_USER, ATTENDANCE_SMTP_PASS
    Optional: ATTENDANCE_EMAIL_FROM, ATTENDANCE_SMTP_USE_SSL
    """
    host = os.getenv("ATTENDANCE_SMTP_HOST", "").strip()
    port_raw = os.getenv("ATTENDANCE_SMTP_PORT", "").strip()
    user = os.getenv("ATTENDANCE_SMTP_USER", "").strip()
    password = os.getenv("ATTENDANCE_SMTP_PASS", "").strip()
    from_addr = os.getenv("ATTENDANCE_EMAIL_FROM", user).strip()

    if not all([host, port_raw, user, password]):
        return None

    try:
        port = int(port_raw)
    except ValueError:
        return None

    use_ssl = os.getenv("ATTENDANCE_SMTP_USE_SSL", "").lower() in ("1", "true", "yes")
    if port == 465:
        use_ssl = True

    return {"host": host, "port": port, "user": user, "pass": password,
            "from": from_addr, "use_ssl": use_ssl}


class SmtpEmailGateway(IEmailGateway):

    def __init__(self) -> None:
        self._config = _load_config()

    def is_configured(self) -> bool:
        return self._config is not None

    def send(self, to_email: str, subject: str, body: str) -> Tuple[bool, Optional[str]]:
        if not self._config:
            return False, "SMTP not configured (env vars missing)"

        msg = EmailMessage()
        msg["From"] = self._config["from"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        ctx = ssl.create_default_context()
        try:
            if self._config["use_ssl"]:
                with smtplib.SMTP_SSL(
                    self._config["host"], self._config["port"],
                    context=ctx, timeout=30
                ) as server:
                    server.login(self._config["user"], self._config["pass"])
                    server.send_message(msg)
            else:
                with smtplib.SMTP(
                    self._config["host"], self._config["port"], timeout=30
                ) as server:
                    server.ehlo()
                    server.starttls(context=ctx)
                    server.ehlo()
                    server.login(self._config["user"], self._config["pass"])
                    server.send_message(msg)
            return True, None
        except Exception as exc:
            return False, str(exc)
