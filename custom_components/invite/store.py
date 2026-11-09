"""Persistent storage for invitations.

Only a SHA-256 hash of each token is stored, so reading the storage file is not enough to
register. The link itself still exists wherever it was sent (email, the action response and
anything that keeps it, such as automation traces).
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

from .const import DOMAIN, INVITE_ID_BYTES, PRUNE_AFTER, TOKEN_BYTES

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
        if self.used_at:
            # Checked first: an account exists, whatever else happened to the invite.
            return STATUS_USED
        if self.revoked_at:
            return STATUS_REVOKED
        if (now or dt_util.utcnow()) >= dt_util.parse_datetime(self.expires_at):
            return STATUS_EXPIRED
        return STATUS_PENDING

    def finished_at(self) -> datetime:
        """Return when the invite stopped being usable (or will)."""
        return dt_util.parse_datetime(self.used_at or self.revoked_at or self.expires_at)

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
        """Load invitations from disk, dropping old finished ones."""
        data = await self._store.async_load() or {"invites": []}
        self.invites = {item["id"]: Invite(**item) for item in data["invites"]}
        if self._prune():
            await self._async_save()

    async def async_remove(self) -> None:
        """Delete all invitations, in memory and on disk."""
        self.invites = {}
        await self._store.async_remove()

    def _prune(self) -> bool:
        cutoff = dt_util.utcnow() - PRUNE_AFTER
        old = [
            invite_id
            for invite_id, invite in self.invites.items()
            if invite.status() != STATUS_PENDING and invite.finished_at() < cutoff
        ]
        for invite_id in old:
            del self.invites[invite_id]
        return bool(old)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"invites": [asdict(invite) for invite in self.invites.values()]}
        )

    def _new_id(self) -> str:
        while (invite_id := secrets.token_hex(INVITE_ID_BYTES)) in self.invites:
            pass
        return invite_id

    async def async_create(
        self, name: str, email: str | None, admin: bool, expires_in: timedelta
    ) -> tuple[Invite, str]:
        """Create an invite and return it with its (unhashed) token."""
        self._prune()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = dt_util.utcnow()
        invite = Invite(
            id=self._new_id(),
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
        try:
            await self._async_save()
        except Exception:
            # Keep memory consistent with disk: the caller removes the new account.
            invite.used_at = invite.user_id = None
            raise

    async def async_revoke(self, invite_id: str) -> Invite | None:
        """Revoke a pending invite. Return it, or None if it does not exist."""
        if (invite := self.invites.get(invite_id)) is None:
            return None
        if invite.status() == STATUS_PENDING:
            invite.revoked_at = dt_util.utcnow().isoformat()
            await self._async_save()
        return invite
