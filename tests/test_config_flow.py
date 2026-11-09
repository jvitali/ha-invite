"""Tests for the Invite config and options flows."""

from __future__ import annotations

import smtplib
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.invite.const import (
    CONF_BASE_URL,
    CONF_EXPIRY_HOURS,
    CONF_SMTP_ENCRYPTION,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_SENDER,
    CONF_SMTP_USERNAME,
    DOMAIN,
    ENCRYPTION_NONE,
)

SMTP_INPUT = {
    CONF_EXPIRY_HOURS: 24,
    CONF_SMTP_HOST: "smtp.example.com",
    CONF_SMTP_USERNAME: "me@example.com",
    CONF_SMTP_PASSWORD: "app-password",
    CONF_SMTP_SENDER: "me@example.com",
}


async def test_user_flow(hass: HomeAssistant) -> None:
    """The URL is validated and stored without a trailing slash."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BASE_URL: "ha.local"}
    )
    assert result["errors"] == {CONF_BASE_URL: "invalid_url"}

    with patch("custom_components.invite.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BASE_URL: "https://ha.example.com/"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_BASE_URL: "https://ha.example.com"}


async def test_options_smtp(hass: HomeAssistant, setup_invite) -> None:
    """SMTP settings are checked; an empty password keeps the stored one."""
    entry = setup_invite
    result = await hass.config_entries.options.async_init(entry.entry_id)
    smtp_input = {
        CONF_EXPIRY_HOURS: 24,
        CONF_SMTP_HOST: "smtp.example.com",
        CONF_SMTP_USERNAME: "me@example.com",
        CONF_SMTP_PASSWORD: "app-password",
        CONF_SMTP_SENDER: "me@example.com",
    }
    with patch(
        "custom_components.invite.config_flow.check_smtp",
        side_effect=smtplib.SMTPAuthenticationError(535, b"bad"),
    ):
        result = await hass.config_entries.options.async_configure(result["flow_id"], smtp_input)
    assert result["errors"] == {"base": "invalid_auth"}

    with patch("custom_components.invite.config_flow.check_smtp"):
        result = await hass.config_entries.options.async_configure(result["flow_id"], smtp_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_SMTP_PASSWORD] == "app-password"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch("custom_components.invite.config_flow.check_smtp"):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**smtp_input, CONF_SMTP_PASSWORD: ""}
        )
    await hass.async_block_till_done()
    assert entry.options[CONF_SMTP_PASSWORD] == "app-password"


@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        ({CONF_SMTP_SENDER: "not-an-email"}, {CONF_SMTP_SENDER: "invalid_sender"}),
        ({CONF_SMTP_ENCRYPTION: ENCRYPTION_NONE}, {CONF_SMTP_ENCRYPTION: "insecure_auth"}),
    ],
)
async def test_options_rejected_before_connecting(
    hass: HomeAssistant, setup_invite, changes: dict, errors: dict
) -> None:
    """A bad sender or plain-text authentication is refused without contacting the server."""
    result = await hass.config_entries.options.async_init(setup_invite.entry_id)
    with patch("custom_components.invite.config_flow.check_smtp") as check:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**SMTP_INPUT, **changes}
        )
    assert result["errors"] == errors
    check.assert_not_called()


async def test_options_cannot_connect(hass: HomeAssistant, setup_invite) -> None:
    """Connection problems are reported."""
    result = await hass.config_entries.options.async_init(setup_invite.entry_id)
    with patch("custom_components.invite.config_flow.check_smtp", side_effect=OSError):
        result = await hass.config_entries.options.async_configure(result["flow_id"], SMTP_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_sender_with_display_name(hass: HomeAssistant, setup_invite) -> None:
    """A sender like "Home <me@example.com>" is accepted."""
    result = await hass.config_entries.options.async_init(setup_invite.entry_id)
    with patch("custom_components.invite.config_flow.check_smtp"):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**SMTP_INPUT, CONF_SMTP_SENDER: "Home <me@example.com>"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
