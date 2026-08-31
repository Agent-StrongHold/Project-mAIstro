"""Reusable integration contracts for M1 cross-product parity (#459).

This module is test/evidence code only. It deliberately does not emulate a
product runtime or fill a missing convergence seam. Product scenarios assert
the exact source-level dependency state before touching a surface that is still
owned by an active convergence PR. An unavailable scenario is therefore a
named, evidence-backed state in the suite rather than a test suppression.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]


class DependencyUnavailable(AssertionError):
    """A named upstream convergence dependency has not landed on this branch."""


class ParityContractError(AssertionError):
    """A product projection diverged from canonical execution identity/lifecycle."""


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
        failures = [
            f"{self.path} lacks {token!r}"
            for token in self.required_tokens
            if token not in text
        ]
        failures.extend(
            f"{self.path} still contains {token!r}"
            for token in self.forbidden_tokens
            if token in text
        )
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
        owner = f"PR #{self.pr}" if self.pr is not None else f"issue #{self.issue}"
        return f"{self.key} ({owner})"

    def failures(self) -> list[str]:
        return [failure for probe in self.probes for failure in probe.failures()]

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
            "packages/maistro-core/src/maistro/builders/canonical_execution.py",
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
    issue=766,
    pr=None,
    description=(
        "GET /v1/dag-runs/{run_id} must resolve canonical Run evidence instead of the "
        "product-private dag_run_store authority."
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
    pr=758,
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
    pr=771,
    description="The immutable #463 fixtures and fail-closed matcher are available.",
    probes=(
        SourceProbe(
            "tests/golden_baselines/contract.py",
            required_tokens=("assert_observation_matches",),
        ),
        SourceProbe("tests/golden_baselines/manifest.json"),
    ),
)


DEPENDENCIES: Final = {
    dependency.key: dependency
    for dependency in (
        BUILDERS,
        EVOLVE,
        SCHEDULER,
        CONDUCTOR_INSPECTION,
        ONTOLOGY,
        GOLDEN_BASELINES,
    )
}


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
        owner = f"PR #{dependency.pr}" if dependency.pr is not None else f"issue #{dependency.issue}"
        assert dependency.key.strip(), "unavailable dependency must have a stable name"
        assert dependency.issue > 0, f"{dependency.key} must name a tracking issue"
        assert failures, f"{dependency.label} cannot be unavailable without probe evidence"
        blockers.append(f"{dependency.key}: waiting on {owner}: {'; '.join(failures)}")
    assessment = DependencyAssessment(ready=not blockers, blockers=tuple(blockers))
    assert assessment.ready is (not assessment.blockers)
    return assessment


def require_dependencies(*dependencies: Dependency) -> None:
    """Fail loudly if code reaches a dependency-owned public seam too early."""
    assessment = dependency_assessment(*dependencies)
    if assessment.blockers:
        raise DependencyUnavailable(" | ".join(assessment.blockers))


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
    (
        project_store,
        run_store,
        task_admitter,
        template_store,
        schedule_store,
        continuation_store,
    ) = await wire_execution_spine(connection, workspace_id=workspace_id)
    project = await project_store.root_for_workspace(workspace_id)
    if project is None:
        await connection.close()
        raise ParityContractError(f"durable profile did not create Root Project for {workspace_id!r}")
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
            raise ParityContractError(
                f"{field} diverged: canonical {expected!r}, product projection {actual!r}"
            )
    if compared == 0:
        raise ParityContractError("canonical observation contains no shared identity to compare")

    run_id = canonical.get("run_id")
    if run_id is not None:
        for alias in _RUN_ID_ALIASES:
            if alias in projected and projected[alias] != run_id:
                raise ParityContractError(
                    f"{alias} creates a second Run identity: {projected[alias]!r} != {run_id!r}"
                )

    canonical_status = canonical.get("status")
    product_terminal = projected.get("terminal_state")
    if canonical_status in _TERMINAL_STATUSES and product_terminal is not None:
        if product_terminal != canonical_status:
            raise ParityContractError(
                "product-private terminal state diverged from canonical Run status: "
                f"{product_terminal!r} != {canonical_status!r}"
            )


def assert_ontology_identity_projection(
    canonical: Mapping[str, object],
    projected: Mapping[str, object],
) -> None:
    """Use #458's executable ontology as the shared-identity field authority."""
    require_dependencies(ONTOLOGY)
    ontology_module = importlib.import_module("maistro.interop")
    ontology = ontology_module.INTEROP_ONTOLOGY_V1

    observed = 0
    for concept in (
        "Workspace",
        "Project",
        "Graph",
        "Run",
        "NodeRun",
        "Attempt",
        "Invocation",
    ):
        identity = ontology.concept(concept).identity
        if canonical.get(identity) is None:
            continue
        observed += 1
        projected_identity = ontology.validate_projection(concept, projected)
        if projected_identity != canonical[identity]:
            raise ParityContractError(
                f"{concept}.{identity} diverged: {projected_identity!r} != {canonical[identity]!r}"
            )
    if observed == 0:
        raise ParityContractError("observation contains none of the #459 ontology identities")

    # Event and artifact/provenance identities are not ontology concepts in v1.
    # If a scenario exposes them, the generic parity contract still requires the
    # exact canonical id instead of inventing an ontology extension in test code.
    assert_identity_projection(canonical, projected)


def load_golden_scenario(product: str, scenario_id: str) -> tuple[dict[str, Any], Any]:
    """Return one immutable #463 scenario plus its independent matcher."""
    require_dependencies(GOLDEN_BASELINES)
    fixture_path = REPO_ROOT / "tests" / "golden_baselines" / "fixtures" / "v1" / f"{product}.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    try:
        scenario = next(item for item in fixture["scenarios"] if item["id"] == scenario_id)
    except StopIteration as exc:
        raise ParityContractError(
            f"#463 baseline {product!r} has no scenario {scenario_id!r}"
        ) from exc
    contract = importlib.import_module("tests.golden_baselines.contract")
    return scenario, contract.assert_observation_matches


def assert_matches_golden(product: str, scenario_id: str, observation: Mapping[str, Any]) -> None:
    """Feed a converged product observation to #463 without duplicating its expectations."""
    scenario, matcher = load_golden_scenario(product, scenario_id)
    matcher(scenario, observation)
