"""RSI's authorized work source: the generic Workspace backlog contracts.

Epic #552 / child #50: RSI is a *downstream consumer* of the generic M3
work-source/control-plane contracts (#98 BacklogItem store, #100 claim/lease
semantics, #101 history/evidence) — it must not own a parallel backlog, claim
system, or campaign model. Before this module, the only "backlog" in
``maistro_rsi`` was prompt prose (the scout's ``backlog`` improvement kind);
the generic substrate in ``maistro.backlog`` / ``maistro.workspaces`` had
zero RSI references.

This seam is the consumption half:

* **next_objective** asks the authorized :class:`AgentBacklogSurface` to
  select and claim work — never the store directly — so an RSI cycle draws
  its objective from the same controlled work source the Workspace Agent
  (#804) and delegated agents use, under the embedder's authorization. A
  claim is a lease on progressing the item; it never reassigns the item's
  canonical Goal linkage and never grants anything.
* history (claim, run evidence, discovered work, closure) is filed through
  the generic :class:`BacklogHistoryStore` as *references* to canonical
  Run/NodeRun/Attempt identity — the journal never copies execution state,
  and neither does RSI.
* **propose_discovered_work** files prerequisites and defects RSI discovers
  while working an item as NEW items — proposed work in the generic backlog,
  never a silent widening of the current item's scope.

Nothing here schedules or executes work: canonical execution stays
``Goal -> Graph -> Run -> NodeRun -> Attempt``, and the persistent Workspace
Agent reconciler (#804) is untouched — RSI neither instantiates nor replaces
it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from maistro.backlog.agent_surface import AgentBacklogSurface
from maistro.backlog.model import BacklogClaim, BacklogItem, BacklogItemStatus
from maistro.backlog.store import BacklogStore
from maistro.workspaces.backlog_history import (
    BacklogHistoryStore,
    BacklogSubject,
    RunReference,
)
from maistro.workspaces.backlog_history.recording import (
    claim_recorded,
    claim_released,
    closure_recorded,
    discovered_work_recorded,
    run_evidence_recorded,
)

logger = structlog.get_logger()

#: ``source`` value on BacklogItems RSI proposes: discovered work is visibly
#: RSI-authored in the generic backlog, never disguised as human work.
RSI_WORK_SOURCE = "rsi"

#: ``actor_agent_id`` on history events RSI files (#101 provenance).
RSI_AGENT_ID = "rsi"


class RsiWorkSourceError(RuntimeError):
    """RSI asked its work source for something it cannot do or may not do."""


@dataclass(frozen=True)
class SourcedObjective:
    """One claimed unit of generic backlog work, mapped to an RSI objective.

    Goal linkage is carried by exact identity/revision exactly as the item
    holds it (#458): a reference, never a copy — claiming work does not make
    RSI the Goal's owner.
    """

    item_id: str
    workspace_id: str
    title: str
    instruction: str
    claim_id: str
    claimed_by: str
    lease_expires_at: datetime
    priority: int
    expected_version: int
    goal_id: str | None = None
    goal_revision: int | None = None


def objective_instruction(item: BacklogItem) -> str:
    """The RSI objective text for one BacklogItem: title, then details.

    Deterministic and derived only from the item's own recorded fields, so
    two consumers asked to work the same item receive the same objective.
    """
    details = item.details.strip()
    return f"{item.title.strip()}\n\n{details}" if details else item.title.strip()


class RsiWorkSource:
    """One RSI campaign's authorized window onto the generic work source.

    ``surface`` is the embedder's authorized :class:`AgentBacklogSurface`
    (list/select/claim/write/release, each fail-closed behind the embedder's
    ``authorize`` callable). ``history`` (optional) is the generic
    #101 journal; ``backlog_store`` (optional, the same store the surface
    wraps) is needed only for the paths the surface deliberately does not
    own: filing new discovered work and closing an item with evidence.
    """

    def __init__(
        self,
        surface: AgentBacklogSurface,
        *,
        history: BacklogHistoryStore | None = None,
        backlog_store: BacklogStore | None = None,
        project_id: str = "",
    ) -> None:
        self._surface = surface
        self._history = history
        self._store = backlog_store
        self._project_id = project_id

    async def next_objective(
        self, *, actor: str, workspace_id: str, lease_seconds: float | None = None
    ) -> SourcedObjective | None:
        """Select and claim the highest-priority claimable item, or None.

        Selection and the claim both go through the authorized surface —
        the store is never touched for the claim path. ``None`` means the
        workspace has no claimable work for this actor right now; a busy or
        unauthorized item surfaces as the surface's own error, never as a
        silent skip.
        """
        selection = await self._surface.select(actor=actor, workspace_id=workspace_id)
        if selection is None:
            return None
        item = selection.item
        claim_kwargs: dict[str, Any] = {}
        if lease_seconds is not None:
            claim_kwargs["lease_seconds"] = lease_seconds
        claim = await self._surface.claim(item.item_id, actor=actor, **claim_kwargs)
        return _sourced(item, claim)

    async def record_claim(
        self,
        sourced: SourcedObjective,
        *,
        run_id: str | None = None,
        actor_principal_id: str | None = None,
    ) -> None:
        """Journal the claim (#101); ``run_id`` cites the canonical Run when
        the claiming cycle's Run already exists, and is simply absent when
        the claim precedes any Run (the claim itself is durable in the
        backlog store either way; this receipt files when a history store is
        wired and logs — never silently pretends — when one is not).
        """

        async def _write(subject: BacklogSubject) -> None:
            await claim_recorded(
                self._history_store(),
                subject,
                claimant_agent_id=RSI_AGENT_ID,
                claim_run_id=run_id,
                actor_principal_id=actor_principal_id,
            )

        await self._record_optional(
            sourced, _write, note="claim taken" + (f" for canonical Run {run_id}" if run_id else "")
        )

    async def record_cycle_evidence(
        self,
        sourced: SourcedObjective,
        *,
        run_id: str,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
        summary: str = "",
        evaluation_refs: Sequence[str] = (),
    ) -> None:
        """Attach canonical Run/NodeRun/Attempt evidence to the item."""
        await self._record_optional(
            sourced,
            lambda subject: run_evidence_recorded(
                self._history_store(),
                subject,
                run_refs=(
                    RunReference(run_id=run_id, node_run_id=node_run_id, attempt_id=attempt_id),
                ),
                evaluation_refs=tuple(evaluation_refs),
                actor_agent_id=RSI_AGENT_ID,
                summary=summary,
            ),
        )

    async def record_discovered_work(
        self,
        sourced: SourcedObjective,
        *,
        child_item_ids: Sequence[str],
        discovered_by_run_id: str | None = None,
        summary: str = "",
    ) -> None:
        """Journal prerequisites/defects found while working the item.

        The children enter the journal as PROPOSED work — recorded scope,
        never a silently widened one (#101): the children were already filed
        into the generic backlog by :meth:`propose_discovered_work`; this
        receipt links them to the Run that discovered them. Like the other
        receipts, an unwired history store logs rather than pretending.
        """
        await self._record_optional(
            sourced,
            lambda subject: discovered_work_recorded(
                self._history_store(),
                subject,
                child_item_ids=tuple(child_item_ids),
                discovered_by_run_id=discovered_by_run_id,
                actor_agent_id=RSI_AGENT_ID,
                summary=summary,
            ),
            note="discovered work journaled",
        )

    async def propose_discovered_work(
        self,
        *,
        actor: str,
        workspace_id: str,
        title: str,
        details: str = "",
        parent_id: str | None = None,
        tags: tuple[str, ...] = (RSI_WORK_SOURCE,),
    ) -> str:
        """File newly discovered work into the generic backlog, as new work.

        A prerequisite or defect RSI finds is a *new* item in the same
        Workspace — proposed back into the generic work source with visible
        RSI provenance, exactly the acceptance #50 asks for ("discovered
        prerequisites/defects are proposed back into the generic backlog as
        new PROPOSED work rather than silently expanding authority"). It
        never edits the item it was discovered under.
        """
        if self._store is None:
            raise RsiWorkSourceError(
                "propose_discovered_work needs the generic BacklogStore; "
                "construct RsiWorkSource with backlog_store to file discovered work"
            )
        if not title.strip():
            raise RsiWorkSourceError("discovered work must carry a non-empty title")
        item = await self._store.create_item(
            workspace_id=workspace_id,
            title=title.strip(),
            actor=actor,
            details=details,
            tags=tags,
            parent_id=parent_id,
            source=RSI_WORK_SOURCE,
        )
        return item.item_id

    async def release(
        self,
        sourced: SourcedObjective,
        *,
        actor: str,
        reason: str = "",
    ) -> None:
        """Release the claim (the item stays open for the next claimant)."""
        await self._surface.release(sourced.item_id, actor=actor, claim_id=sourced.claim_id)
        await self._record_optional(
            sourced,
            lambda subject: claim_released(
                self._history_store(),
                subject,
                previous={"claimant_agent_id": RSI_AGENT_ID, "claim_run_id": None},
                actor_agent_id=RSI_AGENT_ID,
            ),
            note=f"claim released: {reason}" if reason else "claim released",
        )
        if reason:
            logger.info("rsi_work_source_released", item_id=sourced.item_id, reason=reason)

    async def close(
        self,
        sourced: SourcedObjective,
        *,
        actor: str,
        evidence_refs: Sequence[str],
        run_id: str,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
        outcome: str = BacklogItemStatus.DONE,
        closure_summary: str = "",
    ) -> None:
        """Close the item against evidence, through the generic contracts.

        Closure is refused without evidence refs — a completed Run is
        supporting evidence at best, never sufficient alone (ADR-082426-19ed)
        — and the terminal status move goes through the store's own
        ``close_item`` (the only path into a terminal status), with the #101
        journal receipt citing the canonical Run identity beside it.
        """
        if self._store is None:
            raise RsiWorkSourceError(
                "close needs the generic BacklogStore; construct RsiWorkSource "
                "with backlog_store to close items"
            )
        if not evidence_refs:
            raise RsiWorkSourceError(
                "closing a BacklogItem requires evidence_refs; a completed Run is "
                "not closure evidence by itself"
            )
        await self._store.close_item(
            sourced.item_id,
            expected_version=sourced.expected_version,
            actor=actor,
            outcome=outcome,
            closure_summary=closure_summary or f"closed by {RSI_AGENT_ID} campaign",
            evidence_refs=tuple(evidence_refs),
        )
        await self._record_optional(
            sourced,
            lambda subject: closure_recorded(
                self._history_store(),
                subject,
                evidence_refs=tuple(evidence_refs),
                run_refs=(
                    RunReference(run_id=run_id, node_run_id=node_run_id, attempt_id=attempt_id),
                ),
                to_status=outcome,
                actor_agent_id=RSI_AGENT_ID,
                summary=closure_summary,
            ),
            note="item closed with evidence",
        )

    def _history_store(self) -> BacklogHistoryStore:
        if self._history is None:
            raise RsiWorkSourceError(
                "this RsiWorkSource has no BacklogHistoryStore; construct it with "
                "history to file journal events"
            )
        return self._history

    def _subject(self, sourced: SourcedObjective) -> BacklogSubject:
        if not self._project_id.strip():
            raise RsiWorkSourceError(
                "this RsiWorkSource has no project scope; construct it with "
                "project_id to file journal events"
            )
        return BacklogSubject(
            workspace_id=sourced.workspace_id,
            project_id=self._project_id,
            item_id=sourced.item_id,
        )

    async def _record_optional(
        self, sourced: SourcedObjective, writer: Any, *, note: str = ""
    ) -> None:
        """File one journal event when history is wired; log when it is not.

        The store-side state change (release, closure) has already happened
        by the time these receipts are written, so a campaign that ran
        without a history store must not lose the work — but it also must
        not pretend it filed a receipt it could not.
        """
        if self._history is None:
            logger.warning("rsi_work_source_history_unwired", item_id=sourced.item_id, note=note)
            return
        await writer(self._subject(sourced))


def _sourced(item: BacklogItem, claim: BacklogClaim) -> SourcedObjective:
    """Map one claimed BacklogItem onto the RSI objective shape."""
    return SourcedObjective(
        item_id=item.item_id,
        workspace_id=item.workspace_id,
        title=item.title,
        instruction=objective_instruction(item),
        claim_id=claim.claim_id,
        claimed_by=claim.claimed_by,
        lease_expires_at=claim.lease_expires_at,
        priority=item.priority,
        expected_version=item.version,
        goal_id=item.goal_id,
        goal_revision=item.goal_revision,
    )
