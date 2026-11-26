"""Typed authority evidence for capability approvals.

Approval providers may expose a human-facing resolver, but an actor string is
not authority.  The typed evidence below lets a policy boundary distinguish a
verified human decision from an untrusted provider-shaped value while keeping
workflow scope bound to one approval request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from typing import Literal

_PROCESS_APPROVAL_SECRET = secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ApprovalAuthority:
    """Authority bound to one approval request and one effect scope."""

    kind: Literal["human", "delegated"]
    principal: str
    scope: str
    evidence_id: str
    signature: str = ""


def _authority_payload(authority: ApprovalAuthority) -> bytes:
    return json.dumps(
        {
            "kind": authority.kind,
            "principal": authority.principal,
            "scope": authority.scope,
            "evidence_id": authority.evidence_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def approval_signing_secret() -> str:
    """Return the deployment key, or an ephemeral process key for local mode."""
    return os.environ.get("CONDUCTOR_APPROVAL_SIGNING_SECRET", _PROCESS_APPROVAL_SECRET)


def sign_approval_authority(authority: ApprovalAuthority, secret: str) -> str:
    """Sign authority evidence without exposing the secret to the model."""
    return hmac.new(
        secret.encode("utf-8"), _authority_payload(authority), hashlib.sha256
    ).hexdigest()


def verify_approval_authority(authority: ApprovalAuthority, secret: str) -> bool:
    """Verify cryptographically signed human or delegated authority."""
    if not secret or not authority.signature:
        return False
    expected = sign_approval_authority(authority, secret)
    return hmac.compare_digest(expected, authority.signature)
