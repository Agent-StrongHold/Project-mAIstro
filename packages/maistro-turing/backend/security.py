"""Canonical inbound trust-boundary composition for the Turing backend.

This module only composes maistro-core security. It does not define a Turing
policy, detector vocabulary, or authorization decision. Parsed request values
and mapping keys are walked before FastAPI route code can consume them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from maistro.security._types import AuditEntry, WardenVerdict
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.warden.detector import Warden


@dataclass(frozen=True)
class TuringSecurityContext:
    """Non-secret correlation metadata for one inbound scan."""

    principal: str
    route: str
    action: str
    workspace_id: str = ""
    project_id: str = ""
    run_id: str = ""
    invocation_id: str = ""


class TuringInboundSecurity:
    """Use the canonical Warden and canonical audit record for Turing ingress."""

    def __init__(self, *, warden: Warden, audit_log: Any | None = None) -> None:
        if warden is None:
            raise RuntimeError("canonical Warden is required for Turing backend startup")
        self.warden = warden
        self.audit_log = audit_log if audit_log is not None else InMemoryAuditLog()

    @property
    def policy_version(self) -> str:
        version = getattr(self.warden, "policy_version", "")
        if not isinstance(version, str) or not version:
            raise RuntimeError("canonical Warden has no policy version")
        return version

    async def scan_text(
        self,
        content: str,
        *,
        boundary: str,
        context: TuringSecurityContext,
    ) -> WardenVerdict:
        try:
            verdict = await self.warden.scan(content, boundary)
        except Exception:
            # Warden itself normally fails closed. Keep the application closed
            # even if a replacement canonical implementation raises at ingress.
            verdict = WardenVerdict(
                clean=False,
                blocked=True,
                flags=("warden_unavailable",),
            )

        try:
            await self._audit(verdict, content, boundary=boundary, context=context)
        except Exception:
            # An unrecorded security verdict is not an auditable allow.
            return WardenVerdict(
                clean=False,
                blocked=True,
                flags=("security_audit_unavailable",),
            )
        return verdict

    async def scan_payload(
        self,
        payload: Any,
        *,
        boundary: str,
        context: TuringSecurityContext,
    ) -> WardenVerdict:
        """Scan consumed strings and attacker-controlled mapping keys in place.

        No serialization is used to create the scan representation: this keeps
        the values Warden sees identical to the values route code receives.
        """

        async def walk(value: Any) -> WardenVerdict:
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    key_verdict = await walk(str(key))
                    if not key_verdict.clean:
                        return key_verdict
                    nested_verdict = await walk(nested)
                    if not nested_verdict.clean:
                        return nested_verdict
                return WardenVerdict()
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                for nested in value:
                    nested_verdict = await walk(nested)
                    if not nested_verdict.clean:
                        return nested_verdict
                return WardenVerdict()
            if isinstance(value, str):
                return await self.scan_text(value, boundary=boundary, context=context)
            return WardenVerdict()

        return await walk(payload)

    async def audit_verdict(
        self,
        verdict: WardenVerdict,
        content: str,
        *,
        boundary: str,
        context: TuringSecurityContext,
    ) -> None:
        """Add correlation after canonical Run admission without rescanning."""
        await self._audit(verdict, content, boundary=boundary, context=context)

    async def _audit(
        self,
        verdict: WardenVerdict,
        content: str,
        *,
        boundary: str,
        context: TuringSecurityContext,
    ) -> None:
        await self.audit_log.log(
            AuditEntry(
                boundary=boundary,
                user_id=context.principal,
                agent_id="turing",
                verdict="allowed" if verdict.clean else "blocked",
                route=context.route,
                action=context.action,
                policy_version=self.policy_version,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                run_id=context.run_id,
                invocation_id=context.invocation_id,
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                content_length=len(content),
            )
        )


_PROTECTED_REQUESTS = {
    ("POST", "/v1/chat"): "chat",
    ("POST", "/v1/feed"): "feed.publish",
    ("PATCH", "/v1/admin/mood"): "admin.mood",
    ("PATCH", "/v1/admin/facet"): "admin.facet",
}


class TuringInboundSecurityMiddleware(BaseHTTPMiddleware):
    """Scan raw parsed request structures before route validation/consumption."""

    def __init__(self, app: object, security: TuringInboundSecurity) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        if security is None:
            raise RuntimeError("canonical Turing security is required")
        self._security = security

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        action = _PROTECTED_REQUESTS.get((request.method, request.url.path))
        if action is None:
            return await call_next(request)

        try:
            raw = await request.body()
            payload = json.loads(raw)
            principal = _principal(request)
            verdict = await self._security.scan_payload(
                payload,
                boundary="user_input",
                context=TuringSecurityContext(
                    principal=principal,
                    route=request.url.path,
                    action=action,
                ),
            )
        except Exception:
            # Malformed/unavailable security input is refused rather than
            # allowing FastAPI's later parsing or a replacement scanner to pass.
            return JSONResponse(status_code=400, content={"detail": "request refused by Warden"})

        request.state.turing_inbound_verdict = verdict
        if not verdict.clean:
            return JSONResponse(status_code=400, content={"detail": "request refused by Warden"})
        return await call_next(request)


def _principal(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    service = getattr(request.state, "service", None)
    name = getattr(service, "name", None)
    return str(name) if name else "unknown"
