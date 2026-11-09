"""Invite people to Home Assistant with a single-use registration link."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
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
from .models import DATA_INVITE, InviteData
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


def _loaded_entry(hass: HomeAssistant) -> ConfigEntry:
    if not (entries := hass.config_entries.async_loaded_entries(DOMAIN)):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0]


async def _async_require_admin(hass: HomeAssistant, call: ServiceCall) -> None:
    """Allow admins and automations or scripts (no user); reject other users."""
    if call.context.user_id is None:
        return
    user = await hass.auth.async_get_user(call.context.user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=call.context)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Load the invitations and register the registration page and the actions."""
    store = InviteStore(hass)
    await store.async_load()
    data = hass.data[DATA_INVITE] = InviteData(store=store)
    hass.http.register_view(InviteRegisterView())

    async def create(call: ServiceCall) -> ServiceResponse:
        await _async_require_admin(hass, call)
        entry = _loaded_entry(hass)
        name: str = call.data[ATTR_NAME]
        email: str | None = call.data.get(ATTR_EMAIL)
        if email and not smtp_configured(entry.options):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="smtp_not_configured"
            )
        if not email and not call.return_response:
            # Without email the response is the only place the link is given: it is never
            # put in a notification, because every user can read those.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="response_required"
            )
        hours = call.data.get(
            ATTR_EXPIRES_HOURS, entry.options.get(CONF_EXPIRY_HOURS, DEFAULT_EXPIRY_HOURS)
        )
        async with data.lock:
            invite, token = await data.store.async_create(
                name, email, call.data[ATTR_ADMIN], timedelta(hours=hours)
            )
        base_url = entry.data[CONF_BASE_URL].rstrip("/")
        link = base_url + REGISTER_URL.format(token=token)

        if email:
            texts = get_texts(hass.config.language)
            expires = dt_util.as_local(dt_util.parse_datetime(invite.expires_at))
            body = texts["email_body"].format(
                name=name,
                link=link,
                expires=expires.strftime("%Y-%m-%d %H:%M %Z"),
                base_url=base_url,
            )
            try:
                await hass.async_add_executor_job(
                    send_email, entry.options, email, texts["email_subject"], body
                )
            except Exception as err:
                _LOGGER.warning("Could not email invite %s: %s", invite.id, err)
                async with data.lock:
                    await data.store.async_revoke(invite.id)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="email_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            return {"invite_id": invite.id, "expires_at": invite.expires_at, "emailed": True}

        return {
            "invite_id": invite.id,
            "expires_at": invite.expires_at,
            "emailed": False,
            "link": link,
        }

    async def revoke(call: ServiceCall) -> None:
        await _async_require_admin(hass, call)
        invite_id = call.data[ATTR_INVITE_ID]
        # Under the lock: a registration in progress either finishes first (the invite is then
        # "used") or sees the invite revoked.
        async with data.lock:
            invite = await data.store.async_revoke(invite_id)
        if invite is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invite_not_found",
                translation_placeholders={"invite_id": invite_id},
            )

    async def list_invites(call: ServiceCall) -> ServiceResponse:
        await _async_require_admin(hass, call)
        invites = [i.as_public_dict() for i in data.store.invites.values()]
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to set up per entry: it only holds the URL and options."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry. The page stays registered but answers 'invalid' meanwhile."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete every invitation when the integration is removed."""
    data = hass.data.get(DATA_INVITE)
    if data is None:
        store = InviteStore(hass)
        await store.async_remove()
        return
    async with data.lock:
        await data.store.async_remove()
