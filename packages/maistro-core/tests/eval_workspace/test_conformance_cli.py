"""Conformance-proof tests for the `maistro eval-workspace` command (#107).

The conformance command is itself a checker, and a checker that cannot fail
is decorative. Besides the passing runs (fake backend for protocol shape,
real backend when this host can build one), these tests inject the failure
each check exists to catch — drifting reads, cross-branch leaks, spawn and
write faults, ownership and warm-pool violations, digest disagreement — and
assert the proof reports the failure instead of passing anyway.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from maistro.cli import _eval_workspace as cli_mod
from maistro.cli import app
from maistro.cli._eval_workspace import (
    BRANCH_WRITE,
    ConformanceReport,
    _check_isolation,
    _check_ownership,
    _check_provision_pair,
    _check_warm_pool,
    _drive_conformance,
    _pick_backend,
    run_conformance_proof,
)
from maistro.eval_workspace.pool import WorkspacePool
from maistro.eval_workspace.service import EvalWorkspaceService
from maistro.eval_workspace.store import InMemoryEvalWorkspaceStore
from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.protocol import SandboxInstance, SandboxProtocol
from maistro.sandbox.selector import SandboxSelector
from maistro.sandbox.wiring import build_selector

try:  # capability probe, not binary presence (mirrors tests/sandbox)
    from maistro.sandbox.detect import detect_host_capabilities

    _capabilities = detect_host_capabilities()
except Exception:
    _capabilities = None
HAS_BWRAP = bool(_capabilities and _capabilities.supports("bubblewrap"))
requires_bwrap = pytest.mark.skipif(
    not HAS_BWRAP, reason="this host cannot build a bubblewrap sandbox"
)


class _DelegatingBackend:
    """Forward every SandboxProtocol call to a wrapped backend."""

    def __init__(self, inner: SandboxProtocol) -> None:
        self._inner = inner

    async def spawn(self, *, config: Any) -> SandboxInstance:
        """Delegate spawn."""
        return await self._inner.spawn(config=config)

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> Any:
        """Delegate exec."""
        return await self._inner.exec(instance, command, timeout_s=timeout_s)

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        """Delegate write_file."""
        await self._inner.write_file(instance, path, content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        """Delegate read_file."""
        return await self._inner.read_file(instance, path)

    async def destroy(self, instance: SandboxInstance) -> None:
        """Delegate destroy."""
        await self._inner.destroy(instance)


class _DriftingBackend(_DelegatingBackend):
    """Reads drift after the first read: the capture and the replay disagree.

    The failure mode: a backend whose snapshot read and whose later branch
    reads return different bytes for the same file — a snapshot that would
    silently fake reproducibility.
    """

    def __init__(self) -> None:
        super().__init__(FakeSandboxBackend())
        self._reads = 0

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        """Return the real bytes once, then mutated bytes."""
        self._reads += 1
        data = await self._inner.read_file(instance, path)
        return data if self._reads == 1 else data + b"\x00drift"


class _FlakyBackend(_DelegatingBackend):
    """A backend with per-operation budgets: inject the fault you are testing.

    `spawn_ok`/`write_ok` count how many of that operation succeed before the
    fault; the counts make every phase reachable — seed-write failure at
    provision, materialization spawn failure, restart-phase write failure.
    """

    def __init__(self, *, spawn_ok: int = 10**6, write_ok: int = 10**6) -> None:
        super().__init__(FakeSandboxBackend())
        self._spawn_budget = spawn_ok
        self._write_budget = write_ok

    async def spawn(self, *, config: Any) -> SandboxInstance:
        """Raise once the spawn budget is spent."""
        if self._spawn_budget <= 0:
            raise RuntimeError("provider exhausted")
        self._spawn_budget -= 1
        return await self._inner.spawn(config=config)

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        """Raise once the write budget is spent."""
        if self._write_budget <= 0:
            raise OSError("disk full")
        self._write_budget -= 1
        await self._inner.write_file(instance, path, content)


class _ReadFailingBackend(_DelegatingBackend):
    """Refuses every read: snapshot capture fails."""

    def __init__(self) -> None:
        super().__init__(FakeSandboxBackend())

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        """Always raise."""
        raise OSError("backend read failed")


class _CrossLeakingBackend(_DelegatingBackend):
    """Start-file reads lie during the isolation phase: a shared-state breach.

    The capture and both materialization reads stay honest (reads 1-3); from
    the isolation phase on, every start-file read returns the other branch's
    write — exactly what a backend whose instances share state would show.
    """

    def __init__(self) -> None:
        super().__init__(FakeSandboxBackend())
        self._reads = 0

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        """Return real bytes for reads 1-3, foreign bytes afterwards."""
        self._reads += 1
        if self._reads > 3 and "branch-write" not in path:
            return BRANCH_WRITE
        return await self._inner.read_file(instance, path)


def _fake_selector() -> SandboxSelector:
    """A selector with only the fake tier registered."""
    selector = SandboxSelector()
    selector.register("fake", FakeSandboxBackend())
    return selector


def _outcomes(report: ConformanceReport | None) -> dict[str, str]:
    """Check outcomes by name; asserts the report exists first."""
    assert report is not None
    return {check.name: check.outcome for check in report.checks}


def _drive(backend: SandboxProtocol) -> ConformanceReport:
    """Drive the conformance proof against an injected backend.

    The scratch directory keeps the fake backend's host-side writes out of
    the repository: without it the fake resolves relative paths against the
    process working directory and litters it.
    """
    import tempfile

    return asyncio.run(
        _drive_conformance(
            backend,
            tier="fake",
            backend_name=type(backend).__name__,
            image="img",
            shape_only=True,
            scratch=Path(tempfile.mkdtemp(prefix="eval-workspace-test-")),
        )
    )


def _conformance(store: InMemoryEvalWorkspaceStore, scratch: Path | None) -> cli_mod._Conformance:
    """A _Conformance context over a fresh store, as the runner builds one."""
    service = EvalWorkspaceService(store)
    return cli_mod._Conformance(
        backend=FakeSandboxBackend(),
        image="img",
        fixtures=cli_mod._fixture_manifest(),
        config=cli_mod._sandbox_config(),
        service=service,
        pool=WorkspacePool(store, service),
        store=store,
        scratch=scratch,
    )


def _provisioned(c: cli_mod._Conformance) -> str:
    """One provisioned, activated workspace id."""
    ws = c.service.provision(workspace_id="w", project_id="p", image="i", sandbox=c.config)
    c.service.activate(ws.workspace_env_id)
    return ws.workspace_env_id


# --- passing runs ---------------------------------------------------------------


def test_conformance_holds_on_fake_backend_protocol_shape() -> None:
    """The whole proof passes on the fake backend, shape-only."""
    report = run_conformance_proof(_fake_selector(), allow_fake=True, image="python:3.12-slim")
    outcomes = _outcomes(report)
    assert report is not None and report.ok
    assert report.shape_only
    for name in (
        "identical-inputs-identical-digest",
        "branch-a-materializes",
        "branch-b-materializes",
        "branch-writes-are-isolated",
        "canonical-attempt-ownership",
        "release-requires-the-owner",
        "warm-pool-serves-released-workspace",
        "restart-preserves-declared-inputs",
    ):
        assert outcomes[name] == "pass", (name, outcomes[name])
    # A missing primitive is reported truthfully, never silently passed.
    assert outcomes["pause-resume-environment-level"] == "unsupported"
    assert report.environment_digest
    assert report.candidate_workspace and report.evaluator_workspace
    assert report.source_snapshot


def test_conformance_report_digest_binds_the_declared_inputs() -> None:
    """The report's environment digest is the digest of what was declared."""
    report_a = run_conformance_proof(_fake_selector(), allow_fake=True, image="img-a")
    report_b = run_conformance_proof(_fake_selector(), allow_fake=True, image="img-b")
    assert report_a is not None and report_b is not None
    assert report_a.environment_digest != report_b.environment_digest
    expected = cli_mod.environment_digest(
        image="img-a",
        sandbox=cli_mod._sandbox_config(),
        fixtures_digest=cli_mod._fixture_manifest().digest,
    )
    assert report_a.environment_digest == expected


def test_conformance_command_prints_evidence_and_exits_zero() -> None:
    """The command renders identities, costs and the verdict."""
    result = CliRunner().invoke(app, ["eval-workspace", "conformance", "--allow-fake"])
    assert result.exit_code == 0
    assert "environment digest" in result.output
    assert "Conformance holds" in result.output
    assert "SHAPE ONLY" in result.output
    assert "measured: snapshot" in result.output


@requires_bwrap
def test_conformance_holds_on_the_real_backend() -> None:
    """On a host that can build one, the proof passes on a real tier."""
    report = run_conformance_proof(build_selector(), allow_fake=False, image="python:3.12-slim")
    assert report is not None
    assert not report.shape_only
    assert report.tier != "fake"
    assert report.ok, [c for c in report.checks if c.outcome != "pass"]


# --- explicit non-answers ---------------------------------------------------------


def test_no_backend_at_all_is_an_explicit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host with no backend is a loud refusal, not a silent pass."""
    monkeypatch.setattr(cli_mod, "build_selector", lambda **_kwargs: SandboxSelector())
    result = CliRunner().invoke(app, ["eval-workspace", "conformance"])
    assert result.exit_code == 1
    assert "No sandbox backend is available" in result.output


def test_no_suitable_backend_for_the_policy_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake-only host without --allow-fake cannot serve the policy."""
    monkeypatch.setattr(cli_mod, "build_selector", lambda **_kwargs: _fake_selector())
    result = CliRunner().invoke(app, ["eval-workspace", "conformance"])
    assert result.exit_code == 1
    assert "No backend satisfies the conformance policy" in result.output


def test_pick_backend_fake_requires_the_opt_in() -> None:
    """The fake tier is only picked under an explicit --allow-fake."""
    assert _pick_backend(_fake_selector(), allow_fake=False) is None
    assert _pick_backend(SandboxSelector(), allow_fake=True) is None
    picked = _pick_backend(_fake_selector(), allow_fake=True)
    assert picked is not None and picked[1] == "fake"


# --- the proof must be able to fail -------------------------------------------------


def test_drifting_reads_fail_materialization() -> None:
    """A backend whose replay disagrees with its capture must fail the proof."""
    report = _drive(_DriftingBackend())
    outcomes = _outcomes(report)
    assert outcomes["branch-a-materializes"] == "fail"
    assert report is not None and not report.ok


def test_drifting_reads_fail_the_command_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same drift surfaces through the command as exit code 1."""
    monkeypatch.setattr(cli_mod, "FakeSandboxBackend", _DriftingBackend)
    result = CliRunner().invoke(app, ["eval-workspace", "conformance", "--allow-fake"])
    assert result.exit_code == 1
    assert "Conformance FAILED" in result.output


def test_spawn_failure_fails_the_proof() -> None:
    """A provider that cannot spawn is a failed check, and cleanup still runs."""
    report = _drive(_FlakyBackend(spawn_ok=0))
    outcomes = _outcomes(report)
    assert outcomes["environment-spawns"] == "fail"
    assert outcomes["cleanup-bounds-retained-resources"] == "pass"
    assert report is not None and not report.ok


def _detail(report: ConformanceReport, name: str) -> str:
    """The detail string of one named check."""
    return next(check.detail for check in report.checks if check.name == name)


def test_seed_write_failure_fails_provision() -> None:
    """A write fault while seeding the first environment fails the check."""
    report = _drive(_FlakyBackend(write_ok=0))
    outcomes = _outcomes(report)
    assert outcomes["environment-spawns"] == "fail"
    assert "seeding start state raised" in _detail(report, "environment-spawns")
    assert report is not None and not report.ok


def test_materialization_spawn_failure_fails_the_branch() -> None:
    """A provider that dies between source and branch spawn fails branch-a."""
    report = _drive(_FlakyBackend(spawn_ok=1))
    outcomes = _outcomes(report)
    assert outcomes["branch-a-materializes"] == "fail"
    assert report is not None and not report.ok


def test_materialization_write_failure_fails_the_branch() -> None:
    """A write fault while seeding a branch is a failed materialization.

    The budget covers the source seed only — branch-a's seed write fails.
    """
    report = _drive(_FlakyBackend(write_ok=1))
    outcomes = _outcomes(report)
    assert outcomes["branch-a-materializes"] == "fail"
    assert "file operation raised" in _detail(report, "branch-a-materializes")
    assert report is not None and not report.ok


def test_restart_spawn_failure_fails_the_restart_check() -> None:
    """A provider that dies before the restart spawn fails the restart check.

    The budget covers the source(1), branch-a(2) and branch-b(3) spawns —
    the restart spawn is the one that fails.
    """
    report = _drive(_FlakyBackend(spawn_ok=3))
    outcomes = _outcomes(report)
    assert outcomes["restart-preserves-declared-inputs"] == "fail"
    assert report is not None and not report.ok


def test_restart_write_failure_fails_the_restart_check() -> None:
    """A write fault while re-seeding the restarted source fails the check.

    The budget covers the writes that precede it: seed(1), branch-a(2),
    branch-b(3), the isolation-phase branch write(4) — the restart write is
    the one that fails.
    """
    report = _drive(_FlakyBackend(write_ok=4))
    outcomes = _outcomes(report)
    assert outcomes["restart-preserves-declared-inputs"] == "fail"
    assert "file operation raised" in _detail(report, "restart-preserves-declared-inputs")
    assert report is not None and not report.ok


def test_read_failure_fails_snapshot_capture() -> None:
    """A backend that cannot read state cannot snapshot, and says so."""
    report = _drive(_ReadFailingBackend())
    outcomes = _outcomes(report)
    assert outcomes["snapshot-fork-identical-start"] == "fail"
    assert report is not None and not report.ok


def test_cross_branch_leak_fails_isolation() -> None:
    """Writes bleeding across instances fail the isolation check."""
    report = _drive(_CrossLeakingBackend())
    outcomes = _outcomes(report)
    assert outcomes["branch-writes-are-isolated"] == "fail"
    assert report is not None and not report.ok


def test_isolation_fails_when_a_branch_record_lies_about_its_start(
    tmp_path: Path,
) -> None:
    """A branch whose recorded start digest is not the snapshot's must fail.

    `model_copy(update=...)` bypasses validation on purpose: it forges the
    record a buggy (or tampering) writer could produce, where the bytes on
    both sides still agree but the declared lineage no longer does.
    """
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws = c.service.provision(workspace_id="w", project_id="p", image="i", sandbox=c.config)
    c.service.activate(ws.workspace_env_id)
    snap = c.service.snapshot(ws.workspace_env_id, state=cli_mod.START_STATE)
    branch_a = c.service.fork_from_snapshot(snap.snapshot_id, workspace_id="a", project_id="p")
    lying_branch_b = branch_a.model_copy(update={"start_state_digest": "f" * 64})
    inst_source = SandboxInstance(id="i0", backend="fake", isolation_tier="fake")
    inst_a = SandboxInstance(id="i1", backend="fake", isolation_tier="fake")
    inst_b = SandboxInstance(id="i2", backend="fake", isolation_tier="fake")
    c.live = [inst_source, inst_a, inst_b]
    for inst in c.live:
        asyncio.run(c.backend.write_file(inst, c.file(inst, "start"), cli_mod.START_STATE))
    ok = asyncio.run(_check_isolation(c, branch_a, lying_branch_b))
    assert not ok
    assert c.checks[-1].outcome == "fail"
    assert "snapshot" in c.checks[-1].detail


def test_ownership_claim_miss_is_reported(tmp_path: Path) -> None:
    """A pool claim that misses an AVAILABLE fork fails ownership."""
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws = c.service.provision(workspace_id="w", project_id="p", image="i", sandbox=c.config)
    c.service.activate(ws.workspace_env_id)
    c.service.archive(ws.workspace_env_id)  # nothing AVAILABLE to claim
    ok = asyncio.run(_check_ownership(c, ws))
    assert not ok
    assert c.checks[-1].name == "canonical-attempt-ownership"
    assert "missed" in c.checks[-1].detail


def test_ownership_reader_disagreement_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """find_by_owner contradicting the claim fails the ownership check."""
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws_id = _provisioned(c)
    monkeypatch.setattr(type(c.store), "find_by_owner", lambda self, attempt_id: [])
    ok = asyncio.run(_check_ownership(c, c.service.get(ws_id)))
    assert not ok
    assert "disagrees" in c.checks[-1].detail


def test_ownership_steal_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A store of record that lets a second attempt take a held workspace."""
    from maistro.eval_workspace.model import EvalWorkspaceStatus

    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws_id = _provisioned(c)
    held = c.service.get(ws_id)

    def _steal(workspace_env_id: str, **kwargs: Any) -> Any:
        ws = store.get_workspace(workspace_env_id)
        ws.owner_attempt_id = str(kwargs.get("attempt_id"))
        ws.status = EvalWorkspaceStatus.IN_USE
        return ws

    monkeypatch.setattr(c.service, "claim_for_attempt", _steal)
    ok = asyncio.run(_check_ownership(c, held))
    assert not ok
    assert "second attempt claimed" in c.checks[-1].detail


def test_non_owner_release_succeeding_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release that should be refused but is not must fail the check."""
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws_id = _provisioned(c)
    monkeypatch.setattr(c.service, "release_from_attempt", lambda *a, **k: None)
    ok = asyncio.run(_check_ownership(c, c.service.get(ws_id)))
    assert not ok
    assert "non-owner released" in c.checks[-1].detail


def test_warm_pool_overstatement_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A warm-count that overstates the pool fails the measurement."""
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws_id = _provisioned(c)
    digest = c.service.get(ws_id).environment_digest
    monkeypatch.setattr(WorkspacePool, "warm_count", lambda self, d: 0)
    ok = asyncio.run(_check_warm_pool(c, digest))
    assert not ok
    assert c.checks[-1].name == "warm-pool-serves-released-workspace"


def test_digest_disagreement_between_provisions_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two provisions of one input set hashing differently must fail loud."""
    import maistro.eval_workspace.service as service_mod

    calls: list[int] = []

    def _digest(**_kwargs: Any) -> str:
        calls.append(1)
        return f"{len(calls):064d}"

    # provision() computes its digest through the service module's import.
    monkeypatch.setattr(service_mod, "environment_digest", _digest)
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, None)
    pair = asyncio.run(_check_provision_pair(c))
    assert pair is None
    assert c.checks[-1].name == "identical-inputs-identical-digest"
    assert c.checks[-1].outcome == "fail"


def test_ownership_failure_skips_the_warm_pool_but_not_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing ownership check skips the warm measurement, not the run.

    The later phases (pause/resume, restart, cleanup) still execute, so one
    broken check cannot hide the state of the ones after it.
    """
    from maistro.eval_workspace.service import EvalWorkspaceService

    def _broken_claim(self: Any, workspace_env_id: str, **_kwargs: Any) -> Any:
        # Returns the record without taking ownership: find_by_owner will then
        # disagree with the claim — the reader-mismatch failure.
        return self._store.get_workspace(workspace_env_id)

    monkeypatch.setattr(EvalWorkspaceService, "claim_for_attempt", _broken_claim)
    report = _drive(_FlakyBackend())
    outcomes = _outcomes(report)
    assert outcomes["canonical-attempt-ownership"] == "fail"
    assert "warm-pool-serves-released-workspace" not in outcomes
    assert outcomes["restart-preserves-declared-inputs"] == "pass"
    assert outcomes["cleanup-bounds-retained-resources"] == "pass"


def test_forks_that_do_not_share_a_start_state_fail_the_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Branch records that do not compare as a matched pair must fail loud.

    Forges the record a broken fork implementation would write: branch-b
    claims a start state its parent never recorded.
    """
    store = InMemoryEvalWorkspaceStore()
    c = _conformance(store, tmp_path)
    ws_id = _provisioned(c)
    c.live.append(SandboxInstance(id="i0", backend="fake", isolation_tier="fake"))
    asyncio.run(c.backend.write_file(c.live[0], c.file(c.live[0], "start"), b"s"))
    real_fork = c.service.fork_from_workspace

    def _lying_fork(workspace_env_id: str, **kwargs: Any) -> Any:
        child = real_fork(workspace_env_id, **kwargs)
        return child.model_copy(update={"start_state_digest": "e" * 64})

    monkeypatch.setattr(c.service, "fork_from_workspace", _lying_fork)
    forks = asyncio.run(cli_mod._check_fork_pair(c, ws_id))
    assert forks is None
    assert c.checks[-1].name == "snapshot-fork-identical-start"
    assert c.checks[-1].outcome == "fail"


def test_report_ok_ignores_unsupported_but_not_failures() -> None:
    """`unsupported` is an honest answer; only `fail` fails the run."""
    from maistro.cli._eval_workspace import CheckResult

    def _report(outcomes: list[str]) -> ConformanceReport:
        return ConformanceReport(
            backend="b",
            tier="t",
            image="i",
            shape_only=False,
            environment_digest="d" * 64,
            candidate_workspace="c",
            evaluator_workspace="e",
            source_snapshot="s",
            checks=[CheckResult(f"c{n}", o, "") for n, o in enumerate(outcomes)],
        )

    assert _report(["pass", "unsupported"]).ok
    assert not _report(["pass", "fail"]).ok
