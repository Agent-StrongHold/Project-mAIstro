"""Tests for maistro.identity.lifecycle (ADR-084 / SPEC-070226-6489)."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("bip_utils")
pytest.importorskip("nacl")

from hypothesis import given, settings
from hypothesis import strategies as st

from maistro.identity import ConductorSeed
from maistro.identity.lifecycle import (
    CapabilityToken,
    CapabilityTokenError,
    IdentityAlreadyExistsError,
    IdentityArchivedError,
    IdentityLifecycleError,
    IdentityNotFoundError,
    InMemoryIdentityStore,
    InMemorySecretStore,
    InMemoryTokenStore,
    InvalidRecoverySeedError,
    InvalidTokenSignatureError,
    TokenExpiredError,
    TokenRevokedError,
    create_agent_identity,
    did_key_from_public_key,
    issue_capability_token,
    offboard_agent,
    public_key_from_did_key,
    recover_agent_identity,
    verify_capability_token,
)


class Env:
    """Wired in-memory stores for one lifecycle scenario."""

    def __init__(self) -> None:
        self.identities = InMemoryIdentityStore()
        self.tokens = InMemoryTokenStore()
        self.secrets = InMemorySecretStore()

    async def create(self, agent_id: str, seed: bytes | str | list[str] | None = None):
        return await create_agent_identity(
            agent_id,
            identity_store=self.identities,
            secret_store=self.secrets,
            seed=seed,
        )

    async def issue(self, agent_id: str, target: str, cap: str = "delegate", ttl: int = 3600):
        return await issue_capability_token(
            agent_id,
            target,
            cap,
            ttl_seconds=ttl,
            identity_store=self.identities,
            token_store=self.tokens,
            secret_store=self.secrets,
        )

    async def recover(self, agent_id: str, seed: bytes | str | list[str], grace: int = 86400):
        return await recover_agent_identity(
            agent_id,
            seed,
            identity_store=self.identities,
            token_store=self.tokens,
            secret_store=self.secrets,
            grace_ttl_seconds=grace,
        )


@pytest.fixture
def env() -> Env:
    return Env()


# ---------------------------------------------------------------------------
# Identity creation
# ---------------------------------------------------------------------------


async def test_create_identity_did_key_format(env: Env) -> None:
    identity = await env.create("agent-a")
    assert identity.agent_id == "agent-a"
    assert identity.did.startswith("did:key:z")
    assert len(identity.public_key) == 32
    assert identity.offboarded_at is None
    assert not identity.is_offboarded
    # DID round-trips to the raw Ed25519 public key.
    assert public_key_from_did_key(identity.did) == identity.public_key


async def test_create_identity_is_persisted(env: Env) -> None:
    identity = await env.create("agent-a")
    assert await env.identities.get("agent-a") == identity


async def test_create_identity_duplicate_rejected(env: Env) -> None:
    await env.create("agent-a")
    with pytest.raises(IdentityAlreadyExistsError):
        await env.create("agent-a")


async def test_create_identity_deterministic_from_seed(env: Env) -> None:
    seed = bytes(range(32))
    a = await env.create("agent-a", seed=seed)
    b = await env.create("agent-b", seed=seed)
    assert a.did == b.did  # same seed -> same keypair -> same DID


async def test_create_identity_random_seeds_differ(env: Env) -> None:
    a = await env.create("agent-a")
    b = await env.create("agent-b")
    assert a.did != b.did


async def test_seed_not_stored_in_plaintext(env: Env) -> None:
    seed = b"\x07" * 32
    identity = await env.create("agent-a", seed=seed)
    assert identity.recovery_seed_encrypted != seed
    assert env.secrets.decrypt(identity.recovery_seed_encrypted) == seed


async def test_create_identity_from_mnemonic_matches_conductor_seed_curve(env: Env) -> None:
    """A BIP39 mnemonic is an accepted seed form (recovery ladder input)."""
    words = ConductorSeed.generate().mnemonic_words()
    a = await env.create("agent-a", seed=words)
    b = await env.create("agent-b", seed=" ".join(words))
    assert a.did == b.did


def test_did_key_helpers_reject_bad_input() -> None:
    with pytest.raises(ValueError):
        did_key_from_public_key(b"\x00" * 31)
    with pytest.raises(ValueError):
        public_key_from_did_key("did:web:example.com")
    with pytest.raises(ValueError):
        public_key_from_did_key("did:key:zzzzz")


def test_did_key_matches_conductor_seed_encoding() -> None:
    """Lifecycle did:key encoding agrees with the existing ConductorSeed one."""
    seed = ConductorSeed.generate()
    pub = seed.public_key("m/44'/9000'/0'")
    assert did_key_from_public_key(pub) == seed.did_key()


# ---------------------------------------------------------------------------
# Capability tokens
# ---------------------------------------------------------------------------


async def test_issue_and_verify_token(env: Env) -> None:
    identity = await env.create("agent-a")
    target = await env.create("agent-b")
    token = await env.issue("agent-a", target.agent_id, "delegate")
    assert token.iss == identity.did
    assert token.sub == "agent-b"
    assert token.cap == "delegate"
    assert token.exp > int(time.time())
    assert await verify_capability_token(token, token_store=env.tokens) is True


@pytest.mark.parametrize("cap", ["delegate", "read", "write"])
async def test_all_capabilities_issuable(env: Env, cap: str) -> None:
    await env.create("agent-a")
    token = await env.issue("agent-a", "agent-b", cap)
    assert token.cap == cap
    assert await verify_capability_token(token, token_store=env.tokens)


async def test_issue_unknown_capability_rejected(env: Env) -> None:
    await env.create("agent-a")
    with pytest.raises(CapabilityTokenError):
        await env.issue("agent-a", "agent-b", "root")


async def test_issue_nonpositive_ttl_rejected(env: Env) -> None:
    await env.create("agent-a")
    with pytest.raises(CapabilityTokenError):
        await env.issue("agent-a", "agent-b", "read", ttl=0)


async def test_issue_requires_identity(env: Env) -> None:
    with pytest.raises(IdentityNotFoundError):
        await env.issue("ghost", "agent-b")


async def test_tampered_subject_fails_signature(env: Env) -> None:
    await env.create("agent-a")
    token = await env.issue("agent-a", "agent-b")
    token.sub = "agent-evil"
    with pytest.raises(InvalidTokenSignatureError):
        await verify_capability_token(token)


async def test_tampered_capability_fails_signature(env: Env) -> None:
    await env.create("agent-a")
    token = await env.issue("agent-a", "agent-b", "read")
    token.cap = "write"
    with pytest.raises(InvalidTokenSignatureError):
        await verify_capability_token(token)


async def test_token_signed_by_other_agent_fails(env: Env) -> None:
    await env.create("agent-a")
    mallory = await env.create("mallory")
    token = await env.issue("agent-a", "agent-b")
    forged = CapabilityToken(
        iss=mallory.did, sub=token.sub, cap=token.cap, exp=token.exp, signature=token.signature
    )
    with pytest.raises(InvalidTokenSignatureError):
        await verify_capability_token(forged)


async def test_expired_token_rejected(env: Env) -> None:
    await env.create("agent-a")
    token = await env.issue("agent-a", "agent-b", ttl=10)
    # Expiry is checked on every use: valid now, rejected at/after exp.
    assert await verify_capability_token(token, now=token.exp - 1)
    with pytest.raises(TokenExpiredError):
        await verify_capability_token(token, now=token.exp)
    with pytest.raises(TokenExpiredError):
        await verify_capability_token(token, now=token.exp + 999)


async def test_revoked_token_rejected(env: Env) -> None:
    await env.create("agent-a")
    token = await env.issue("agent-a", "agent-b")
    await env.tokens.revoke(token)
    with pytest.raises(TokenRevokedError):
        await verify_capability_token(token, token_store=env.tokens)


async def test_unknown_token_treated_as_revoked(env: Env) -> None:
    await env.create("agent-a")
    token = await env.issue("agent-a", "agent-b")
    with pytest.raises(TokenRevokedError):
        await verify_capability_token(token, token_store=InMemoryTokenStore())


async def test_get_by_issuer_lists_live_tokens_only(env: Env) -> None:
    identity = await env.create("agent-a")
    t1 = await env.issue("agent-a", "agent-b", "read")
    await env.issue("agent-a", "agent-c", "write")
    assert len(await env.tokens.get_by_issuer(identity.did)) == 2
    await env.tokens.revoke(t1)
    live = await env.tokens.get_by_issuer(identity.did)
    assert [t.sub for t in live] == ["agent-c"]


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


async def test_recover_with_correct_seed_same_did(env: Env) -> None:
    seed = b"\x2a" * 32
    identity = await env.create("agent-a", seed=seed)
    recovered = await env.recover("agent-a", seed)
    assert recovered.did == identity.did


async def test_recover_with_wrong_seed_raises(env: Env) -> None:
    await env.create("agent-a", seed=b"\x01" * 32)
    with pytest.raises(InvalidRecoverySeedError):
        await env.recover("agent-a", b"\x02" * 32)


async def test_recover_with_bad_seed_length_raises(env: Env) -> None:
    await env.create("agent-a")
    with pytest.raises(InvalidRecoverySeedError):
        await env.recover("agent-a", b"short")


async def test_recover_with_garbage_mnemonic_raises(env: Env) -> None:
    await env.create("agent-a")
    with pytest.raises(InvalidRecoverySeedError):
        await env.recover("agent-a", ["not", "a", "valid", "mnemonic"])


async def test_recover_unknown_agent_raises(env: Env) -> None:
    with pytest.raises(IdentityNotFoundError):
        await env.recover("ghost", b"\x00" * 32)


async def test_recover_reissues_tokens_with_grace_ttl(env: Env) -> None:
    seed = b"\x05" * 32
    identity = await env.create("agent-a", seed=seed)
    old = await env.issue("agent-a", "agent-b", "delegate", ttl=3600)
    await env.recover("agent-a", seed, grace=86400)

    # Old token is revoked.
    with pytest.raises(TokenRevokedError):
        await verify_capability_token(old, token_store=env.tokens)

    # A replacement token exists for the same subject/cap with grace expiry.
    live = await env.tokens.get_by_issuer(identity.did)
    assert len(live) == 1
    new = live[0]
    assert (new.sub, new.cap) == ("agent-b", "delegate")
    assert new.exp > old.exp
    assert await verify_capability_token(new, token_store=env.tokens)


async def test_recover_with_mnemonic_seed(env: Env) -> None:
    words = ConductorSeed.generate().mnemonic_words()
    identity = await env.create("agent-a", seed=words)
    recovered = await env.recover("agent-a", words)
    assert recovered.did == identity.did
    with pytest.raises(InvalidRecoverySeedError):
        await env.recover("agent-a", ConductorSeed.generate().mnemonic_words())


# Property: recovery from seed always produces the same DID (spec Testing).
@settings(max_examples=50, deadline=None)
@given(seed=st.binary(min_size=32, max_size=32))
async def test_property_same_seed_same_did(seed: bytes) -> None:
    env1, env2 = Env(), Env()
    a = await env1.create("agent-a", seed=seed)
    b = await env2.create("agent-a", seed=seed)
    assert a.did == b.did
    recovered = await env1.recover("agent-a", seed)
    assert recovered.did == a.did


@settings(max_examples=25, deadline=None)
@given(
    seed=st.binary(min_size=32, max_size=32),
    wrong=st.binary(min_size=32, max_size=32),
)
async def test_property_wrong_seed_never_recovers(seed: bytes, wrong: bytes) -> None:
    env = Env()
    await env.create("agent-a", seed=seed)
    if wrong == seed:
        assert (await env.recover("agent-a", wrong)) is not None
    else:
        with pytest.raises(InvalidRecoverySeedError):
            await env.recover("agent-a", wrong)


# ---------------------------------------------------------------------------
# Offboarding
# ---------------------------------------------------------------------------


async def test_offboard_revokes_all_tokens_and_archives(env: Env) -> None:
    identity = await env.create("agent-a")
    t1 = await env.issue("agent-a", "agent-b", "read")
    t2 = await env.issue("agent-a", "agent-c", "delegate")
    events: list[tuple[str, str]] = []

    archived = await offboard_agent(
        "agent-a",
        identity_store=env.identities,
        token_store=env.tokens,
        emit=lambda name, agent_id: events.append((name, agent_id)),
    )

    assert archived.is_offboarded
    assert archived.did == identity.did  # archived, not deleted
    assert events == [("identity.offboarded", "agent-a")]
    stored = await env.identities.get("agent-a")
    assert stored is not None and stored.is_offboarded

    for token in (t1, t2):
        with pytest.raises(TokenRevokedError):
            await verify_capability_token(token, token_store=env.tokens)
    assert await env.tokens.get_by_issuer(identity.did) == []


async def test_offboarded_agent_cannot_issue_or_recover(env: Env) -> None:
    seed = b"\x09" * 32
    await env.create("agent-a", seed=seed)
    await offboard_agent("agent-a", identity_store=env.identities, token_store=env.tokens)
    with pytest.raises(IdentityArchivedError):
        await env.issue("agent-a", "agent-b")
    with pytest.raises(IdentityArchivedError):
        await env.recover("agent-a", seed)


async def test_offboard_unknown_agent_raises(env: Env) -> None:
    with pytest.raises(IdentityNotFoundError):
        await offboard_agent("ghost", identity_store=env.identities, token_store=env.tokens)


async def test_offboard_is_idempotent(env: Env) -> None:
    await env.create("agent-a")
    first = await offboard_agent("agent-a", identity_store=env.identities, token_store=env.tokens)
    second = await offboard_agent("agent-a", identity_store=env.identities, token_store=env.tokens)
    assert second.offboarded_at == first.offboarded_at


# ---------------------------------------------------------------------------
# Integration: delegation flow (spec Testing section)
# ---------------------------------------------------------------------------


async def test_delegation_flow_accept_then_reject_after_offboard(env: Env) -> None:
    """Agent A issues to sub-agent B; B's token is accepted, then rejected
    after A is offboarded."""
    await env.create("agent-a")
    await env.create("agent-b")
    token = await env.issue("agent-a", "agent-b", "delegate", ttl=3600)

    # Sub-agent presents the token; verifier checks sig + expiry + revocation.
    assert await verify_capability_token(token, token_store=env.tokens)

    await offboard_agent("agent-a", identity_store=env.identities, token_store=env.tokens)
    with pytest.raises(TokenRevokedError):
        await verify_capability_token(token, token_store=env.tokens)


def test_in_memory_secret_store_rejects_unknown_handle() -> None:
    store = InMemorySecretStore()
    with pytest.raises(IdentityLifecycleError):
        store.decrypt(b"nope")
