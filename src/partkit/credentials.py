"""Supplier API keys, kept in the operating system's password store.

On Windows that is Credential Manager, so keys never sit in a plain file and
never leave the user's PC. An environment variable (for example
PARTKIT_DIGIKEY_CLIENT_ID) wins over the stored value, which is handy for
scripts and tests.
"""

from __future__ import annotations

import os

SERVICE = "PartKit"

# Supplier -> the values its API needs, and where to get a free key.
NEEDED: dict[str, tuple[str, ...]] = {
    "DigiKey": ("client_id", "client_secret"),
    "Mouser": ("api_key",),
    "Farnell": ("api_key",),
}

SIGNUP: dict[str, str] = {
    "DigiKey": "https://developer.digikey.com/",
    "Mouser": "https://www.mouser.com/api-hub/",
    "Farnell": "https://partner.element14.com/",
}


def _env_name(supplier: str, field: str) -> str:
    return f"PARTKIT_{supplier.upper()}_{field.upper()}"


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:  # noqa: BLE001 - no password store: env vars still work
        return None


def get(supplier: str, field: str) -> str:
    env = os.environ.get(_env_name(supplier, field))
    if env:
        return env
    kr = _keyring()
    if kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, f"{supplier}.{field}") or ""
    except Exception:  # noqa: BLE001
        return ""


def set(supplier: str, field: str, value: str) -> None:  # noqa: A001 - mirrors keyring's API
    kr = _keyring()
    if kr is None:
        raise RuntimeError("No password store is available on this computer.")
    if value:
        kr.set_password(SERVICE, f"{supplier}.{field}", value)
    else:
        try:
            kr.delete_password(SERVICE, f"{supplier}.{field}")
        except Exception:  # noqa: BLE001 - nothing stored
            pass


def all_for(supplier: str) -> dict[str, str]:
    return {f: get(supplier, f) for f in NEEDED.get(supplier, ())}


def is_set_up(supplier: str) -> bool:
    need = NEEDED.get(supplier)
    return bool(need) and all(get(supplier, f) for f in need)
