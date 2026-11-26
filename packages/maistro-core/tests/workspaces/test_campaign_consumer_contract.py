"""One campaign contract for every consumer (SPEC-092626-1831/AC-9).

The persistent Workspace Agent (#804) consumes this contract now and RSI
(#50) reuses it later — so the contract must be importable as a shared
library surface and must not grow an edge to any RSI-private campaign model.
`maistro_rsi.trace_notes.read_campaign` stays a trace reconstructor; nothing
in this package imports it or anything else from `maistro_rsi`.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from maistro.workspaces.campaigns import (
    Actor,
    ActorKind,
    AutonomyMode,
    BacklogItemView,
    CampaignSelector,
    ControlKind,
    InMemoryCampaignStore,
    SelectionSignals,
)

CAMPAIGNS_PACKAGE = Path(
    importlib.import_module("maistro.workspaces.campaigns").__file__ or "."
).parent

OPERATOR = Actor(kind=ActorKind.USER, id="operator")


def _agent() -> Actor:
    return Actor(kind=ActorKind.AGENT, id="persistent-workspace-agent")


@pytest.mark.ac("SPEC-092626-1831/AC-9")
async def test_a_consumer_selects_work_through_the_shared_contract() -> None:
    """The way #804 consumes it: build a selector over a store, hand it the
    authorized pool, and get an ordered, mode-annotated selection back."""
    store = InMemoryCampaignStore()
    campaign = await store.create_campaign(
        workspace_id="w1",
        name="maintenance",
        actor=OPERATOR,
    )
    await store.set_control(
        campaign.campaign_id,
        ControlKind.PIN_NEXT,
        actor=OPERATOR,
        item_id="dep-upgrade",
    )
    selector = CampaignSelector(store)
    ranked = await selector.select_next(
        actor=_agent(),
        items=[
            BacklogItemView.model_validate({"item_id": "dep-upgrade", "workspace_id": "w1"}),
            BacklogItemView.model_validate({"item_id": "doc-sweep", "workspace_id": "w1"}),
        ],
        can_actor_access=lambda item: True,
        signals={"doc-sweep": SelectionSignals(verification_confidence=0.9)},
        limit=10,
    )
    assert [c.item_id for c in ranked] == ["dep-upgrade", "doc-sweep"]
    assert ranked[0].effective_mode is AutonomyMode.AUTONOMOUS


@pytest.mark.ac("SPEC-092626-1831/AC-9")
def test_the_contract_has_no_edge_to_an_rsi_private_campaign_model() -> None:
    """No module under `maistro.workspaces.campaigns` imports `maistro_rsi`:
    RSI consumes this contract, it is never a dependency of it."""
    sources = CAMPAIGNS_PACKAGE.rglob("*.py")
    offenders = [str(path) for path in sources if "maistro_rsi" in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_rsi_keeps_its_trace_reconstructor_and_gains_no_policy_model() -> None:
    """`read_campaign` still exists where #50 says it must stay (a trace
    reconstructor), and the RSI package defines no campaign policy type that
    could compete with this contract."""
    trace_notes = importlib.import_module("maistro_rsi.trace_notes")
    assert callable(trace_notes.read_campaign)

    rsi_source_root = Path(importlib.import_module("maistro_rsi").__file__ or ".").parent
    campaign_policy_definitions = [
        str(path)
        for path in rsi_source_root.rglob("*.py")
        if "class CampaignPolicy" in path.read_text(encoding="utf-8")
        or "class CampaignDefinition" in path.read_text(encoding="utf-8")
    ]
    assert campaign_policy_definitions == []
