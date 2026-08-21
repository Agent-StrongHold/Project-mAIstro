"""Tests tied to SPEC.md §5 (RSI cycle runner) acceptance criteria runner-1..5."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalResult, EvalWeights, NodeGenome, PipelineGenome
from maistro_rsi.runner import RsiCycle, RsiCycleConfig
from maistro_rsi.selfbranch import SelfBranchResult


def _genome(genome_id: str) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


class FakeSandbox:
    def __init__(self, *, raise_on_exec: bool = False) -> None:
        self.destroyed = False
        self.raise_on_exec = raise_on_exec

    async def exec(self, command, timeout=60):
        if self.raise_on_exec:
            raise RuntimeError("sandbox blew up")
        return 0, "ok"

    async def destroy(self):
        self.destroyed = True


class FakeHarness:
    """Returns a fixed score map per genome id; benchmark sets can differ to exercise runner-2."""

    def __init__(self, scores: dict[str, dict[str, float]]) -> None:
        self._scores = scores
        self.received_llm_calls: list[object] = []

    async def evaluate_genome(self, genome, benchmarks=None, llm_call=None):
        self.received_llm_calls.append(llm_call)
        per_benchmark = self._scores[genome.id]
        return [
            EvalResult(benchmark=name, score=score)
            for name, score in per_benchmark.items()
            if benchmarks is None or name in benchmarks
        ]


class FakeScheduler:
    def __init__(self, model: str | None = "openai/gpt-5") -> None:
        self._model = model

    async def next_model(self, available_models):
        return self._model


def _config(**overrides) -> RsiCycleConfig:
    base = {
        "repo_url": "https://github.com/org/repo.git",
        "test_command": "pytest -q",
        "benchmarks": ["proxy_swebench", "proxy_swebench_pro"],
    }
    base.update(overrides)
    return RsiCycleConfig(**base)


async def _noop_patch(sandbox, workspace, model=None) -> None:
    pass


@pytest.fixture
def patched_sandbox(monkeypatch):
    """Replace `create_rsi_sandbox` with a controllable fake; returns the fake instance holder."""
    holder: dict[str, FakeSandbox] = {}

    async def fake_create(workspace, settings=None, env=None, backend=None):
        sandbox = holder.setdefault("sandbox", FakeSandbox())
        return sandbox

    # runner imports create_rsi_sandbox (the backend-selecting wrapper), so the
    # fake must replace that binding — not create_microvm_sandbox, which runner
    # never imports and which lacks the `backend` argument the fake accepts.
    monkeypatch.setattr("maistro_rsi.runner.create_rsi_sandbox", fake_create)
    return holder


@pytest.fixture
def patched_self_branch(monkeypatch):
    """Skip the real git/sandbox plumbing; the runner only needs a SelfBranchResult back."""

    async def fake_run_attempt(
        sandbox,
        workspace,
        attempt,
        apply_patch,
        open_pr=False,
        quarantine_check=None,
        model=None,
        probe=None,
    ):
        await apply_patch(sandbox, workspace, model)
        exit_code, output = await sandbox.exec(attempt.test_command)
        return SelfBranchResult(
            attempt=attempt,
            test_exit_code=exit_code,
            test_output=output,
            diff="diff",
        )

    monkeypatch.setattr("maistro_rsi.runner.run_self_branch_attempt", fake_run_attempt)


class TestRsiCycleRun:
    @pytest.mark.asyncio
    async def test_evaluates_baseline_and_candidate_on_configured_benchmarks(
        self,
        patched_sandbox,
        patched_self_branch,
    ):
        """runner-1: both genomes are evaluated on exactly RsiCycleConfig.benchmarks."""
        scores = {
            "baseline": {"proxy_swebench": 0.4, "proxy_swebench_pro": 0.2},
            "candidate": {"proxy_swebench": 0.6, "proxy_swebench_pro": 0.5},
        }
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench", "proxy_swebench_pro"]),
            FakeHarness(scores),
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
        )

        result = await cycle.run(_genome("baseline"), _genome("candidate"), ["openai/gpt-5"])

        assert {r.benchmark for r in result.baseline_results} == {
            "proxy_swebench",
            "proxy_swebench_pro",
        }
        assert {r.benchmark for r in result.candidate_results} == {
            "proxy_swebench",
            "proxy_swebench_pro",
        }

    @pytest.mark.asyncio
    async def test_battles_only_recorded_for_benchmarks_present_in_both_result_sets(
        self,
        patched_sandbox,
        patched_self_branch,
    ):
        """runner-2: a benchmark missing from either side is skipped, not battled with a missing score."""
        scores = {
            "baseline": {"proxy_swebench": 0.4, "proxy_swebench_pro": 0.2},
            "candidate": {"proxy_swebench": 0.6},  # no proxy_swebench_pro score for the candidate
        }
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench", "proxy_swebench_pro"]),
            FakeHarness(scores),
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
        )

        result = await cycle.run(_genome("baseline"), _genome("candidate"), ["openai/gpt-5"])

        assert len(result.battles) == 1
        assert result.battles[0].benchmark == "proxy_swebench"

    @pytest.mark.asyncio
    async def test_benchmarks_won_counts_only_outright_candidate_wins(
        self,
        patched_sandbox,
        patched_self_branch,
    ):
        """runner-3: draws and baseline wins do not count toward benchmarks_won."""
        scores = {
            "baseline": {"a": 0.5, "b": 0.5, "c": 0.7},
            "candidate": {"a": 0.5, "b": 0.9, "c": 0.3},  # a=draw, b=candidate win, c=baseline win
        }
        cycle = RsiCycle(
            _config(benchmarks=["a", "b", "c"]),
            FakeHarness(scores),
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
        )

        result = await cycle.run(_genome("baseline"), _genome("candidate"), ["openai/gpt-5"])

        assert result.benchmarks_won == 1

    @pytest.mark.asyncio
    async def test_improved_requires_passing_tests_and_benchmark_majority(
        self,
        patched_sandbox,
        patched_self_branch,
        monkeypatch,
    ):
        """runner-4: improved is True only with BOTH a passing test suite and a benchmark majority."""
        winning_scores = {
            "baseline": {"a": 0.3, "b": 0.3},
            "candidate": {"a": 0.9, "b": 0.9},  # candidate wins both
        }

        # Case 1: tests pass + candidate wins majority -> improved
        cycle = RsiCycle(
            _config(benchmarks=["a", "b"]),
            FakeHarness(winning_scores),
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
        )
        result_ok = await cycle.run(_genome("baseline"), _genome("candidate"), ["openai/gpt-5"])
        assert result_ok.improved is True

        # Case 2: candidate wins majority but tests fail -> not improved
        async def failing_attempt(
            sandbox,
            workspace,
            attempt,
            apply_patch,
            open_pr=False,
            quarantine_check=None,
            model=None,
            probe=None,
        ):
            await apply_patch(sandbox, workspace, model)
            return SelfBranchResult(attempt=attempt, test_exit_code=1, test_output="boom", diff="")

        monkeypatch.setattr("maistro_rsi.runner.run_self_branch_attempt", failing_attempt)
        result_failed_tests = await cycle.run(
            _genome("baseline"), _genome("candidate"), ["openai/gpt-5"]
        )
        assert result_failed_tests.improved is False

    @pytest.mark.asyncio
    async def test_injected_llm_call_reaches_both_genome_evals(
        self, patched_sandbox, patched_self_branch
    ):
        """A caller-supplied llm_call is threaded to evaluate_genome for both genomes."""
        harness = FakeHarness(
            {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}
        )

        async def injected(messages, *, temperature=0.2, max_tokens=2048):
            return "x"

        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            harness,
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
            llm_call=injected,
        )
        await cycle.run(_genome("baseline"), _genome("candidate"), ["m"])
        assert harness.received_llm_calls == [injected, injected]

    @pytest.mark.asyncio
    async def test_gateway_llm_call_built_when_model_available(
        self, patched_sandbox, patched_self_branch
    ):
        """No injected llm_call + a scheduler model -> a real (non-None) call is built and used,
        instead of the heuristic (near-noise) fallback the runner used before."""
        harness = FakeHarness(
            {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}
        )
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            harness,
            EloTournament(),
            FakeScheduler("chat"),
            _noop_patch,
        )
        await cycle.run(_genome("baseline"), _genome("candidate"), ["chat"])
        assert len(harness.received_llm_calls) == 2
        assert all(c is not None for c in harness.received_llm_calls)

    @pytest.mark.asyncio
    async def test_no_model_leaves_scoring_heuristic(self, patched_sandbox, patched_self_branch):
        """If the scheduler yields no model, llm_call stays None (explicit heuristic fallback)."""
        harness = FakeHarness(
            {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}
        )
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            harness,
            EloTournament(),
            FakeScheduler(None),
            _noop_patch,
        )
        await cycle.run(_genome("baseline"), _genome("candidate"), [])
        assert harness.received_llm_calls == [None, None]

    @pytest.mark.asyncio
    async def test_sandbox_destroyed_even_when_apply_patch_raises(
        self, patched_sandbox, monkeypatch
    ):
        """runner-5: the sandbox is torn down even when the cycle fails mid-way."""
        scores = {"baseline": {"proxy_swebench": 0.5}, "candidate": {"proxy_swebench": 0.5}}

        async def boom_patch(sandbox, workspace, model=None):
            raise RuntimeError("agent crashed mid-patch")

        async def attempt_that_runs_the_patch(
            sandbox,
            workspace,
            attempt,
            apply_patch,
            open_pr=False,
            quarantine_check=None,
            model=None,
            probe=None,
        ):
            await apply_patch(sandbox, workspace, model)
            raise AssertionError("apply_patch should have raised before this point")

        monkeypatch.setattr(
            "maistro_rsi.runner.run_self_branch_attempt", attempt_that_runs_the_patch
        )

        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            FakeHarness(scores),
            EloTournament(),
            FakeScheduler(),
            boom_patch,
        )

        with pytest.raises(RuntimeError):
            await cycle.run(_genome("baseline"), _genome("candidate"), ["openai/gpt-5"])

        assert patched_sandbox["sandbox"].destroyed is True


class SpyHarness(FakeHarness):
    """FakeHarness that also records every evaluate_genome invocation."""

    def __init__(self, scores):
        super().__init__(scores)
        self.calls: list[dict] = []

    async def evaluate_genome(self, genome, benchmarks=None, llm_call=None):
        self.calls.append({"genome": genome, "llm_call": llm_call})
        return await super().evaluate_genome(genome, benchmarks=benchmarks, llm_call=llm_call)


class TestModelAndLlmCallThreading:
    """The quota-burn pick and the llm_call must actually reach the work —
    without these, scheduling is reporting-only and 'real' benchmarks silently
    score by heuristic."""

    @pytest.mark.asyncio
    async def test_scheduler_model_reaches_apply_patch(self, patched_sandbox, patched_self_branch):
        """The quota-burn pick must reach the patching agent via ApplyPatchFn's
        third argument (scoring gets it separately: run() bakes it into the
        gateway-built llm_call)."""
        scores = {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}
        seen_models: list[str | None] = []

        async def recording_patch(sandbox, workspace, model=None):
            seen_models.append(model)

        harness = SpyHarness(scores)
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            harness,
            EloTournament(),
            FakeScheduler(model="groq/kimi-k2"),
            recording_patch,
        )
        result = await cycle.run(_genome("baseline"), _genome("candidate"), ["groq/kimi-k2"])

        assert seen_models == ["groq/kimi-k2"]
        assert result.model_used == "groq/kimi-k2"

    @pytest.mark.asyncio
    async def test_usage_recorded_to_scheduler_after_cycle(
        self, patched_sandbox, patched_self_branch
    ):
        """Quota-burn loop closure: cumulative usage on the llm_call is recorded
        via scheduler.record_attempt after the cycle."""
        scores = {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}

        async def fake_llm(messages, **kwargs):
            return "text"

        fake_llm.usage_input = 120
        fake_llm.usage_output = 45

        recorded: list[tuple] = []

        class RecordingScheduler(FakeScheduler):
            async def record_attempt(self, model, input_tokens, output_tokens):
                recorded.append((model, input_tokens, output_tokens))

        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            SpyHarness(scores),
            EloTournament(),
            RecordingScheduler(model="groq/kimi-k2"),
            _noop_patch,
            llm_call=fake_llm,
        )
        await cycle.run(_genome("baseline"), _genome("candidate"), ["groq/kimi-k2"])
        assert recorded == [("groq/kimi-k2", 120, 45)]

    @pytest.mark.asyncio
    async def test_llm_call_reaches_evaluate_genome(self, patched_sandbox, patched_self_branch):
        scores = {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}

        async def fake_llm(messages, **kwargs):
            return "text"

        harness = SpyHarness(scores)
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            harness,
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
            llm_call=fake_llm,
        )
        await cycle.run(_genome("baseline"), _genome("candidate"), ["openai/gpt-5"])

        assert len(harness.calls) == 2
        assert all(c["llm_call"] is fake_llm for c in harness.calls)


class TestWorkspaceCleanup:
    @pytest.mark.asyncio
    async def test_workspace_removed_by_default_and_kept_on_flag(
        self, patched_sandbox, patched_self_branch, tmp_path, monkeypatch
    ):
        scores = {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}
        removed: list[str] = []
        monkeypatch.setattr(
            "maistro_rsi.runner.shutil.rmtree",
            lambda path, ignore_errors=False: removed.append(str(path)),
        )

        base = _config(benchmarks=["proxy_swebench"], workspace_root=str(tmp_path))
        cycle = RsiCycle(base, FakeHarness(scores), EloTournament(), FakeScheduler(), _noop_patch)
        result = await cycle.run(_genome("baseline"), _genome("candidate"), ["m"])
        assert removed == [f"{tmp_path}/{result.run_id}"]

        removed.clear()
        keep = _config(
            benchmarks=["proxy_swebench"], workspace_root=str(tmp_path), keep_workspace=True
        )
        cycle2 = RsiCycle(keep, FakeHarness(scores), EloTournament(), FakeScheduler(), _noop_patch)
        await cycle2.run(_genome("baseline"), _genome("candidate"), ["m"])
        assert removed == []


class TestQuarantineThreading:
    @pytest.mark.asyncio
    async def test_quarantine_check_reaches_run_self_branch_attempt(
        self, patched_sandbox, monkeypatch
    ):
        scores = {"baseline": {"proxy_swebench": 0.4}, "candidate": {"proxy_swebench": 0.6}}
        received: dict = {}

        async def capturing_attempt(
            sandbox,
            workspace,
            attempt,
            apply_patch,
            open_pr=False,
            quarantine_check=None,
            model=None,
            probe=None,
        ):
            received["quarantine_check"] = quarantine_check
            return SelfBranchResult(
                attempt=attempt, test_exit_code=0, test_output="ok", diff="diff"
            )

        monkeypatch.setattr("maistro_rsi.runner.run_self_branch_attempt", capturing_attempt)

        async def my_check(diff, paths):
            raise AssertionError("not called in this test")

        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"]),
            FakeHarness(scores),
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
            quarantine_check=my_check,
        )
        await cycle.run(_genome("baseline"), _genome("candidate"), ["m"])
        assert received["quarantine_check"] is my_check


class TestProbeFromCommands:
    """Tests tied to SPEC.md §5 differential-scoring ACs (probe_from_commands /
    _parse_probe_score, and RsiCycle._score preferring probe metrics)."""

    def test_parse_probe_score_parses_last_line_as_float(self):
        from maistro_rsi.runner import _parse_probe_score

        assert _parse_probe_score(0, "some output\n87.5\n") == 87.5

    def test_parse_probe_score_falls_back_to_exit_code_on_unparseable_output(self):
        from maistro_rsi.runner import _parse_probe_score

        assert _parse_probe_score(0, "not a number") == 1.0
        assert _parse_probe_score(1, "not a number") == 0.0

    def test_parse_probe_score_falls_back_to_exit_code_on_empty_output(self):
        from maistro_rsi.runner import _parse_probe_score

        assert _parse_probe_score(0, "   \n  \n") == 1.0
        assert _parse_probe_score(2, "") == 0.0

    @pytest.mark.asyncio
    async def test_probe_from_commands_runs_each_command_and_scores_it(self):
        from maistro_rsi.runner import probe_from_commands

        class _Sandbox:
            def __init__(self):
                self.calls: list[tuple[str, int]] = []

            async def exec(self, command, timeout=60):
                self.calls.append((command, timeout))
                if command == "lint":
                    return 0, "1.0"
                return 1, "boom"

        sandbox = _Sandbox()
        probe = probe_from_commands({"lint": "lint", "tests": "tests"}, timeout=42)
        scores = await probe(sandbox, "/ws")

        assert scores == {"lint": 1.0, "tests": 0.0}
        assert sandbox.calls == [("lint", 42), ("tests", 42)]

    @pytest.mark.asyncio
    async def test_cycle_prefers_probe_metrics_over_stock_benchmarks(
        self, patched_sandbox, patched_self_branch, monkeypatch
    ):
        """When benchmark_commands are configured, the tournament battles over
        the differential probe metrics, not the stock genome harness."""

        async def fake_run_attempt(
            sandbox,
            workspace,
            attempt,
            apply_patch,
            open_pr=False,
            quarantine_check=None,
            model=None,
            probe=None,
        ):
            assert probe is not None  # a probe was actually built and passed through
            return SelfBranchResult(
                attempt=attempt,
                test_exit_code=0,
                test_output="ok",
                diff="diff",
                baseline_metrics={"lint": 0.2},
                candidate_metrics={"lint": 0.9},
            )

        monkeypatch.setattr("maistro_rsi.runner.run_self_branch_attempt", fake_run_attempt)

        harness = FakeHarness(
            {"baseline": {"proxy_swebench": 0.9}, "candidate": {"proxy_swebench": 0.1}}
        )
        cycle = RsiCycle(
            _config(benchmarks=["proxy_swebench"], benchmark_commands={"lint": "ruff check ."}),
            harness,
            EloTournament(),
            FakeScheduler(),
            _noop_patch,
        )

        result = await cycle.run(_genome("baseline"), _genome("candidate"), ["m"])

        # probe metrics (candidate wins) drive the outcome, not the stock
        # harness scores (which would have favored the baseline instead).
        assert {r.benchmark for r in result.baseline_results} == {"lint"}
        assert result.benchmarks_won == 1
        # the stock harness was never consulted when probe metrics exist
        assert harness.received_llm_calls == []
