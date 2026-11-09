# Invite for Home Assistant

[![Validate](https://github.com/jvitali/ha-invite/actions/workflows/validate.yml/badge.svg)](https://github.com/jvitali/ha-invite/actions/workflows/validate.yml)

Invite people to your Home Assistant with a **single-use link** where they choose their own
username and password. The link can be emailed (SMTP, e.g. Gmail) or shared by you.

Home Assistant has no built-in invitations: an admin has to create each user and pass the
password around. With Invite, you run one action and the guest does the rest.

## How it works

1. An admin runs **Invite: Create invite** with the guest's name (and optionally an email).
2. With an email, Invite sends the link. Without one, the link comes back in the action
   response and you share it yourself.
3. The guest opens `https://your-ha/api/invite/register/<token>`, picks a username and
   password, and Invite creates the user, its login and a linked person.
4. The link stops working. You get a notification.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/jvitali/ha-invite`, type
   **Integration**.
2. Download **Invite** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Invite**, and enter the URL guests
   use to open Home Assistant (for example `https://ha.example.com`).
4. Optional: open the integration options to set the default expiry and an SMTP server.
   For Gmail: `smtp.gmail.com`, port `587`, STARTTLS, your address as username and sender,
   and an [app password](https://myaccount.google.com/apppasswords).

## Actions

| Action | What it does |
| --- | --- |
| `invite.create` | `name` (required), `email`, `admin` (default `false`), `expires_hours` (1 to 168). With `email`, sends the link over SMTP (an error if SMTP is not configured or sending fails; the invite is then revoked). Without `email`, returns the link in the response, which must be requested. Response: `invite_id`, `expires_at`, `emailed`, and `link` when not emailed. |
| `invite.revoke` | `invite_id`. Invalidates a pending invite. |
| `invite.list` | Returns pending and past invites (without links). |

Only administrators can run them. Calls without a user (automations and scripts) are also
allowed, like any admin-only action in Home Assistant: if non-admins can trigger one of your
automations or scripts that calls `invite.create`, they can create invites through it.

To run them by hand, open **Settings → Tools → Actions** (`/config/tools/action`; it was
called *Developer tools* before Home Assistant 2026.8) and search for "Invite". The response
with the link is shown below the action. In a script, keep it with `response_variable`.

```yaml
action: invite.create
data:
  name: Ana
  email: ana@example.com
```

## Security

- Tokens are 256-bit random values. Only their SHA-256 hash is stored, so reading
  `.storage/invite.invites` is not enough to register.
- Links are single use and expire (48 h by default, at most 7 days). They can be revoked.
  Registration, creation and revocation are serialized, so a link cannot be used twice, even
  across a reload of the integration, and a revoke never hides an account being created.
- The registration page needs no login. After 10 unknown or used links in 10 minutes from the
  same address (IPv6: the same /64), it answers 429 for unknown links; a valid link always
  works. Tokens are long enough that guessing them is not practical anyway.
- Invites never create admins unless you ask for it, and never create the owner: if Home
  Assistant has no owner yet, registration is refused.
- The page sends `Referrer-Policy: no-referrer`, a strict CSP and no-cache headers.
- The link is never put in a notification (every user can read those).
- The link does exist outside the hashed store: in the email, in the action response and
  anything that keeps it (automation traces), and in the access logs of a reverse proxy in
  front of Home Assistant. Keep expiries short and revoke unused invites.
- SMTP uses certificate validation; plain-text authentication (no encryption with a username)
  is refused. Removing the integration deletes all invites.
- The link only works where the URL works: if your Home Assistant is only reachable at home or
  through a VPN, the guest has to be there to register.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest
```

## License

MIT
