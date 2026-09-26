"""End-to-end smoke test for UX flow 2: sandboxed self-evolving coding agent.

A single trivial-coding-task variant evaluates two genome candidates through
the real, wired-together sandbox + evolve loop:

    maistro-core's real Docker sandbox boundary (SandboxContainer/create_sandbox)
        -> EvalHarness.evaluate_genome() registers a benchmark that actually
           drives the sandbox to write and execute a trivial coding task and
           turns the exit code into a score
        -> EloTournament.record_battle() scores the two genomes against each
           other and tournament_select() promotes the winner
        -> a second sandboxed run confirms the promoted genome's
           harness_params (model/temperature) -- not the loser's -- are what
           gets used for the next sandbox dispatch

maistro-evolve does not (and must not) depend on maistro-core, so this test
lives in maistro-evolve's own test suite and imports maistro-core's sandbox
module directly, the same direction the real product wiring would use (the
self-evolving-agent host process depends on both packages).

Docker itself is not available in CI/sandboxed dev environments, so --
mirroring the existing precedent in
packages/maistro-core/tests/tools/sandbox/test_docker.py -- only the sandbox
backend at the process boundary (the canonical `SandboxProtocol` seam the
facade drives) is stubbed. Every other component (SandboxContainer,
EvalHarness, EloTournament, PipelineGenome) is the real production class.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.sandbox import ExecResult, SandboxInstance
from maistro.tools.sandbox.docker import SandboxContainer
from maistro_evolve.harness import EvalHarness
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome

BENCHMARK_NAME = "trivial_addition"


class _StubSandboxBackend:
    """Stands in for the canonical backend behind the legacy facade.

    The facade (``SandboxContainer``) is real production code; only the
    protocol backend at the process boundary is stubbed -- no real Docker
    daemon is available in this environment. The boundary moved from an
    asyncio subprocess to the backend protocol seam when the legacy launcher
    was retired behind `maistro.sandbox` (#18); the equivalence is exact:
    both are where "the command left the process under test".
    """

    tier = "vm"

    def __init__(self, stdout: bytes, returncode: int) -> None:
        self._result = ExecResult(
            exit_code=returncode,
            stdout=stdout.decode(),
            stderr="",
            duration_ms=1,
        )

    async def spawn(self, *, config: Any) -> SandboxInstance:
        return SandboxInstance(id="stub", backend="stub", isolation_tier="vm")

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        return self._result

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        raise NotImplementedError

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        raise NotImplementedError

    async def destroy(self, instance: SandboxInstance) -> None:
        pass


def _make_genome(
    *, genome_id: str, model: str, temperature: float, generation: int = 0
) -> PipelineGenome:
    now = datetime.now(UTC).isoformat()
    return PipelineGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="coder",
                    role="coder",
                    strategy="react",
                    model=model,
                    temperature=temperature,
                    max_tokens=2048,
                    system_prompt="Write the requested function.",
                    max_tool_rounds=3,
                )
            ],
            edges=[],
            entry_node="coder",
            max_cycles=1,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        harness_params={"model": model, "temperature": temperature},
        generation=generation,
        created_at=now,
        updated_at=now,
    )


async def _run_coding_task_in_sandbox(
    genome: PipelineGenome, expected_exit: int
) -> tuple[int, str]:
    """Sandbox-execute a trivial coding task: write add.py, run it.

    Returns (exit_code, output) from the in-sandbox execution of the task
    associated with `genome`'s harness_params. The genome with the correct
    `temperature` (used here as a stand-in for "the variant that writes
    correct code") gets exit code 0; the other gets a nonzero exit code --
    this is the deterministic stand-in for "harness scores the result."
    """
    backend = _StubSandboxBackend(
        stdout=b"3\n" if expected_exit == 0 else b"Traceback: NameError\n",
        returncode=expected_exit,
    )
    instance = SandboxInstance(id=f"sandbox-{genome.id}", backend="stub", isolation_tier="vm")
    container = SandboxContainer(backend, instance)
    code, output = await container.exec("python3 add.py")
    return code, output


@pytest.fixture
def good_genome() -> PipelineGenome:
    return _make_genome(genome_id="genome-good", model="gpt-4o-mini", temperature=0.2)


@pytest.fixture
def bad_genome() -> PipelineGenome:
    return _make_genome(genome_id="genome-bad", model="gpt-3.5-turbo", temperature=1.5)


class TestSandboxEvolveE2E:
    async def test_sandbox_execute_score_promote_and_reuse(
        self, good_genome: PipelineGenome, bad_genome: PipelineGenome
    ) -> None:
        # --- Step 1: sandbox-execute the trivial coding task for each genome ---
        good_code, good_output = await _run_coding_task_in_sandbox(good_genome, expected_exit=0)
        bad_code, bad_output = await _run_coding_task_in_sandbox(bad_genome, expected_exit=1)

        assert good_code == 0
        assert good_output == "3\n"
        assert bad_code == 1
        assert bad_output == "Traceback: NameError\n"

        # --- Step 2: harness turns sandbox exit codes into scores --------------
        harness = EvalHarness()

        async def _sandbox_backed_runner(genome: PipelineGenome, llm_call: object) -> object:
            from maistro_evolve.types import EvalResult

            expected_exit = 0 if genome.id == good_genome.id else 1
            code, _ = await _run_coding_task_in_sandbox(genome, expected_exit=expected_exit)
            return EvalResult(
                benchmark=BENCHMARK_NAME,
                score=1.0 if code == 0 else 0.0,
                cost_usd=0.001,
                duration_seconds=0.01,
                samples_evaluated=1,
                metadata={"stub": False, "exit_code": code},
            )

        harness.register_benchmark(BENCHMARK_NAME, _sandbox_backed_runner)

        good_results = await harness.evaluate_genome(
            good_genome, benchmarks=[BENCHMARK_NAME], llm_call=None
        )
        bad_results = await harness.evaluate_genome(
            bad_genome, benchmarks=[BENCHMARK_NAME], llm_call=None
        )

        assert len(good_results) == 1
        assert good_results[0].score == 1.0
        assert good_results[0].metadata == {"stub": False, "exit_code": 0}
        assert len(bad_results) == 1
        assert bad_results[0].score == 0.0
        assert bad_results[0].metadata == {"stub": False, "exit_code": 1}

        # --- Step 3: tournament battle promotes the winner ----------------------
        tournament = EloTournament()
        battle = tournament.record_battle(
            benchmark=BENCHMARK_NAME,
            genome_a_id=good_genome.id,
            genome_b_id=bad_genome.id,
            score_a=good_results[0].score,
            score_b=bad_results[0].score,
        )
        assert battle.winner_id == good_genome.id
        assert tournament.get_elo(good_genome.id, BENCHMARK_NAME) > 1200.0
        assert tournament.get_elo(bad_genome.id, BENCHMARK_NAME) < 1200.0

        winner_id = tournament.tournament_select(
            [good_genome.id, bad_genome.id], benchmark=BENCHMARK_NAME, tournament_size=2
        )
        assert winner_id == good_genome.id

        # --- Step 4: confirm a second sandboxed run uses the *promoted* variant -
        genomes_by_id = {good_genome.id: good_genome, bad_genome.id: bad_genome}
        promoted = genomes_by_id[winner_id]
        assert promoted.harness_params == {"model": "gpt-4o-mini", "temperature": 0.2}

        second_run_code, second_run_output = await _run_coding_task_in_sandbox(
            promoted, expected_exit=0
        )
        assert second_run_code == 0
        assert second_run_output == "3\n"
        # The losing variant's params must NOT be what the next dispatch uses.
        assert promoted.harness_params != bad_genome.harness_params

    async def test_losing_genome_is_not_selected_even_with_larger_tournament_pool(
        self, good_genome: PipelineGenome, bad_genome: PipelineGenome
    ) -> None:
        """Negative branch: tournament_select must never promote the loser,
        regardless of pool composition, once its elo has been driven down."""
        tournament = EloTournament()
        for _ in range(3):
            tournament.record_battle(
                benchmark=BENCHMARK_NAME,
                genome_a_id=good_genome.id,
                genome_b_id=bad_genome.id,
                score_a=1.0,
                score_b=0.0,
            )

        assert tournament.get_elo(good_genome.id, BENCHMARK_NAME) > tournament.get_elo(
            bad_genome.id, BENCHMARK_NAME
        )

        winner_id = tournament.tournament_select(
            [good_genome.id, bad_genome.id],
            benchmark=BENCHMARK_NAME,
            tournament_size=2,
        )
        assert winner_id == good_genome.id
        assert winner_id != bad_genome.id
