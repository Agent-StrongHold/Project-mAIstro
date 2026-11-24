"""The Hive schedule projection converges on canonical truth at restart (#2467).

The ``/v1/schedules`` routes write the canonical ``ScheduleStore`` definition
first and the Hive row second (#1199). Those are two separate stores with no
shared commit, so a crash between the halves can leave a projection behind an
acknowledged canonical edit or deletion, or leave a canonical row with no
projection at all (an interrupted create).

Startup reconciliation used to answer every one of those states the same way:
re-derive a definition from the Hive row and ``put`` it canonically whenever
the canonical row was missing or drifted (``_backfill_one``). That made the
projection the authority, so a stale row reverted an acknowledged canonical
edit and recreated a deleted schedule — potentially rearming recurring work —
at every runner startup, forever.

This module owns the replacement policy. The direction of authority is the
canonical store; the Hive row is repaired *from* it:

- **Legacy import is bounded.** A durable migration marker (the
  ``schedule_migration`` store below) records that the one-time import of
  pre-#1199 Hive rows completed. Only a startup that finds no marker runs the
  import pass (``scheduler.backfill_canonical_definitions``): put rows with
  no canonical counterpart and drift-reconcile rows whose canonical row the
  old lazy tick left stale. Completing the pass writes the marker only if
  every row imported; a row that fails keeps the marker unwritten, so the
  next startup retries the whole pass instead of sealing the loss in, and
  the affected rows are named on the health surface. Every
  startup after it runs the repair pass instead. A previously migrated
  schedule can therefore never be reimported, whatever an old Hive record
  says.
- **Canonical deletions are finished, not undone.** The delete route records
  a durable tombstone after the canonical delete lands. A restart that finds
  a tombstone drops any surviving Hive row — and re-issues the canonical
  delete if a restore-from-backup revived it — instead of resurrecting the
  schedule from the stale row.
- **Interrupted creates are resolved through a pending marker.** The create
  route writes a durable ``pending`` record before its canonical put and
  clears it once the Hive projection landed (or the canonical write was
  compensated). A restart that finds one repairs the projection *from* the
  canonical row — the schedule keeps its one identity and becomes visible —
  or clears the marker when canonical truth says the create never committed.
- **Degraded beats silent.** A Hive row canonical cannot account for (a
  canonical deletion whose tombstone write itself crashed) is never
  reimported and never fired — canonical absence is authority — and is
  reported through :func:`projection_health` (surfaced by
  ``scheduler_status``, #290) rather than silently projected as if it were
  current.

The ledger rides the same Hive ``JsonStore`` persistence the rows do, so the
marker, tombstones, and pending records survive exactly the restarts the
projection does. Two replicas reconciling concurrently converge: both put
identical legacy definitions (cursor-preserving), the marker write is
single-winner (``put_if_absent``), and the repair pass only ever rewrites a
projection to what canonical already says.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import stores
from stores import JsonStore

logger = logging.getLogger(__name__)

#: The ledger's durable store, owned by this module rather than ``stores.py``:
#: every ``stores.py`` store is a row in the cutover retirement ledger (#1046)
#: and a retiring surface may not gain consumers, so durable state added here
#: lives beside the only code that writes it — the same move ``settings`` made
#: out of ``stores.py`` (#334) — while ``stores.register_json_store`` keeps the
#: deployment's persistence wiring and initialization centralized, so the
#: marker, tombstones, and pending records cannot silently miss the configured
#: backend and stop surviving the restarts they exist to close.
schedule_migration: JsonStore = stores.register_json_store(JsonStore("schedule_migration"))

_MARKER_KEY = "migration"
_TOMBSTONE_PREFIX = "tombstone:"
_PENDING_PREFIX = "pending:"

# Health of the last startup reconciliation, read by `scheduler_status` (#290)
# so a projection that could not be reconciled is visible to an operator
# instead of silently serving a definition canonical refutes.
_PROJECTION_HEALTH: dict[str, Any] = {
    "migrated": False,
    "reconciled_at": None,
    "degraded": [],
}


def projection_health() -> dict[str, Any]:
    """The last reconciliation's outcome, for ``scheduler_status`` (#290)."""
    return dict(_PROJECTION_HEALTH)


def reset_projection_health() -> None:
    """Back to the never-reconciled state (test isolation)."""
    _PROJECTION_HEALTH["migrated"] = False
    _PROJECTION_HEALTH["reconciled_at"] = None
    _PROJECTION_HEALTH["degraded"] = []


class ScheduleProjectionLedger:
    """Marker, tombstones, and pending-create records over one JsonStore.

    Every read goes to the store, so the ledger has no cache to invalidate:
    the store is the state. Writes persist before mutating memory (the
    ``JsonStore`` contract), which is what makes each record durable across
    the crash windows it exists to close.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def migrated(self) -> bool:
        """Whether the one-time legacy import pass has completed."""
        return _MARKER_KEY in self._store

    def mark_migrated(self) -> bool:
        """Record import completion; single-winner across replicas."""
        return self._store.put_if_absent(
            _MARKER_KEY, {"version": 1, "completed_at": datetime.now(UTC).isoformat()}
        )

    def is_tombstoned(self, sid: str) -> bool:
        return f"{_TOMBSTONE_PREFIX}{sid}" in self._store

    def record_tombstone(self, sid: str) -> None:
        """A canonically deleted schedule that must never be reimported."""
        self._store[f"{_TOMBSTONE_PREFIX}{sid}"] = {
            "schedule_id": sid,
            "deleted_at": datetime.now(UTC).isoformat(),
        }

    def pending_creates(self) -> dict[str, dict[str, Any]]:
        """The interrupted-create markers awaiting resolution, keyed by sid."""
        pending: dict[str, dict[str, Any]] = {}
        for key, value in self._store.items():
            if isinstance(key, str) and key.startswith(_PENDING_PREFIX) and isinstance(value, dict):
                pending[key[len(_PENDING_PREFIX) :]] = value
        return pending

    def mark_pending_create(self, sid: str) -> bool:
        """Open the interrupted-create marker before the canonical put."""
        return self._store.put_if_absent(
            f"{_PENDING_PREFIX}{sid}",
            {"schedule_id": sid, "opened_at": datetime.now(UTC).isoformat()},
        )

    def clear_pending_create(self, sid: str) -> None:
        """The create's two-write window closed (projected or compensated)."""
        self._store.pop(f"{_PENDING_PREFIX}{sid}", None)


def ledger() -> ScheduleProjectionLedger:
    """The ledger over the Hive-persisted ``schedule_migration`` store."""
    return ScheduleProjectionLedger(schedule_migration)


def mark_pending_create(sid: str) -> bool:
    """Open the interrupted-create marker (create route, before the put)."""
    return ledger().mark_pending_create(sid)


def clear_pending_create(sid: str) -> None:
    """Close the interrupted-create marker (create route, window closed)."""
    ledger().clear_pending_create(sid)


def record_tombstone(sid: str) -> None:
    """Record a canonical deletion (delete route, after the delete lands)."""
    ledger().record_tombstone(sid)


def _canonical_projection_updates(canonical: Any) -> dict[str, Any]:
    """The Hive-row fields a canonical definition is the authority for.

    Definition fields and the cursor pair alike: reads after a restart must
    serve what canonical recorded, including the cursor the tick moved in
    this or another replica. ``description`` and ``created_at`` are the row's
    own history and stay.
    """
    return {
        "workspace_id": canonical.workspace_id,
        "project_id": canonical.project_id,
        "name": canonical.name,
        "cron_expression": canonical.cron,
        "mission_template_id": canonical.graph_template_id,
        "enabled": canonical.enabled,
        "timezone": canonical.timezone,
        "max_runs": canonical.max_runs,
        "catchup_window_seconds": canonical.catchup_window_seconds,
        "user_id": str(getattr(canonical, "actor_principal_id", "") or ""),
        "last_run": canonical.last_fired_at,
        "last_run_id": canonical.last_run_id,
        "next_run": canonical.next_due_at,
    }


def _projection_drifted(canonical: Any, row: Any) -> bool:
    """Whether the Hive row disagrees with canonical on any owned field."""
    mirrored = _canonical_projection_updates(canonical)
    projection_fields = {
        field: value
        for field, value in mirrored.items()
        if field not in {"last_run", "last_run_id", "next_run"}
    }
    return any(getattr(row, field) != value for field, value in projection_fields.items())


def _hive_row_from_canonical(canonical: Any) -> Any:
    """The projection row a canonical definition describes, rebuilt.

    The interrupted-create repair (#2467): the canonical put committed but
    the process died before the Hive row existed. The schedule keeps its one
    identity — the same sid — and becomes reachable through the Hive-keyed
    routes again, instead of staying an enabled orphan only ``due()`` can
    see.
    """
    from models.schemas import Schedule

    return Schedule(
        id=canonical.schedule_id,
        **_canonical_projection_updates(canonical),
        description="",
        created_at=canonical.created_at,
        updated_at=canonical.updated_at,
    )


async def finish_tombstoned_row(sid: str, container: Any) -> bool:
    """Finish a tombstoned deletion: canonical stays deleted, the row goes.

    Caller holds the schedule's ``definition_lock``. Returns whether ``sid``
    was tombstoned (so the caller skips any import/repair for it). The
    canonical delete is re-issued idempotently: a restore-from-backup can
    revive the row under a surviving tombstone, and the tombstone is the
    durable word that this schedule was deleted.
    """
    if not ledger().is_tombstoned(sid):
        return False
    from services.scheduler import drop_hive_schedule_row

    await container.schedule_store.delete(sid)
    drop_hive_schedule_row(sid)
    logger.info(
        "Schedule %s was deleted canonically; dropped its stale Hive projection instead of "
        "reimporting it (#2467)",
        sid,
    )
    return True


async def _repair_projection_one(sid: str, container: Any, degraded: list[str]) -> int:
    """Point one Hive row back at canonical truth. Caller holds the lock.

    Returns 1 when the row was rewritten. A row canonical cannot account for
    is left in place but named degraded: it can never fire (execution selects
    from canonical ``due()``) and can never be reimported post-marker, so the
    honest surface is the health record, not a silent stale definition.
    """
    from services.scheduler import hive_schedule_row, replace_hive_schedule_row

    row = hive_schedule_row(sid)
    canonical = await container.schedule_store.get(sid)
    if row is None:
        if canonical is None or canonical.workspace_id.startswith("hive:schedule:"):
            return 0
        replace_hive_schedule_row(sid, _hive_row_from_canonical(canonical))
        logger.info(
            "Rebuilt the Hive projection of canonical schedule %s (#2467)",
            sid,
        )
        return 1
    if canonical is None:
        if str(getattr(row, "mission_template_id", "") or "").strip():
            # A non-empty template with no canonical row and no tombstone: a
            # canonical deletion whose tombstone write crashed, or a direct
            # canonical-side deletion. Post-marker there is no import pass to
            # resurrect it with; the row stays readable-but-nonfireable and
            # is reported, never silently trusted.
            logger.warning(
                "Schedule %s has a Hive projection but no canonical definition and no "
                "tombstone; it cannot fire and will not be reimported (#2467)",
                sid,
            )
            degraded.append(sid)
        # An empty template is the legitimate no-canonical-definition state
        # the clear-template route leaves; the row stays exactly as it is.
        return 0
    updates = _canonical_projection_updates(canonical)
    if not _projection_drifted(canonical, row):
        return 0
    updates["updated_at"] = canonical.updated_at
    replace_hive_schedule_row(sid, row.model_copy(update=updates))
    logger.info(
        "Repaired Hive projection of schedule %s from the canonical definition (#2467)",
        sid,
    )
    return 1


async def _resolve_pending_creates(runner: Any, container: Any) -> int:
    """Resolve interrupted-create markers left by a crash mid-create.

    Canonical row present: the create's canonical half committed, so the
    projection is built (or caught up) *from* it — visible, one identity, no
    false acknowledgment either way, since the client of a crashed request
    holds no receipt. Canonical row absent: the create never committed (or
    its compensation ran); the marker closes with nothing to project.
    """

    pending = ledger().pending_creates()
    if not pending:
        return 0
    from services.scheduler import (
        definition_lock,
        hive_schedule_row,
        replace_hive_schedule_row,
    )

    resolved = 0
    for sid in sorted(pending):
        try:
            async with definition_lock(sid):
                canonical = await container.schedule_store.get(sid)
                if canonical is None:
                    logger.info(
                        "Resolved the interrupted create of schedule %s: nothing was "
                        "committed canonically, so there is no projection to build (#2467)",
                        sid,
                    )
                else:
                    row = hive_schedule_row(sid)
                    if row is None:
                        replace_hive_schedule_row(sid, _hive_row_from_canonical(canonical))
                        resolved += 1
                        logger.info(
                            "Rebuilt the Hive projection of schedule %s from its committed "
                            "canonical definition after an interrupted create (#2467)",
                            sid,
                        )
                    elif _projection_drifted(canonical, row):
                        replace_hive_schedule_row(
                            sid, row.model_copy(update=_canonical_projection_updates(canonical))
                        )
                        resolved += 1
                ledger().clear_pending_create(sid)
        except Exception as exc:
            # Keep the marker: the next startup retries the resolution, and a
            # pending marker alone never fires anything.
            logger.warning(
                "Could not resolve the interrupted create of schedule %s; it stays pending: %s",
                sid,
                exc,
            )
    return resolved


async def run_startup_reconciliation() -> int:
    """The runner's one startup pass: import once, then repair from canonical.

    Runs before the first tick. With no migration marker, the legacy import
    pass runs (``backfill_canonical_definitions``) and the marker is written
    only on a fully successful pass — from then on, every startup repairs the
    projection from canonical truth and a stale Hive row can no longer
    rewrite it. A partially failed pass raises ``LegacyImportIncomplete``;
    the marker stays unwritten (retryable next startup) and the failed rows
    are degraded on the health surface. Returns
    how many rows changed. A half-wired Container (a configured core missing
    its schedule/project store) records the degradation on the health surface
    and reconciles nothing, exactly as the old backfill silently did with a
    missing store.
    """
    from services.scheduler import (
        LegacyImportIncomplete,
        ScheduleAdmissionUnavailable,
        _definition_authority,
        backfill_canonical_definitions,
        definition_lock,
        hive_schedule_ids,
    )

    lg = ledger()
    try:
        authority = _definition_authority()
    except ScheduleAdmissionUnavailable as exc:
        _PROJECTION_HEALTH["degraded"] = ["<container>"]
        logger.error("Schedule projection reconciliation unavailable: %s", exc)
        return 0
    if authority is None:
        return 0
    runner, container = authority

    _PROJECTION_HEALTH["degraded"] = []
    changed = await _resolve_pending_creates(runner, container)
    if not lg.migrated():
        skipped: list[str] = []
        try:
            changed += await backfill_canonical_definitions(degraded=skipped)
            lg.mark_migrated()
            # Rows the import could never authorize (the canonical scope's
            # deterministic refusals) are skipped, not failed: the marker
            # completes and they are named here until the repair pass takes
            # over the naming next startup.
            _PROJECTION_HEALTH["degraded"] = skipped
        except LegacyImportIncomplete as exc:
            # A failed put must not complete the migration: leave the marker
            # unwritten so the next startup retries the import pass, and name
            # the affected rows on the health surface rather than reporting a
            # clean migration over rows that cannot fire.
            _PROJECTION_HEALTH["degraded"] = sorted(set(skipped) | set(exc.failed_sids))
            logger.error(
                "Legacy schedule import incomplete; migration marker left unwritten for retry: %s",
                exc,
            )
    degraded: list[str] = []
    repair_ids = set(hive_schedule_ids())
    repair_ids.update(
        definition.schedule_id
        for definition in await container.schedule_store.list_all()
        if not definition.workspace_id.startswith("hive:schedule:")
    )
    for sid in sorted(repair_ids):
        try:
            async with definition_lock(sid):
                if await finish_tombstoned_row(sid, container):
                    changed += 1
                    continue
                changed += await _repair_projection_one(sid, container, degraded)
        except Exception as exc:
            degraded.append(sid)
            logger.warning(
                "Failed to reconcile Hive projection %s with canonical truth: %s", sid, exc
            )
    _PROJECTION_HEALTH["degraded"] = sorted(set(_PROJECTION_HEALTH["degraded"]) | set(degraded))
    _PROJECTION_HEALTH["migrated"] = lg.migrated()
    _PROJECTION_HEALTH["reconciled_at"] = datetime.now(UTC).isoformat()
    return changed
