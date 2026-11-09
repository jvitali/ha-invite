"""Config flow: base URL first, email (SMTP) and defaults in the options."""

from __future__ import annotations

import logging
import smtplib
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BASE_URL,
    CONF_EXPIRY_HOURS,
    CONF_SMTP_ENCRYPTION,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_SENDER,
    CONF_SMTP_USERNAME,
    DEFAULT_EXPIRY_HOURS,
    DEFAULT_SMTP_PORT,
    DOMAIN,
    ENCRYPTION_NONE,
    ENCRYPTION_STARTTLS,
    ENCRYPTION_TLS,
    MAX_EXPIRY_HOURS,
)
from .mailer import check_smtp

_LOGGER = logging.getLogger(__name__)

_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))


def _valid_email(address: str) -> bool:
    try:
        vol.Email()(address)  # pylint: disable=no-value-for-parameter
    except vol.Invalid:
        return False
    return True


def _valid_url(url: str) -> bool:
    return url.startswith(("http://", "https://")) and len(url) > len("https://x")


class InviteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Invite."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the URL guests use to reach Home Assistant."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_BASE_URL].strip().rstrip("/")
            if _valid_url(url):
                return self.async_create_entry(title="Invite", data={CONF_BASE_URL: url})
            errors[CONF_BASE_URL] = "invalid_url"

        try:
            default_url = get_url(self.hass, prefer_external=True)
        except NoURLAvailableError:
            default_url = ""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_BASE_URL, default=default_url): _URL}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> InviteOptionsFlow:
        """Return the options flow."""
        return InviteOptionsFlow()


class InviteOptionsFlow(OptionsFlowWithReload):
    """Edit expiry and email settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and validate the options."""
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options)
        if user_input is not None:
            options = {k: v for k, v in user_input.items() if v not in (None, "")}
            # An empty password field keeps the stored one (it is never shown back).
            if not options.get(CONF_SMTP_PASSWORD) and current.get(CONF_SMTP_PASSWORD):
                options[CONF_SMTP_PASSWORD] = current[CONF_SMTP_PASSWORD]
            if options.get(CONF_SMTP_HOST):
                if not options.get(CONF_SMTP_SENDER):
                    errors[CONF_SMTP_SENDER] = "sender_required"
                elif not _valid_email(options[CONF_SMTP_SENDER]):
                    errors[CONF_SMTP_SENDER] = "invalid_sender"
                elif options.get(CONF_SMTP_ENCRYPTION) == ENCRYPTION_NONE and options.get(
                    CONF_SMTP_USERNAME
                ):
                    # The password would travel in plain text.
                    errors[CONF_SMTP_ENCRYPTION] = "insecure_auth"
                else:
                    try:
                        await self.hass.async_add_executor_job(check_smtp, options)
                    except smtplib.SMTPAuthenticationError:
                        errors["base"] = "invalid_auth"
                    except (TimeoutError, smtplib.SMTPException, OSError) as err:
                        _LOGGER.warning("SMTP check failed: %s", err)
                        errors["base"] = "cannot_connect"
            if not errors:
                return self.async_create_entry(data=options)
            current = {**current, **user_input}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_EXPIRY_HOURS,
                    default=current.get(CONF_EXPIRY_HOURS, DEFAULT_EXPIRY_HOURS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=MAX_EXPIRY_HOURS, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_SMTP_HOST,
                    description={"suggested_value": current.get(CONF_SMTP_HOST)},
                ): TextSelector(),
                vol.Optional(
                    CONF_SMTP_PORT,
                    default=current.get(CONF_SMTP_PORT, DEFAULT_SMTP_PORT),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_SMTP_ENCRYPTION,
                    default=current.get(CONF_SMTP_ENCRYPTION, ENCRYPTION_STARTTLS),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[ENCRYPTION_STARTTLS, ENCRYPTION_TLS, ENCRYPTION_NONE],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="smtp_encryption",
                    )
                ),
                vol.Optional(
                    CONF_SMTP_USERNAME,
                    description={"suggested_value": current.get(CONF_SMTP_USERNAME)},
                ): TextSelector(),
                vol.Optional(CONF_SMTP_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_SMTP_SENDER,
                    description={"suggested_value": current.get(CONF_SMTP_SENDER)},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
