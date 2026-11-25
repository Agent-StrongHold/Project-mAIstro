"""The canonical quarantine + signed-approval boundary for RSI promotion (#302).

`quarantine.py` already decides whether a self-modification *diff* may leave
the sandbox — but the internal promotion path (`LocalRsiLoop._run_cycle`)
fast-forwarded `rsi-baseline` without ever consulting it, so a candidate could
reach the baseline on test-passing alone. This module is the ONE gate every
promotion crosses before the baseline may move, composing:

1. **Quarantine** (`quarantine_scan`): Warden over the full diff, plus the
   sensitive-path classifier (`sensitive_paths.py`) over the touched paths.
   A Warden-flagged diff never clears; a diff touching the agent's own
   containment surface needs an adversarial review pass on top.
2. **Signed approval**: sensitive-surface candidates additionally require an
   approval record that
   - already exists before promotion (it is supplied, not minted by the loop),
   - is cryptographically bound to the candidate commit sha, the diff sha256,
     the promotion scope, the approver identity, the sensitive-path policy
     version, and an expiry,
   - verifies against a deployment signing secret.

   The signature itself is produced and checked by the canonical approval-
   evidence seam (``maistro.capabilities.authority``) — ADR-090726 makes the
   RSI promotion decision a delegated-approval shape and requires it to extend
   the existing seams rather than introduce a parallel authorization path — so
   the crypto here is the repo's, not a second implementation of it.

Fail-closed throughout: a missing reviewer, an unavailable approval source, a
malformed record, an expired one, a signature mismatch, a binding mismatch
(candidate/diff/scope), a Warden flag, or a sensitive-path hit each leaves the
baseline untouched. Nothing here trusts a model-populated boolean: whether
approval is required is decided ONLY by `matches_sensitive_pattern` over the
diff's real paths — deterministic string work, not a candidate-controlled bit.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maistro.capabilities.authority import (
    ApprovalAuthority,
    sign_approval_authority,
    verify_approval_authority,
)
from maistro.capabilities.authority import (
    approval_signing_secret as _canonical_approval_signing_secret,
)
from maistro_rsi.quarantine import (
    AdversarialReview,
    QuarantineVerdict,
    _touches_sensitive_surface,
    quarantine_scan,
)
from maistro_rsi.sensitive_paths import SENSITIVE_PATH_POLICY_VERSION

__all__ = [
    "APPROVAL_POLICY_VERSION",
    "DirectoryApprovalStore",
    "PromotionGateVerdict",
    "SignedPromotionApproval",
    "approval_signing_secret",
    "diff_sha256",
    "evaluate_promotion",
    "promotion_scope",
    "sign_promotion_approval",
    "verify_promotion_approval",
]

#: The policy version an approval must carry. Aliased from the classifier so
#: there is exactly one source of the version — an approval minted under a
#: stale/weaker sensitive-path policy can never authorize a promotion under
#: this one.
APPROVAL_POLICY_VERSION = SENSITIVE_PATH_POLICY_VERSION


def approval_signing_secret() -> str:
    """The deployment signing secret, or an ephemeral process key for local mode.

    The secret itself comes from the canonical approval-evidence seam
    (``maistro.capabilities.authority``), so there is ONE secret policy for
    approvals in this codebase — an approval signed under the Conductor's key
    is the same kind of evidence here as it is there. The RSI-scoped
    environment variable is an override for a deployment that signs promotions
    with a different key than it signs capability approvals with.
    """
    secret = os.environ.get("RSI_PROMOTION_APPROVAL_SIGNING_SECRET")
    if secret:
        return secret
    return _canonical_approval_signing_secret()


def promotion_scope(repo_path: str, baseline_branch: str) -> str:
    """The scope a promotion (and its approval) is bound to: the repository the
    loop may touch, resolved, plus the branch it promotes onto. An approval
    minted for another repo or another branch does not authorize this one."""
    return f"{Path(repo_path).resolve()}#{baseline_branch}"


def diff_sha256(diff: str) -> str:
    """The diff's content digest — the approval's second binding."""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SignedPromotionApproval:
    """A cryptographically signed human approval for one sensitive promotion.

    Every field is a binding: verification recomputes the signature over all
    of them, so nothing can be edited after signing. ``signature`` is the
    HMAC-SHA256 of the canonical payload under the deployment secret.
    """

    candidate_sha: str
    diff_sha256: str
    scope: str
    approver: str
    policy_version: str
    expires_at: str  # ISO-8601 UTC; verification treats it as a hard deadline
    signature: str = ""


def _authority_for(approval: SignedPromotionApproval) -> ApprovalAuthority:
    """The canonical authority record for one RSI promotion approval.

    ADR-090726 ("RSI promotion — the promotion decision is a delegated-approval
    shape") puts the typed evidence for such a decision in
    ``maestro.capabilities.authority``, and says explicitly that it is an
    extension of the existing seams rather than a parallel system. This maps
    the RSI-specific bindings onto that record: the approver identity and the
    promotion scope stay first-class fields, and the remaining bindings
    (candidate sha, diff digest, policy version, expiry) become the
    ``evidence_id`` digest — so the canonical signature covers every one of
    them, and swapping any field after signing breaks verification.
    """
    bindings = json.dumps(
        {
            "candidate_sha": approval.candidate_sha,
            "diff_sha256": approval.diff_sha256,
            "policy_version": approval.policy_version,
            "expires_at": approval.expires_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ApprovalAuthority(
        kind="delegated",
        principal=approval.approver,
        scope=approval.scope,
        evidence_id=hashlib.sha256(bindings).hexdigest(),
        signature=approval.signature,
    )


def sign_promotion_approval(approval: SignedPromotionApproval, secret: str) -> str:
    """Sign an approval without exposing the secret to any candidate."""
    return sign_approval_authority(_authority_for(approval), secret)


_REQUIRED_FIELDS = (
    "candidate_sha",
    "diff_sha256",
    "scope",
    "approver",
    "policy_version",
    "expires_at",
    "signature",
)


def verify_promotion_approval(
    approval: SignedPromotionApproval,
    secret: str,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Verify an approval's bindings. Returns ``(valid, reason)``.

    Fails closed on: a non-string/empty field (malformed evidence), an
    unparsable expiry, a wrong policy version, an expired approval, a missing
    secret or signature, and a signature mismatch. Binding to the *actual*
    candidate/diff/scope is checked by the caller (`evaluate_promotion`), which
    holds those live values; this function verifies the record is internally
    sound and authentic.
    """
    for name in _REQUIRED_FIELDS:
        value = getattr(approval, name, None)
        if not isinstance(value, str) or not value:
            return False, f"malformed_approval:{name}"
    if approval.policy_version != APPROVAL_POLICY_VERSION:
        return False, "policy_version_mismatch"
    try:
        expiry = datetime.fromisoformat(approval.expires_at)
    except ValueError:
        return False, "malformed_expiry"
    current = now or datetime.now(UTC)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry <= current:
        return False, "approval_expired"
    if not secret or not approval.signature:
        return False, "unsigned"
    if not verify_approval_authority(_authority_for(approval), secret):
        return False, "signature_mismatch"
    return True, ""


ApprovalProvider = Callable[[str, str, str], "SignedPromotionApproval | None"]


class DirectoryApprovalStore:
    """An on-disk approval source the operator provisions BEFORE a run.

    Each pre-signed approval lives as ``<candidate_sha[:12]>.approval.json`` —
    the canonical JSON of a `SignedPromotionApproval` — under ``root``. The
    loop consults this store at promotion time; nothing in the loop can mint
    or edit an approval, so "exists before promotion" holds by construction.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def __call__(self, candidate_sha: str, diff: str, scope: str) -> SignedPromotionApproval | None:
        meta = self._root / f"{candidate_sha[:12]}.approval.json"
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # absent or unreadable evidence is NO evidence
        try:
            return SignedPromotionApproval(
                candidate_sha=str(data["candidate_sha"]),
                diff_sha256=str(data["diff_sha256"]),
                scope=str(data["scope"]),
                approver=str(data["approver"]),
                policy_version=str(data["policy_version"]),
                expires_at=str(data["expires_at"]),
                signature=str(data["signature"]),
            )
        except (KeyError, TypeError):
            return None  # malformed record is NO evidence (fail closed)


@dataclass(frozen=True)
class PromotionGateVerdict:
    """The promotion gate's outcome, with the evidence a promotion record
    carries for independent audit."""

    cleared: bool
    requires_approval: bool
    sensitive_paths: tuple[str, ...] = ()
    reason: str | None = None
    flags: tuple[str, ...] = ()
    # Provenance of the approval that authorized a sensitive promotion
    # (approver, both shas, policy version, expiry, signature) — persisted onto
    # the promotion's trace note so the audit trail names WHO authorized it.
    approval: dict[str, Any] | None = None


async def evaluate_promotion(
    *,
    diff: str,
    touched_paths: list[str],
    candidate_sha: str,
    scope: str,
    warden: Any,
    adversarial_review: AdversarialReview | None = None,
    approval_provider: ApprovalProvider | None = None,
    signing_secret: str | None = None,
    now: datetime | None = None,
) -> PromotionGateVerdict:
    """One canonical gate: quarantine, then (for sensitive diffs) signed approval.

    ``candidate_sha`` is the promote branch's tip commit and ``scope`` the
    promotion scope (`promotion_scope`); a valid approval must bind to both and
    to the ``diff`` digest. ``now`` is injectable for expiry tests.
    """
    quarantine: QuarantineVerdict = await quarantine_scan(
        diff, touched_paths, warden, adversarial_review=adversarial_review
    )
    sensitive = tuple(_touches_sensitive_surface(touched_paths))

    if not quarantine.cleared:
        return PromotionGateVerdict(
            cleared=False,
            requires_approval=bool(sensitive),
            sensitive_paths=sensitive,
            reason=quarantine.reason or "warden_flagged_diff",
            flags=quarantine.flags,
        )

    if not sensitive:
        return PromotionGateVerdict(
            cleared=True,
            requires_approval=False,
            flags=quarantine.flags,
        )

    # Sensitive surface: approval is required — decided by the classifier over
    # the real paths, never by anything a candidate or model produced.
    if approval_provider is None:
        return PromotionGateVerdict(
            cleared=False,
            requires_approval=True,
            sensitive_paths=sensitive,
            reason="approval_required:no_source",
            flags=quarantine.flags,
        )

    digest = diff_sha256(diff)
    try:
        approval = approval_provider(candidate_sha, digest, scope)
    except Exception as exc:
        # An approval source that errors is UNAVAILABLE, not approving.
        return PromotionGateVerdict(
            cleared=False,
            requires_approval=True,
            sensitive_paths=sensitive,
            reason=f"approval_unavailable:{type(exc).__name__}",
            flags=quarantine.flags,
        )

    if isinstance(approval, dict):
        # A JSON-shaped record (an HTTP approval service, a pre-staged file)
        # coerces to the typed record; a record missing/wrongly-typing a field
        # is MALFORMED EVIDENCE, never approval.
        try:
            approval = SignedPromotionApproval(**approval)
        except (TypeError, ValueError):
            return PromotionGateVerdict(
                cleared=False,
                requires_approval=True,
                sensitive_paths=sensitive,
                reason="approval_invalid:malformed_approval",
                flags=quarantine.flags,
            )

    if approval is None:
        return PromotionGateVerdict(
            cleared=False,
            requires_approval=True,
            sensitive_paths=sensitive,
            reason="approval_required:none_found",
            flags=quarantine.flags,
        )

    valid, reason = verify_promotion_approval(
        approval, signing_secret or approval_signing_secret(), now=now
    )
    if not valid:
        return PromotionGateVerdict(
            cleared=False,
            requires_approval=True,
            sensitive_paths=sensitive,
            reason=f"approval_invalid:{reason}",
            flags=quarantine.flags,
        )

    # The record must bind to THIS candidate, THIS diff and THIS scope — a
    # validly-signed approval for a different change authorizes nothing here.
    if (
        approval.candidate_sha != candidate_sha
        or approval.diff_sha256 != digest
        or approval.scope != scope
    ):
        return PromotionGateVerdict(
            cleared=False,
            requires_approval=True,
            sensitive_paths=sensitive,
            reason="approval_binding_mismatch",
            flags=quarantine.flags,
        )

    return PromotionGateVerdict(
        cleared=True,
        requires_approval=True,
        sensitive_paths=sensitive,
        flags=quarantine.flags,
        approval=asdict(approval),
    )
