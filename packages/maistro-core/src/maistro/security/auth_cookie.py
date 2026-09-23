"""Cookie-based authentication provider (BFF pattern).

Extracts a JWT from an HttpOnly session cookie and delegates validation
to the JWTAuthProvider. This keeps tokens out of JavaScript entirely.
"""

from __future__ import annotations

import logging
import re
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING

from maistro.protocols.auth import AuthError, CredentialNotApplicable

if TYPE_CHECKING:
    from maistro.security._types import AuthContext
    from maistro.security.auth_jwt import JWTAuthProvider

logger = logging.getLogger("maistro.auth.cookie")


class CookieAuthProvider:
    """Authenticates via HttpOnly session cookie containing a JWT."""

    scheme = "session_cookie"

    def __init__(
        self,
        *,
        jwt_provider: JWTAuthProvider,
        cookie_name: str = "maistro_session",
    ) -> None:
        self._jwt = jwt_provider
        self._cookie_name = cookie_name

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        if not headers:
            raise CredentialNotApplicable("No headers provided (cookie auth requires headers)")

        cookie_header = headers.get("cookie", "")
        if not cookie_header:
            raise CredentialNotApplicable("No cookie header present")

        token = self._extract_cookie(cookie_header)
        if token is None:
            raise CredentialNotApplicable(f"Cookie '{self._cookie_name}' not found")
        if not token:
            raise AuthError("Empty session cookie")

        try:
            ctx = await self._jwt.authenticate(f"Bearer {token}", headers=headers)
        except CredentialNotApplicable as error:
            # The cookie was already recognized; a nested verifier miss is a
            # rejected session, not an opportunity for another composite member.
            raise AuthError("Invalid session cookie") from error

        logger.debug("Cookie auth succeeded for user=%s", ctx.user_id)
        return ctx

    def _extract_cookie(self, cookie_header: str) -> str | None:
        try:
            sc: SimpleCookie = SimpleCookie()
            sc.load(cookie_header)
            morsel = sc.get(self._cookie_name)
            if morsel is not None:
                return str(morsel.value)
            if re.search(rf"(?:^|;)\s*{re.escape(self._cookie_name)}\s*=", cookie_header):
                return ""
        except Exception:
            logger.warning("Failed to parse cookie header")
            # A malformed value for this provider's cookie is still a
            # recognized credential; do not let a later provider reinterpret it.
            if re.search(rf"(?:^|;)\s*{re.escape(self._cookie_name)}\s*=", cookie_header):
                return ""
        return None
