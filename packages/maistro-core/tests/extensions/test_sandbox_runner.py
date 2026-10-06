"""The extension sandbox runner: fail-closed startup and attributable violations (#970).

The runner is the fail-closed path between a profile and a real backend.
These tests pin its behavior with tier-labeled stub backends — the same
idiom ``tests/sandbox/test_selector.py`` uses, because what is under test
here is the *runner's* contract (selection refusal becomes a typed startup
failure, spawn failure never falls back to the trusted tier, boundary events
are attributed to an extension identity), not the kernel boundary itself.
That is the conformance suite's job (``test_sandbox_conformance.py``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from maistro.extensions.isolation import (
    ExtensionIsolationProfile,
    ExtensionSandboxExecutionFailure,
    ExtensionSandboxPolicy,
    ExtensionSandboxRunner,
    ExtensionSandboxStartFailure,
    InProcessExtensionLoader,
    SandboxViolationLog,
    ViolationKind,
    select_isolation_profile,
)
from maistro.extensions.manifest import inspect_manifest
from maistro.extensions.trust import TrustReport
from maistro.extensions.types import ExtensionInstallRecord, ExtensionState
from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.network import EgressGrant, EgressMode
from maistro.sandbox.policy import ExecutionMode
from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance
from maistro.sandbox.selector import SandboxSelector

TRUSTED = TrustReport(trusted=True)


def _manifest(
    permissions: tuple[str, ...] = ("workspace.read",),
    publisher: str = "acme",
) -> object:
    payload = b"runner-payload-v1"
    document = {
        "manifest_version": 1,
        "id": f"{publisher}.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": publisher,
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        },
    }
    return inspect_manifest(json.dumps(document).encode("utf-8"))


def _policy(**overrides: object) -> ExtensionSandboxPolicy:
    defaults: dict[str, object] = {
        "min_tier": "bubblewrap",
        "egress": EgressGrant(mode=EgressMode.SCOPED, allow=("api.example.com",), reason="op"),
    }
    defaults.update(overrides)
    return ExtensionSandboxPolicy(**defaults)  # type: ignore[arg-type]


def _profile(**kwargs: object) -> ExtensionIsolationProfile:
    granted = kwargs.pop("granted", ("workspace.read",))
    policy = kwargs.pop("policy", None) or _policy(**kwargs)
    return select_isolation_profile(
        _manifest(tuple(granted)),  # type: ignore[arg-type]
        granted=tuple(granted),  # type: ignore[arg-type]
        trust=TRUSTED,
        policy=policy,  # type: ignore[arg-type]
        # Interactive mode: these tests run against bubblewrap-tier stubs, and
        # an unstated mode would raise the floor to gVisor (ADR-093 decision 6)
        # and refuse the tier the stubs are registered at.
        mode=ExecutionMode.INTERACTIVE,
    )


class _StubBackend(FakeSandboxBackend):
    """A fake backend labeled with the tier it is registered at.

    The selector refuses relabeling a weaker backend as stronger, so these
    tests declare ``bubblewrap`` and register at ``bubblewrap`` — the runner
    then exercises its real selection path against a backend that answers
    immediately instead of building a namespace. The stub claims scoped-
    egress support so the runner tests with a scoped policy reach the exec
    path; the refusal half (a backend that cannot filter) has its own test
    below and its real-backend proof in the conformance suite.
    """

    supports_scoped_egress = True

    def __init__(self, tier: str = "bubblewrap") -> None:
        super().__init__()
        self.tier = tier
        self.calls: list[tuple[str, str]] = []

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self.calls.append(("spawn", config.min_isolation))
        return await super().spawn(config=config)

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        self.calls.append(("exec", command[0] if command else ""))
        return await super().exec(instance, command, timeout_s=timeout_s)

    async def destroy(self, instance: SandboxInstance) -> None:
        self.calls.append(("destroy", instance.id))
        await super().destroy(instance)


class _ExplodingSpawnBackend(_StubBackend):
    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        raise RuntimeError("namespace creation failed: Resource temporarily unavailable")


class _ExplodingExecBackend(_StubBackend):
    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        raise RuntimeError("backend vanished mid-execution")


def _runner(backend: object, **kwargs: object) -> ExtensionSandboxRunner:
    selector = SandboxSelector()
    selector.register("bubblewrap", backend)  # type: ignore[arg-type]
    defaults: dict[str, object] = {
        "clock": lambda: datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return ExtensionSandboxRunner(selector, **defaults)  # type: ignore[arg-type]


class TestStartupFailsClosed:
    async def test_no_qualifying_backend_is_a_typed_startup_failure(self) -> None:
        runner = ExtensionSandboxRunner(SandboxSelector())
        with pytest.raises(ExtensionSandboxStartFailure, match="did not run"):
            await runner.exec(_profile(), ["echo", "hi"])

    async def test_spawn_failure_is_a_typed_startup_failure(self) -> None:
        runner = _runner(_ExplodingSpawnBackend())
        with pytest.raises(ExtensionSandboxStartFailure, match="Resource temporarily"):
            await runner.exec(_profile(), ["echo", "hi"])

    async def test_startup_failure_is_recorded_against_the_extension(self) -> None:
        log = SandboxViolationLog()
        runner = _runner(_ExplodingSpawnBackend(), violations=log)
        with pytest.raises(ExtensionSandboxStartFailure):
            await runner.exec(_profile(), ["echo", "hi"])
        assert len(log) == 1
        (violation,) = log.all()
        assert violation.extension_id == "acme.chart_tools"
        assert violation.version == "1.4.0"
        assert violation.kind is ViolationKind.SANDBOX_START_FAILURE
        assert violation.sandbox_id is None

    async def test_startup_failure_is_logged_operationally(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        runner = _runner(_ExplodingSpawnBackend())
        with (
            caplog.at_level(logging.WARNING, logger="maistro.extensions.isolation"),
            pytest.raises(ExtensionSandboxStartFailure),
        ):
            await runner.exec(_profile(), ["echo", "hi"])
        assert any(
            "extension_sandbox_violation" in r.message and "acme.chart_tools" in r.getMessage()
            for r in caplog.records
        )

    async def test_sandbox_failure_never_falls_back_to_the_trusted_tier(self) -> None:
        """The policy *would* allow this publisher in process — but the grant
        is elevated risk (network), so the profile is sandboxed, and when the
        sandbox cannot start the run fails closed. The in-process tier is a
        selection outcome, not a substitute reached after a sandbox failure."""
        policy = _policy(allow_in_process=True, in_process_publishers=frozenset({"acme"}))
        profile = _profile(granted=("network.outbound",), policy=policy)
        assert profile.in_process is False  # elevated risk: ineligible in process
        runner = ExtensionSandboxRunner(SandboxSelector())
        with pytest.raises(ExtensionSandboxStartFailure):
            await runner.exec(profile, ["echo", "hi"])

    async def test_a_scoped_grant_a_backend_cannot_filter_fails_closed(self) -> None:
        """An unfilterable backend must refuse a scoped grant, not approximate
        it with the host network whole — for extensions that refusal is a
        fail-closed startup, never a wider grant."""

        class _UnfilterableBackend(_StubBackend):
            supports_scoped_egress = False

        runner = _runner(_UnfilterableBackend())
        with pytest.raises(ExtensionSandboxStartFailure, match="cannot filter egress"):
            await runner.exec(_profile(granted=("network.outbound",)), ["curl", "x"])

    async def test_exec_failure_destroys_and_raises_typed_failure(self) -> None:
        backend = _ExplodingExecBackend()
        runner = _runner(backend)
        with pytest.raises(ExtensionSandboxExecutionFailure) as excinfo:
            await runner.exec(_profile(), ["echo", "hi"])
        # the failed sandbox did not leak: destroy ran despite the exec error
        assert backend.calls
        assert backend.calls[-1][0] == "destroy"
        assert list(backend._instances) == []
        # not a startup failure: the sandbox was up, so the message must not
        # claim extension code never ran (a caller retrying on that basis
        # would rerun code whose side effects already happened)
        assert not isinstance(excinfo.value, ExtensionSandboxStartFailure)
        assert "did not run" not in str(excinfo.value)
        assert "may already have run" in str(excinfo.value)

    async def test_cancellation_mid_exec_still_destroys(self) -> None:
        """CancelledError is a BaseException, not an ``except Exception``
        match — without a cancellation-safe teardown a cancel arriving while
        exec() is suspended skips destroy and leaves the sandbox child and its
        registration behind."""

        class _HangingExecBackend(_StubBackend):
            async def exec(
                self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
            ) -> ExecResult:
                await asyncio.Event().wait()  # cancelled by the test, never returns

        backend = _HangingExecBackend()
        runner = _runner(backend)
        task = asyncio.create_task(runner.exec(_profile(), ["echo", "hi"]))
        await asyncio.sleep(0)  # let spawn+exec start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # teardown still ran despite cancellation, and nothing leaked
        assert backend.calls[-1][0] == "destroy"
        assert list(backend._instances) == []


class TestExecutionPath:
    async def test_happy_path_spawns_execs_destroys_in_order(self) -> None:
        backend = _StubBackend()
        runner = _runner(backend)
        outcome = await runner.exec(_profile(), ["echo", "hello"])
        assert [step for step, _ in backend.calls] == ["spawn", "exec", "destroy"]
        assert outcome.succeeded is True
        assert outcome.stdout.strip() == "hello"
        assert outcome.tier == "bubblewrap"  # the selector's adjudicated tier
        assert outcome.backend == "fake"  # the serving backend's own name (a stub)
        assert outcome.sandbox_id

    async def test_outcome_carries_the_extension_identity_and_profile_facts(self) -> None:
        profile = _profile(granted=("network.outbound",))
        outcome = await _runner(_StubBackend()).exec(profile, ["true"])
        assert outcome.extension_id == "acme.chart_tools"
        assert outcome.version == "1.4.0"
        assert outcome.egress_mode is EgressMode.SCOPED

    async def test_an_in_process_profile_cannot_be_routed_at_a_sandbox(self) -> None:
        policy = _policy(allow_in_process=True, in_process_publishers=frozenset({"acme"}))
        profile = _profile(granted=("workspace.read",), policy=policy)
        assert profile.in_process is True
        runner = _runner(_StubBackend())
        with pytest.raises(ValueError, match="run_in_process"):
            await runner.exec(profile, ["echo", "hi"])


class TestViolationAttribution:
    @pytest.mark.parametrize(
        ("exit_code", "expected_fragment"),
        [
            (-9, "SIGKILL"),
            (-24, "SIGXCPU"),
            (-25, "SIGXFSZ"),
        ],
    )
    async def test_kernel_kill_signals_become_attributed_violations(
        self, exit_code: int, expected_fragment: str
    ) -> None:
        class _KilledBackend(_StubBackend):
            async def exec(
                self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
            ) -> ExecResult:
                return ExecResult(exit_code=exit_code, stdout="", stderr="killed", duration_ms=5)

        log = SandboxViolationLog()
        outcome = await _runner(_KilledBackend(), violations=log).exec(_profile(), ["busy-loop"])
        assert outcome.succeeded is False
        assert len(outcome.violations) == 1
        violation = outcome.violations[0]
        assert violation.kind is ViolationKind.RESOURCE_LIMIT_EXCEEDED
        assert violation.extension_id == "acme.chart_tools"
        assert violation.version == "1.4.0"
        assert violation.sandbox_id == outcome.sandbox_id
        assert expected_fragment in violation.detail
        assert log.violations_for("acme.chart_tools", "1.4.0") == (violation,)

    async def test_an_ordinary_nonzero_exit_is_not_a_boundary_violation(self) -> None:
        """A workload's own failure is reported on the outcome; the violation
        log stays reserved for kernel-evidenced boundary events."""
        log = SandboxViolationLog()
        outcome = await _runner(_StubBackend(), violations=log).exec(_profile(), ["false"])
        assert outcome.exit_code != 0
        assert outcome.succeeded is False
        assert outcome.violations == ()
        assert len(log) == 0

    async def test_a_timed_out_workload_is_recorded(self) -> None:
        class _TimedOutBackend(_StubBackend):
            async def exec(
                self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
            ) -> ExecResult:
                return ExecResult(
                    exit_code=124, stdout="", stderr="timeout", duration_ms=30, timed_out=True
                )

        log = SandboxViolationLog()
        outcome = await _runner(_TimedOutBackend(), violations=log).exec(_profile(), ["while", ":"])
        assert outcome.timed_out is True
        (violation,) = outcome.violations
        assert "wall-clock timeout" in violation.detail

    async def test_the_violation_log_is_bounded(self) -> None:
        log = SandboxViolationLog(capacity=2)
        profile = _profile()
        runner = _runner(_KilledOnceBackend(), violations=log)
        for _ in range(5):
            await runner.exec(profile, ["x"])
        assert len(log) == 2


class _KilledOnceBackend(_StubBackend):
    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        return ExecResult(exit_code=-9, stdout="", stderr="killed", duration_ms=1)


class TestRepeatedViolationEscalation:
    async def test_repeated_violations_escalate_to_a_named_operational_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The health evidence a quarantine flow (M9-G4) consumes: the third
        boundary event for one extension/version stops being a per-event line
        and becomes a named candidate-for-quarantine warning."""
        runner = _runner(_KilledOnceBackend())
        with caplog.at_level(logging.WARNING, logger="maistro.extensions.isolation"):
            for _ in range(3):
                await runner.exec(_profile(), ["x"])
        escalated = [
            r for r in caplog.records if "extension_repeated_sandbox_violations" in r.getMessage()
        ]
        assert len(escalated) == 1
        assert "acme.chart_tools" in escalated[0].getMessage()
        assert "M9-G4" in escalated[0].getMessage()

    async def test_escalation_fires_once_per_threshold_not_every_time(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        runner = _runner(_KilledOnceBackend())
        with caplog.at_level(logging.WARNING, logger="maistro.extensions.isolation"):
            for _ in range(5):
                await runner.exec(_profile(), ["x"])
        escalated = [
            r for r in caplog.records if "extension_repeated_sandbox_violations" in r.getMessage()
        ]
        assert len(escalated) == 1

    async def test_violations_for_queries_by_identity_and_version(self) -> None:
        log = SandboxViolationLog()
        runner = _runner(_KilledOnceBackend(), violations=log)
        await runner.exec(_profile(), ["x"])
        await runner.exec(_profile(), ["x"])
        assert len(log.violations_for("acme.chart_tools")) == 2
        assert len(log.violations_for("acme.chart_tools", "1.4.0")) == 2
        assert log.violations_for("acme.chart_tools", "9.9.9") == ()
        assert log.violations_for("other.extension") == ()


class TestInProcessExecution:
    def _in_process_profile(self) -> ExtensionIsolationProfile:
        policy = _policy(allow_in_process=True, in_process_publishers=frozenset({"acme"}))
        return _profile(granted=("workspace.read",), policy=policy)

    async def test_runs_a_sync_callable(self) -> None:
        outcome = await _runner(_StubBackend()).run_in_process(
            self._in_process_profile(), lambda: "greeting"
        )
        assert outcome == "greeting"

    async def test_runs_an_async_callable(self) -> None:
        async def activate() -> int:
            return 42

        result = await _runner(_StubBackend()).run_in_process(self._in_process_profile(), activate)
        assert result == 42

    async def test_in_process_start_and_completion_are_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="maistro.extensions.isolation"):
            await _runner(_StubBackend()).run_in_process(self._in_process_profile(), lambda: None)
        messages = [r.getMessage() for r in caplog.records]
        assert any("extension_in_process_start" in m for m in messages)
        assert any("extension_in_process_done" in m for m in messages)

    async def test_a_sandboxed_profile_cannot_enter_the_trusted_tier(self) -> None:
        profile = _profile()  # no in-process policy: sandboxed
        runner = _runner(_StubBackend())
        with pytest.raises(Exception, match="never a fallback"):
            await runner.run_in_process(profile, lambda: None)

    async def test_exceptions_from_the_callable_still_log_completion(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom() -> None:
            raise RuntimeError("extension crashed")

        with (
            caplog.at_level(logging.INFO, logger="maistro.extensions.isolation"),
            pytest.raises(RuntimeError, match="extension crashed"),
        ):
            await _runner(_StubBackend()).run_in_process(self._in_process_profile(), boom)
        assert any("extension_in_process_done" in r.getMessage() for r in caplog.records)


class TestInProcessExtensionLoader:
    """The trusted tier's ExtensionCodeLoader: activation through the
    governed install seam, with the runner's evidence path around it."""

    def _loader(self, **kwargs: object) -> InProcessExtensionLoader:
        runner = kwargs.pop("runner", None) or _runner(_StubBackend())
        profile = kwargs.pop("profile", None) or self._in_process_profile_public()
        activate = kwargs.pop("activate", None) or (lambda record, payload: "activated")
        return InProcessExtensionLoader(runner, profile, activate)  # type: ignore[arg-type]

    def _in_process_profile_public(self) -> ExtensionIsolationProfile:
        policy = _policy(allow_in_process=True, in_process_publishers=frozenset({"acme"}))
        return _profile(granted=("workspace.read",), policy=policy)

    def _record(self) -> ExtensionInstallRecord:
        return ExtensionInstallRecord(
            install_id="i-1",
            org_id="org-1",
            workspace_id="",
            extension_id="acme.chart_tools",
            version="1.4.0",
            manifest=_manifest(),  # type: ignore[arg-type]
            state=ExtensionState.AUTHORIZED,
            requested_permissions=("workspace.read",),
        )

    async def test_load_activates_through_the_in_process_path(self) -> None:
        seen: dict[str, object] = {}

        async def activate(record: ExtensionInstallRecord, payload: bytes) -> str:
            seen["payload"] = payload
            return "extension-up"

        loader = self._loader(activate=activate)
        loaded = await loader.load(self._record(), b"payload-bytes")
        assert loaded.extension_id == "acme.chart_tools"
        assert loaded.version == "1.4.0"
        assert seen["payload"] == b"payload-bytes"
        assert loaded.result == "extension-up"

    async def test_a_sandboxed_profile_is_refused_at_wiring_time(self) -> None:
        runner = _runner(_StubBackend())
        with pytest.raises(Exception, match="requires an in-process profile"):
            InProcessExtensionLoader(
                runner, _profile(granted=("workspace.read",)), lambda r, p: None
            )

    async def test_a_mismatched_record_is_refused_before_activation(self) -> None:
        loader = self._loader()
        wrong = replace(self._record(), version="2.0.0")
        with pytest.raises(Exception, match="is wired for"):
            await loader.load(wrong, b"payload")
