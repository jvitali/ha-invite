"""Invite people to Home Assistant with a single-use registration link."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ADMIN,
    ATTR_EMAIL,
    ATTR_EXPIRES_HOURS,
    ATTR_INVITE_ID,
    ATTR_NAME,
    CONF_BASE_URL,
    CONF_EXPIRY_HOURS,
    DEFAULT_EXPIRY_HOURS,
    DOMAIN,
    MAX_EXPIRY_HOURS,
    REGISTER_URL,
    SERVICE_CREATE,
    SERVICE_LIST,
    SERVICE_REVOKE,
)
from .mailer import send_email, smtp_configured
from .store import STATUS_PENDING, InviteStore
from .texts import get_texts
from .views import InviteRegisterView

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): vol.All(cv.string, vol.Length(min=1, max=64)),
        vol.Optional(ATTR_EMAIL): vol.Email(),  # pylint: disable=no-value-for-parameter
        vol.Optional(ATTR_ADMIN, default=False): cv.boolean,
        vol.Optional(ATTR_EXPIRES_HOURS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_EXPIRY_HOURS)
        ),
    }
)
REVOKE_SCHEMA = vol.Schema({vol.Required(ATTR_INVITE_ID): cv.string})


@dataclass
class InviteRuntimeData:
    """Runtime data of the config entry."""

    store: InviteStore
    register_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


type InviteConfigEntry = ConfigEntry[InviteRuntimeData]


def _loaded_entry(hass: HomeAssistant) -> InviteConfigEntry:
    if not (entries := hass.config_entries.async_loaded_entries(DOMAIN)):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0]


async def _async_require_admin(hass: HomeAssistant, call: ServiceCall) -> None:
    """Allow admins and automations (no user); reject other users."""
    if call.context.user_id is None:
        return
    user = await hass.auth.async_get_user(call.context.user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=call.context)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the registration page and the actions."""
    hass.http.register_view(InviteRegisterView())

    async def create(call: ServiceCall) -> ServiceResponse:
        await _async_require_admin(hass, call)
        entry = _loaded_entry(hass)
        hours = call.data.get(
            ATTR_EXPIRES_HOURS,
            entry.options.get(CONF_EXPIRY_HOURS, DEFAULT_EXPIRY_HOURS),
        )
        name: str = call.data[ATTR_NAME]
        email: str | None = call.data.get(ATTR_EMAIL)
        invite, token = await entry.runtime_data.store.async_create(
            name, email, call.data[ATTR_ADMIN], timedelta(hours=hours)
        )
        base_url = entry.data[CONF_BASE_URL].rstrip("/")
        link = base_url + REGISTER_URL.format(token=token)
        expires_local = dt_util.as_local(dt_util.parse_datetime(invite.expires_at))
        expires_text = expires_local.strftime("%d/%m/%Y %H:%M")

        emailed = False
        if email and smtp_configured(entry.options):
            texts = get_texts(hass.config.language)
            body = texts["email_body"].format(
                name=name, link=link, expires=expires_text, base_url=base_url
            )
            try:
                await hass.async_add_executor_job(
                    send_email, entry.options, email, texts["email_subject"], body
                )
                emailed = True
            except Exception as err:  # noqa: BLE001 - fall back to sharing the link
                _LOGGER.warning("Could not email invite %s to %s: %s", invite.id, email, err)

        if not emailed:
            # Persistent notifications are visible to every user: revoke the invite if
            # someone else could have used it.
            texts = get_texts(hass.config.language)
            persistent_notification.async_create(
                hass,
                texts["notif_created"].format(name=name, expires=expires_text, link=link),
                title=texts["notif_created_title"],
                notification_id=f"{DOMAIN}_created_{invite.id}",
            )
        return {
            "invite_id": invite.id,
            "link": link,
            "expires_at": invite.expires_at,
            "emailed": emailed,
        }

    async def revoke(call: ServiceCall) -> None:
        await _async_require_admin(hass, call)
        entry = _loaded_entry(hass)
        invite_id = call.data[ATTR_INVITE_ID]
        if await entry.runtime_data.store.async_revoke(invite_id) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invite_not_found",
                translation_placeholders={"invite_id": invite_id},
            )
        persistent_notification.async_dismiss(hass, f"{DOMAIN}_created_{invite_id}")

    async def list_invites(call: ServiceCall) -> ServiceResponse:
        await _async_require_admin(hass, call)
        entry = _loaded_entry(hass)
        invites = [i.as_public_dict() for i in entry.runtime_data.store.invites.values()]
        return {
            "pending": [i for i in invites if i["status"] == STATUS_PENDING],
            "other": [i for i in invites if i["status"] != STATUS_PENDING],
        }

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE, create, CREATE_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, SERVICE_REVOKE, revoke, REVOKE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_LIST, list_invites, vol.Schema({}), SupportsResponse.ONLY
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: InviteConfigEntry) -> bool:
    """Load the invitations."""
    store = InviteStore(hass)
    await store.async_load()
    entry.runtime_data = InviteRuntimeData(store=store)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InviteConfigEntry) -> bool:
    """Unload the entry. The view stays registered but answers 'invalid' meanwhile."""
    return True
