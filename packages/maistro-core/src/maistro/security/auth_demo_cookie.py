"""Demo cookie authentication provider.

Validates HS256 JWTs signed with the router API key.
Accepts tokens from two sources:
  1. Authorization header: "Bearer demo-jwt:<token>" (injected by middleware)
  2. Session cookie (direct cookie reads, when headers are passed)
"""

from __future__ import annotations

from http.cookies import SimpleCookie

from maistro.security._types import AuthContext, IdentityKind
from maistro.security.auth_composite import AuthError, CredentialNotApplicable

_PREFIX = "Bearer demo-jwt:"

_MIN_KEY_LENGTH = 32
_logger = __import__("logging").getLogger("maistro.auth.demo_cookie")


class DemoCookieAuthProvider:
    """Authenticates via HS256 JWT from middleware-injected header or cookie."""

    scheme = "demo_session"

    def __init__(self, api_key: str, cookie_name: str = "maistro_session") -> None:
        if len(api_key) < _MIN_KEY_LENGTH:
            _logger.warning(
                "DemoCookieAuthProvider: API key is %d bytes, minimum recommended "
                "is %d for HS256 security. Set a longer ROUTER_API_KEY.",
                len(api_key),
                _MIN_KEY_LENGTH,
            )
        self._key = api_key
        self._cookie_name = cookie_name

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        recognized, token = self._extract_credential(authorization, headers)
        if not recognized:
            raise CredentialNotApplicable("No demo session credential")
        if not token:
            raise AuthError("Empty demo session credential")

        try:
            import jwt as pyjwt
        except ImportError:
            raise

        try:
            claims = pyjwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience="maistro",
                issuer="maistro-demo",
            )
        except Exception as error:
            raise AuthError("Invalid demo session") from error

        roles_raw = claims.get("roles", [])
        roles = frozenset(roles_raw) if isinstance(roles_raw, list) else frozenset()

        return AuthContext(
            user_id=claims.get("sub", ""),
            username=claims.get("preferred_username", ""),
            roles=roles,
            team_id=claims.get("team_id", ""),
            kind=IdentityKind.USER,
            auth_method="demo_cookie",
        )

    def _extract_credential(
        self,
        authorization: str | None,
        headers: dict[str, str] | None,
    ) -> tuple[bool, str]:
        if authorization and authorization.startswith(_PREFIX):
            return True, authorization[len(_PREFIX) :]

        if not headers:
            return False, ""
        cookie_header = headers.get("cookie", "")
        if not cookie_header:
            return False, ""

        sc: SimpleCookie = SimpleCookie()
        try:
            sc.load(cookie_header)
        except Exception as error:
            _logger.warning("Failed to parse cookie header: %s", type(error).__name__)
            return False, ""

        morsel = sc.get(self._cookie_name)
        if morsel is None:
            return False, ""
        return True, str(morsel.value)
