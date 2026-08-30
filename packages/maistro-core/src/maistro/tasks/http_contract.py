"""Shared HTTP contract for task admission scope.

Workspace scope is an admission binding, not part of ``TaskCreate``. The
Conductor therefore carries an already-authorized Workspace across the
server-to-server boundary in a dedicated header. A second header proves that
the binding came from the trusted Hive service rather than from an ordinary
maistro-server API client; maistro-server verifies that proof before passing the
binding to the canonical ``WorkspaceRoutingAdmitter``.
"""

from __future__ import annotations

import hashlib
import hmac

WORKSPACE_ID_HEADER = "X-Maistro-Workspace-Id"
WORKSPACE_SCOPE_SIGNATURE_HEADER = "X-Maistro-Workspace-Signature"
_SCOPE_SIGNATURE_DOMAIN = "maistro-workspace-scope:v1:"


def sign_workspace_scope(workspace_id: str, key: str) -> str:
    """Return the domain-separated HMAC-SHA256 proof for one Workspace binding."""
    message = f"{_SCOPE_SIGNATURE_DOMAIN}{workspace_id}"
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_workspace_scope_signature(workspace_id: str, signature: str, key: str) -> bool:
    """Verify a Workspace binding without timing-sensitive string comparison."""
    expected = sign_workspace_scope(workspace_id, key)
    return hmac.compare_digest(signature, expected)


__all__ = [
    "WORKSPACE_ID_HEADER",
    "WORKSPACE_SCOPE_SIGNATURE_HEADER",
    "sign_workspace_scope",
    "verify_workspace_scope_signature",
]
