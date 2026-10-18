"""The capabilities package root publishes the typed workflow-authority surface.

`ApprovalAuthority` and its sign/verify helpers are the canonical approval
vocabulary consumed by downstream products (hive-conductor's chat gate and
approval routes import them). They are re-exported from the package root so
the public API is importable as `from maistro.capabilities import ...`; this
test pins that surface so it cannot silently regress (e.g. an `__all__` prune
would reintroduce unbanked public-API vulture debt on the exact-debt-ledger
gate, since the consuming product lives outside the `packages/*/src` scan
glob).
"""

from __future__ import annotations


def test_authority_surface_importable_from_package_root() -> None:
    from maistro.capabilities import (
        ApprovalAuthority,
        approval_signing_secret,
        sign_approval_authority,
        verify_approval_authority,
    )

    authority = ApprovalAuthority(
        kind="human",
        principal="principal-1",
        scope="run_workflow",
        evidence_id="request-1",
    )
    signature = sign_approval_authority(authority, approval_signing_secret())
    signed = ApprovalAuthority(
        kind="human",
        principal="principal-1",
        scope="run_workflow",
        evidence_id="request-1",
        signature=signature,
    )
    assert verify_approval_authority(signed, approval_signing_secret())


def test_verify_approval_authority_fails_closed_without_secret_or_signature() -> None:
    """Either half of the HMAC pair missing means the authority proves nothing."""

    from maistro.capabilities import (
        ApprovalAuthority,
        approval_signing_secret,
        sign_approval_authority,
        verify_approval_authority,
    )

    unsigned = ApprovalAuthority(
        kind="human",
        principal="principal-1",
        scope="run_workflow",
        evidence_id="request-1",
    )
    secret = approval_signing_secret()
    signed = ApprovalAuthority(
        kind="human",
        principal="principal-1",
        scope="run_workflow",
        evidence_id="request-1",
        signature=sign_approval_authority(unsigned, secret),
    )

    # A signature verified without the deployment secret proves nothing.
    assert verify_approval_authority(signed, "") is False
    # A deployment secret cannot vouch for an unsigned authority.
    assert verify_approval_authority(unsigned, secret) is False


def test_all_publishes_authority_names() -> None:
    import maistro.capabilities as capabilities

    for name in (
        "ApprovalAuthority",
        "approval_signing_secret",
        "sign_approval_authority",
        "verify_approval_authority",
    ):
        assert name in capabilities.__all__
        assert getattr(capabilities, name) is not None
