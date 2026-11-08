"""User-facing texts for the registration page and the invitation email.

These are outside Home Assistant's translation system (the guest has no session yet), so
they are picked from the instance language: Spanish for "es*", English otherwise.
"""

from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "page_title": "Join Home Assistant",
        "heading": "Hi {name}! Create your account",
        "intro": "Choose the username and password you will use to sign in to Home Assistant.",
        "username": "Username",
        "username_hint": "3 to 32 characters: lowercase letters, numbers, dot, dash or underscore.",
        "password": "Password",
        "password_hint": "At least {min} characters.",
        "password_confirm": "Repeat the password",
        "submit": "Create account",
        "invalid_title": "Invitation not valid",
        "invalid_body": "This invitation does not exist, has expired or was already used. Ask for a new one.",
        "too_many": "Too many attempts. Try again in a few minutes.",
        "done_title": "Your account is ready",
        "done_body": "You can now sign in with the username {username}.",
        "done_link": "Open Home Assistant",
        "error_username": "The username is not valid.",
        "error_username_taken": "That username is already taken.",
        "error_password_short": "The password must have at least {min} characters.",
        "error_password_mismatch": "The passwords do not match.",
        "error_unknown": "The account could not be created. Try again or ask whoever invited you.",
        "notif_created_title": "Invite created",
        "notif_created": "Send this link to **{name}** (single use, expires {expires}):\n\n{link}",
        "notif_used_title": "Invite used",
        "notif_used": "{name} created the user **{username}** (invite `{invite_id}`).",
        "email_subject": "You are invited to Home Assistant",
        "email_body": (
            "Hi {name}!\n\n"
            "You have been invited to the Home Assistant at home. To create your account, "
            "open this link and choose your username and password:\n\n{link}\n\n"
            "The link works only once and expires on {expires}.\n"
            "It opens only from the home network or with the VPN (for example Tailscale) on.\n\n"
            "Then install the Home Assistant app on your phone and sign in with {base_url}\n"
        ),
    },
    "es": {
        "page_title": "Sumate a Home Assistant",
        "heading": "¡Hola, {name}! Creá tu cuenta",
        "intro": "Elegí el usuario y la contraseña con los que vas a entrar a Home Assistant.",
        "username": "Usuario",
        "username_hint": "De 3 a 32 caracteres: minúsculas, números, punto, guion o guion bajo.",
        "password": "Contraseña",
        "password_hint": "Al menos {min} caracteres.",
        "password_confirm": "Repetí la contraseña",
        "submit": "Crear cuenta",
        "invalid_title": "Invitación no válida",
        "invalid_body": "Esta invitación no existe, venció o ya se usó. Pedí una nueva.",
        "too_many": "Demasiados intentos. Probá de nuevo en unos minutos.",
        "done_title": "Tu cuenta está lista",
        "done_body": "Ya podés entrar con el usuario {username}.",
        "done_link": "Abrir Home Assistant",
        "error_username": "El usuario no es válido.",
        "error_username_taken": "Ese usuario ya existe.",
        "error_password_short": "La contraseña tiene que tener al menos {min} caracteres.",
        "error_password_mismatch": "Las contraseñas no coinciden.",
        "error_unknown": "No se pudo crear la cuenta. Probá de nuevo o avisale a quien te invitó.",
        "notif_created_title": "Invitación creada",
        "notif_created": "Mandale este enlace a **{name}** (un solo uso, vence el {expires}):\n\n{link}",
        "notif_used_title": "Invitación usada",
        "notif_used": "{name} creó el usuario **{username}** (invitación `{invite_id}`).",
        "email_subject": "Te invitaron a Home Assistant",
        "email_body": (
            "¡Hola, {name}!\n\n"
            "Te invitaron al Home Assistant de casa. Para crear tu cuenta, abrí este enlace "
            "y elegí tu usuario y contraseña:\n\n{link}\n\n"
            "El enlace sirve una sola vez y vence el {expires}.\n"
            "Solo abre conectado al Wi-Fi de casa o con la VPN (por ejemplo Tailscale) prendida.\n\n"
            "Después instalá la app Home Assistant en el celular y entrá con {base_url}\n"
        ),
    },
}


def get_texts(language: str | None) -> dict[str, str]:
    """Return the texts for an instance language."""
    return TEXTS["es"] if (language or "").lower().startswith("es") else TEXTS["en"]
