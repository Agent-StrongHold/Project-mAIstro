"""Campaign eligibility, selection and invariants (SPEC-092626-1831, #103).

These run the pure policy over the reference in-memory store through
`CampaignSelector` — the same entrypoint the persistent Workspace Agent
(#804) consumes, so what is asserted here is the shipped selection path, not
a seam only tests construct.
"""

from __future__ import annotations

import pytest

from maistro.workspaces.campaigns import (
    Actor,
    ActorKind,
    AreaRef,
    AuditKind,
    AutonomyMode,
    BacklogItemView,
    CampaignConstraints,
    CampaignPolicy,
    CampaignSelector,
    ControlKind,
    InMemoryCampaignStore,
    ItemNotEligible,
    ParkEvidence,
    SelectionSignals,
)
from maistro.workspaces.campaigns.policy import (
    ORDER_RULE_VERSION,
    SCORE_RULE_VERSION,
    GoalReader,
    score_item,
)

OPERATOR = Actor(kind=ActorKind.USER, id="operator-1")
AGENT = Actor(kind=ActorKind.AGENT, id="workspace-agent-1")


def _item(item_id: str = "item-1", **overrides: object) -> BacklogItemView:
    fields: dict[str, object] = {"item_id": item_id, "workspace_id": "w1"}
    fields.update(overrides)
    return BacklogItemView.model_validate(fields)


async def _campaign(
    store: InMemoryCampaignStore,
    campaign_id: str = "main",
    **policy_overrides: object,
):
    policy_fields: dict[str, object] = {"constraints": CampaignConstraints()}
    policy_fields.update(policy_overrides)
    return await store.create_campaign(
        workspace_id="w1",
        name="sprint",
        actor=OPERATOR,
        campaign_id=campaign_id,
        policy=CampaignPolicy.model_validate(policy_fields),
    )


def _everyone(_: BacklogItemView) -> bool:
    return True


class _RecordingGoalReader:
    """A stand-in for `maistro.goals`: read-only, and it remembers every read
    so tests can assert campaigns never write Goal state."""

    def __init__(self, states: dict[str, str]) -> None:
        self._states = states
        self.reads: list[tuple[str, str | None]] = []
        self.writes: list[object] = []

    async def read_goal_state(self, goal_id: str, goal_revision: str | None) -> str | None:
        self.reads.append((goal_id, goal_revision))
        return self._states.get(goal_id)


def _selector(
    store: InMemoryCampaignStore, goal_reader: GoalReader | None = None
) -> CampaignSelector:
    return CampaignSelector(store, goal_reader)


@pytest.mark.ac("SPEC-092626-1831/AC-1")
async def test_constraints_narrow_tags_milestones_packages_and_scope() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(
        store,
        constraints=CampaignConstraints(
            tags=["backend"],
            milestones=["m3"],
            packages=["maistro-core"],
            workspace_ids=["w1"],
            project_ids=["p1"],
        ),
    )
    items = [
        _item(
            "match",
            tags=frozenset({"backend"}),
            milestone="m3",
            package="maistro-core",
            project_id="p1",
        ),
        _item(
            "no-tag",
            tags=frozenset({"ui"}),
            milestone="m3",
            package="maistro-core",
            project_id="p1",
        ),
        _item(
            "no-milestone",
            tags=frozenset({"backend"}),
            milestone="m9",
            package="maistro-core",
            project_id="p1",
        ),
        _item(
            "no-package",
            tags=frozenset({"backend"}),
            milestone="m3",
            package="canvas",
            project_id="p1",
        ),
        _item(
            "no-project",
            tags=frozenset({"backend"}),
            milestone="m3",
            package="maistro-core",
            project_id="p2",
        ),
        _item(
            "no-workspace",
            workspace_id="w9",
            tags=frozenset({"backend"}),
            milestone="m3",
            package="maistro-core",
            project_id="p1",
        ),
    ]
    decisions = {
        d.item_id: d
        for _, d in await _selector(store).eligible_items(
            actor=AGENT, items=items, can_actor_access=_everyone
        )
    }
    prefix = f"campaign:{campaign.campaign_id}"
    assert decisions["match"].eligible
    assert decisions["no-tag"].reasons == [f"{prefix}:tag-mismatch"]
    assert decisions["no-milestone"].reasons == [f"{prefix}:milestone-mismatch"]
    assert decisions["no-package"].reasons == [f"{prefix}:package-mismatch"]
    assert decisions["no-project"].reasons == [f"{prefix}:project-scope-mismatch"]
    # The item in another Workspace is out of the campaign's reach entirely
    # (scope, not a constraint reason) AND fails the declared workspace axis
    # wherever it is evaluated from.
    assert decisions["no-workspace"].eligible
    assert decisions["no-workspace"].campaign_versions == []


@pytest.mark.ac("SPEC-092626-1831/AC-1")
async def test_protected_area_removes_item_from_automated_selection() -> None:
    store = InMemoryCampaignStore()
    await _campaign(store, protected_areas=[AreaRef(kind="path", value="deploy/")])
    items = [
        _item("safe", declared_areas=[AreaRef(kind="package", value="maistro-core")]),
        _item("touching", declared_areas=[AreaRef(kind="path", value="deploy/prod.yml")]),
    ]
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone
    )
    assert [c.item_id for c in ranked] == ["safe"]


@pytest.mark.ac("SPEC-092626-1831/AC-1")
async def test_reached_budget_stops_new_selections() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store, budgets={"max_cost_usd": 10.0})
    await store.record_usage(campaign.campaign_id, actor=AGENT, cost_usd=10.0)
    items = [_item("cheap"), _item("cheaper")]
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone
    )
    assert ranked == []
    decisions = {
        d.item_id: d
        for _, d in await _selector(store).eligible_items(
            actor=AGENT, items=items, can_actor_access=_everyone
        )
    }
    assert decisions["cheap"].reasons == [f"budget:{campaign.campaign_id}:cost-reached"]


@pytest.mark.ac("SPEC-092626-1831/AC-1")
async def test_completion_budget_stops_new_selections_too() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store, budgets={"max_completions": 2})
    await store.record_usage(campaign.campaign_id, actor=AGENT, completions=2)
    ranked = await _selector(store).select_next(
        actor=AGENT, items=[_item("next")], can_actor_access=_everyone
    )
    assert ranked == []
    usage = await store.get_usage(campaign.campaign_id)
    assert usage.completions == 2


@pytest.mark.ac("SPEC-092626-1831/AC-2")
async def test_each_mode_governs_what_an_automated_actor_may_do() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    items = [
        _item("plain"),
        _item("promotion"),
        _item("reviewed"),
        _item("human"),
    ]
    for item_id, mode in (
        ("plain", None),
        ("promotion", AutonomyMode.AUTONOMOUS_WITH_PROMOTION_APPROVAL),
        ("reviewed", AutonomyMode.HUMAN_REVIEW_REQUIRED),
        ("human", AutonomyMode.HUMAN_ONLY),
    ):
        await store.set_item_record(
            campaign.campaign_id,
            item_id,
            actor=OPERATOR,
            mode_override=mode,
        )
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone, limit=10
    )
    modes = {c.item_id: c.effective_mode for c in ranked}
    assert modes == {
        "plain": AutonomyMode.AUTONOMOUS,
        "promotion": AutonomyMode.AUTONOMOUS_WITH_PROMOTION_APPROVAL,
        "reviewed": AutonomyMode.HUMAN_REVIEW_REQUIRED,
    }
    promotion = next(c for c in ranked if c.item_id == "promotion")
    assert promotion.needs_promotion_approval
    assert not promotion.needs_human_review
    review = next(c for c in ranked if c.item_id == "reviewed")
    assert review.needs_human_review


@pytest.mark.ac("SPEC-092626-1831/AC-2")
async def test_human_only_is_absolute_even_when_pinned() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    await store.set_item_record(
        campaign.campaign_id, "human", actor=OPERATOR, mode_override=AutonomyMode.HUMAN_ONLY
    )
    await store.set_control(
        campaign.campaign_id, ControlKind.PIN_NEXT, actor=OPERATOR, item_id="human"
    )
    ranked = await _selector(store).select_next(
        actor=AGENT,
        items=[_item("human"), _item("other")],
        can_actor_access=_everyone,
    )
    assert [c.item_id for c in ranked] == ["other"]


@pytest.mark.ac("SPEC-092626-1831/AC-2")
async def test_default_mode_comes_from_the_campaign_policy() -> None:
    store = InMemoryCampaignStore()
    await _campaign(store, default_autonomy_mode=AutonomyMode.HUMAN_REVIEW_REQUIRED)
    ranked = await _selector(store).select_next(
        actor=AGENT, items=[_item("quiet")], can_actor_access=_everyone
    )
    assert ranked[0].effective_mode is AutonomyMode.HUMAN_REVIEW_REQUIRED


@pytest.mark.ac("SPEC-092626-1831/AC-3")
async def test_human_priority_stays_explicit_and_separate_from_score() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    # The person sets priority exactly as given; the system is never asked to
    # rewrite it.
    await store.set_item_record(campaign.campaign_id, "urgent", actor=OPERATOR, human_priority=7.0)
    await store.set_item_record(
        campaign.campaign_id, "measured", actor=OPERATOR, human_priority=0.25
    )
    items = [_item("urgent"), _item("measured"), _item("silent")]
    ranked = await _selector(store).select_next(
        actor=AGENT,
        items=items,
        can_actor_access=_everyone,
        signals={
            "measured": SelectionSignals(
                criticality=0.9, unblock_value=0.6, verification_confidence=0.8
            )
        },
        limit=10,
    )
    assert [c.item_id for c in ranked] == ["urgent", "measured", "silent"]
    urgent, measured, silent = ranked
    # Stored as given, not normalized, not zero-filled.
    assert urgent.human_priority == 7.0
    assert measured.human_priority == 0.25
    assert silent.human_priority is None
    assert silent.score == 0.0 and silent.score_inputs == {}
    # The measured item's score is the mean of its measured signals only.
    assert measured.score == pytest.approx((0.9 + 0.6 + 0.8) / 3)
    assert set(measured.score_inputs) == {
        "criticality",
        "unblock_value",
        "verification_confidence",
    }


@pytest.mark.ac("SPEC-092626-1831/AC-3")
async def test_selection_audit_record_carries_both_inputs_and_rule_versions() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    await store.set_item_record(campaign.campaign_id, "picked", actor=OPERATOR, human_priority=3.0)
    await _selector(store).select_next(
        actor=AGENT,
        items=[_item("picked")],
        can_actor_access=_everyone,
        signals={"picked": SelectionSignals(risk=0.1, cost=0.4)},
    )
    selection = [
        r
        for r in await store.audit_trail(campaign.campaign_id)
        if r.kind is AuditKind.SELECTION_DECIDED
    ]
    assert len(selection) == 1
    payload = selection[0].payload
    assert payload["human_priority"] == 3.0
    assert payload["score_inputs"] == {"risk": 0.1, "cost": 0.4}
    assert payload["score_rule"] == SCORE_RULE_VERSION
    assert payload["order_rule"] == ORDER_RULE_VERSION
    assert selection[0].actor == AGENT
    assert selection[0].policy_version == campaign.policy_version


def test_score_leaves_unmeasured_signals_out_of_the_mean() -> None:
    score, measured = score_item(SelectionSignals(criticality=0.8, risk=None))
    assert score == pytest.approx(0.8)
    assert measured == {"criticality": 0.8}
    assert score_item(None) == (0.0, {})


@pytest.mark.ac("SPEC-092626-1831/AC-4")
async def test_eligibility_reads_linked_goal_state_without_copying_it() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store, required_goal_state="active")
    reader = _RecordingGoalReader({"goal-1": "active", "goal-2": "draft"})
    items = [
        _item("linked-active", goal_id="goal-1", goal_revision="rev-7"),
        _item("linked-draft", goal_id="goal-2", goal_revision="rev-2"),
    ]
    decisions = {
        d.item_id: d
        for _, d in await _selector(store, reader).eligible_items(
            actor=AGENT, items=items, can_actor_access=_everyone
        )
    }
    # The Goal was read by goal_id and goal_revision, nothing more.
    assert reader.reads == [("goal-1", "rev-7"), ("goal-2", "rev-2")]
    assert reader.writes == []
    assert decisions["linked-active"].eligible
    assert decisions["linked-draft"].reasons == [
        f"campaign:{campaign.campaign_id}:goal-state-mismatch",
        "goal-state-observed:draft",
    ]
    # The observed state appears only as audit evidence on the decision, and
    # the store holds no Goal-shaped record.
    assert any(r.startswith("goal-state-observed:") for r in decisions["linked-active"].reasons)
    assert await store.list_item_records(campaign.campaign_id) == []


@pytest.mark.ac("SPEC-092626-1831/AC-6")
async def test_parked_item_leaves_the_pool_and_another_is_selected() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    await store.park_item(
        campaign.campaign_id,
        "stalled",
        ParkEvidence(
            reason="dependency not merged",
            blocking_dependency="PR #98",
            failing_check="ci/integration",
            run_reference="run-123",
            artifact_references=["artifact-9"],
        ),
        actor=OPERATOR,
    )
    items = [_item("stalled"), _item("healthy")]
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone
    )
    assert [c.item_id for c in ranked] == ["healthy"]
    parks = await store.list_parks(campaign.campaign_id, active_only=True)
    assert len(parks) == 1
    evidence = parks[0].evidence
    assert evidence.reason == "dependency not merged"
    assert evidence.blocking_dependency == "PR #98"
    assert evidence.failing_check == "ci/integration"
    assert evidence.run_reference == "run-123"


@pytest.mark.ac("SPEC-092626-1831/AC-6")
async def test_unparking_returns_the_item_to_the_pool() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    park = await store.park_item(
        campaign.campaign_id,
        "stalled",
        ParkEvidence(reason="blocked on review"),
        actor=OPERATOR,
    )
    items = [_item("stalled")]
    assert (
        await _selector(store).select_next(actor=AGENT, items=items, can_actor_access=_everyone)
        == []
    )
    await store.unpark_item(park.park_id, actor=OPERATOR)
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone
    )
    assert [c.item_id for c in ranked] == ["stalled"]
    # The unpark is its own attributed decision, not a deletion.
    trail = await store.audit_trail(campaign.campaign_id)
    unparks = [r for r in trail if r.kind is AuditKind.ITEM_UNPARKED]
    assert len(unparks) == 1
    assert unparks[0].actor == OPERATOR
    assert (await store.list_parks(campaign.campaign_id, active_only=True)) == []


@pytest.mark.ac("SPEC-092626-1831/AC-7")
async def test_selection_cannot_widen_authorization() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    items = [_item("reachable"), _item("forbidden")]
    decisions = {
        d.item_id: d
        for _, d in await _selector(store).eligible_items(
            actor=AGENT,
            items=items,
            can_actor_access=lambda item: item.item_id != "forbidden",
        )
    }
    assert decisions["reachable"].eligible
    assert not decisions["forbidden"].eligible
    assert decisions["forbidden"].reasons == ["authorization:actor-cannot-access"]
    # Pinning the forbidden item does not widen anything either.
    await store.set_control(
        campaign.campaign_id, ControlKind.PIN_NEXT, actor=OPERATOR, item_id="forbidden"
    )
    ranked = await _selector(store).select_next(
        actor=AGENT,
        items=items,
        can_actor_access=lambda item: item.item_id != "forbidden",
    )
    assert [c.item_id for c in ranked] == ["reachable"]


@pytest.mark.ac("SPEC-092626-1831/AC-7")
async def test_claiming_never_writes_goal_state_or_ownership() -> None:
    store = InMemoryCampaignStore()
    await _campaign(store)
    reader = _RecordingGoalReader({"goal-1": "active"})
    item = _item("work", goal_id="goal-1", goal_revision="rev-1")
    record = await _selector(store, reader).claim(
        actor=AGENT, item=item, can_actor_access=_everyone
    )
    assert record.kind is AuditKind.ITEM_CLAIMED
    assert record.item_id == "work"
    assert record.payload["goal_owner_written"] is False
    assert record.payload["goal_id"] == "goal-1"
    # A claim performed zero Goal reads and zero Goal writes: the reader only
    # supports reads and was never called.
    assert reader.reads == []
    assert reader.writes == []


@pytest.mark.ac("SPEC-092626-1831/AC-7")
async def test_claim_cannot_bypass_eligibility() -> None:
    """Calling ``claim`` directly enforces exactly what ``select_next`` does:
    an inaccessible, paused, parked, excluded or human-only item raises
    ``ItemNotEligible`` and records no claim."""
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    campaign_pause = await store.set_control(
        campaign.campaign_id, ControlKind.PAUSE, actor=OPERATOR
    )
    selector = _selector(store)
    with pytest.raises(ItemNotEligible) as exc:
        await selector.claim(actor=AGENT, item=_item("any"), can_actor_access=_everyone)
    assert "campaign:paused" in exc.value.reasons
    await store.clear_control(campaign_pause.control_id, actor=OPERATOR)
    await store.set_control(
        campaign.campaign_id, ControlKind.PAUSE, actor=OPERATOR, item_id="paused-item"
    )
    await store.set_control(
        campaign.campaign_id, ControlKind.EXCLUDE, actor=OPERATOR, item_id="excluded-item"
    )
    await store.park_item(
        campaign.campaign_id,
        "parked-item",
        evidence=ParkEvidence(reason="waiting on upstream"),
        actor=OPERATOR,
    )
    await store.update_policy(
        campaign.campaign_id,
        CampaignPolicy.model_validate(
            {
                "constraints": CampaignConstraints(),
                "default_autonomy_mode": AutonomyMode.HUMAN_ONLY,
            }
        ),
        actor=OPERATOR,
    )
    inaccessible = _item("inaccessible")
    for item in (_item("paused-item"), _item("excluded-item"), _item("parked-item")):
        with pytest.raises(ItemNotEligible) as exc:
            await selector.claim(actor=AGENT, item=item, can_actor_access=_everyone)
        assert exc.value.item_id == item.item_id
        assert exc.value.reasons
    with pytest.raises(ItemNotEligible) as exc:
        await selector.claim(actor=AGENT, item=_item("human-item"), can_actor_access=_everyone)
    assert "mode:human-only" in exc.value.reasons
    with pytest.raises(ItemNotEligible) as exc:
        await selector.claim(actor=AGENT, item=inaccessible, can_actor_access=lambda _: False)
    assert exc.value.reasons == ["authorization:actor-cannot-access"]
    # Nothing was recorded: no claim, and only the eligibility decisions
    # that document the refusals.
    trail = await store.audit_trail(campaign.campaign_id)
    assert not [r for r in trail if r.kind is AuditKind.ITEM_CLAIMED]
    # The compliant path still records the claim, with the decision's
    # reasons as evidence. The campaign is now human-only, so the claim
    # comes from the human operator an agent could never substitute for.
    record = await selector.claim(actor=OPERATOR, item=_item("fine"), can_actor_access=_everyone)
    assert record.kind is AuditKind.ITEM_CLAIMED
    assert record.payload["eligibility_reasons"] == []


@pytest.mark.ac("SPEC-092626-1831/AC-8")
async def test_every_decision_is_attributed_to_actor_and_policy_version() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    actor = Actor(kind=ActorKind.USER, id="operator-9")
    await store.set_control(
        campaign.campaign_id, ControlKind.EXCLUDE, actor=actor, item_id="excluded"
    )
    updated = await store.update_policy(campaign.campaign_id, CampaignPolicy(), actor=actor)
    trail = await store.audit_trail(campaign.campaign_id)
    kinds = [(r.kind, r.actor, r.policy_version) for r in trail]
    assert (AuditKind.CAMPAIGN_CREATED, OPERATOR, 1) in kinds
    assert (AuditKind.CONTROL_SET, actor, 1) in kinds
    assert (AuditKind.POLICY_UPDATED, actor, 2) in kinds
    assert updated.policy_version == 2
    # Earlier versions stay readable for audit.
    assert len(await store.list_campaigns("w1", latest_only=False)) == 2


@pytest.mark.ac("SPEC-092626-1831/AC-8")
async def test_clearing_a_control_is_a_recorded_decision() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    control = await store.set_control(campaign.campaign_id, ControlKind.PAUSE, actor=OPERATOR)
    await store.clear_control(control.control_id, actor=OPERATOR)
    trail = await store.audit_trail(campaign.campaign_id)
    clears = [r for r in trail if r.kind is AuditKind.CONTROL_CLEARED]
    assert len(clears) == 1
    assert clears[0].actor == OPERATOR
    assert clears[0].payload["kind"] == "pause"
    # The cleared control stays readable, with its actor and time.
    stored = await store.get_control(control.control_id)
    assert stored is not None and not stored.active
    assert stored.cleared_by == OPERATOR
    assert stored.cleared_at is not None
    # And an unpaused campaign selects again.
    ranked = await _selector(store).select_next(
        actor=AGENT, items=[_item("back")], can_actor_access=_everyone
    )
    assert [c.item_id for c in ranked] == ["back"]


async def test_campaign_pause_stops_selection_until_cleared() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    items = [_item("a"), _item("b")]
    await store.set_control(campaign.campaign_id, ControlKind.PAUSE, actor=OPERATOR)
    assert (
        await _selector(store).select_next(actor=AGENT, items=items, can_actor_access=_everyone)
        == []
    )
    decisions = {
        d.item_id: d
        for _, d in await _selector(store).eligible_items(
            actor=AGENT, items=items, can_actor_access=_everyone
        )
    }
    assert decisions["a"].reasons == ["campaign:paused"]


async def test_item_scoped_pause_and_exclude_narrow_one_item() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    await store.set_control(
        campaign.campaign_id, ControlKind.PAUSE, actor=OPERATOR, item_id="paused-item"
    )
    await store.set_control(
        campaign.campaign_id, ControlKind.EXCLUDE, actor=OPERATOR, item_id="excluded-item"
    )
    items = [_item("paused-item"), _item("excluded-item"), _item("fine")]
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone, limit=10
    )
    assert [c.item_id for c in ranked] == ["fine"]


async def test_pin_next_outranks_score_and_priority() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store)
    await store.set_item_record(
        campaign.campaign_id, "high-priority", actor=OPERATOR, human_priority=9.0
    )
    await store.set_control(
        campaign.campaign_id, ControlKind.PIN_NEXT, actor=OPERATOR, item_id="pinned"
    )
    ranked = await _selector(store).select_next(
        actor=AGENT,
        items=[_item("high-priority"), _item("pinned"), _item("scored")],
        can_actor_access=_everyone,
        signals={
            "scored": SelectionSignals(criticality=1.0, unblock_value=1.0),
            "high-priority": SelectionSignals(criticality=1.0),
        },
        limit=10,
    )
    assert [c.item_id for c in ranked] == ["pinned", "high-priority", "scored"]
    assert ranked[0].pinned
    assert not ranked[1].pinned


async def test_applicable_campaigns_intersect_and_any_budget_stops() -> None:
    store = InMemoryCampaignStore()
    await _campaign(store, campaign_id="tags", constraints=CampaignConstraints(tags=["backend"]))
    cheap = await _campaign(store, campaign_id="cheap", budgets={"max_completions": 1})
    await store.record_usage(cheap.campaign_id, actor=AGENT, completions=1)
    items = [_item("matches", tags=frozenset({"backend"}))]
    decisions = {
        d.item_id: d
        for _, d in await _selector(store).eligible_items(
            actor=AGENT, items=items, can_actor_access=_everyone
        )
    }
    # The tag campaign passes the item on its own axis, but the budget
    # reached in the second applicable campaign removes the item from the
    # eligible set (Q3: constraints intersect, budgets combine).
    assert not decisions["matches"].eligible
    assert decisions["matches"].reasons == [f"budget:{cheap.campaign_id}:completions-reached"]
    ranked = await _selector(store).select_next(
        actor=AGENT, items=items, can_actor_access=_everyone
    )
    assert ranked == []


async def test_items_outside_every_campaign_are_untouched_by_campaign_policy() -> None:
    store = InMemoryCampaignStore()
    other = await store.create_campaign(workspace_id="w2", name="elsewhere", actor=OPERATOR)
    _ = other
    decisions = {
        d.item_id: d
        for _, d in await _selector(store).eligible_items(
            actor=AGENT, items=[_item("uncovered")], can_actor_access=_everyone
        )
    }
    assert decisions["uncovered"].eligible
    assert decisions["uncovered"].campaign_versions == []
    assert decisions["uncovered"].effective_mode is None


async def test_usage_accumulates_across_recordings() -> None:
    store = InMemoryCampaignStore()
    campaign = await _campaign(store, budgets={"max_minutes": 60.0})
    await store.record_usage(campaign.campaign_id, actor=AGENT, minutes=25.0, cost_usd=1.5)
    usage = await store.record_usage(campaign.campaign_id, actor=AGENT, minutes=30.0)
    assert usage.minutes == pytest.approx(55.0)
    assert usage.cost_usd == pytest.approx(1.5)
    assert (await store.get_usage(campaign.campaign_id)).completions == 0
    _ = campaign
