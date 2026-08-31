"""Surveying and repairing Attempts emptied by the pre-#566 serialization.

ADR-083026-14c3. Before #566, a node returning a typed model persisted its
Attempt as ``output: {}``: Pydantic serialized a union member declared as bare
``BaseModel`` through that class's empty schema. SPEC-082926-2844 fixed the
contract and left the already-written rows to this module.

**Where the rows are.** Through the configured `RunStore`, which is what
`CanonicalDurableRunStore` assembles Attempts from. The withdrawn first version
of this repair (#638) ran over the document-shaped `durable_graph_runs` table
instead — a table nothing in production writes — so against a real deployment
it created an empty table and reported that there was nothing to repair. That
is the failure this module exists not to repeat, and AC-1 is the regression.

**What counts as damage.** Not emptiness. ``output: {}`` is indistinguishable
from a node that genuinely returned an empty mapping, and the envelope never
recorded which. An Attempt is repairable only where a *second copy* proves the
loss: its NodeRun accepted it, and that NodeRun's own result carries something
the Attempt's does not.

That second copy is the graph executor's `_result_output`, which has always
dumped the model explicitly onto `NodeRun.result`. The reconciliation path
(tasks, chat) records the whole Attempt result there instead, so a NodeRun
whose result *equals* the Attempt's carries no second copy at all — which is
the exact discriminator used below, rather than a guess about shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from maistro.runs.model import Attempt, NodeRun, Run, RunStatus, evidence_values_equal
from maistro.runs.store import RunStore

#: How many Runs one sweep examines per status. `RunStore` offers no cursor
#: over every Run, so a walk is necessarily bounded; the survey reports when it
#: stopped here rather than presenting a partial sweep as a complete one.
DEFAULT_SWEEP_LIMIT = 500


class Disposition(StrEnum):
    """Why an Attempt with an emptied output can or cannot be repaired."""

    REPAIRABLE = "repairable"
    #: No accepted outcome names this Attempt -- a superseded retry, a failure,
    #: or one still in flight. There is no second copy anywhere.
    NOT_ACCEPTED = "not_accepted"
    #: Accepted, but the NodeRun holds the same value the Attempt does, so it
    #: is not a separate projection and proves nothing. Nothing distinguishes
    #: an emptied output from one that was genuinely `{}`.
    NO_SECOND_COPY = "no_second_copy"


@dataclass(frozen=True)
class Finding:
    """One Attempt whose recorded output is empty, and what can be done."""

    run_id: str
    node_run_id: str
    attempt_id: str
    disposition: Disposition
    #: The output recovered from the NodeRun, present only when REPAIRABLE.
    recovered: object | None = None

    @property
    def repairable(self) -> bool:
        return self.disposition is Disposition.REPAIRABLE


@dataclass(frozen=True)
class Survey:
    """What one sweep found, and what it could not see."""

    findings: tuple[Finding, ...] = ()
    runs_examined: int = 0
    #: Statuses whose listing filled the sweep limit. Non-empty means the sweep
    #: was truncated and a further pass may find more (AC-8).
    truncated_statuses: tuple[RunStatus, ...] = ()
    #: The Workspace this sweep was confined to, or None for every Workspace in
    #: the database. A caller that names one must not be shown -- or worse, have
    #: repaired -- another tenant's records (Codex, #690).
    workspace_id: str | None = None

    @property
    def repairable(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.repairable)

    @property
    def complete(self) -> bool:
        return not self.truncated_statuses


@dataclass
class _Accumulator:
    findings: list[Finding] = field(default_factory=list)
    runs_examined: int = 0
    truncated: list[RunStatus] = field(default_factory=list)


def _has_emptied_output(attempt: Attempt) -> bool:
    """Whether this Attempt's recorded `NodeResult` has an empty output.

    A mapping with an ``output`` key holding an empty mapping is the shape the
    pre-#566 serialization produced. An absent key is a different record
    entirely -- the reconciliation path's evidence, not a graph node's -- and
    is not a candidate.
    """
    result = attempt.result
    if not isinstance(result, dict) or "output" not in result:
        return False
    output = result["output"]
    return isinstance(output, dict) and not output


def _recovers_nothing(value: object) -> bool:
    """Whether a NodeRun result offers anything the emptied Attempt lacks.

    `None` and `{}` both say the logical record is as empty as the physical
    one, so neither is evidence that anything was lost. They have to be named,
    because they compare *unequal* to the Attempt's `{"output": {}}` -- one is
    a projection and the other an envelope (Codex, #690). Equality alone would
    therefore call a node that genuinely returned `{}` repairable, write `{}`
    back unchanged, and report the same Attempt on every sweep after that: a
    finding no operator could ever clear.
    """
    return value is None or (isinstance(value, dict) and not value)


def classify(attempt: Attempt, node_run: NodeRun) -> Finding:
    """Decide what can be done for one Attempt with an emptied output."""
    outcome = node_run.accepted_outcome
    if outcome is None or outcome.attempt_result.attempt_id != attempt.attempt_id:
        disposition = Disposition.NOT_ACCEPTED
    elif _recovers_nothing(node_run.result) or evidence_values_equal(
        node_run.result, attempt.result
    ):
        # Equal means the NodeRun is carrying the Attempt's own evidence rather
        # than a separate projection of it -- the reconciliation path's shape.
        # There is nothing here the Attempt does not already have, and an empty
        # logical record says the same thing in the other direction.
        disposition = Disposition.NO_SECOND_COPY
    else:
        return Finding(
            run_id=node_run.run_id,
            node_run_id=node_run.node_run_id,
            attempt_id=attempt.attempt_id,
            disposition=Disposition.REPAIRABLE,
            recovered=node_run.result,
        )
    return Finding(
        run_id=node_run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        disposition=disposition,
    )


async def survey(
    store: RunStore,
    *,
    limit: int = DEFAULT_SWEEP_LIMIT,
    workspace_id: str | None = None,
) -> Survey:
    """Find every Attempt with an emptied output the sweep can reach.

    Reads only. Applying anything is `repair`'s job, so that an operator can
    see what would happen before it does — the first thing anyone wants from a
    data-repair tool.

    `workspace_id` confines the sweep. Without it the listing is global, so a
    caller naming one Workspace surveyed — and with ``--apply`` repaired —
    every other Workspace in the database (Codex, #690). The filter is applied
    after the listing rather than pushed into it, because `list_by_status`
    selects on Project and this question is about the Workspace above it; the
    limit is therefore spent on rows that may be filtered out, which is why a
    filtered sweep still reports the statuses that filled it.

    **Archived Runs are outside every sweep.** Once a terminal Run's payload is
    offloaded to the archive tier the store's listing skips it — `PgRunStore`
    selects `payload IS NOT NULL` — so a cold record holding the very loss this
    command repairs is invisible here, and no larger `limit` reveals it. That
    is stated rather than silently tolerated: reporting a clean sweep over
    records it could not read is the false clean bill of health this design
    exists to refuse (AC-1).
    """
    acc = _Accumulator()
    seen: set[str] = set()
    for status in RunStatus:
        runs = await store.list_by_status(status, limit=limit)
        if len(runs) >= limit:
            acc.truncated.append(status)
        for run in runs:
            if run.run_id in seen:
                continue
            seen.add(run.run_id)
            if workspace_id is not None and run.workspace_id != workspace_id:
                continue
            acc.runs_examined += 1
            await _examine_run(store, run, acc)
    return Survey(
        findings=tuple(acc.findings),
        runs_examined=acc.runs_examined,
        truncated_statuses=tuple(acc.truncated),
        workspace_id=workspace_id,
    )


async def _examine_run(store: RunStore, run: Run, acc: _Accumulator) -> None:
    for node_run in await store.list_node_runs(run.run_id):
        for attempt in await store.list_attempts(node_run.node_run_id):
            if _has_emptied_output(attempt):
                acc.findings.append(classify(attempt, node_run))


async def repair(store: RunStore, findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Apply every repairable finding. Returns the ones actually written.

    Unrepairable findings are skipped rather than attempted: there is nothing
    to write for them, and writing a guess into a durable record is the outcome
    this whole design exists to avoid.
    """
    applied: list[Finding] = []
    for finding in findings:
        if not finding.repairable:
            continue
        attempt = await store.get_attempt(finding.attempt_id)
        if attempt is None:  # pragma: no cover - surveyed ids resolve
            continue
        result = dict(attempt.result) if isinstance(attempt.result, dict) else {}
        result["output"] = finding.recovered
        await store.repair_attempt_result(finding.attempt_id, result=result)
        applied.append(finding)
    return tuple(applied)


__all__ = [
    "DEFAULT_SWEEP_LIMIT",
    "Disposition",
    "Finding",
    "Survey",
    "classify",
    "repair",
    "survey",
]
