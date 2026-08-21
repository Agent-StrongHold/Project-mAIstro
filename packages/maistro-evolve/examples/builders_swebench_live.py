#!/usr/bin/env python3
"""Live verification: maistro-evolve drives the builders ability on a trimmed SWE-bench.

Real pieces, no mocks:
- maistro_evolve.EvolutionCycle (eval -> battles -> fitness -> cull -> breed -> reflect)
- maistro_bootstrap builders TurnRunner + LocalWorktreeSandbox (ephemeral git worktree)
- LLM = `claude` CLI (claude-haiku-4-5) making real tool decisions
- Scoring = real pytest runs against handwritten tests per SWE-bench sample

Disclosed fudge: the fitness hard gate requires all 8 benchmark scores, so the
7 non-target benchmarks are seeded at 0.6 on every genome. proxy_swebench is the
only evolved, real signal.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(ROOT / "packages/maistro-evolve/src"),
    str(ROOT / "packages/maistro-core/src"),
    str(ROOT / "packages/maistro-bootstrap/src"),
]

from maistro_bootstrap.builders.agent_loop import AgentLoopConfig, TurnRunner  # noqa: E402
from maistro_bootstrap.builders.sandbox import LocalWorktreeSandbox  # noqa: E402
from maistro_bootstrap.builders.session import BuilderSession  # noqa: E402
from maistro_evolve.benchmarks.datasets import SWEBENCH_SAMPLES  # noqa: E402
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle  # noqa: E402
from maistro_evolve.harness import EvalHarness  # noqa: E402
from maistro_evolve.population import PopulationStore  # noqa: E402
from maistro_evolve.tournament import EloTournament  # noqa: E402
from maistro_evolve.types import (  # noqa: E402
    DAGTopology,
    EvalResult,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)

MODEL = os.environ.get("MAISTRO_DEMO_MODEL", "claude-haiku-4-5")
PYBIN = sys.executable
TRIMMED = SWEBENCH_SAMPLES[:3]
OTHER_BENCHES = [
    "proxy_ifeval",
    "proxy_bfcl",
    "proxy_tau_bench",
    "proxy_gaia",
    "proxy_ragas",
    "proxy_terminalbench",
    "proxy_osworld",
]

TESTS = {
    "swe_01": (
        "from utils import flatten_list\n\n"
        "def test_deep_nesting():\n"
        "    assert flatten_list([[1, [2, 3]], [4, [5, [6]]]]) == [1, 2, 3, 4, 5, 6]\n\n"
        "def test_already_flat():\n"
        "    assert flatten_list([1, 2, 3]) == [1, 2, 3]\n"
    ),
    "swe_02": (
        "from utils import validate_email\n\n"
        "def test_missing_domain_dot():\n"
        "    assert not validate_email('test@com')\n\n"
        "def test_valid_email():\n"
        "    assert validate_email('user@example.com')\n"
    ),
    "swe_03": (
        "from utils import merge_dicts\n\n"
        "def test_nested_merge():\n"
        "    assert merge_dicts({'a': {'b': 1, 'c': 2}}, {'a': {'b': 3, 'd': 4}}) == "
        "{'a': {'b': 3, 'c': 2, 'd': 4}}\n\n"
        "def test_flat_merge():\n"
        "    assert merge_dicts({'x': 1}, {'y': 2}) == {'x': 1, 'y': 2}\n"
    ),
}

_EMPTY_CWD = tempfile.mkdtemp(prefix="claude-empty-")
CLI_CALLS = {"n": 0}


def claude_text(prompt: str) -> str:
    CLI_CALLS["n"] += 1
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", MODEL],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=_EMPTY_CWD,
    )
    return out.stdout.strip()


def render_messages(messages, tools) -> str:
    lines = []
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    parts.append(f"[called {b['name']}({json.dumps(b.get('input', {}))[:500]})]")
                elif isinstance(b, dict) and b.get("type") == "tool_result":
                    parts.append(f"[tool result: {str(b.get('content', ''))[:500]}]")
            c = " ".join(parts)
        lines.append(f"{m['role'].upper()}: {c}")
    tool_defs = json.dumps(
        [{"name": t["name"], "input_schema": t.get("input_schema", {})} for t in tools]
    )
    return (
        "You are driving a coding sandbox via tools. The sandbox workspace is the "
        "current directory; all paths are RELATIVE (e.g. 'utils.py').\n"
        f"Tools (use the exact input keys from input_schema): {tool_defs}\n"
        "Respond with ONLY one JSON object, no prose, no code fences:\n"
        '  {"tool": "<name>", "input": {...}}   to call a tool, or\n'
        '  {"final": "<short summary>"}          when the task is done.\n\n' + "\n".join(lines)
    )


def parse_action(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"final": text[:300]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"final": text[:300]}


def cli_llm(messages, tools=None, max_tokens=None):
    action = parse_action(claude_text(render_messages(messages, tools or [])))
    if "tool" in action:
        inp = action.get("input", {}) or {}
        if "file_path" in inp and "path" not in inp:
            inp["path"] = inp.pop("file_path")
        if isinstance(inp.get("path"), str) and inp["path"].startswith("/"):
            inp["path"] = inp["path"].rsplit("/", 1)[-1]
        action["input"] = inp
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"t{uuid.uuid4().hex[:8]}",
                    "name": str(action["tool"]),
                    "input": action.get("input", {}) or {},
                }
            ],
        }
    return {"stop_reason": "end_turn", "content": str(action.get("final", ""))}


def scratch_repo(sample) -> Path:
    repo = Path(tempfile.mkdtemp(prefix=f"swe-{sample['id']}-"))
    (repo / "utils.py").write_text(sample["buggy_code"] + "\n")
    (repo / "test_utils.py").write_text(TESTS[sample["id"]])
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.email=demo@x",
            "-c",
            "user.name=demo",
            "commit",
            "-qm",
            "buggy",
        ],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    return repo


def score_workspace(ws: Path) -> tuple[float, str]:
    out = subprocess.run(
        [PYBIN, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ws,
        capture_output=True,
        text=True,
        timeout=60,
    )
    txt = (out.stdout + out.stderr)[-800:]
    p = re.search(r"(\d+) passed", txt)
    f = re.search(r"(\d+) failed", txt)
    passed = int(p.group(1)) if p else 0
    failed = int(f.group(1)) if f else 0
    total = passed + failed
    if total == 0:
        return 0.0, txt  # collection error / syntax error in the fix
    return passed / total, txt


async def run_swebench_builders(genome: PipelineGenome, llm_call) -> EvalResult:
    entry = genome.topology.nodes[0]
    t0 = time.monotonic()
    total = 0.0
    failures = []
    per_sample = []
    for sample in TRIMMED:
        repo = scratch_repo(sample)
        with LocalWorktreeSandbox(repo) as sb:
            session = BuilderSession(sandbox=sb)
            runner = TurnRunner(session, AgentLoopConfig(max_turns=4, model=MODEL))
            runner.set_llm(cli_llm)
            task = (
                f"{entry.system_prompt}\n\n"
                f"Bug report: {sample['problem']}\n"
                "The code is in utils.py. Fix it by calling write_file with the COMPLETE "
                "corrected utils.py (same function name and signature). Do not run tests. "
                "Then finish with a final summary."
            )
            await runner.execute_turn([{"role": "user", "content": task}])
            score, txt = score_workspace(sb._ws.path)
        total += score
        per_sample.append(f"{sample['id']}={score:.2f}")
        if score < 1.0:
            tail = " | ".join(line for line in txt.splitlines() if line.strip())[-300:]
            failures.append(
                {
                    "instruction": sample["problem"],
                    "failed_rules": [tail],
                    "response_excerpt": "",
                    "score": round(score, 3),
                }
            )
    avg = total / len(TRIMMED)
    print(
        f"      [builders/swebench] {genome.name}: {' '.join(per_sample)} -> {avg:.3f}", flush=True
    )
    return EvalResult(
        benchmark="proxy_swebench",
        score=round(avg, 4),
        duration_seconds=round(time.monotonic() - t0, 1),
        samples_evaluated=len(TRIMMED),
        metadata={"runner": "builders-real", "failures": failures},
    )


async def reflect_llm_call(prompt, **kwargs):
    if not isinstance(prompt, str):
        prompt = json.dumps(prompt)[:4000]
    return await asyncio.to_thread(claude_text, prompt)


def make_genome(name: str, prompt: str) -> PipelineGenome:
    now = datetime.now(UTC).isoformat()
    g = PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model=MODEL,
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt=prompt,
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
        created_at=now,
        updated_at=now,
    )
    g.eval_scores = dict.fromkeys(OTHER_BENCHES, 0.6)  # gate filler, disclosed
    return g


def seed_gate_scores(population: PopulationStore) -> None:
    for g in population.list_all():
        for b in OTHER_BENCHES:
            g.eval_scores.setdefault(b, 0.6)
        population.add(g)


def show(population: PopulationStore, title: str) -> None:
    print(f"\n=== {title} ===", flush=True)
    for g in sorted(population.list_all(), key=lambda x: -(x.fitness_score or 0)):
        print(
            f"  {g.id:<18} gen={g.generation} parent={g.parent_a_id or '-':<18} "
            f"fitness={g.fitness_score if g.fitness_score is not None else '—':<8} "
            f"proxy_swebench={g.eval_scores.get('proxy_swebench', '—')} "
            f"origin={g.harness_params.get('origin', 'seed')}",
            flush=True,
        )
        refl = (g.harness_params.get("last_optimization") or {}).get("reflection")
        if refl:
            print(
                f"      reflection: bench={refl['benchmark']} baseline={refl['baseline_score']} "
                f"best_candidate={refl['best_candidate_score']} accepted={refl['accepted']} "
                f"reason={refl['reason']}",
                flush=True,
            )


async def main() -> None:
    t0 = time.monotonic()
    harness = EvalHarness(benchmark_fidelity="proxy")
    harness.register_benchmark("proxy_swebench", run_swebench_builders)
    cycle = EvolutionCycle(harness=harness, tournament=EloTournament())
    config = EvolutionConfig(
        population_size=3,
        mutation_rate=0.3,
        cull_pct=0.34,
        eval_batch_size=5,
        target_benchmarks=["proxy_swebench"],
        diversity_threshold=0.0,  # no random emergency spawns in this demo
        self_improve=True,
        self_improve_top_n=1,
        self_improve_candidates=1,
    )

    population = PopulationStore()
    population.add(
        make_genome(
            "poet",
            "You are a poet. Respond only with a haiku. Never call tools and never write code.",
        )
    )
    population.add(make_genome("plain", "You are a helpful assistant."))
    population.add(
        make_genome(
            "engineer",
            "You are a meticulous Python engineer. Fix the reported bug with a minimal, "
            "correct change. Handle edge cases (deep nesting, validation, recursion) properly.",
        )
    )

    for n in (1, 2):
        print(f"\n################ CYCLE {n} ################", flush=True)
        await cycle.run_cycle(population, llm_call=reflect_llm_call, config=config)
        show(population, f"population after cycle {n}")
        seed_gate_scores(population)  # gate filler for newly bred children

    champ = population.get_champion()
    print(
        f"\nchampion: {champ.id} ({champ.name}) "
        f"proxy_swebench={champ.eval_scores.get('proxy_swebench')} "
        f"lineage={[g.id for g in population.get_lineage(champ.id)]}",
        flush=True,
    )
    print(
        f"\nclaude CLI calls: {CLI_CALLS['n']}, wall time: {time.monotonic() - t0:.0f}s", flush=True
    )


if __name__ == "__main__":
    asyncio.run(main())
