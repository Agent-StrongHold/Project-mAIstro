"""`python -m maistro_rsi` — run a safe, capped, local self-improvement loop.

Drives the native builders agent (the engine behind `maistro builders`) to
propose improvements to a *clone* of a repo, gates each on the repo's own test
command, and ratchets forward only the ones that pass. Nothing is pushed and
the source checkout is never touched.

Example:
    python -m maistro_rsi run \\
        --repo C:/maistro \\
        --test-cmd "python -m pytest packages/maistro-core/tests -q" \\
        --cycles 3
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from maistro_rsi.competitors import parse_competitors
from maistro_rsi.export_policy import (
    CANONICAL_DEVELOPMENT_BRANCH,
    ExportPolicyError,
    resolve_export_path,
    resolve_pr_base,
    validate_patch,
)
from maistro_rsi.free_router import FREE_ROUTER_ALIASES, expand_free_router, make_free_selector
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop

if TYPE_CHECKING:
    from maistro_rsi.harvest import PromotedPatch


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maistro_rsi", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a capped local self-improvement loop.")
    run.add_argument(
        "--repo", required=True, help="Path to the repo to improve (cloned, not touched)."
    )
    run.add_argument(
        "--test-cmd",
        required=True,
        help="Shell command that passes (exit 0) iff the repo is healthy.",
    )
    run.add_argument("--cycles", type=int, default=3, help="Hard cap on cycles (default: 3).")
    run.add_argument(
        "--objective", default=None, help="Override the improvement objective handed to the agent."
    )
    run.add_argument(
        "--targets",
        default=None,
        help="Comma-separated file paths to improve, one per cycle (rotated). "
        "Each cycle gets a targeted objective naming its file (overrides --objective).",
    )
    run.add_argument(
        "--model",
        default=None,
        help="LiteLLM model alias (default: MAISTRO_BUILDERS_MODEL / DEFAULT_MODEL).",
    )
    run.add_argument(
        "--agent-turns", type=int, default=6, help="Max agent turns per cycle (default: 6)."
    )
    run.add_argument(
        "--isolation",
        choices=("local", "container"),
        default="local",
        help="Where the agent runs: 'local' (host worktree) or 'container' "
        "(ADR-093 Docker isolation). Default: local.",
    )
    run.add_argument(
        "--image",
        default="maistro-builders:latest",
        help="Container image for --isolation container (default: maistro-builders:latest).",
    )
    run.add_argument(
        "--fitness",
        action="store_true",
        help="Decide promotion with the full multi-signal Scorecard (gates + weighted "
        "scores) instead of the bare test command; logs an auditable breakdown per cycle.",
    )
    run.add_argument(
        "--coverage-source",
        default=".",
        help="Path passed to coverage --source when --fitness is on (default: .).",
    )
    run.add_argument(
        "--coverage-pytest-args",
        default="",
        help="pytest args for the coverage run when --fitness is on (e.g. a scoped "
        "test path). Default: bare pytest, which runs every testpath in the repo.",
    )
    run.add_argument(
        "--competitors",
        default="",
        help="Tournament roster: 'model@temp,model,...' (e.g. "
        "'devstral-medium@0.2,codestral@0.7'). Each competes per target; the "
        "highest-scoring fix wins, complementary fixes are both kept. Empty ⇒ a "
        "single attempt with --model.",
    )
    run.add_argument(
        "--genome-db",
        default=None,
        help="PopulationStore path — activates UNIFIED LIVE EVOLUTION: the genome "
        "population IS the tournament roster, each cycle's real composites fold "
        "back into the genomes (EMA), same-objective variants fight Elo battles, "
        "and cull/breed/hyper-mutation run between cycles. Work is kept "
        "(promoted/exported) exactly as in a plain run; the population persists, "
        "so every run continues the lineage. No separate training evals exist.",
    )
    run.add_argument(
        "--genome-models",
        default="",
        help="CSV of model aliases to seed the genome population across in live "
        "mode (one seed per model — evolution learns per-model differences and "
        "the bench/reliability machinery makes the full roster safe). "
        "Empty ⇒ seed on --model only.",
    )
    run.add_argument(
        "--evolve-goal",
        default="",
        help="Operator goal for the hyper-mutator's meta-prompts in live mode.",
    )
    run.add_argument(
        "--roster-size",
        type=int,
        default=4,
        help="Genomes fielded per cycle in live mode (unscored children get "
        "priority so verification-by-work never starves). Default: 4.",
    )
    run.add_argument(
        "--emergency-models",
        default="",
        help="Never-idle fallback: CSV of cross-provider models to spawn onto when "
        "the WHOLE roster is benched (rate-limited/quota-drained). Empty ⇒ a built-in "
        "cross-provider default. A different provider here rescues a run whose roster "
        "provider is fully rate-limited.",
    )
    run.add_argument(
        "--local-fallback-model",
        default="",
        help="Never-idle FLOOR: a gateway alias served from local hardware, used only "
        "when the whole emergency pool is benched too. Local hardware has no rate limit "
        "to hit, so it keeps a quota-drained run alive. Empty ⇒ no local tier.",
    )
    run.add_argument(
        "--scout",
        action="store_true",
        help="Before competing, one model reads the target file and names the "
        "concrete improvement all competitors then implement (fairer head-to-head).",
    )
    run.add_argument(
        "--scout-model",
        default=None,
        help="Model alias for the scout (default: --model).",
    )
    run.add_argument(
        "--scout-fallback-models",
        default="",
        help="Comma-separated models the scout tries in skill-ranked order when "
        "--scout-model is benched or fails (default: --genome-models, so no "
        "override is usually needed in live-evolution mode).",
    )
    run.add_argument(
        "--no-regression-judge",
        action="store_true",
        help="Skip the second-opinion LLM regression check (on by default) — "
        "saves the extra LLM call per already-passing candidate.",
    )
    run.add_argument(
        "--no-promotion-review",
        action="store_true",
        help="Skip the checkpoint-time RLPHD review that reverts low-confidence "
        "promotions pending human approve/deny (on by default).",
    )
    run.add_argument(
        "--export-patches",
        default=None,
        help="After the run, export each promotion as a patch + manifest.json here "
        "(the durable output of an isolated run; feed to `maistro_rsi harvest`).",
    )
    run.add_argument(
        "--report-every",
        type=int,
        default=0,
        help="Emit a progress report + refreshed patch export every N cycles "
        "(0 = only a final report). The baseline keeps ratcheting — a checkpoint "
        "is an observation point, not a reset.",
    )
    run.add_argument(
        "--report-dir",
        default=None,
        help="Where to write checkpoint reports (checkpoint-*.md/.json) and the "
        "rolling export/. Point this OUTSIDE the edited repo (e.g. a host-mounted "
        "dir) to get reports out of an isolated run.",
    )
    run.add_argument(
        "--work-root",
        default=None,
        help="Where to put throwaway clones/worktrees (default: a temp dir).",
    )

    harvest = sub.add_parser(
        "harvest",
        help="Open PRs from an exported run, grouped by the file each promotion edited.",
    )
    harvest.add_argument(
        "--export-dir", required=True, help="Directory written by `run --export-patches`."
    )
    harvest.add_argument(
        "--repo-dir",
        default=None,
        help="Existing checkout to build the PR branches in (local runs).",
    )
    harvest.add_argument(
        "--clone-url",
        default=None,
        help="Clone this repo URL fresh (LF, no host dependency) instead of --repo-dir. "
        "This is the cloud path: a trusted runner clones, applies, and pushes with GH_TOKEN. "
        "Auth for push/PR comes from GH_TOKEN via `gh auth setup-git`.",
    )
    harvest.add_argument(
        "--base",
        default=None,
        help="Branch to base the PR branches on (default: the canonical development "
        "branch, or the current branch for --repo-dir).",
    )
    harvest.add_argument(
        "--pr-base",
        default=None,
        help=f"Target branch for the PRs (default: {CANONICAL_DEVELOPMENT_BRANCH}). A "
        f"release tier is refused unless --allow-release-tier is also passed.",
    )
    harvest.add_argument(
        "--allow-release-tier",
        action="store_true",
        help="Authorize a PR against a release tier (main/integration). ADR-095 routes "
        "topic branches through the development tier, so this exists to be set by "
        "workflow policy on a deliberate release harvest -- never by a candidate, a "
        "manifest, or a dispatch input.",
    )
    harvest.add_argument(
        "--session", default=None, help="Session slug for branch names (default: a UTC timestamp)."
    )
    harvest.add_argument(
        "--push",
        action="store_true",
        help="Push branches and open PRs via gh (default: dry-run — build branches locally only).",
    )
    harvest.add_argument(
        "--skip-doc-regressions",
        action="store_true",
        help="Drop any promotion that only made an existing docstring vaguer (older runs "
        "predate the no_doc_regression fitness veto), so a harvest keeps the genuinely-new "
        "docstrings but not the specificity regressions.",
    )

    evolve = sub.add_parser(
        "evolve",
        help="Evolve the fixer genome population against a target via the code_rsi benchmark.",
    )
    evolve.add_argument("--repo", required=True, help="Repo to improve (cloned, not touched).")
    evolve.add_argument("--test-cmd", required=True, help="Health test command (exit 0 = healthy).")
    evolve.add_argument("--target", required=True, help="File the genomes compete to improve.")
    evolve.add_argument("--cycles", type=int, default=1, help="Evolution cycles (default: 1).")
    evolve.add_argument("--population", type=int, default=4, help="Population size (default: 4).")
    evolve.add_argument(
        "--models",
        default=None,
        help="Comma-separated gateway aliases to seed genomes with (e.g. "
        "'devstral-medium,codestral,mistral-medium'). Required for a live run — "
        "evolve's own model names are not routable.",
    )
    evolve.add_argument("--coverage-source", default=".")
    evolve.add_argument("--coverage-pytest-args", default="")
    evolve.add_argument("--agent-turns", type=int, default=6)
    evolve.add_argument("--isolation", choices=("local", "container"), default="local")
    evolve.add_argument(
        "--db", default=None, help="PopulationStore path (persists lineage; default: in-memory)."
    )
    evolve.add_argument("--work-root", default=None)
    evolve.add_argument(
        "--goal",
        default="",
        help="Operator goal threaded into the hyper-mutator's meta-prompt "
        "(guides what the fixer population evolves toward).",
    )
    evolve.add_argument(
        "--mutator-model",
        default=None,
        help="Gateway alias for the hyper-mutator's meta-prompts (default: the "
        "first --models entry). Without a reachable gateway the hyper-mutator "
        "simply proposes nothing.",
    )

    review = sub.add_parser(
        "review",
        help="List/approve/deny promotions the checkpoint reviewer reverted "
        "pending human judgment (SPEC-248 RLPHD). Pure host-side file "
        "operations — no running container needed.",
    )
    review.add_argument(
        "--report-dir", required=True, help="The run's REPORT_DIR (same one passed to `run`)."
    )
    review_sub = review.add_subparsers(dest="review_action", required=True)
    review_sub.add_parser("list", help="List promotions still pending a decision.")
    approve = review_sub.add_parser(
        "approve", help="Approve a flagged promotion — re-queues its patch for the next harvest."
    )
    approve.add_argument("sha", help="Commit sha (or its 12-char prefix) of the flagged promotion.")
    deny = review_sub.add_parser(
        "deny", help="Deny a flagged promotion — it stays reverted; the patch is kept for audit."
    )
    deny.add_argument("sha", help="Commit sha (or its 12-char prefix) of the flagged promotion.")

    return parser


def _evolve(args: argparse.Namespace) -> int:
    import asyncio
    import tempfile

    from maistro_evolve.cycle import EvolutionConfig
    from maistro_evolve.harness import EvalHarness
    from maistro_rsi.code_fixer import LiveCodeFixer
    from maistro_rsi.evolve_bridge import (
        make_code_rsi_runner,
        open_population,
        run_evolution,
        seed_population,
    )
    from maistro_rsi.local_loop import _git

    repo = Path(args.repo).expanduser()
    if not (repo / ".git").exists():
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 2
    work_root = Path(args.work_root or tempfile.mkdtemp(prefix="maistro-rsi-evo-"))
    work_root.mkdir(parents=True, exist_ok=True)
    baseline = work_root / "baseline"
    _git(work_root, "clone", "--quiet", str(repo.resolve()), "baseline")
    _git(baseline, "checkout", "-q", "-B", "rsi-baseline")

    fixer = LiveCodeFixer(
        baseline,
        args.test_cmd,
        coverage_source=args.coverage_source,
        coverage_pytest_args=args.coverage_pytest_args,
        agent_turns=args.agent_turns,
        isolation=args.isolation,
    )
    harness = EvalHarness(benchmark_fidelity="proxy")
    harness.register_benchmark("code_rsi", make_code_rsi_runner(fixer.fix_and_score, args.target))
    from maistro_rsi.free_router import (
        DEFAULT_FREE_MODEL,
        FREE_ROUTER_ALIASES,
        make_free_selector,
    )

    store = open_population(args.db)
    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else None

    # A free-router sentinel in the roster becomes a random-model SELECTOR: each
    # seeded genome pins its own concrete, gateway-registered $0 model.
    uses_free_router = bool(models and any(m in FREE_ROUTER_ALIASES for m in models))
    free_selector = make_free_selector() if uses_free_router else None
    resolved = seed_population(store, args.population, models=models, free_selector=free_selector)

    # allowed_models must be concrete: drop the (un-pinnable) sentinel and fold in
    # the concrete free models the selector actually surfaced, so breeding/mutation
    # stays on routable $0 models instead of drifting back to the sentinel.
    if models:
        allowed = [m for m in models if m not in FREE_ROUTER_ALIASES] + sorted(resolved)
        if not allowed:
            allowed = [DEFAULT_FREE_MODEL]
    else:
        allowed = []
    cfg = EvolutionConfig(
        target_benchmarks=["code_rsi"],
        population_size=args.population,
        eval_batch_size=args.population,
        tournament_size=2,
        goal=args.goal,
        # Keep breeding/mutation on the routable roster — otherwise a mutated
        # model gene (e.g. gemini-2.5-flash from the generic registry) yields
        # guaranteed-0 evals and spreads through the lineage.
        allowed_models=allowed,
    )

    # The hyper-mutator's meta-LLM: a plain async text->text callable over the
    # gateway. Unconfigured gateway ⇒ stub text ⇒ proposals parse to nothing —
    # evolution still runs, just without guided mutation.
    llm_call = None
    # The sentinel can't drive the meta-LLM either; prefer a concrete allowed model.
    mutator_model = args.mutator_model or (allowed[0] if allowed else None)
    if mutator_model:
        from maistro_bootstrap.builders.responses_callable import ResponsesAPICallable

        callable_ = ResponsesAPICallable(model=mutator_model, timeout=300.0)

        async def llm_call(prompt: str) -> str:
            result = await asyncio.to_thread(callable_, [{"role": "user", "content": prompt}])
            content = result.get("content", "") if isinstance(result, dict) else result
            return content if isinstance(content, str) else str(content)

    print(
        f"RSI evolve -> {args.population} genomes x {args.cycles} cycle(s) on {args.target} "
        f"(models={models or 'evolve defaults (not routable!)'}, "
        f"hyper-mutator={mutator_model or 'off'})"
    )
    asyncio.run(run_evolution(store, harness, args.cycles, config=cfg, llm_call=llm_call))

    genomes = store.list_all()
    print(f"\nEvolution complete: {len(genomes)} genomes")
    for g in sorted(genomes, key=lambda x: x.fitness_score or -1.0, reverse=True)[:12]:
        nodes = g.topology.nodes
        entry = next((n for n in nodes if n.id == g.topology.entry_node), nodes[0])
        print(
            f"  {g.name} gen{g.generation} model={entry.model} "
            f"code_rsi={g.eval_scores.get('code_rsi')} fitness={g.fitness_score}"
        )
    champ = store.get_champion()
    if champ is not None:
        print(f"champion: {champ.name} (fitness={champ.fitness_score})")
    return 0


def _validated_export(export: Path, groups: dict[str, list[PromotedPatch]]) -> dict[str, Path]:
    """Resolve and check every patch the manifest names. Raises on the first
    artifact that may not become a pull request.

    Returns the resolved path per manifest entry, so the apply loop uses the
    path this function vetted rather than re-deriving it -- re-deriving is how
    a check and the thing it checked drift apart.
    """
    resolved: dict[str, Path] = {}
    for declared_file, group in groups.items():
        for patch in group:
            entry = patch.patch_file
            path = resolve_export_path(export, entry)
            verdict = validate_patch(
                path.read_text(encoding="utf-8", errors="replace"),
                declared_file=declared_file,
            )
            if not verdict.ok:
                reasons = "\n".join(f"  - {reason}" for reason in verdict.reasons)
                raise ExportPolicyError(f"refusing {entry}:\n{reasons}")
            resolved[entry] = path
    return resolved


def _harvest(args: argparse.Namespace) -> int:  # noqa: C901  clone/repo setup + am/skip/PR loop
    import subprocess
    import tempfile
    from datetime import UTC, datetime

    from maistro_evolve.doc_regression import doc_regressions
    from maistro_rsi.harvest import branch_slug, group_by_file, load_manifest, pr_body, pr_title

    export = Path(args.export_dir)
    manifest = export / "manifest.json"
    if not manifest.is_file():
        print(f"error: no manifest.json in {export}", file=sys.stderr)
        return 2
    groups = group_by_file(load_manifest(manifest))
    if not groups:
        print("no promotions to harvest")
        return 0
    if not (args.repo_dir or args.clone_url):
        print("error: pass --repo-dir (local) or --clone-url (cloud)", file=sys.stderr)
        return 2
    session = args.session or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    # The tier is policy, resolved before a single patch is read (#356). It used
    # to be `--pr-base` defaulting to "main", fed straight from a
    # `workflow_dispatch` input -- so the documented way to run a harvest opened
    # agent-authored PRs against the release tier, skipping both integration
    # tiers ADR-095 defines, with the target chosen by whoever dispatched it.
    try:
        pr_base = resolve_pr_base(args.pr_base, release_tier_authorized=args.allow_release_tier)
    except ExportPolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # What every patch *contains*, before any of them acts on a working tree
    # (#356). The workflow already refused an export directory holding anything
    # but patches and a manifest -- but a patch is a program for the working
    # tree, and nothing asked what was in it. It could create a symlink, move a
    # submodule pointer, write outside the file the manifest names, or edit the
    # containment surface that decides what a future self-modification may do.
    #
    # All of them up front, and a refusal fails the whole harvest. Two reasons
    # it is not a per-patch skip like the unappliable case further down:
    #
    # * A stale patch is an accident and the rest of the run is still good. A
    #   patch reaching for `.github/` is a statement about this export, and
    #   opening the other PRs from it would be treating one artifact as
    #   trustworthy and untrustworthy at the same time.
    # * Failing here means no branch was created and nothing was pushed. Doing
    #   it inside the apply loop would leave the branches for whichever files
    #   happened to sort first.
    try:
        patch_paths_by_entry = _validated_export(export, groups)
    except ExportPolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    base = args.base
    if args.clone_url:
        # Cloud path: wire GH_TOKEN into git FIRST (so a private clone + the push
        # both authenticate), then clone fresh with an LF working tree (no CRLF
        # host artifacts). The credential lives only in this trusted step.
        if args.push:
            subprocess.run(["gh", "auth", "setup-git"], check=True)
        repo = tempfile.mkdtemp(prefix="rsi-harvest-")
        # Branching off the release tier and then targeting the development tier
        # would put every commit between them into the PR. Same default as the
        # target, for the same reason.
        clone_base = base or pr_base
        subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "clone",
                "--single-branch",
                "--branch",
                clone_base,
                args.clone_url,
                repo,
            ],
            check=True,
        )
        base = clone_base
    else:
        repo = str(Path(args.repo_dir).resolve())

    # Identity flags so `git am` can commit in a clone with no configured user
    # (the RSI commits are bot commits); --3way lets am fall back to a blob-level
    # 3-way merge when line-ending/context differs from the patch's base.
    ident = ["-c", "user.email=rsi@maistro.local", "-c", "user.name=maistro-rsi"]

    def git(*a: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *ident, "-C", repo, *a], check=check, capture_output=True, text=True
        )

    # base is set above for --clone-url; for --repo-dir default to its current branch.
    base = base or git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _regresses_docs(rel: str) -> bool:
        # Compare the file just committed (HEAD) against its parent (HEAD~1).
        if not rel.endswith(".py"):
            return False
        before = git("show", f"HEAD~1:{rel}", check=False)
        after = git("show", f"HEAD:{rel}", check=False)
        if before.returncode != 0 or after.returncode != 0:
            return False
        return bool(doc_regressions(before.stdout, after.stdout))

    opened = 0
    skipped = 0
    unappliable = 0
    for file, group in groups.items():
        branch = branch_slug(file, session)
        git("checkout", "-B", branch, base)
        kept_patches = []
        for patch in group:
            # A patch from an older run may no longer apply once the base has
            # moved past it (even with --3way). Skip it and keep harvesting —
            # one stale patch must not sink the rest of the run's promotions.
            am = git("am", "--3way", str(patch_paths_by_entry[patch.patch_file]), check=False)
            if am.returncode != 0:
                git("am", "--abort", check=False)
                unappliable += 1
                continue
            if args.skip_doc_regressions and _regresses_docs(file):
                git("reset", "--hard", "HEAD~1")  # drop the doc-specificity regression
                skipped += 1
                continue
            kept_patches.append(patch)
        if not kept_patches:
            print(f"[skipped] {branch}  <- {file}  (0 of {len(group)} promotion(s) kept)")
            continue
        action = "pushed + PR" if args.push else "built (dry-run)"
        print(f"[{action}] {branch}  <- {file}  ({len(kept_patches)} commit(s))")
        if args.push:
            git("push", "-u", "origin", branch, "--force-with-lease")
            subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    pr_base,
                    "--head",
                    branch,
                    "--title",
                    pr_title(file, kept_patches),
                    "--body",
                    pr_body(file, kept_patches),
                ],
                cwd=repo,
                check=True,
            )
            opened += 1
    git("checkout", base, check=False)
    tail = f", {skipped} doc-regression(s) dropped" if skipped else ""
    if unappliable:
        tail += f", {unappliable} stale patch(es) no longer apply"
    print(f"\nharvest: {len(groups)} file group(s), {opened} PR(s) opened{tail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "run":
        return _run(args)

    if args.command == "harvest":
        return _harvest(args)

    if args.command == "evolve":
        return _evolve(args)

    if args.command == "review":
        return _review(args)

    return 1


def _run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser()
    # `.git` is a dir in a normal checkout, a file in a linked worktree.
    if not (repo / ".git").exists():
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 2
    work_root = args.work_root or tempfile.mkdtemp(prefix="maistro-rsi-")
    targets = [t.strip() for t in args.targets.split(",") if t.strip()] if args.targets else []
    competitors = parse_competitors(args.competitors)
    if args.genome_db:
        print(
            f"live evolution: population at {args.genome_db} IS the roster — "
            "work is kept AND scores the genomes; lineage continues across runs"
        )
    # A free-router sentinel (openrouter/free / or-free-router) in the roster is a
    # random-model SELECTOR, not a scorable model — it re-randomises every call.
    # Resolve it to concrete, gateway-registered $0 aliases so seeding + tournament
    # pin stable models. Normally the launcher expands this HOST-SIDE (it has
    # OPENROUTER_API_KEY, which the container env deliberately drops); this in-loop
    # pass is the safety net — with no OpenRouter key it maps the sentinel to
    # DEFAULT_FREE_MODEL so a raw, un-pinnable sentinel never reaches the tournament.
    genome_models = [m.strip() for m in args.genome_models.split(",") if m.strip()]
    if any(m in FREE_ROUTER_ALIASES for m in genome_models):
        selector = make_free_selector()
        genome_models = expand_free_router(genome_models, selector) or genome_models
        print(f"free-router roster resolved -> {genome_models}")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command=args.test_cmd,
        work_root=work_root,
        max_cycles=args.cycles,
        # Only override the config's own default objective when one is given.
        **({"objective": args.objective} if args.objective else {}),
        targets=targets,
        model=args.model,
        agent_turns_per_cycle=args.agent_turns,
        isolation=args.isolation,
        sandbox_image=args.image,
        use_fitness=args.fitness,
        coverage_source=args.coverage_source,
        coverage_pytest_args=args.coverage_pytest_args,
        competitors=competitors,
        scout=args.scout,
        scout_model=args.scout_model,
        scout_fallback_models=[
            m.strip() for m in args.scout_fallback_models.split(",") if m.strip()
        ],
        regression_judge=not args.no_regression_judge,
        promotion_review=not args.no_promotion_review,
        export_patches=args.export_patches,
        report_every=args.report_every,
        report_dir=args.report_dir,
        genome_db=args.genome_db,
        genome_models=genome_models,
        evolve_goal=args.evolve_goal,
        roster_size=args.roster_size,
        emergency_models=[m.strip() for m in args.emergency_models.split(",") if m.strip()],
        local_fallback_model=args.local_fallback_model.strip(),
    )
    print(
        f"RSI local loop -> clone of {repo} in {work_root} ({args.cycles} cycles, model={args.model or 'env default'})"
    )
    loop = LocalRsiLoop(config)
    result = loop.run()
    print("\n" + result.summary())
    if config.genome_db:
        summary = loop._population_summary()
        print(
            f"\nEvolution: {summary['population_size']} genome(s), "
            f"generations={summary['generations']}"
        )
        for g in summary["top_genomes"]:
            print(
                f"  champion: {g['name']} (gen {g['generation']}, {g['model']}) "
                f"fitness={g['fitness']} tdd_rigor={g['tdd_rigor']} "
                f"test_style={g['test_style']}"
            )
        if summary["reliability"]:
            print(
                "  reliability: "
                + ", ".join(f"{m}={round(v, 3)}" for m, v in sorted(summary["reliability"].items()))
            )
        if summary["benched_models"]:
            print(f"  benched: {', '.join(summary['benched_models'])}")
    return 0


def _review(args: argparse.Namespace) -> int:
    from maistro_rsi.promotion_review import (
        load_kept_reviews,
        load_pending_reviews,
        resolve_review,
    )

    report_dir = Path(args.report_dir).expanduser()
    flagged_dir = report_dir / "flagged"
    kept_dir = report_dir / "kept"

    if args.review_action == "list":
        pending = load_pending_reviews(flagged_dir)
        kept = load_kept_reviews(kept_dir)
        if not pending and not kept:
            print("No promotions pending review.")
            return 0
        if pending:
            print(f"=== FLAGGED (auto-reverted, need your ruling) — {len(pending)} ===")
            for r in pending:
                print(
                    f"  {r.sha[:12]}  cycle={r.index:<4} kind={r.kind:<12} target={r.target}\n"
                    f"    predicted_p={r.predicted_p:.3f} theta={r.theta:.3f}  {r.note}"
                )
        if kept:
            print(f"\n=== KEPT (auto-approved, review to override) — {len(kept)} ===")
            for r in kept:
                print(
                    f"  {r.sha[:12]}  cycle={r.index:<4} kind={r.kind:<12} target={r.target}\n"
                    f"    predicted_p={r.predicted_p:.3f} theta={r.theta:.3f}  {r.note}"
                )
        print(
            "\nTo decide: python -m maistro_rsi review approve <sha> --report-dir <dir>\n"
            "            python -m maistro_rsi review deny <sha> --report-dir <dir>"
        )
        return 0

    sha = args.sha
    decision: Literal["approve", "deny"] = "approve" if args.review_action == "approve" else "deny"
    # resolve from flagged OR kept dir — the review data has the same shape
    for d in (flagged_dir, kept_dir):
        if (d / f"{sha[:12]}.json").is_file():
            try:
                review = resolve_review(
                    d, report_dir / "export", report_dir / "rlphd_state.json", sha, decision
                )
            except FileNotFoundError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            verb = (
                "approved — patch re-queued for the next harvest"
                if decision == "approve"
                else "denied"
            )
            print(
                f"{review.sha[:12]} ({review.target}) {verb}. RLPHD model updated for {review.action_class}."
            )
            return 0
    print(
        f"error: no review found for sha {sha[:12]} in {flagged_dir} or {kept_dir}", file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
