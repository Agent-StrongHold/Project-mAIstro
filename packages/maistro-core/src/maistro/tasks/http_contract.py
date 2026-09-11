"""Shared HTTP contract for task admission scope.

Workspace scope is an admission binding, not part of ``TaskCreate``. The
Conductor therefore carries an already-authorized Workspace across the
server-to-server boundary in a dedicated header. A second header proves that
the binding came from the trusted Hive service rather than from an ordinary
maistro-server API client; maistro-server verifies that proof before passing the
binding to the canonical ``WorkspaceRoutingAdmitter``.

The same service boundary carries the Hive principal that owns a task. The
owner is not taken from a client-controlled ``TaskCreate.user_id`` field: Hive
sends it in a dedicated header with a separate domain-separated HMAC proof.
This keeps the maistro-server API-key principal (the Hive service account)
separate from the browser principal that owns the task.
"""

from __future__ import annotations

import hashlib
import hmac

WORKSPACE_ID_HEADER = "X-Maistro-Workspace-Id"
WORKSPACE_SCOPE_SIGNATURE_HEADER = "X-Maistro-Workspace-Signature"
TASK_OWNER_ID_HEADER = "X-Maistro-Task-Owner"
TASK_OWNER_SIGNATURE_HEADER = "X-Maistro-Task-Owner-Signature"
_SCOPE_SIGNATURE_DOMAIN = "maistro-workspace-scope:v1:"
_TASK_OWNER_SIGNATURE_DOMAIN = "maistro-task-owner:v1:"


def sign_workspace_scope(workspace_id: str, key: str) -> str:
    """Return the domain-separated HMAC-SHA256 proof for one Workspace binding."""
    message = f"{_SCOPE_SIGNATURE_DOMAIN}{workspace_id}"
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_workspace_scope_signature(workspace_id: str, signature: str, key: str) -> bool:
    """Verify a Workspace binding without timing-sensitive string comparison."""
    expected = sign_workspace_scope(workspace_id, key)
    return hmac.compare_digest(signature, expected)


def sign_task_owner(owner_id: str, key: str) -> str:
    """Return the proof for a Hive principal owning a task."""
    message = f"{_TASK_OWNER_SIGNATURE_DOMAIN}{owner_id}"
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_task_owner_signature(owner_id: str, signature: str, key: str) -> bool:
    """Verify a task-owner binding without timing-sensitive string comparison."""
    expected = sign_task_owner(owner_id, key)
    return hmac.compare_digest(signature, expected)


__all__ = [
    "TASK_OWNER_ID_HEADER",
    "TASK_OWNER_SIGNATURE_HEADER",
    "WORKSPACE_ID_HEADER",
    "WORKSPACE_SCOPE_SIGNATURE_HEADER",
    "sign_task_owner",
    "sign_workspace_scope",
    "verify_task_owner_signature",
    "verify_workspace_scope_signature",
]
