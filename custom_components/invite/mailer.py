"""Send invitation emails over SMTP."""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Any

from .const import (
    CONF_SMTP_ENCRYPTION,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_SENDER,
    CONF_SMTP_USERNAME,
    DEFAULT_SMTP_PORT,
    ENCRYPTION_STARTTLS,
    ENCRYPTION_TLS,
)

SMTP_TIMEOUT = 15


def smtp_configured(options: Mapping[str, Any]) -> bool:
    """Return True if enough SMTP settings are present to send mail."""
    return bool(options.get(CONF_SMTP_HOST) and options.get(CONF_SMTP_SENDER))


def _connect(options: Mapping[str, Any]) -> smtplib.SMTP:
    """Open an authenticated connection. Closes it again if any step fails."""
    host = options[CONF_SMTP_HOST]
    port = int(options.get(CONF_SMTP_PORT) or DEFAULT_SMTP_PORT)
    encryption = options.get(CONF_SMTP_ENCRYPTION, ENCRYPTION_STARTTLS)
    context = ssl.create_default_context()
    server: smtplib.SMTP
    if encryption == ENCRYPTION_TLS:
        server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
    try:
        if encryption == ENCRYPTION_STARTTLS:
            server.starttls(context=context)
        if options.get(CONF_SMTP_USERNAME):
            server.login(options[CONF_SMTP_USERNAME], options.get(CONF_SMTP_PASSWORD, ""))
    except BaseException:
        server.close()
        raise
    return server


def check_smtp(options: Mapping[str, Any]) -> None:
    """Connect and authenticate, raising on failure. Runs in the executor."""
    with _connect(options):
        pass


def send_email(options: Mapping[str, Any], to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Runs in the executor."""
    message = EmailMessage()
    message["From"] = options[CONF_SMTP_SENDER]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with _connect(options) as server:
        server.send_message(message)
