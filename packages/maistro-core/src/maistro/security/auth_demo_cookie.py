"""Demo cookie authentication provider.

Validates HS256 JWTs signed with the router API key.
Accepts tokens from two sources:
  1. Authorization header: "Bearer demo-jwt:<token>" (injected by middleware)
  2. Session cookie (direct cookie reads, when headers are passed)
"""

from __future__ import annotations

from http.cookies import SimpleCookie

from maistro.security._types import AuthContext, IdentityKind

_PREFIX = "Bearer demo-jwt:"

_MIN_KEY_LENGTH = 32
_logger = __import__("logging").getLogger("maistro.auth.demo_cookie")


class DemoCookieAuthProvider:
    """Authenticates via HS256 JWT from middleware-injected header or cookie."""

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
        token: str = ""

        if authorization and authorization.startswith(_PREFIX):
            token = authorization[len(_PREFIX) :]

        if not token and headers:
            cookie_header = headers.get("cookie", "")
            if cookie_header:
                sc: SimpleCookie = SimpleCookie()
                try:
                    sc.load(cookie_header)
                except Exception as _exc:
                    __import__("logging").getLogger("maistro.security.auth_demo_cookie").warning(
                        "error_swallowed file=%s line=%d: %s",
                        "packages/maistro-core/src/maistro/security/auth_demo_cookie.py",
                        51,
                        _exc,
                    )
                    pass
                else:
                    morsel = sc.get(self._cookie_name)
                    if morsel and morsel.value:
                        token = morsel.value

        if not token:
            msg = "No demo session token"
            raise ValueError(msg)

        try:
            import jwt as pyjwt

            claims = pyjwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience="maistro",
                issuer="maistro-demo",
            )
        except Exception as e:
            msg = f"Invalid demo session: {e}"
            raise ValueError(msg) from e

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
