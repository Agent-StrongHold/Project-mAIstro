"""Tests for RLPHD predictive approval (SPEC-248 / ADR-068 §E)."""

from __future__ import annotations

from maistro.security.sentinel.approver_graph import ApproverGraph
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.sentinel.rlphd import (
    COLD_START_THETA,
    InMemoryRlphdThresholdStore,
    RlphdModel,
    is_surprise,
    update_theta,
)
from maistro.security.warden.detector import Warden


def _agent(principal_id: str, scopes: tuple[str, ...] = ()) -> Principal:
    return Principal(id=principal_id, kind="agent", roles=(), scopes=scopes, owner="u1")


class TestPredictPurity:
    def test_predict_is_pure_function_of_weights_and_features(self) -> None:
        model = RlphdModel(feature_weights={"risk": 1.0, "recency": -0.5})

        p1 = model.predict({"risk": 0.8, "recency": 0.2})
        p2 = model.predict({"risk": 0.8, "recency": 0.2})

        assert p1 == p2

    def test_predict_missing_feature_defaults_to_zero(self) -> None:
        model = RlphdModel(feature_weights={"risk": 1.0})

        assert model.predict({}) == model.predict({"risk": 0.0})


class TestUpdateDirection:
    def test_deny_at_high_p_raises_theta_and_lowers_weight(self) -> None:
        model = RlphdModel(feature_weights={"risk": 1.0})
        predicted_p = model.predict({"risk": 1.0})

        updated = model.update({"risk": 1.0}, "deny", predicted_p)
        new_theta = update_theta(0.7, predicted_p, "deny")

        assert updated.feature_weights["risk"] < model.feature_weights["risk"]
        assert new_theta > 0.7

    def test_approve_at_low_p_lowers_theta_and_raises_weight(self) -> None:
        model = RlphdModel(feature_weights={"risk": -1.0})
        predicted_p = model.predict({"risk": 1.0})

        updated = model.update({"risk": 1.0}, "approve", predicted_p)
        new_theta = update_theta(0.7, predicted_p, "approve")

        assert updated.feature_weights["risk"] > model.feature_weights["risk"]
        assert new_theta < 0.7


class TestConfidenceGapScaling:
    """The weight step scales with |p - theta|: a confident-wrong prediction
    teaches the most, a borderline call (p ≈ theta) teaches little."""

    def test_confident_prediction_moves_weights_more_than_borderline(self) -> None:
        feats = {"risk": 1.0}
        # Same denial, same features — only the confidence gap differs.
        borderline = RlphdModel().update(feats, "deny", predicted_p=0.5, theta=0.45)
        confident = RlphdModel().update(feats, "deny", predicted_p=0.9, theta=0.45)

        assert borderline.feature_weights["risk"] < 0  # denied -> risk weight drops
        # Confident-wrong (|0.9-0.45|=0.45) moves it further than borderline (|0.5-0.45|=0.05).
        assert confident.feature_weights["risk"] < borderline.feature_weights["risk"]

    def test_update_without_theta_is_unscaled_legacy_step(self) -> None:
        # No theta => gap_scale = 1.0 => the plain gradient step is unchanged.
        feats = {"risk": 1.0}
        updated = RlphdModel().update(feats, "deny", predicted_p=0.8)

        # base(0) + lr(0.1) * error(0 - 0.8) * feat(1.0) = -0.08
        assert abs(updated.feature_weights["risk"] - (-0.08)) < 1e-9


class TestSurpriseWeighting:
    def test_confirmation_moves_theta_less_than_equal_magnitude_surprise(self) -> None:
        theta = 0.7
        surprise_theta = update_theta(theta, predicted_p=0.9, decision="deny")
        confirm_theta = update_theta(theta, predicted_p=0.1, decision="deny")

        assert abs(surprise_theta - theta) > abs(confirm_theta - theta)

    def test_is_surprise_classifies_deny_above_theta_as_surprise(self) -> None:
        assert is_surprise("deny", predicted_p=0.9, theta=0.7) is True
        assert is_surprise("deny", predicted_p=0.5, theta=0.7) is False

    def test_is_surprise_classifies_approve_below_theta_as_surprise(self) -> None:
        assert is_surprise("approve", predicted_p=0.2, theta=0.7) is True
        assert is_surprise("approve", predicted_p=0.9, theta=0.7) is False


class TestThresholdStore:
    async def test_get_theta_defaults_to_cold_start(self) -> None:
        store = InMemoryRlphdThresholdStore()

        assert await store.get_theta("u1", "deploy", "delegated") == COLD_START_THETA

    async def test_set_then_get_theta_roundtrips(self) -> None:
        store = InMemoryRlphdThresholdStore()

        await store.set_theta("u1", "deploy", "delegated", 0.85)

        assert await store.get_theta("u1", "deploy", "delegated") == 0.85

    async def test_opted_in_defaults_false(self) -> None:
        store = InMemoryRlphdThresholdStore()

        assert await store.opted_in("u1", "deploy") is False


class TestSentinelIntegration:
    async def test_rlphd_not_invoked_when_not_opted_in(self) -> None:
        store = InMemoryRlphdThresholdStore()
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("deploy", "team:1"): Tier.DELEGATED},
            approver_graph=ApproverGraph([]),
            rlphd_model=RlphdModel(feature_weights={"risk": 5.0}),
            rlphd_threshold_store=store,
        )
        principal = _agent("agent-1", scopes=("team:1",))

        decision = await sentinel.authorize("deploy", principal, within_budget=True)

        assert decision.rlphd is None
        assert decision.needs == "delegated"

    async def test_rlphd_auto_acts_when_opted_in_and_p_above_theta(self) -> None:
        store = InMemoryRlphdThresholdStore()
        store.opt_ins.add(("agent-1", "deploy"))
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("deploy", "team:1"): Tier.DELEGATED},
            approver_graph=ApproverGraph([]),
            rlphd_model=RlphdModel(feature_weights={"risk": 5.0}),
            rlphd_threshold_store=store,
        )
        principal = _agent("agent-1", scopes=("team:1",))

        decision = await sentinel.authorize(
            "deploy", principal, within_budget=True, rlphd_features={"risk": 1.0}
        )

        assert decision.rlphd is not None
        assert decision.rlphd.auto_acted is True
        assert decision.needs == "none"

    async def test_rlphd_surfaces_low_confidence_without_auto_acting(self) -> None:
        store = InMemoryRlphdThresholdStore()
        store.opt_ins.add(("agent-1", "deploy"))
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("deploy", "team:1"): Tier.DELEGATED},
            approver_graph=ApproverGraph([]),
            rlphd_model=RlphdModel(feature_weights={"risk": -5.0}),
            rlphd_threshold_store=store,
        )
        principal = _agent("agent-1", scopes=("team:1",))

        decision = await sentinel.authorize(
            "deploy", principal, within_budget=True, rlphd_features={"risk": 1.0}
        )

        assert decision.rlphd is not None
        assert decision.rlphd.auto_acted is False
        assert decision.needs == "delegated"

    async def test_rlphd_never_invoked_for_admin_tier(self) -> None:
        store = InMemoryRlphdThresholdStore()
        store.opt_ins.add(("agent-1", "destroy_db"))
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("destroy_db", "team:1"): Tier.ADMIN},
            rlphd_model=RlphdModel(feature_weights={"risk": 5.0}),
            rlphd_threshold_store=store,
        )
        principal = _agent("agent-1", scopes=("team:1",))

        decision = await sentinel.authorize("destroy_db", principal, within_budget=True)

        assert decision.rlphd is None
        assert decision.needs == "admin"

    async def test_rlphd_never_invoked_for_blocked_tier(self) -> None:
        store = InMemoryRlphdThresholdStore()
        store.opt_ins.add(("agent-1", "wipe_disk"))
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("wipe_disk", "team:1"): Tier.BLOCKED},
            rlphd_model=RlphdModel(feature_weights={"risk": 5.0}),
            rlphd_threshold_store=store,
        )
        principal = _agent("agent-1", scopes=("team:1",))

        decision = await sentinel.authorize("wipe_disk", principal, within_budget=True)

        assert decision.rlphd is None
        assert decision.authorized is False
        assert decision.reason == "action is blocked"

    async def test_rlphd_never_invoked_before_budget_check(self) -> None:
        store = InMemoryRlphdThresholdStore()
        store.opt_ins.add(("agent-1", "deploy"))
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("deploy", "team:1"): Tier.DELEGATED},
            rlphd_model=RlphdModel(feature_weights={"risk": 5.0}),
            rlphd_threshold_store=store,
        )
        principal = _agent("agent-1", scopes=("team:1",))

        decision = await sentinel.authorize("deploy", principal, within_budget=False)

        assert decision.rlphd is None
        assert decision.within_budget is False
        assert decision.authorized is False
