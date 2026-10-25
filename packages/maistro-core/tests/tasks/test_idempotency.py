"""Task admission idempotency (#1176).

The contract has four edges, and the issue holds each one separately: a key
scoped so it cannot collide or leak across principals and Workspaces; a replay
that reconciles to the original admission inside a documented window instead
of minting a second Run; a payload mismatch that fails visibly; and
concurrency where identical submissions deterministically produce one Run.
These tests hold the in-memory claim store and the queue integration to all
four, plus the failure-ordering rule: a failed admission must release its
claim, or the retry would reconcile against an outcome that never happened.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro.tasks import queue as queue_module
from maistro.tasks.admission import TaskRunAdmitter, WorkspaceRoutingAdmitter
from maistro.tasks.idempotency import (
    DEFAULT_REPLAY_WINDOW,
    IDEMPOTENCY_KEY_PROVENANCE,
    MAX_PENDING_POLLS,
    PENDING_LEASE,
    PENDING_POLL,
    TASK_SUBMIT_ACTION,
    AdmissionRecord,
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
from maistro.tasks.models import TaskCreate, TaskStatus
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


def _record_fingerprint(store: InMemoryTaskIdempotencyStore, scope: str) -> str:
    record = store._rows.get(scope)
    assert record is not None
    return record.fingerprint


async def test_claim_complete_then_replay() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    first = await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert isinstance(first, Claimed)
    assert await store.complete(scope, task_id="t1", run_id="r1") is True

    replay = await store.claim(
        scope, fingerprint="fp", request="{}", now=_NOW + timedelta(minutes=1)
    )
    assert isinstance(replay, Replayed)
    assert replay.record.task_id == "t1"
    assert replay.record.run_id == "r1"


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

    await store.claim(scope, fingerprint="fp-one", request="{}", now=_NOW)
    await store.complete(scope, task_id="t1", run_id="r1")

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

    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    await store.complete(scope, task_id="t1", run_id="r1")

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
    await store.claim(other_scope, fingerprint="fp", request="{}", now=_NOW)
    await store.complete(other_scope, task_id="t3", run_id="r3")
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


# ── the shared claim flow under interleaving ──────────────────────


def _scope(key: str) -> str:
    return admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key=key)


def _mid_admission_record(created: datetime) -> AdmissionRecord:
    """A pending claim: no receipt yet, lease still running from ``created``."""
    return AdmissionRecord(
        fingerprint="fp",
        request="{}",
        task_id=None,
        run_id=None,
        created_at_us=int(created.timestamp() * 1_000_000),
        expires_at_us=int((created + DEFAULT_REPLAY_WINDOW).timestamp() * 1_000_000),
        lease_expires_at_us=int((created + PENDING_LEASE).timestamp() * 1_000_000),
    )


def _expired_record(created: datetime) -> AdmissionRecord:
    """A claim whose replay window is long gone — deletable, take-overable."""
    return AdmissionRecord(
        fingerprint="fp",
        request="{}",
        task_id=None,
        run_id=None,
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
            # before its takeover lands.
            await store.release(scope_key)
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


async def test_release_returns_a_failed_admissions_claim() -> None:
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert await store.release(scope) is True
    assert await store.get(scope) is None
    # A retry claims fresh, with no memory of the failure.
    assert isinstance(await store.claim(scope, fingerprint="fp", request="{}", now=_NOW), Claimed)


async def test_release_and_complete_refuse_to_touch_a_completed_claim() -> None:
    """The guards keep an owner from rewriting an outcome that already landed,
    and from releasing a claim another submission has taken over."""
    store = InMemoryTaskIdempotencyStore()
    scope = admission_scope_key(principal="u", workspace_id="w", action=TASK_SUBMIT_ACTION, key="k")

    await store.claim(scope, fingerprint="fp", request="{}", now=_NOW)
    assert await store.complete(scope, task_id="t1", run_id="r1") is True
    assert await store.complete(scope, task_id="t9", run_id="r9") is False
    assert await store.release(scope) is False


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


async def test_the_bound_evicts_expired_claims_first() -> None:
    """Past ``_MAX_ENTRIES`` the store sheds load: expired claims go first —
    evicting one is merely early window expiry — and the claim being admitted
    now survives with the bound restored."""
    store = InMemoryTaskIdempotencyStore()
    wall = datetime.now(UTC)
    ancient = wall - timedelta(hours=48)
    for i in range(store._MAX_ENTRIES + 2):
        store._rows[_scope(f"ancient-{i}")] = _expired_record(ancient + timedelta(seconds=i))

    outcome = await store.claim(_scope("fresh"), fingerprint="fp", request="{}", now=wall)

    assert isinstance(outcome, Claimed)
    assert len(store._rows) == store._MAX_ENTRIES
    assert _scope("fresh") in store._rows
    # The three oldest-created expired claims are the ones that went.
    assert _scope("ancient-0") not in store._rows
    assert _scope("ancient-1") not in store._rows
    assert _scope("ancient-2") not in store._rows
    assert _scope("ancient-3") in store._rows
    assert _scope(f"ancient-{store._MAX_ENTRIES + 1}") in store._rows


async def test_the_bound_evicts_the_oldest_when_nothing_is_expired() -> None:
    """Nothing has expired but the store is over its bound: the oldest claims
    go — the same bound the in-memory Run store applies — and the claim being
    admitted now survives."""
    store = InMemoryTaskIdempotencyStore()
    wall = datetime.now(UTC)
    for i in range(store._MAX_ENTRIES + 2):
        # Millisecond-staggered creation inside the last few seconds, so every
        # row is live and `ancient-0`-style ordering is exact: i=0 is oldest.
        store._rows[_scope(f"live-{i}")] = _mid_admission_record(
            wall - timedelta(milliseconds=store._MAX_ENTRIES + 2 - i)
        )

    outcome = await store.claim(_scope("fresh"), fingerprint="fp", request="{}", now=wall)

    assert isinstance(outcome, Claimed)
    assert len(store._rows) == store._MAX_ENTRIES
    assert _scope("fresh") in store._rows
    assert _scope("live-0") not in store._rows
    assert _scope("live-1") not in store._rows
    assert _scope("live-2") not in store._rows
    assert _scope("live-3") in store._rows
    assert _scope(f"live-{store._MAX_ENTRIES + 1}") in store._rows


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
    stored request is what reconstructs the receipt, and nothing mints."""
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
    # And the Run count did not move: reconciliation, not a second admission.
    receipts, _cursor = restarted.list_tasks(user_id="alice")
    assert receipts == []


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
                    fingerprint=record.fingerprint,
                    request=record.request,
                    task_id=None,
                    run_id=None,
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
