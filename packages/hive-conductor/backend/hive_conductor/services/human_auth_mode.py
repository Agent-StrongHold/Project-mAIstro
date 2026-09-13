"""Human-login mode policy for M2 #491.

The route layer consumes this policy; it does not infer login availability from
whether a provider happens to be configured. Keeping the mode explicit makes
`local`, `entra`, and `hybrid` deployments distinguishable and prevents a
misconfigured Entra-only deployment from silently falling back to passwords.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HumanAuthMode = Literal["local", "entra", "hybrid"]


@dataclass(frozen=True)
class HumanAuthModePolicy:
    mode: HumanAuthMode = "local"
    allow_break_glass_password: bool = False

    @property
    def entra_login_enabled(self) -> bool:
        return self.mode in ("entra", "hybrid")

    @property
    def ordinary_password_login_enabled(self) -> bool:
        return self.mode in ("local", "hybrid")

    def oauth_provider_enabled(self, provider: str) -> bool:
        """Return whether this deployment exposes a configured OAuth provider."""
        if self.mode == "local":
            return False
        if self.mode == "entra":
            return provider == "entra"
        return True

    def password_login_enabled(self, *, break_glass: bool = False) -> bool:
        """Return whether this server-side login path may accept a password.

        ``break_glass`` is not a request parameter. It represents a distinct
        operator-controlled recovery path. Entra-only mode therefore cannot be
        weakened by a caller asking for break-glass behavior.
        """
        if self.ordinary_password_login_enabled:
            return True
        return bool(break_glass and self.allow_break_glass_password)


__all__ = ["HumanAuthMode", "HumanAuthModePolicy"]
