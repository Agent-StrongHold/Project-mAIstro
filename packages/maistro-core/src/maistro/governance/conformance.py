"""The ADR->Spec->prior-policy precedence walk (SPEC-206 / ADR-074)."""

from __future__ import annotations

from maistro.governance.conformance_types import (
    ArtifactResolver,
    Authority,
    ConformanceVerdict,
    Invariant,
    NoopArtifactResolver,
    PolicyDecision,
    PriorPolicyStore,
)


def _is_relevant(invariant: Invariant, candidate: PolicyDecision) -> bool:
    """Whether an invariant's action/scope overlaps the candidate's, including wildcards."""
    action_matches = invariant.action in ("*", candidate.action)
    scope_matches = invariant.scope in ("*", candidate.scope)
    return action_matches and scope_matches


class ConformanceEngine:
    """Checks a candidate policy decision against ADRs, then Specs, then prior policy."""

    def __init__(
        self,
        *,
        adr_invariants: tuple[Invariant, ...] = (),
        spec_invariants: tuple[Invariant, ...] = (),
        prior_policy_store: PriorPolicyStore | None = None,
        artifact_resolver: ArtifactResolver | None = None,
    ) -> None:
        """Wire the invariant sets and the prior-policy/artifact-resolution extension points."""
        self._adr_invariants = adr_invariants
        self._spec_invariants = spec_invariants
        self._prior_policy_store = prior_policy_store
        self._artifact_resolver = artifact_resolver or NoopArtifactResolver()

    def _check_layer(
        self, authority: Authority, invariants: tuple[Invariant, ...], candidate: PolicyDecision
    ) -> ConformanceVerdict | None:
        """Check one authority layer's relevant invariants, returning the first conflict found."""
        for invariant in invariants:
            if not _is_relevant(invariant, candidate):
                continue
            if invariant.checker is None:
                reason = f"invariant {invariant.id} is prose-only and requires human review"
            elif not invariant.checker(candidate):
                reason = f"invariant {invariant.id} not satisfied"
            else:
                continue
            return ConformanceVerdict(
                ok=False,
                conflict_layer=authority,
                conflict_ref=invariant.authority_ref,
                safety_critical=invariant.safety_critical,
                artifacts=self._artifact_resolver.artifacts_for(invariant.authority_ref),
                evidence={"reason": reason},
            )
        return None

    async def check(self, candidate: PolicyDecision) -> ConformanceVerdict:
        """Walk ADR -> Spec -> prior-policy, returning on the first conflict found."""
        adr_verdict = self._check_layer(Authority.ADR, self._adr_invariants, candidate)
        if adr_verdict is not None:
            return adr_verdict

        spec_verdict = self._check_layer(Authority.SPEC, self._spec_invariants, candidate)
        if spec_verdict is not None:
            return spec_verdict

        if self._prior_policy_store is not None:
            conflict_ref = self._prior_policy_store.find_conflict(candidate)
            if conflict_ref is not None:
                return ConformanceVerdict(
                    ok=False,
                    conflict_layer=Authority.PRIOR_POLICY,
                    conflict_ref=conflict_ref,
                    artifacts=self._artifact_resolver.artifacts_for(conflict_ref),
                    evidence={"reason": "contradicts a prior policy decision"},
                )

        return ConformanceVerdict(ok=True)
