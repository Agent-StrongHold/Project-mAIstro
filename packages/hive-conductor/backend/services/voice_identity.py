"""The credential a voice satellite presents, and the account it acts as (#316).

`/v1/voice/` used to sit in `AuthMiddleware`'s public-prefix list, so the whole
prefix skipped authentication. The route's own `VOICE_API_KEY` check did not
close that: it was read once at import, and its first line was

    if not VOICE_API_KEY:
        return

so with the key unset — the shipped default — every request passed. An
unauthenticated caller reached `run_chat_completion` with tools enabled and no
principal at all.

A voice satellite is a device, not a person, so it cannot hold a session. It
holds a service credential instead, and three properties make that a control
rather than a decoration:

**It resolves to a real account.** The credential names a username; the
principal the middleware attaches is that user's, with their role and
permissions. The key authenticates the device and authorises nothing on its
own, so every downstream decision — the admin chat block, tool elevation,
ownership — applies exactly as it does to that person at a browser.

**Unset means closed, not open.** With no key, or no account, or an account
that does not exist or is disabled, this returns `None` and the middleware
answers 401. There is no configuration of this file that makes the prefix
public again.

**It is read per request.** The old check bound the key to a module-level
constant at import, so no amount of reconfiguration could change it while the
process lived. This resolves it on every call: a rotated vault entry takes
effect on the next request (`resolve_secret` reads the vault uncached), and a
rotated `.env` or environment value on the next `get_settings` cache clear —
which is what a reload does. Neither needs a redeploy.

Scope is enforced by the caller, not here: `AuthMiddleware` only consults this
for paths under `/v1/voice/`, so the credential cannot be replayed against the
rest of the API.
"""

from __future__ import annotations

import os
from typing import Any

from maistro.security.secret_equal import secret_equal

#: The environment variable and vault entry holding the device credential.
VOICE_KEY_SECRET = "VOICE_SERVICE_KEY"

#: The username the credential acts as.
VOICE_ACCOUNT_ENV = "VOICE_SERVICE_ACCOUNT"


def configured_credential() -> tuple[str, str] | None:
    """`(key, username)`, or `None` when voice is not configured.

    Read on every call rather than cached at import: the vault is the source of
    truth (SPEC-003), and a rotation nobody has to restart for is the whole
    point of putting it there.
    """
    from config import get_settings

    from services.secrets import resolve_secret

    settings = get_settings()
    key = resolve_secret(
        VOICE_KEY_SECRET,
        config_value=settings.voice_service_key,
        env_var=VOICE_KEY_SECRET,
    )
    account = (settings.voice_service_account or os.environ.get(VOICE_ACCOUNT_ENV) or "").strip()
    if not key or not account:
        return None
    return key, account


def bearer_token(authorization: str | None) -> str | None:
    """The token in an `Authorization: Bearer …` header, if there is one."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    return token or None


def principal_for(authorization: str | None) -> dict[str, Any] | None:
    """The account this voice credential acts as, or `None`.

    `None` for every reason a caller might want told apart — unconfigured, no
    header, wrong key, unknown account, disabled account — because the answer
    to all of them is the same 401 and any distinction between them is an
    oracle about the deployment's configuration.
    """
    configured = configured_credential()
    if configured is None:
        return None
    key, username = configured

    presented = bearer_token(authorization)
    if presented is None:
        return None
    if not secret_equal(presented, key):
        return None

    import stores

    account = next((u for u in stores.users.values() if u.username == username), None)
    if account is None or not account.is_active:
        return None

    return {
        "id": account.id,
        "username": account.username,
        "role": account.role,
        "permissions": list(account.permissions),
        "did": account.did,
        # A device holds no task-scoped elevation. Anything behind
        # `_PROTECTED_OPS` stays refused for the voice principal, which is the
        # scoping the acceptance criteria ask for: the key is an identity, not
        # a permission.
        "elevated_permissions": [],
        "elevated_tasks": [],
    }
