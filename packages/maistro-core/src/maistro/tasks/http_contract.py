"""Shared HTTP contract for task admission scope.

Workspace scope is an admission binding, not part of ``TaskCreate``.  The
Conductor therefore carries an already-authorized Workspace across the
server-to-server boundary in a dedicated header, and maistro-server passes that
binding to the canonical ``WorkspaceRoutingAdmitter``.
"""

from __future__ import annotations

WORKSPACE_ID_HEADER = "X-Maistro-Workspace-Id"

__all__ = ["WORKSPACE_ID_HEADER"]
