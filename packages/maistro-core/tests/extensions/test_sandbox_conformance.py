"""Extension sandbox conformance against real isolation backends (#970, M9-G2).

Issue acceptance: "conformance tests exercise real supported isolation
backends, not mocked policy calls only." Every test here drives the
extension profile → :class:`~maistro.sandbox.SandboxConfig` → real-backend
path — the same ``bwrap`` boundary ``tests/sandbox/test_escape_conformance``
asks its questions of — and skips, loudly, where this host cannot build the
namespace (per SPEC-190: a logged skip is never silently treated as
covered).

What is asserted, on the kernel:

- the profile's CPU / memory / PID / file-size ceilings are read back from
  *inside* the sandbox as the rlimits the kernel will enforce;
- undeclared egress means no connectivity — the extension cannot reach the
  network its grant never declared;
- a scoped grant an unfilterable backend cannot honor fails closed at
  startup instead of approximating with the host namespace whole;
- host paths outside the profile's mounts are not there to read;
- the workspace is the only writable surface, and its contents land in the
  sandbox's own ephemeral workdir, not the host;
- a memory hog and a CPU busy-loop are stopped by the ceilings, live.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import signal
from pathlib import Path

import pytest

from maistro.extensions.isolation import (
    ExtensionSandboxPolicy,
    ExtensionSandboxRunner,
    ExtensionSandboxStartFailure,
    build_sandbox_config,
    select_isolation_profile,
)
from maistro.extensions.manifest import inspect_manifest
from maistro.extensions.trust import TrustReport
from maistro.sandbox.network import EgressGrant, EgressMode
from maistro.sandbox.policy import ExecutionMode
from maistro.sandbox.wiring import build_selector

logger = logging.getLogger("tests.extensions.conformance")

TRUSTED = TrustReport(trusted=True)


def _manifest(permissions: tuple[str, ...]) -> object:
    payload = b"conformance-payload-v1"
    document = {
        "manifest_version": 1,
        "id": "acme.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        },
    }
    return inspect_manifest(json.dumps(document).encode("utf-8"))


def _profile(
    permissions: tuple[str, ...] = ("workspace.read",), **policy_overrides: object
) -> object:
    defaults: dict[str, object] = {
        "min_tier": "bubblewrap",
        "max_memory_mb": 256,
        # RLIMIT_NPROC is counted per *user*, not per sandbox: the ceiling must
        # be one the detection probe can reproduce on hosts where this user
        # already runs dozens of processes, or the tier is honestly evidenced
        # as unavailable and the conformance skips (logged). The value itself
        # is arbitrary; the conformance asserts the sandbox's enforced limit
        # equals whatever the profile declares.
        "max_processes": 1024,
        "max_timeout_s": 120,
        "max_file_mb": 8,
    }
    defaults.update(policy_overrides)
    policy = ExtensionSandboxPolicy(**defaults)  # type: ignore[arg-type]
    return select_isolation_profile(
        _manifest(permissions),  # type: ignore[arg-type]
        granted=permissions,
        trust=TRUSTED,
        policy=policy,
        # The conformance runner is a human at the keyboard: the interactive
        # floor is what admits a Tier-3 backend (ADR-093 decision 6).
        mode=ExecutionMode.INTERACTIVE,
    )


def _real_tiers() -> list[str]:
    """Tiers evidenced by probing this host, strongest first.

    Detection is budgeted with the exact config execution will run under
    (#1328): the Tier-3 probe reproduces the profile's ceilings, so the tier
    it evidences is one this profile can actually get at spawn. On a host
    where the probe cannot reproduce the budget — a busy user colliding with
    the PID ceiling, for instance — the answer is honestly "no" and the
    conformance skips with its logged reason.
    """
    selector = build_selector(sandbox_config=build_sandbox_config(_profile()))  # type: ignore[arg-type]
    return [t for t in selector.available_tiers if t != "fake"]


_REAL_TIERS = _real_tiers()

if not _REAL_TIERS:
    # SPEC-190: log the skip — an unexplained skip must never read as cover.
    logger.warning(
        "extension sandbox conformance skipped: no real isolation backend on "
        "this host (bubblewrap cannot build a namespace or is absent); the "
        "conformance suite is exercised on capable hosts/CI"
    )

requires_real_backend = pytest.mark.skipif(
    not _REAL_TIERS,
    reason="no real isolation backend on this host (logged at module import)",
)


@pytest.fixture()
def runner() -> ExtensionSandboxRunner:
    selector = build_selector(sandbox_config=build_sandbox_config(_profile()))  # type: ignore[arg-type]
    return ExtensionSandboxRunner(selector)


def _limits_argv(timeout_s: int, cpu_cores: float) -> list[str]:
    """Read the rlimits the workload itself sees, from inside the sandbox."""
    cpu_budget = math.ceil(timeout_s * cpu_cores) + 2  # the backend's grace
    code = (
        "import resource; "
        "vals = [resource.getrlimit(w)[0] for w in "
        "(resource.RLIMIT_AS, resource.RLIMIT_NPROC, resource.RLIMIT_CPU, resource.RLIMIT_FSIZE)]; "
        f"print(*vals, {cpu_budget})"
    )
    return ["python3", "-c", code]


@requires_real_backend
class TestResourceLimitsAreReal:
    async def test_profile_ceilings_are_the_kernels_rlimits(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        """The acceptance asks for *actual* CPU/memory/PID limits. The proof
        is read back from inside the sandbox: the rlimits the workload itself
        sees are the profile's ceilings."""
        profile = _profile()
        assert profile is not None
        outcome = await runner.exec(
            profile,
            _limits_argv(timeout_s=int(profile.timeout_s), cpu_cores=float(profile.cpu_cores)),  # type: ignore[arg-type]
        )
        assert outcome.succeeded, f"limits readback failed: {outcome.stderr}"
        as_bytes, nproc, cpu_budget, fsize, _expected = (int(x) for x in outcome.stdout.split())
        assert as_bytes == 256 * 1024 * 1024
        assert nproc == int(profile.max_processes)  # type: ignore[arg-type]
        assert fsize == 8 * 1024 * 1024
        assert cpu_budget == math.ceil(int(profile.timeout_s) * float(profile.cpu_cores)) + 2  # type: ignore[arg-type]

    async def test_a_memory_hog_is_stopped_by_the_ceiling(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        outcome = await runner.exec(
            _profile(),
            ["python3", "-c", "b = bytearray(1024 * 1024 * 1024)"],
        )
        assert outcome.exit_code != 0
        assert "MemoryError" in outcome.stdout + outcome.stderr

    async def test_a_cpu_busy_loop_is_stopped_by_the_budget_not_the_wall_clock(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        """cpu_cores=0.25 over a 20s wall clock is a 5s CPU budget (+grace);
        the kernel stops the loop well before the timeout could."""
        outcome = await runner.exec(
            _profile(max_cpu_cores=0.25, max_timeout_s=20),
            ["bash", "-c", "while :; do :; done"],
            timeout_s=20,
        )
        assert outcome.timed_out is False, "the wall clock fired first — budget not enforced"
        assert outcome.exit_code != 0

    async def test_an_ordinary_workload_still_runs_under_all_ceilings(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        outcome = await runner.exec(_profile(), ["echo", "conformance"])
        assert outcome.succeeded
        assert outcome.stdout.strip() == "conformance"


@requires_real_backend
class TestNetworkIsDeniedUntilDeclared:
    async def test_undeclared_egress_cannot_reach_the_network(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        """The grant declares no network, so the sandbox has no interface:
        the connect attempt fails inside the boundary."""
        profile = _profile()  # workspace.read only
        assert profile.egress.mode is EgressMode.DENY
        outcome = await runner.exec(
            profile,
            [
                "python3",
                "-c",
                "import socket; s = socket.socket(); s.settimeout(5); "
                "s.connect(('example.com', 80))",
            ],
        )
        assert outcome.exit_code != 0

    async def test_a_scoped_grant_an_unfilterable_backend_cannot_honor_fails_closed(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        """bubblewrap has two network states: none, or the host's whole. A
        scoped grant must be refused at startup — not granted wide and
        called scoped."""
        profile = _profile(
            ("network.outbound",),
            egress=EgressGrant(
                mode=EgressMode.SCOPED, allow=("api.example.com",), reason="operator grant"
            ),
        )
        with pytest.raises(ExtensionSandboxStartFailure, match="cannot filter"):
            await runner.exec(profile, ["curl", "https://api.example.com"])


@requires_real_backend
class TestFilesystemBoundary:
    async def test_host_paths_outside_the_profile_are_not_there(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        outcome = await runner.exec(_profile(), ["cat", "/etc/hostname"])
        assert outcome.exit_code != 0
        assert "No such file" in outcome.stdout + outcome.stderr

    async def test_the_runtime_binds_are_read_only(self, runner: ExtensionSandboxRunner) -> None:
        outcome = await runner.exec(_profile(), ["touch", "/usr/escape"])
        assert outcome.exit_code != 0
        assert "Read-only" in outcome.stdout + outcome.stderr

    async def test_writes_land_in_the_sandboxes_own_workspace(
        self, runner: ExtensionSandboxRunner, tmp_path: Path
    ) -> None:
        """Without ``filesystem.write`` the only writable host path is the
        sandbox's own ephemeral workdir — and the file is there, on the
        host, under the backend's workdir root."""
        selector = build_selector(sandbox_config=build_sandbox_config(_profile()))  # type: ignore[arg-type]
        tier = selector.available_tiers[0]
        backend = selector._backends[tier]
        config = build_sandbox_config(_profile())  # type: ignore[arg-type]
        instance = await backend.spawn(config=config)
        try:
            result = await backend.exec(
                instance, ["bash", "-c", "echo written > /work/proof"], timeout_s=30
            )
            assert result.exit_code == 0
            workdir = Path(str(instance.metadata["workdir"]))
            assert (workdir / "proof").read_text().strip() == "written"
        finally:
            await backend.destroy(instance)


@requires_real_backend
class TestWorkspaceStorageRule:
    async def test_the_file_size_ceiling_stops_a_runaway_write(
        self, runner: ExtensionSandboxRunner
    ) -> None:
        """max_file_mb=8 is the temporary/workspace storage rule, enforced as
        RLIMIT_FSIZE: the write dies on SIGXFSZ (bwrap reports a signal death
        as 128+signal) with nothing on the streams — the kernel stopped it."""
        outcome = await runner.exec(
            _profile(),
            ["dd", "if=/dev/zero", "of=/work/big", "bs=1M", "count=64"],
        )
        assert outcome.exit_code == 128 + int(signal.SIGXFSZ)
        assert outcome.timed_out is False
