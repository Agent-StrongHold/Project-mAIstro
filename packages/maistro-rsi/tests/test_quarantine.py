"""Tests tied to SPEC.md §2 (quarantine gate) acceptance criteria quarantine-1..5."""

from __future__ import annotations

import pytest

from maistro.security._types import WardenVerdict
from maistro_rsi.quarantine import _touches_sensitive_surface, quarantine_scan


class FakeWarden:
    def __init__(self, verdict: WardenVerdict) -> None:
        self._verdict = verdict
        self.scan_calls: list[tuple[str, str]] = []

    async def scan(self, content, boundary="default"):
        self.scan_calls.append((content, boundary))
        return self._verdict


class FakeAdversarialReview:
    def __init__(self, *, approve: bool) -> None:
        self.approve = approve
        self.review_calls: list[tuple[str, list[str]]] = []

    async def review(self, diff, touched_paths):
        self.review_calls.append((diff, touched_paths))
        return self.approve


ORDINARY_PATHS = ["packages/maistro-core/src/maistro/agents/base.py"]
SENSITIVE_PATHS = ["packages/maistro-rsi/src/maistro_rsi/quarantine.py", "README.md"]


class TestQuarantineScan:
    @pytest.mark.asyncio
    async def test_flagged_diff_never_clears_regardless_of_touched_paths(self):
        """quarantine-1: cleared is False whenever the Warden verdict is not clean."""
        flagged = WardenVerdict(clean=False, flags=("secret_leak",))

        ordinary = await quarantine_scan("diff", ORDINARY_PATHS, FakeWarden(flagged))
        sensitive = await quarantine_scan("diff", SENSITIVE_PATHS, FakeWarden(flagged))

        assert ordinary.cleared is False
        assert sensitive.cleared is False

    @pytest.mark.asyncio
    async def test_clean_diff_touching_no_sensitive_surface_clears_without_review(self):
        """quarantine-2: a clean diff touching ordinary surface clears, no adversarial review required."""
        clean = WardenVerdict(clean=True, flags=())

        verdict = await quarantine_scan("diff", ORDINARY_PATHS, FakeWarden(clean))

        assert verdict.cleared is True
        assert verdict.requires_adversarial_review is False

    @pytest.mark.asyncio
    async def test_diff_touching_any_sensitive_path_requires_adversarial_review(self):
        """quarantine-3: touching even one sensitive-surface path sets requires_adversarial_review,
        regardless of the Warden verdict."""
        clean = WardenVerdict(clean=True, flags=())
        flagged = WardenVerdict(clean=False, flags=("secret_leak",))

        clean_verdict = await quarantine_scan("diff", SENSITIVE_PATHS, FakeWarden(clean))
        flagged_verdict = await quarantine_scan("diff", SENSITIVE_PATHS, FakeWarden(flagged))

        assert clean_verdict.requires_adversarial_review is True
        assert flagged_verdict.requires_adversarial_review is True

    @pytest.mark.asyncio
    async def test_cleared_requires_clean_warden_and_no_pending_adversarial_review(self):
        """quarantine-4: cleared is True only when Warden is clean AND (no review required OR
        a supplied adversarial review passed). A pending/missing review on a sensitive diff
        must never clear."""
        clean = WardenVerdict(clean=True, flags=())

        # Sensitive-surface diff, no adversarial reviewer supplied -> pending, never clears.
        pending = await quarantine_scan("diff", SENSITIVE_PATHS, FakeWarden(clean))
        assert pending.cleared is False
        assert pending.requires_adversarial_review is True

        # Sensitive-surface diff, reviewer supplied and approves -> clears.
        approved = await quarantine_scan(
            "diff",
            SENSITIVE_PATHS,
            FakeWarden(clean),
            adversarial_review=FakeAdversarialReview(approve=True),
        )
        assert approved.cleared is True

        # Sensitive-surface diff, reviewer supplied and rejects -> never clears.
        rejected = await quarantine_scan(
            "diff",
            SENSITIVE_PATHS,
            FakeWarden(clean),
            adversarial_review=FakeAdversarialReview(approve=False),
        )
        assert rejected.cleared is False

    @pytest.mark.asyncio
    async def test_flags_surface_warden_flags_verbatim(self):
        """quarantine-5: the verdict's flags carry the Warden flags verbatim, unsummarized."""
        flagged = WardenVerdict(clean=False, flags=("secret_leak", "prompt_injection"))

        verdict = await quarantine_scan("diff", ORDINARY_PATHS, FakeWarden(flagged))

        assert verdict.flags == ("secret_leak", "prompt_injection")


class TestSensitiveSurfaceCoverage:
    """The DAG-synthesis substrate (depth cap, synth_dag/spawn_harness nodes) is part of
    the agent's own containment surface once RSI can propose changes to this repo — a
    self-diff patching the recursion-depth cap or the harness-dispatch node changes what
    *future* self-modifications are allowed to get away with, same as sandbox/security code."""

    def test_depth_cap_is_sensitive_surface(self):
        touched = _touches_sensitive_surface(["packages/maistro-core/src/maistro/graph/depth.py"])
        assert touched

    def test_synth_dag_node_is_sensitive_surface(self):
        touched = _touches_sensitive_surface(
            ["packages/maistro-core/src/maistro/graph/nodes/agent_synth_dag.py"]
        )
        assert touched

    def test_spawn_harness_node_is_sensitive_surface(self):
        touched = _touches_sensitive_surface(
            ["packages/maistro-core/src/maistro/graph/nodes/agent_spawn_harness.py"]
        )
        assert touched

    def test_durable_executor_is_sensitive_surface(self):
        """The durable executor carries the actual synth_depth increment/
        enforcement across checkpoints -- a diff here can defang the
        recursion cap just as effectively as touching depth.py itself."""
        touched = _touches_sensitive_surface(
            ["packages/maistro-core/src/maistro/graph/durable_runs/executor.py"]
        )
        assert touched

    def test_htr_coordinator_is_sensitive_surface(self):
        touched = _touches_sensitive_surface(
            ["packages/maistro-rsi/src/maistro_rsi/coordinator.py"]
        )
        assert touched

    def test_dag_shape_gate_is_sensitive_surface_via_security_prefix(self):
        """Not new — already covered by the existing "maistro/security/" prefix. Asserted
        here so a future refactor of that prefix can't silently drop this coverage."""
        touched = _touches_sensitive_surface(
            ["packages/maistro-core/src/maistro/security/dag_shape/evaluator.py"]
        )
        assert touched

    def test_ordinary_graph_node_is_not_sensitive_surface(self):
        touched = _touches_sensitive_surface(
            ["packages/maistro-core/src/maistro/graph/nodes/llm_summarize.py"]
        )
        assert touched == []

    @pytest.mark.asyncio
    async def test_diff_touching_depth_cap_requires_adversarial_review(self):
        clean = WardenVerdict(clean=True, flags=())
        verdict = await quarantine_scan(
            "diff",
            ["packages/maistro-core/src/maistro/graph/depth.py"],
            FakeWarden(clean),
        )
        assert verdict.requires_adversarial_review is True
        assert verdict.cleared is False  # no reviewer supplied -> pending, never clears


class TestSensitivePathMatching:
    """Segment-boundary matching, not raw substring: `pattern in path` accepted
    unrelated look-alikes and a leading `./` (or the lstrip('./') "fix" that
    eats the dot of .github/) broke real containment paths."""

    def test_directory_pattern_matches_at_root_and_nested(self):
        from maistro_rsi.quarantine import matches_sensitive_pattern

        assert matches_sensitive_pattern(".github/workflows/ci.yml")
        assert matches_sensitive_pattern(
            "packages/maistro-core/src/maistro/security/warden/detector.py"
        )

    def test_file_pattern_matches_whole_segment_only(self):
        from maistro_rsi.quarantine import matches_sensitive_pattern

        assert matches_sensitive_pattern("packages/maistro-rsi/src/maistro_rsi/runner.py")
        # A suffix look-alike is NOT the protected file.
        assert not matches_sensitive_pattern("packages/x/src/notmaistro_rsi/runner.py.orig")

    def test_leading_dot_slash_is_normalized_without_eating_dots(self):
        from maistro_rsi.quarantine import matches_sensitive_pattern

        # The lstrip("./") character-set bug turned "./.github/x" into "github/x".
        assert matches_sensitive_pattern("./.github/workflows/quality.yml")
        assert matches_sensitive_pattern("./packages/maistro-rsi/src/maistro_rsi/autorun.py")

    def test_unrelated_sibling_directory_does_not_match(self):
        from maistro_rsi.quarantine import matches_sensitive_pattern

        assert not matches_sensitive_pattern("packages/x/src/notmaistro/security_helpers.py")
        assert not matches_sensitive_pattern("docs/quality-notes/README.md")
