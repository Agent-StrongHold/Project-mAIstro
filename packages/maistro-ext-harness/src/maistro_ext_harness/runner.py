"""The conformance runner: one engine, many family plug-ins (#974).

`run_conformance` turns a `RunRequest` into a `ConformanceReport`:

1. discover → validate → grant → load the subject through the public
   lifecycle (a manifest rejection happens before any code runs, and is a
   typed failure, not a crash);
2. optionally load the built-in reference subject and run **the same case
   list** against both, so a third party can compare its implementation to
   the known-conforming reference case for case;
3. execute the family's cases with containment: a case that raises is a
   failed record, never a dead run;
4. apply the backend rule: a case that requires an unprobed backend is
   **failed** (or explicitly, recorded-ly waived) — it never silently skips.

The engine knows nothing about families; `maistro_ext_harness.families`
supplies the case lists through `family_cases`.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from maistro_ext_harness.backends import BackendRegistry
from maistro_ext_harness.contract import CONTRACT_VERSION, SUPPORTED_CONTRACT_MAJORS, ContractError
from maistro_ext_harness.families import (
    CaseEnvironment,
    CaseOutcome,
    ConformanceCase,
    family_cases,
    record_for,
)
from maistro_ext_harness.grants import GrantPolicy
from maistro_ext_harness.lifecycle import (
    DiscoveredExtension,
    ExtensionHost,
    LoadedExtension,
)
from maistro_ext_harness.manifest import ExtensionManifest
from maistro_ext_harness.reference import write_reference_extension
from maistro_ext_harness.report import (
    CaseRecord,
    CaseStatus,
    ConformanceReport,
    SubjectRecord,
)

__all__ = ["HARNESS_VERSION", "RunRequest", "run_conformance"]

#: The harness's own release version — read from installed metadata like
#: every other package in the monorepo, with the unbuilt-checkout fallback
#: the version bumper keeps in sync.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _metadata_version

    HARNESS_VERSION = _metadata_version("maistro-ext-harness")
except PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    HARNESS_VERSION = "0.9.0-dev"

#: Subject labels as the report records them.
EXTERNAL = "external"
REFERENCE = "reference"


@dataclass(frozen=True)
class RunRequest:
    """What to run: a subject, optionally a reference, a family, backends.

    `with_reference` runs the same case list against the harness's built-in
    reference extension (materialized fresh, or taken from
    `reference_root` when a caller wants to pin its own copy).
    """

    subject: Path
    family: str | None = None
    with_reference: bool = False
    reference_root: Path | None = None
    policy: GrantPolicy | None = None
    backends: BackendRegistry | None = None


def _subject_record(role: str, manifest: ExtensionManifest, root: Path) -> SubjectRecord:
    return SubjectRecord(
        role=role,
        extension_id=manifest.id,
        version=manifest.version,
        family=manifest.family,
        contract_range=manifest.contract,
        optional_features=manifest.optional_features,
        source=str(root),
    )


def _pick_family(requested: str | None, manifest: ExtensionManifest) -> str:
    family = requested or manifest.family
    if family != manifest.family:
        raise ContractError(
            f"requested family {family!r} does not match the subject's declared "
            f"family {manifest.family!r}; conformance runs the declared family"
        )
    return family


def _execute_case(case: ConformanceCase, env: CaseEnvironment, family: str) -> CaseRecord:
    """One case → one record, applying the backend rule with containment."""
    if case.requires_backend is not None:
        name = case.requires_backend
        if not env.backends.probe(name):
            waived = env.backends.waived(name)
            return CaseRecord(
                case_id=case.case_id,
                family=family,
                subject=env.subject,
                status=CaseStatus.SKIPPED if waived else CaseStatus.FAILED,
                detail=(
                    f"required backend {name!r} unavailable; skipped under an "
                    "explicit recorded waiver (this property did NOT execute)"
                    if waived
                    else f"required backend {name!r} is unavailable: the case fails "
                    "closed rather than silently skipping a property that "
                    "cannot be mocked honestly"
                ),
                required_backend=name,
            )
    try:
        outcome: CaseOutcome = case.run(env)
    except Exception as exc:
        return CaseRecord(
            case_id=case.case_id,
            family=family,
            subject=env.subject,
            status=CaseStatus.FAILED,
            detail=f"case raised {type(exc).__name__}: {exc}",
            required_backend=case.requires_backend,
        )
    return record_for(case, outcome, env.subject, family)


def _run_subject(
    host: ExtensionHost,
    discovered: DiscoveredExtension,
    manifest: ExtensionManifest,
    loaded: LoadedExtension,
    family: str,
    subject: str,
    backends: BackendRegistry,
) -> list[CaseRecord]:
    env = CaseEnvironment(
        subject=subject,
        host=host,
        discovered=discovered,
        manifest=manifest,
        grant=loaded.grant,
        loaded=loaded,
        backends=backends,
    )
    return [(_execute_case(case, env, family)) for case in family_cases(family)]


def _run_reference(
    request: RunRequest, family: str, backends: BackendRegistry
) -> tuple[SubjectRecord, list[CaseRecord]]:
    """Load the reference subject, run the same cases, and clean up."""
    host = ExtensionHost(policy=request.policy)
    materialized: Path | None = None
    if request.reference_root is not None:
        root = request.reference_root
    else:
        materialized = Path(tempfile.mkdtemp(prefix="maistro-ext-harness-ref-"))
        root = write_reference_extension(materialized / "reference")
    try:
        discovered = host.discover(root)
        manifest = host.validate(discovered)
        grant = host.grants_for(manifest)
        loaded = host.load(discovered, manifest, grant)
        try:
            records = _run_subject(host, discovered, manifest, loaded, family, REFERENCE, backends)
        finally:
            host.release(loaded)
        return _subject_record(REFERENCE, manifest, root), records
    finally:
        if materialized is not None:
            shutil.rmtree(materialized, ignore_errors=True)


def run_conformance(request: RunRequest) -> ConformanceReport:
    """Run the family suite over the subject (and optionally the reference)."""
    backends = request.backends or BackendRegistry()

    report = ConformanceReport(
        harness_version=HARNESS_VERSION,
        contract_version=CONTRACT_VERSION,
        supported_contract_majors=SUPPORTED_CONTRACT_MAJORS,
    )

    # The documented stages, in order: a failure in any of the first four
    # propagates as a typed error before any extension code has run.
    host = ExtensionHost(policy=request.policy)
    discovered = host.discover(request.subject)
    manifest = host.validate(discovered)
    family = _pick_family(request.family, manifest)
    grant = host.grants_for(manifest)
    loaded = host.load(discovered, manifest, grant)
    try:
        report.subjects.append(_subject_record(EXTERNAL, manifest, request.subject))
        cases = _run_subject(host, discovered, manifest, loaded, family, EXTERNAL, backends)
    finally:
        host.release(loaded)

    if request.with_reference:
        subject_record, reference_cases = _run_reference(request, family, backends)
        report.subjects.append(subject_record)
        cases.extend(reference_cases)

    report.cases.extend(cases)
    report.backend_waivers = tuple(sorted(backends.waivers))
    return report
