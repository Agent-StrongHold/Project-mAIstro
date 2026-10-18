"""Durable Goal reconciliation store (M3 #806).

One store owns every control fact the reconciliation loop needs to survive
restarts and concurrent MAIstro processes: the canonical Goal row, the one
claim/lease/fence per Goal, deduplicated wake facts, and idempotent
admission records. In-memory and SQLite twins implement the same protocol;
the SQLite twin uses ``BEGIN IMMEDIATE`` compare-and-set so two processes
sharing one database serialize exactly like the single-loop in-memory twin.

This is the #806 control-plane table set (``goals``/``goal_claims``/
``goal_wakes``/``goal_admissions``), distinct from #1572's canonical Goal
store (``canonical_goals``/``canonical_goal_revisions``/
``canonical_goal_transitions``); composing the control loop directly on
#1572's Goal record is tracked for the #805/#804 activation round.

Nothing here is an execution authority: admission records name canonical
artifacts (``physical_ref``), they do not create or own Runs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.goals.reconciliation.model import (
    Goal,
    GoalAdmission,
    GoalClaim,
    GoalStatus,
    WakeFact,
    WakeReason,
    coerce_datetime,
    default_lease_ttl,
    wake_id_for,
)

if TYPE_CHECKING:
    import aiosqlite

from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

__all__ = [
    "GoalBudgetExhausted",
    "GoalCancelled",
    "GoalDeadlinePassed",
    "GoalReconciliationError",
    "GoalReconciliationStore",
    "InMemoryGoalStore",
    "SqliteGoalStore",
    "StaleGoalFence",
]


class GoalReconciliationError(Exception):
    """Base class for Goal reconciliation control-plane failures."""


class StaleGoalFence(GoalReconciliationError):
    """A control write or admission used a superseded/expired fencing token.

    This is the stale-owner guard: after a holder loses or expires its
    claim, every token it still holds is stale and cannot admit a later Run
    even if its process keeps running.
    """


class GoalCancelled(GoalReconciliationError):
    """The Goal was cancelled; admission is fenced across restarts."""


class GoalDeadlinePassed(GoalReconciliationError):
    """The Goal-level deadline passed; no further admission."""


class GoalBudgetExhausted(GoalReconciliationError):
    """The Goal-level admission budget is spent; no further admission."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


@runtime_checkable
class GoalReconciliationStore(Protocol):
    """Durable Goal + claim/lease/fence + wake + admission facts."""

    async def ensure_schema(self) -> None: ...

    async def create_goal(self, goal: Goal) -> Goal: ...

    async def get_goal(self, goal_id: str) -> Goal | None: ...

    async def cancel_goal(self, goal_id: str, reason: str) -> Goal:
        """Durably cancel a Goal; fences admission across restarts."""
        ...

    async def non_terminal_goals(self) -> list[Goal]:
        """Goals the control loop still owns (restart reconstruction)."""
        ...

    async def due_goals(self, now: datetime, limit: int) -> list[Goal]:
        """Sleeping/active Goals whose bounded sweep horizon has passed.

        The safety sweep reads only this bounded, indexed set — it never
        polls every Goal.
        """
        ...

    async def record_wake(
        self,
        goal_id: str,
        *,
        reason: WakeReason,
        correlation_id: str = "",
        unblocks: bool = False,
        now: datetime | None = None,
    ) -> WakeFact | None:
        """Record a durable wake fact, deduplicated by (goal, correlation).

        Returns ``None`` when the same correlation already woke this Goal —
        duplicate/replayed Event delivery collapses to one fact.
        """
        ...

    async def claim(
        self,
        goal_id: str,
        *,
        holder: str,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> GoalClaim | None:
        """Take or renew the one claim; ``None`` while another holder is live."""
        ...

    async def release_claim(self, goal_id: str, *, fencing_token: str) -> bool: ...

    async def reclaim_expired(self, now: datetime, limit: int) -> list[Goal]:
        """Release lapsed leases and wake their Goals (bounded)."""
        ...

    async def admit(
        self,
        goal_id: str,
        *,
        fencing_token: str,
        decision_key: str,
        kind: str = "run",
        correlation_id: str = "",
        now: datetime | None = None,
    ) -> tuple[GoalAdmission, bool]:
        """Fenced, idempotent admission of next work.

        Raises :class:`StaleGoalFence` for a non-current token,
        :class:`GoalCancelled`/:class:`GoalDeadlinePassed`/
        :class:`GoalBudgetExhausted` for Goal-level stop conditions.
        Returns ``(admission, created)``; ``created`` is ``False`` when the
        ``decision_key`` was already admitted (duplicate decision).
        """
        ...

    async def complete_admission(
        self, admission_id: str, *, physical_ref: str, now: datetime | None = None
    ) -> bool:
        """Idempotently attach the canonical artifact an admission produced."""
        ...

    async def pending_admissions(
        self, goal_id: str | None = None, limit: int = 100
    ) -> list[GoalAdmission]:
        """Admissions not yet attached to a canonical artifact (restart repair set)."""
        ...

    async def pending_wakes(self, goal_id: str | None = None, limit: int = 100) -> list[WakeFact]:
        """Undispatched wake facts (durable; survives process death)."""
        ...

    async def mark_wakes_dispatched(
        self, wake_ids: list[str], *, now: datetime | None = None
    ) -> int: ...

    async def sleep_goal(
        self,
        goal_id: str,
        *,
        status: GoalStatus,
        fencing_token: str,
        awake_after: datetime | None = None,
        blocked_reason: str | None = None,
        now: datetime | None = None,
    ) -> Goal:
        """Park a Goal in a sleep state until a relevant change or the sweep."""
        ...

    async def finish_goal(
        self, goal_id: str, *, fencing_token: str, now: datetime | None = None
    ) -> Goal: ...

    async def reconciliation_view(self, goal_id: str) -> dict[str, object] | None:
        """Derived control metadata for inspection — not an execution lifecycle."""
        ...


class InMemoryGoalStore:
    """In-memory :class:`GoalReconciliationStore`.

    Used from one event loop: like ``runs.consumer_claim``, there is no
    ``await`` between the read and the writes of each fenced operation, so
    each operation is atomic with respect to other tasks.
    """

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}
        self._claims: dict[str, GoalClaim] = {}
        self._wakes: dict[str, WakeFact] = {}
        self._admissions: dict[tuple[str, str], GoalAdmission] = {}
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        return None

    async def create_goal(self, goal: Goal) -> Goal:
        async with self._lock:
            if goal.goal_id in self._goals:
                raise GoalReconciliationError(f"Goal {goal.goal_id!r} already exists")
            self._goals[goal.goal_id] = goal
            return goal

    async def get_goal(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    async def cancel_goal(self, goal_id: str, reason: str) -> Goal:
        async with self._lock:
            goal = self._require_goal(goal_id)
            goal = goal.model_copy(
                update={
                    "status": GoalStatus.WITHDRAWN,
                    "cancelled_reason": reason,
                    "awake_after": None,
                    "updated_at": _utcnow(),
                }
            )
            self._goals[goal_id] = goal
            self._claims.pop(goal_id, None)
            return goal

    async def non_terminal_goals(self) -> list[Goal]:
        terminal = GoalStatus.terminal()
        return [g for g in self._goals.values() if g.status not in terminal]

    async def due_goals(self, now: datetime, limit: int) -> list[Goal]:
        terminal = GoalStatus.terminal()
        due = [
            g
            for g in self._goals.values()
            if g.status not in terminal and g.awake_after is not None and g.awake(now)
        ]
        return sorted(due, key=lambda g: g.awake_after or now)[:limit]

    async def record_wake(
        self,
        goal_id: str,
        *,
        reason: WakeReason,
        correlation_id: str = "",
        unblocks: bool = False,
        now: datetime | None = None,
    ) -> WakeFact | None:
        async with self._lock:
            goal = self._require_goal(goal_id)
            at = now or _utcnow()
            effective = correlation_id or f"manual:{uuid_hex()}"
            wake_id = wake_id_for(goal_id, effective)
            if wake_id in self._wakes:
                return None
            wake = WakeFact(
                wake_id=wake_id,
                goal_id=goal.goal_id,
                reason=reason,
                correlation_id=effective,
                unblocks=unblocks or reason is WakeReason.MANUAL,
                created_at=at,
            )
            self._wakes[wake_id] = wake
            # A relevant wake makes the Goal due for the bounded sweep: a
            # process that dies between recording the fact and reconciling it
            # loses nothing — the sweep re-derives from the durable fact
            # (AC: a missed notification is repaired by the sweep). Sleeping
            # postures stay asleep for non-unblocking wakes, so a blocked or
            # dormant Goal still consumes no decision until a relevant change.
            if goal.status not in GoalStatus.terminal() and (
                wake.unblocks or goal.status not in GoalStatus.sleeping()
            ):
                self._goals[goal_id] = goal.model_copy(update={"awake_after": at, "updated_at": at})
            return wake

    async def claim(
        self,
        goal_id: str,
        *,
        holder: str,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> GoalClaim | None:
        async with self._lock:
            goal = self._require_goal(goal_id)
            if goal.status in GoalStatus.terminal():
                return None
            at = now or _utcnow()
            existing = self._claims.get(goal_id)
            if existing is not None and not existing.lapsed(at) and existing.holder != holder:
                return None
            claim = GoalClaim(
                goal_id=goal_id,
                holder=holder,
                fence_epoch=(existing.fence_epoch + 1) if existing else 1,
                acquired_at=at,
                expires_at=at + (ttl or default_lease_ttl()),
            )
            self._claims[goal_id] = claim
            return claim

    async def release_claim(self, goal_id: str, *, fencing_token: str) -> bool:
        async with self._lock:
            existing = self._claims.get(goal_id)
            if existing is None or existing.fencing_token != fencing_token:
                return False
            del self._claims[goal_id]
            return True

    async def reclaim_expired(self, now: datetime, limit: int) -> list[Goal]:
        async with self._lock:
            lapsed = [
                claim
                for claim in self._claims.values()
                if claim.lapsed(now)
                and self._goals[claim.goal_id].status not in GoalStatus.terminal()
            ]
            woken: list[Goal] = []
            for claim in sorted(lapsed, key=lambda c: c.expires_at or now)[:limit]:
                del self._claims[claim.goal_id]
                goal = self._goals[claim.goal_id].model_copy(
                    update={"awake_after": now, "updated_at": now}
                )
                self._goals[goal.goal_id] = goal
                woken.append(goal)
            return woken

    async def admit(
        self,
        goal_id: str,
        *,
        fencing_token: str,
        decision_key: str,
        kind: str = "run",
        correlation_id: str = "",
        now: datetime | None = None,
    ) -> tuple[GoalAdmission, bool]:
        async with self._lock:
            goal = self._require_goal(goal_id)
            at = now or _utcnow()
            # Duplicate decisions dedupe before the fence: a replayed decision
            # key must resolve to the recorded admission even from a holder
            # that has since lost its claim (restart/takeover convergence).
            existing = self._admissions.get((goal_id, decision_key))
            if existing is not None:
                return existing, False
            self._require_current_claim(goal_id, fencing_token, at)
            self._check_gates(goal, at)
            admission = GoalAdmission(
                goal_id=goal_id,
                revision=goal.revision,
                fence_epoch=self._claims[goal_id].fence_epoch,
                decision_key=decision_key,
                kind=kind,
                correlation_id=correlation_id,
                admitted_at=at,
            )
            self._admissions[(goal_id, decision_key)] = admission
            goal = goal.model_copy(
                update={"runs_admitted": goal.runs_admitted + 1, "updated_at": at}
            )
            self._goals[goal_id] = goal
            return admission, True

    async def complete_admission(
        self, admission_id: str, *, physical_ref: str, now: datetime | None = None
    ) -> bool:
        async with self._lock:
            for admission in self._admissions.values():
                if admission.admission_id == admission_id:
                    if admission.completed_at is not None:
                        return False
                    at = now or _utcnow()
                    self._admissions[(admission.goal_id, admission.decision_key)] = (
                        admission.model_copy(
                            update={"completed_at": at, "physical_ref": physical_ref}
                        )
                    )
                    return True
            return False

    async def pending_admissions(
        self, goal_id: str | None = None, limit: int = 100
    ) -> list[GoalAdmission]:
        open_admissions = [a for a in self._admissions.values() if a.completed_at is None]
        if goal_id is not None:
            open_admissions = [a for a in open_admissions if a.goal_id == goal_id]
        return sorted(open_admissions, key=lambda a: a.admitted_at)[:limit]

    async def pending_wakes(self, goal_id: str | None = None, limit: int = 100) -> list[WakeFact]:
        wakes = [w for w in self._wakes.values() if w.dispatched_at is None]
        if goal_id is not None:
            wakes = [w for w in wakes if w.goal_id == goal_id]
        return sorted(wakes, key=lambda w: w.created_at)[:limit]

    async def mark_wakes_dispatched(
        self, wake_ids: list[str], *, now: datetime | None = None
    ) -> int:
        async with self._lock:
            at = now or _utcnow()
            marked = 0
            for wake_id in wake_ids:
                wake = self._wakes.get(wake_id)
                if wake is not None and wake.dispatched_at is None:
                    self._wakes[wake_id] = wake.model_copy(update={"dispatched_at": at})
                    marked += 1
            return marked

    async def sleep_goal(
        self,
        goal_id: str,
        *,
        status: GoalStatus,
        fencing_token: str,
        awake_after: datetime | None = None,
        blocked_reason: str | None = None,
        now: datetime | None = None,
    ) -> Goal:
        async with self._lock:
            goal = self._require_goal(goal_id)
            at = now or _utcnow()
            self._require_current_claim(goal_id, fencing_token, at)
            if status not in GoalStatus.sleeping():
                raise GoalReconciliationError(f"sleep_goal takes a sleeping status, got {status!r}")
            goal = goal.model_copy(
                update={
                    "status": status,
                    "awake_after": awake_after,
                    "blocked_reason": blocked_reason,
                    "updated_at": at,
                }
            )
            self._goals[goal_id] = goal
            return goal

    async def finish_goal(
        self, goal_id: str, *, fencing_token: str, now: datetime | None = None
    ) -> Goal:
        async with self._lock:
            goal = self._require_goal(goal_id)
            at = now or _utcnow()
            self._require_current_claim(goal_id, fencing_token, at)
            goal = goal.model_copy(
                update={"status": GoalStatus.SETTLED, "awake_after": None, "updated_at": at}
            )
            self._goals[goal_id] = goal
            self._claims.pop(goal_id, None)
            return goal

    async def reconciliation_view(self, goal_id: str) -> dict[str, object] | None:
        async with self._lock:
            goal = self._goals.get(goal_id)
            if goal is None:
                return None
            claim = self._claims.get(goal_id)
            wakes = [w for w in self._wakes.values() if w.goal_id == goal_id]
            admissions = [a for a in self._admissions.values() if a.goal_id == goal_id]
            return {
                "goal_id": goal.goal_id,
                "revision": goal.revision,
                "status": goal.status.value,
                "runs_admitted": goal.runs_admitted,
                "budget_max_runs": goal.budget_max_runs,
                "deadline_at": goal.deadline_at,
                "awake_after": goal.awake_after,
                "blocked_reason": goal.blocked_reason,
                "claim": {
                    "holder": claim.holder,
                    "fence_epoch": claim.fence_epoch,
                    "expires_at": claim.expires_at,
                }
                if claim
                else None,
                "pending_wakes": sum(1 for w in wakes if w.dispatched_at is None),
                "open_admissions": sum(1 for a in admissions if a.completed_at is None),
                "admissions_total": len(admissions),
            }

    # -- internals ---------------------------------------------------------

    def _require_goal(self, goal_id: str) -> Goal:
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalReconciliationError(f"unknown Goal {goal_id!r}")
        return goal

    def _require_current_claim(self, goal_id: str, fencing_token: str, at: datetime) -> GoalClaim:
        claim = self._claims.get(goal_id)
        if claim is None or claim.fencing_token != fencing_token or claim.lapsed(at):
            raise StaleGoalFence(
                f"fencing token for Goal {goal_id!r} is not current "
                f"(epoch {claim.fence_epoch if claim else 'none'})"
            )
        return claim

    def _check_gates(self, goal: Goal, at: datetime) -> None:
        if goal.status is GoalStatus.WITHDRAWN:
            raise GoalCancelled(f"Goal {goal.goal_id!r} is cancelled")
        if goal.deadline_passed(at):
            raise GoalDeadlinePassed(f"Goal {goal.goal_id!r} deadline passed at {goal.deadline_at}")
        if goal.budget_exhausted():
            raise GoalBudgetExhausted(
                f"Goal {goal.goal_id!r} budget exhausted ({goal.runs_admitted}/{goal.budget_max_runs})"
            )


def uuid_hex() -> str:
    from uuid import uuid4

    return uuid4().hex


_GOALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    owning_agent_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'ready',
    runs_admitted INTEGER NOT NULL DEFAULT 0,
    budget_max_runs INTEGER,
    deadline_at TEXT,
    stop_condition TEXT,
    blocked_reason TEXT,
    awake_after TEXT,
    cancelled_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goals_awake_after ON goals(awake_after);
CREATE TABLE IF NOT EXISTS goal_claims (
    goal_id TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    fence_epoch INTEGER NOT NULL,
    fencing_token TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS goal_wakes (
    wake_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    correlation_id TEXT NOT NULL DEFAULT '',
    unblocks INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    dispatched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_goal_wakes_dispatch ON goal_wakes(dispatched_at);
CREATE TABLE IF NOT EXISTS goal_admissions (
    admission_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    fence_epoch INTEGER NOT NULL,
    decision_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'run',
    correlation_id TEXT NOT NULL DEFAULT '',
    admitted_at TEXT NOT NULL,
    completed_at TEXT,
    physical_ref TEXT,
    UNIQUE (goal_id, decision_key)
);
CREATE INDEX IF NOT EXISTS idx_goal_admissions_open ON goal_admissions(completed_at);
"""

_GOAL_COLUMNS = (
    "goal_id, workspace_id, project_id, owning_agent_id, revision, status, runs_admitted,"
    " budget_max_runs, deadline_at, stop_condition, blocked_reason, awake_after,"
    " cancelled_reason, created_at, updated_at"
)


def _goal_from_row(row: Any) -> Goal:
    (
        goal_id,
        workspace_id,
        project_id,
        owning_agent_id,
        revision,
        status,
        runs_admitted,
        budget_max_runs,
        deadline_at,
        stop_condition,
        blocked_reason,
        awake_after,
        cancelled_reason,
        created_at,
        updated_at,
    ) = row
    return Goal(
        goal_id=goal_id,
        workspace_id=workspace_id,
        project_id=project_id,
        owning_agent_id=owning_agent_id,
        revision=int(revision),
        status=GoalStatus(status),
        runs_admitted=int(runs_admitted),
        budget_max_runs=int(budget_max_runs) if budget_max_runs is not None else None,
        deadline_at=coerce_datetime(deadline_at) if deadline_at else None,
        stop_condition=stop_condition,
        blocked_reason=blocked_reason,
        awake_after=coerce_datetime(awake_after) if awake_after else None,
        cancelled_reason=cancelled_reason,
        created_at=coerce_datetime(created_at),
        updated_at=coerce_datetime(updated_at),
    )


def _goal_params(goal: Goal) -> tuple[Any, ...]:
    return (
        goal.goal_id,
        goal.workspace_id,
        goal.project_id,
        goal.owning_agent_id,
        goal.revision,
        goal.status.value,
        goal.runs_admitted,
        goal.budget_max_runs,
        _iso(goal.deadline_at) if goal.deadline_at else None,
        goal.stop_condition,
        goal.blocked_reason,
        _iso(goal.awake_after) if goal.awake_after else None,
        goal.cancelled_reason,
        _iso(goal.created_at),
        _iso(goal.updated_at),
    )


class SqliteGoalStore:
    """SQLite :class:`GoalReconciliationStore`.

    Claim and admission are ``BEGIN IMMEDIATE`` compare-and-set transactions:
    two processes sharing one database cannot both hold the claim or admit
    the same decision key, exactly like two tasks on the in-memory twin.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _GOALS_SCHEMA)

    async def create_goal(self, goal: Goal) -> Goal:
        await self._conn.execute(
            f"INSERT INTO goals ({_GOAL_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _goal_params(goal),
        )
        await self._conn.commit()
        return goal

    async def get_goal(self, goal_id: str) -> Goal | None:
        async with self._conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM goals WHERE goal_id = ?", (goal_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return _goal_from_row(row) if row else None

    async def cancel_goal(self, goal_id: str, reason: str) -> Goal:
        await self._conn.execute(
            """UPDATE goals SET status = 'withdrawn', cancelled_reason = ?,
               awake_after = NULL, updated_at = ? WHERE goal_id = ?""",
            (reason, _iso(_utcnow()), goal_id),
        )
        await self._conn.execute("DELETE FROM goal_claims WHERE goal_id = ?", (goal_id,))
        await self._conn.commit()
        goal = await self.get_goal(goal_id)
        assert goal is not None
        return goal

    async def non_terminal_goals(self) -> list[Goal]:
        async with self._conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM goals WHERE status NOT IN ('withdrawn', 'settled')"
        ) as cursor:
            rows = await cursor.fetchall()
        return [_goal_from_row(row) for row in rows]

    async def due_goals(self, now: datetime, limit: int) -> list[Goal]:
        async with self._conn.execute(
            f"""SELECT {_GOAL_COLUMNS} FROM goals
                WHERE status NOT IN ('withdrawn', 'settled')
                  AND awake_after IS NOT NULL AND awake_after <= ?
                ORDER BY awake_after LIMIT ?""",
            (_iso(now), limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_goal_from_row(row) for row in rows]

    async def record_wake(
        self,
        goal_id: str,
        *,
        reason: WakeReason,
        correlation_id: str = "",
        unblocks: bool = False,
        now: datetime | None = None,
    ) -> WakeFact | None:
        goal = await self.get_goal(goal_id)
        if goal is None:
            raise GoalReconciliationError(f"unknown Goal {goal_id!r}")
        at = now or _utcnow()
        effective = correlation_id or f"manual:{uuid_hex()}"
        wake = WakeFact(
            wake_id=wake_id_for(goal_id, effective),
            goal_id=goal_id,
            reason=reason,
            correlation_id=effective,
            unblocks=unblocks or reason is WakeReason.MANUAL,
            created_at=at,
        )
        cursor = await self._conn.execute(
            """INSERT INTO goal_wakes (wake_id, goal_id, reason, correlation_id, unblocks, created_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT(wake_id) DO NOTHING""",
            (
                wake.wake_id,
                goal_id,
                reason.value,
                wake.correlation_id,
                int(wake.unblocks),
                _iso(at),
            ),
        )
        if cursor.rowcount:
            # Same due-marking rule as the in-memory twin: a relevant wake
            # makes the Goal sweep-due; non-unblocking wakes never shorten a
            # sleeping posture's night.
            await self._conn.execute(
                """UPDATE goals SET awake_after = ?, updated_at = ?
                   WHERE goal_id = ? AND status NOT IN ('withdrawn', 'settled')
                     AND (status NOT IN ('dormant', 'gated') OR ? = 1)""",
                (_iso(at), _iso(at), goal_id, int(wake.unblocks)),
            )
        await self._conn.commit()
        return wake if cursor.rowcount else None

    async def claim(
        self,
        goal_id: str,
        *,
        holder: str,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> GoalClaim | None:
        """Compare-and-set claim inside one ``BEGIN IMMEDIATE`` transaction.

        Two processes share the database write lock for the read-modify-write,
        so exactly one of two concurrent claimants wins; the loser gets
        ``None`` and skips instead of admitting.
        """
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            async with self._conn.execute(
                "SELECT status FROM goals WHERE goal_id = ?", (goal_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise GoalReconciliationError(f"unknown Goal {goal_id!r}")
            if GoalStatus(str(row[0])) in GoalStatus.terminal():
                await self._conn.commit()
                return None
            at = now or _utcnow()
            existing = await self._read_claim_locked(goal_id)
            if existing is not None and not existing.lapsed(at) and existing.holder != holder:
                await self._conn.commit()
                return None
            claim = GoalClaim(
                goal_id=goal_id,
                holder=holder,
                fence_epoch=(existing.fence_epoch + 1) if existing else 1,
                acquired_at=at,
                expires_at=at + (ttl or default_lease_ttl()),
            )
            await self._conn.execute(
                """INSERT INTO goal_claims (goal_id, holder, fence_epoch, fencing_token, acquired_at, expires_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(goal_id) DO UPDATE SET holder=excluded.holder,
                     fence_epoch=excluded.fence_epoch, fencing_token=excluded.fencing_token,
                     acquired_at=excluded.acquired_at, expires_at=excluded.expires_at""",
                (
                    claim.goal_id,
                    claim.holder,
                    claim.fence_epoch,
                    claim.fencing_token,
                    _iso(claim.acquired_at),
                    _iso(claim.expires_at) if claim.expires_at else None,
                ),
            )
            await self._conn.commit()
            return claim
        except BaseException:
            await self._conn.rollback()
            raise

    async def release_claim(self, goal_id: str, *, fencing_token: str) -> bool:
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = await self._read_claim_locked(goal_id)
            if existing is None or existing.fencing_token != fencing_token:
                await self._conn.rollback()
                return False
            await self._conn.execute("DELETE FROM goal_claims WHERE goal_id = ?", (goal_id,))
            await self._conn.commit()
            return True
        except BaseException:
            await self._conn.rollback()
            raise

    async def reclaim_expired(self, now: datetime, limit: int) -> list[Goal]:
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            async with self._conn.execute(
                """SELECT goal_claims.goal_id FROM goal_claims JOIN goals USING (goal_id)
                   WHERE goal_claims.expires_at IS NOT NULL AND goal_claims.expires_at <= ?
                     AND goals.status NOT IN ('withdrawn', 'settled')
                   ORDER BY goal_claims.expires_at LIMIT ?""",
                (_iso(now), limit),
            ) as cursor:
                rows = await cursor.fetchall()
            woken: list[Goal] = []
            for (goal_id,) in rows:
                await self._conn.execute("DELETE FROM goal_claims WHERE goal_id = ?", (goal_id,))
                await self._conn.execute(
                    "UPDATE goals SET awake_after = ?, updated_at = ? WHERE goal_id = ?",
                    (_iso(now), _iso(now), goal_id),
                )
                goal = await self.get_goal(goal_id)
                if goal is not None:
                    woken.append(goal)
            await self._conn.commit()
            return woken
        except BaseException:
            await self._conn.rollback()
            raise

    async def admit(
        self,
        goal_id: str,
        *,
        fencing_token: str,
        decision_key: str,
        kind: str = "run",
        correlation_id: str = "",
        now: datetime | None = None,
    ) -> tuple[GoalAdmission, bool]:
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            async with self._conn.execute(
                f"SELECT {_GOAL_COLUMNS} FROM goals WHERE goal_id = ?", (goal_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise GoalReconciliationError(f"unknown Goal {goal_id!r}")
            goal = _goal_from_row(row)
            at = now or _utcnow()
            async with self._conn.execute(
                """SELECT admission_id, goal_id, revision, fence_epoch, decision_key, kind,
                   correlation_id, admitted_at, completed_at, physical_ref
                   FROM goal_admissions WHERE goal_id = ? AND decision_key = ?""",
                (goal_id, decision_key),
            ) as cursor:
                existing_row = await cursor.fetchone()
            if existing_row is not None:
                # Dedupe before the fence: a replayed decision key resolves to
                # the recorded admission even from a superseded holder.
                await self._conn.commit()
                return _admission_from_row(existing_row), False
            claim = await self._read_claim_locked(goal_id)
            if claim is None or claim.fencing_token != fencing_token or claim.lapsed(at):
                await self._conn.rollback()
                raise StaleGoalFence(
                    f"fencing token for Goal {goal_id!r} is not current "
                    f"(epoch {claim.fence_epoch if claim else 'none'})"
                )
            _check_gates(goal, at)
            admission = GoalAdmission(
                goal_id=goal_id,
                revision=goal.revision,
                fence_epoch=claim.fence_epoch,
                decision_key=decision_key,
                kind=kind,
                correlation_id=correlation_id,
                admitted_at=at,
            )
            await self._conn.execute(
                """INSERT INTO goal_admissions (admission_id, goal_id, revision, fence_epoch,
                   decision_key, kind, correlation_id, admitted_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    admission.admission_id,
                    admission.goal_id,
                    admission.revision,
                    admission.fence_epoch,
                    admission.decision_key,
                    admission.kind,
                    admission.correlation_id,
                    _iso(admission.admitted_at),
                ),
            )
            await self._conn.execute(
                "UPDATE goals SET runs_admitted = runs_admitted + 1, updated_at = ? WHERE goal_id = ?",
                (_iso(at), goal_id),
            )
            await self._conn.commit()
            return admission, True
        except BaseException:
            await self._conn.rollback()
            raise

    async def complete_admission(
        self, admission_id: str, *, physical_ref: str, now: datetime | None = None
    ) -> bool:
        at = now or _utcnow()
        cursor = await self._conn.execute(
            """UPDATE goal_admissions SET completed_at = ?, physical_ref = ?
               WHERE admission_id = ? AND completed_at IS NULL""",
            (_iso(at), physical_ref, admission_id),
        )
        await self._conn.commit()
        return bool(cursor.rowcount)

    async def pending_admissions(
        self, goal_id: str | None = None, limit: int = 100
    ) -> list[GoalAdmission]:
        query = """SELECT admission_id, goal_id, revision, fence_epoch, decision_key, kind,
                   correlation_id, admitted_at, completed_at, physical_ref
                   FROM goal_admissions WHERE completed_at IS NULL"""
        params: list[object] = []
        if goal_id is not None:
            query += " AND goal_id = ?"
            params.append(goal_id)
        query += " ORDER BY admitted_at LIMIT ?"
        params.append(limit)
        async with self._conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [_admission_from_row(row) for row in rows]

    async def pending_wakes(self, goal_id: str | None = None, limit: int = 100) -> list[WakeFact]:
        query = """SELECT wake_id, goal_id, reason, correlation_id, unblocks, created_at, dispatched_at
                   FROM goal_wakes WHERE dispatched_at IS NULL"""
        params: list[object] = []
        if goal_id is not None:
            query += " AND goal_id = ?"
            params.append(goal_id)
        query += " ORDER BY created_at LIMIT ?"
        params.append(limit)
        async with self._conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [_wake_from_row(row) for row in rows]

    async def mark_wakes_dispatched(
        self, wake_ids: list[str], *, now: datetime | None = None
    ) -> int:
        if not wake_ids:
            return 0
        at = now or _utcnow()
        marked = 0
        for wake_id in wake_ids:
            cursor = await self._conn.execute(
                "UPDATE goal_wakes SET dispatched_at = ? WHERE wake_id = ? AND dispatched_at IS NULL",
                (_iso(at), wake_id),
            )
            marked += int(cursor.rowcount)
        await self._conn.commit()
        return marked

    async def sleep_goal(
        self,
        goal_id: str,
        *,
        status: GoalStatus,
        fencing_token: str,
        awake_after: datetime | None = None,
        blocked_reason: str | None = None,
        now: datetime | None = None,
    ) -> Goal:
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            claim = await self._read_claim_locked(goal_id)
            at = now or _utcnow()
            if claim is None or claim.fencing_token != fencing_token or claim.lapsed(at):
                await self._conn.rollback()
                raise StaleGoalFence(
                    f"fencing token for Goal {goal_id!r} is not current "
                    f"(epoch {claim.fence_epoch if claim else 'none'})"
                )
            if status not in GoalStatus.sleeping():
                raise GoalReconciliationError(f"sleep_goal takes a sleeping status, got {status!r}")
            await self._conn.execute(
                """UPDATE goals SET status = ?, awake_after = ?, blocked_reason = ?, updated_at = ?
                   WHERE goal_id = ?""",
                (
                    status.value,
                    _iso(awake_after) if awake_after else None,
                    blocked_reason,
                    _iso(at),
                    goal_id,
                ),
            )
            await self._conn.commit()
            goal = await self.get_goal(goal_id)
            assert goal is not None
            return goal
        except BaseException:
            await self._conn.rollback()
            raise

    async def finish_goal(
        self, goal_id: str, *, fencing_token: str, now: datetime | None = None
    ) -> Goal:
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            claim = await self._read_claim_locked(goal_id)
            at = now or _utcnow()
            if claim is None or claim.fencing_token != fencing_token or claim.lapsed(at):
                await self._conn.rollback()
                raise StaleGoalFence(
                    f"fencing token for Goal {goal_id!r} is not current "
                    f"(epoch {claim.fence_epoch if claim else 'none'})"
                )
            await self._conn.execute(
                "UPDATE goals SET status = 'settled', awake_after = NULL, updated_at = ? WHERE goal_id = ?",
                (_iso(at), goal_id),
            )
            await self._conn.execute("DELETE FROM goal_claims WHERE goal_id = ?", (goal_id,))
            await self._conn.commit()
            goal = await self.get_goal(goal_id)
            assert goal is not None
            return goal
        except BaseException:
            await self._conn.rollback()
            raise

    async def reconciliation_view(self, goal_id: str) -> dict[str, object] | None:
        goal = await self.get_goal(goal_id)
        if goal is None:
            return None
        async with self._conn.execute(
            "SELECT holder, fence_epoch, expires_at FROM goal_claims WHERE goal_id = ?",
            (goal_id,),
        ) as cursor:
            claim_row = await cursor.fetchone()
        async with self._conn.execute(
            """SELECT COUNT(*) FROM goal_wakes WHERE goal_id = ? AND dispatched_at IS NULL""",
            (goal_id,),
        ) as cursor:
            pending_wake_count = (await cursor.fetchone() or (0,))[0]
        async with self._conn.execute(
            """SELECT COUNT(*), SUM(completed_at IS NULL) FROM goal_admissions WHERE goal_id = ?""",
            (goal_id,),
        ) as cursor:
            total, open_count = await cursor.fetchone() or (0, 0)
        return {
            "goal_id": goal.goal_id,
            "revision": goal.revision,
            "status": goal.status.value,
            "runs_admitted": goal.runs_admitted,
            "budget_max_runs": goal.budget_max_runs,
            "deadline_at": goal.deadline_at,
            "awake_after": goal.awake_after,
            "blocked_reason": goal.blocked_reason,
            "claim": {
                "holder": claim_row[0],
                "fence_epoch": int(claim_row[1]),
                "expires_at": coerce_datetime(claim_row[2]) if claim_row[2] else None,
            }
            if claim_row
            else None,
            "pending_wakes": int(pending_wake_count),
            "open_admissions": int(open_count or 0),
            "admissions_total": int(total or 0),
        }

    # -- internals ---------------------------------------------------------

    async def _read_claim_locked(self, goal_id: str) -> GoalClaim | None:
        async with self._conn.execute(
            """SELECT goal_id, holder, fence_epoch, fencing_token, acquired_at, expires_at
               FROM goal_claims WHERE goal_id = ?""",
            (goal_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return GoalClaim(
            goal_id=row[0],
            holder=row[1],
            fence_epoch=int(row[2]),
            fencing_token=row[3],
            acquired_at=coerce_datetime(row[4]),
            expires_at=coerce_datetime(row[5]) if row[5] else None,
        )


def _admission_from_row(row: Any) -> GoalAdmission:
    return GoalAdmission(
        admission_id=row[0],
        goal_id=row[1],
        revision=int(row[2]),
        fence_epoch=int(row[3]),
        decision_key=row[4],
        kind=row[5],
        correlation_id=row[6],
        admitted_at=coerce_datetime(row[7]),
        completed_at=coerce_datetime(row[8]) if row[8] else None,
        physical_ref=row[9],
    )


def _wake_from_row(row: Any) -> WakeFact:
    return WakeFact(
        wake_id=row[0],
        goal_id=row[1],
        reason=WakeReason(row[2]),
        correlation_id=row[3],
        unblocks=bool(row[4]),
        created_at=coerce_datetime(row[5]),
        dispatched_at=coerce_datetime(row[6]) if row[6] else None,
    )


def _check_gates(goal: Goal, at: datetime) -> None:
    if goal.status is GoalStatus.WITHDRAWN:
        raise GoalCancelled(f"Goal {goal.goal_id!r} is cancelled")
    if goal.deadline_passed(at):
        raise GoalDeadlinePassed(f"Goal {goal.goal_id!r} deadline passed at {goal.deadline_at}")
    if goal.budget_exhausted():
        raise GoalBudgetExhausted(
            f"Goal {goal.goal_id!r} budget exhausted ({goal.runs_admitted}/{goal.budget_max_runs})"
        )
