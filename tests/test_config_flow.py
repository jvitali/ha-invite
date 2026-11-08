"""Tests for the Invite config and options flows."""

from __future__ import annotations

import smtplib
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.invite.const import (
    CONF_BASE_URL,
    CONF_EXPIRY_HOURS,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_SENDER,
    CONF_SMTP_USERNAME,
    DOMAIN,
)


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
