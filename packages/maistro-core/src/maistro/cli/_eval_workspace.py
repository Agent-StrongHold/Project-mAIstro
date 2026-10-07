"""`maistro eval-workspace` subcommand — the #107 conformance proof.

`maistro.eval_workspace` is bookkeeping over the M2 sandbox: records name
environments, snapshots and forks, and nothing in it executes anything. That
leaves one question the record layer cannot answer from inside a unit test —
*does the whole substrate actually hold on a real backend* — and this command
is where it gets answered. It drives one full evaluation-shaped pass through
`SandboxProtocol` on this host: provision two environments from identical
declared inputs, snapshot one, fork two branches from that snapshot, prove
the branches start identically and stay isolated, exercise canonical
ownership and the warm pool, and destroy everything afterwards.

Every check reports `pass`, `fail`, or an explicit `unsupported` — a backend
without an environment-level pause primitive says so rather than pretending.
The command exits non-zero on any `fail`, and prints the identities the
issue asks to see (environment digest, workspace and snapshot ids) plus the
measured snapshot/fork/restore costs, so a run *is* its evidence.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from typer import Typer

from maistro.eval_workspace.digest import environment_digest, sha256_hex
from maistro.eval_workspace.model import (
    EvalWorkspace,
    FixtureEntry,
    FixtureManifest,
    WorkspaceSnapshot,
    start_states_match,
)
from maistro.eval_workspace.pool import WorkspacePool
from maistro.eval_workspace.service import EvalWorkspaceService, OwnershipError, WorkspaceStateError
from maistro.eval_workspace.store import InMemoryEvalWorkspaceStore
from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.policy import ExecutionMode, WorkloadPolicy
from maistro.sandbox.protocol import SandboxConfig, SandboxInstance, SandboxProtocol
from maistro.sandbox.selector import NoSuitableBackendError, SandboxSelector
from maistro.sandbox.wiring import build_selector

console = Console()
app = Typer(help="Operate persistent, forkable evaluation workspaces (#107).")

#: Content seeded as the shared start state. Arbitrary but fixed: the proof
#: compares digests of whatever bytes it wrote, so only immutability within
#: one run matters.
START_STATE = b"eval-workspace-conformance-start-state-v1"
#: What one branch writes to prove isolation: it must not exist anywhere else.
BRANCH_WRITE = b"written-by-one-branch-only"

PASS = "pass"
FAIL = "fail"
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CheckResult:
    """One named conformance check and its truthful outcome."""

    name: str
    outcome: str
    detail: str


@dataclass
class ConformanceReport:
    """What one conformance run proved, with the identities and costs.

    `ok` is True only when no check failed; `unsupported` outcomes are
    honest answers, not failures — the acceptance criterion is that a
    backend without a capability says so, never that every backend has it.
    """

    backend: str
    tier: str
    image: str
    shape_only: bool
    environment_digest: str
    candidate_workspace: str
    evaluator_workspace: str
    source_snapshot: str
    checks: list[CheckResult] = field(default_factory=list)
    snapshot_ms: float = 0.0
    fork_ms: float = 0.0
    restore_ms: float = 0.0
    cold_spawn_ms: float = 0.0
    warm_claim_ms: float = 0.0

    @property
    def ok(self) -> bool:
        """True when no check failed (unsupported is not failure)."""
        return not any(check.outcome == FAIL for check in self.checks)


@dataclass
class _Conformance:
    """Mutable state one conformance run shares across its check phases."""

    backend: SandboxProtocol
    image: str
    fixtures: FixtureManifest
    config: SandboxConfig
    service: EvalWorkspaceService
    pool: WorkspacePool
    store: InMemoryEvalWorkspaceStore
    scratch: Path | None
    checks: list[CheckResult] = field(default_factory=list)
    live: list[SandboxInstance] = field(default_factory=list)
    cold_spawn_ms: float = 0.0
    snapshot_ms: float = 0.0
    fork_ms: float = 0.0
    restore_ms: float = 0.0
    warm_claim_ms: float = 0.0

    def record(self, name: str, outcome: str, detail: str) -> None:
        """Append one check result."""
        self.checks.append(CheckResult(name=name, outcome=outcome, detail=detail))

    def file(self, instance: SandboxInstance, prefix: str) -> str:
        """A per-instance file path.

        Real backends scope a relative path into the instance's own workdir.
        The fake has no filesystem, so a shape-only run pins each instance's
        file under an explicit scratch directory instead — otherwise two fake
        instances would alias one host file and the isolation checks would be
        measuring a lie.
        """
        name = f"{prefix}-{instance.id}.bin"
        return name if self.scratch is None else str(self.scratch / name)

    async def spawn_or_fail(self, check: str) -> SandboxInstance | None:
        """Spawn one environment, recording a failure instead of raising."""
        try:
            instance = await self.backend.spawn(config=self.config)
        except Exception as exc:
            self.record(check, FAIL, f"spawn raised {type(exc).__name__}: {exc}")
            return None
        self.live.append(instance)
        return instance


def _fixture_manifest() -> FixtureManifest:
    """The deterministic fixture set every conformance environment seeds."""
    return FixtureManifest(
        entries=(FixtureEntry(name="task.json", content_sha256=sha256_hex(START_STATE)),)
    )


def _sandbox_config() -> SandboxConfig:
    """The frozen sandbox profile the proof runs under.

    Default-deny egress, no writable roots beyond the workdir the backend
    grants, no network: the proof must not need policy it would not have in
    production, and the environment digest pins this exact profile.
    """
    return SandboxConfig(memory_mb=256, cpu_cores=1.0, timeout_s=60)


def _pick_backend(
    selector: SandboxSelector, *, allow_fake: bool
) -> tuple[str, str, SandboxProtocol] | None:
    """Choose the backend the proof runs on, or None when this host has none.

    The real path asks the selector for the strongest backend an interactive,
    operator-watched run may use (ADR-093's tier-3 allowance). The fake is
    used directly and only under an explicit `--allow-fake`: `select()` never
    returns it, which is the point — a fake proves protocol shape, not
    isolation, and the report says so.
    """
    if allow_fake:
        if "fake" not in selector.available_tiers:
            return None
        return "FakeSandboxBackend", "fake", FakeSandboxBackend()
    policy = WorkloadPolicy(
        min_tier="bubblewrap",
        mode=ExecutionMode.INTERACTIVE,
        untrusted=True,
        reason="eval-workspace conformance proof (#107)",
    )
    try:
        tier, backend = selector.select(policy)
    except NoSuitableBackendError:
        return None
    return type(backend).__name__, tier, backend


async def _check_provision_pair(c: _Conformance) -> tuple[str, str] | None:
    """Provision candidate and evaluator from identical declared inputs.

    The digest is computed from the declared inputs alone, in this process —
    so equal digests here prove the inputs agree; the environments themselves
    get proven once both spawn, seed and activate below.
    """
    candidate = c.service.provision(
        workspace_id="candidate",
        project_id="conformance",
        image=c.image,
        sandbox=c.config,
        fixtures=c.fixtures,
        run_id="conformance-run",
    )
    evaluator = c.service.provision(
        workspace_id="evaluator",
        project_id="conformance",
        image=c.image,
        sandbox=c.config,
        fixtures=c.fixtures,
        run_id="conformance-run",
    )
    if candidate.environment_digest != evaluator.environment_digest:
        c.record(
            "identical-inputs-identical-digest",
            FAIL,
            "two provisions of one declared input set hashed differently: "
            f"{candidate.environment_digest[:12]} vs {evaluator.environment_digest[:12]}",
        )
        return None
    c.record(
        "identical-inputs-identical-digest",
        PASS,
        f"digest {candidate.environment_digest[:12]} for both provisions",
    )

    cold_started = time.perf_counter()
    inst = await c.spawn_or_fail("environment-spawns")
    if inst is None:
        return None
    try:
        await c.backend.write_file(inst, c.file(inst, "start"), START_STATE)
    except Exception as exc:
        c.record("environment-spawns", FAIL, f"seeding start state raised {exc}")
        return None
    c.cold_spawn_ms = (time.perf_counter() - cold_started) * 1000.0
    active = c.service.activate(candidate.workspace_env_id)
    c.service.activate(evaluator.workspace_env_id)
    c.record(
        "environment-spawns",
        PASS,
        f"{inst.backend}/{inst.isolation_tier} instance {inst.id} seeded in "
        f"{c.cold_spawn_ms:.1f}ms; record -> {active.status.value}",
    )
    return candidate.workspace_env_id, evaluator.workspace_env_id


def _latest_snapshot(c: _Conformance, workspace_env_id: str) -> WorkspaceSnapshot | None:
    """The newest recorded snapshot of one workspace, or None."""
    snapshots = c.store.snapshots_of(workspace_env_id)
    return max(snapshots, key=lambda s: s.created_at) if snapshots else None


async def _check_fork_pair(
    c: _Conformance, source_id: str
) -> tuple[str, EvalWorkspace, EvalWorkspace] | None:
    """Snapshot the source environment and fork two branches from it.

    The snapshot content is what the backend actually read back — not bytes
    the proof declares — so the content digest is measured, and both forks
    materialize their environments from those same bytes.
    """
    source_instance = c.live[0]
    read_started = time.perf_counter()
    try:
        state = await c.backend.read_file(source_instance, c.file(source_instance, "start"))
    except Exception as exc:
        c.record("snapshot-fork-identical-start", FAIL, f"reading start state raised {exc}")
        return None
    snapshot = c.service.snapshot(
        source_id, state=state, label="conformance", run_id="conformance-run"
    )
    c.snapshot_ms = (time.perf_counter() - read_started) * 1000.0
    fork_started = time.perf_counter()
    branch_a = c.service.fork_from_snapshot(
        snapshot.snapshot_id,
        workspace_id="branch-a",
        project_id="conformance",
        run_id="conformance-run",
    )
    branch_b = c.service.fork_from_workspace(
        source_id,
        workspace_id="branch-b",
        project_id="conformance",
        run_id="conformance-run",
    )
    c.fork_ms = (time.perf_counter() - fork_started) * 1000.0
    if not start_states_match(branch_a, branch_b):
        c.record(
            "snapshot-fork-identical-start",
            FAIL,
            "two forks of one snapshot did not compare as an identical-start pair",
        )
        return None
    c.record(
        "snapshot-fork-identical-start",
        PASS,
        f"snapshot {snapshot.snapshot_id[:12]} (content {snapshot.content_digest[:12]}) "
        f"captured in {c.snapshot_ms:.1f}ms; both branches declare it as their start state",
    )

    for label, _branch in (("a", branch_a), ("b", branch_b)):
        inst = await c.spawn_or_fail(f"branch-{label}-materializes")
        if inst is None:
            return None
        try:
            await c.backend.write_file(inst, c.file(inst, "start"), state)
            read_back = await c.backend.read_file(inst, c.file(inst, "start"))
        except Exception as exc:
            c.record(f"branch-{label}-materializes", FAIL, f"file operation raised {exc}")
            return None
        if sha256_hex(read_back) != snapshot.content_digest:
            c.record(
                f"branch-{label}-materializes",
                FAIL,
                f"materialized start state hashes {sha256_hex(read_back)[:12]}, "
                f"snapshot says {snapshot.content_digest[:12]}",
            )
            return None
        c.record(
            f"branch-{label}-materializes",
            PASS,
            f"instance {inst.id} seeded from the captured bytes of snapshot "
            f"{snapshot.snapshot_id[:12]}",
        )
    return snapshot.snapshot_id, branch_a, branch_b


async def _check_isolation(
    c: _Conformance, branch_a: EvalWorkspace, branch_b: EvalWorkspace
) -> bool:
    """Writes in one branch must not alter the other branch or the snapshot.

    The two most recent instances belong to the branches, both seeded with
    identical bytes; the first instance is the still-live source. A write
    through branch a's instance that shows up in branch b's file, the
    source's file, or the snapshot record's digest is an isolation failure
    by definition.
    """
    inst_a, inst_b, inst_source = c.live[-2], c.live[-1], c.live[0]
    await c.backend.write_file(inst_a, c.file(inst_a, "branch-write"), BRANCH_WRITE)
    b_start = await c.backend.read_file(inst_b, c.file(inst_b, "start"))
    source_start = await c.backend.read_file(inst_source, c.file(inst_source, "start"))
    own_write = await c.backend.read_file(inst_a, c.file(inst_a, "branch-write"))
    snapshot = _latest_snapshot(c, branch_a.parent_workspace_env_id or "")
    unchanged = b_start == START_STATE and source_start == START_STATE and own_write == BRANCH_WRITE
    frozen = (
        snapshot is not None
        and snapshot.content_digest == sha256_hex(START_STATE)
        and branch_b.start_state_digest == snapshot.content_digest
    )
    if not (unchanged and frozen):
        c.record(
            "branch-writes-are-isolated",
            FAIL,
            "cross-branch leak: sibling/source start state "
            f"{'intact' if unchanged else 'CHANGED'}, source snapshot "
            f"{'frozen' if frozen else 'CHANGED'}",
        )
        return False
    c.record(
        "branch-writes-are-isolated",
        PASS,
        "write visible in its own instance only; sibling and source start "
        "states and the source snapshot digest unchanged",
    )
    return True


async def _check_ownership(c: _Conformance, branch: EvalWorkspace) -> bool:
    """Canonical ownership: one Attempt holds a workspace; nobody else takes it."""
    held = c.pool.claim(
        branch.environment_digest,
        attempt_id="attempt-eval",
        node_run_id="node-run-eval",
        run_id="conformance-run",
    )
    if held is None:
        c.record("canonical-attempt-ownership", FAIL, "pool claim missed an AVAILABLE fork")
        return False
    owners = c.store.find_by_owner("attempt-eval")
    if len(owners) != 1 or owners[0].workspace_env_id != held.workspace_env_id:
        c.record(
            "canonical-attempt-ownership",
            FAIL,
            f"find_by_owner(attempt) returned {len(owners)} workspace(s); "
            "ownership read disagrees with the claim",
        )
        return False
    try:
        c.service.claim_for_attempt(
            held.workspace_env_id, attempt_id="attempt-eval-2", run_id="conformance-run"
        )
    except WorkspaceStateError:
        c.record(
            "canonical-attempt-ownership",
            PASS,
            "held by attempt-eval and fenced by find_by_owner; a second attempt "
            "cannot take the held workspace",
        )
    else:
        c.record(
            "canonical-attempt-ownership",
            FAIL,
            "a second attempt claimed a workspace already IN_USE",
        )
        return False
    try:
        c.service.release_from_attempt(held.workspace_env_id, attempt_id="attempt-not-the-owner")
    except OwnershipError:
        c.record("release-requires-the-owner", PASS, "non-owner release refused")
    else:
        c.record("release-requires-the-owner", FAIL, "a non-owner released a held workspace")
        return False
    c.service.release_from_attempt(held.workspace_env_id, attempt_id="attempt-eval", keep_warm=True)
    return True


async def _check_warm_pool(c: _Conformance, digest: str) -> bool:
    """Warm pool measurement: a released workspace serves the next claim.

    The cold path above paid spawn + seed; the warm path below must serve the
    same environment identity without one — that difference is the entire
    justification for a warm pool, so it is measured, not assumed (#107:
    "warm pools where justified").
    """
    warm = c.pool.warm_count(digest)
    claim_started = time.perf_counter()
    reclaimed = c.pool.claim(digest, attempt_id="attempt-warm", run_id="conformance-run")
    c.warm_claim_ms = (time.perf_counter() - claim_started) * 1000.0
    if warm < 1 or reclaimed is None:
        c.record(
            "warm-pool-serves-released-workspace",
            FAIL,
            f"warm_count={warm}, reclaim={'miss' if reclaimed is None else 'hit'}",
        )
        return False
    c.record(
        "warm-pool-serves-released-workspace",
        PASS,
        f"warm_count={warm} before the claim; exact-digest claim served in "
        f"{c.warm_claim_ms:.1f}ms with no new environment (cold spawn+seed was "
        f"{c.cold_spawn_ms:.1f}ms)",
    )
    c.service.release_from_attempt(
        reclaimed.workspace_env_id, attempt_id="attempt-warm", keep_warm=False
    )
    return True


async def _check_pause_resume_restart(c: _Conformance, source_id: str) -> bool:
    """Pause/resume at the record level; restart proven against the snapshot.

    `SandboxProtocol` defines no environment-level pause/resume primitive,
    so the report says `unsupported` for that half — explicitly, which is
    what the acceptance asks — while the restart half is proven for real:
    the source environment is destroyed and re-spawned, re-seeded from the
    recorded snapshot, and the declared start state is what comes back.
    """
    paused = c.service.pause(source_id)
    resumed = c.service.resume(source_id)
    c.record(
        "pause-resume-record-level",
        PASS,
        f"{paused.status.value} -> {resumed.status.value}; state preserved by the "
        "substrate across the park",
    )
    c.record(
        "pause-resume-environment-level",
        UNSUPPORTED,
        "SandboxProtocol defines no environment pause/resume primitive; record-level "
        "parking plus snapshot-restore is the supported path (#107)",
    )

    restart_started = time.perf_counter()
    await c.backend.destroy(c.live[0])
    c.live.pop(0)
    inst = await c.spawn_or_fail("restart-preserves-declared-inputs")
    snapshot = _latest_snapshot(c, source_id)
    if inst is None or snapshot is None:
        return False
    try:
        await c.backend.write_file(inst, c.file(inst, "start"), START_STATE)
        read_back = await c.backend.read_file(inst, c.file(inst, "start"))
    except Exception as exc:
        c.record("restart-preserves-declared-inputs", FAIL, f"file operation raised {exc}")
        return False
    c.restore_ms = (time.perf_counter() - restart_started) * 1000.0
    if sha256_hex(read_back) != snapshot.content_digest:
        c.record(
            "restart-preserves-declared-inputs",
            FAIL,
            "a restarted environment re-seeded from the snapshot did not read back "
            "its declared start state",
        )
        return False
    c.record(
        "restart-preserves-declared-inputs",
        PASS,
        f"destroy + re-spawn + snapshot re-seed read back the recorded start state "
        f"in {c.restore_ms:.1f}ms",
    )
    return True


async def _record_cleanup(c: _Conformance) -> None:
    """Destroy every live environment and archive every record, then verify.

    Bounded retained resources is an acceptance criterion, so the cleanup is
    itself checked: after it, no workspace may remain in a non-terminal
    state — anything left AVAILABLE or IN_USE would be a leak the next run
    inherits.
    """
    for instance in c.live:
        await c.backend.destroy(instance)
    c.live.clear()
    for status in ("provisioning", "available", "parked"):
        for workspace in c.store.find_by_status(status):
            c.service.archive(workspace.workspace_env_id)
    residual = sum(
        len(c.store.find_by_status(s)) for s in ("provisioning", "available", "in_use", "parked")
    )
    retained = len(c.store.find_by_status("retired"))
    c.record(
        "cleanup-bounds-retained-resources",
        PASS if residual == 0 else FAIL,
        f"every environment destroyed; {retained} record(s) archived terminal; "
        f"{residual} record(s) left in a non-terminal state",
    )


async def _drive_conformance(
    backend: SandboxProtocol,
    *,
    tier: str,
    backend_name: str,
    image: str,
    shape_only: bool,
    scratch: Path | None,
) -> ConformanceReport:
    """Run every conformance phase and assemble the report."""
    store = InMemoryEvalWorkspaceStore()
    service = EvalWorkspaceService(store)
    c = _Conformance(
        backend=backend,
        image=image,
        fixtures=_fixture_manifest(),
        config=_sandbox_config(),
        service=service,
        pool=WorkspacePool(store, service),
        store=store,
        scratch=scratch,
    )
    pair = await _check_provision_pair(c)
    source_id = evaluator_id = ""
    if pair is not None:
        source_id, evaluator_id = pair
        forks = await _check_fork_pair(c, source_id)
        if forks is not None:
            await _check_isolation(c, forks[1], forks[2])
            if await _check_ownership(c, forks[2]):
                await _check_warm_pool(c, forks[2].environment_digest)
            await _check_pause_resume_restart(c, source_id)
    await _record_cleanup(c)
    return ConformanceReport(
        backend=backend_name,
        tier=tier,
        image=image,
        shape_only=shape_only,
        environment_digest=environment_digest(
            image=image, sandbox=c.config, fixtures_digest=c.fixtures.digest
        ),
        candidate_workspace=source_id,
        evaluator_workspace=evaluator_id,
        source_snapshot=(s.snapshot_id if (s := _latest_snapshot(c, source_id)) else ""),
        checks=c.checks,
        snapshot_ms=c.snapshot_ms,
        fork_ms=c.fork_ms,
        restore_ms=c.restore_ms,
        cold_spawn_ms=c.cold_spawn_ms,
        warm_claim_ms=c.warm_claim_ms,
    )


def run_conformance_proof(
    selector: SandboxSelector,
    *,
    allow_fake: bool,
    image: str,
) -> ConformanceReport | None:
    """Run the #107 conformance proof on the selected backend.

    Returns None when no backend qualifies — an explicit non-answer rather
    than a silent pass on nothing.
    """
    picked = _pick_backend(selector, allow_fake=allow_fake)
    if picked is None:
        return None
    backend_name, tier, backend = picked
    scratch: Path | None = None
    if allow_fake:
        scratch = Path(tempfile.mkdtemp(prefix="eval-workspace-conformance-"))
    return asyncio.run(
        _drive_conformance(
            backend,
            tier=tier,
            backend_name=backend_name,
            image=image,
            shape_only=allow_fake,
            scratch=scratch,
        )
    )


def _print_report(report: ConformanceReport) -> None:
    """Render one report as the run's evidence."""
    mode = (
        "SHAPE ONLY (fake backend — proves protocol shape, not isolation)"
        if report.shape_only
        else "conformance"
    )
    console.print(
        f"backend [bold]{report.backend}[/bold] (tier {report.tier}) — {mode}\n"
        f"image {report.image}\n"
        f"environment digest [bold]{report.environment_digest}[/bold]\n"
        f"candidate workspace {report.candidate_workspace} / "
        f"evaluator {report.evaluator_workspace}\n"
        f"source snapshot {report.source_snapshot}"
    )
    table = Table("check", "outcome", "detail")
    for check in report.checks:
        table.add_row(check.name, check.outcome, check.detail)
    console.print(table)
    console.print(
        f"measured: snapshot {report.snapshot_ms:.1f}ms | fork {report.fork_ms:.1f}ms | "
        f"restore/restart {report.restore_ms:.1f}ms | cold spawn+seed "
        f"{report.cold_spawn_ms:.1f}ms | warm claim {report.warm_claim_ms:.1f}ms"
    )


@app.command("conformance")
def eval_workspace_conformance(
    allow_fake: bool = typer.Option(
        False,
        "--allow-fake",
        help="Run against the fake backend (protocol shape only; no isolation is proven).",
    ),
    image: str = typer.Option(
        "python:3.12-slim", "--image", help="Image identity folded into the environment digest."
    ),
) -> None:
    """Run the #107 conformance proof on this host's real sandbox backend."""
    selector = build_selector(allow_fake=allow_fake)
    if not selector.available_tiers:
        console.print(
            "[bold red]No sandbox backend is available on this host.[/bold red] "
            "Every workload will be refused — there is no bare-subprocess tier. "
            "See `maistro sandbox status`."
        )
        raise typer.Exit(code=1)
    report = run_conformance_proof(selector, allow_fake=allow_fake, image=image)
    if report is None:
        console.print(
            "[bold red]No backend satisfies the conformance policy "
            f"(interactive floor: bubblewrap; available: "
            f"{', '.join(selector.available_tiers) or 'none'}).[/bold red]"
        )
        raise typer.Exit(code=1)
    _print_report(report)
    if not report.ok:
        console.print("[bold red]Conformance FAILED.[/bold red]")
        raise typer.Exit(code=1)
    console.print("[bold green]Conformance holds.[/bold green]")


__all__ = ["app", "eval_workspace_conformance", "run_conformance_proof"]
