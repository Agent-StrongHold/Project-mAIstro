"""The record guards the campaign contract stands on (SPEC-092626-1831).

Every campaign decision is attributable to an actor, and every scoped record
names what it scopes. Those are validator-enforced invariants, not
conventions: an empty identity, an empty area value, an empty park reason or
a non-pause control without an item is a malformed record, and the model
refuses it rather than letting an unattributable decision into the audit
trail. These tests pin the refusals so the guards cannot quietly become
defaults.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.workspaces.campaigns.model import (
    Actor,
    AreaRef,
    BacklogItemView,
    CampaignDefinition,
    ControlKind,
    ControlRecord,
    ParkEvidence,
)

OPERATOR = Actor(id="operator-1")


def test_an_actor_requires_a_non_empty_identity() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        Actor(id="   ")
    assert Actor(id="operator-1").id == "operator-1"


def test_an_area_requires_a_non_empty_value() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        AreaRef(kind="path", value="")
    assert AreaRef(kind="package", value="maistro-core").value == "maistro-core"


def test_a_campaign_requires_a_non_empty_workspace_and_name() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        CampaignDefinition(workspace_id="  ", name="sprint", created_by=OPERATOR)
    with pytest.raises(ValidationError, match="non-empty"):
        CampaignDefinition(workspace_id="w1", name="", created_by=OPERATOR)
    campaign = CampaignDefinition(workspace_id="w1", name="sprint", created_by=OPERATOR)
    assert campaign.name == "sprint"


def test_only_a_pause_may_be_campaign_wide() -> None:
    """A campaign-wide pause is the one control that scopes nothing; every
    other kind names the item it steers, so the record cannot silently mean
    "this whole campaign" (AC-5)."""
    for kind in (ControlKind.PIN_NEXT, ControlKind.EXCLUDE, ControlKind.HUMAN_ONLY):
        with pytest.raises(ValidationError, match="item_id"):
            ControlRecord(
                campaign_id="c1",
                kind=kind,
                item_id=None,
                set_by=OPERATOR,
                policy_version=1,
            )
    campaign_wide = ControlRecord(
        campaign_id="c1",
        kind=ControlKind.PAUSE,
        item_id=None,
        set_by=OPERATOR,
        policy_version=1,
    )
    assert campaign_wide.item_id is None


def test_park_evidence_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="reason"):
        ParkEvidence(reason="   ")
    evidence = ParkEvidence(reason="waiting on upstream", failing_check="ci/lint")
    assert evidence.reason == "waiting on upstream"


def test_a_backlog_item_view_requires_identity() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        BacklogItemView(item_id="", workspace_id="w1")
    with pytest.raises(ValidationError, match="non-empty"):
        BacklogItemView(item_id="item-1", workspace_id=" ")
    item = BacklogItemView(item_id="item-1", workspace_id="w1")
    assert item.workspace_id == "w1"
