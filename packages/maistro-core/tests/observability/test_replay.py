"""Tests for maistro.observability.replay — record store, tier routing, replay session."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from maistro.observability.replay import (
    InMemoryRecordStore,
    ReplayDivergenceError,
    ReplayEvent,
    ReplayPayloadUnavailableError,
    ReplaySession,
    SealedAccessError,
    canonical_request_hash,
)
from maistro.observability.tiers import SensitivityTier


def make_event(
    seq: int,
    tier: SensitivityTier = SensitivityTier.NORMAL,
    kind: str = "llm",
    args: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    trace_id: str = "trace-1",
) -> ReplayEvent:
    args = args if args is not None else {"prompt": f"q{seq}"}
    return ReplayEvent(
        trace_id=trace_id,
        span_id=f"span-{seq}",
        seq=seq,
        kind=kind,  # type: ignore[arg-type]
        request_hash=canonical_request_hash(args),
        payload={"request": args, "response": response or {"content": f"a{seq}"}},
        tier=tier,
    )


class TestCanonicalHash:
    def test_stable_across_key_order(self) -> None:
        assert canonical_request_hash({"a": 1, "b": 2}) == canonical_request_hash({"b": 2, "a": 1})

    def test_differs_on_value_change(self) -> None:
        assert canonical_request_hash({"a": 1}) != canonical_request_hash({"a": 2})

    def test_is_sha256_hex(self) -> None:
        h = canonical_request_hash({"a": 1})
        assert len(h) == 64
        int(h, 16)


#: Distinctive enough that it cannot occur in a repr by accident — which is
#: the property the generated strings did not have (#173).
CANARY = "SECRET-CANARY-9c2e77"


class TestTierRouting:
    async def test_normal_stores_full_payload(self) -> None:
        store = InMemoryRecordStore()
        event = make_event(0)
        await store.record(event)
        [stored] = await store.events_for_trace("trace-1")
        assert stored.payload == event.payload

    @pytest.mark.ac("SPEC-070226-2b70/AC-5")
    async def test_sensitive_payload_sealed_and_encrypted(self) -> None:
        encrypted_inputs: list[bytes] = []

        def encryptor(b: bytes) -> bytes:
            encrypted_inputs.append(b)
            return bytes(x ^ 0x5A for x in b)

        store = InMemoryRecordStore(
            encryptor=encryptor, decryptor=lambda b: bytes(x ^ 0x5A for x in b)
        )
        event = make_event(0, tier=SensitivityTier.SENSITIVE)
        await store.record(event)

        [stored] = await store.events_for_trace("trace-1")
        assert stored.payload is None  # not readable via the normal path
        assert len(encrypted_inputs) == 1  # encryptor was actually used

        payload = await store.read_sensitive_payload("trace-1", 0, "alice", "debugging")
        assert payload == event.payload

    @pytest.mark.ac("SPEC-070226-2b70/AC-5")
    async def test_sensitive_read_writes_access_audit_row(self) -> None:
        store = InMemoryRecordStore()
        await store.record(make_event(0, tier=SensitivityTier.SENSITIVE))
        assert store.access_audit == []

        await store.read_sensitive_payload("trace-1", 0, "alice", "incident-42")
        await store.read_sensitive_payload("trace-1", 0, "bob", "audit")

        audit = store.access_audit
        assert [(a.accessor, a.reason) for a in audit] == [
            ("alice", "incident-42"),
            ("bob", "audit"),
        ]
        assert all(a.trace_id == "trace-1" and a.seq == 0 for a in audit)

    @pytest.mark.ac("SPEC-070226-2b70/AC-5")
    async def test_sensitive_read_missing_raises(self) -> None:
        store = InMemoryRecordStore()
        with pytest.raises(SealedAccessError):
            await store.read_sensitive_payload("trace-1", 7, "alice", "nope")

    @pytest.mark.ac("SPEC-070226-2b70/AC-6")
    async def test_secret_stores_hash_and_metadata_only(self) -> None:
        store = InMemoryRecordStore()
        event = make_event(0, tier=SensitivityTier.SECRET, args={"ssn": "123-45-6789"})
        await store.record(event)
        [stored] = await store.events_for_trace("trace-1")
        assert stored.payload is None
        assert stored.request_hash == event.request_hash
        assert stored.trace_id == "trace-1"
        with pytest.raises(SealedAccessError):
            await store.read_sensitive_payload("trace-1", 0, "alice", "peek")

    @settings(max_examples=50, deadline=None)
    @given(
        payload=st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(st.text(max_size=50), st.integers(), st.booleans()),
            max_size=5,
        )
    )
    # The exact value that made the old assertion fire: `asyncio.Lock.__repr__`
    # ends `[unlocked]`, and this is 8 characters, so it cleared the length
    # filter. Pinned so the regression stays covered without depending on a
    # search finding it again (#173).
    @example(payload={"lock_state": "unlocked"})
    @pytest.mark.ac("SPEC-070226-2b70/AC-6")
    async def test_property_secret_tier_state_does_not_vary_with_the_payload(
        self, payload: dict[str, Any]
    ) -> None:
        """For any payload, what SECRET tier persists is a function of the hash alone.

        This is the same claim as "no payload bytes are stored", stated so it
        can be checked exactly. The previous version searched
        ``repr(store.__dict__)`` for every generated string of 8+ characters,
        which was wrong in both directions (#173):

        - **False positives.** The store holds an ``asyncio.Lock``, whose repr
          ends ``[unlocked]``. Hypothesis eventually generates the 8-character
          value ``"unlocked"``, and the assertion fired on structural text
          having proved nothing. It passed in CI only because a fresh runner
          starts with an empty example database and the search rarely gets that
          lucky — a red build waiting for an unrelated PR to inherit.
        - **False negatives.** A substring scan cannot see a leak that is
          encoded, truncated, or reordered, and skips short values entirely.

        Recording two different payloads under one identical hash and demanding
        byte-identical state covers all of those: anything that varies with the
        payload — including its length — fails. Comparison is over the state
        attributes only, because the lock's repr carries a memory address that
        differs between instances for reasons that are not leaks.
        """
        control = {"canary": CANARY, "control": "a-different-value-entirely"}
        assert await self._secret_state({"canary": CANARY, **payload}) == await self._secret_state(
            control
        ), "SECRET-tier state varied with the payload"

    #: Store attributes that cannot carry payload bytes: two injected callables
    #: and a lock. Named rather than filtered by type so that a *new* attribute
    #: fails `_secret_state` until someone classifies it — an unclassified
    #: attribute is exactly where a leak would land unnoticed.
    _INERT_ATTRS = frozenset({"_encryptor", "_decryptor", "_lock"})
    _STATE_ATTRS = ("_audit", "_events", "_sealed")

    async def _secret_state(self, payload: dict[str, Any]) -> str:
        """Everything a SECRET-tier record leaves behind, with the hash masked."""
        store = InMemoryRecordStore()
        args = {"data": payload}
        event = ReplayEvent(
            trace_id="t",
            span_id="s",
            seq=0,
            kind="tool",
            request_hash=canonical_request_hash(args),
            payload={"request": args, "response": {"output": payload}},
            tier=SensitivityTier.SECRET,
        )
        await store.record(event)

        [stored] = await store.events_for_trace("t")
        assert stored.payload is None

        unclassified = set(store.__dict__) - self._INERT_ATTRS - set(self._STATE_ATTRS)
        assert not unclassified, (
            f"InMemoryRecordStore grew attribute(s) {sorted(unclassified)}; classify each as "
            f"state or inert before this test can speak for them"
        )
        # The hash is derived from the payload and is stored on purpose, so it
        # is the one value allowed to differ. Masking it is what leaves the
        # comparison meaning "nothing *else* varied".
        state = repr({name: store.__dict__[name] for name in self._STATE_ATTRS})
        return state.replace(event.request_hash, "<request-hash>")

    async def test_the_property_check_would_catch_a_payload_that_reached_the_store(self) -> None:
        """The property above passes if `_secret_state` compares nothing.

        Recording at NORMAL tier keeps the payload, so two different payloads
        must produce different state. If this ever passes, the comparison has
        stopped being sensitive to payload content and the property test above
        has become vacuous.
        """
        seen = set()
        for payload in ({"canary": CANARY, "x": "one"}, {"canary": CANARY, "x": "two"}):
            store = InMemoryRecordStore()
            args = {"data": payload}
            await store.record(
                ReplayEvent(
                    trace_id="t",
                    span_id="s",
                    seq=0,
                    kind="tool",
                    request_hash=canonical_request_hash(args),
                    payload={"request": args},
                    tier=SensitivityTier.NORMAL,
                )
            )
            seen.add(repr({name: store.__dict__[name] for name in self._STATE_ATTRS}))
        assert len(seen) == 2, "the state comparison cannot see payload content at all"

    @pytest.mark.ac("SPEC-070226-2b70/AC-6")
    async def test_the_literal_canary_never_appears_in_the_stored_state(self) -> None:
        """The readable half, kept as its own test.

        A distinctive canary cannot collide with structural text, so this states
        the intent directly without the false-positive rate that made the
        substring scan unusable over arbitrary generated strings.
        """
        state = await self._secret_state({"canary": CANARY, "ssn": "123-45-6789"})
        assert CANARY not in state
        assert "123-45-6789" not in state


class TestReplaySession:
    @pytest.mark.ac("SPEC-070226-2b70/AC-2")
    async def test_serves_recorded_responses_in_order(self) -> None:
        store = InMemoryRecordStore()
        await store.record(make_event(0, args={"prompt": "a"}, response={"content": "ra"}))
        await store.record(
            make_event(1, kind="tool", args={"name": "ls"}, response={"output": "rb"})
        )

        session = ReplaySession(store, "trace-1")
        assert await session.next_response("llm", {"prompt": "a"}) == {"content": "ra"}
        assert await session.next_response("tool", {"name": "ls"}) == {"output": "rb"}

    @pytest.mark.ac("SPEC-070226-2b70/AC-4")
    async def test_hash_mismatch_raises_divergence_naming_seq_and_hashes(self) -> None:
        store = InMemoryRecordStore()
        await store.record(make_event(0, args={"prompt": "recorded"}))
        session = ReplaySession(store, "trace-1")

        with pytest.raises(ReplayDivergenceError) as exc_info:
            await session.next_response("llm", {"prompt": "different"})

        err = exc_info.value
        assert err.seq == 0
        assert err.recorded_hash == canonical_request_hash({"prompt": "recorded"})
        assert err.attempted_hash == canonical_request_hash({"prompt": "different"})
        assert "seq=0" in str(err)
        assert err.recorded_hash is not None and err.recorded_hash in str(err)
        assert err.attempted_hash in str(err)

    @pytest.mark.ac("SPEC-070226-2b70/AC-4")
    async def test_kind_mismatch_raises_divergence(self) -> None:
        store = InMemoryRecordStore()
        await store.record(make_event(0, kind="llm", args={"prompt": "a"}))
        session = ReplaySession(store, "trace-1")
        with pytest.raises(ReplayDivergenceError, match="kind"):
            await session.next_response("tool", {"prompt": "a"})

    @pytest.mark.ac("SPEC-070226-2b70/AC-4")
    async def test_exhausted_trace_raises_divergence(self) -> None:
        store = InMemoryRecordStore()
        session = ReplaySession(store, "trace-1")
        with pytest.raises(ReplayDivergenceError, match="exhausted"):
            await session.next_response("llm", {"prompt": "a"})

    @pytest.mark.ac("SPEC-070226-2b70/AC-5")
    async def test_sensitive_replay_reads_via_sealed_path_with_audit(self) -> None:
        store = InMemoryRecordStore()
        await store.record(
            make_event(
                0,
                tier=SensitivityTier.SENSITIVE,
                args={"prompt": "a"},
                response={"content": "sealed"},
            )
        )
        session = ReplaySession(store, "trace-1")
        assert await session.next_response("llm", {"prompt": "a"}) == {"content": "sealed"}
        assert [a.accessor for a in store.access_audit] == ["replay"]

    @pytest.mark.ac("SPEC-070226-2b70/AC-6")
    async def test_secret_replay_raises_payload_unavailable(self) -> None:
        store = InMemoryRecordStore()
        await store.record(make_event(0, tier=SensitivityTier.SECRET, args={"prompt": "a"}))
        session = ReplaySession(store, "trace-1")
        with pytest.raises(ReplayPayloadUnavailableError):
            await session.next_response("llm", {"prompt": "a"})

    @settings(max_examples=30, deadline=None)
    @given(
        kinds=st.lists(st.sampled_from(["llm", "tool"]), min_size=1, max_size=12),
        seed=st.integers(min_value=0, max_value=10_000),
    )
    @pytest.mark.ac("SPEC-070226-2b70/AC-2")
    async def test_property_replay_preserves_seq_order(self, kinds: list[str], seed: int) -> None:
        """For any recorded sequence of LLM + tool calls, events_for_trace and the
        replay session preserve the original per-trace seq order."""
        store = InMemoryRecordStore()
        for i, kind in enumerate(kinds):
            await store.record(make_event(i, kind=kind, args={"i": i, "seed": seed}))

        events = await store.events_for_trace("trace-1")
        assert [e.seq for e in events] == list(range(len(kinds)))
        assert [e.kind for e in events] == kinds

        session = ReplaySession(store, "trace-1")
        for i, kind in enumerate(kinds):
            response = await session.next_response(kind, {"i": i, "seed": seed})  # type: ignore[arg-type]
            assert response == {"content": f"a{i}"}
