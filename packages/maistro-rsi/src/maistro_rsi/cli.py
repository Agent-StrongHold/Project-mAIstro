"""`maistro-rsi` console script — run one end-to-end RSI cycle from the shell.

Wires the pieces `RsiCycle` composes (harness, tournament, quota scheduler,
apply_patch) into a single command so an operator (or an sbx kit) can run:

    maistro-rsi run --repo-url https://github.com/org/repo \\
        --goal "improve X" --test-command "pytest -q"

without hand-writing the wiring in `runner.py`'s docstring/tests each time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

from maistro.observability.logging import configure_logging
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome
from maistro_rsi.local_loop import make_builders_apply_patch
from maistro_rsi.quota_burn import QuotaBurnScheduler, discover_models
from maistro_rsi.runner import DEFAULT_WORKSPACE_ROOT, RsiCycle, RsiCycleConfig, build_harness
from maistro_rsi.selfbranch import QuarantineCheckFn

# Priority order for each canonical value: the first alias that's set wins.
# builders reads LITELLM_URL/LITELLM_MASTER_KEY; evolve reads LITELLM_BASE_URL/
# LITELLM_API_KEY/LITELLM_VIRTUAL_KEY; LiteLLMSettings (used by discover_models)
# reads LITELLM_BASE_URL/LITELLM_MASTER_KEY. Normalizing all aliases to the same
# value means whichever chain a given piece of code happens to read, it sees
# the same gateway.
_BASE_URL_ALIASES = ("LITELLM_BASE_URL", "LITELLM_URL", "LITELLM_PROXY_URL")
_API_KEY_ALIASES = (
    "LITELLM_MASTER_KEY",
    "LITELLM_PROXY_KEY",
    "LITELLM_API_KEY",
    "LITELLM_VIRTUAL_KEY",
)


def normalize_litellm_env() -> tuple[str | None, str | None]:
    """Read the LiteLLM base URL + key from whichever alias is set, strip a
    trailing /v1 (builders posts {base}/v1/..., evolve posts {base}/...), and
    write the normalized values back to every alias so every consumer agrees.

    Returns (base_url, api_key), either of which may be None if unconfigured.
    """
    base_url: str | None = None
    for name in _BASE_URL_ALIASES:
        value = os.environ.get(name)
        if value:
            base_url = value.rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[: -len("/v1")]
            break

    api_key: str | None = None
    for name in _API_KEY_ALIASES:
        value = os.environ.get(name)
        if value:
            api_key = value
            break

    if base_url:
        for name in _BASE_URL_ALIASES:
            os.environ[name] = base_url
    if api_key:
        for name in _API_KEY_ALIASES:
            os.environ[name] = api_key

    return base_url, api_key


def _default_genome(genome_id: str, name: str) -> PipelineGenome:
    """A minimal single-node genome — RSI scores baseline vs. candidate on the
    same benchmark suite; the topology itself isn't what's under test here,
    the self-modified codebase is."""
    now = datetime.now(UTC).isoformat()
    return PipelineGenome(
        id=genome_id,
        name=name,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt=f"{name} agent",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maistro-rsi")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run one end-to-end RSI cycle")
    run.add_argument("--repo-url", required=True, help="Git URL of the target codebase")
    run.add_argument("--goal", required=True, help="Task description for the patching agent")
    run.add_argument(
        "--test-command", required=True, help="Command run inside the sandbox to score the attempt"
    )
    run.add_argument("--base-branch", default="main")
    run.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)
    run.add_argument(
        "--benchmarks",
        nargs="*",
        default=None,
        help="Override the default benchmark set "
        "(default: proxy_swebench, proxy_swebench_pro, proxy_terminalbench)",
    )
    run.add_argument(
        "--open-prs", action="store_true", help="Push and open a PR if the attempt passes"
    )
    run.add_argument("--model", default=None, help="Force a specific model for the patching agent")
    run.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Candidate model pool for quota-burn scheduling (default: discover from LiteLLM)",
    )
    run.add_argument(
        "--max-turns", type=int, default=10, help="Max agent turns before the attempt fails"
    )
    run.add_argument(
        "--allow-stub-llm",
        action="store_true",
        help="Proceed even if LITELLM_* is unconfigured (the agent then gets stub responses)",
    )
    run.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep the cloned workspace after the cycle instead of deleting it (debugging)",
    )
    run.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary")

    return parser


def _build_quarantine_check() -> QuarantineCheckFn:
    """Warden-backed QuarantineCheckFn for gating PRs.

    Only needed when --open-prs is set: nothing self-modified may leave the
    sandbox unscanned. Warden's layers 1-2.5 need no LLM, so this constructs
    with no configuration.
    """
    from maistro.security.warden.detector import Warden
    from maistro_rsi.quarantine import QuarantineVerdict, quarantine_scan

    warden = Warden()

    async def check(diff: str, touched_paths: list[str]) -> QuarantineVerdict:
        return await quarantine_scan(diff, touched_paths, warden)

    return check


async def _resolve_models(args: argparse.Namespace) -> list[str] | None:
    """Model pool from --models or LiteLLM discovery; None means exit 2."""
    if args.models is not None:
        return list(args.models)
    try:
        return await discover_models()
    except Exception as exc:
        if args.allow_stub_llm:
            return []
        print(f"error: could not discover models from LiteLLM: {exc}", file=sys.stderr)
        return None


def _build_config(args: argparse.Namespace) -> RsiCycleConfig:
    config_kwargs: dict[str, object] = {
        "repo_url": args.repo_url,
        "test_command": args.test_command,
        "workspace_root": args.workspace_root,
        "base_branch": args.base_branch,
        "open_prs": args.open_prs,
        "keep_workspace": args.keep_workspace,
    }
    if args.benchmarks:
        config_kwargs["benchmarks"] = args.benchmarks
    return RsiCycleConfig(**config_kwargs)  # type: ignore[arg-type]


def _print_summary(summary: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(summary))
        return
    print(f"run_id:          {summary['run_id']}")
    print(f"model_used:      {summary['model_used']}")
    print(f"tests_passed:    {summary['tests_passed']}")
    print(f"benchmarks_won:  {summary['benchmarks_won']}/{summary['benchmarks_total']}")
    print(f"improved:        {summary['improved']}")
    if summary["pr_url"]:
        print(f"pr_url:          {summary['pr_url']}")
    if summary["error"]:
        print(f"error:           {summary['error']}")


async def _run(args: argparse.Namespace) -> int:
    base_url, api_key = normalize_litellm_env()
    if not (base_url and api_key) and not args.allow_stub_llm:
        print(
            "error: LiteLLM is not configured — set LITELLM_BASE_URL and one of "
            "LITELLM_MASTER_KEY/LITELLM_API_KEY/LITELLM_VIRTUAL_KEY, or pass "
            "--allow-stub-llm to proceed with stub agent responses.",
            file=sys.stderr,
        )
        return 2

    models = await _resolve_models(args)
    if models is None:
        return 2

    config = _build_config(args)
    harness = build_harness(benchmark_fidelity="proxy")
    tournament = EloTournament()
    scheduler = QuotaBurnScheduler(InMemoryQuotaTracker())
    apply_patch = make_builders_apply_patch(
        args.goal, model=args.model, max_agent_turns=args.max_turns
    )

    # PRs never leave the sandbox unscanned: quarantine is mandatory for
    # --open-prs, and failure to construct it refuses the run (fail closed)
    # rather than silently opening unscanned PRs.
    quarantine_check = None
    if args.open_prs:
        try:
            quarantine_check = _build_quarantine_check()
        except Exception as exc:
            print(
                f"error: --open-prs requires the quarantine gate, but it could not "
                f"be constructed: {exc}",
                file=sys.stderr,
            )
            return 2

    cycle = RsiCycle(
        config,
        harness,
        tournament,
        scheduler,
        apply_patch,
        quarantine_check=quarantine_check,
    )
    baseline = _default_genome("baseline", "baseline")
    candidate = _default_genome("candidate", "candidate")
    result = await cycle.run(baseline, candidate, models)

    _print_summary(
        {
            "run_id": result.run_id,
            "model_used": result.model_used,
            "tests_passed": result.branch_result.tests_passed,
            "benchmarks_won": result.benchmarks_won,
            "benchmarks_total": len(result.battles),
            "improved": result.improved,
            "pr_url": result.branch_result.pr_url,
            "error": result.branch_result.error,
        },
        args.json,
    )

    return 0 if result.branch_result.tests_passed else 1


def main(argv: list[str] | None = None) -> int:
    # structlog is unconfigured by default and prints to stdout, which would
    # interleave log lines with --json's machine-readable summary. Route
    # logging to stderr so stdout only ever carries the CLI's own output.
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return asyncio.run(_run(args))
    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable — parser.error() exits


if __name__ == "__main__":
    sys.exit(main())
