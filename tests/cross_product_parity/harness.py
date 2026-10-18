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
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_STRICT_ENV_VAR: Final = "MAISTRO_PARITY_STRICT"


def _strict_mode_enabled() -> bool:
    return os.environ.get(_STRICT_ENV_VAR) == "1"


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

# A dependency's source-level seam landing is necessary but not sufficient for a
# scenario to count as executed: #459's own scenarios 1-3 currently activate into
# import/source-token checks rather than a real Run created and observed through
# the landed seam, and scenario 6 currently feeds #463's own fixture example back
# into itself rather than a converged product's observation. Each of these stays a
# named, permanently-evidenced blocker -- probing for a marker/rewrite that does
# not exist yet -- so strict mode cannot go green on that scaffold once the named
# dependency above it lands. Implementing the real scenario clears the blocker by
# construction: the marker only exists once real assertions replace the scaffold.
_TEST_SUITE_PATH = "tests/cross_product_parity/test_cross_product_parity.py"

REAL_BUILDERS_CONDUCTOR_SCENARIO = Dependency(
    key="Builders->Conductor real executed scenario",
    issue=459,
    pr=None,
    description=(
        "Scenario 1 must create a real canonical Run through Builders' executor and "
        "observe it through Conductor's landed inspection seam; import/source-token "
        "checks alone do not exercise the real product path."
    ),
    probes=(
        SourceProbe(
            _TEST_SUITE_PATH,
            required_tokens=("REAL_SCENARIO_EVIDENCE: builders-conductor",),
        ),
    ),
)

REAL_SCHEDULE_CONDUCTOR_SCENARIO = Dependency(
    key="schedule fire->Conductor real executed scenario",
    issue=459,
    pr=None,
    description=(
        "Scenario 2 must admit a real schedule occurrence and observe its canonical "
        "Run through Conductor's landed inspection seam; source-token checks alone "
        "do not exercise the real product path."
    ),
    probes=(
        SourceProbe(
            _TEST_SUITE_PATH,
            required_tokens=("REAL_SCENARIO_EVIDENCE: schedule-conductor",),
        ),
    ),
)

REAL_EVOLVE_CONDUCTOR_SCENARIO = Dependency(
    key="Evolve->Conductor real executed scenario",
    issue=459,
    pr=None,
    description=(
        "Scenario 3 must run a real Evolve cycle and observe its canonical Run "
        "through Conductor's landed inspection seam; source-token checks alone do "
        "not exercise the real product path."
    ),
    probes=(
        SourceProbe(
            _TEST_SUITE_PATH,
            required_tokens=("REAL_SCENARIO_EVIDENCE: evolve-conductor",),
        ),
    ),
)

REAL_GOLDEN_PRODUCT_OBSERVATION = Dependency(
    key="#463 golden fixtures checked against a real product observation",
    issue=459,
    pr=None,
    description=(
        "Scenario 6 must feed a converged product's own observation to the #463 "
        "matcher; feeding the fixture's own example_observation back at itself "
        "only proves oracle wiring, not product behavior."
    ),
    probes=(
        SourceProbe(
            _TEST_SUITE_PATH,
            forbidden_tokens=(
                'assert_matches_golden("builders", "retry_keeps_logical_run", '
                'scenario["example_observation"])',
            ),
        ),
    ),
)

_DEPENDENCY_LIST: Final = (
    BUILDERS,
    EVOLVE,
    SCHEDULER,
    CONDUCTOR_INSPECTION,
    ONTOLOGY,
    GOLDEN_BASELINES,
    REAL_BUILDERS_CONDUCTOR_SCENARIO,
    REAL_SCHEDULE_CONDUCTOR_SCENARIO,
    REAL_EVOLVE_CONDUCTOR_SCENARIO,
    REAL_GOLDEN_PRODUCT_OBSERVATION,
)
DEPENDENCIES: Final = {dependency.key: dependency for dependency in _DEPENDENCY_LIST}


def dependency_assessment(*dependencies: Dependency) -> DependencyAssessment:
    """Return an assertion-backed dependency state for an executable scenario.

    A blocked scenario is only accepted when every blocker is tied to a named
    issue/PR and a concrete missing/legacy source seam. This is intentionally
    not a pytest skip or expected-failure mechanism. Once the probes pass the
    caller must execute the scenario's real assertions.

    Under ``MAISTRO_PARITY_STRICT=1`` (M1 closeout mode) a blocker is not a
    named, evidence-backed state to report and continue past: it raises
    ``DependencyUnavailable`` instead, so a scenario that only proved its
    dependency missing cannot register as a pass.
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

    if blockers and _strict_mode_enabled():
        raise DependencyUnavailable(" | ".join(blockers))

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
