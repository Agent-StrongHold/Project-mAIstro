"""Reusable integration contracts for M1 cross-product parity (#459).

This module is test/evidence code only. It deliberately does not emulate a
product runtime or fill a missing convergence seam. Source probes remain
optional development diagnostics; strict closeout evidence requires a real
producer and observer callback and records an unavailable seam as a failure.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]


class DependencyUnavailable(AssertionError):
    """A named upstream convergence dependency has not landed on this branch."""


class ParityContractError(AssertionError):
    """A product projection diverged from canonical execution identity/lifecycle."""


class ScenarioAbstained(AssertionError):
    """A required product scenario did not execute its real producer boundary."""


class CloseoutFailure(AssertionError):
    """The strict M1 closeout report contains a failed required scenario."""


class ParityMode(StrEnum):
    """The development diagnostic mode and the fail-closed M1 closeout mode."""

    DEVELOPMENT = "development"
    M1_CLOSEOUT = "m1-closeout"


@dataclass(frozen=True, slots=True)
class SourceProbe:
    """Repository-visible evidence that a dependency's public seam has landed."""

    path: str
    required_tokens: tuple[str, ...] = ()
    forbidden_tokens: tuple[str, ...] = ()

    def failures(self) -> list[str]:
        source = REPO_ROOT / self.path
        if not source.exists():
            return [f"missing {self.path}"]

        text = source.read_text(encoding="utf-8")
        failures: list[str] = []
        for token in self.required_tokens:
            if token not in text:
                failures.append(f"{self.path} lacks {token!r}")
        for token in self.forbidden_tokens:
            if token in text:
                failures.append(f"{self.path} still contains {token!r}")
        return failures


@dataclass(frozen=True, slots=True)
class Dependency:
    key: str
    issue: int
    pr: int | None
    description: str
    probes: tuple[SourceProbe, ...]

    @property
    def label(self) -> str:
        owner = f"issue #{self.issue}"
        if self.pr is not None:
            owner = f"PR #{self.pr}"
        return f"{self.key} ({owner})"

    def failures(self) -> list[str]:
        failures: list[str] = []
        for probe in self.probes:
            failures.extend(probe.failures())
        return failures

    def available(self) -> bool:
        return not self.failures()


@dataclass(frozen=True, slots=True)
class DependencyAssessment:
    """Executable or explicitly blocked state for one parity scenario."""

    ready: bool
    blockers: tuple[str, ...]


BUILDERS = Dependency(
    key="Builders canonical execution",
    issue=734,
    pr=744,
    description="Builders exposes its canonical Graph/Run execution adapter.",
    probes=(
        SourceProbe(
            "packages/maistro-core/src/maistro/builders/graph_executor.py",
            required_tokens=("class CanonicalGraphPipelineExecutor",),
        ),
    ),
)

EVOLVE = Dependency(
    key="Evolve canonical execution",
    issue=51,
    pr=733,
    description="The shipped Evolve cycle returns and records its canonical Run identity.",
    probes=(
        SourceProbe(
            "packages/hive-conductor/backend/services/evolution.py",
            required_tokens=("run_canonical_evolution_cycle", "last_run_id"),
        ),
    ),
)

SCHEDULER = Dependency(
    key="scheduler canonical admission",
    issue=231,
    pr=759,
    description="The live scheduler delegates occurrence admission to ScheduleRunAdmitter.",
    probes=(
        SourceProbe(
            "packages/hive-conductor/backend/services/scheduler.py",
            required_tokens=("ScheduleRunAdmitter", "_canonical_admitter"),
        ),
    ),
)

CONDUCTOR_INSPECTION = Dependency(
    key="Conductor canonical inspection plane",
    issue=1036,
    pr=None,
    description=(
        "The #1036 inspection/control boundary must resolve canonical Run evidence "
        "instead of a product-private dag_run_store authority."
    ),
    probes=(
        SourceProbe(
            "packages/hive-conductor/backend/routes/dag_runs.py",
            required_tokens=("run_store",),
            forbidden_tokens=("from services.dag_run_store import get_dag_run_store",),
        ),
    ),
)

ONTOLOGY = Dependency(
    key="importable interoperability ontology",
    issue=458,
    pr=870,
    description="maistro.interop exposes the executable shared identity registry.",
    probes=(
        SourceProbe(
            "packages/maistro-core/src/maistro/interop/__init__.py",
            required_tokens=("INTEROP_ONTOLOGY_V1",),
        ),
    ),
)

GOLDEN_BASELINES = Dependency(
    key="golden behavioral baselines",
    issue=463,
    pr=869,
    description="The immutable #463 fixtures and fail-closed matcher are available.",
    probes=(
        SourceProbe(
            "tests/golden_baselines/contract.py",
            required_tokens=("assert_observation_matches",),
        ),
        SourceProbe("tests/golden_baselines/manifest.json"),
    ),
)

_DEPENDENCY_LIST: Final = (
    BUILDERS,
    EVOLVE,
    SCHEDULER,
    CONDUCTOR_INSPECTION,
    ONTOLOGY,
    GOLDEN_BASELINES,
)
DEPENDENCIES: Final = {dependency.key: dependency for dependency in _DEPENDENCY_LIST}


def dependency_assessment(*dependencies: Dependency) -> DependencyAssessment:
    """Return an assertion-backed dependency state for an executable scenario.

    A blocked scenario is only accepted when every blocker is tied to a named
    issue/PR and a concrete missing/legacy source seam. This is intentionally
    not a pytest skip or expected-failure mechanism. Once the probes pass the
    caller must execute the scenario's real assertions.
    """
    blockers: list[str] = []
    for dependency in dependencies:
        failures = dependency.failures()
        if not failures:
            continue

        owner = f"issue #{dependency.issue}"
        if dependency.pr is not None:
            owner = f"PR #{dependency.pr}"
        assert dependency.key.strip(), "unavailable dependency must have a stable name"
        assert dependency.issue > 0, f"{dependency.key} must name a tracking issue"
        assert failures, f"{dependency.label} cannot be unavailable without probe evidence"
        detail = "; ".join(failures)
        blockers.append(f"{dependency.key}: waiting on {owner}: {detail}")

    assessment = DependencyAssessment(ready=not blockers, blockers=tuple(blockers))
    assert assessment.ready is (not assessment.blockers)
    return assessment


def require_dependencies(*dependencies: Dependency) -> None:
    """Fail loudly if code reaches a dependency-owned public seam too early."""
    assessment = dependency_assessment(*dependencies)
    if assessment.blockers:
        raise DependencyUnavailable(" | ".join(assessment.blockers))


@dataclass(frozen=True, slots=True)
class ScenarioExecution:
    """The real product observation returned by an executed scenario."""

    observation: Mapping[str, Any] | None = None


ScenarioCallable = Callable[[], ScenarioExecution | Awaitable[ScenarioExecution]]
ScenarioValidator = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class ParityScenario:
    """One required producer -> canonical spine -> observer/control scenario."""

    name: str
    dependencies: tuple[Dependency, ...]
    execute: ScenarioCallable
    validate_observation: ScenarioValidator | None = None


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    """Machine-readable result for one required scenario."""

    name: str
    status: str
    executed: bool
    blockers: tuple[str, ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.name,
            "status": self.status,
            "executed": self.executed,
            "blockers": list(self.blockers),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class CloseoutReport:
    """The complete strict report; no strict scenario can be BLOCKED-as-green."""

    evidence: tuple[ScenarioEvidence, ...]

    @property
    def passed(self) -> bool:
        return bool(self.evidence) and all(item.status == "PASSED" for item in self.evidence)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": ParityMode.M1_CLOSEOUT.value,
            "scenarios": [item.as_dict() for item in self.evidence],
            "passed": self.passed,
        }


def parity_mode(value: str | None = None) -> ParityMode:
    """Resolve the explicit mode switch used by the closeout invocation."""
    raw = value if value is not None else os.environ.get("MAISTRO_PARITY_MODE", "development")
    try:
        return ParityMode(raw)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ParityMode)
        raise ValueError(f"MAISTRO_PARITY_MODE must be one of: {allowed}") from exc


def _emit_evidence(evidence: ScenarioEvidence) -> None:
    """Emit one JSON object per scenario for CI log/artifact consumers."""
    print(f"M1_PARITY_EVIDENCE {json.dumps(evidence.as_dict(), sort_keys=True)}")


async def execute_scenario(
    scenario: ParityScenario,
    *,
    mode: ParityMode | None = None,
    raise_on_failure: bool = True,
) -> ScenarioEvidence:
    """Run one scenario, converting every strict abstention into a failure."""
    selected_mode = mode or parity_mode()
    assessment = dependency_assessment(*scenario.dependencies)
    if assessment.blockers:
        status = "FAILED" if selected_mode is ParityMode.M1_CLOSEOUT else "BLOCKED"
        evidence = ScenarioEvidence(
            name=scenario.name,
            status=status,
            executed=False,
            blockers=assessment.blockers,
        )
        _emit_evidence(evidence)
        if selected_mode is ParityMode.M1_CLOSEOUT and raise_on_failure:
            raise DependencyUnavailable(" | ".join(assessment.blockers))
        return evidence

    try:
        result = scenario.execute()
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ScenarioExecution):
            raise ScenarioAbstained(
                f"{scenario.name} returned no real ScenarioExecution observation"
            )
        if scenario.validate_observation is not None:
            if result.observation is None:
                raise ScenarioAbstained(f"{scenario.name} returned no product observation")
            scenario.validate_observation(result.observation)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        status = "FAILED" if selected_mode is ParityMode.M1_CLOSEOUT else "BLOCKED"
        evidence = ScenarioEvidence(
            name=scenario.name,
            status=status,
            executed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        _emit_evidence(evidence)
        if selected_mode is ParityMode.M1_CLOSEOUT and raise_on_failure:
            raise
        return evidence

    evidence = ScenarioEvidence(name=scenario.name, status="PASSED", executed=True)
    _emit_evidence(evidence)
    return evidence


def execute_scenario_sync(
    scenario: ParityScenario,
    *,
    mode: ParityMode | None = None,
) -> ScenarioEvidence:
    """Synchronous wrapper for ordinary pytest tests and small CI probes."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute_scenario(scenario, mode=mode))
    raise RuntimeError("execute_scenario_sync cannot run inside an active event loop")


async def execute_closeout(scenarios: tuple[ParityScenario, ...]) -> CloseoutReport:
    """Execute every required scenario and raise only after all evidence is emitted."""
    evidence: list[ScenarioEvidence] = []
    for scenario in scenarios:
        evidence.append(
            await execute_scenario(
                scenario,
                mode=ParityMode.M1_CLOSEOUT,
                raise_on_failure=False,
            )
        )
    report = CloseoutReport(tuple(evidence))
    if not report.passed:
        raise CloseoutFailure(json.dumps(report.as_dict(), sort_keys=True))
    return report


@dataclass(slots=True)
class DurableIntegrationProfile:
    """The supported SQLite execution-spine profile used by parity scenarios."""

    db_path: Path
    connection: Any
    workspace_id: str
    project_id: str
    project_store: Any
    run_store: Any
    task_admitter: Any
    template_store: Any
    schedule_store: Any
    continuation_store: Any

    async def close(self) -> None:
        await self.connection.close()


async def open_durable_profile(db_path: Path, *, workspace_id: str) -> DurableIntegrationProfile:
    """Wire the real durable spine through the repository's supported factory."""
    import aiosqlite

    from maistro.runs.wiring import wire_execution_spine

    connection = await aiosqlite.connect(db_path)
    stores = await wire_execution_spine(connection, workspace_id=workspace_id)
    (
        project_store,
        run_store,
        task_admitter,
        template_store,
        schedule_store,
        continuation_store,
    ) = stores
    project = await project_store.root_for_workspace(workspace_id)
    if project is None:
        await connection.close()
        message = f"durable profile did not create Root Project for {workspace_id!r}"
        raise ParityContractError(message)

    return DurableIntegrationProfile(
        db_path=db_path,
        connection=connection,
        workspace_id=workspace_id,
        project_id=project.project_id,
        project_store=project_store,
        run_store=run_store,
        task_admitter=task_admitter,
        template_store=template_store,
        schedule_store=schedule_store,
        continuation_store=continuation_store,
    )


_SHARED_ID_FIELDS: Final = (
    "workspace_id",
    "project_id",
    "graph_id",
    "run_id",
    "node_run_id",
    "attempt_id",
    "event_id",
    "invocation_id",
    "artifact_id",
    "provenance_id",
)
_RUN_ID_ALIASES: Final = ("product_run_id", "execution_run_id", "job_run_id")
_TERMINAL_STATUSES: Final = frozenset({"completed", "failed", "cancelled", "timed_out"})


def assert_identity_projection(
    canonical: Mapping[str, object],
    projected: Mapping[str, object],
) -> None:
    """Require one identity and one terminal lifecycle authority across a projection."""
    compared = 0
    for field in _SHARED_ID_FIELDS:
        expected = canonical.get(field)
        if expected is None:
            continue
        compared += 1
        actual = projected.get(field)
        if actual != expected:
            message = f"{field} diverged: canonical {expected!r}, product projection {actual!r}"
            raise ParityContractError(message)

    if compared == 0:
        message = "canonical observation contains no shared identity to compare"
        raise ParityContractError(message)

    run_id = canonical.get("run_id")
    if run_id is not None:
        for alias in _RUN_ID_ALIASES:
            if alias in projected and projected[alias] != run_id:
                product_id = projected[alias]
                message = f"{alias} creates a second Run identity: {product_id!r} != {run_id!r}"
                raise ParityContractError(message)

    canonical_status = canonical.get("status")
    product_terminal = projected.get("terminal_state")
    terminal_diverged = (
        canonical_status in _TERMINAL_STATUSES
        and product_terminal is not None
        and product_terminal != canonical_status
    )
    if terminal_diverged:
        prefix = "product-private terminal state diverged from canonical Run status"
        message = f"{prefix}: {product_terminal!r} != {canonical_status!r}"
        raise ParityContractError(message)


def assert_ontology_identity_projection(
    canonical: Mapping[str, object],
    projected: Mapping[str, object],
) -> None:
    """Use #458's executable ontology as the shared-identity field authority."""
    require_dependencies(ONTOLOGY)
    ontology_module = importlib.import_module("maistro.interop")
    ontology = ontology_module.INTEROP_ONTOLOGY_V1

    concepts = (
        "Workspace",
        "Project",
        "Graph",
        "Run",
        "NodeRun",
        "Attempt",
        "Invocation",
    )
    observed = 0
    for concept in concepts:
        identity = ontology.concept(concept).identity
        if canonical.get(identity) is None:
            continue
        observed += 1
        projected_identity = ontology.validate_projection(concept, projected)
        if projected_identity != canonical[identity]:
            expected = canonical[identity]
            message = f"{concept}.{identity} diverged: {projected_identity!r} != {expected!r}"
            raise ParityContractError(message)

    if observed == 0:
        message = "observation contains none of the #459 ontology identities"
        raise ParityContractError(message)

    # Event and artifact/provenance identities are not ontology concepts in v1.
    # If a scenario exposes them, the generic parity contract still requires the
    # exact canonical id instead of inventing an ontology extension in test code.
    assert_identity_projection(canonical, projected)


def load_golden_scenario(product: str, scenario_id: str) -> tuple[dict[str, Any], Any]:
    """Return one immutable #463 scenario plus its independent matcher."""
    require_dependencies(GOLDEN_BASELINES)
    fixture_path = REPO_ROOT.joinpath(
        "tests",
        "golden_baselines",
        "fixtures",
        "v1",
        f"{product}.json",
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    try:
        scenario = next(item for item in fixture["scenarios"] if item["id"] == scenario_id)
    except StopIteration as exc:
        message = f"#463 baseline {product!r} has no scenario {scenario_id!r}"
        raise ParityContractError(message) from exc

    contract = importlib.import_module("tests.golden_baselines.contract")
    return scenario, contract.assert_observation_matches


def assert_matches_golden(
    product: str,
    scenario_id: str,
    observation: Mapping[str, Any],
) -> None:
    """Feed a converged product observation to #463 without duplicating its expectations."""
    scenario, matcher = load_golden_scenario(product, scenario_id)
    matcher(scenario, observation)
