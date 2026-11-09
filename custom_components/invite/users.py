"""Create Home Assistant users the same way the UI does (user + credentials + person)."""

from __future__ import annotations

import contextlib
import logging

from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.auth.models import User
from homeassistant.auth.providers import homeassistant as auth_ha
from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.components.person import async_create_person
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class UsernameTakenError(Exception):
    """The username already exists."""


class NoOwnerError(Exception):
    """Home Assistant has no owner yet; the new user would become the owner."""


async def async_create_user(
    hass: HomeAssistant, name: str, username: str, password: str, admin: bool
) -> User:
    """Create a user with local credentials and a linked person.

    The caller serializes calls. If any step fails, the steps already done are undone so a
    retry starts clean.
    """
    # Home Assistant makes the first user the owner. Never let an invite do that.
    if not any(u.is_owner for u in await hass.auth.async_get_users()):
        raise NoOwnerError

    provider = auth_ha.async_get_provider(hass)
    try:
        await provider.async_add_auth(username, password)
    except auth_ha.InvalidUsername as err:
        if err.translation_key == "username_already_exists":
            raise UsernameTakenError from err
        raise

    user: User | None = None
    try:
        credentials = await provider.async_get_or_create_credentials({"username": username})
        user = await hass.auth.async_create_user(
            name, group_ids=[GROUP_ID_ADMIN if admin else GROUP_ID_USER]
        )
        await hass.auth.async_link_user(user, credentials)
        await async_create_person(hass, name, user_id=user.id)
    except Exception:
        _LOGGER.exception("Could not create user %s; rolling back", username)
        await async_remove_user(hass, user, username)
        raise
    return user


async def async_remove_user(hass: HomeAssistant, user: User | None, username: str) -> None:
    """Remove a user created by an invite, its person and its password. Best effort."""
    provider = auth_ha.async_get_provider(hass)
    try:
        if user is not None:
            persons = hass.data[PERSON_DOMAIN][1]
            for person in persons.async_items():
                if person.get("user_id") == user.id:
                    await persons.async_delete_item(person["id"])
            # Also removes the linked credentials and, through the provider, the password.
            await hass.auth.async_remove_user(user)
    except Exception:
        _LOGGER.exception("Could not remove user %s during rollback", username)
    finally:
        with contextlib.suppress(auth_ha.InvalidUser):
            await provider.async_remove_auth(username)
