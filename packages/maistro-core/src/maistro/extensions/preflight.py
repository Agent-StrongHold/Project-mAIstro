"""Host-upgrade compatibility preflight for installed extensions (M9-C3, #957).

Before a host upgrade is applied, this module answers one question from data
alone: *which installed extensions are compatible, deprecated,
migration-required, or blocking against the target release* — so an upgrade
never discovers incompatibility after cutover.

Three properties are structural, not aspirational:

* **The target is data, never code.** The target release enters as a
  :class:`TargetHostContract` — its host version, the manifest-contract
  version it enforces, and its public capability vocabulary with
  deprecation/removal metadata. The preflight imports no target-private
  internals and no extension code; the only ``maistro`` import in this module
  is the public record model (:mod:`maistro.extensions.types`). Evaluating an
  upgrade therefore requires nothing from the release being evaluated, and
  the evaluation never activates the new host version.
* **The input is the installed lock state.** Records come from the
  install-record store (#952) — who installed what, with which manifest
  snapshot. The manifest snapshot *is* the public contract metadata the
  evaluation reads: contract range, capability names, dependency edges.
  Nothing mutable about a registry or catalog can reach into a report.
* **The report is reproducible.** :meth:`PreflightReport.canonical_json` is a
  pure function of (lock state, target contract, policy, enabled set): no
  wall clock, no randomness, sorted rows and keys. The same installed state
  evaluated twice — or re-read from a restarted store — yields byte-identical
  reports.

Verdicts are total and ordered: every installed extension gets exactly one
status. ``blocking`` rows carry ``conflicts`` naming the exact contract or
dependency conflict; everything softer lands in ``warnings`` /
``migration_notes``. Under :attr:`PreflightPolicy.STRICT`, an enabled
blocking row means the upgrade cannot proceed (``can_proceed`` is ``False``);
under :attr:`PreflightPolicy.PERMISSIVE` the same rows are reported but do
not refuse the upgrade. Disabled extensions cannot block — an operator who
has already disabled an extension must not be told the upgrade is impossible.

Manifest shapes read here (all public ``extension.json`` fields):

* ``contract`` — the manifest-contract range, strict comparator grammar
  (``>=1.0.0,<2.0.0``). A range that admits more than one contract major is a
  manifest-contract authoring violation (see ``docs/extensions/
  manifest-reference.md``): it validates against today's host but must be
  repinned, so it reports ``migration-required``, not ``blocking``.
* ``capabilities`` — names checked against the target vocabulary: removed
  names block; deprecated names warn with their replacement; names outside a
  declared vocabulary block.
* ``dependencies`` — entries of ``{"id": ..., "range": ...}`` checked against
  the installed lock state. A dependency that is itself blocking on the
  target blocks its dependents (named as a transitive conflict); a
  migration-required dependency makes dependents migration-required too.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum

from maistro.extensions.types import ExtensionRegistryError, InstallRecord

__all__ = [
    "ExtensionPreflightRow",
    "ExtensionStatus",
    "ManifestContractError",
    "ParsedManifest",
    "PreflightPolicy",
    "PreflightReport",
    "SemanticVersion",
    "TargetHostContract",
    "VersionRange",
    "current_lock_state",
    "parse_manifest",
    "parse_semantic_version",
    "parse_version_range",
    "run_preflight",
]


class ManifestContractError(ExtensionRegistryError):
    """A manifest snapshot (or a version range inside it) cannot be evaluated.

    Raised for structurally unreadable contract metadata — not-JSON snapshots,
    missing ``contract`` fields, malformed comparator ranges. The message is
    the exact conflict an operator sees; it always names what was unreadable.
    """


class PreflightPolicy(Enum):
    """What a blocking finding means for the upgrade.

    ``PERMISSIVE`` reports blockers; ``STRICT`` refuses the upgrade while an
    enabled extension blocks. The strict policy is the upgrade gate —
    ``PreflightReport.can_proceed`` is ``False`` and the CLI exits non-zero —
    so an upgrade cannot proceed under it while blocking extensions remain
    enabled.
    """

    PERMISSIVE = "permissive"
    STRICT = "strict"

    @classmethod
    def from_name(cls, name: str) -> PreflightPolicy:
        """Parse a CLI/policy name, failing loudly on an unknown one."""
        try:
            return cls(name.strip().lower())
        except ValueError as exc:
            known = ", ".join(policy.value for policy in cls)
            raise ValueError(
                f"unknown preflight policy {name!r}; expected one of: {known}"
            ) from exc


class ExtensionStatus(Enum):
    """The total, ordered verdict for one installed extension.

    ``BLOCKING`` outranks ``MIGRATION_REQUIRED``, which outranks
    ``DEPRECATED``, which outranks ``COMPATIBLE`` — a row that triggers
    several verdicts reports the strongest one and keeps the softer findings
    in its warnings/notes.
    """

    COMPATIBLE = "compatible"
    DEPRECATION = "deprecated"
    MIGRATION_REQUIRED = "migration-required"
    BLOCKING = "blocking"


#: Strict semver: exactly three numeric parts. The manifest contract grammar
#: and the install-record versions are all pinned to this shape, so comparison
#: never guesses (``1.0`` vs ``1.0.0`` is malformed here, not ambiguous).
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

#: One comparator of a contract/dependency range: operator and exact version.
_COMPARATOR_RE = re.compile(r"^(>=|<=|==|!=|>|<)(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


@dataclass(frozen=True, order=True)
class SemanticVersion:
    """A parsed ``MAJOR.MINOR.PATCH`` version; orders naturally."""

    major: int
    minor: int
    patch: int

    def as_tuple(self) -> tuple[int, int, int]:
        """The ``(major, minor, patch)`` triple."""
        return (self.major, self.minor, self.patch)


def parse_semantic_version(text: str) -> SemanticVersion:
    """Parse a strict ``MAJOR.MINOR.PATCH`` version.

    Raises :class:`ManifestContractError` for anything else — a silent
    fallback here would let a malformed version compare as "compatible".
    """
    match = _SEMVER_RE.match(text.strip())
    if match is None:
        raise ManifestContractError(
            f"malformed semantic version {text!r}; expected MAJOR.MINOR.PATCH"
        )
    return SemanticVersion(*(int(part) for part in match.groups()))


@dataclass(frozen=True)
class VersionRange:
    """A strict comparator range: ``>=1.0.0,<2.0.0``.

    The grammar is deliberately tiny — comma-separated comparators over exact
    semver versions — because the manifest contract is a *schema* version
    range, not a package resolution input. Anything the grammar cannot express
    is a parse error naming the offending text, never a silent interpretation.
    """

    comparators: tuple[tuple[str, SemanticVersion], ...]
    source: str
    """The exact range text as written in the manifest, for conflict messages."""

    def admits(self, version: SemanticVersion) -> bool:
        """True when ``version`` satisfies every comparator."""
        for operator, bound in self.comparators:
            actual = version.as_tuple()
            limit = bound.as_tuple()
            if operator == ">=" and not actual >= limit:
                return False
            if operator == "<=" and not actual <= limit:
                return False
            if operator == ">" and not actual > limit:
                return False
            if operator == "<" and not actual < limit:
                return False
            if operator == "==" and actual != limit:
                return False
            if operator == "!=" and actual == limit:
                return False
        return True

    def spans_multiple_majors(self) -> bool:
        """True when the range admits versions under more than one major.

        This is the manifest-reference authoring rule ("pin exactly the major
        you code against"): a range that reaches across a major boundary
        claims compatibility with a schema that does not exist yet, so a
        manifest pinned that way works today but must be repinned before the
        next contract major — migration-required, not blocking.

        ``!=`` comparators remove points and can therefore never add a major,
        so they are ignored for span purposes; an exact ``==`` pin admits a
        single version, hence a single major.
        """
        if any(operator == "==" for operator, _ in self.comparators):
            return False
        floors = [bound.major for operator, bound in self.comparators if operator in (">=", ">")]
        ceilings = [
            (bound, operator) for operator, bound in self.comparators if operator in ("<=", "<")
        ]
        lowest = min(floors) if floors else 0
        if not ceilings:
            # Unbounded above: every major from `lowest` up is admitted.
            return True
        ceiling, ceiling_operator = min(ceilings, key=lambda item: item[0].as_tuple())
        if ceiling_operator == "<" and ceiling.minor == 0 and ceiling.patch == 0:
            highest = ceiling.major - 1
        else:
            highest = ceiling.major
        return highest > lowest


def parse_version_range(source: str) -> VersionRange:
    """Parse a strict comparator range; raise with the exact offending text."""
    text = source.strip()
    if not text:
        raise ManifestContractError("malformed version range '': expected at least one comparator")
    comparators: list[tuple[str, SemanticVersion]] = []
    for token in text.split(","):
        match = _COMPARATOR_RE.match(token.strip())
        if match is None:
            raise ManifestContractError(
                f"malformed version range {source!r}: comparator {token.strip()!r} "
                "is not one of >=, <=, ==, !=, >, < followed by MAJOR.MINOR.PATCH"
            )
        operator = match.group(1)
        version = SemanticVersion(*(int(part) for part in match.groups()[1:]))
        comparators.append((operator, version))
    return VersionRange(comparators=tuple(comparators), source=text)


@dataclass(frozen=True)
class TargetHostContract:
    """The target release's public extension-contract metadata.

    This is what the preflight knows about the host being upgraded *to* — and
    all of it is public contract data an operator (or CI fixture) supplies;
    the preflight never imports the target release's code. ``host_version``
    names the release; ``contract_version`` names the manifest-contract
    version that release enforces; the vocabulary maps describe what happened
    to capability names between the current and target contract.
    """

    host_version: str
    contract_version: str
    #: Capability names the target contract supports. An empty set means the
    #: caller supplies no vocabulary — the preflight then has no opinion on
    #: unknown names (it still enforces deprecations/removals it is told
    #: about), so a partially declared target cannot block everything.
    capabilities: frozenset[str] = field(default=frozenset())
    #: Capability → replacement/removal guidance: valid in the target, but
    #: announced for removal in a later contract major.
    deprecated: Mapping[str, str] = field(default_factory=dict)
    #: Capability → removal note: no longer valid in the target at all.
    removed: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Fail fast on malformed target metadata — never evaluate against it."""
        parse_semantic_version(self.host_version)
        parse_semantic_version(self.contract_version)
        unknown = set(self.deprecated) & set(self.removed)
        if unknown:
            raise ManifestContractError(
                f"target contract metadata declares {sorted(unknown)} as both deprecated and removed"
            )


@dataclass(frozen=True)
class ParsedManifest:
    """The public contract metadata one manifest snapshot carries.

    Exactly the fields the preflight reads; the manifest snapshot bytes stay
    the authority (the digests in the install record pin them).
    """

    contract_range: VersionRange
    capabilities: tuple[str, ...]
    dependencies: tuple[tuple[str, str], ...]
    """``(id, range-source)`` pairs, in manifest order."""


def parse_manifest(body: str) -> ParsedManifest:
    """Parse the public contract metadata out of a manifest snapshot.

    Raises :class:`ManifestContractError` naming the exact unreadable field.
    Malformed metadata is a *blocking* finding upstream, not an exception that
    skips the row: an unreadable manifest must be reported, not dropped.
    """
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ManifestContractError(f"manifest snapshot is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestContractError("manifest snapshot is not a JSON object")
    contract = document.get("contract")
    if not isinstance(contract, str):
        raise ManifestContractError("manifest snapshot has no string 'contract' field")
    contract_range = parse_version_range(contract)

    raw_capabilities = document.get("capabilities", [])
    if not isinstance(raw_capabilities, list) or not all(
        isinstance(name, str) for name in raw_capabilities
    ):
        raise ManifestContractError("manifest 'capabilities' must be a list of strings")
    capabilities = tuple(raw_capabilities)

    dependencies: list[tuple[str, str]] = []
    raw_dependencies = document.get("dependencies", [])
    if not isinstance(raw_dependencies, list):
        raise ManifestContractError("manifest 'dependencies' must be a list")
    for entry in raw_dependencies:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ManifestContractError(
                "manifest dependency entries must be objects with a string 'id'"
            )
        dep_range = entry.get("range")
        if not isinstance(dep_range, str):
            raise ManifestContractError(
                f"manifest dependency {entry.get('id')!r} has no string 'range' field"
            )
        # The range grammar itself is checked where the edge is evaluated
        # (_check_dependencies), so a malformed dependency range blocks with
        # the dependency named, not as a whole-manifest parse failure.
        dependencies.append((entry["id"], dep_range))

    return ParsedManifest(
        contract_range=contract_range,
        capabilities=capabilities,
        dependencies=tuple(dependencies),
    )


@dataclass(frozen=True)
class ExtensionPreflightRow:
    """One installed extension's verdict against the target contract.

    ``conflicts`` (blocking) is kept strictly apart from ``warnings`` (works,
    announces future removal) and ``migration_notes`` (actionable metadata);
    the acceptance rule "warnings and hard blockers are distinct" is this
    separation plus :attr:`ExtensionStatus.BLOCKING` being the only status
    that can contribute blockers to the report.
    """

    extension_name: str
    semantic_version: str
    package_sha256: str
    manifest_sha256: str
    installed_at: str
    """ISO-8601 timestamp of the install record — part of the lock state."""
    enabled: bool
    status: ExtensionStatus
    contract_range: str
    """The manifest's contract range as written (empty when unreadable)."""
    capabilities: tuple[str, ...]
    dependencies: tuple[tuple[str, str], ...]
    conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
    migration_notes: tuple[str, ...]

    def _payload(self) -> dict[str, object]:
        """JSON-safe form of the row (enums and pairs rendered plainly)."""
        return {
            "extension_name": self.extension_name,
            "semantic_version": self.semantic_version,
            "package_sha256": self.package_sha256,
            "manifest_sha256": self.manifest_sha256,
            "installed_at": self.installed_at,
            "enabled": self.enabled,
            "status": self.status.value,
            "contract_range": self.contract_range,
            "capabilities": list(self.capabilities),
            "dependencies": [list(pair) for pair in self.dependencies],
            "conflicts": list(self.conflicts),
            "warnings": list(self.warnings),
            "migration_notes": list(self.migration_notes),
        }


@dataclass(frozen=True)
class PreflightReport:
    """The upgrade compatibility matrix, its blockers, and the verdict."""

    target_host_version: str
    target_contract_version: str
    policy: PreflightPolicy
    rows: tuple[ExtensionPreflightRow, ...]
    """One row per installed extension (current version), sorted by name."""
    can_proceed: bool
    """False exactly under a strict policy with enabled blocking rows."""

    @property
    def blockers(self) -> tuple[ExtensionPreflightRow, ...]:
        """Enabled blocking rows — the reason a strict upgrade refuses."""
        return tuple(
            row for row in self.rows if row.status is ExtensionStatus.BLOCKING and row.enabled
        )

    @property
    def warning_rows(self) -> tuple[ExtensionPreflightRow, ...]:
        """Rows that upgrade but carry warnings or migration metadata."""
        return tuple(
            row
            for row in self.rows
            if row.status is not ExtensionStatus.BLOCKING and (row.warnings or row.migration_notes)
        )

    def canonical_json(self) -> str:
        """Deterministic JSON: sorted keys, compact separators, no wall clock.

        Two evaluations of the same installed lock state against the same
        target and policy produce byte-identical output.
        """
        return json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))

    def _payload(self) -> dict[str, object]:
        return {
            "target_host_version": self.target_host_version,
            "target_contract_version": self.target_contract_version,
            "policy": self.policy.value,
            "can_proceed": self.can_proceed,
            "rows": [row._payload() for row in self.rows],
        }


def current_lock_state(records: Iterable[InstallRecord]) -> list[InstallRecord]:
    """Reduce raw install records to the current record per extension.

    The lock state the preflight evaluates: for each extension name, the
    latest install record (max ``installed_at``, ties broken by ``install_id``
    so the selection is total and deterministic). Sorted by name.
    """
    latest: dict[str, InstallRecord] = {}
    for record in records:
        incumbent = latest.get(record.identity.extension_name)
        if incumbent is None or (record.installed_at, record.install_id) > (
            incumbent.installed_at,
            incumbent.install_id,
        ):
            latest[record.identity.extension_name] = record
    return [latest[name] for name in sorted(latest)]


def _evaluate_row(
    record: InstallRecord,
    target: TargetHostContract,
    *,
    installed_versions: Mapping[str, str],
    enabled: bool,
) -> ExtensionPreflightRow:
    """Evaluate one current install record against the target contract."""
    conflicts: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    contract_range = ""
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[tuple[str, str], ...] = ()

    try:
        parsed = parse_manifest(record.manifest.body)
    except ManifestContractError as exc:
        conflicts.append(
            f"{record.identity.extension_name}@{record.identity.semantic_version}: {exc}"
        )
    else:
        contract_range = parsed.contract_range.source
        capabilities = parsed.capabilities
        dependencies = parsed.dependencies
        _check_contract_range(parsed, target, conflicts, notes)
        _check_capabilities(parsed, target, conflicts, warnings)
        _check_dependencies(parsed, record, installed_versions, conflicts)

    if conflicts:
        status = ExtensionStatus.BLOCKING
    elif notes:
        status = ExtensionStatus.MIGRATION_REQUIRED
    elif warnings:
        status = ExtensionStatus.DEPRECATION
    else:
        status = ExtensionStatus.COMPATIBLE

    return ExtensionPreflightRow(
        extension_name=record.identity.extension_name,
        semantic_version=record.identity.semantic_version,
        package_sha256=record.identity.package_sha256,
        manifest_sha256=record.identity.manifest_sha256,
        installed_at=record.installed_at.isoformat(),
        enabled=enabled,
        status=status,
        contract_range=contract_range,
        capabilities=capabilities,
        dependencies=dependencies,
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
        migration_notes=tuple(notes),
    )


def _check_contract_range(
    parsed: ParsedManifest,
    target: TargetHostContract,
    conflicts: list[str],
    notes: list[str],
) -> None:
    """Contract-range check: does the manifest validate against the target?"""
    target_contract = parse_semantic_version(target.contract_version)
    if not parsed.contract_range.admits(target_contract):
        conflicts.append(
            f"manifest pins contract range '{parsed.contract_range.source}' which does not "
            f"include the target host contract version {target.contract_version} "
            f"(host {target.host_version}); the manifest must be repinned to a range "
            "that includes it before this upgrade"
        )
        return
    if parsed.contract_range.spans_multiple_majors():
        suggested = f">={target_contract.major}.0.0,<{target_contract.major + 1}.0.0"
        notes.append(
            f"contract range '{parsed.contract_range.source}' spans more than one contract "
            f"major; repin to exactly the major the extension codes against "
            f"(suggested '{suggested}') before the next contract major removes the old one"
        )


def _check_capabilities(
    parsed: ParsedManifest,
    target: TargetHostContract,
    conflicts: list[str],
    warnings: list[str],
) -> None:
    """Capability names against the target vocabulary."""
    for name in parsed.capabilities:
        if name in target.removed:
            conflicts.append(
                f"capability '{name}' was removed in the target host contract "
                f"{target.contract_version}: {target.removed[name]}"
            )
        elif name in target.deprecated:
            warnings.append(
                f"capability '{name}' is deprecated in the target host contract "
                f"{target.contract_version}: {target.deprecated[name]}"
            )
        elif target.capabilities and name not in target.capabilities:
            conflicts.append(
                f"capability '{name}' is not part of the target host contract "
                f"{target.contract_version} vocabulary"
            )


def _check_dependencies(
    parsed: ParsedManifest,
    record: InstallRecord,
    installed_versions: Mapping[str, str],
    conflicts: list[str],
) -> None:
    """Dependency edges against the installed lock state."""
    name = record.identity.extension_name
    for dependency_id, range_source in parsed.dependencies:
        try:
            required = parse_version_range(range_source)
        except ManifestContractError as exc:
            conflicts.append(f"dependency '{dependency_id}': {exc}")
            continue
        found_version = installed_versions.get(dependency_id)
        if found_version is None:
            conflicts.append(
                f"dependency '{dependency_id}' is not installed "
                f"(manifest requires '{range_source}')"
            )
            continue
        try:
            installed_version = parse_semantic_version(found_version)
        except ManifestContractError as exc:  # pragma: no cover - store data is semver
            conflicts.append(f"dependency '{dependency_id}': {exc}")
            continue
        if not required.admits(installed_version):
            conflicts.append(
                f"dependency '{dependency_id}' requires '{range_source}' but "
                f"{found_version} is installed"
            )
        if dependency_id == name:
            conflicts.append(f"dependency '{dependency_id}' declares itself as its own dependency")


def _propagate_dependency_verdicts(
    rows: Sequence[ExtensionPreflightRow],
) -> tuple[ExtensionPreflightRow, ...]:
    """Second pass: a dependency's verdict reaches its dependents.

    A dependency that is blocking on the target (old contract major, removed
    capability) will not function after the upgrade, so any extension that
    depends on it gains the exact transitive conflict. A dependency that is
    merely migration-required makes its dependents migration-required as
    well. Deprecation does not propagate: a deprecated dependency still
    works, so its dependents still work.
    """
    by_name = {row.extension_name: row for row in rows}
    _rank = {
        ExtensionStatus.COMPATIBLE: 0,
        ExtensionStatus.DEPRECATION: 1,
        ExtensionStatus.MIGRATION_REQUIRED: 2,
        ExtensionStatus.BLOCKING: 3,
    }
    updated: list[ExtensionPreflightRow] = []
    for row in rows:
        if row.status is ExtensionStatus.BLOCKING:
            updated.append(row)
            continue
        conflicts = row.conflicts
        notes = row.migration_notes
        status: ExtensionStatus = row.status
        for dependency_id, range_source in row.dependencies:
            dependency = by_name.get(dependency_id)
            if dependency is None or dependency.extension_name == row.extension_name:
                continue
            if dependency.status is ExtensionStatus.BLOCKING:
                conflicts = (
                    *conflicts,
                    (
                        f"dependency '{dependency_id}' is blocking on the target host "
                        f"({'; '.join(dependency.conflicts)}) and this extension requires "
                        f"it ('{range_source}')"
                    ),
                )
                status = ExtensionStatus.BLOCKING
            elif _rank[dependency.status] > _rank[status]:
                notes = (
                    *notes,
                    (
                        f"dependency '{dependency_id}' requires a manifest migration on the "
                        f"target host; this extension depends on it ('{range_source}') and "
                        "inherits the migration"
                    ),
                )
                status = ExtensionStatus.MIGRATION_REQUIRED
        updated.append(
            replace(row, conflicts=conflicts, migration_notes=notes, status=status)
            if (conflicts, notes, status) != (row.conflicts, row.migration_notes, row.status)
            else row
        )
    return tuple(updated)


def run_preflight(
    records: Sequence[InstallRecord],
    target: TargetHostContract,
    *,
    policy: PreflightPolicy = PreflightPolicy.PERMISSIVE,
    enabled: frozenset[str] | None = None,
) -> PreflightReport:
    """Evaluate the installed lock state against a target host contract.

    ``records`` is the raw install history; the lock state (current record
    per extension) is derived here. ``enabled`` names the extensions the host
    currently has enabled; ``None`` treats every installed extension as
    enabled — the conservative default, because a strict policy must refuse
    an upgrade it cannot prove safe.

    Pure: no wall clock, no I/O, no imports of extension or target code. The
    same inputs always produce the same report.
    """
    lock_state = current_lock_state(records)
    installed_versions = {
        r.identity.extension_name: r.identity.semantic_version for r in lock_state
    }
    rows = [
        _evaluate_row(
            record,
            target,
            installed_versions=installed_versions,
            enabled=enabled is None or record.identity.extension_name in enabled,
        )
        for record in lock_state
    ]
    final_rows = _propagate_dependency_verdicts(rows)
    enabled_blockers = any(row.status is ExtensionStatus.BLOCKING and row.enabled for row in rows)
    can_proceed = not (enabled_blockers and policy is PreflightPolicy.STRICT)
    return PreflightReport(
        target_host_version=target.host_version,
        target_contract_version=target.contract_version,
        policy=policy,
        rows=final_rows,
        can_proceed=can_proceed,
    )
