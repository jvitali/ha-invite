"""Constants for the Invite integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "invite"

CONF_BASE_URL: Final = "base_url"
CONF_EXPIRY_HOURS: Final = "expiry_hours"
CONF_SMTP_HOST: Final = "smtp_host"
CONF_SMTP_PORT: Final = "smtp_port"
CONF_SMTP_ENCRYPTION: Final = "smtp_encryption"
CONF_SMTP_USERNAME: Final = "smtp_username"
CONF_SMTP_PASSWORD: Final = "smtp_password"
CONF_SMTP_SENDER: Final = "smtp_sender"

ENCRYPTION_STARTTLS: Final = "starttls"
ENCRYPTION_TLS: Final = "tls"
ENCRYPTION_NONE: Final = "none"

DEFAULT_EXPIRY_HOURS: Final = 48
MAX_EXPIRY_HOURS: Final = 720
DEFAULT_SMTP_PORT: Final = 587

ATTR_NAME: Final = "name"
ATTR_EMAIL: Final = "email"
ATTR_ADMIN: Final = "admin"
ATTR_EXPIRES_HOURS: Final = "expires_hours"
ATTR_INVITE_ID: Final = "invite_id"

SERVICE_CREATE: Final = "create"
SERVICE_REVOKE: Final = "revoke"
SERVICE_LIST: Final = "list"

REGISTER_URL: Final = "/api/invite/register/{token}"

TOKEN_BYTES: Final = 32
MIN_PASSWORD_LENGTH: Final = 8
USERNAME_PATTERN: Final = r"^[a-z0-9][a-z0-9._-]{2,31}$"

# Requests with an unknown, expired or used token count as failures. Past the limit the
# client gets a 429 until the window passes, so tokens cannot be guessed by brute force.
MAX_FAILED_ATTEMPTS: Final = 10
FAILED_ATTEMPT_WINDOW: Final = timedelta(minutes=10)
