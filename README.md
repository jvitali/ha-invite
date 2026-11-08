# Invite for Home Assistant

[![Validate](https://github.com/jvitali/ha-invite/actions/workflows/validate.yml/badge.svg)](https://github.com/jvitali/ha-invite/actions/workflows/validate.yml)

Invite people to your Home Assistant with a **single-use link** where they choose their own
username and password. The link can be emailed (SMTP, e.g. Gmail) or shared by you.

Home Assistant has no built-in invitations: an admin has to create each user and pass the
password around. With Invite, you run one action and the guest does the rest.

## How it works

1. An admin runs **Invite: Create invite** with the guest's name (and optionally an email).
2. The guest gets a link like `https://your-ha/api/invite/register/<token>` and opens it.
3. They pick a username and password. Invite creates the user, its login and a linked person.
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
| `invite.create` | `name` (required), `email`, `admin` (default `false`), `expires_hours`. Emails the link if SMTP is configured; otherwise shows it in a notification. Always returns `invite_id`, `link`, `expires_at` and `emailed` as response. |
| `invite.revoke` | `invite_id`. Invalidates a pending invite. |
| `invite.list` | Returns pending and past invites (without links). |

Only administrators (and automations) can run them.

```yaml
action: invite.create
data:
  name: Ana
  email: ana@example.com
```

## Security

- Tokens are 256-bit random values. Only their SHA-256 hash is stored, so reading
  `.storage/invite.invites` is not enough to register.
- Links are single use and expire (48 h by default, at most 30 days). They can be revoked.
- The registration page needs no login. After 10 bad links in 10 minutes from the same
  address, it answers 429 for that address.
- Invites never create admins unless you ask for it, and never create the owner: if Home
  Assistant has no owner yet, registration is refused.
- The page sends `Referrer-Policy: no-referrer`, a strict CSP and no-cache headers.
- **Notifications are visible to every user.** When the link is not emailed, it is shown in a
  notification; revoke the invite if someone else may have used it.
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
