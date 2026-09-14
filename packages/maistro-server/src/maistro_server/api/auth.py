"""Bearer token authentication for API endpoints.

Every configured API key names an explicit canonical principal (#843):
entries are ``principal:secret``. Administrator authority is selected only by
placing the same entry shape in the separate ``ADMIN_API_KEYS`` setting; it is
never inferred from secret text. A plain secret-only entry is the legacy form
that authenticated everything as the invented user ``default``; it no longer
authenticates at all and the server refuses to start while one is configured
(see ``_validate_startup``). API keys authenticate into the same canonical
``AuthenticatedPrincipal`` model used by every other identity provider — there
is no API-key-only user store or authorization path (#843 stop condition).
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
API_KEY_ENTRY_DOC = 'principal:secret, e.g. API_KEYS=["ops:<secret>"]'


def _parse_api_key_entry(entry: str) -> tuple[str, str, frozenset[str]] | None:
    """Parse one entry into ``(principal, secret, roles)``.

    The wire format is deliberately only ``principal:secret``. Splitting at
    the first colon preserves every later colon as secret material, so a
    secret can never turn into an authority marker. Administrator authority is
    supplied by the caller for entries in ``ADMIN_API_KEYS`` rather than
    inferred from a reserved token.

    The one rejected legacy-looking shape ``principal:admin:`` is kept as an
    invalid configuration instead of being accepted with a different meaning:
    it was the old role spelling with an empty effective secret.
    """
    entry = entry.strip()
    if not entry or entry.startswith("sk-"):
        return None
    principal, separator, secret = entry.partition(":")
    if not separator or not principal.strip() or not secret.strip():
        return None
    parts = entry.split(":")
    if len(parts) == 3 and parts[1].strip().lower() == "admin" and not parts[2].strip():
        return None
    return principal.strip(), secret, frozenset({"user"})


def invalid_api_key_entries(settings: Settings) -> list[str]:
    """Describe invalid entries using the canonical parser, without secrets."""
    problems: list[str] = []
    for setting_name, entries in (
        ("entry", settings.api_keys),
        ("admin entry", settings.admin_api_keys),
    ):
        for position, entry in enumerate(entries, start=1):
            if _parse_api_key_entry(entry) is not None:
                continue
            stripped = entry.strip()
            if not stripped:
                defect = "empty"
            elif stripped.startswith("sk-"):
                defect = "secret-shaped key with no principal prefix"
            elif ":" not in stripped:
                defect = "plain secret-only key"
            elif not stripped.split(":", 1)[0].strip():
                defect = "missing principal before ':'"
            elif (
                len(stripped.split(":")) == 3
                and stripped.split(":")[1].strip().lower() == "admin"
                and not stripped.split(":")[2].strip()
            ):
                defect = "empty secret after legacy admin marker"
            else:
                defect = "missing secret after ':'"
            problems.append(f"{setting_name} {position}: {defect}")
    return problems


def _configured_entries(settings: Settings) -> tuple[tuple[str, bool], ...]:
    """Return entries with authority sourced from configuration, not text."""
    return tuple((entry, False) for entry in settings.api_keys) + tuple(
        (entry, True) for entry in settings.admin_api_keys
    )


def resolve_token_principal(token: str, settings: Settings) -> AuthenticatedPrincipal | None:
    """Resolve bearer secret to principal, or None if invalid."""
    if not settings.api_keys and not settings.admin_api_keys:
        # nosec B106 — auth is DISABLED (both key lists are empty), so we
        # construct a dev principal with an empty token literal. The empty
        # string is a sentinel, not a hardcoded credential.
        return AuthenticatedPrincipal(user_id="dev", token="", roles=frozenset({"admin", "user"}))  # nosec B106
    index = _build_token_index(settings)
    for secret, principal in index.items():
        if secret_equal(token, secret):
            return principal
    return None


def _build_token_index(settings: Settings) -> dict[str, AuthenticatedPrincipal]:
    """Map bearer secret -> principal for configured key entries.

    Legacy plain secret-only entries are deliberately absent from the index
    (#843): even if the startup gate is bypassed, presenting one must fail
    closed rather than authenticate as an invented ``default`` user.

    Both the bare secret and the full configured entry authenticate. The
    bare secret is the credential clients send (the principal prefix is
    server-side configuration), which is what lets an installation rewrite
    a legacy plain key ``<secret>`` as ``principal:<secret>`` and keep every
    existing client working — the #843 migration path. Administrator roles
    come only from the list that supplied the entry.
    """
    index: dict[str, AuthenticatedPrincipal] = {}
    # Add ordinary keys first and explicit administrator keys last. If an
    # operator intentionally uses the same secret in both lists, authority is
    # still explicit in configuration rather than inferred from the secret.
    for entry, is_admin in _configured_entries(settings):
        parsed = _parse_api_key_entry(entry)
        if parsed is None:
            continue
        user_id, secret, _ = parsed
        roles = frozenset({"admin", "user"}) if is_admin else frozenset({"user"})
        principal = AuthenticatedPrincipal(user_id=user_id, token=secret, roles=roles)
        index[secret] = principal
        index[entry.strip()] = principal
    return index


def verify_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedPrincipal | None:
    """Verify bearer token. Returns None only when auth is disabled (no API keys)."""
    if not settings.api_keys and not settings.admin_api_keys:
        # nosec B106 — auth is DISABLED (both key lists are empty), so we
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
