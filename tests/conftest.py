"""Fixtures for the Invite tests."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.invite.const import CONF_BASE_URL, DOMAIN

BASE_URL = "https://ha.example.com"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""


@pytest.fixture
def entry_options() -> dict:
    """Options of the config entry (no SMTP by default)."""
    return {}


@pytest.fixture
async def setup_invite(
    hass: HomeAssistant, local_auth, hass_owner_user, entry_options: dict
) -> MockConfigEntry:
    """Set up the integration with a config entry."""
    await hass.config.async_update(language="es")
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_BASE_URL: BASE_URL}, options=entry_options)
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "person", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
