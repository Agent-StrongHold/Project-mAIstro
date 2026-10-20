"""The publish-set unit suites execute exactly once per environment (#654).

`quality.yml`'s `coverage (no services)` job (id `coverage-unit`) and `ci.yml`'s
`test` job are both independently required by the PR ruleset (both are named in
`.github/branch-protection.json`), yet both used to execute the five
publish-set unit suites — maistro-core, -canvas, -evolve, -rsi, -bootstrap —
on the same SHA, in the same no-services environment. Two required green
ticks, one computation: the second run added wall-clock minutes to every PR
without adding a single new observation, because identical inputs in the
identical environment cannot yield independent evidence.

#654's first slice makes `coverage-unit` the canonical producer for those five
suites and removes their invocations from `CI / test`. This module pins that
partition so it cannot quietly regress in either direction:

- across every workflow, exactly one *no-services* whole-suite execution site
  per publish-set suite, and it is `coverage-unit`, running under
  `coverage run --branch` (so the single execution still feeds the coverage
  gate);
- `CI / test` keeps what the producer cannot execute — server, Turing,
  design, the extension harness/SDK suites, the root integration tree, Hive,
  the frontends, the cross-suite leakage proof, and the suite-inventory and
  duplicate-test checks;
- service-backed variants are distinct evidence and must survive: #654
  explicitly defers them ("PostgreSQL majors and storage environments are
  distinct evidence until their input/environment identities are
  normalized"). `coverage-postgres` legitimately re-runs the canvas suite
  against a live pgvector service, and the postgres/object-storage legs of
  `ci.yml` run core subpaths against their services. Any whole-suite site
  outside the declared service-backed set fails here, so adding one is a
  conscious decision, not a silent duplicate.

"Whole-suite site" is an occurrence of the suite path not continued into a
subpath: `pytest packages/maistro-core/tests -v` is an execution of the suite;
`pytest packages/maistro-core/tests/persistence` (the postgres leg) and
`pytest packages/maistro-core/tests/archive` (the MinIO leg) are the
service-backed subsets that must keep running. YAML comments outside a
`run:` block are not executions and are not scanned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SUITE_INVENTORY = ROOT / "docs" / "testing" / "SUITE-INVENTORY.md"

#: The publish-set unit suites, i.e. exactly the producer set of quality.yml's
#: coverage-unit job (quality.yml: "measured over the PyPI publish set").
PUBLISH_SET_SUITES = (
    "packages/maistro-core/tests",
    "packages/maistro-canvas/tests",
    "packages/maistro-evolve/tests",
    "packages/maistro-rsi/tests",
    "packages/maistro-bootstrap/tests",
)

PRODUCER_WORKFLOW = "quality.yml"
PRODUCER_JOB = "coverage-unit"
CONSUMER_WORKFLOW = "ci.yml"
CONSUMER_JOB = "test"

#: Jobs allowed to execute a publish-set suite *in addition to* the producer,
#: because they provide an environment the producer cannot (a live service).
#: #654 keeps these until environment identities are normalized. Each entry is
#: pinned to its actual service-backed legs by
#: ``test_service_backed_variants_survive_the_dedup`` — removing the legs
#: without removing the allowlist entry fails there.
SERVICE_BACKED_JOBS = frozenset(
    {
        (PRODUCER_WORKFLOW, "coverage-postgres"),
        (PRODUCER_WORKFLOW, "coverage-archive"),
        (CONSUMER_WORKFLOW, "postgres"),
        (CONSUMER_WORKFLOW, "object-storage"),
        (CONSUMER_WORKFLOW, "durable-events"),
        (CONSUMER_WORKFLOW, "strike-ladder"),
    }
)

#: Suite path NOT continued into a subpath (`/`, `.`, `-`, word char). The
#: service-backed legs all name subpaths (tests/persistence, tests/archive,
#: tests/workspaces, ...); only a whole-suite invocation matches.
_WHOLE_SUITE = {
    suite: re.compile(re.escape(suite) + r"(?![/\w.\-])") for suite in PUBLISH_SET_SUITES
}


@dataclass(frozen=True)
class Site:
    """One whole-suite occurrence inside one step of one job."""

    workflow: str
    job: str
    step: int

    def __str__(self) -> str:  # pragma: no cover - test-failure formatting
        return f"{self.workflow} job `{self.job}` step #{self.step}"

    @property
    def is_service_backed(self) -> bool:
        return (self.workflow, self.job) in SERVICE_BACKED_JOBS


def _step_texts(job: dict) -> list[tuple[int, str]]:
    """``(step index, run text)`` for every step of one job with a command."""
    return [
        (index, step["run"])
        for index, step in enumerate(job.get("steps") or [])
        if isinstance(step.get("run"), str)
    ]


def _all_run_text(job: dict) -> str:
    return "\n".join(run for _, run in _step_texts(job))


def _all_step_text(job: dict) -> str:
    """Run commands plus every step's ``working-directory``, joined."""
    parts = []
    for step in job.get("steps") or []:
        if isinstance(step.get("run"), str):
            parts.append(step["run"])
        workdir = (step.get("working-directory") or "").strip()
        if workdir:
            parts.append(workdir)
    return "\n".join(parts)


def _workflow_docs() -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }


def _execution_sites(docs: dict[str, dict]) -> dict[str, list[Site]]:
    """Map each publish-set suite to every whole-suite execution site."""
    sites: dict[str, list[Site]] = {suite: [] for suite in PUBLISH_SET_SUITES}
    for name, doc in docs.items():
        for job_id, job in (doc.get("jobs") or {}).items():
            for index, run in _step_texts(job):
                for suite, pattern in _WHOLE_SUITE.items():
                    if pattern.search(run):
                        sites[suite].append(Site(workflow=name, job=job_id, step=index))
    return sites


def _job(docs: dict[str, dict], workflow: str, job_id: str) -> dict:
    doc = docs.get(workflow)
    assert doc is not None, f"workflow {workflow} is missing"
    job = (doc.get("jobs") or {}).get(job_id)
    assert job is not None, f"job `{workflow}`:`{job_id}` is missing"
    return job


def test_each_publish_set_suite_has_one_no_services_execution() -> None:
    """One no-services whole-suite site per suite: the coverage-unit producer."""
    sites = _execution_sites(_workflow_docs())
    for suite in PUBLISH_SET_SUITES:
        found = sites[suite]
        assert found, f"{suite} is executed by no workflow — a vanished suite, not a dedup"
        unbacked = [site for site in found if not site.is_service_backed]
        assert len(unbacked) == 1, (
            f"{suite} has {len(unbacked)} no-services execution sites "
            f"({', '.join(map(str, found))}); #654 requires exactly one producer"
        )
        only = unbacked[0]
        assert (only.workflow, only.job) == (PRODUCER_WORKFLOW, PRODUCER_JOB), (
            f"{suite}'s canonical no-services producer must be "
            f"{PRODUCER_WORKFLOW} `{PRODUCER_JOB}`, not {only}"
        )


def test_every_extra_whole_suite_site_is_a_declared_service_backed_job() -> None:
    """A whole-suite site outside the producer must be service-backed, on purpose."""
    sites = _execution_sites(_workflow_docs())
    strays = [
        (suite, site)
        for suite, found in sites.items()
        for site in found
        if (site.workflow, site.job) != (PRODUCER_WORKFLOW, PRODUCER_JOB)
        and not site.is_service_backed
    ]
    assert not strays, (
        "; ".join(f"{suite} executed whole by {site}" for suite, site in strays)
        + " — a whole-suite execution outside coverage-unit is only legitimate in a "
        "service-backed job; add it to SERVICE_BACKED_JOBS with its service evidence "
        "or drop the duplicate (#654)"
    )


def test_ci_test_job_executes_no_publish_set_suite_anymore() -> None:
    """The regression #654 fixed: CI / test re-running the five suites."""
    test_job_text = _all_step_text(_job(_workflow_docs(), CONSUMER_WORKFLOW, CONSUMER_JOB))
    for suite in PUBLISH_SET_SUITES:
        assert suite not in test_job_text, (
            f"ci.yml `{CONSUMER_JOB}` references `{suite}`; the canonical producer is "
            f"{PRODUCER_WORKFLOW} `{PRODUCER_JOB}` (#654) — a second execution is "
            f"duplicate computation on the same SHA, not independent evidence"
        )


def test_the_single_execution_is_the_coverage_producer() -> None:
    """The one run must stay a coverage run: it feeds the coverage gate too."""
    docs = _workflow_docs()
    producer_text = _all_run_text(_job(docs, PRODUCER_WORKFLOW, PRODUCER_JOB))
    for suite in PUBLISH_SET_SUITES:
        assert _WHOLE_SUITE[suite].search(producer_text), (
            f"{PRODUCER_JOB} stopped executing {suite} — the partition forbids "
            f"re-adding it elsewhere without restoring it here first"
        )
    assert "coverage run" in producer_text and "--branch" in producer_text, (
        f"{PRODUCER_JOB} must execute the suites under `coverage run --branch`: "
        f"it is the coverage gate's producer for these suites, not just a test job"
    )
    # And the inventory table must not attribute the suites to ci.yml anymore.
    inventory = SUITE_INVENTORY.read_text(encoding="utf-8")
    for suite in PUBLISH_SET_SUITES:
        rows = [line for line in inventory.splitlines() if f"| `{suite}`" in line]
        assert rows, f"SUITE-INVENTORY.md lost its row for {suite}"
        assert "quality.yml" in rows[0], (
            f"SUITE-INVENTORY.md still attributes {suite} to a workflow other than "
            f"the producer: {rows[0].strip()}"
        )


def test_ci_test_job_still_owns_what_the_producer_cannot_execute() -> None:
    """Dedup removes only duplicates — `test` keeps its remaining mandates."""
    test_job_text = _all_step_text(_job(_workflow_docs(), CONSUMER_WORKFLOW, CONSUMER_JOB))
    required = (
        # Server, Turing (both trees), design, extension harness + SDK.
        "uv run pytest packages/maistro-server/tests",
        "uv run pytest packages/maistro-turing/tests",
        "uv run pytest packages/maistro-turing/backend/tests",
        "uv run pytest packages/maistro-design/tests",
        "uv run pytest packages/maistro-ext-harness/tests",
        "uv run pytest packages/maistro-ext-sdk/tests",
        # Root integration tree (registry split out to registry.yml).
        "uv run pytest tests/ --ignore=tests/tools/registry",
        # Hive backend, both frontends, the cross-suite leakage proof.
        "python -m pytest packages/hive-conductor/backend/tests",
        "packages/hive-conductor/frontend",
        "packages/maistro-canvas/frontend",
        "pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests",
        # The inventory + duplicate-test gates run in this job by name.
        "scripts/check-suite-inventory.py",
        "scripts/check-test-duplicates.py",
    )
    for fragment in required:
        assert fragment in test_job_text, (
            f"ci.yml `{CONSUMER_JOB}` lost `{fragment}`: #654's dedup removes only the "
            f"five publish-set suites, not this job's other mandates"
        )


def test_service_backed_variants_survive_the_dedup() -> None:
    """MinIO/PostgreSQL legs are distinct evidence until identities normalize."""
    docs = _workflow_docs()
    ci = docs[CONSUMER_WORKFLOW]
    # ci.yml's service-backed legs (PostgreSQL majors are their own evidence).
    postgres = _all_run_text(_job(docs, CONSUMER_WORKFLOW, "postgres"))
    assert "packages/maistro-core/tests/persistence" in postgres
    assert "packages/maistro-core/tests/test_container_postgres.py" in postgres
    assert "packages/maistro-core/tests/archive" in _all_run_text(
        _job(docs, CONSUMER_WORKFLOW, "object-storage")
    )
    assert "durable-events" in (ci.get("jobs") or {})
    assert "strike-ladder" in (ci.get("jobs") or {})
    # quality.yml's service-backed coverage producers: real services, real runs.
    pg_job = _job(docs, PRODUCER_WORKFLOW, "coverage-postgres")
    assert pg_job.get("services"), "coverage-postgres lost its PostgreSQL service"
    assert "pytest" in _all_run_text(pg_job)
    assert "packages/maistro-core/tests/archive" in _all_run_text(
        _job(docs, PRODUCER_WORKFLOW, "coverage-archive")
    )
