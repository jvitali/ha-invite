"""Tests for the Invite integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.auth.providers import homeassistant as auth_ha
from homeassistant.components import persistent_notification
from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.setup import async_setup_component

from custom_components.invite import users as users_module
from custom_components.invite.const import (
    CONF_SMTP_ENCRYPTION,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_SENDER,
    CONF_SMTP_USERNAME,
    DOMAIN,
    ENCRYPTION_TLS,
    MAX_FAILED_ATTEMPTS,
    MAX_TRACKED_CLIENTS,
    PRUNE_AFTER,
)
from custom_components.invite.models import DATA_INVITE
from custom_components.invite.views import FailedAttempts, client_key

from .conftest import BASE_URL

SMTP_OPTIONS = {
    CONF_SMTP_HOST: "smtp.example.com",
    CONF_SMTP_USERNAME: "me@example.com",
    CONF_SMTP_PASSWORD: "app-password",
    CONF_SMTP_SENDER: "me@example.com",
}


async def _create(hass: HomeAssistant, context: Context | None = None, **data) -> dict:
    data.setdefault("name", "Ana")
    return await hass.services.async_call(
        DOMAIN, "create", data, blocking=True, return_response=True, context=context
    )


def _store(hass: HomeAssistant):
    return hass.data[DATA_INVITE].store


def _path(link: str) -> str:
    assert link.startswith(BASE_URL)
    return link.removeprefix(BASE_URL)


def _form(username="ana", password="secreto123", confirm=None) -> dict:
    return {
        "username": username,
        "password": password,
        "password_confirm": password if confirm is None else confirm,
    }


def _notifications_text(hass: HomeAssistant) -> str:
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    return " ".join(n["message"] for n in notifications.values())


async def _users_named(hass: HomeAssistant, name: str) -> list:
    return [u for u in await hass.auth.async_get_users() if u.name == name]


async def test_full_registration(hass: HomeAssistant, setup_invite, hass_client_no_auth) -> None:
    """A guest opens the link, registers once and the link stops working."""
    result = await _create(hass)
    assert result["emailed"] is False
    path = _path(result["link"])

    client = await hass_client_no_auth()
    resp = await client.get(path)
    assert resp.status == 200
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert "Ana" in await resp.text()

    resp = await client.post(path, data=_form(username="  Ana "))
    assert resp.status == 200
    assert "ana" in await resp.text()

    auth_ha.async_get_provider(hass).data.validate_login("ana", "secreto123")
    (user,) = await _users_named(hass, "Ana")
    assert [g.id for g in user.groups] == [GROUP_ID_USER]
    assert not user.is_admin
    persons = hass.data[PERSON_DOMAIN][1].async_items()
    assert any(p["user_id"] == user.id for p in persons)

    invite = _store(hass).invites[result["invite_id"]]
    assert invite.status() == "used"
    assert invite.user_id == user.id
    assert "ana" in _notifications_text(hass)

    # Single use.
    assert (await client.get(path)).status == 404
    assert (await client.post(path, data=_form(username="otra"))).status == 404


async def test_link_never_in_notifications(
    hass: HomeAssistant,
    setup_invite,
    hass_read_only_user,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    """Finding 1: other users must not be able to read the link (admin invite escalation)."""
    assert await async_setup_component(hass, "persistent_notification", {})
    result = await _create(hass, admin=True)
    token = result["link"].rsplit("/", 1)[1]
    assert token not in _notifications_text(hass)

    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "persistent_notification/get"})
    msg = await client.receive_json()
    assert msg["success"]
    assert token not in str(msg["result"])


async def test_create_without_response_or_email_refused(hass: HomeAssistant, setup_invite) -> None:
    """Without email the response is the only channel, so it must be requested."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "create", {"name": "Ana"}, blocking=True)
    assert not _store(hass).invites


async def test_email_without_smtp_refused(hass: HomeAssistant, setup_invite) -> None:
    """Asking for an email without SMTP is an error, not a silent change of channel."""
    with pytest.raises(ServiceValidationError):
        await _create(hass, email="ana@example.com")
    assert not _store(hass).invites


async def test_admin_invite(hass: HomeAssistant, setup_invite, hass_client_no_auth) -> None:
    """Admin invites create admin users."""
    result = await _create(hass, admin=True)
    client = await hass_client_no_auth()
    assert (await client.post(_path(result["link"]), data=_form())).status == 200
    (user,) = await _users_named(hass, "Ana")
    assert [g.id for g in user.groups] == [GROUP_ID_ADMIN]


async def test_name_is_escaped(hass: HomeAssistant, setup_invite, hass_client_no_auth) -> None:
    """Names are HTML-escaped in the page."""
    result = await _create(hass, name="<script>x</script>")
    client = await hass_client_no_auth()
    text = await (await client.get(_path(result["link"]))).text()
    assert "<script>x" not in text
    assert "&lt;script&gt;" in text


@pytest.mark.parametrize(
    ("form", "message"),
    [
        (_form(username="a"), "El usuario no es válido"),
        (_form(username="ana pérez"), "El usuario no es válido"),
        (_form(username="İsa"), "El usuario no es válido"),
        (_form(password="corta"), "al menos 8"),
        (_form(password="ñ" * 40), "demasiado larga"),
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
    assert _store(hass).invites[result["invite_id"]].status() == "pending"


async def test_uppercase_ascii_username(
    hass: HomeAssistant, setup_invite, hass_client_no_auth
) -> None:
    """Usernames are casefolded like Home Assistant does."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    await client.post(_path(result["link"]), data=_form(username="ANA.P"))
    auth_ha.async_get_provider(hass).data.validate_login("ana.p", "secreto123")


async def test_username_taken(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, local_auth
) -> None:
    """An existing username is rejected without consuming the invite."""
    await local_auth.async_add_auth("ana", "otraclave1")
    result = await _create(hass)
    client = await hass_client_no_auth()
    resp = await client.post(_path(result["link"]), data=_form())
    assert "ya existe" in await resp.text()
    assert _store(hass).invites[result["invite_id"]].status() == "pending"
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
    assert not await _users_named(hass, "Ana")
    assert all(u["username"] != "ana" for u in local_auth.data.users)
    resp = await client.post(_path(result["link"]), data=_form())
    assert "lista" in await resp.text()


async def test_rollback_continues_if_user_removal_fails(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, local_auth
) -> None:
    """The password is removed even if removing the user raises."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    with (
        patch("custom_components.invite.users.async_create_person", side_effect=RuntimeError),
        patch.object(hass.auth, "async_remove_user", side_effect=RuntimeError),
    ):
        await client.post(_path(result["link"]), data=_form())
    assert all(u["username"] != "ana" for u in local_auth.data.users)


async def test_mark_used_failure_removes_user(
    hass: HomeAssistant, setup_invite, hass_client_no_auth
) -> None:
    """If the invite cannot be marked used, the new account is removed with its person."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    with patch.object(_store(hass), "async_mark_used", side_effect=OSError):
        resp = await client.post(_path(result["link"]), data=_form())
    assert "No se pudo crear" in await resp.text()
    assert not await _users_named(hass, "Ana")
    assert all(p["name"] != "Ana" for p in hass.data[PERSON_DOMAIN][1].async_items())


async def test_refused_without_owner(
    hass: HomeAssistant, setup_invite, hass_client_no_auth, hass_owner_user
) -> None:
    """An invite never creates the first (owner) user."""
    hass_owner_user.is_owner = False
    result = await _create(hass)
    client = await hass_client_no_auth()
    resp = await client.post(_path(result["link"]), data=_form())
    assert "No se pudo crear" in await resp.text()
    assert not await _users_named(hass, "Ana")
    assert _store(hass).invites[result["invite_id"]].status() == "pending"


async def _hold_first_registration(hass: HomeAssistant):
    """Patch user creation so the first call waits until released."""
    started, release = asyncio.Event(), asyncio.Event()
    original = users_module.async_create_user

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    return started, release, slow


async def test_reload_during_registration(
    hass: HomeAssistant, setup_invite, hass_client_no_auth
) -> None:
    """Finding 2: reloading the entry mid-registration must not allow a second use."""
    result = await _create(hass)
    path = _path(result["link"])
    client = await hass_client_no_auth()
    started, release, slow = await _hold_first_registration(hass)
    with patch("custom_components.invite.views.async_create_user", side_effect=slow):
        first = asyncio.create_task(client.post(path, data=_form(username="ana")))
        await started.wait()
        assert await hass.config_entries.async_reload(setup_invite.entry_id)
        second = asyncio.create_task(client.post(path, data=_form(username="ana2")))
        await asyncio.sleep(0.05)
        release.set()
        responses = [await first, await second]
    assert sorted(r.status for r in responses) == [200, 404]
    assert len(await _users_named(hass, "Ana")) == 1


async def test_revoke_during_registration(
    hass: HomeAssistant, setup_invite, hass_client_no_auth
) -> None:
    """Finding 4: a revoke waits for an in-flight registration and reports it as used."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    started, release, slow = await _hold_first_registration(hass)
    with patch("custom_components.invite.views.async_create_user", side_effect=slow):
        post = asyncio.create_task(client.post(_path(result["link"]), data=_form()))
        await started.wait()
        revoke = asyncio.create_task(
            hass.services.async_call(
                DOMAIN, "revoke", {"invite_id": result["invite_id"]}, blocking=True
            )
        )
        await asyncio.sleep(0.05)
        assert not revoke.done()
        release.set()
        assert (await post).status == 200
        await revoke
    invite = _store(hass).invites[result["invite_id"]]
    assert invite.status() == "used"
    assert invite.revoked_at is None


async def test_expired_and_revoked(
    hass: HomeAssistant,
    setup_invite,
    hass_client_no_auth,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Expired and revoked invites are rejected; expiry is exact."""
    expired = await _create(hass, expires_hours=1)
    revoked = await _create(hass, name="Beto")
    await hass.services.async_call(
        DOMAIN, "revoke", {"invite_id": revoked["invite_id"]}, blocking=True
    )
    client = await hass_client_no_auth()
    freezer.tick(timedelta(minutes=59, seconds=59))
    assert (await client.get(_path(expired["link"]))).status == 200
    freezer.tick(timedelta(seconds=1))
    assert (await client.get(_path(expired["link"]))).status == 404
    assert (await client.get(_path(revoked["link"]))).status == 404

    listed = await hass.services.async_call(DOMAIN, "list", {}, blocking=True, return_response=True)
    statuses = {i["id"]: i["status"] for i in listed["other"]}
    assert statuses == {expired["invite_id"]: "expired", revoked["invite_id"]: "revoked"}
    assert all("token_hash" not in i for i in listed["other"])


async def test_old_invites_pruned(
    hass: HomeAssistant, setup_invite, freezer: FrozenDateTimeFactory
) -> None:
    """Finished invites are dropped after PRUNE_AFTER; pending ones are kept."""
    old = await _create(hass, expires_hours=1)
    freezer.tick(PRUNE_AFTER + timedelta(hours=2))
    new = await _create(hass, name="Beto")
    assert old["invite_id"] not in _store(hass).invites
    assert new["invite_id"] in _store(hass).invites


async def test_revoke_unknown(hass: HomeAssistant, setup_invite) -> None:
    """Revoking an unknown invite raises a validation error."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "revoke", {"invite_id": "nope"}, blocking=True)


async def test_unknown_tokens_throttled_but_valid_link_works(
    hass: HomeAssistant, setup_invite, hass_client_no_auth
) -> None:
    """Finding 3: bad tokens get 429 after the limit, but a valid link always works."""
    result = await _create(hass)
    client = await hass_client_no_auth()
    for i in range(MAX_FAILED_ATTEMPTS):
        assert (await client.get(f"/api/invite/register/bad{i}")).status == 404
    assert (await client.get("/api/invite/register/bad-more")).status == 429
    assert (await client.get(_path(result["link"]))).status == 200
    assert (await client.post(_path(result["link"]), data=_form())).status == 200


def test_failed_attempts_bounded(freezer: FrozenDateTimeFactory) -> None:
    """Finding 3: the limiter forgets old clients and caps its size."""
    failed = FailedAttempts()
    failed.add("a")
    freezer.tick(timedelta(minutes=11))
    assert not failed.blocked("a")
    assert len(failed) == 0
    for i in range(MAX_TRACKED_CLIENTS + 5):
        failed.add(f"c{i}")
    assert len(failed) == MAX_TRACKED_CLIENTS


def test_client_key_groups_ipv6() -> None:
    """IPv6 clients are grouped by /64 so rotating addresses does not bypass the limit."""
    assert client_key("2001:db8:1:2::1") == client_key("2001:db8:1:2:ffff::9")
    assert client_key("2001:db8:1:2::1") != client_key("2001:db8:1:3::1")
    assert client_key("192.0.2.1") == "192.0.2.1"
    assert client_key(None) == "unknown"


async def test_page_invalid_while_unloaded(
    hass: HomeAssistant, setup_invite, hass_client_no_auth
) -> None:
    """With the entry unloaded, links answer 'invalid'."""
    result = await _create(hass)
    assert await hass.config_entries.async_unload(setup_invite.entry_id)
    client = await hass_client_no_auth()
    assert (await client.get(_path(result["link"]))).status == 404


async def test_remove_entry_deletes_invites(
    hass: HomeAssistant, setup_invite, hass_storage
) -> None:
    """Finding 5: removing the integration deletes stored invites."""
    await _create(hass)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.invites" in hass_storage
    assert await hass.config_entries.async_remove(setup_invite.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.invites" not in hass_storage
    assert not _store(hass).invites


async def test_non_admin_cannot_create(
    hass: HomeAssistant, setup_invite, hass_read_only_user
) -> None:
    """Only admins (or automations) can create invites."""
    with pytest.raises(Unauthorized):
        await _create(hass, context=Context(user_id=hass_read_only_user.id))


async def test_token_not_stored(hass: HomeAssistant, setup_invite, hass_storage) -> None:
    """The storage keeps only the token hash."""
    result = await _create(hass)
    token = result["link"].rsplit("/", 1)[1]
    await hass.async_block_till_done()
    assert token not in str(hass_storage[f"{DOMAIN}.invites"])


async def test_invite_id_collision(hass: HomeAssistant, setup_invite) -> None:
    """A colliding ID is regenerated instead of overwriting another invite."""
    with patch(
        "custom_components.invite.store.secrets.token_hex", side_effect=["aaaa", "aaaa", "bbbb"]
    ):
        first = await _create(hass)
        second = await _create(hass, name="Beto")
    assert (first["invite_id"], second["invite_id"]) == ("aaaa", "bbbb")
    assert len(_store(hass).invites) == 2


@pytest.mark.parametrize("entry_options", [SMTP_OPTIONS])
async def test_email_sent(hass: HomeAssistant, setup_invite) -> None:
    """With SMTP configured, the link is emailed and not returned or shown anywhere."""
    smtp = MagicMock()
    with patch("custom_components.invite.mailer.smtplib.SMTP", return_value=smtp):
        result = await _create(hass, email="ana@example.com")
    assert result["emailed"] is True
    assert "link" not in result
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("me@example.com", "app-password")
    message = smtp.__enter__.return_value.send_message.call_args.args[0]
    assert message["To"] == "ana@example.com"
    assert "/api/invite/register/" in message.get_content()
    assert "/api/invite/register/" not in _notifications_text(hass)


@pytest.mark.parametrize("entry_options", [{**SMTP_OPTIONS, CONF_SMTP_ENCRYPTION: ENCRYPTION_TLS}])
async def test_email_sent_tls(hass: HomeAssistant, setup_invite) -> None:
    """TLS/SSL mode uses SMTP_SSL and no STARTTLS."""
    smtp = MagicMock()
    with patch("custom_components.invite.mailer.smtplib.SMTP_SSL", return_value=smtp) as ssl:
        result = await _create(hass, email="ana@example.com")
    assert result["emailed"] is True
    ssl.assert_called_once()
    smtp.starttls.assert_not_called()


@pytest.mark.parametrize("entry_options", [SMTP_OPTIONS])
async def test_email_failure_revokes(hass: HomeAssistant, setup_invite) -> None:
    """If the email fails, the action fails, the invite is revoked and the link is not shown."""
    smtp = MagicMock()
    smtp.login.side_effect = OSError("boom")
    with (
        patch("custom_components.invite.mailer.smtplib.SMTP", return_value=smtp),
        pytest.raises(HomeAssistantError),
    ):
        await _create(hass, email="ana@example.com")
    smtp.close.assert_called_once()  # connection closed on failure
    (invite,) = _store(hass).invites.values()
    assert invite.status() == "revoked"
    assert "/api/invite/register/" not in _notifications_text(hass)
