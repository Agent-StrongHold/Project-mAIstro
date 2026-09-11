"""Task admission idempotency (#1176).

The contract has four edges, and the issue holds each one separately: a key
scoped so it cannot collide or leak across principals and Workspaces; a replay
that reconciles to the original admission inside a documented window instead
of minting a second Run; a payload mismatch that fails visibly; and
concurrency where identical submissions deterministically produce one Run.
These tests hold the in-memory claim store and the queue integration to all
four, plus the failure-ordering rule: a failed admission must release its
claim, a superseded claimant must not stamp (or release) the winner's row, and
a claimant that died around minting must resolve by discovery — the ambiguous
window ends in the existing Run or a takeover that provably mints nothing
twice.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

import maistro.tasks.idempotency as idempotency_module
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import admit_direct_work
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.runs.task_kinds import resolve_direct_work
from maistro.tasks import queue as queue_module
from maistro.tasks.admission import (
    TASK_ID_KEY,
    TASK_QUEUE_SOURCE,
    TaskRunAdmitter,
    WorkspaceRoutingAdmitter,
)
from maistro.tasks.idempotency import (
    DEFAULT_REPLAY_WINDOW,
    IDEMPOTENCY_KEY_PROVENANCE,
    MAX_PENDING_POLLS,
    PENDING_LEASE,
    PENDING_POLL,
    TASK_SUBMIT_ACTION,
    AdmissionRecord,
    Ambiguous,
    Claimed,
    IdempotencyKeyMismatch,
    IdempotencyPendingTimeout,
    InMemoryTaskIdempotencyStore,
    InvalidIdempotencyKey,
    Pending,
    Replayed,
    admission_scope_key,
    from_epoch_us,
    normalize_idempotency_key,
    request_fingerprint,
)
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus
from maistro.tasks.queue import TaskQueue

_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


# ── the scope: no collisions, no leaks ────────────────────────────


def test_the_same_tuple_yields_one_scope() -> None:
    first = admission_scope_key(
        principal="u1", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    second = admission_scope_key(
        principal="u1", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    assert first == second


def test_a_key_cannot_cross_principals_workspaces_or_actions() -> None:
    """Length-prefixed parts: no two distinct tuples may share a digest, which
    is what makes cross-tenant collision structural rather than improbable."""
    base = admission_scope_key(
        principal="u1", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    assert base != admission_scope_key(
        principal="u2", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    assert base != admission_scope_key(
        principal="u1", workspace_id="w2", action=TASK_SUBMIT_ACTION, key="k"
    )
    assert base != admission_scope_key(
        principal="u1", workspace_id="w1", action="other.action", key="k"
    )
    assert base != admission_scope_key(
        principal="u1", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k2"
    )


def test_scope_parts_do_not_alias_through_the_separator() -> None:
    """("a", "b") must not digest as ("a\x1fb-part", ...): the length prefix
    pins each part's extent, so one caller's key cannot be re-cut into
    another's principal."""
    aliased = admission_scope_key(
        principal="u1\x1fw", workspace_id="1", action=TASK_SUBMIT_ACTION, key="k"
    )
    honest = admission_scope_key(
        principal="u1", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    assert aliased != honest


def test_scope_keys_are_not_reversible_into_the_key() -> None:
    scope = admission_scope_key(
        principal="u1", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="secret"
    )
    assert "secret" not in scope


# ── the fingerprint and the derived key ───────────────────────────


def test_the_fingerprint_covers_the_payload_and_ignores_identity_slots() -> None:
    base = TaskCreate(description="Fix it", session_id="s1")
    assert request_fingerprint(base) == request_fingerprint(base.model_copy())
    # user_id is auth's answer, not the client's: the scope already carries
    # the principal, and the API overwrites whatever was sent.
    assert request_fingerprint(base) == request_fingerprint(
        base.model_copy(update={"user_id": "someone-else"})
    )
    # The key slot must not feed the fingerprint, or an explicit key would
    # change the payload the key is checked against.
    assert request_fingerprint(base) == request_fingerprint(
        base.model_copy(update={"idempotency_key": "k"})
    )
    assert request_fingerprint(base) != request_fingerprint(
        base.model_copy(update={"description": "Fix it differently"})
    )
    assert request_fingerprint(base) != request_fingerprint(
        base.model_copy(update={"session_id": "s2"})
    )


# ── key normalization: visible refusal, never a silent rename ─────


def test_conflicting_key_sources_are_refused() -> None:
    with pytest.raises(InvalidIdempotencyKey, match="conflicting"):
        normalize_idempotency_key("alpha", "beta")


def test_agreeing_and_partial_sources_collapse() -> None:
    assert normalize_idempotency_key("alpha", "alpha") == "alpha"
    assert normalize_idempotency_key("alpha", None) == "alpha"
    assert normalize_idempotency_key(None, None) is None
    assert normalize_idempotency_key("  alpha  ") == "alpha"
    # Whitespace-only means absent, not a key made of spaces.
    assert normalize_idempotency_key("   ") is None
    assert normalize_idempotency_key(None, "   ") is None


def test_an_oversized_key_is_refused_rather_than_truncated() -> None:
    with pytest.raises(InvalidIdempotencyKey, match="exceeds"):
        normalize_idempotency_key("k" * 201)


# ── the claim store: window, mismatch, takeover, purge ────────────


async def test_claim_complete_then_replay() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    first = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(first, Claimed)
    assert await store.complete(scope, token=first.token, task_id="t1", run_id="r1") is True

    replay = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + timedelta(minutes=1)
    )
    assert isinstance(replay, Replayed)
    assert replay.record.task_id == "t1"
    assert replay.record.run_id == "r1"
    assert replay.record.admitted is True


async def test_a_second_claimant_on_a_pending_claim_waits() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    assert isinstance(await store.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed)
    # The winner is mid-admission: unexpired lease, no receipt yet.
    twin = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW + timedelta(seconds=1))
    assert isinstance(twin, Pending)
    assert twin.record.admitted is False


async def test_a_fingerprint_mismatch_inside_the_window_fails_visibly() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    first = await store.claim(scope, fingerprint="fp-one", request="{}", now=_NOW)
    assert isinstance(first, Claimed)
    await store.complete(scope, token=first.token, task_id="t1", run_id="r1")

    with pytest.raises(IdempotencyKeyMismatch, match="different request payload"):
        await store.claim(
            scope, fingerprint="fp-two", request="{}", now=_NOW + timedelta(minutes=1)
        )


async def test_the_replay_window_expires_and_frees_the_key() -> None:
    """The window is the contract's documented bound: after it, the same key
    is a new admission — the old Run keeps standing, but nothing reconciles
    to it, and the fingerprint contract has the window's lifetime, no more."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    first = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(first, Claimed)
    await store.complete(scope, token=first.token, task_id="t1", run_id="r1")

    # A different payload after expiry is NOT the visible 409: the mismatch
    # contract lived inside the window. The key is simply free again.
    other = await store.claim(
        scope,
        fingerprint="fp-two",
        request="{}",
        now=_NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1),
    )
    assert isinstance(other, Claimed)

    # And the same payload after expiry is a fresh admission too — the old
    # Run is not resurrected as a replay.
    other_scope = admission_scope_key(
        principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k2"
    )
    second = await store.claim(other_scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(second, Claimed)
    await store.complete(other_scope, token=second.token, task_id="t3", run_id="r3")
    fresh = await store.claim(
        other_scope,
        fingerprint="fp",
        request="{}",
        now=_NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1),
    )
    assert isinstance(fresh, Claimed)


async def test_a_stalled_pending_claim_is_taken_over() -> None:
    """A claimant that died mid-admission must not pin the key forever: the
    lease lapses, the retry takes over, and admission stays retryable."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    takeover = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + PENDING_LEASE + timedelta(seconds=1)
    )
    assert isinstance(takeover, Claimed)
    record = await store.get(scope)
    assert record is not None and record.admitted is False
    # The takeover is a new claimant: the old token answers nothing now.
    assert await store.complete(scope, token="stale-token", task_id="t1", run_id="r1") is False


# ── claimant fencing: a superseded claimant writes nothing ────────


async def test_a_superseded_claimant_cannot_stamp_the_winners_row() -> None:
    """The false-completion regression: a claimant stalled past the lease,
    whose claim a twin took over, must not land its outcome on the thief's
    row — the winner's outcome is the one this key reconciles to."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    stalled = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(stalled, Claimed)
    winner = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + PENDING_LEASE + timedelta(seconds=1)
    )
    assert isinstance(winner, Claimed)
    assert winner.token != stalled.token

    assert (
        await store.complete(scope, token=stalled.token, task_id="t-stalled", run_id="r-stalled")
        is False
    )
    record = await store.get(scope)
    assert record is not None and record.admitted is False

    assert (
        await store.complete(scope, token=winner.token, task_id="t-winner", run_id="r-winner")
        is True
    )
    record = await store.get(scope)
    assert record is not None
    assert (record.task_id, record.run_id) == ("t-winner", "r-winner")
    # And the fence holds after the outcome too.
    assert (
        await store.complete(scope, token=stalled.token, task_id="t-stalled", run_id="r-stalled")
        is False
    )


async def test_a_superseded_claimant_cannot_release_the_winners_claim() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    stalled = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(stalled, Claimed)
    await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + PENDING_LEASE + timedelta(seconds=1)
    )

    assert await store.release(scope, token=stalled.token) is False
    record = await store.get(scope)
    assert record is not None, "the winner's claim must survive the loser's release"


# ── begin: the announcement that makes the ambiguous window decidable ──


async def test_begin_announces_the_receipt_and_refreshes_the_lease() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    begun_at = _NOW + timedelta(seconds=20)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=begun_at) is True

    record = await store.get(scope)
    assert record is not None
    assert record.task_id == "t1"
    assert record.begun is True
    assert record.admitted is False
    # The lease now runs from the announcement: the mint is the dangerous
    # stretch, and its fence is measured from when it starts.
    assert from_epoch_us(record.lease_expires_at_us) == begun_at + PENDING_LEASE

    # A begun claim inside its lease still reads as Pending, not replayable —
    # the outcome has not landed, and replaying it would hand out a receipt
    # whose Run may not exist yet.
    twin = await store.claim(
        scope, fingerprint="fp", request="{}", now=begun_at + timedelta(seconds=1)
    )
    assert isinstance(twin, Pending)


async def test_begin_refuses_a_superseded_or_repeated_announcement() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    stalled = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(stalled, Claimed)
    winner_at = _NOW + PENDING_LEASE + timedelta(seconds=1)
    await store.claim(scope, fingerprint="fp", request="{}", now=winner_at)
    assert await store.begin(scope, token=stalled.token, task_id="t1", now=_NOW) is False

    # And a claimant cannot announce twice: the second begin is a different
    # receipt for the same claim, which is exactly the duplication fence.
    again = await store.claim(
        scope,
        fingerprint="fp",
        request="{}",
        now=winner_at + PENDING_LEASE + timedelta(seconds=1),
    )
    assert isinstance(again, Claimed)
    assert await store.begin(scope, token=again.token, task_id="t2", now=_NOW) is True
    assert await store.begin(scope, token=again.token, task_id="t3", now=_NOW) is False


async def test_a_begun_claim_past_its_lease_is_ambiguous_not_takeover() -> None:
    """The heart of the repair: a claimant that announced a receipt and died
    somewhere around minting cannot be answered by takeover alone — the next
    submitter gets the ambiguity and must resolve it by discovery, because a
    blind takeover is the duplicate-Run bug this issue exists to close."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=_NOW) is True

    outcome = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + PENDING_LEASE + timedelta(seconds=1)
    )
    assert isinstance(outcome, Ambiguous)
    assert outcome.record.task_id == "t1"


async def test_discovery_resolves_the_ambiguous_window_to_the_existing_run() -> None:
    """The ambiguous-failure acceptance: the owner died after minting but
    before recording. Discovery finds the Run by the announced receipt,
    resolution records it, and the retry replays the existing Run instead of
    minting a second one."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=_NOW) is True

    later = _NOW + PENDING_LEASE + timedelta(seconds=1)
    ambiguous = await store.claim(scope, fingerprint="fp", request="{}", now=later)
    assert isinstance(ambiguous, Ambiguous)

    # Discovery: a Run naming the announced receipt exists (minted by the
    # corpse). resolve_run records the fact on the claim — deliberately not
    # claimant-fenced, it writes down what discovery proved.
    assert await store.resolve_run(scope, task_id="t1", run_id="r1") is True

    replay = await store.claim(scope, fingerprint="fp", request="{}", now=later)
    assert isinstance(replay, Replayed)
    assert (replay.record.task_id, replay.record.run_id) == ("t1", "r1")
    assert replay.record.admitted is True


async def test_discovery_finding_no_run_frees_the_claim_for_a_resolved_takeover() -> None:
    """The other half of the ambiguity: the owner died BEFORE minting. The
    announced receipt was never minted durably, so the takeover duplicates
    nothing — but it is fenced on the announced task id, so it can only land
    on the exact claim the discovery resolved."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=_NOW) is True

    later = _NOW + PENDING_LEASE + timedelta(seconds=1)
    assert isinstance(
        await store.claim(scope, fingerprint="fp", request="{}", now=later), Ambiguous
    )

    taken = await store.take_over_resolved(
        scope, task_id="t1", fingerprint="fp", request="{}", now=later
    )
    assert isinstance(taken, Claimed)
    record = await store.get(scope)
    assert record is not None
    assert record.admitted is False and record.begun is False

    # The winner completes; the corpse's late write is refused by the fence.
    assert await store.complete(scope, token=taken.token, task_id="t2", run_id="r2") is True
    assert await store.complete(scope, token=claimed.token, task_id="t1", run_id="r1") is False


async def test_a_resolved_takeover_only_lands_on_its_own_announcement() -> None:
    """The takeover fence: a discovery resolution that raced a winner's
    completion (or another takeover) must refuse, not stamp a moved row."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=_NOW) is True
    later = _NOW + PENDING_LEASE + timedelta(seconds=1)

    # A different announcement entirely, or an admitted row, is not ours.
    assert (
        await store.take_over_resolved(
            scope, task_id="other", fingerprint="fp", request="{}", now=later
        )
        is None
    )
    assert await store.resolve_run(scope, task_id="t1", run_id="r1") is True
    assert (
        await store.take_over_resolved(
            scope, task_id="t1", fingerprint="fp", request="{}", now=later
        )
        is None
    )


async def test_release_after_a_begun_failure_still_frees_the_key() -> None:
    """Failure before Run creation stays retryable, announcement included:
    the mint failed before any outcome, so the claim releases and the retry
    starts fresh."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.begin(scope, token=claimed.token, task_id="t1", now=_NOW) is True
    assert await store.release(scope, token=claimed.token) is True
    assert await store.get(scope) is None
    retry = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(retry, Claimed)


async def test_release_and_complete_refuse_to_touch_a_completed_claim() -> None:
    """The guards keep an owner from rewriting an outcome that already landed,
    and from releasing a claim another submission has taken over."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    claimed = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(claimed, Claimed)
    assert await store.complete(scope, token=claimed.token, task_id="t1", run_id="r1") is True
    assert await store.complete(scope, token=claimed.token, task_id="t9", run_id="r9") is False
    assert await store.release(scope, token=claimed.token) is False


async def test_purge_expired_removes_only_expired_claims() -> None:
    store = InMemoryTaskIdempotencyStore()
    old_scope = admission_scope_key(
        principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="old"
    )
    new_scope = admission_scope_key(
        principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="new"
    )

    await store.claim(old_scope, fingerprint="fp", request="{}", now=_NOW)
    # Created a day later, so its own window outlives the old claim's by a day
    # and a purge at the old claim's expiry must leave it alone.
    await store.claim(new_scope, fingerprint="fp", request="{}", now=_NOW + timedelta(hours=24))

    assert await store.purge_expired(now=_NOW + timedelta(hours=1)) == 0
    assert await store.purge_expired(now=_NOW + DEFAULT_REPLAY_WINDOW + timedelta(seconds=1)) == 1
    assert await store.get(old_scope) is None
    assert await store.get(new_scope) is not None


# ── the shared claim flow under interleaving ──────────────────────


def _scope(key: str) -> str:
    return admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key=key)


def _mid_admission_record(created: datetime) -> AdmissionRecord:
    """A pending claim: no receipt yet, lease still running from ``created``."""
    return AdmissionRecord(
        claim_token="token-" + created.isoformat(),
        fingerprint="fp",
        request="{}",
        task_id=None,
        run_id=None,
        completed_at_us=0,
        created_at_us=int(created.timestamp() * 1_000_000),
        expires_at_us=int((created + DEFAULT_REPLAY_WINDOW).timestamp() * 1_000_000),
        lease_expires_at_us=int((created + PENDING_LEASE).timestamp() * 1_000_000),
    )


def _expired_record(created: datetime) -> AdmissionRecord:
    """A claim whose replay window is long gone — deletable, take-overable."""
    return AdmissionRecord(
        claim_token="token-expired-" + created.isoformat(),
        fingerprint="fp",
        request="{}",
        task_id=None,
        run_id=None,
        completed_at_us=0,
        created_at_us=int(created.timestamp() * 1_000_000),
        expires_at_us=int((created + timedelta(hours=1)).timestamp() * 1_000_000),
        lease_expires_at_us=int((created + timedelta(minutes=1)).timestamp() * 1_000_000),
    )


class _ScriptedClaims(InMemoryTaskIdempotencyStore):
    """The in-memory tier with scripted ``_insert``/``_read`` outcomes, so the
    shared ``_ClaimFlow`` loop can be walked through interleavings a
    single-process test cannot otherwise produce. Every scripted value is one
    a real backend returns under concurrency: a refused INSERT, a row that is
    no longer there."""

    def __init__(self) -> None:
        super().__init__()
        self.insert_results: list[bool] = []
        self.read_results: list[AdmissionRecord | None] = []

    async def _insert(self, scope_key: str, record: AdmissionRecord) -> bool:
        if self.insert_results:
            return self.insert_results.pop(0)
        return await super()._insert(scope_key, record)

    async def _read(self, scope_key: str) -> AdmissionRecord | None:
        if self.read_results:
            return self.read_results.pop(0)
        return await super()._read(scope_key)


class _AlwaysContested(InMemoryTaskIdempotencyStore):
    """A takeover that never lands: every guard re-check finds the row moved
    under us again — the wasted round trip the takeover statements' comment
    names, where the read-side assessment and the write-side guard disagree
    by one interleaving."""

    def __init__(self) -> None:
        super().__init__()
        self.takeover_attempts = 0

    async def _take_over(self, scope_key: str, record: AdmissionRecord, now_us: int) -> bool:
        self.takeover_attempts += 1
        return False


async def test_a_slot_freed_between_read_and_takeover_is_rewon(monkeypatch) -> None:
    """The read-side classification said takeover, but the stalled claim's
    owner released before the write landed: the takeover guard refuses (the
    row is not there any more), the loop re-reads, and the freed slot is
    re-won — not reported as a phantom conflict or a wait."""
    store = InMemoryTaskIdempotencyStore()
    scope = _scope("k")
    assert isinstance(await store.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed)
    now = _NOW + PENDING_LEASE + timedelta(seconds=1)

    real_read = store._read

    async def read_then_release(scope_key: str) -> AdmissionRecord | None:
        record = await real_read(scope_key)
        if record is not None:
            # The stalled owner lets go after the flow has read the claim but
            # before its takeover lands — with the token it still holds.
            await store.release(scope_key, token=record.claim_token)
        return record

    monkeypatch.setattr(store, "_read", read_then_release)

    outcome = await store.claim(scope, fingerprint="fp", request="{}", now=now)

    assert isinstance(outcome, Claimed)
    record = await store.get(scope)
    assert record is not None and record.admitted is False
    assert from_epoch_us(record.created_at_us) == now


async def test_a_freed_slot_can_be_lost_a_second_time() -> None:
    """The slot frees between the refused insert and the re-read — and a twin
    re-claims it before our re-insert lands: the loop keeps classifying and
    reports the twin's claim, the pending owner that actually holds the key
    now."""
    store = _ScriptedClaims()
    twin = _mid_admission_record(_NOW - timedelta(seconds=5))
    store.insert_results.extend([False, False])
    store.read_results.extend([None, twin])

    outcome = await store.claim(_scope("k"), fingerprint="fp", request="{}", now=_NOW)

    assert isinstance(outcome, Pending)
    assert outcome.record is twin


async def test_takeover_rounds_are_bounded_and_report_the_row() -> None:
    """A takeover that keeps losing the row must end in the bounded wait, not
    a spin: exactly ``_RACE_ROUNDS`` attempts, then the claim as it stands —
    a pending answer keeps the caller's own retry loop and its takeover
    armed."""
    store = _AlwaysContested()
    scope = _scope("k")
    assert isinstance(await store.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed)

    outcome = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + PENDING_LEASE + timedelta(seconds=1)
    )

    assert isinstance(outcome, Pending)
    assert outcome.record is not None and outcome.record.admitted is False
    assert store.takeover_attempts == InMemoryTaskIdempotencyStore._RACE_ROUNDS


async def test_records_round_trip_through_epoch_microseconds() -> None:
    """Claim comparisons are SQL WHERE clauses on the durable tiers, so the
    stored timestamp must be exact — `from_epoch_us` is what a replay reads."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")
    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)

    record = await store.get(scope)
    assert record is not None
    assert from_epoch_us(record.created_at_us) == _NOW
    assert from_epoch_us(record.expires_at_us) == _NOW + DEFAULT_REPLAY_WINDOW
    assert from_epoch_us(record.lease_expires_at_us) == _NOW + PENDING_LEASE


async def test_a_naive_timestamp_is_refused_rather_than_assumed_utc() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.claim(scope, fingerprint="fp", request="{}", now=_NOW.replace(tzinfo=None))


# ── the queue integration ──────────────────────────────────────────


@pytest.fixture
async def scoped():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Tasks"
    )
    return projects, InMemoryRunStore(project_store=projects), root, project


def _wired_queue(
    runs: InMemoryRunStore, project_id: str
) -> tuple[TaskQueue, InMemoryTaskIdempotencyStore]:
    store = InMemoryTaskIdempotencyStore()
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project_id),
        idempotency_store=store,
    )
    return queue, store


async def test_an_explicit_retry_reconciles_to_the_first_run(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)
    request = TaskCreate(description="Fix the parser", idempotency_key="retry-1")

    first = await queue.submit(request, user_id="alice")
    retry = await queue.submit(request, user_id="alice")

    assert retry.task_id == first.task_id
    assert retry.run_id == first.run_id
    assert retry.idempotency_key == "retry-1"
    # One Run, one receipt: the retry minted neither.
    receipts, _cursor = queue.list_tasks(user_id="alice")
    assert len(receipts) == 1
    assert first.run_id is not None
    assert await runs.get_run(first.run_id) is not None
    run_ids = [receipt.run_id for receipt in receipts]
    assert run_ids == [first.run_id]


async def test_a_derived_key_reconciles_a_byte_identical_retry(scoped) -> None:
    """No explicit key: the payload fingerprint is the key, so a client that
    never heard of idempotency still gets its timeout-retry reconciled."""
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)

    first = await queue.submit(TaskCreate(description="Ship it", task_type="code"), user_id="alice")
    retry = await queue.submit(TaskCreate(description="Ship it", task_type="code"), user_id="alice")

    assert retry.task_id == first.task_id
    assert retry.run_id == first.run_id
    # The derived key is admission machinery: nothing on the receipt claims
    # the caller supplied one.
    assert first.idempotency_key is None
    assert retry.idempotency_key is None


async def test_a_derived_key_does_not_swallow_a_changed_payload(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)

    first = await queue.submit(TaskCreate(description="one"), user_id="alice")
    second = await queue.submit(TaskCreate(description="two"), user_id="alice")

    assert second.task_id != first.task_id
    assert second.run_id != first.run_id


async def test_an_explicit_key_with_a_changed_payload_fails_visibly(scoped) -> None:
    """The issue's visible-failure box: a reused key must never hand back an
    unrelated prior Run."""
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)

    first = await queue.submit(TaskCreate(description="one", idempotency_key="k"), user_id="alice")

    with pytest.raises(IdempotencyKeyMismatch):
        await queue.submit(TaskCreate(description="two", idempotency_key="k"), user_id="alice")

    # The refused submission minted nothing and queued nothing.
    assert first.run_id is not None
    assert await runs.get_run(first.run_id) is not None
    receipts, _cursor = queue.list_tasks(user_id="alice")
    assert [receipt.task_id for receipt in receipts] == [first.task_id]


async def test_the_same_key_across_principals_admits_twice(scoped) -> None:
    """Two callers reusing one textual key: no collision, no shared Run, and
    each principal's claim is unaddressable by the other."""
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)
    request = TaskCreate(description="same payload", idempotency_key="shared-key")

    alices = await queue.submit(request, user_id="alice")
    bobs = await queue.submit(request, user_id="bob")

    assert alices.task_id != bobs.task_id
    assert alices.run_id != bobs.run_id
    # And the scoping cannot be used to read across: bob's key resolves only
    # bob's claim, and the queue's owner check fails the receipt read closed.
    assert queue.get(alices.task_id, user_id="bob") is None
    assert queue.get(bobs.task_id, user_id="alice") is None


async def test_the_scope_uses_the_effective_workspace(scoped) -> None:
    """A retry that arrives without the Workspace header must meet the claim
    its first call made under the default, not mint beside it."""
    projects, runs, _root, _project = scoped
    admitter = WorkspaceRoutingAdmitter(runs, projects, default_workspace_id="w1")
    queue = TaskQueue(admitter=admitter, idempotency_store=InMemoryTaskIdempotencyStore())
    request = TaskCreate(description="routed", idempotency_key="k")

    first = await queue.submit(request, user_id="alice")
    # Second submission names the default Workspace explicitly: same effective
    # Workspace, same scope, same admission.
    retry = await queue.submit(request, user_id="alice", workspace_id="w1")

    assert retry.task_id == first.task_id
    assert retry.run_id == first.run_id


async def test_concurrent_identical_submissions_mint_one_run(scoped) -> None:
    """The issue's concurrency box, deterministic: the two racers meet at one
    claim, and the loser replays the winner's admission."""
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)
    request = TaskCreate(description="race", idempotency_key="same")

    first, second = await asyncio.gather(
        queue.submit(request, user_id="alice"),
        queue.submit(request, user_id="alice"),
    )

    assert first.task_id == second.task_id
    assert first.run_id == second.run_id
    receipts, _cursor = queue.list_tasks(user_id="alice")
    assert len(receipts) == 1
    run_ids = {receipt.run_id for receipt in receipts}
    assert len(run_ids) == 1


async def test_a_failed_admission_releases_its_claim(scoped) -> None:
    """Failure before Run creation stays retryable: the claim must not pin the
    key to an outcome that never happened."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id="no-such-project"),
        idempotency_store=store,
    )
    request = TaskCreate(description="doomed", idempotency_key="k")

    with pytest.raises(Exception):  # noqa: B017 - the admitter's integrity refusal
        await queue.submit(request, user_id="alice")

    scope = admission_scope_key(
        principal="alice", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    assert await store.get(scope) is None

    # A retry after fixing the admitter is a fresh admission, not a replay.
    fixed = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id),
        idempotency_store=store,
    )
    recovered = await fixed.submit(request, user_id="alice")
    assert recovered.run_id is not None


async def test_a_replay_survives_the_receipt_leaving_memory(scoped) -> None:
    """The ambiguous-failure box: process death after `complete` but before the
    caller read the response. A restart empties the queue's tasks; the claim's
    stored request is what reconstructs the receipt, nothing mints — and the
    receipt is re-materialized into the queue the retry landed on, because a
    replay whose Run was stranded outside every queue would reconcile the
    answer while silently losing the work."""
    _projects, runs, _root, project = scoped
    queue, store = _wired_queue(runs, project.project_id)
    request = TaskCreate(description="lost response", tier=3, session_id="s9", idempotency_key="k")

    first = await queue.submit(request, user_id="alice")
    # The restart: a fresh queue over the same claim store, no live receipts.
    restarted = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id),
        idempotency_store=store,
    )

    replay = await restarted.submit(request, user_id="alice")

    assert replay.task_id == first.task_id
    assert replay.run_id == first.run_id
    assert replay.description == "lost response"
    assert replay.tier == 3
    assert replay.session_id == "s9"
    assert replay.user_id == "alice"
    assert replay.status is TaskStatus.QUEUED
    # The Run count did not move: reconciliation, not a second admission — and
    # the reconciled work is executable here, not stranded outside the queue.
    receipts, _cursor = restarted.list_tasks(user_id="alice")
    assert [r.task_id for r in receipts] == [replay.task_id]
    assert await asyncio.wait_for(restarted.next_task(), timeout=1) == replay.task_id


async def test_a_header_only_key_survives_the_restart_replay(scoped) -> None:
    """The receipt-drift regression: the key arrived as an HTTP header, so it
    is in no request body — the stored request must carry it anyway, or a
    restarted deployment answers the same retry with a receipt that has
    forgotten its own key."""
    _projects, runs, _root, project = scoped
    queue, store = _wired_queue(runs, project.project_id)
    request = TaskCreate(description="headered")

    first = await queue.submit(request, user_id="alice", idempotency_key="header-key")
    assert first.idempotency_key == "header-key"

    restarted = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id),
        idempotency_store=store,
    )
    replay = await restarted.submit(request, user_id="alice", idempotency_key="header-key")

    assert replay.task_id == first.task_id
    assert replay.run_id == first.run_id
    assert replay.idempotency_key == "header-key"


async def test_the_admitted_run_carries_the_callers_key_in_provenance(scoped) -> None:
    """An auditor correlating a retry storm reads the Run, so the key the
    caller chose is recorded where the admission it produced lives."""
    _projects, runs, _root, project = scoped
    queue, _store = _wired_queue(runs, project.project_id)

    task = await queue.submit(
        TaskCreate(description="x", idempotency_key="audit-me"), user_id="alice"
    )

    assert task.run_id is not None
    run = await runs.get_run(task.run_id)
    assert run is not None
    assert run.provenance[IDEMPOTENCY_KEY_PROVENANCE] == "audit-me"


async def test_an_unwired_store_leaves_submission_exactly_as_before(scoped) -> None:
    """The deployment that has not grown the claim tier: every call mints,
    keys are echoed but reconcile nothing, and no store exists to consult."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    request = TaskCreate(description="legacy path", idempotency_key="k")

    first = await queue.submit(request, user_id="alice")
    second = await queue.submit(request, user_id="alice")

    assert second.task_id != first.task_id
    assert second.run_id != first.run_id
    assert second.idempotency_key == "k"


async def test_a_pathologically_slow_twin_times_out_visibly(scoped, monkeypatch) -> None:
    """Not the takeover path — a twin that keeps re-claiming through it. The
    bounded wait fails loudly instead of hanging the submission forever."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id),
        idempotency_store=store,
    )

    real_claim = store.claim

    async def always_pending(scope_key: str, **kwargs: object):
        outcome = await real_claim(scope_key, **kwargs)  # type: ignore[arg-type]
        if isinstance(outcome, Replayed):
            record: AdmissionRecord = outcome.record
            return Pending(
                AdmissionRecord(
                    claim_token=record.claim_token,
                    fingerprint=record.fingerprint,
                    request=record.request,
                    task_id=None,
                    run_id=None,
                    completed_at_us=0,
                    created_at_us=record.created_at_us,
                    expires_at_us=record.expires_at_us,
                    lease_expires_at_us=record.lease_expires_at_us,
                )
            )
        return outcome

    monkeypatch.setattr(store, "claim", always_pending)
    monkeypatch.setattr(queue_module, "PENDING_POLL", 0.001)

    first = await queue.submit(TaskCreate(description="x", idempotency_key="k"), user_id="alice")
    assert first.run_id is not None

    with pytest.raises(IdempotencyPendingTimeout, match="bounded wait"):
        await queue.submit(TaskCreate(description="x", idempotency_key="k"), user_id="alice")


def test_pending_poll_bound_covers_the_lease() -> None:
    """The wait bound is sized so a dead twin's claim is *taken over* — not
    merely waited on — before the submitter gives up."""
    assert PENDING_LEASE.total_seconds() <= MAX_PENDING_POLLS * PENDING_POLL


# ── the ambiguous window, end to end through the queue ────────────


class _GatedAdmitter:
    """A TaskRunAdmitter whose FIRST admit can be stalled mid-flight — the
    stand-in for a replica that dies (or pauses past the lease) between
    announcing its receipt and finishing the mint. Later admits pass through;
    the gate models one stalled process, not a broken deployment."""

    def __init__(self, inner: TaskRunAdmitter) -> None:
        self._inner = inner
        self._first = True
        self.mint_entered = asyncio.Event()
        self.release_mint = asyncio.Event()

    async def admit(self, task, *, workspace_id=None):  # type: ignore[no-untyped-def]
        first, self._first = self._first, False
        if first:
            self.mint_entered.set()
            await self.release_mint.wait()
        return await self._inner.admit(task, workspace_id=workspace_id)

    async def record_transition(self, run_id, status, **kwargs):  # type: ignore[no-untyped-def]
        return await self._inner.record_transition(run_id, status, **kwargs)

    async def run_for_task_receipt(self, task_id: str) -> str | None:
        return await self._inner.run_for_task_receipt(task_id)

    @property
    def workspace_id(self) -> str:
        return self._inner.workspace_id


class _Death(BaseException):
    """The stand-in for process death: nothing after it runs."""


async def test_a_takeover_mid_mint_leaves_exactly_one_standing_run(scoped, monkeypatch) -> None:
    """The executed-probe regression, at the lease's own word: a submitter
    stalled inside the mint past the pending lease is superseded, and the
    deterministic outcome is ONE standing Run — the winner's — with the
    superseded mint cancelled, not two live Runs for one key."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    gated = _GatedAdmitter(TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id))
    queue = TaskQueue(admitter=gated, idempotency_store=store)
    request = TaskCreate(description="stalled mid-mint", idempotency_key="k")

    # The lease runs from the announcement; shrink it so the takeover is
    # reachable inside the test, and poll fast enough to reach it.
    monkeypatch.setattr(idempotency_module, "PENDING_LEASE", timedelta(seconds=0.05))
    monkeypatch.setattr(queue_module, "PENDING_POLL", 0.005)

    async def stalled():
        return await queue.submit(request, user_id="alice")

    first_task = asyncio.create_task(stalled())
    await gated.mint_entered.wait()
    # The stall has spanned the (shrunken) lease by the time the twin lands;
    # the twin resolves the ambiguity by discovery and takes the claim over.
    await asyncio.sleep(0.1)
    winner = await queue.submit(request, user_id="alice")
    assert winner.run_id is not None

    gated.release_mint.set()
    superseded = await first_task

    # Both callers hold the SAME receipt: the winner's.
    assert superseded.task_id == winner.task_id
    assert superseded.run_id == winner.run_id
    # The superseded mint was cancelled, the winner's Run stands alone.
    assert superseded.run_id is not None
    standing = {run.run_id: run for run in runs._runs.values()}
    assert standing[winner.run_id].status is RunStatus.QUEUED
    superseded_runs = [
        run
        for run in standing.values()
        if run.run_id != winner.run_id and run.provenance.get("task_id") is not None
    ]
    assert superseded_runs, "the stalled mint must have left its Run behind to cancel"
    assert all(run.status is RunStatus.CANCELLED for run in superseded_runs)
    # And the queue holds one receipt, reconciled to the winner.
    receipts, _cursor = queue.list_tasks(user_id="alice")
    assert [r.task_id for r in receipts] == [winner.task_id]


async def test_a_death_after_the_mint_resolves_to_the_existing_run(scoped, monkeypatch) -> None:
    """The ambiguous-failure acceptance, executed: a claimant that minted the
    Run and died before recording it leaves a begun claim whose lease lapses.
    The retry discovers the minted Run through the announced receipt and
    reconciles to it — no second Run, not even a cancelled one."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter, idempotency_store=store)
    request = TaskCreate(description="died after the mint", idempotency_key="k")

    monkeypatch.setattr(idempotency_module, "PENDING_LEASE", timedelta(seconds=0.05))
    monkeypatch.setattr(queue_module, "PENDING_POLL", 0.005)

    async def complete_then_die(scope_key: str, **kwargs: object):
        # Simulate the process dying in the instant after the Run was minted
        # but before the outcome was recorded: the write never lands, and the
        # receipt is never enqueued (the enqueue below never runs either).
        return True

    async def _silent_noop(_task: object) -> None:
        return None

    real_complete = store.complete
    monkeypatch.setattr(store, "complete", complete_then_die)
    monkeypatch.setattr(queue, "_enqueue", _silent_noop)
    corpse = await queue.submit(request, user_id="alice")
    assert corpse.run_id is not None
    assert await runs.get_run(corpse.run_id) is not None
    monkeypatch.setattr(store, "complete", real_complete)

    # A fresh process (fresh queue, same claim store) answers the retry.
    restarted = TaskQueue(admitter=admitter, idempotency_store=store)
    replay = await restarted.submit(request, user_id="alice")

    assert replay.task_id == corpse.task_id
    assert replay.run_id == corpse.run_id
    # The claim now carries the discovered outcome, so later replays skip
    # discovery entirely.
    record = await store.get(
        admission_scope_key(
            principal="alice", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
        )
    )
    assert record is not None and record.admitted is True
    runs_named = [
        run for run in runs._runs.values() if run.provenance.get("task_id") == corpse.task_id
    ]
    assert [run.run_id for run in runs_named] == [corpse.run_id]


async def test_ambiguous_resolution_rechecks_a_claim_that_lost_a_race(scoped, monkeypatch) -> None:
    """A discovery result can race a takeover by another retry.

    If resolution loses that race, the row is temporarily non-admitted. The
    retry must not return the stale begun receipt (with no Run) while the new
    claimant is still admitting; it must re-read until the winner's outcome is
    available.
    """
    _projects, _runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    admitter = TaskRunAdmitter(_runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter, idempotency_store=store)
    request = TaskCreate(description="racing ambiguous resolution", idempotency_key="k")
    scope = admission_scope_key(
        principal="alice", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    stale = datetime.now(UTC) - PENDING_LEASE - timedelta(seconds=1)
    stored_request = json.dumps(
        request.model_copy(update={"user_id": "alice", "idempotency_key": "k"}).model_dump(
            mode="json"
        )
    )
    claimed = await store.claim(
        scope,
        fingerprint=request_fingerprint(request),
        request=stored_request,
        now=stale,
    )
    assert isinstance(claimed, Claimed)
    old_task_id = TaskResponse.new_id()
    assert await store.begin(scope, token=claimed.token, task_id=old_task_id, now=stale)

    async def discover(_task_id: str) -> str:
        # The old claimant did mint a Run, but another retry takes over before
        # this caller can record the discovered Run on the claim.
        return "old-run"

    monkeypatch.setattr(admitter, "run_for_task_receipt", discover)
    winner_done = asyncio.Event()

    async def racing_resolve(scope_key: str, *, task_id: str, run_id: str) -> bool:
        current = await store.get(scope_key)
        assert current is not None
        takeover = await store.take_over_resolved(
            scope_key,
            task_id=task_id,
            fingerprint=current.fingerprint,
            request=current.request,
            now=datetime.now(UTC),
        )
        assert isinstance(takeover, Claimed)

        async def finish_winner() -> None:
            await asyncio.sleep(0.01)
            now = datetime.now(UTC)
            assert await store.begin(
                scope_key, token=takeover.token, task_id="winner-task", now=now
            )
            assert await store.complete(
                scope_key, token=takeover.token, task_id="winner-task", run_id="winner-run"
            )
            winner_done.set()

        winner_task = asyncio.create_task(finish_winner())
        winner_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return False

    monkeypatch.setattr(store, "resolve_run", racing_resolve)
    replay = await queue.submit(request, user_id="alice")
    await asyncio.wait_for(winner_done.wait(), timeout=1)

    assert replay.task_id == "winner-task"
    assert replay.run_id == "winner-run"


async def test_a_crash_between_mint_and_queue_is_resumed_not_stranded(scoped) -> None:
    """The crash-after-create probe: a claimant that died in the instant after
    minting the Run but before it was queued left canonical state no retry
    could execute — the claim reconciled to a Run still sitting at CREATED,
    the replayed receipt said ``queued``, and the queue the retry landed on
    held nothing, so the reconciled work was stranded past every queue. The
    reconciliation now finishes the crash victim's own last step: a Run still
    CREATED is moved to QUEUED and the receipt lands in the reconciling
    process's queue, so the retry hands the work to a runner instead of
    narrating a corpse."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    request = TaskCreate(description="crashed between mint and queue", idempotency_key="k")
    task_id = TaskResponse.new_id()
    scope = admission_scope_key(
        principal="alice", workspace_id="w1", action=TASK_SUBMIT_ACTION, key="k"
    )
    # The corpse's durable state, exactly as the crash left it: a begun claim
    # (receipt announced, outcome never recorded) an hour dead — past its
    # pending lease, inside the replay window — and the Run the mint produced,
    # still CREATED because the QUEUED transition never ran.
    claimed = await store.claim(
        scope,
        fingerprint=request_fingerprint(request),
        request=json.dumps(
            request.model_copy(update={"user_id": "alice", "idempotency_key": "k"}).model_dump(
                mode="json"
            )
        ),
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    assert isinstance(claimed, Claimed)
    assert await store.begin(
        scope, token=claimed.token, task_id=task_id, now=datetime.now(UTC) - timedelta(hours=1)
    )
    work = resolve_direct_work(description=request.description)
    run = await admit_direct_work(
        runs,
        workspace_id="w1",
        project_id=project.project_id,
        node_type=work.node_type,
        name=work.name,
        source=TASK_QUEUE_SOURCE,
        description=request.description,
        provenance={TASK_ID_KEY: task_id},
    )
    assert run.status is RunStatus.CREATED

    # A fresh process (fresh queue, same durable claim store and Run store)
    # answers the retry.
    restarted = TaskQueue(admitter=admitter, idempotency_store=store)
    replay = await restarted.submit(request, user_id="alice")

    # The same admission, reconciled — not a second one.
    assert replay.task_id == task_id
    assert replay.run_id == run.run_id
    resumed = await runs.get_run(run.run_id)
    assert resumed is not None
    assert resumed.status is RunStatus.QUEUED
    # The receipt is not stranded: this queue hands the work to a runner.
    assert await asyncio.wait_for(restarted.next_task(), timeout=1) == task_id
    # Exactly one Run names the receipt.
    runs_named = [r for r in runs._runs.values() if r.provenance.get("task_id") == task_id]
    assert [r.run_id for r in runs_named] == [run.run_id]


async def test_a_run_already_past_queuing_is_not_reenqueued_by_a_replay(scoped) -> None:
    """The resume gate's refusal edge: a replay of an admission whose Run has
    already been picked up (RUNNING) must return the receipt without
    re-enqueueing it — the work is somebody's live execution, and a second
    queue entry would be exactly the duplicate the issue forbids."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter, idempotency_store=store)
    request = TaskCreate(description="already running elsewhere", idempotency_key="k")

    corpse = await queue.submit(request, user_id="alice")
    assert corpse.run_id is not None
    # The receipt left this process (a replica took the execution over).
    queue._tasks.pop(corpse.task_id)
    assert await runs.transition_run(corpse.run_id, RunStatus.RUNNING)

    restarted = TaskQueue(admitter=admitter, idempotency_store=store)
    replay = await restarted.submit(request, user_id="alice")
    assert replay.task_id == corpse.task_id
    assert replay.run_id == corpse.run_id
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(restarted.next_task(), timeout=0.1)


async def test_a_death_before_the_mint_takes_over_without_a_duplicate(scoped, monkeypatch) -> None:
    """A claimant that announced its receipt and died before minting leaves
    nothing to discover: the resolved takeover mints fresh, once."""
    _projects, runs, _root, project = scoped
    store = InMemoryTaskIdempotencyStore()
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter, idempotency_store=store)
    request = TaskCreate(description="died before the mint", idempotency_key="k")

    monkeypatch.setattr(idempotency_module, "PENDING_LEASE", timedelta(seconds=0.05))
    monkeypatch.setattr(queue_module, "PENDING_POLL", 0.005)

    real_begin = store.begin

    async def begin_then_die(scope_key: str, **kwargs: object):
        # The announcement lands; the process dies before minting anything.
        await real_begin(scope_key, **kwargs)  # type: ignore[arg-type]
        raise _Death()

    monkeypatch.setattr(store, "begin", begin_then_die)
    with pytest.raises(_Death):
        await queue.submit(request, user_id="alice")
    monkeypatch.setattr(store, "begin", real_begin)

    # The corpse's claim: begun, no Run, lease lapsed. A fresh process's
    # retry resolves the ambiguity by discovery (no Run names the receipt)
    # and takes the claim over — minting exactly one Run.
    restarted = TaskQueue(admitter=admitter, idempotency_store=store)
    retry = await restarted.submit(request, user_id="alice")
    assert retry.run_id is not None
    runs_named = [run for run in runs._runs.values() if run.provenance.get("task_id") is not None]
    assert [run.run_id for run in runs_named] == [retry.run_id]
