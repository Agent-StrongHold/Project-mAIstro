"""Canonical-convergence wiring for the two RSI drivers (#50 / epic #552).

The adapters (``canonical_provenance``, ``work_source``,
``promotion_contract``) are proven elsewhere; these tests prove the *drivers
actually wired them*: the autorun campaign claims generic backlog work and
settles it against canonical Run identity, and the local loop records every
executed cycle as one canonical Run with an honest shared-contract leg on
each promotion review.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from maistro.backlog.agent_surface import AgentBacklogSurface
from maistro.backlog.model import BacklogItemStatus
from maistro.backlog.store import InMemoryBacklogStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.workspaces.backlog_history import InMemoryBacklogHistoryStore
from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.autorun import AutorunConfig, run_autonomous
from maistro_rsi.canonical_provenance import RsiCycleProvenance
from maistro_rsi.coordinator import ExecutionReport, HypothesisEvidence
from maistro_rsi.local_loop import CycleOutcome, LocalRsiConfig, LocalRsiLoop
from maistro_rsi.work_source import RsiWorkSource

WS = "ws-convergence"
PROJECT = "proj-1"


async def _stack() -> tuple[
    RsiCycleProvenance, RsiWorkSource, InMemoryBacklogStore, InMemoryRunStore
]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WS)
    runs = InMemoryRunStore(project_store=projects)
    provenance = RsiCycleProvenance(runs, workspace_id=WS, project_id=root.project_id)
    backlog = InMemoryBacklogStore()
    history = InMemoryBacklogHistoryStore()

    async def authorize(actor: str, workspace_id: str, action: str):
        if workspace_id != WS:
            return None
        return "editor" if actor == "rsi-campaign" else None

    surface = AgentBacklogSurface(backlog, authorize)
    work_source = RsiWorkSource(surface, history=history, backlog_store=backlog, project_id=PROJECT)
    return provenance, work_source, backlog, runs


def _autorun_config(tmp_path, **overrides) -> AutorunConfig:
    base = {
        "repo_url": "https://github.com/org/repo.git",
        "test_command": "pytest -q",
        "num_cycles": 1,
        "workspace_root": str(tmp_path),
    }
    base.update(overrides)
    return AutorunConfig(**base)


class TestAutorunCanonicalWiring:
    async def test_work_source_without_provenance_is_refused(self, tmp_path):
        """A claimed backlog item must be worked under canonical Run identity,
        never an RSI-private one — the wiring refuses the half-state."""
        _, work_source, _, _ = await _stack()
        config = _autorun_config(tmp_path)

        async def executor(context):
            return ExecutionReport(evidence=HypothesisEvidence())

        try:
            await run_autonomous(
                config,
                executor=executor,
                proposer=lambda ctx: "next",
                work_source=work_source,
            )
        except ValueError as exc:
            assert "work_source requires provenance" in str(exc)
        else:
            raise AssertionError("expected ValueError for work_source without provenance")

    async def test_campaign_claims_works_and_closes_it_with_run_evidence(self, tmp_path):
        provenance, work_source, backlog, runs = await _stack()
        await backlog.create_item(
            workspace_id=WS,
            title="Improve the router",
            details="make it faster",
            actor="human:owner",
            item_id="eng-001",
        )
        seen: list[str] = []

        async def executor(context):
            seen.append(context.node.hypothesis)
            return ExecutionReport(
                evidence=HypothesisEvidence(
                    tests_passed=True, benchmarks_won=1, battles=1, improved=True
                )
            )

        await run_autonomous(
            _autorun_config(tmp_path),
            executor=executor,
            proposer=lambda ctx: "next",
            provenance=provenance,
            work_source=work_source,
            work_actor="rsi-campaign",
        )

        # The claimed objective was worked: it is the campaign's first cycle.
        assert seen and "Improve the router" in seen[0]
        # Every executed cycle left a completed canonical Run in the store.
        canonical = await runs.list_by_status(
            RunStatus.COMPLETED, limit=100, admission_source="rsi"
        )
        assert canonical, "the campaign's cycles must exist as canonical Runs"
        # The claimed item was closed with evidence citing the canonical Run.
        item = await backlog.get_item("eng-001")
        assert item is not None and item.status == BacklogItemStatus.DONE
        assert item.closure is not None
        cited = set(item.closure.evidence_refs)
        assert any(
            ref.startswith("run:") and ref[4:] in {r.run_id for r in canonical} for ref in cited
        )

    async def test_unimproved_campaign_releases_the_claim(self, tmp_path):
        provenance, work_source, backlog, _ = await _stack()
        await backlog.create_item(
            workspace_id=WS,
            title="Try an improvement",
            actor="human:owner",
            item_id="eng-002",
        )

        async def executor(context):
            return ExecutionReport(
                evidence=HypothesisEvidence(
                    tests_passed=True, benchmarks_won=0, battles=1, improved=False
                )
            )

        await run_autonomous(
            _autorun_config(tmp_path),
            executor=executor,
            proposer=lambda ctx: "next",
            provenance=provenance,
            work_source=work_source,
            work_actor="rsi-campaign",
        )

        # No proven improvement: the item stays open for the next claimant.
        item = await backlog.get_item("eng-002")
        assert item is not None and item.status != BacklogItemStatus.DONE


def _make_repo(path) -> None:
    """A minimal git repo the local loop can clone and improve."""
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    _git_cmd = ["git", "-C", str(path)]
    subprocess.run([*_git_cmd, "init", "-q"], check=True)
    subprocess.run([*_git_cmd, "config", "user.email", "rsi@test"], check=True)
    subprocess.run([*_git_cmd, "config", "user.name", "rsi-test"], check=True)
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    subprocess.run([*_git_cmd, "add", "-A"], check=True)
    subprocess.run([*_git_cmd, "commit", "-q", "-m", "init"], check=True)


class TestLocalLoopCanonicalWiring:
    def test_each_executed_cycle_is_recorded_as_a_canonical_run(self, tmp_path):
        import asyncio

        projects = InMemoryProjectScopeStore()
        asyncio.run(projects.create_root(WS))
        root_created = None

        async def _setup():
            nonlocal root_created
            root_created = await projects.create_root(WS)

        asyncio.run(_setup())
        runs = InMemoryRunStore(project_store=projects)
        provenance = RsiCycleProvenance(runs, workspace_id=WS, project_id=root_created.project_id)

        repo = tmp_path / "src"
        _make_repo(repo)

        def bump(ws) -> None:
            f = ws / "value.txt"
            f.write_text(f.read_text() + "x\n", encoding="utf-8")

        async def apply(sandbox, workspace, model=None):
            bump(__import__("pathlib").Path(workspace))

        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="exit 0",
            work_root=str(tmp_path / "work"),
            report_dir=str(tmp_path / "report"),
            max_cycles=2,
        )
        loop = LocalRsiLoop(
            config,
            apply,
            provenance=provenance,
            campaign_id="camp-local",
            actor_principal_id="human:op-1",
        )
        result = loop.run()

        executed = [c for c in result.cycles if c.changed]
        assert executed, "fixture must produce real work"
        for outcome in executed:
            assert outcome.evaluation_run_ids, "each executed cycle must cite its Run"
        # The cited Runs are real, completed canonical Runs.
        import asyncio as _aio

        async def _fetch(run_id):
            return await runs.get_run(run_id)

        for outcome in executed:
            run = _aio.run(_fetch(outcome.evaluation_run_ids[0]))
            assert run is not None
            assert run.status is RunStatus.COMPLETED
            assert run.provenance.get("rsi_campaign_id") == "camp-local"

        # The promotion reviews reported the shared contract honestly: the
        # plain-fixture promotions carry no evaluator provenance, so the leg
        # says skipped rather than fabricating a record.
        report_dir = tmp_path / "report"
        records = sorted((report_dir / "promotions").glob("*.json"))
        assert records
        shared = [json.loads(p.read_text())["decision"]["shared_contract"] for p in records]
        assert shared
        assert all(entry["status"] == "skipped" for entry in shared), shared

    def _loop(self, tmp_path) -> LocalRsiLoop:
        return LocalRsiLoop(
            LocalRsiConfig(
                repo_path=str(tmp_path / "repo"),
                test_command="exit 0",
                work_root=str(tmp_path / "work"),
            )
        )

    def test_shared_contract_leg_skips_without_canonical_runs(self, tmp_path):
        loop = self._loop(tmp_path)
        outcome = CycleOutcome(0, changed=True, tests_passed=True, promoted=True)
        leg = loop._shared_contract_leg(
            outcome,
            sha="b" * 40,
            built_on="a" * 40,
            touched_paths=["x.py"],
            note=None,
            decision={"outcome": "auto_keep_mechanical"},
        )
        assert leg["status"] == "skipped"
        assert "canonical evaluation Run" in leg["reason"]

    def test_shared_contract_leg_skips_without_evaluator_provenance(self, tmp_path):
        loop = self._loop(tmp_path)
        outcome = CycleOutcome(
            0, changed=True, tests_passed=True, promoted=True, evaluation_run_ids=("r1",)
        )
        leg = loop._shared_contract_leg(
            outcome,
            sha="b" * 40,
            built_on="a" * 40,
            touched_paths=["x.py"],
            note=None,
            decision={"outcome": "auto_keep_mechanical"},
        )
        assert leg["status"] == "skipped"
        assert "evaluator version provenance" in leg["reason"]

    def test_shared_contract_leg_records_a_kept_promotion(self, tmp_path):
        loop = self._loop(tmp_path)
        note = SimpleNamespace(evaluator={"evaluator_digest": "digest-1"}, version=2)
        outcome = CycleOutcome(
            1,
            changed=True,
            tests_passed=True,
            promoted=True,
            sha="b" * 40,
            kind=ImprovementKind.PERF,
            evaluation_run_ids=("run-1",),
        )
        leg = loop._shared_contract_leg(
            outcome,
            sha="b" * 40,
            built_on="a" * 40,
            touched_paths=["packages/app/src/thing.py"],
            note=note,
            decision={"outcome": "auto_keep_mechanical", "reason": "gates green"},
        )
        assert leg["status"] == "recorded", leg
        assert leg["new_version"] == 1
        assert leg["policy"] == "rsi-checkpoint-review-v1"
        assert leg["authority"] == "rsi-mechanical-policy-v1"
        # A second kept promotion on the same subject chains the version.
        second = loop._shared_contract_leg(
            outcome,
            sha="c" * 40,
            built_on="b" * 40,
            touched_paths=["packages/app/src/other.py"],
            note=note,
            decision={"outcome": "auto_keep_judgment", "reason": "reviewer keep"},
        )
        assert second["status"] == "recorded", second
        assert second["new_version"] == 2

    def test_shared_contract_leg_reports_a_refusal_loudly(self, tmp_path):
        from maistro_rsi.sensitive_paths import EVALUATOR_ORACLE_PATTERNS

        loop = self._loop(tmp_path)
        note = SimpleNamespace(evaluator={"evaluator_digest": "d"}, version=1)
        outcome = CycleOutcome(
            1,
            changed=True,
            tests_passed=True,
            promoted=True,
            sha="b" * 40,
            evaluation_run_ids=("run-1",),
        )
        leg = loop._shared_contract_leg(
            outcome,
            sha="b" * 40,
            built_on="a" * 40,
            touched_paths=[EVALUATOR_ORACLE_PATTERNS[0], "x.py"],
            note=note,
            decision={"outcome": "auto_keep_mechanical"},
        )
        assert leg["status"] == "refused", leg
        assert leg["reason"]
