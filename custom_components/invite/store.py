"""Persistent storage for invitations.

Only a SHA-256 hash of each token is stored: the token itself exists only in the link
sent to the guest, so reading the storage file is not enough to register.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TOKEN_BYTES

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.invites"

STATUS_PENDING = "pending"
STATUS_USED = "used"
STATUS_EXPIRED = "expired"
STATUS_REVOKED = "revoked"


def hash_token(token: str) -> str:
    """Return the storage hash of a token."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Invite:
    """An invitation to create a Home Assistant user."""

    id: str
    token_hash: str
    name: str
    email: str | None
    admin: bool
    created_at: str
    expires_at: str
    used_at: str | None = None
    revoked_at: str | None = None
    user_id: str | None = None

    def status(self, now: datetime | None = None) -> str:
        """Return the current status of the invite."""
        if self.revoked_at:
            return STATUS_REVOKED
        if self.used_at:
            return STATUS_USED
        if (now or dt_util.utcnow()) >= dt_util.parse_datetime(self.expires_at):
            return STATUS_EXPIRED
        return STATUS_PENDING

    def as_public_dict(self) -> dict[str, Any]:
        """Return the invite without its token hash."""
        data = asdict(self)
        data.pop("token_hash")
        data["status"] = self.status()
        return data


class InviteStore:
    """Keep invitations in .storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, list[dict[str, Any]]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY, private=True, atomic_writes=True
        )
        self.invites: dict[str, Invite] = {}

    async def async_load(self) -> None:
        """Load invitations from disk."""
        data = await self._store.async_load() or {"invites": []}
        self.invites = {item["id"]: Invite(**item) for item in data["invites"]}

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"invites": [asdict(invite) for invite in self.invites.values()]}
        )

    async def async_create(
        self, name: str, email: str | None, admin: bool, expires_in: timedelta
    ) -> tuple[Invite, str]:
        """Create an invite and return it with its (unhashed) token."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = dt_util.utcnow()
        invite = Invite(
            id=secrets.token_hex(4),
            token_hash=hash_token(token),
            name=name,
            email=email,
            admin=admin,
            created_at=now.isoformat(),
            expires_at=(now + expires_in).isoformat(),
        )
        self.invites[invite.id] = invite
        await self._async_save()
        return invite, token

    def get_pending_by_token(self, token: str) -> Invite | None:
        """Return the invite for a token if it can still be used."""
        token_hash = hash_token(token)
        for invite in self.invites.values():
            if secrets.compare_digest(invite.token_hash, token_hash):
                return invite if invite.status() == STATUS_PENDING else None
        return None

    async def async_mark_used(self, invite: Invite, user_id: str) -> None:
        """Mark an invite as used by the given user."""
        invite.used_at = dt_util.utcnow().isoformat()
        invite.user_id = user_id
        await self._async_save()

    async def async_revoke(self, invite_id: str) -> Invite | None:
        """Revoke an invite. Return it, or None if it does not exist."""
        if (invite := self.invites.get(invite_id)) is None:
            return None
        if invite.status() == STATUS_PENDING:
            invite.revoked_at = dt_util.utcnow().isoformat()
            await self._async_save()
        return invite
