"""Tests for the Invite integration."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.auth.providers import homeassistant as auth_ha
from homeassistant.components import persistent_notification
from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from custom_components.invite.const import (
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_SENDER,
    CONF_SMTP_USERNAME,
    DOMAIN,
    MAX_FAILED_ATTEMPTS,
)

from .conftest import BASE_URL


async def _create(hass: HomeAssistant, **data) -> dict:
    data.setdefault("name", "Ana")
    return await hass.services.async_call(
        DOMAIN, "create", data, blocking=True, return_response=True
    )


def _path(link: str) -> str:
    assert link.startswith(BASE_URL)
    return link.removeprefix(BASE_URL)


def _form(username="ana", password="secreto123", confirm=None) -> dict:
    return {
        "username": username,
        "password": password,
        "password_confirm": password if confirm is None else confirm,
    }


async def test_full_registration(hass: HomeAssistant, setup_invite, hass_client_no_auth) -> None:
    """A guest opens the link, registers once and the link stops working."""
    result = await _create(hass)
    assert result["emailed"] is False
    path = _path(result["link"])

    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert any(result["link"] in n["message"] for n in notifications.values())

    client = await hass_client_no_auth()
    resp = await client.get(path)
    assert resp.status == 200
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "Ana" in await resp.text()

    resp = await client.post(path, data=_form(username="  Ana "))
    assert resp.status == 200
    assert "ana" in await resp.text()

    provider = auth_ha.async_get_provider(hass)
    provider.data.validate_login("ana", "secreto123")
    users = [u for u in await hass.auth.async_get_users() if u.name == "Ana"]
    assert len(users) == 1
    user = users[0]
    assert [g.id for g in user.groups] == [GROUP_ID_USER]
    assert not user.is_admin
    persons = hass.data[PERSON_DOMAIN][1].async_items()
    assert any(p["user_id"] == user.id for p in persons)

    invite = setup_invite.runtime_data.store.invites[result["invite_id"]]
    assert invite.status() == "used"
    assert invite.user_id == user.id

    # Single use.
    assert (await client.get(path)).status == 404
    assert (await client.post(path, data=_form(username="otra"))).status == 404


async def test_admin_invite(hass: HomeAssistant, setup_invite, hass_client_no_auth) -> None:
    """Admin invites create admin users."""
    result = await _create(hass, admin=True)
    client = await hass_client_no_auth()
    assert (await client.post(_path(result["link"]), data=_form())).status == 200
    user = next(u for u in await hass.auth.async_get_users() if u.name == "Ana")
    assert [g.id for g in user.groups] == [GROUP_ID_ADMIN]


@pytest.mark.parametrize(
    ("form", "message"),
    [
        (_form(username="a"), "El usuario no es válido"),
        (_form(username="ana pérez"), "El usuario no es válido"),
        (_form(password="corta"), "al menos 8"),
        (_form(confirm="otracosa1"), "no coinciden"),
    ],
)
async def test_invalid_form(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, form: dict, message: str
) -> None:
    """Validation errors keep the invite usable."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    resp = await client.post(_path(result["link"]), data=form)
    assert resp.status == 200
    assert message in await resp.text()
    assert setup_invite.runtime_data.store.invites[result["invite_id"]].status() == "pending"


async def test_username_taken(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, local_auth
) -> None:
    """An existing username is rejected without consuming the invite."""
    await local_auth.async_add_auth("ana", "otraclave1")
    result = await _create(hass)
    client = await hass_client_no_auth()
    resp = await client.post(_path(result["link"]), data=_form())
    assert "ya existe" in await resp.text()
    assert setup_invite.runtime_data.store.invites[result["invite_id"]].status() == "pending"
    # The original password is untouched.
    local_auth.data.validate_login("ana", "otraclave1")


async def test_rollback_on_failure(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, local_auth
) -> None:
    """If creating the person fails, the user and the password are removed."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    with patch("custom_components.invite.users.async_create_person", side_effect=RuntimeError):
        resp = await client.post(_path(result["link"]), data=_form())
    assert "No se pudo crear" in await resp.text()
    assert not [u for u in await hass.auth.async_get_users() if u.name == "Ana"]
    assert all(u["username"] != "ana" for u in local_auth.data.users)
    # And the guest can retry.
    resp = await client.post(_path(result["link"]), data=_form())
    assert "lista" in await resp.text()


async def test_expired_and_revoked(
    hass: HomeAssistant,
    setup_invite,
    hass_client_no_auth,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Expired and revoked invites are rejected."""
    expired = await _create(hass, expires_hours=1)
    revoked = await _create(hass, name="Beto")
    await hass.services.async_call(
        DOMAIN, "revoke", {"invite_id": revoked["invite_id"]}, blocking=True
    )
    freezer.tick(timedelta(hours=2))
    client = await hass_client_no_auth()
    assert (await client.get(_path(expired["link"]))).status == 404
    assert (await client.get(_path(revoked["link"]))).status == 404

    listed = await hass.services.async_call(DOMAIN, "list", {}, blocking=True, return_response=True)
    statuses = {i["id"]: i["status"] for i in listed["other"]}
    assert statuses == {expired["invite_id"]: "expired", revoked["invite_id"]: "revoked"}
    assert all("token_hash" not in i for i in listed["other"])


async def test_revoke_unknown(hass: HomeAssistant, setup_invite) -> None:
    """Revoking an unknown invite raises a validation error."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "revoke", {"invite_id": "nope"}, blocking=True)


async def test_brute_force_blocked(hass: HomeAssistant, setup_invite, hass_client_no_auth) -> None:
    """Too many bad tokens block the client, even for a valid link."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    for i in range(MAX_FAILED_ATTEMPTS):
        assert (await client.get(f"/api/invite/register/bad{i}")).status == 404
    assert (await client.get(_path(result["link"]))).status == 429


async def test_non_admin_cannot_create(
    hass: HomeAssistant, setup_invite, hass_read_only_user
) -> None:
    """Only admins (or automations) can create invites."""
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "create",
            {"name": "Ana"},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_token_not_stored(hass: HomeAssistant, setup_invite, hass_storage) -> None:
    """The storage keeps only the token hash."""
    result = await _create(hass)
    token = result["link"].rsplit("/", 1)[1]
    await hass.async_block_till_done()
    stored = str(hass_storage[f"{DOMAIN}.invites"])
    assert token not in stored


@pytest.mark.parametrize(
    "entry_options",
    [
        {
            CONF_SMTP_HOST: "smtp.example.com",
            CONF_SMTP_USERNAME: "me@example.com",
            CONF_SMTP_PASSWORD: "app-password",
            CONF_SMTP_SENDER: "me@example.com",
        }
    ],
)
async def test_email_sent(hass: HomeAssistant, setup_invite) -> None:
    """With SMTP configured, the link is emailed and no notification is shown."""
    smtp = MagicMock()
    with patch("custom_components.invite.mailer.smtplib.SMTP", return_value=smtp):
        result = await _create(hass, email="ana@example.com")
    assert result["emailed"] is True
    server = smtp.__enter__.return_value
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("me@example.com", "app-password")
    message = server.send_message.call_args.args[0]
    assert message["To"] == "ana@example.com"
    assert result["link"] in message.get_content()
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert not any(result["link"] in n["message"] for n in notifications.values())


@pytest.mark.parametrize(
    "entry_options", [{CONF_SMTP_HOST: "smtp.example.com", CONF_SMTP_SENDER: "me@x.com"}]
)
async def test_email_failure_falls_back(hass: HomeAssistant, setup_invite) -> None:
    """If the email fails, the link is shown in a notification instead."""
    with patch("custom_components.invite.mailer.smtplib.SMTP", side_effect=OSError):
        result = await _create(hass, email="ana@example.com")
    assert result["emailed"] is False
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert any(result["link"] in n["message"] for n in notifications.values())


async def test_refused_without_owner(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, hass_owner_user
) -> None:
    """An invite never creates the first (owner) user."""
    hass_owner_user.is_owner = False
    result = await _create(hass)
    client = await hass_client_no_auth()
    resp = await client.post(_path(result["link"]), data=_form())
    assert "No se pudo crear" in await resp.text()
    assert not [u for u in await hass.auth.async_get_users() if u.name == "Ana"]
    assert setup_invite.runtime_data.store.invites[result["invite_id"]].status() == "pending"
