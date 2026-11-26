"""Promotion gate (#302): quarantine + signed approval before RSI promotion.

Unit tests for `maistro_rsi.promotion_gate` — the one canonical boundary every
promotion crosses before the baseline may move. Fail-closed semantics:
denial, expiry, an unavailable source, malformed evidence, and binding
mismatches each refuse the promotion.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maistro.security._types import WardenVerdict
from maistro_rsi.promotion_gate import (
    APPROVAL_POLICY_VERSION,
    DirectoryApprovalStore,
    PromotionGateVerdict,
    SignedPromotionApproval,
    approval_signing_secret,
    diff_sha256,
    evaluate_promotion,
    promotion_scope,
    sign_promotion_approval,
    verify_promotion_approval,
)
from maistro_rsi.quarantine import _touches_sensitive_surface
from maistro_rsi.sensitive_paths import SENSITIVE_PATH_POLICY_VERSION

SECRET = "unit-test-signing-secret"

ORDINARY_PATHS = ["packages/maistro-core/src/maistro/agents/base.py"]
SENSITIVE_PATHS = ["packages/maistro-rsi/src/maistro_rsi/local_loop.py", "README.md"]


class FakeWarden:
    def __init__(self, verdict: WardenVerdict) -> None:
        self._verdict = verdict
        self.calls: list[tuple[str, str]] = []

    async def scan(self, content: str, boundary: str = "default"):
        self.calls.append((content, boundary))
        return self._verdict


class FakeReview:
    def __init__(self, approve: bool) -> None:
        self.approve = approve
        self.calls: list[tuple[str, list[str]]] = []

    async def review(self, diff: str, touched_paths: list[str]) -> bool:
        self.calls.append((diff, touched_paths))
        return self.approve


def _approval(
    *,
    candidate_sha: str = "a" * 40,
    diff_text: str = "+x\n",
    scope: str = "/repo#rsi-baseline",
    approver: str = "op-1",
    policy_version: str = SENSITIVE_PATH_POLICY_VERSION,
    expires_at: str | None = None,
    secret: str | None = SECRET,
) -> SignedPromotionApproval:
    approval = SignedPromotionApproval(
        candidate_sha=candidate_sha,
        diff_sha256=diff_sha256(diff_text),
        scope=scope,
        approver=approver,
        policy_version=policy_version,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    if secret is not None:
        approval = replace(approval, signature=sign_promotion_approval(approval, secret))
    return approval


def _clean_warden() -> FakeWarden:
    return FakeWarden(WardenVerdict(clean=True))


async def _evaluate(**kwargs: object) -> PromotionGateVerdict:
    params: dict[str, object] = {
        "diff": "+x\n",
        "touched_paths": list(ORDINARY_PATHS),
        "candidate_sha": "a" * 40,
        "scope": "/repo#rsi-baseline",
        "warden": _clean_warden(),
        "signing_secret": SECRET,
    }
    params.update(kwargs)
    return await evaluate_promotion(**params)  # type: ignore[arg-type]


class TestSigning:
    def test_policy_version_alias_tracks_the_classifier(self) -> None:
        """One source of the version: the approval policy IS the classifier's."""
        assert APPROVAL_POLICY_VERSION == SENSITIVE_PATH_POLICY_VERSION

    def test_verify_accepts_a_well_signed_approval(self) -> None:
        valid, reason = verify_promotion_approval(_approval(), SECRET)
        assert valid and reason == ""

    def test_verify_rejects_a_tampered_record(self) -> None:
        approval = _approval()
        tampered = replace(approval, approver="someone-else")
        valid, reason = verify_promotion_approval(tampered, SECRET)
        assert not valid
        assert reason == "signature_mismatch"

    def test_verify_rejects_malformed_fields(self) -> None:
        for field in (
            "candidate_sha",
            "diff_sha256",
            "scope",
            "approver",
            "policy_version",
            "expires_at",
            "signature",
        ):
            approval = replace(_approval(), **{field: ""})
            valid, reason = verify_promotion_approval(approval, SECRET)
            assert not valid
            assert reason == f"malformed_approval:{field}"

    def test_verify_rejects_wrong_policy_version(self) -> None:
        valid, reason = verify_promotion_approval(
            _approval(policy_version="rsi-sensitive-paths-v0"), SECRET
        )
        assert not valid
        assert reason == "policy_version_mismatch"

    def test_verify_rejects_expired_approval(self) -> None:
        past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        valid, reason = verify_promotion_approval(_approval(expires_at=past), SECRET)
        assert not valid
        assert reason == "approval_expired"

    def test_verify_rejects_malformed_expiry(self) -> None:
        valid, reason = verify_promotion_approval(_approval(expires_at="not-a-time"), SECRET)
        assert not valid
        assert reason == "malformed_expiry"

    def test_verify_rejects_unsigned(self) -> None:
        valid, reason = verify_promotion_approval(_approval(secret=None), SECRET)
        assert not valid
        # An empty signature is caught as malformed evidence (there is nothing
        # to verify) — either way, no signature is no authority.
        assert reason == "malformed_approval:signature"

    def test_verify_fails_closed_on_missing_secret(self) -> None:
        valid, reason = verify_promotion_approval(_approval(), "")
        assert not valid
        # No secret means the signature cannot be authenticated — refused.
        assert reason == "unsigned"


class TestGate:
    def test_sensitive_paths_classifier_matches_promotion_modules(self) -> None:
        assert _touches_sensitive_surface(["packages/maistro-rsi/src/maistro_rsi/local_loop.py"])

    @pytest.mark.asyncio
    async def test_clean_ordinary_diff_clears_without_approval(self) -> None:
        verdict = await _evaluate()
        assert verdict.cleared
        assert not verdict.requires_approval
        assert verdict.approval is None

    @pytest.mark.asyncio
    async def test_warden_flagged_diff_never_clears(self) -> None:
        verdict = await _evaluate(
            warden=FakeWarden(WardenVerdict(clean=False, flags=("secret_leak",)))
        )
        assert not verdict.cleared
        assert verdict.reason == "warden_flagged_diff"
        assert "secret_leak" in verdict.flags

    @pytest.mark.asyncio
    async def test_sensitive_diff_with_no_reviewer_and_no_provider_refuses(self) -> None:
        """Default posture: a sensitive candidate parks — baseline unchanged.
        With no reviewer supplied, quarantine itself refuses first (pending
        review), which is the same fail-closed outcome."""
        verdict = await _evaluate(touched_paths=list(SENSITIVE_PATHS))
        assert not verdict.cleared
        assert verdict.requires_approval
        assert verdict.reason is not None
        assert verdict.reason.startswith("sensitive_surface_pending_review")

    @pytest.mark.asyncio
    async def test_sensitive_diff_with_review_but_no_approval_provider_refuses(self) -> None:
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
        )
        assert not verdict.cleared
        assert verdict.reason == "approval_required:no_source"

    @pytest.mark.asyncio
    async def test_sensitive_diff_with_provider_but_no_record_refuses(self) -> None:
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
            approval_provider=lambda *a: None,
        )
        assert not verdict.cleared
        assert verdict.reason == "approval_required:none_found"

    @pytest.mark.asyncio
    async def test_sensitive_diff_with_crashing_provider_refuses(self) -> None:
        def boom(*a: object) -> SignedPromotionApproval:
            raise RuntimeError("approval service down")

        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
            approval_provider=boom,
        )
        assert not verdict.cleared
        assert verdict.reason == "approval_unavailable:RuntimeError"

    @pytest.mark.asyncio
    async def test_expired_approval_refuses(self) -> None:
        """The signed record exists — but past expiry it is no authority."""
        approval = _approval(expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
            approval_provider=lambda *a: approval,
        )
        assert not verdict.cleared
        assert verdict.reason == "approval_invalid:approval_expired"

    @pytest.mark.asyncio
    async def test_wrongly_bound_approval_refuses(self) -> None:
        """A valid approval for ANOTHER candidate/diff/scope authorizes nothing."""
        approval = _approval(candidate_sha="b" * 40, scope="/other-repo#main")
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
            approval_provider=lambda *a: approval,
        )
        assert not verdict.cleared
        assert verdict.reason == "approval_binding_mismatch"

    @pytest.mark.asyncio
    async def test_adversarial_review_denial_refuses_a_sensitive_candidate(self) -> None:
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=False),
            approval_provider=lambda *a: _approval(),
        )
        assert not verdict.cleared
        assert verdict.reason == "adversarial_review_rejected"

    @pytest.mark.asyncio
    async def test_valid_review_and_approval_clears_with_provenance(self) -> None:
        approval = _approval()
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
            approval_provider=lambda *a: approval,
        )
        assert verdict.cleared
        assert verdict.requires_approval
        assert verdict.approval is not None
        assert verdict.approval["approver"] == "op-1"
        assert verdict.approval["policy_version"] == SENSITIVE_PATH_POLICY_VERSION

    @pytest.mark.asyncio
    async def test_ordinary_diff_clears_even_when_approval_source_exists(self) -> None:
        """Approval is required only for sensitive surface — the classifier
        decides, not the provider's existence and not a candidate boolean."""
        verdict = await _evaluate(approval_provider=lambda *a: _approval())
        assert verdict.cleared
        assert not verdict.requires_approval


class TestDirectoryApprovalStore:
    def test_missing_file_is_no_evidence(self, tmp_path: Path) -> None:
        store = DirectoryApprovalStore(tmp_path)
        assert store("a" * 40, diff_sha256("+x\n"), "/repo#rsi-baseline") is None

    def test_malformed_file_is_no_evidence(self, tmp_path: Path) -> None:
        (tmp_path / "aaaaaaaaaaaa.approval.json").write_text("{not json", encoding="utf-8")
        store = DirectoryApprovalStore(tmp_path)
        assert store("a" * 40, diff_sha256("+x\n"), "/repo#rsi-baseline") is None

    def test_pre_signed_record_round_trips(self, tmp_path: Path) -> None:
        approval = _approval(candidate_sha="a" * 40)
        (tmp_path / "aaaaaaaaaaaa.approval.json").write_text(
            json.dumps(asdict(approval)), encoding="utf-8"
        )
        store = DirectoryApprovalStore(tmp_path)
        loaded = store("a" * 40, approval.diff_sha256, approval.scope)
        assert loaded == approval
        valid, reason = verify_promotion_approval(loaded, SECRET)
        assert valid and reason == ""


class TestScopeAndSecret:
    def test_scope_binds_repo_and_branch(self) -> None:
        assert promotion_scope("/repo", "rsi-baseline").endswith("#rsi-baseline")

    def test_secret_has_process_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RSI_PROMOTION_APPROVAL_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("CONDUCTOR_APPROVAL_SIGNING_SECRET", raising=False)
        assert approval_signing_secret()


class TestFailClosedEdges:
    def test_naive_expiry_is_interpreted_as_utc_and_can_expire(self) -> None:
        past = (datetime.now(UTC) - timedelta(seconds=1)).replace(tzinfo=None).isoformat()
        valid, reason = verify_promotion_approval(_approval(expires_at=past), SECRET)
        assert not valid
        assert reason == "approval_expired"

    def test_store_record_missing_a_field_is_no_evidence(self, tmp_path: Path) -> None:
        (tmp_path / "aaaaaaaaaaaa.approval.json").write_text(
            json.dumps({"candidate_sha": "a" * 40}),  # no diff/scope/approver/...
            encoding="utf-8",
        )
        store = DirectoryApprovalStore(tmp_path)
        assert store("a" * 40, diff_sha256("+x\n"), "/repo#rsi-baseline") is None

    @pytest.mark.asyncio
    async def test_dict_record_with_bad_shape_is_malformed_not_approval(self) -> None:
        verdict = await _evaluate(
            touched_paths=list(SENSITIVE_PATHS),
            adversarial_review=FakeReview(approve=True),
            approval_provider=lambda *a: {"candidate_sha": "a" * 40},  # missing fields
        )
        assert not verdict.cleared
        assert verdict.reason == "approval_invalid:malformed_approval"
