"""Extension usage metering, attribution, and Workspace/org quota enforcement (#977).

An accounting collaborator at the extension seam — not an executor, router,
Run authority, or a second provider-usage recorder. Canonical provider totals
keep flowing only through the canonical Invocation machinery
(``maistro.quota`` / ``CanonicalInvocationUsageRecorder``); this module never
writes to it. Extension metering holds *attribution* rows that reference the
same canonical Invocation ids, so operators can aggregate by Workspace,
extension, publisher, capability and time window without any physical
provider/tool usage ever being counted twice:

- **Physical-use identity**: a usage event that carries a canonical
  ``invocation_id`` is the one physical record for that Invocation. The
  schema enforces UNIQUE(invocation_id), so a retry, a re-hand-out, or an
  alternate extension alias re-reporting the same canonical call conflicts
  instead of charging again. Extension-host-measured resources (CPU, memory,
  network — recorded where measurable) may omit ``invocation_id``; there is
  no other record of that work, and ``event_id`` idempotency guards it.
- **Nested attribution**: delegation lineage rides on the same physical rows
  via ``parent_invocation_id``/``root_invocation_id``/``depth``. Causal
  roll-ups (:meth:`ExtensionMeter.lineage`) are groupings *of* the physical
  rows, never additive copies, so nested extension calls preserve who caused
  what without double counting the underlying resource use.
- **Quotas**: :class:`ExtensionQuotaPolicy` scopes budgets by org, Workspace,
  extension, publisher, capability and provider — never by caller or Agent
  identity, so budget exhaustion cannot be bypassed by a retry, a new Agent,
  or an alternate extension alias. Admission is one ``BEGIN IMMEDIATE``
  transaction per reservation against a shared database file: all replicas
  must point at the same file (the same non-distributed-SQLite limitation the
  canonical Invocation quota documents). Refusal evidence commits, but no
  budget is charged by a refusal.
- **Reservations**: :meth:`ExtensionQuotaLedger.reserve` takes an atomic hold
  before dispatch; :meth:`~ExtensionQuotaLedger.commit` settles the absolute
  measured usage (truthful overage allowed);
  :meth:`~ExtensionQuotaLedger.release` refunds a reservation for work that
  never executed; :meth:`~ExtensionQuotaLedger.correct` applies a newer,
  absolute, provider-reported correction with monotonic revisions — a stale
  revision is kept as evidence but never rolls accounting backwards.
- **Rate limits**: a policy may carry a fixed-window
  ``rate_limit``/``rate_window_s``; the window count is checked inside the
  same admission transaction, so concurrent callers cannot race past it.
  Refused admissions do not consume rate budget.

Unconfigured admission mirrors the canonical Invocation quota: no policy
registered anywhere means quota admission is not configured and admits; a
populated policy table that covers nothing applicable to this call is a
policy gap and refuses.

No request payload, result, error string, or credential is ever copied into
these tables — identity, scope, and integer amounts only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from maistro.quota.invocation_quota import (
    QuotaUnit,
    require_amount,
    require_identifier,
)

__all__ = [
    "AttributionDimension",
    "ExtensionMeter",
    "ExtensionMeteringError",
    "ExtensionQuotaBalance",
    "ExtensionQuotaConflict",
    "ExtensionQuotaDenied",
    "ExtensionQuotaLedger",
    "ExtensionQuotaPolicy",
    "ExtensionQuotaRequest",
    "ExtensionUsageAmounts",
    "ExtensionUsageConflict",
    "ExtensionUsageEvent",
    "UsageTotals",
]

T = TypeVar("T")

Row = dict[str, Any]


def _named_rows(cursor: sqlite3.Cursor) -> list[Row]:
    """Fetch every result row as a column-name dict."""
    columns = [column[0] for column in cursor.description or ()]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _named_row(cursor: sqlite3.Cursor) -> Row | None:
    """Fetch the first result row as a column-name dict, or ``None``."""
    rows = _named_rows(cursor)
    return rows[0] if rows else None


#: Shared with the canonical Invocation quota so both ledgers speak one
#: vocabulary of units.
Unit = QuotaUnit

#: A dimension of :meth:`ExtensionMeter.breakdown`.
AttributionDimension = Literal["workspace", "extension", "publisher", "capability", "provider"]

_BREAKDOWN_COLUMNS: dict[AttributionDimension, str] = {
    "workspace": "workspace_id",
    "extension": "extension_id",
    "publisher": "publisher_id",
    "capability": "capability",
    "provider": "provider_name",
}

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS extension_usage_events (
        event_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        org_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        extension_id TEXT NOT NULL,
        publisher_id TEXT NOT NULL,
        capability TEXT NOT NULL,
        provider_name TEXT,
        invocation_id TEXT UNIQUE,
        root_invocation_id TEXT,
        depth INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        micro_usd INTEGER NOT NULL DEFAULT 0,
        requests INTEGER NOT NULL DEFAULT 0,
        cpu_ms INTEGER,
        memory_bytes INTEGER,
        network_bytes INTEGER,
        recorded_at REAL NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_extension_usage_scope
        ON extension_usage_events (org_id, workspace_id, recorded_at)""",
    """CREATE INDEX IF NOT EXISTS idx_extension_usage_extension
        ON extension_usage_events (extension_id, recorded_at)""",
    """CREATE TABLE IF NOT EXISTS extension_quota_policies (
        policy_id TEXT PRIMARY KEY,
        definition TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS extension_quota_reservations (
        reservation_id TEXT PRIMARY KEY,
        identity_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN
            ('held', 'settled', 'released', 'denied')),
        reason TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
        caller_id TEXT NOT NULL,
        org_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        extension_id TEXT NOT NULL,
        publisher_id TEXT NOT NULL,
        capability TEXT NOT NULL,
        provider_name TEXT,
        created_at REAL NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_extension_quota_res_scope
        ON extension_quota_reservations
        (org_id, workspace_id, extension_id, created_at)""",
    """CREATE TABLE IF NOT EXISTS extension_quota_allocations (
        reservation_id TEXT NOT NULL
            REFERENCES extension_quota_reservations(reservation_id),
        policy_id TEXT NOT NULL REFERENCES extension_quota_policies(policy_id),
        maximum INTEGER NOT NULL CHECK (maximum >= 0),
        held INTEGER NOT NULL CHECK (held >= 0),
        spent INTEGER NOT NULL DEFAULT 0 CHECK (spent >= 0),
        measured INTEGER NOT NULL DEFAULT 0 CHECK (measured IN (0, 1)),
        PRIMARY KEY (reservation_id, policy_id)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_extension_quota_alloc_policy
        ON extension_quota_allocations(policy_id)""",
    """CREATE TABLE IF NOT EXISTS extension_quota_evidence (
        reservation_id TEXT NOT NULL
            REFERENCES extension_quota_reservations(reservation_id),
        revision INTEGER NOT NULL CHECK (revision >= 0),
        evidence_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (reservation_id, revision),
        UNIQUE (reservation_id, evidence_id)
    )""",
)

#: No policy registered anywhere means quota admission is not configured, and
#: an unconfigured door admits — the same semantics the canonical Invocation
#: quota documents for its budget table.
_UNCONFIGURED = ""
_NO_APPLICABLE_POLICY = "missing applicable quota policy"

#: The settlement evidence row's evidence_id: the canonical commit is keyed by
#: the reservation itself, so only corrections carry caller-chosen ids.
_SETTLEMENT_EVIDENCE_ID = ""


class ExtensionMeteringError(RuntimeError):
    """Base class for extension metering/quota failures."""


class ExtensionUsageConflict(ExtensionMeteringError):
    """A usage event or physical-use identity was reused with different facts."""


class ExtensionQuotaDenied(ExtensionMeteringError):
    """No applicable quota policy, an unbounded request, or exhausted budget."""


class ExtensionQuotaConflict(ExtensionMeteringError):
    """A reservation/evidence identity was reused with different facts."""


def _optional_identifier(value: str | None, name: str) -> None:
    if value is not None:
        require_identifier(value, name)


def _optional_amount(value: int | None, name: str) -> None:
    if value is not None:
        require_amount(value, name)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class ExtensionUsageEvent:
    """One attribution row: who caused what usage, in which scope.

    ``invocation_id`` names the canonical Invocation whose physical effect
    this row attributes (provider tokens/cost, or a tool call routed through
    the canonical effect path). Rows without one describe extension-host
    measured resources (CPU/memory/network) with no canonical twin. Nested
    extension delegation is recorded as lineage on the same physical row —
    never as an additive copy of the underlying usage.
    """

    event_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    extension_version: str
    publisher_id: str
    capability: str
    caller_id: str
    invocation_id: str | None = None
    parent_invocation_id: str | None = None
    root_invocation_id: str | None = None
    depth: int = 0
    provider_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    micro_usd: int = 0
    requests: int = 0
    cpu_ms: int | None = None
    memory_bytes: int | None = None
    network_bytes: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "org_id",
            "workspace_id",
            "extension_id",
            "extension_version",
            "publisher_id",
            "capability",
            "caller_id",
        ):
            require_identifier(getattr(self, name), name)
        for name in (
            "invocation_id",
            "parent_invocation_id",
            "root_invocation_id",
            "provider_name",
        ):
            _optional_identifier(getattr(self, name), name)
        require_amount(self.depth, "depth")
        for name in ("input_tokens", "output_tokens", "micro_usd", "requests"):
            require_amount(getattr(self, name), name)
        for name in ("cpu_ms", "memory_bytes", "network_bytes"):
            _optional_amount(getattr(self, name), name)
        if (self.parent_invocation_id is None) != (self.root_invocation_id is None):
            raise ValueError("nested attribution needs both parent and root lineage")

    def attribution_payload(self) -> dict[str, object]:
        """The stable facts an ``event_id`` retry must repeat verbatim.

        Deliberately excludes ``recorded_at``: the ledger stamps arrival time
        once at first write, and a retry arriving a millisecond later is the
        same observation, not a conflict.
        """
        return {key: value for key, value in asdict(self).items() if key != "recorded_at"}


@dataclass(frozen=True)
class UsageTotals:
    """Aggregate physical usage over a filter or one breakdown bucket.

    ``events`` counts the physical rows summed. The resource fields sum only
    the rows that reported that measure; ``None`` means *no row in the group
    measured it* — an honest absence, not a measured zero.
    """

    events: int
    input_tokens: int
    output_tokens: int
    micro_usd: int
    requests: int
    cpu_ms: int | None
    memory_bytes: int | None
    network_bytes: int | None


@dataclass(frozen=True)
class ExtensionUsageAmounts:
    """Absolute measured usage of one settled reservation, per unit.

    Absolute, never a delta: a second commit/correction with the same facts
    is an idempotent no-op, and a correction replaces the settled amount
    instead of adding to it.
    """

    tokens: int = 0
    micro_usd: int = 0
    requests: int = 0

    def __post_init__(self) -> None:
        for name in ("tokens", "micro_usd", "requests"):
            require_amount(getattr(self, name), name)


def _unit_amount(unit: str, amounts: ExtensionUsageAmounts) -> int:
    if unit == "tokens":
        return amounts.tokens
    if unit == "micro_usd":
        return amounts.micro_usd
    if unit == "requests":
        return amounts.requests
    raise ValueError("unknown quota unit")


@dataclass(frozen=True)
class ExtensionQuotaPolicy:
    """One immutable budget (and optionally a rate limit) over a scope.

    Scope selectors left ``None`` mean "all values of that dimension"; every
    matching policy applies to a reservation, not just the most specific one.
    ``limit``/``opening_spend``/``reserve`` follow
    :class:`~maistro.quota.invocation_quota.QuotaBudget`: ``reserve`` is
    protected headroom so the usable ceiling is ``limit - reserve``, and
    ``opening_spend`` must include verified prior spend with ``coverage_ref``
    naming the operator's evidence for it. A new policy version needs a new
    ``policy_id`` — registered policies are immutable.
    """

    policy_id: str
    org_id: str
    unit: Unit
    limit: int
    period_start: int
    period_end: int
    coverage_ref: str
    opening_spend: int = 0
    reserve: int = 0
    workspace_id: str | None = None
    extension_id: str | None = None
    publisher_id: str | None = None
    capability: str | None = None
    provider_name: str | None = None
    rate_limit: int | None = None
    rate_window_s: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_identifier(self.org_id, "org_id")
        require_identifier(self.coverage_ref, "coverage_ref")
        if self.unit not in {"tokens", "micro_usd", "requests"}:
            raise ValueError("unknown quota unit")
        for name in ("limit", "reserve", "opening_spend", "period_start", "period_end"):
            require_amount(getattr(self, name), name)
        if self.reserve > self.limit or self.period_start >= self.period_end:
            raise ValueError("invalid reserve or billing period")
        for name in (
            "workspace_id",
            "extension_id",
            "publisher_id",
            "capability",
            "provider_name",
        ):
            _optional_identifier(getattr(self, name), name)
        _optional_amount(self.rate_limit, "rate_limit")
        _optional_amount(self.rate_window_s, "rate_window_s")
        if (self.rate_limit is None) != (self.rate_window_s is None):
            raise ValueError("rate limiting needs both rate_limit and rate_window_s")
        if self.rate_limit == 0:
            raise ValueError("rate_limit of zero refuses every call; narrow the scope instead")

    def covers(
        self,
        now: float,
        *,
        org_id: str,
        workspace_id: str,
        extension_id: str,
        publisher_id: str,
        capability: str,
        provider_name: str | None,
    ) -> bool:
        """Whether this policy applies to a reservation of the given scope."""
        if not (self.period_start <= now < self.period_end):
            return False
        if self.org_id != org_id:
            return False
        for value, selector in (
            (workspace_id, self.workspace_id),
            (extension_id, self.extension_id),
            (publisher_id, self.publisher_id),
            (capability, self.capability),
            (provider_name, self.provider_name),
        ):
            if selector is not None and selector != value:
                return False
        return True


@dataclass(frozen=True)
class ExtensionQuotaRequest:
    """One reservation attempt at the extension seam.

    ``reservation_id`` is the idempotency identity: callers derive it from
    the work they are about to dispatch (e.g. from the canonical invocation
    or effect identity), so a retry of the same work carries the same id and
    cannot hold twice — or slip past a refusal that already committed.
    ``caller_id`` is recorded for audit only; no policy matches on it, which
    is exactly why budget exhaustion cannot be bypassed by a new Agent.
    """

    reservation_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    publisher_id: str
    capability: str
    caller_id: str
    provider_name: str | None = None
    tokens: int | None = None
    micro_usd: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "reservation_id",
            "org_id",
            "workspace_id",
            "extension_id",
            "publisher_id",
            "capability",
            "caller_id",
        ):
            require_identifier(getattr(self, name), name)
        _optional_identifier(self.provider_name, "provider_name")
        _optional_amount(self.tokens, "tokens")
        _optional_amount(self.micro_usd, "micro_usd")

    def identity(self) -> dict[str, object]:
        """The facts a retry must repeat verbatim for idempotent admission."""
        return asdict(self)

    def bound(self, unit: Unit) -> int | None:
        """The caller-supplied upper bound for ``unit``, if any.

        ``requests`` is always bounded: one reservation is one request.
        """
        if unit == "requests":
            return 1
        if unit == "tokens":
            return self.tokens
        if unit == "micro_usd":
            return self.micro_usd
        raise ValueError("unknown quota unit")


@dataclass(frozen=True)
class ExtensionQuotaBalance:
    """One policy's ceiling and current spend/holds.

    Negative :attr:`available` is truthful overage, not a clamped zero.
    """

    policy_id: str
    ceiling: int
    spent: int
    held: int

    @property
    def available(self) -> int:
        """Ceiling minus settled spend minus outstanding holds."""
        return self.ceiling - self.spent - self.held


class _SqliteLedger:
    """Shared BEGIN IMMEDIATE plumbing for both extension ledgers.

    Mirrors the canonical Invocation quota's transaction discipline: every
    operation is one transaction on a fresh connection; no process-local
    mutex participates in admission; cancellation joins the in-flight
    transaction before propagating. Rows come back as column-name dicts (the
    ``sqlite3.Row`` shortcut needs a ``row_factory`` assignment whose debt
    identity belongs to other ledgers).
    """

    def __init__(self, path: str | Path, *, clock: Callable[[], float]) -> None:
        if str(path) == ":memory:" or not str(path).strip():
            raise ValueError("extension ledgers require an explicit shared SQLite file")
        self._path = str(path)
        self._clock = clock

    def _transaction(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        conn = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = operation(conn)
                conn.commit()
                return result
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    async def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        worker = asyncio.create_task(asyncio.to_thread(self._transaction, operation))
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            with contextlib.suppress(Exception):
                worker.result()
            raise asyncio.CancelledError
        return worker.result()

    def _create_schema(self, conn: sqlite3.Connection, schema: tuple[str, ...]) -> None:
        for sql in schema:
            conn.execute(sql)


class ExtensionMeter(_SqliteLedger):
    """Durable extension usage attribution and aggregation ledger.

    Attribution only: recording here never charges a canonical provider
    total. Physical usage is deduplicated on the canonical ``invocation_id``
    and, absent one, on ``event_id`` idempotency.
    """

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__(path, clock=clock)

    async def ensure_schema(self) -> None:
        """Create the attribution tables. A deployment step, not per-call."""

        def create(conn: sqlite3.Connection) -> None:
            self._create_schema(conn, _SCHEMA)

        await self._run(create)

    async def record(self, event: ExtensionUsageEvent) -> None:
        """Attribute one usage observation exactly once.

        Retrying with the same ``event_id`` and identical facts is an
        idempotent no-op; different facts under the same id conflict. A
        second event claiming the same canonical ``invocation_id`` — a
        different event id reporting the same physical provider/tool call,
        e.g. through an alternate extension alias — conflicts instead of
        charging twice.
        """
        payload = _json(event.attribution_payload())

        def write(conn: sqlite3.Connection) -> None:
            old = _named_row(
                conn.execute(
                    "SELECT payload FROM extension_usage_events WHERE event_id = ?",
                    (event.event_id,),
                )
            )
            if old is not None:
                if old["payload"] != payload:
                    raise ExtensionUsageConflict("usage event identity was reused")
                return
            try:
                conn.execute(
                    "INSERT INTO extension_usage_events "
                    "(event_id, payload, org_id, workspace_id, extension_id, publisher_id, "
                    "capability, provider_name, invocation_id, root_invocation_id, depth, "
                    "input_tokens, output_tokens, micro_usd, requests, cpu_ms, memory_bytes, "
                    "network_bytes, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        payload,
                        event.org_id,
                        event.workspace_id,
                        event.extension_id,
                        event.publisher_id,
                        event.capability,
                        event.provider_name,
                        event.invocation_id,
                        event.root_invocation_id,
                        event.depth,
                        event.input_tokens,
                        event.output_tokens,
                        event.micro_usd,
                        event.requests,
                        event.cpu_ms,
                        event.memory_bytes,
                        event.network_bytes,
                        self._clock(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ExtensionUsageConflict(
                    f"canonical Invocation {event.invocation_id} already carries "
                    "a physical usage record"
                ) from exc

        await self._run(write)

    @staticmethod
    def _scope_filters(
        *,
        org_id: str | None,
        workspace_id: str | None,
        extension_id: str | None,
        publisher_id: str | None,
        capability: str | None,
        since: float | None,
        until: float | None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        values: list[object] = []
        if org_id is not None:
            clauses.append("org_id = ?")
            values.append(org_id)
        for column, value in (
            ("workspace_id", workspace_id),
            ("extension_id", extension_id),
            ("publisher_id", publisher_id),
            ("capability", capability),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        if since is not None:
            clauses.append("recorded_at >= ?")
            values.append(since)
        if until is not None:
            clauses.append("recorded_at < ?")
            values.append(until)
        return (" AND ".join(clauses) or "1 = 1"), values

    @staticmethod
    def _totals_row_query(clause: str, values: list[object], *, bucket: str | None) -> str:
        bucket_select = "" if bucket is None else f"COALESCE({bucket}, '') AS bucket, "
        group_by = "" if bucket is None else " GROUP BY bucket"
        return (
            f"SELECT {bucket_select}"
            "COUNT(*) AS events, "
            "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
            "SUM(micro_usd) AS micro_usd, SUM(requests) AS requests, "
            "SUM(cpu_ms) AS cpu_ms, SUM(memory_bytes) AS memory_bytes, "
            f"SUM(network_bytes) AS network_bytes FROM extension_usage_events "
            f"WHERE {clause}{group_by}"
        )

    @staticmethod
    def _totals_from_row(row: Row) -> UsageTotals:
        return UsageTotals(
            events=int(row["events"]),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            micro_usd=int(row["micro_usd"] or 0),
            requests=int(row["requests"] or 0),
            cpu_ms=None if row["cpu_ms"] is None else int(row["cpu_ms"]),
            memory_bytes=None if row["memory_bytes"] is None else int(row["memory_bytes"]),
            network_bytes=None if row["network_bytes"] is None else int(row["network_bytes"]),
        )

    async def totals(
        self,
        *,
        org_id: str | None = None,
        workspace_id: str | None = None,
        extension_id: str | None = None,
        publisher_id: str | None = None,
        capability: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> UsageTotals:
        """Aggregate physical usage rows under the given filters.

        Sums rows only — attribution copies do not exist, so no filter
        combination can double count a physical resource use. The half-open
        time window is ``since <= recorded_at < until``.
        """
        clause, values = self._scope_filters(
            org_id=org_id,
            workspace_id=workspace_id,
            extension_id=extension_id,
            publisher_id=publisher_id,
            capability=capability,
            since=since,
            until=until,
        )

        def read(conn: sqlite3.Connection) -> UsageTotals:
            cursor = conn.execute(self._totals_row_query(clause, values, bucket=None), values)
            return self._totals_from_row(_named_row(cursor) or {})

        return await self._run(read)

    async def breakdown(
        self,
        dimension: AttributionDimension,
        *,
        org_id: str | None = None,
        workspace_id: str | None = None,
        extension_id: str | None = None,
        publisher_id: str | None = None,
        capability: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> dict[str, UsageTotals]:
        """Per-bucket totals along one dimension, under the same filters.

        The bucket key is the dimension's value ('' for rows that never
        reported one, e.g. providerless host-measured resource rows). Buckets
        partition the same physical rows ``totals`` sums, so a breakdown
        re-adds to its parent total by construction — never to more.
        """
        clause, values = self._scope_filters(
            org_id=org_id,
            workspace_id=workspace_id,
            extension_id=extension_id,
            publisher_id=publisher_id,
            capability=capability,
            since=since,
            until=until,
        )
        column = _BREAKDOWN_COLUMNS[dimension]

        def read(conn: sqlite3.Connection) -> dict[str, UsageTotals]:
            query = self._totals_row_query(clause, values, bucket=column)
            return {
                str(row["bucket"]): self._totals_from_row(row)
                for row in _named_rows(conn.execute(query, values))
            }

        return await self._run(read)

    async def lineage(self, root_invocation_id: str) -> list[ExtensionUsageEvent]:
        """The causal delegation chain under one root Invocation.

        Ordered by nesting depth then arrival time. Every row is a distinct
        physical resource use attributed once; the chain explains who caused
        what without re-adding anything.
        """
        require_identifier(root_invocation_id, "root_invocation_id")

        def read(conn: sqlite3.Connection) -> list[ExtensionUsageEvent]:
            rows = _named_rows(
                conn.execute(
                    "SELECT payload FROM extension_usage_events "
                    "WHERE root_invocation_id = ? "
                    "OR (root_invocation_id IS NULL AND invocation_id = ?) "
                    "ORDER BY depth, recorded_at, event_id",
                    (root_invocation_id, root_invocation_id),
                )
            )
            return [ExtensionUsageEvent(**json.loads(str(row["payload"]))) for row in rows]

        return await self._run(read)


class ExtensionQuotaLedger(_SqliteLedger):
    """Server-side Workspace/org quota admission for extension work.

    Enforcement lives in the shared database transaction, not in any client:
    two workers admitting against the same remaining budget serialize at
    ``BEGIN IMMEDIATE``, and the loser is refused with its refusal recorded.
    """

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__(path, clock=clock)

    async def ensure_schema(self) -> None:
        """Create the quota tables. A deployment step, not per-call."""

        def create(conn: sqlite3.Connection) -> None:
            self._create_schema(conn, _SCHEMA)

        await self._run(create)

    async def register_policy(self, policy: ExtensionQuotaPolicy) -> None:
        """Install an immutable policy (trusted deployment/admin operation).

        Establish completeness of the opening balance and quiesce outstanding
        work before adding a policy to a previously unmetered scope. Existing
        history is not retroactively counted; ``opening_spend`` attests to it.
        """
        definition = _json(asdict(policy))

        def register(conn: sqlite3.Connection) -> None:
            row = _named_row(
                conn.execute(
                    "SELECT definition FROM extension_quota_policies WHERE policy_id = ?",
                    (policy.policy_id,),
                )
            )
            if row is not None:
                if row["definition"] != definition:
                    raise ExtensionQuotaConflict("policy identity is immutable")
                return
            conn.execute(
                "INSERT INTO extension_quota_policies VALUES (?, ?)",
                (policy.policy_id, definition),
            )

        await self._run(register)

    @staticmethod
    def _balance(conn: sqlite3.Connection, policy: ExtensionQuotaPolicy) -> ExtensionQuotaBalance:
        rows = _named_rows(
            conn.execute(
                "SELECT spent, held FROM extension_quota_allocations WHERE policy_id = ?",
                (policy.policy_id,),
            )
        )
        return ExtensionQuotaBalance(
            policy.policy_id,
            policy.limit - policy.reserve,
            policy.opening_spend + sum(int(row["spent"]) for row in rows),
            sum(int(row["held"]) for row in rows),
        )

    async def policy_balance(self, policy_id: str) -> ExtensionQuotaBalance:
        """Current ceiling/spend/holds for one registered policy."""
        require_identifier(policy_id, "policy_id")

        def read(conn: sqlite3.Connection) -> ExtensionQuotaBalance:
            row = _named_row(
                conn.execute(
                    "SELECT definition FROM extension_quota_policies WHERE policy_id = ?",
                    (policy_id,),
                )
            )
            if row is None:
                raise KeyError(policy_id)
            return self._balance(conn, ExtensionQuotaPolicy(**json.loads(str(row["definition"]))))

        return await self._run(read)

    @staticmethod
    def _applicable(
        policies: list[ExtensionQuotaPolicy], request: ExtensionQuotaRequest, now: float
    ) -> list[ExtensionQuotaPolicy]:
        return [
            policy
            for policy in policies
            if policy.covers(
                now,
                org_id=request.org_id,
                workspace_id=request.workspace_id,
                extension_id=request.extension_id,
                publisher_id=request.publisher_id,
                capability=request.capability,
                provider_name=request.provider_name,
            )
        ]

    @staticmethod
    def _rate_count(conn: sqlite3.Connection, policy: ExtensionQuotaPolicy, now: float) -> int:
        """Admissions inside the policy's current fixed rate window.

        Only admitted reservations count: a refusal never dispatched work and
        must not consume rate budget.
        """
        if policy.rate_window_s is None:  # pragma: no cover - guarded by _admission_reason
            return 0
        row = _named_row(
            conn.execute(
                "SELECT COUNT(*) AS admissions FROM extension_quota_reservations "
                "WHERE state IN ('held', 'settled') AND created_at >= ? AND created_at <= ? "
                "AND org_id = ? "
                "AND (? IS NULL OR workspace_id = ?) "
                "AND (? IS NULL OR extension_id = ?) "
                "AND (? IS NULL OR publisher_id = ?) "
                "AND (? IS NULL OR capability = ?) "
                "AND (? IS NULL OR provider_name = ?)",
                (
                    now - policy.rate_window_s,
                    now,
                    policy.org_id,
                    policy.workspace_id,
                    policy.workspace_id,
                    policy.extension_id,
                    policy.extension_id,
                    policy.publisher_id,
                    policy.publisher_id,
                    policy.capability,
                    policy.capability,
                    policy.provider_name,
                    policy.provider_name,
                ),
            )
        )
        return int(row["admissions"]) if row else 0

    @staticmethod
    def _admission_decision(
        conn: sqlite3.Connection,
        policies: list[ExtensionQuotaPolicy],
        applicable: list[ExtensionQuotaPolicy],
        request: ExtensionQuotaRequest,
        now: float,
    ) -> tuple[str, list[tuple[str, str, int, int]]]:
        """Refusal reason (``""`` admits) plus the hold rows admission takes."""
        if not policies:
            return _UNCONFIGURED, []
        if not applicable:
            return _NO_APPLICABLE_POLICY, []
        allocations: list[tuple[str, str, int, int]] = []
        for policy in applicable:
            if (
                policy.rate_limit is not None
                and ExtensionQuotaLedger._rate_count(conn, policy, now) >= policy.rate_limit
            ):
                return f"rate limit exceeded for policy {policy.policy_id}", []
            bound = request.bound(policy.unit)
            if bound is None:
                return f"missing upper bound for policy {policy.policy_id}", []
            if ExtensionQuotaLedger._balance(conn, policy).available < bound:
                return f"quota exhausted for policy {policy.policy_id}", []
            allocations.append((request.reservation_id, policy.policy_id, bound, bound))
        return "", allocations

    async def reserve(self, request: ExtensionQuotaRequest) -> None:
        """Take atomic holds on every applicable policy before dispatch.

        Idempotent on ``reservation_id``: an identical retry returns without
        holding again, and a previously refused reservation stays refused.
        Reusing the id with different facts conflicts. Raises
        :class:`ExtensionQuotaDenied` after the refusal evidence has committed
        — no budget is ever charged by a refusal.
        """
        identity = _json(request.identity())

        def admit(conn: sqlite3.Connection) -> str:
            old = _named_row(
                conn.execute(
                    "SELECT identity_json, state, reason FROM extension_quota_reservations "
                    "WHERE reservation_id = ?",
                    (request.reservation_id,),
                )
            )
            if old is not None:
                if old["identity_json"] != identity:
                    raise ExtensionQuotaConflict(
                        "reservation identity was reused with different facts"
                    )
                if old["state"] == "denied":
                    return str(old["reason"])
                return ""
            # Sampled after acquiring the database write lock, so a queued
            # admission cannot reserve against an already-ended period.
            now = self._clock()
            if not math.isfinite(now):
                raise ValueError("invalid admission clock")
            policies = [
                ExtensionQuotaPolicy(**json.loads(str(row["definition"])))
                for row in _named_rows(
                    conn.execute("SELECT definition FROM extension_quota_policies")
                )
            ]
            applicable = self._applicable(policies, request, now)
            reason, allocations = self._admission_decision(conn, policies, applicable, request, now)
            conn.execute(
                "INSERT INTO extension_quota_reservations "
                "(reservation_id, identity_json, state, reason, caller_id, org_id, "
                "workspace_id, extension_id, publisher_id, capability, provider_name, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.reservation_id,
                    identity,
                    "denied" if reason else "held",
                    reason,
                    request.caller_id,
                    request.org_id,
                    request.workspace_id,
                    request.extension_id,
                    request.publisher_id,
                    request.capability,
                    request.provider_name,
                    now,
                ),
            )
            if not reason:
                conn.executemany(
                    "INSERT INTO extension_quota_allocations "
                    "(reservation_id, policy_id, maximum, held) VALUES (?, ?, ?, ?)",
                    allocations,
                )
            return reason

        reason = await self._run(admit)
        if reason:
            raise ExtensionQuotaDenied(reason)

    @staticmethod
    def _reservation_row(conn: sqlite3.Connection, reservation_id: str) -> Row:
        row = _named_row(
            conn.execute(
                "SELECT state, revision FROM extension_quota_reservations WHERE reservation_id = ?",
                (reservation_id,),
            )
        )
        if row is None:
            raise ExtensionQuotaConflict(f"unknown reservation {reservation_id}")
        if row["state"] == "denied":
            raise ExtensionQuotaConflict("denied reservation has no provider outcome")
        return row

    async def commit(self, reservation_id: str, amounts: ExtensionUsageAmounts) -> None:
        """Settle a held reservation with the absolute measured usage.

        Actual usage above the hold is truthful overage and is recorded as
        such. Idempotent: repeating the same settlement is a no-op; different
        facts under the same identity conflict. A released reservation cannot
        settle — refunding unexecuted work and reporting executed work are
        contradictory facts about the same reservation.
        """
        payload = _json({"amounts": asdict(amounts)})

        def settle(conn: sqlite3.Connection) -> None:
            row = self._reservation_row(conn, reservation_id)
            if str(row["state"]) == "released":
                raise ExtensionQuotaConflict("released reservation cannot settle")
            prior = _named_row(
                conn.execute(
                    "SELECT payload FROM extension_quota_evidence "
                    "WHERE reservation_id = ? AND revision = 0",
                    (reservation_id,),
                )
            )
            if prior is not None:
                if prior["payload"] != payload:
                    raise ExtensionQuotaConflict("settlement identity was reused")
                return
            conn.execute(
                "INSERT INTO extension_quota_evidence VALUES (?, ?, ?, ?)",
                (reservation_id, 0, _SETTLEMENT_EVIDENCE_ID, payload),
            )
            allocations = _named_rows(
                conn.execute(
                    "SELECT a.policy_id, p.definition FROM extension_quota_allocations a "
                    "JOIN extension_quota_policies p USING (policy_id) WHERE a.reservation_id = ?",
                    (reservation_id,),
                )
            )
            for allocation in allocations:
                unit = json.loads(str(allocation["definition"]))["unit"]
                conn.execute(
                    "UPDATE extension_quota_allocations SET spent = ?, held = 0, measured = 1 "
                    "WHERE reservation_id = ? AND policy_id = ?",
                    (_unit_amount(unit, amounts), reservation_id, allocation["policy_id"]),
                )
            conn.execute(
                "UPDATE extension_quota_reservations SET state = 'settled' "
                "WHERE reservation_id = ?",
                (reservation_id,),
            )

        await self._run(settle)

    async def release(self, reservation_id: str) -> None:
        """Refund a reservation for reserved-but-unexecuted work.

        Idempotent: releasing twice keeps the refund. A settled reservation
        cannot be released; a provider correction is the only path that moves
        settled spend.
        """

        def refund(conn: sqlite3.Connection) -> None:
            row = self._reservation_row(conn, reservation_id)
            state = str(row["state"])
            if state == "released":
                return
            if state == "settled":
                raise ExtensionQuotaConflict("settled reservation cannot be released")
            conn.execute(
                "UPDATE extension_quota_allocations SET held = 0 WHERE reservation_id = ?",
                (reservation_id,),
            )
            conn.execute(
                "UPDATE extension_quota_reservations SET state = 'released' "
                "WHERE reservation_id = ?",
                (reservation_id,),
            )

        await self._run(refund)

    async def correct(
        self,
        reservation_id: str,
        *,
        revision: int,
        evidence_id: str,
        amounts: ExtensionUsageAmounts,
    ) -> None:
        """Apply an absolute, provider-reported correction to settled usage.

        ``revision`` must be positive — zero is the canonical settlement.
        Corrections may reduce spend only with a newer revision: a stale
        revision is kept as evidence but never rolls accounting backwards.
        Repeating the same correction verbatim is an idempotent no-op.
        """
        require_amount(revision, "revision")
        if revision == 0:
            raise ValueError("revision zero is reserved for the canonical settlement")
        require_identifier(evidence_id, "evidence_id")
        payload = _json({"evidence_id": evidence_id, "amounts": asdict(amounts)})

        def apply(conn: sqlite3.Connection) -> None:
            row = self._reservation_row(conn, reservation_id)
            if str(row["state"]) != "settled":
                raise ExtensionQuotaConflict(
                    "only settled reservations carry measured usage to correct"
                )
            prior = _named_rows(
                conn.execute(
                    "SELECT payload FROM extension_quota_evidence "
                    "WHERE reservation_id = ? AND (revision = ? OR evidence_id = ?)",
                    (reservation_id, revision, evidence_id),
                )
            )
            if prior:
                if any(record["payload"] != payload for record in prior):
                    raise ExtensionQuotaConflict("correction identity/revision was reused")
                return
            conn.execute(
                "INSERT INTO extension_quota_evidence VALUES (?, ?, ?, ?)",
                (reservation_id, revision, evidence_id, payload),
            )
            if revision < int(row["revision"]):
                return  # Keep stale evidence, but never roll accounting backwards.
            allocations = _named_rows(
                conn.execute(
                    "SELECT a.policy_id, p.definition FROM extension_quota_allocations a "
                    "JOIN extension_quota_policies p USING (policy_id) WHERE a.reservation_id = ?",
                    (reservation_id,),
                )
            )
            for allocation in allocations:
                unit = json.loads(str(allocation["definition"]))["unit"]
                conn.execute(
                    "UPDATE extension_quota_allocations SET spent = ?, held = 0, measured = 1 "
                    "WHERE reservation_id = ? AND policy_id = ?",
                    (_unit_amount(unit, amounts), reservation_id, allocation["policy_id"]),
                )
            conn.execute(
                "UPDATE extension_quota_reservations SET revision = ? WHERE reservation_id = ?",
                (revision, reservation_id),
            )

        await self._run(apply)
