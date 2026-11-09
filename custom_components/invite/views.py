"""Public registration page reached through the invitation link."""

from __future__ import annotations

import ipaddress
import logging
import re
from collections import deque
from datetime import datetime
from html import escape
from http import HTTPStatus

from aiohttp import web
from homeassistant.components import persistent_notification
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_URL,
    DOMAIN,
    FAILED_ATTEMPT_WINDOW,
    MAX_FAILED_ATTEMPTS,
    MAX_PASSWORD_BYTES,
    MAX_TRACKED_CLIENTS,
    MIN_PASSWORD_LENGTH,
    REGISTER_URL,
    USERNAME_PATTERN,
)
from .models import DATA_INVITE
from .store import Invite
from .texts import get_texts
from .users import UsernameTakenError, async_create_user, async_remove_user

_LOGGER = logging.getLogger(__name__)

_USERNAME_RE = re.compile(USERNAME_PATTERN)

# Home Assistant's own middleware adds X-Frame-Options: SAMEORIGIN; the CSP below forbids
# framing altogether in current browsers.
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    # The token is in the URL: never leak it to other sites.
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
}

_STYLE = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f2f4f7;
margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;color:#1c1c1c}
main{background:#fff;max-width:380px;width:100%;margin:16px;padding:28px;border-radius:12px;
box-shadow:0 2px 12px rgba(0,0,0,.08)}
h1{font-size:1.3rem;margin:0 0 8px}p{line-height:1.45}label{display:block;margin-top:16px;
font-weight:600}input{width:100%;box-sizing:border-box;padding:10px;margin-top:6px;
border:1px solid #c4c9d0;border-radius:8px;font-size:1rem}small{color:#5f6b7a}
button,a.button{display:block;width:100%;margin-top:24px;padding:12px;border:0;
border-radius:8px;background:#03a9f4;color:#fff;font-size:1rem;text-align:center;
text-decoration:none;cursor:pointer}.error{background:#fdecea;color:#b3261e;padding:10px;
border-radius:8px}
"""


def _page(title: str, body: str, status: int = HTTPStatus.OK) -> web.Response:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
    return web.Response(
        text=html, content_type="text/html", status=status, headers=_SECURITY_HEADERS
    )


def client_key(remote: str | None) -> str:
    """Group clients for rate limiting: one IPv4 address, or one IPv6 /64."""
    if not remote:
        return "unknown"
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return remote
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


class FailedAttempts:
    """Count failed token lookups per client, with bounded memory."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[datetime]] = {}

    def _prune(self, key: str) -> deque[datetime] | None:
        attempts = self._attempts.get(key)
        if attempts is None:
            return None
        cutoff = dt_util.utcnow() - FAILED_ATTEMPT_WINDOW
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if not attempts:
            del self._attempts[key]
            return None
        return attempts

    def blocked(self, key: str) -> bool:
        attempts = self._prune(key)
        return attempts is not None and len(attempts) >= MAX_FAILED_ATTEMPTS

    def add(self, key: str) -> None:
        attempts = self._prune(key)
        if attempts is None:
            while len(self._attempts) >= MAX_TRACKED_CLIENTS:
                # Forget the client tracked the longest (dicts keep insertion order).
                del self._attempts[next(iter(self._attempts))]
            attempts = self._attempts[key] = deque()
        attempts.append(dt_util.utcnow())

    def __len__(self) -> int:
        return len(self._attempts)


class InviteRegisterView(HomeAssistantView):
    """Let an invited guest choose a username and password."""

    url = REGISTER_URL
    name = "api:invite:register"
    requires_auth = False

    def __init__(self) -> None:
        """Initialize the view."""
        self.failed = FailedAttempts()

    @staticmethod
    def _entry(hass: HomeAssistant) -> ConfigEntry | None:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        return entries[0] if entries else None

    def _lookup(self, hass: HomeAssistant, token: str) -> Invite | None:
        if self._entry(hass) is None or (data := hass.data.get(DATA_INVITE)) is None:
            return None
        return data.store.get_pending_by_token(token)

    def _reject(self, hass: HomeAssistant, key: str) -> web.Response:
        """Answer an unusable token, counting it as a failed attempt."""
        texts = get_texts(hass.config.language)
        if self.failed.blocked(key):
            body = f"<p class='error'>{escape(texts['too_many'])}</p>"
            return _page(texts["page_title"], body, HTTPStatus.TOO_MANY_REQUESTS)
        self.failed.add(key)
        body = f"<h1>{escape(texts['invalid_title'])}</h1><p>{escape(texts['invalid_body'])}</p>"
        return _page(texts["invalid_title"], body, HTTPStatus.NOT_FOUND)

    @staticmethod
    def _form(
        hass: HomeAssistant, name: str, username: str = "", error: str | None = None
    ) -> web.Response:
        texts = get_texts(hass.config.language)
        error_html = f"<p class='error'>{escape(error)}</p>" if error else ""
        body = (
            f"<h1>{escape(texts['heading'].format(name=name))}</h1>"
            f"<p>{escape(texts['intro'])}</p>{error_html}"
            "<form method='post' autocomplete='on'>"
            f"<label for='username'>{escape(texts['username'])}</label>"
            f"<input id='username' name='username' value='{escape(username)}' required "
            "autocapitalize='none' autocomplete='username' maxlength='32'>"
            f"<small>{escape(texts['username_hint'])}</small>"
            f"<label for='password'>{escape(texts['password'])}</label>"
            "<input id='password' name='password' type='password' required "
            f"autocomplete='new-password' minlength='{MIN_PASSWORD_LENGTH}'>"
            f"<small>{escape(texts['password_hint'].format(min=MIN_PASSWORD_LENGTH))}</small>"
            f"<label for='password_confirm'>{escape(texts['password_confirm'])}</label>"
            "<input id='password_confirm' name='password_confirm' type='password' required "
            f"autocomplete='new-password' minlength='{MIN_PASSWORD_LENGTH}'>"
            f"<button type='submit'>{escape(texts['submit'])}</button></form>"
        )
        return _page(texts["page_title"], body)

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Show the registration form."""
        hass: HomeAssistant = request.app["hass"]
        # A valid token is always honoured; only failures are throttled.
        if (invite := self._lookup(hass, token)) is None:
            return self._reject(hass, client_key(request.remote))
        return self._form(hass, invite.name)

    async def post(self, request: web.Request, token: str) -> web.Response:
        """Create the user."""
        hass: HomeAssistant = request.app["hass"]
        key = client_key(request.remote)
        if (invite := self._lookup(hass, token)) is None:
            return self._reject(hass, key)
        texts = get_texts(hass.config.language)

        # Read and validate the form before taking the lock, so a slow client holding a link
        # cannot stall everybody else's registration.
        form = await request.post()
        username = str(form.get("username", "")).strip().casefold()
        password = str(form.get("password", ""))
        confirm = str(form.get("password_confirm", ""))
        error: str | None = None
        if not _USERNAME_RE.match(username):
            error = texts["error_username"]
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = texts["error_password_short"].format(min=MIN_PASSWORD_LENGTH)
        elif len(password.encode()) > MAX_PASSWORD_BYTES:
            error = texts["error_password_long"].format(max=MAX_PASSWORD_BYTES)
        elif password != confirm:
            error = texts["error_password_mismatch"]
        if error:
            return self._form(hass, invite.name, username, error)

        data = hass.data[DATA_INVITE]
        async with data.lock:
            # Looked up again inside the lock: the invite may have been used or revoked while
            # the form was being read.
            if (invite := self._lookup(hass, token)) is None:
                return self._reject(hass, key)
            try:
                user = await async_create_user(hass, invite.name, username, password, invite.admin)
            except UsernameTakenError:
                return self._form(hass, invite.name, username, texts["error_username_taken"])
            except Exception:
                _LOGGER.exception("Registration failed for invite %s", invite.id)
                return self._form(hass, invite.name, username, texts["error_unknown"])
            try:
                await data.store.async_mark_used(invite, user.id)
            except Exception:
                _LOGGER.exception("Could not mark invite %s as used; removing user", invite.id)
                await async_remove_user(hass, user, username)
                return self._form(hass, invite.name, username, texts["error_unknown"])

        _LOGGER.info("Invite %s used: created user %s (%s)", invite.id, username, user.id)
        persistent_notification.async_create(
            hass,
            texts["notif_used"].format(name=invite.name, username=username, invite_id=invite.id),
            title=texts["notif_used_title"],
            notification_id=f"{DOMAIN}_used_{invite.id}",
        )
        entry = self._entry(hass)
        base_url = entry.data[CONF_BASE_URL] if entry else "/"
        body = (
            f"<h1>{escape(texts['done_title'])}</h1>"
            f"<p>{escape(texts['done_body'].format(username=username))}</p>"
            f"<a class='button' href='{escape(base_url)}'>{escape(texts['done_link'])}</a>"
        )
        return _page(texts["done_title"], body)
