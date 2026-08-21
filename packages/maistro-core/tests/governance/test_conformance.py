"""Tests for the policy-conformance precedence walk (SPEC-206 / ADR-074)."""

from __future__ import annotations

import pytest

from maistro.governance.conformance import ConformanceEngine
from maistro.governance.conformance_types import (
    ArtifactResolver,
    Authority,
    Invariant,
    PolicyDecision,
    PriorPolicyStore,
)


def _decision(
    *, action: str = "deploy", scope: str = "team:eng", allowed: bool = True
) -> PolicyDecision:
    return PolicyDecision(action=action, scope=scope, reversibility="reversible", allowed=allowed)


class _FixedPriorPolicyStore:
    def __init__(self, conflict_ref: str | None) -> None:
        self._conflict_ref = conflict_ref

    def find_conflict(self, candidate: PolicyDecision) -> str | None:
        return self._conflict_ref


class _FixedArtifactResolver:
    def __init__(self, artifacts: tuple[str, ...]) -> None:
        self._artifacts = artifacts

    def artifacts_for(self, conflict_ref: str) -> tuple[str, ...]:
        return self._artifacts


class TestPrecedenceOrder:
    @pytest.mark.asyncio
    async def test_conflict_with_adr_and_spec_reports_adr_layer(self) -> None:
        adr_inv = Invariant(
            id="INV-ADR", authority_ref="ADR-X", action="deploy", scope="*", checker=lambda c: False
        )
        spec_inv = Invariant(
            id="INV-SPEC",
            authority_ref="SPEC-Y",
            action="deploy",
            scope="*",
            checker=lambda c: False,
        )
        engine = ConformanceEngine(adr_invariants=(adr_inv,), spec_invariants=(spec_inv,))

        verdict = await engine.check(_decision())

        assert verdict.ok is False
        assert verdict.conflict_layer == Authority.ADR
        assert verdict.conflict_ref == "ADR-X"

    @pytest.mark.asyncio
    async def test_spec_conflict_when_adr_layer_clean(self) -> None:
        adr_inv = Invariant(
            id="INV-ADR", authority_ref="ADR-X", action="deploy", scope="*", checker=lambda c: True
        )
        spec_inv = Invariant(
            id="INV-SPEC",
            authority_ref="SPEC-Y",
            action="deploy",
            scope="*",
            checker=lambda c: False,
        )
        engine = ConformanceEngine(adr_invariants=(adr_inv,), spec_invariants=(spec_inv,))

        verdict = await engine.check(_decision())

        assert verdict.conflict_layer == Authority.SPEC
        assert verdict.conflict_ref == "SPEC-Y"

    @pytest.mark.asyncio
    async def test_prior_policy_conflict_when_adr_and_spec_clean(self) -> None:
        engine = ConformanceEngine(prior_policy_store=_FixedPriorPolicyStore("PRIOR-1"))

        verdict = await engine.check(_decision())

        assert verdict.conflict_layer == Authority.PRIOR_POLICY
        assert verdict.conflict_ref == "PRIOR-1"

    @pytest.mark.asyncio
    async def test_clean_candidate_passes(self) -> None:
        engine = ConformanceEngine(prior_policy_store=_FixedPriorPolicyStore(None))

        verdict = await engine.check(_decision())

        assert verdict.ok is True
        assert verdict.conflict_layer is None


class TestSafetyCritical:
    @pytest.mark.asyncio
    async def test_safety_critical_flag_propagates(self) -> None:
        inv = Invariant(
            id="INV-SAFE",
            authority_ref="ADR-072",
            action="*",
            scope="*",
            safety_critical=True,
            checker=lambda c: False,
        )
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision())

        assert verdict.safety_critical is True

    @pytest.mark.asyncio
    async def test_non_safety_critical_defaults_false(self) -> None:
        inv = Invariant(
            id="INV", authority_ref="ADR-X", action="*", scope="*", checker=lambda c: False
        )
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision())

        assert verdict.safety_critical is False


class TestProseOnlyFailsClosed:
    @pytest.mark.asyncio
    async def test_invariant_with_no_checker_is_never_silently_passed(self) -> None:
        inv = Invariant(id="INV-PROSE", authority_ref="ADR-Z", action="*", scope="*", checker=None)
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision())

        assert verdict.ok is False
        assert verdict.conflict_layer == Authority.ADR
        assert verdict.conflict_ref == "ADR-Z"


class TestRelevanceFiltering:
    @pytest.mark.asyncio
    async def test_invariant_for_unrelated_action_is_not_checked(self) -> None:
        inv = Invariant(
            id="INV-OTHER",
            authority_ref="ADR-X",
            action="delete",
            scope="*",
            checker=lambda c: False,
        )
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision(action="deploy"))

        assert verdict.ok is True

    @pytest.mark.asyncio
    async def test_invariant_for_unrelated_scope_is_not_checked(self) -> None:
        inv = Invariant(
            id="INV-OTHER",
            authority_ref="ADR-X",
            action="*",
            scope="team:other",
            checker=lambda c: False,
        )
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision(scope="team:eng"))

        assert verdict.ok is True

    @pytest.mark.asyncio
    async def test_wildcard_invariant_applies_to_all_actions_and_scopes(self) -> None:
        inv = Invariant(
            id="INV-WILD", authority_ref="ADR-X", action="*", scope="*", checker=lambda c: False
        )
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision(action="anything", scope="team:any"))

        assert verdict.ok is False


class TestArtifactBlastRadius:
    @pytest.mark.asyncio
    async def test_conflict_includes_resolved_artifacts(self) -> None:
        inv = Invariant(
            id="INV-X", authority_ref="ADR-X", action="*", scope="*", checker=lambda c: False
        )
        resolver: ArtifactResolver = _FixedArtifactResolver(("recipe:a", "policy:b"))
        engine = ConformanceEngine(adr_invariants=(inv,), artifact_resolver=resolver)

        verdict = await engine.check(_decision())

        assert verdict.artifacts == ("recipe:a", "policy:b")

    @pytest.mark.asyncio
    async def test_no_resolver_defaults_to_no_artifacts(self) -> None:
        inv = Invariant(
            id="INV-X", authority_ref="ADR-X", action="*", scope="*", checker=lambda c: False
        )
        engine = ConformanceEngine(adr_invariants=(inv,))

        verdict = await engine.check(_decision())

        assert verdict.artifacts == ()


def _check_protocol_conformance() -> None:
    store: PriorPolicyStore = _FixedPriorPolicyStore(None)
    resolver: ArtifactResolver = _FixedArtifactResolver(())
    assert store is not None
    assert resolver is not None
