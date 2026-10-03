"""Rolling cycle summaries, periodic simplification, hard resets (#301).

All three are **appends**, never edits: the log's losslessness is the feature
the epic asks for, so every policy below changes the working set by adding a
marker entry the derivation reads, and the full history stays retrievable
after any number of simplifications and resets.

* ``append_cycle_summary`` — one cycle's active entries folded into a compact
  extractive summary (no LLM: the summary is lines and counts, which is also
  what keeps it testable).
* ``simplify`` — the periodic pass: active entries older than ``keep_cycles``
  fold into one rolling summary. Survival-set entries are skipped: they said
  they survive.
* ``hard_reset`` — append a RESET marker naming its survival set. The next
  derivation (and the next hydration) starts from the marker; everything
  before it is out of the working set but exactly where it was in the log.
"""

from __future__ import annotations

from maistro.memory.working.projection import WorkspaceWorkingMemory
from maistro.memory.working.store import WorkspaceLogStore
from maistro.memory.working.types import (
    ObservationKind,
    WorkspaceObservation,
    reset_entry,
    summary_entry,
)


def _foldable(
    projection: WorkspaceWorkingMemory,
    cycle: int,
    kinds: tuple[ObservationKind, ...] | None,
) -> list[WorkspaceObservation]:
    """The cycle's active entries a rolling summary may fold."""
    return [
        e
        for e in projection.active_entries()
        if e.cycle == cycle
        and e.kind is not ObservationKind.SUMMARY
        and (kinds is None or e.kind in kinds)
    ]


def _cycle_shape(active: list[WorkspaceObservation]) -> str:
    """One-line census of what the cycle held, e.g. ``2 observation, 1 tool_result``."""
    counts: dict[str, int] = {}
    for entry in active:
        counts[entry.kind.value] = counts.get(entry.kind.value, 0) + 1
    return ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))


async def append_cycle_summary(
    store: WorkspaceLogStore,
    projection: WorkspaceWorkingMemory,
    *,
    cycle: int,
    run_id: str = "",
    kinds: tuple[ObservationKind, ...] | None = None,
) -> WorkspaceObservation | None:
    """Fold one cycle's active entries into a rolling summary entry.

    Returns the appended summary, or ``None`` when the cycle has nothing
    active to fold — a policy that appends empty summaries would be spam the
    working set then has to fold itself.
    """
    active = _foldable(projection, cycle, kinds)
    if not active:
        return None
    lines = [f"cycle {cycle}: {_cycle_shape(active)}"]
    lines.extend(f"- {entry.text}" for entry in active)
    summary = summary_entry(
        workspace_id=projection.workspace_id,
        cycle=cycle,
        folded_ids=[e.entry_id for e in active],
        through_cycle=cycle,
        text="\n".join(lines),
        run_id=run_id,
    )
    stored = await store.append(summary)
    projection.apply(stored)
    return stored


async def simplify(
    store: WorkspaceLogStore,
    projection: WorkspaceWorkingMemory,
    *,
    keep_cycles: int = 2,
    run_id: str = "",
) -> WorkspaceObservation | None:
    """Periodic simplification: fold stale cycles into one rolling summary.

    ``keep_cycles`` is the window the working set keeps verbatim; everything
    active older than it folds. Entries in the survival set are never folded
    — survival is a promise about simplification too, not only resets.
    """
    active = projection.active_entries()
    if not active:
        return None
    newest_cycle = max(e.cycle for e in active)
    stale = [
        e
        for e in active
        if e.cycle <= newest_cycle - keep_cycles
        and e.kind is not ObservationKind.SUMMARY
        and not e.survive_reset
    ]
    if not stale:
        return None
    lines = [f"rolled {len(stale)} entr(y/ies) through cycle {newest_cycle - keep_cycles}:"]
    lines.extend(f"- {entry.text}" for entry in stale)
    summary = summary_entry(
        workspace_id=projection.workspace_id,
        cycle=newest_cycle,
        folded_ids=[e.entry_id for e in stale],
        through_cycle=newest_cycle - keep_cycles,
        text="\n".join(lines),
        run_id=run_id,
    )
    stored = await store.append(summary)
    projection.apply(stored)
    return stored


async def hard_reset(
    store: WorkspaceLogStore,
    projection: WorkspaceWorkingMemory,
    *,
    survival_ids: list[str] | None = None,
    cycle: int | None = None,
    run_id: str = "",
) -> WorkspaceObservation:
    """Hard-reset the working set, keeping only the explicit survival set.

    ``survival_ids`` name the entries to keep, by id, up front — the reset is
    explicit about what it keeps *in the log record itself*, which is what
    makes a later rebuild reproduce the same working set. Entries flagged
    ``survive_reset`` survive automatically and need not be listed. Unknown
    ids raise: a survival set that silently names nothing is a reset that
    loses everything while claiming otherwise.
    """
    workspace_id = projection.workspace_id
    survival: list[str] = []
    for entry_id in survival_ids or []:
        entry = projection.entry(entry_id) or await store.get_entry(workspace_id, entry_id)
        if entry is None:
            raise KeyError(f"survival id {entry_id!r} is not in workspace {workspace_id!r}")
        survival.append(entry_id)
    active = projection.active_entries()
    current_cycle = cycle if cycle is not None else max((e.cycle for e in active), default=0)
    marker = reset_entry(
        workspace_id=workspace_id,
        cycle=current_cycle,
        survival_ids=survival,
        run_id=run_id,
    )
    stored = await store.append(marker)
    projection.apply(stored)
    return stored
