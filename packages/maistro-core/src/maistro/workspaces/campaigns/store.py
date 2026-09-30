"""The campaign store: durable records for campaigns, controls, parks and audit.

A store persists *policy and decisions*, not work. It is not a scheduler, a
queue or a lease holder; the execution spine keeps its own primitives. Two
implementations ship:

* :class:`InMemoryCampaignStore` — the reference. The definition of the
  contract, used directly by tests and by deployments that accept losing
  controls on restart (with a loud warning from the wiring).
* :class:`SqliteCampaignStore` — the durable twin over the deployment's
  SQLite database, so pin-next / pause / exclude / human-only survive a
  restart (AC-5). Both run the same conformance suite
  (``tests/workspaces/test_campaign_stores.py``).

Every mutation appends a :class:`CampaignAuditRecord` naming the actor and the
``policy_version`` it was made under (invariant 3); eligibility and selection
decisions computed by the policy are appended through
:meth:`CampaignStore.append_audit` by the :class:`CampaignSelector` facade.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.workspaces.campaigns.model import (
    Actor,
    AuditKind,
    AutonomyMode,
    BacklogItemView,
    BudgetUsage,
    CampaignAuditRecord,
    CampaignDefinition,
    CampaignPolicy,
    ControlKind,
    ControlRecord,
    ItemPolicyRecord,
    ParkEvidence,
    ParkRecord,
    ParkUnpark,
    SelectionSignals,
)
from maistro.workspaces.campaigns.policy import (
    EligibilityDecision,
    GoalReader,
    RankedCandidate,
    applicable_campaigns,
    audit_eligibility,
    audit_selection,
    evaluate_items,
    order_candidates,
)


class CampaignNotFound(KeyError):
    """No campaign record carries this id."""

    def __init__(self, campaign_id: str) -> None:
        super().__init__(campaign_id)


class ControlNotFound(KeyError):
    def __init__(self, control_id: str) -> None:
        super().__init__(control_id)


class ParkNotFound(KeyError):
    def __init__(self, park_id: str) -> None:
        super().__init__(park_id)


@runtime_checkable
class CampaignStore(Protocol):
    """Durable, attributed campaign records (Q4: beside the campaign, never
    on the BacklogItem, never on the Goal)."""

    async def create_campaign(
        self,
        *,
        workspace_id: str,
        name: str,
        actor: Actor,
        policy: CampaignPolicy | None = None,
        project_id: str | None = None,
        campaign_id: str | None = None,
        created_at: datetime | None = None,
    ) -> CampaignDefinition: ...

    async def get_campaign(self, campaign_id: str) -> CampaignDefinition | None: ...

    async def require_campaign(self, campaign_id: str) -> CampaignDefinition: ...

    async def list_campaigns(
        self, workspace_id: str | None = None, *, latest_only: bool = True
    ) -> list[CampaignDefinition]: ...

    async def update_policy(
        self, campaign_id: str, policy: CampaignPolicy, *, actor: Actor
    ) -> CampaignDefinition:
        """Record a new ``policy_version``; earlier versions stay readable."""
        ...

    async def set_control(
        self,
        campaign_id: str,
        kind: ControlKind,
        *,
        actor: Actor,
        item_id: str | None = None,
        set_at: datetime | None = None,
    ) -> ControlRecord: ...

    async def clear_control(self, control_id: str, *, actor: Actor) -> ControlRecord:
        """Clearing is its own recorded decision, not a deletion."""
        ...

    async def list_controls(
        self, campaign_id: str, *, active_only: bool = False
    ) -> list[ControlRecord]: ...

    async def get_control(self, control_id: str) -> ControlRecord | None: ...

    async def set_item_record(
        self,
        campaign_id: str,
        item_id: str,
        *,
        actor: Actor,
        mode_override: AutonomyMode | None = None,
        human_priority: float | None = None,
    ) -> ItemPolicyRecord:
        """Replace the item's per-campaign record. ``None`` clears the field:
        the API writes the whole record, so a partial update is expressed by
        reading, changing and writing it back."""
        ...

    async def list_item_records(self, campaign_id: str) -> list[ItemPolicyRecord]: ...

    async def park_item(
        self,
        campaign_id: str,
        item_id: str,
        evidence: ParkEvidence,
        *,
        actor: Actor,
    ) -> ParkRecord: ...

    async def unpark_item(self, park_id: str, *, actor: Actor) -> ParkRecord: ...

    async def get_park(self, park_id: str) -> ParkRecord | None: ...

    async def list_parks(
        self, campaign_id: str, *, active_only: bool = False
    ) -> list[ParkRecord]: ...

    async def record_usage(
        self,
        campaign_id: str,
        *,
        actor: Actor,
        cost_usd: float = 0.0,
        minutes: float = 0.0,
        completions: int = 0,
    ) -> BudgetUsage: ...

    async def get_usage(self, campaign_id: str) -> BudgetUsage: ...

    async def append_audit(self, *records: CampaignAuditRecord) -> None: ...

    async def audit_trail(
        self, campaign_id: str | None = None, *, limit: int | None = None
    ) -> list[CampaignAuditRecord]: ...


class InMemoryCampaignStore:
    """The reference implementation. Plain dicts; durability is the durable
    twin's job, behavior is this class's job."""

    def __init__(self) -> None:
        self._campaigns: dict[str, list[CampaignDefinition]] = {}
        self._controls: dict[str, ControlRecord] = {}
        self._item_records: dict[tuple[str, str], ItemPolicyRecord] = {}
        self._parks: dict[str, ParkRecord] = {}
        self._audit: list[CampaignAuditRecord] = []
        self._usage: dict[str, BudgetUsage] = {}

    async def create_campaign(
        self,
        *,
        workspace_id: str,
        name: str,
        actor: Actor,
        policy: CampaignPolicy | None = None,
        project_id: str | None = None,
        campaign_id: str | None = None,
        created_at: datetime | None = None,
    ) -> CampaignDefinition:
        fields: dict[str, object] = {
            "workspace_id": workspace_id,
            "name": name,
            "policy": policy or CampaignPolicy(),
            "project_id": project_id,
            "created_by": actor,
        }
        if campaign_id is not None:
            fields["campaign_id"] = campaign_id
        if created_at is not None:
            fields["created_at"] = created_at
        campaign = CampaignDefinition.model_validate(fields)
        self._campaigns.setdefault(campaign.campaign_id, []).append(campaign)
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.CAMPAIGN_CREATED,
                policy_version=campaign.policy_version,
                campaign_id=campaign.campaign_id,
                payload={"name": campaign.name, "workspace_id": workspace_id},
            )
        )
        return campaign

    async def get_campaign(self, campaign_id: str) -> CampaignDefinition | None:
        versions = self._campaigns.get(campaign_id)
        return versions[-1] if versions else None

    async def require_campaign(self, campaign_id: str) -> CampaignDefinition:
        campaign = await self.get_campaign(campaign_id)
        if campaign is None:
            raise CampaignNotFound(campaign_id)
        return campaign

    async def list_campaigns(
        self, workspace_id: str | None = None, *, latest_only: bool = True
    ) -> list[CampaignDefinition]:
        rows = [c for versions in self._campaigns.values() for c in versions]
        if workspace_id is not None:
            rows = [c for c in rows if c.workspace_id == workspace_id]
        if not latest_only:
            return sorted(rows, key=lambda c: (c.campaign_id, c.policy_version))
        latest: dict[str, CampaignDefinition] = {}
        for campaign in rows:
            current = latest.get(campaign.campaign_id)
            if current is None or campaign.policy_version > current.policy_version:
                latest[campaign.campaign_id] = campaign
        return sorted(latest.values(), key=lambda c: (c.campaign_id, c.policy_version))

    async def update_policy(
        self, campaign_id: str, policy: CampaignPolicy, *, actor: Actor
    ) -> CampaignDefinition:
        campaign = await self.require_campaign(campaign_id)
        updated = campaign.model_copy(
            update={
                "policy": policy,
                "policy_version": campaign.policy_version + 1,
                "superseded_version": campaign.policy_version,
            }
        )
        self._campaigns[campaign_id].append(updated)
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.POLICY_UPDATED,
                policy_version=updated.policy_version,
                campaign_id=campaign_id,
                payload={"superseded_version": updated.superseded_version},
            )
        )
        return updated

    async def set_control(
        self,
        campaign_id: str,
        kind: ControlKind,
        *,
        actor: Actor,
        item_id: str | None = None,
        set_at: datetime | None = None,
    ) -> ControlRecord:
        campaign = await self.require_campaign(campaign_id)
        control_fields: dict[str, object] = {
            "campaign_id": campaign_id,
            "kind": kind,
            "item_id": item_id,
            "set_by": actor,
            "policy_version": campaign.policy_version,
        }
        if set_at is not None:
            control_fields["set_at"] = set_at
        control = ControlRecord.model_validate(control_fields)
        self._controls[control.control_id] = control
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.CONTROL_SET,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                item_id=item_id,
                payload={"kind": kind.value, "control_id": control.control_id},
            )
        )
        return control

    async def clear_control(self, control_id: str, *, actor: Actor) -> ControlRecord:
        control = self._controls.get(control_id)
        if control is None:
            raise ControlNotFound(control_id)
        if not control.active:
            return control
        cleared = control.model_copy(update={"cleared_at": datetime.now(UTC), "cleared_by": actor})
        self._controls[control_id] = cleared
        campaign = await self.get_campaign(control.campaign_id)
        payload: dict[str, object] = {"kind": control.kind.value, "control_id": control_id}
        if control.kind is ControlKind.HUMAN_ONLY and campaign is not None:
            # Clearing returns the item to the mode it had before, recorded
            # on the clear decision itself.
            record = self._item_records.get((control.campaign_id, control.item_id or ""))
            override = record.mode_override if record is not None else None
            if record is None or override is AutonomyMode.HUMAN_ONLY:
                restored: str | None = campaign.policy.default_autonomy_mode.value
            elif override is not None:
                restored = override.value
            else:
                restored = campaign.policy.default_autonomy_mode.value
            payload["restored_mode"] = restored
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.CONTROL_CLEARED,
                policy_version=campaign.policy_version if campaign else control.policy_version,
                campaign_id=control.campaign_id,
                item_id=control.item_id,
                payload=payload,
            )
        )
        return cleared

    async def list_controls(
        self, campaign_id: str, *, active_only: bool = False
    ) -> list[ControlRecord]:
        rows = [c for c in self._controls.values() if c.campaign_id == campaign_id]
        if active_only:
            rows = [c for c in rows if c.active]
        return sorted(rows, key=lambda c: (c.set_at, c.control_id))

    async def get_control(self, control_id: str) -> ControlRecord | None:
        return self._controls.get(control_id)

    async def set_item_record(
        self,
        campaign_id: str,
        item_id: str,
        *,
        actor: Actor,
        mode_override: AutonomyMode | None = None,
        human_priority: float | None = None,
    ) -> ItemPolicyRecord:
        campaign = await self.require_campaign(campaign_id)
        record = ItemPolicyRecord(
            campaign_id=campaign_id,
            item_id=item_id,
            mode_override=mode_override,
            human_priority=human_priority,
            updated_by=actor,
            policy_version=campaign.policy_version,
        )
        self._item_records[(campaign_id, item_id)] = record
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.ITEM_RECORD_SET,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                item_id=item_id,
                payload={
                    "mode_override": record.mode_override.value if record.mode_override else None,
                    "human_priority": record.human_priority,
                },
            )
        )
        return record

    async def list_item_records(self, campaign_id: str) -> list[ItemPolicyRecord]:
        return [
            record for (cid, _), record in sorted(self._item_records.items()) if cid == campaign_id
        ]

    async def park_item(
        self,
        campaign_id: str,
        item_id: str,
        evidence: ParkEvidence,
        *,
        actor: Actor,
    ) -> ParkRecord:
        campaign = await self.require_campaign(campaign_id)
        park = ParkRecord(
            campaign_id=campaign_id,
            item_id=item_id,
            evidence=evidence,
            parked_by=actor,
            policy_version=campaign.policy_version,
        )
        self._parks[park.park_id] = park
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.ITEM_PARKED,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                item_id=item_id,
                payload={
                    "park_id": park.park_id,
                    "reason": evidence.reason,
                    "blocking_dependency": evidence.blocking_dependency,
                    "failing_check": evidence.failing_check,
                    "run_reference": evidence.run_reference,
                    "artifact_references": list(evidence.artifact_references),
                },
            )
        )
        return park

    async def unpark_item(self, park_id: str, *, actor: Actor) -> ParkRecord:
        park = self._parks.get(park_id)
        if park is None:
            raise ParkNotFound(park_id)
        if not park.active:
            return park
        campaign = await self.get_campaign(park.campaign_id)
        policy_version = campaign.policy_version if campaign else park.policy_version
        unparked = park.model_copy(
            update={"unparked": ParkUnpark(unparked_by=actor, policy_version=policy_version)}
        )
        self._parks[park_id] = unparked
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.ITEM_UNPARKED,
                policy_version=policy_version,
                campaign_id=park.campaign_id,
                item_id=park.item_id,
                payload={"park_id": park_id},
            )
        )
        return unparked

    async def get_park(self, park_id: str) -> ParkRecord | None:
        return self._parks.get(park_id)

    async def list_parks(self, campaign_id: str, *, active_only: bool = False) -> list[ParkRecord]:
        rows = [p for p in self._parks.values() if p.campaign_id == campaign_id]
        if active_only:
            rows = [p for p in rows if p.active]
        return sorted(rows, key=lambda p: (p.parked_at, p.park_id))

    async def record_usage(
        self,
        campaign_id: str,
        *,
        actor: Actor,
        cost_usd: float = 0.0,
        minutes: float = 0.0,
        completions: int = 0,
    ) -> BudgetUsage:
        campaign = await self.require_campaign(campaign_id)
        previous = self._usage.get(campaign_id, BudgetUsage())
        updated = BudgetUsage(
            cost_usd=previous.cost_usd + cost_usd,
            minutes=previous.minutes + minutes,
            completions=previous.completions + completions,
        )
        self._usage[campaign_id] = updated
        await self.append_audit(
            CampaignAuditRecord(
                actor=actor,
                kind=AuditKind.USAGE_RECORDED,
                policy_version=campaign.policy_version,
                campaign_id=campaign_id,
                payload={"cost_usd": cost_usd, "minutes": minutes, "completions": completions},
            )
        )
        return updated

    async def get_usage(self, campaign_id: str) -> BudgetUsage:
        return self._usage.get(campaign_id, BudgetUsage())

    async def append_audit(self, *records: CampaignAuditRecord) -> None:
        for offset, record in enumerate(records):
            self._audit.append(record.model_copy(update={"seq": len(self._audit) + 1 + offset}))

    async def audit_trail(
        self, campaign_id: str | None = None, *, limit: int | None = None
    ) -> list[CampaignAuditRecord]:
        rows = [r for r in self._audit if campaign_id is None or r.campaign_id == campaign_id]
        if limit is not None:
            rows = rows[-limit:]
        return list(rows)


class CampaignSelector:
    """The entrypoint an authorized actor consumes (#804 now, #50 later).

    It composes the pure policy with a store: evaluate eligibility, order the
    pool, record both inputs, and append the audit trail. It never executes
    the selected work and never touches a Goal — claiming is recorded as a
    decision, and the Goal's owner stays wherever the Goal owner put it
    (invariant 2).
    """

    def __init__(self, store: CampaignStore, goal_reader: GoalReader | None = None) -> None:
        self._store = store
        self._goal_reader = goal_reader

    async def eligible_items(
        self,
        *,
        actor: Actor,
        items: Sequence[BacklogItemView],
        can_actor_access: Callable[[BacklogItemView], bool],
        campaign_ids: Sequence[str] | None = None,
    ) -> list[tuple[BacklogItemView, EligibilityDecision]]:
        campaigns = await self._campaigns_for(campaign_ids)
        decisions = await self._evaluate(actor, items, campaigns, can_actor_access)
        await self._store.append_audit(*audit_eligibility(actor=actor, decisions=decisions))
        by_id = {item.item_id: item for item in items}
        return [(by_id[d.item_id], d) for d in decisions]

    async def select_next(
        self,
        *,
        actor: Actor,
        items: Sequence[BacklogItemView],
        can_actor_access: Callable[[BacklogItemView], bool],
        signals: Mapping[str, SelectionSignals] | None = None,
        limit: int = 1,
        campaign_ids: Sequence[str] | None = None,
    ) -> list[RankedCandidate]:
        """Order the eligible pool and return the top ``limit`` candidates.

        Selection records the decision — it does not run anything."""
        campaigns = await self._campaigns_for(campaign_ids)
        decisions = await self._evaluate(actor, items, campaigns, can_actor_access)
        await self._store.append_audit(*audit_eligibility(actor=actor, decisions=decisions))
        ranked = order_candidates(
            actor=actor,
            eligible=decisions,
            items={item.item_id: item for item in items},
            item_records=await self._item_records_for(campaigns),
            controls=await self._controls_for(campaigns),
            signals=signals or {},
        )
        versions = [(c.campaign_id, c.policy_version) for c in campaigns]
        await self._store.append_audit(
            *audit_selection(actor=actor, candidates=ranked[:limit], campaign_versions=versions)
        )
        return ranked[:limit]

    async def claim(self, *, actor: Actor, item: BacklogItemView) -> CampaignAuditRecord:
        """Record that ``actor`` claimed ``item``.

        A claim is a decision record and nothing else: no permission is
        granted, no Goal field is written, and the linked Goal's owning Agent
        is untouched (invariants 1 and 2). The read-only goal reference in
        the payload is the item's own linkage, unchanged."""
        campaigns = applicable_campaigns(item, await self._store.list_campaigns())
        primary = campaigns[0] if campaigns else None
        record = CampaignAuditRecord(
            actor=actor,
            kind=AuditKind.ITEM_CLAIMED,
            policy_version=primary.policy_version if primary else 0,
            campaign_id=primary.campaign_id if primary else None,
            item_id=item.item_id,
            payload={
                "goal_id": item.goal_id,
                "goal_revision": item.goal_revision,
                "goal_owner_written": False,
            },
        )
        await self._store.append_audit(record)
        return record

    async def _evaluate(
        self,
        actor: Actor,
        items: Sequence[BacklogItemView],
        campaigns: Sequence[CampaignDefinition],
        can_actor_access: Callable[[BacklogItemView], bool],
    ) -> list[EligibilityDecision]:
        return await evaluate_items(
            actor=actor,
            items=items,
            campaigns=campaigns,
            item_records=await self._item_records_for(campaigns),
            controls=await self._controls_for(campaigns),
            parks=await self._parks_for(campaigns),
            usage=await self._usage_for(campaigns),
            can_actor_access=can_actor_access,
            goal_reader=self._goal_reader,
        )

    async def _campaigns_for(self, campaign_ids: Sequence[str] | None) -> list[CampaignDefinition]:
        if campaign_ids is None:
            return await self._store.list_campaigns()
        return [
            campaign
            for campaign_id in campaign_ids
            if (campaign := await self._store.get_campaign(campaign_id)) is not None
        ]

    async def _item_records_for(
        self, campaigns: Sequence[CampaignDefinition]
    ) -> dict[str, ItemPolicyRecord]:
        records: dict[str, ItemPolicyRecord] = {}
        for campaign in campaigns:
            for record in await self._store.list_item_records(campaign.campaign_id):
                records.setdefault(record.item_id, record)
        return records

    async def _controls_for(self, campaigns: Sequence[CampaignDefinition]) -> list[ControlRecord]:
        controls: list[ControlRecord] = []
        for campaign in campaigns:
            controls.extend(await self._store.list_controls(campaign.campaign_id))
        return controls

    async def _parks_for(self, campaigns: Sequence[CampaignDefinition]) -> list[ParkRecord]:
        parks: list[ParkRecord] = []
        for campaign in campaigns:
            parks.extend(await self._store.list_parks(campaign.campaign_id))
        return parks

    async def _usage_for(self, campaigns: Sequence[CampaignDefinition]) -> BudgetUsage:
        total = BudgetUsage()
        for campaign in campaigns:
            usage = await self._store.get_usage(campaign.campaign_id)
            total = BudgetUsage(
                cost_usd=total.cost_usd + usage.cost_usd,
                minutes=total.minutes + usage.minutes,
                completions=total.completions + usage.completions,
            )
        return total
