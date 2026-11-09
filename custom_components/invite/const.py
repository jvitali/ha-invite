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

# Links can end up in reverse-proxy access logs and automation traces, so keep them short-lived.
DEFAULT_EXPIRY_HOURS: Final = 48
MAX_EXPIRY_HOURS: Final = 168
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
INVITE_ID_BYTES: Final = 8
MIN_PASSWORD_LENGTH: Final = 8
# Home Assistant hashes passwords with bcrypt, which only uses the first 72 bytes.
MAX_PASSWORD_BYTES: Final = 72
USERNAME_PATTERN: Final = r"^[a-z0-9][a-z0-9._-]{2,31}$"

# Used, expired and revoked invites are kept this long for `invite.list`, then dropped.
PRUNE_AFTER: Final = timedelta(days=30)

# Failed lookups (unknown, expired or used tokens) per client. Past the limit the client gets
# a 429 for unknown tokens until the window passes; a valid token is always accepted.
MAX_FAILED_ATTEMPTS: Final = 10
FAILED_ATTEMPT_WINDOW: Final = timedelta(minutes=10)
MAX_TRACKED_CLIENTS: Final = 10_000
