"""Shared runtime data."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .store import InviteStore


@dataclass
class InviteData:
    """Domain-level data, created once in async_setup.

    It lives outside the config entry on purpose: reloading the entry (for example after
    saving the options) must not create a second store or lock while a registration that
    holds the old ones is still running.
    """

    store: InviteStore
    # Serializes everything that reads or changes the status of an invite: registration,
    # creation and revocation.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


DATA_INVITE: HassKey[InviteData] = HassKey(DOMAIN)
