"""Bearer token authentication for API endpoints.

Every configured API key names an explicit canonical principal (#843):
entries are ``principal:secret`` (or ``principal:admin:secret``). A plain
secret-only entry is the legacy form that authenticated everything as the
invented user ``default``; it no longer authenticates at all and the server
refuses to start while one is configured (see ``_validate_startup``). API
keys authenticate into the same canonical ``AuthenticatedPrincipal`` model
used by every other identity provider — there is no API-key-only user store
or authorization path (#843 stop condition).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from maistro.config.settings import Settings, get_settings
from maistro.security.secret_equal import secret_equal
from maistro_server.api.principal import AuthenticatedPrincipal

security_scheme = HTTPBearer(auto_error=False)

#: The accepted API_KEYS entry syntax, stated once so the parser, the
#: startup gate, and every error message agree on it (#843).
API_KEY_ENTRY_DOC = (
    "principal:secret (or principal:admin:secret), e.g. "
    'API_KEYS=["ops:<secret>"]'
)


def _parse_api_key_entry(entry: str) -> tuple[str, str, frozenset[str]] | None:
    """Parse one ``API_KEYS`` entry into ``(principal, secret, roles)``.

    #843: an entry that does not name an explicit canonical principal is
    rejected — the parser must never invent a ``default`` owner.

    Accepted:

    * ``principal:secret`` — everything after the first colon is the secret,
      so secrets containing colons keep working unchanged.
    * ``principal:admin:secret`` — grants the ``admin`` role in addition to
      ``user``. The ``admin`` segment is only interpreted as a role when it
      sits between the principal and the secret (``split(":", 2)``), which
      makes the previously-dead ``endswith(":admin")`` branch of the old
      parser actually reachable.

    Rejected (``None`` — must not authenticate):

    * a plain secret with no colon, including ``sk-``-prefixed secrets;
    * an empty/whitespace-only principal or secret segment.
    """
    entry = entry.strip()
    if not entry or entry.startswith("sk-"):
        # ``sk-`` marks a secret-shaped entry (its colons belong to the
        # secret), never a principal prefix.
        return None
    parts = entry.split(":", 2)
    if len(parts) < 2:
        return None
    user_id = parts[0].strip()
    roles = frozenset({"user"})
    secret_start = 1
    if len(parts) == 3 and parts[1].strip().lower() == "admin":
        roles = frozenset({"admin", "user"})
        secret_start = 2
    secret = ":".join(parts[secret_start:])
    if not user_id or not secret:
        return None
    return user_id, secret, roles


def invalid_api_key_entries(settings: Settings) -> list[str]:
    """Describe every non-conforming ``API_KEYS`` entry, without echoing it.

    Key material must never appear in an error, log label, or metric label
    (#843), so descriptions name the entry's position and its defect only.
    An empty result means the configuration is valid.
    """
    problems: list[str] = []
    for position, entry in enumerate(settings.api_keys, start=1):
        stripped = entry.strip()
        if not stripped:
            problems.append(f"entry {position}: empty")
        elif stripped.startswith("sk-"):
            problems.append(
                f"entry {position}: secret-shaped key with no principal prefix"
            )
        elif ":" not in stripped:
            problems.append(f"entry {position}: plain secret-only key")
        else:
            user_id, _, secret = stripped.partition(":")
            if not user_id.strip():
                problems.append(f"entry {position}: missing principal before ':'")
            elif not secret:
                problems.append(f"entry {position}: missing secret after ':'")
    return problems


def resolve_token_principal(token: str, settings: Settings) -> AuthenticatedPrincipal | None:
    """Resolve bearer secret to principal, or None if invalid."""
    if not settings.api_keys:
        # nosec B106 — auth is DISABLED (settings.api_keys is empty), so we
        # construct a dev principal with an empty token literal. The empty
        # string is a sentinel, not a hardcoded credential.
        return AuthenticatedPrincipal(user_id="dev", token="", roles=frozenset({"admin", "user"}))  # nosec B106
    index = _build_token_index(settings)
    for secret, principal in index.items():
        if secret_equal(token, secret):
            return principal
    return None


def _build_token_index(settings: Settings) -> dict[str, AuthenticatedPrincipal]:
    """Map bearer secret -> principal for ``principal:secret`` entries.

    Legacy plain secret-only entries are deliberately absent from the index
    (#843): even if the startup gate is bypassed, presenting one must fail
    closed rather than authenticate as an invented ``default`` user.

    Both the bare secret and the full configured entry authenticate. The
    bare secret is the credential clients send (the principal prefix is
    server-side configuration), which is what lets an installation rewrite
    a legacy plain key ``<secret>`` as ``principal:<secret>`` and keep every
    existing client working — the #843 migration path.
    """
    index: dict[str, AuthenticatedPrincipal] = {}
    for entry in settings.api_keys:
        parsed = _parse_api_key_entry(entry)
        if parsed is None:
            continue
        user_id, secret, roles = parsed
        principal = AuthenticatedPrincipal(user_id=user_id, token=secret, roles=roles)
        index[secret] = principal
        index[entry.strip()] = principal
    return index


def verify_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedPrincipal | None:
    """Verify bearer token. Returns None only when auth is disabled (no API keys)."""
    if not settings.api_keys:
        # nosec B106 — auth is DISABLED (settings.api_keys is empty), so we
        # construct a dev principal with an empty token literal. The empty
        # string is a sentinel, not a hardcoded credential.
        return AuthenticatedPrincipal(user_id="dev", token="", roles=frozenset({"admin", "user"}))  # nosec B106

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = resolve_token_principal(credentials.credentials, settings)
    if principal is not None:
        return principal

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


RequireAuth = Annotated[AuthenticatedPrincipal | None, Depends(verify_api_key)]
