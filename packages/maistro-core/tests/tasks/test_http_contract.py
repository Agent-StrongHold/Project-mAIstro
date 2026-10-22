"""Task admission scope HTTP contract coverage (#234).

The fail-closed guards (#1057) get their own tests: every malformed or
hostile delegation envelope must be refused by the *verification* side, not
merely unsigned by the signing side, because a malicious client crafts
envelopes directly rather than going through `sign_delegation_context`.
"""

import base64
import hashlib
import hmac
import json

import pytest

from maistro.tasks.http_contract import (
    _DELEGATION_DOMAIN,
    DELEGATION_HEADER,
    _encode_delegation_payload,
    sign_delegation_context,
    sign_workspace_scope,
    verify_delegation_context,
    verify_workspace_scope_signature,
)


def _forged_token(payload: dict[str, object], key: str = "bridge-key") -> str:
    """Build an envelope the way a hostile client would: encode any claims,
    sign with a known key, never touch the signing helper's validation."""
    encoded = _encode_delegation_payload(payload)
    signature = hmac.new(
        key.encode("utf-8"), f"{_DELEGATION_DOMAIN}.{encoded}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def test_delegation_context_preserves_service_and_originating_principals() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="alice",
        key="bridge-key",
        now=100,
        delegation_id="stable-evidence",
    )

    context = verify_delegation_context(token, "bridge-key", now=120)

    assert context.service_principal == "conductor"
    assert context.originating_principal == "alice"
    assert context.delegation_id == "stable-evidence"
    assert context.expires_at == 400


def test_delegation_context_rejects_tampering_wrong_key_and_expiry() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="alice",
        key="bridge-key",
        now=100,
    )

    with pytest.raises(ValueError):
        verify_delegation_context(token + "x", "bridge-key", now=100)
    with pytest.raises(ValueError):
        verify_delegation_context(token, "wrong-key", now=100)
    with pytest.raises(ValueError, match="expired"):
        verify_delegation_context(token, "bridge-key", now=401)


def test_an_envelope_that_is_not_two_parts_is_refused() -> None:
    with pytest.raises(ValueError, match="envelope"):
        verify_delegation_context("no-signature-here", "bridge-key", now=100)
    with pytest.raises(ValueError, match="envelope"):
        verify_delegation_context("a.b.c", "bridge-key", now=100)


def _forged_raw(payload_bytes: bytes, key: str = "bridge-key") -> str:
    """A validly signed envelope whose payload is not JSON at all."""
    encoded = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(
        key.encode("utf-8"), f"{_DELEGATION_DOMAIN}.{encoded}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def test_an_envelope_with_unreadable_payload_is_refused() -> None:
    with pytest.raises(ValueError, match="envelope"):
        verify_delegation_context(_forged_raw(b"\x00\x01\x02"), "bridge-key", now=100)
    raw = base64.urlsafe_b64encode(b"[not-an-object]").decode("ascii").rstrip("=")
    signature = hmac.new(
        b"bridge-key",
        f"{_DELEGATION_DOMAIN}.{raw}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    with pytest.raises(ValueError, match="envelope"):
        verify_delegation_context(f"{raw}.{signature}", "bridge-key", now=100)


def test_the_signer_refuses_empty_principals_and_missing_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        sign_delegation_context(
            service_principal=" ", originating_principal="alice", key="bridge-key"
        )
    with pytest.raises(ValueError, match="non-empty"):
        sign_delegation_context(
            service_principal="conductor", originating_principal="", key="bridge-key"
        )
    with pytest.raises(ValueError, match="key"):
        sign_delegation_context(
            service_principal="conductor", originating_principal="alice", key=""
        )


def test_the_signer_refuses_system_kind_claiming_a_named_user() -> None:
    with pytest.raises(ValueError, match="system"):
        sign_delegation_context(
            service_principal="conductor",
            originating_principal="alice",
            principal_kind="system",
            key="bridge-key",
        )


def test_the_signer_refuses_an_out_of_range_ttl() -> None:
    for ttl in (0, -5, 3601):
        with pytest.raises(ValueError, match="ttl"):
            sign_delegation_context(
                service_principal="conductor",
                originating_principal="alice",
                key="bridge-key",
                ttl_seconds=ttl,
            )


def test_a_claiming_system_kind_for_a_named_user_is_refused_at_verification() -> None:
    """The signer refuses this shape; a forger bypasses the signer, so the
    verifier must refuse it too."""
    token = _forged_token(
        {
            "aud": "maistro-server",
            "exp": 400,
            "iat": 100,
            "jti": "forged-1",
            "kind": "system",
            "service": "conductor",
            "sub": "alice",
            "v": 1,
        }
    )
    with pytest.raises(ValueError, match="system"):
        verify_delegation_context(token, "bridge-key", now=100)


def test_an_unknown_principal_kind_is_refused_at_verification() -> None:
    token = _forged_token(
        {
            "aud": "maistro-server",
            "exp": 400,
            "iat": 100,
            "jti": "forged-1",
            "kind": "admin",
            "service": "conductor",
            "sub": "alice",
            "v": 1,
        }
    )
    with pytest.raises(ValueError, match="kind"):
        verify_delegation_context(token, "bridge-key", now=100)


def test_an_envelope_missing_required_claims_is_refused() -> None:
    base = {
        "aud": "maistro-server",
        "exp": 400,
        "iat": 100,
        "jti": "forged-1",
        "kind": "user",
        "service": "conductor",
        "sub": "alice",
        "v": 1,
    }
    for claim in ("service", "sub", "jti"):
        broken = dict(base)
        del broken[claim]
        with pytest.raises(ValueError, match="claims"):
            verify_delegation_context(_forged_token(broken), "bridge-key", now=100)
    for claim in ("iat", "exp"):
        broken = dict(base)
        broken[claim] = "not-a-number"
        with pytest.raises(ValueError, match="timestamps"):
            verify_delegation_context(_forged_token(broken), "bridge-key", now=100)


def test_an_envelope_with_the_wrong_version_or_audience_is_refused() -> None:
    token = sign_delegation_context(
        service_principal="conductor", originating_principal="alice", key="bridge-key", now=100
    )
    encoded = token.split(".")[0]
    padding = "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode((encoded + padding).encode("ascii")))
    for claim, value in (("v", 2), ("aud", "other-service")):
        broken = dict(payload)
        broken[claim] = value
        with pytest.raises(ValueError, match="audience or version"):
            verify_delegation_context(_forged_token(broken), "bridge-key", now=100)


def test_an_envelope_valid_before_its_skew_window_is_refused() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="alice",
        key="bridge-key",
        now=1000,
    )
    # 1000 - 100 is far past the 30s clock-skew allowance.
    with pytest.raises(ValueError, match="not yet valid"):
        verify_delegation_context(token, "bridge-key", now=100)


def test_an_envelope_with_an_over_long_lifetime_is_refused_at_verification() -> None:
    """The signer caps ttl at 3600s; a forger mints a longer one directly."""
    token = _forged_token(
        {
            "aud": "maistro-server",
            "exp": 10000,
            "iat": 100,
            "jti": "forged-1",
            "kind": "user",
            "service": "conductor",
            "sub": "alice",
            "v": 1,
        }
    )
    with pytest.raises(ValueError, match="lifetime"):
        verify_delegation_context(token, "bridge-key", now=100)


def test_an_inverted_lifetime_is_refused_at_verification() -> None:
    token = _forged_token(
        {
            "aud": "maistro-server",
            "exp": 100,
            "iat": 100,
            "jti": "forged-1",
            "kind": "user",
            "service": "conductor",
            "sub": "alice",
            "v": 1,
        }
    )
    with pytest.raises(ValueError, match="lifetime"):
        verify_delegation_context(token, "bridge-key", now=100)


def test_the_delegation_header_name_stays_stable() -> None:
    """Conductor and maistro-server must agree on the wire name; this pins it."""
    assert DELEGATION_HEADER == "X-Maistro-Delegation"


def test_system_delegation_has_an_explicit_system_actor() -> None:
    token = sign_delegation_context(
        service_principal="conductor",
        originating_principal="system",
        principal_kind="system",
        key="bridge-key",
        now=100,
    )

    assert verify_delegation_context(token, "bridge-key", now=100).principal_kind == "system"


def test_workspace_scope_signature_is_bound_to_workspace_and_key() -> None:
    signature = sign_workspace_scope("workspace-a", "key-a")

    assert verify_workspace_scope_signature("workspace-a", signature, "key-a")
    assert not verify_workspace_scope_signature("workspace-b", signature, "key-a")
    assert not verify_workspace_scope_signature("workspace-a", signature, "key-b")
