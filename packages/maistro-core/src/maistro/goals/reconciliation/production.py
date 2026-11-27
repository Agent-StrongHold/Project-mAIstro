"""Production decision semantics for the Goal reconciliation loop (M3 #805).

#806 built the *mechanics* — durable wakes, one claim/lease/fence per Goal,
idempotent admissions, bounded sweeps — and deliberately refused to say what a
reconciliation *decision* means. #805 owns that meaning; this module is its
production spelling, composed by ``create_container`` so the persistent
Workspace Agent actually decides rather than only reclaiming fences:

- :class:`FactDrivenReconciliationPolicy` — the deterministic decide-half. It
  reads only the durable :class:`GoalFacts` the mechanics hand it (never a
  process-local queue, never a model call) and answers in the milestone's
  vocabulary:

  * **progress** — fresh capacity, no work owed elsewhere: admit one Run.
  * **wait** — pursuit work in flight, or nothing new to react to: sleep
    until a durable wake makes the Goal due again (no polling horizon).
  * **gate** — budget exhausted: park as gated so blocked work consumes
    nothing.
  * **replan** — the decision key is derived from the triggering wake's
    canonical correlation id, so a *new* canonical change (a Goal revision
    bump, fresh evidence) yields a *new* key and therefore new work against
    the new desired state — while a replayed event collapses onto the
    admission it already produced.
  * **delegate** — the admitted Run's one node is in-process A2A delegation
    to the Goal's accountable Agent (``agent.delegate_remote``), the same
    node kind every directly-submitted task executes through. Goal → Subgoal
    *decomposition* — choosing that a Goal should split and into what —
    stays with the planner that owns desired-state language; this module
    fulfils delegation-shaped execution, it does not invent the split.

  The policy never settles a Goal. ``complete`` is not derivable from a Run
  outcome: Goal completion stays evidence-backed desired-state truth owned by
  the Goal authority (#804), never inferred from the latest Run terminal
  status. That is why every terminal decision here is a sleep or a gate, and
  why ``PolicyDecision.complete`` is never set.

- :class:`GoalRunAdmitter` — the physical half of an admission
  (:class:`~maistro.goals.reconciliation.reconciler.PhysicalAdmitter`): it
  fulfils a recorded admission by creating the canonical artifact through the
  shipped admission seam — a QUEUED Run over a one-node delegation Graph,
  bound to the Goal and the exact desired-state revision it was admitted
  against. The durable consumer tick owns everything after that: claiming,
  NodeRun/Attempt creation, execution and disposition under the canonical
  ``Goal -> Graph -> Run -> NodeRun -> Attempt`` lineage. The admitter never
  executes anything and never reads an outcome.

Both halves fail loudly and per-Goal: an unfulfillable admission raises a
:class:`GoalReconciliationError` subclass the reconciler contains as that
Goal's pass error, so one broken Goal never discards its siblings in the
sweep and never crashes the operator cadence.
"""

from __future__ import annotations

from typing import Any

from maistro.goals.reconciliation.model import Goal, GoalFacts, GoalStatus
from maistro.goals.reconciliation.reconciler import PlannedAdmission, PolicyDecision
from maistro.goals.reconciliation.store import GoalReconciliationError
from maistro.goals.store import GoalStore
from maistro.runs.admission import admit_direct_work
from maistro.runs.goal_context import (
    ACCOUNTABLE_AGENT_ID_KEY,
    DESIRED_STATE_KEY,
    GOAL_ID_KEY,
    GOAL_REVISION_KEY,
)
from maistro.runs.model import RunStatus
from maistro.runs.sources import GOAL_RECONCILIATION_SOURCE
from maistro.runs.store import RunStore
from maistro.runs.task_kinds import DELEGATE_NODE_KIND

__all__ = [
    "DISCOVERY_CORRELATION",
    "GOAL_RECONCILIATION_AGENT",
    "FactDrivenReconciliationPolicy",
    "GoalDelegationUnsupported",
    "GoalPursuitUnresolvable",
    "GoalRunAdmitter",
]

#: Reserved A2A principal a goal-pursuit Run delegates *from*. Mirrors
#: ``DIRECT_SUBMISSION_AGENT``: registered by the agent factory with the
#: roster's targets, so a blank ``from_agent`` never makes an admitted
#: pursuit look like a target refusal rather than an authorized system
#: submission.
GOAL_RECONCILIATION_AGENT = "__maistro_goal_reconciliation__"

#: Correlation token for the crash point "after Goal commit, before
#: notification": a ``ready`` Goal whose row is durable but that no wake fact
#: ever reached. The Goal row itself is the discovery fact, so the first
#: consultation that finds unowned capacity progresses it under this
#: constant correlation — one stable decision key, therefore one admission,
#: no matter how many sweeps pass before the pursuit Run is admitted.
DISCOVERY_CORRELATION = "discovery"


class GoalPursuitUnresolvable(GoalReconciliationError):
    """An admission's pursuit cannot be resolved into a canonical Run.

    The canonical Goal the admission names does not exist, or the Goal's
    current revision is missing from its append-only chain (a misbehaving
    store). Recorded as that Goal's pass error — never silently dropped,
    never fatal to the sweep.
    """


class GoalDelegationUnsupported(GoalReconciliationError):
    """An admission names a kind this admitter does not fulfil.

    ``kind="run"`` is the one admission the production admitter fulfils. A
    ``subgoal`` admission needs the decomposition producer's child desired
    state, which a :class:`~maistro.goals.reconciliation.reconciler.PlannedAdmission`
    does not carry — refusing loudly keeps the admission open for whoever can
    fulfil it instead of minting an empty Goal nobody described.
    """


def _pursuit_name(desired_state: str, *, limit: int = 80) -> str:
    """A bounded Graph name from the desired state: first line, bounded."""
    line = desired_state.strip().splitlines()[0].strip() if desired_state.strip() else ""
    if not line:
        return "goal pursuit"
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


class FactDrivenReconciliationPolicy:
    """The #805 decide-half: deterministic answers from durable facts only.

    Consulted once per claimed Goal per sweep pass. Every branch reads only
    the :class:`GoalFacts` the mechanics assembled from the store — the Goal
    row, its undispatched wakes, its open admissions — so the same facts
    always produce the same decision, on any replica, after any restart.
    """

    async def decide(self, facts: GoalFacts) -> PolicyDecision:
        goal = facts.goal
        if goal.status in GoalStatus.terminal():
            # Terminal posture already fenced admission; re-deciding a
            # withdrawn or settled Goal would only record noise.
            return PolicyDecision()
        if goal.budget_exhausted():
            # Gate, not sleep: blocked work consumes no decisions and no
            # model calls, and a relevant wake can still unblock it (the
            # budget is a ceiling an operator or a revision may raise).
            return PolicyDecision(
                blocked_reason=(
                    f"budget exhausted: {goal.runs_admitted}/{goal.budget_max_runs} runs admitted"
                )
            )
        for wake in facts.pending_wakes:
            if wake.unblocks:
                # Replan: the correlation id is the canonical event that
                # changed the Goal's world. A replay collapses onto the key
                # it already produced; a genuinely new change produces a new
                # key — and therefore new work against the new facts.
                correlation = wake.correlation_id or f"wake:{wake.wake_id}"
                return self._progress(goal, correlation)
        if facts.pending_admissions:
            # Work is recorded but its artifact is not confirmed yet (the
            # crash window between record and fulfilment). Never stack a
            # second admission while one is open; the mechanics repair the
            # open one before this policy is consulted again.
            return PolicyDecision()
        if goal.runs_admitted == 0:
            # Discovery: the Goal row is the durable fact a Goal committed
            # with no wake ever recorded. Progress it once under the stable
            # discovery key; the admission dedupe makes every later sweep
            # with the same facts converge on the same single admission.
            return self._progress(goal, DISCOVERY_CORRELATION)
        # Wait: pursuit work was admitted (and fulfilled — open admissions
        # were handled above) and no new canonical change has arrived. Park
        # wake-driven: ``sleep_for=None`` with no blocked reason sleeps
        # without a sweep horizon, so the Goal costs nothing until a durable
        # wake (a revision change, fresh evidence, a subgoal transition)
        # makes it due again.
        return PolicyDecision()

    @staticmethod
    def _progress(goal: Goal, correlation: str) -> PolicyDecision:
        """One admission per canonical change, keyed by that change's id.

        The key is wake-correlation-scoped, deliberately not
        control-revision-scoped: the control row's ``revision`` is posture
        bookkeeping that can trail the canonical Goal, and a key derived from
        a stale value would both misname the decision and let two different
        canonical changes that observed the same stale value collide.
        """
        return PolicyDecision(
            admissions=(
                PlannedAdmission(
                    kind="run",
                    decision_key=f"{goal.goal_id}:{correlation}",
                    correlation_id=correlation,
                ),
            )
        )


class GoalRunAdmitter:
    """Fulfils a recorded admission as one canonical QUEUED pursuit Run.

    The physical half of the production composition: the reconciliation
    store records *that* work was admitted; this admitter creates the
    artifact the admission names — one single-node delegation Graph over the
    Goal's current desired state, admitted QUEUED and bound to
    ``goal_id``/``goal_revision`` through the same ``admit_direct_work`` seam
    tasks and chat use. Everything after the QUEUED row — claiming,
    NodeRun/Attempt creation, execution, disposition — belongs to the
    canonical consumer tick, exactly as for a schedule Run.
    """

    def __init__(
        self,
        runs: RunStore,
        goals: GoalStore,
        *,
        source: str = GOAL_RECONCILIATION_SOURCE,
    ) -> None:
        self._runs = runs
        self._goals = goals
        self._source = source

    async def admit(self, admission: Any) -> str:
        """Fulfil ``admission`` and return the Run id it created.

        Idempotent per the admission's ``decision_key`` by construction of
        the caller: the store dedupes the decision before this is reached,
        and the crash-repair path re-runs this with the *same* recorded
        admission rather than filing a second one.
        """
        if admission.kind != "run":
            raise GoalDelegationUnsupported(
                f"goal reconciliation fulfils 'run' admissions, not {admission.kind!r}"
            )
        goal = await self._goals.get_goal(admission.goal_id)
        if goal is None:
            raise GoalPursuitUnresolvable(
                f"canonical Goal {admission.goal_id!r} does not exist for admission "
                f"{admission.decision_key!r}"
            )
        # The canonical Goal is the revision authority. The control row's
        # revision can trail it (nothing in the control plane rewrites
        # desired state), so fulfilment binds the Run to the canonical
        # CURRENT revision and its exact language — the pairing #1572
        # requires: a Run's ``goal_revision`` is always the revision whose
        # desired state the Run carries.
        desired_state = await self._desired_state(admission.goal_id, goal.current_revision)
        run = await admit_direct_work(
            self._runs,
            workspace_id=goal.workspace_id,
            project_id=goal.project_id,
            node_type=DELEGATE_NODE_KIND,
            name=_pursuit_name(desired_state),
            source=self._source,
            parameters={
                "from_agent": GOAL_RECONCILIATION_AGENT,
                "task": desired_state,
                "to_agent": goal.agent_id,
            },
            description=desired_state,
            # The accountable Agent is the acting identity: the pursuit runs
            # as the Agent the Goal names, not as a caller-supplied string.
            actor_principal_id=goal.agent_id,
            provenance={
                GOAL_ID_KEY: admission.goal_id,
                GOAL_REVISION_KEY: str(goal.current_revision),
                ACCOUNTABLE_AGENT_ID_KEY: goal.agent_id,
                DESIRED_STATE_KEY: desired_state,
            },
            # QUEUED in the same insert, like a schedule fire: no caller
            # holds a receipt here, so a CREATED pursuit Run would be
            # admitted work nobody would ever execute.
            initial_status=RunStatus.QUEUED,
            goal_id=admission.goal_id,
            goal_revision=goal.current_revision,
        )
        return run.run_id

    async def _desired_state(self, goal_id: str, revision: int) -> str:
        """The desired state the Goal's pursued revision committed to.

        Historical revisions are never rewritten, so a Run admitted against
        revision N always carries revision N's language even after the Goal
        has moved on.
        """
        for entry in await self._goals.list_goal_revisions(goal_id):
            if entry.revision == revision:
                return entry.desired_state
        raise GoalPursuitUnresolvable(f"Goal {goal_id!r} has no revision {revision} to pursue")
