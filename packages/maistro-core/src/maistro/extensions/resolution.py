"""Deterministic extension dependency resolution and reproducible lock state
(M9-C2, issue #956).

Given an immutable catalog snapshot (every version an extension registry
offers, with each version's full :class:`~maistro.extensions.types.PackageIdentity`
and its declared dependencies) and one or more install requests, produce a
:class:`LockState`: the exact set of extension versions to install, each
pinned by name, version, package digest, manifest digest, and catalog source.
The lock is the contract between "what the operator asked for" and "what gets
installed": identical inputs always produce a byte-identical lock, and an
installed ecosystem can always be reproduced from the lock alone.

Determinism is a stated policy, not an accident:

* **Selection order** — names are resolved in lexicographic order until no
  unconstrained name remains.
* **Version policy** — the *highest* version satisfying every constraint
  accumulated so far; ties (same version, different bytes) break by package
  digest, then manifest digest, then catalog source, all descending — a total
  order, so even a catalog offering the same version twice resolves the same
  way everywhere.
* **No backtracking.** A constraint discovered after a version was selected
  that the selection violates is a loud :class:`ResolutionConflict`, never a
  silent re-selection. A deterministic failure is reproducible; a clever one
  is not.
* **Optional edges never gain authority.** An optional dependency is resolved
  as its own all-or-nothing branch *after* the required graph is fixed: if it
  resolves cleanly it is pinned with ``kind="optional"``, and if anything
  about it fails — absent, unsatisfiable, cyclic, or incompatible with what
  the lock already pins — the branch is recorded in ``skipped_optional`` with
  the reason and the requiring extension still installs. An optional
  dependency can add entries to the lock; it can never fail one or override
  a chosen version.

Cycles among required edges raise :class:`DependencyCycle` before any lock
exists, and therefore before any extension is activated: the resolver runs
entirely in manifest metadata, so a cycle is rejected while nothing has been
fetched, verified, or imported.

Every lock entry records *why*: the constraints that bounded its version (and
who declared each), the candidates that were rejected (and the constraint
each failed), and whether it is present because the install requested it,
because another extension required it, or as an optional branch. This is the
data :meth:`LockState.explain` and the ``maistro extensions explain`` command
render for the acceptance criterion "operator can explain why each
dependency/version was selected".

:func:`materialize_lock` closes the loop with the M9-B1 install store
(#952): it fetches each locked entry's artifacts, fails explicitly naming
every unavailable artifact *before* recording or activating anything, and
otherwise drives every entry through the store's digest/signature
verification — so reinstalling from a lock either recreates exactly the same
identities or fails with nothing installed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from maistro.extensions.semver import (
    InvalidSemanticVersion,
    InvalidVersionRange,
    SemVer,
    VersionRange,
    parse_range,
)
from maistro.extensions.store import ActivationCallback, ExtensionInstallStore
from maistro.extensions.types import (
    ExtensionRegistryError,
    InstallRecord,
    InstallRequest,
    PackageIdentity,
    RegistryProvenance,
    identity_key,
    sha256_hex,
)

#: Version tag of the lock serialization. Bumping it is a format change:
#: ``from_json`` refuses anything else rather than guessing.
LOCK_FORMAT = "maistro-extension-lock:v1"

#: Origin label for the operator's own install request, as opposed to a
#: requirement declared by another extension. Angle brackets keep it outside
#: the slug namespace extension ids live in.
ROOT_REQUEST_ORIGIN = "<install-request>"

#: The version-selection policy, stated once so diagnostics, ``explain``,
#: and docstrings quote the same sentence.
SELECTION_POLICY = (
    "highest semantic version satisfying every accumulated constraint; ties "
    "broken by package digest, then manifest digest, then catalog source "
    "(descending); no backtracking — a later violated constraint is a conflict"
)

#: Lock entries carry the identity digests install verification checks; they
#: must be full hex sha256 strings, the same form ``DIGEST_ALGORITHM`` names.
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ResolutionError(ExtensionRegistryError):
    """Base class for dependency-resolution and lock-state failures."""


class UnresolvableDependency(ResolutionError):
    """A dependency declaration is malformed (empty target, unusable range)."""


class ResolutionConflict(ResolutionError):
    """No version satisfies the accumulated constraints for an extension.

    The message is the diagnostic: every constraint with its origin, every
    available version, and the reason each candidate was excluded.
    """


class DependencyCycle(ResolutionError):
    """Required dependencies form a cycle. Refused before any activation."""


class LockFormatError(ResolutionError):
    """A lock payload is not a valid ``maistro-extension-lock`` document."""


class MissingLockArtifacts(ResolutionError):
    """Reinstalling from a lock hit artifacts that are unavailable.

    Raised before anything is recorded or activated, naming every missing
    entry — the explicit failure the reproducibility criterion asks for.
    """


@dataclass(frozen=True)
class ExtensionDependency:
    """One declared dependency: target extension id + version range.

    ``required=False`` marks an *optional* dependency: resolution attempts it
    opportunistically, but any failure leaves the requiring extension
    installable and records the skip reason in the lock. Optional
    dependencies never escalate into required authority.
    """

    target: str
    range_text: str
    required: bool = True

    def sort_key(self) -> tuple[str, str, bool]:
        """Deterministic processing order for a set of declarations."""
        return (self.target, self.range_text, self.required)


@dataclass(frozen=True)
class CatalogEntry:
    """One installable version as the catalog offers it.

    Every field is metadata about immutable bytes: the identity (name,
    version, both digests), where the catalog served it from, the snapshot
    digest proving which catalog revision claimed it, the publisher and
    signature the install will verify against, and the dependencies the
    manifest declares. A catalog is a *snapshot* — resolution never refetches
    or re-reads it mid-run, which is what makes two runs over the same
    snapshot comparable.
    """

    identity: PackageIdentity
    source: str
    catalog_snapshot_sha256: str
    publisher_id: str
    signature: str
    dependencies: tuple[ExtensionDependency, ...] = ()

    @property
    def version(self) -> SemVer:
        return SemVer.parse(self.identity.semantic_version)


@dataclass(frozen=True)
class ExtensionCatalog:
    """The immutable catalog snapshot resolution runs against."""

    entries: tuple[CatalogEntry, ...]


@dataclass(frozen=True)
class RootRequest:
    """The operator's ask: install this extension within this range."""

    extension_name: str
    range_text: str = "*"


class LockKind(StrEnum):
    """Why a locked entry exists: required authority, or an optional branch."""

    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class ConstraintRecord:
    """One range constraint on one extension, with who declared it.

    Stored verbatim in the lock entry so the explanation of a version never
    depends on the catalog still being available.
    """

    origin: str
    range_text: str
    required: bool


@dataclass(frozen=True)
class RejectedCandidate:
    """A catalog version that was considered and excluded, and why."""

    semantic_version: str
    package_sha256: str
    reason: str


@dataclass(frozen=True)
class SkippedOptional:
    """An optional dependency that was not pinned, and exactly why.

    Recorded in the lock so an absent optional branch is visible, auditable
    evidence rather than a silent omission.
    """

    requirer: str
    target: str
    range_text: str
    reason: str


@dataclass(frozen=True)
class LockEntry:
    """One locked extension version: identity, source, and the why.

    The first five fields are the reproducibility contract (acceptance:
    "lock records include immutable version/digest/source identity"); the
    rest is the audit trail. ``required_by`` lists the origins whose
    *required* constraints pulled this entry in (with
    :data:`ROOT_REQUEST_ORIGIN` for the operator's own ask); ``optional_for``
    lists the extensions whose optional dependency selected it.
    """

    extension_name: str
    semantic_version: str
    package_sha256: str
    manifest_sha256: str
    source: str
    catalog_snapshot_sha256: str
    kind: LockKind
    required_by: tuple[str, ...]
    optional_for: tuple[str, ...]
    constraints: tuple[ConstraintRecord, ...]
    rejected: tuple[RejectedCandidate, ...]
    publisher_id: str
    signature: str

    @property
    def identity(self) -> PackageIdentity:
        """The immutable installed-version identity this entry pins."""
        return PackageIdentity(
            extension_name=self.extension_name,
            semantic_version=self.semantic_version,
            package_sha256=self.package_sha256,
            manifest_sha256=self.manifest_sha256,
        )

    @property
    def version(self) -> SemVer:
        return SemVer.parse(self.semantic_version)

    def sort_key(self) -> tuple[str, str, str, str]:
        """Total order over identities: name, version, then both digests."""
        return (
            self.extension_name,
            self.semantic_version,
            self.package_sha256,
            self.manifest_sha256,
        )


@dataclass(frozen=True)
class SelectionExplanation:
    """The operator-facing answer to "why this extension, why this version"."""

    entry: LockEntry
    present_because: str
    policy: str
    constraints: tuple[ConstraintRecord, ...]
    rejected: tuple[RejectedCandidate, ...]
    skipped_optional: tuple[SkippedOptional, ...]


@dataclass(frozen=True)
class LockState:
    """The reproducible result of resolution over one catalog snapshot.

    Immutable and JSON-round-trippable: :meth:`to_json` is canonical (sorted
    keys, fixed shape), so identical inputs produce byte-identical lock files
    and identical :meth:`lock_digest` values. The state carries no timestamps
    — reproducibility means nothing wall-clock-dependent may leak in.
    """

    format_version: str
    requests: tuple[RootRequest, ...]
    entries: tuple[LockEntry, ...]
    skipped_optional: tuple[SkippedOptional, ...]

    def get(self, extension_name: str) -> LockEntry | None:
        """The locked entry for one extension, or ``None``."""
        for entry in self.entries:
            if entry.extension_name == extension_name:
                return entry
        return None

    def identity_keys(self) -> set[tuple[str, str, str, str]]:
        """The full identity of every locked entry — the "same set" test."""
        return {identity_key(entry.identity) for entry in self.entries}

    def explain(self, extension_name: str) -> SelectionExplanation | None:
        """Why ``extension_name`` is locked at its version, or ``None``.

        Answers entirely from the lock: the recorded constraints, rejected
        candidates, and skipped optional branches — never by re-consulting
        the catalog, which may have changed or vanished since.
        """
        entry = self.get(extension_name)
        if entry is None:
            return None
        if ROOT_REQUEST_ORIGIN in entry.required_by:
            present = "requested directly by the install request"
        elif entry.kind is LockKind.OPTIONAL and entry.optional_for:
            present = f"optional dependency of {', '.join(entry.optional_for)}"
        else:
            present = f"required by {', '.join(entry.required_by)}"
        skipped = tuple(
            sorted(
                (
                    skip
                    for skip in self.skipped_optional
                    if skip.requirer == extension_name or skip.target == extension_name
                ),
                key=lambda skip: (skip.requirer, skip.target, skip.range_text),
            )
        )
        return SelectionExplanation(
            entry=entry,
            present_because=present,
            policy=SELECTION_POLICY,
            constraints=entry.constraints,
            rejected=entry.rejected,
            skipped_optional=skipped,
        )

    def to_dict(self) -> dict[str, object]:
        """The canonical JSON-shaped form (sorting happens in ``json.dumps``)."""
        return {
            "format": self.format_version,
            "requests": [
                {"extension_name": request.extension_name, "range": request.range_text}
                for request in self.requests
            ],
            "entries": [_entry_to_dict(entry) for entry in self.entries],
            "skipped_optional": [
                {
                    "requirer": skip.requirer,
                    "target": skip.target,
                    "range": skip.range_text,
                    "reason": skip.reason,
                }
                for skip in self.skipped_optional
            ],
        }

    def to_json(self) -> str:
        """Canonical serialization: sorted keys, fixed indent, trailing newline."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    def lock_digest(self) -> str:
        """The sha256 of the canonical compact form — the reproducibility proof."""
        return sha256_hex(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        )

    @classmethod
    def from_json(cls, raw: str) -> LockState:
        """Rebuild a lock from its canonical JSON, fail-closed.

        Every field is re-validated (format tag, strict versions, hex
        digests, kinds, non-empty sources and signatures) so a corrupted or
        truncated lock is a loud :class:`LockFormatError`, never a half-quiet
        rebuild that would silently install something else.
        """
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LockFormatError(f"lock payload is not valid JSON: {exc}") from exc
        return _lock_from_dict(payload)


def _entry_to_dict(entry: LockEntry) -> dict[str, object]:
    return {
        "extension_name": entry.extension_name,
        "semantic_version": entry.semantic_version,
        "package_sha256": entry.package_sha256,
        "manifest_sha256": entry.manifest_sha256,
        "source": entry.source,
        "catalog_snapshot_sha256": entry.catalog_snapshot_sha256,
        "kind": str(entry.kind),
        "required_by": list(entry.required_by),
        "optional_for": list(entry.optional_for),
        "constraints": [
            {
                "origin": constraint.origin,
                "range": constraint.range_text,
                "required": constraint.required,
            }
            for constraint in entry.constraints
        ],
        "rejected": [
            {
                "semantic_version": candidate.semantic_version,
                "package_sha256": candidate.package_sha256,
                "reason": candidate.reason,
            }
            for candidate in entry.rejected
        ],
        "publisher_id": entry.publisher_id,
        "signature": entry.signature,
    }


def _require_str(payload: dict[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LockFormatError(f"{context}: field {key!r} must be a non-empty string")
    return value


def _require_hex64(payload: dict[str, object], key: str, context: str) -> str:
    value = _require_str(payload, key, context)
    if _HEX64.match(value) is None:
        raise LockFormatError(f"{context}: field {key!r} must be a hex sha256 digest")
    return value


def _require_bool(payload: dict[str, object], key: str, context: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise LockFormatError(f"{context}: field {key!r} must be a boolean")
    return value


def _require_str_list(payload: dict[str, object], key: str, context: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise LockFormatError(f"{context}: field {key!r} must be a list of strings")
    return tuple(value)


def _lock_from_dict(payload: object) -> LockState:
    """Validate and rebuild a lock from its parsed JSON form."""
    if not isinstance(payload, dict):
        raise LockFormatError("lock payload must be a JSON object")
    if payload.get("format") != LOCK_FORMAT:
        raise LockFormatError(
            f"lock payload names format {payload.get('format')!r}; this host reads {LOCK_FORMAT!r}"
        )
    requests_payload = payload.get("requests")
    if not isinstance(requests_payload, list):
        raise LockFormatError("lock payload field 'requests' must be a list")
    requests = tuple(
        RootRequest(
            extension_name=_require_str(item, "extension_name", "lock request"),
            range_text=_require_str(item, "range", "lock request"),
        )
        for item in requests_payload
    )
    entries_payload = payload.get("entries")
    if not isinstance(entries_payload, list):
        raise LockFormatError("lock payload field 'entries' must be a list")
    entries = tuple(_entry_from_dict(item) for item in entries_payload)
    skips_payload = payload.get("skipped_optional")
    if not isinstance(skips_payload, list):
        raise LockFormatError("lock payload field 'skipped_optional' must be a list")
    skips = tuple(
        SkippedOptional(
            requirer=_require_str(item, "requirer", "skipped optional"),
            target=_require_str(item, "target", "skipped optional"),
            range_text=_require_str(item, "range", "skipped optional"),
            reason=_require_str(item, "reason", "skipped optional"),
        )
        for item in skips_payload
    )
    return LockState(
        format_version=LOCK_FORMAT,
        requests=requests,
        entries=entries,
        skipped_optional=skips,
    )


def _entry_from_dict(item: object) -> LockEntry:
    context = "lock entry"
    if not isinstance(item, dict):
        raise LockFormatError("lock entries must be JSON objects")
    name = _require_str(item, "extension_name", context)
    detail = f"lock entry {name!r}"
    version = _require_str(item, "semantic_version", detail)
    try:
        SemVer.parse(version)
    except InvalidSemanticVersion as exc:
        raise LockFormatError(
            f"{detail}: semantic_version {version!r} is not MAJOR.MINOR.PATCH: {exc}"
        ) from exc
    kind_text = _require_str(item, "kind", detail)
    try:
        kind = LockKind(kind_text)
    except ValueError as exc:
        raise LockFormatError(f"{detail}: unknown kind {kind_text!r}") from exc
    constraints_payload = item.get("constraints")
    if not isinstance(constraints_payload, list):
        raise LockFormatError(f"{detail}: field 'constraints' must be a list")
    constraints = tuple(
        ConstraintRecord(
            origin=_require_str(constraint, "origin", detail),
            range_text=_require_str(constraint, "range", detail),
            required=_require_bool(constraint, "required", detail),
        )
        for constraint in constraints_payload
    )
    rejected_payload = item.get("rejected")
    if not isinstance(rejected_payload, list):
        raise LockFormatError(f"{detail}: field 'rejected' must be a list")
    rejected = tuple(
        RejectedCandidate(
            semantic_version=_require_str(candidate, "semantic_version", detail),
            package_sha256=_require_hex64(candidate, "package_sha256", detail),
            reason=_require_str(candidate, "reason", detail),
        )
        for candidate in rejected_payload
    )
    return LockEntry(
        extension_name=name,
        semantic_version=version,
        package_sha256=_require_hex64(item, "package_sha256", detail),
        manifest_sha256=_require_hex64(item, "manifest_sha256", detail),
        source=_require_str(item, "source", detail),
        catalog_snapshot_sha256=_require_hex64(item, "catalog_snapshot_sha256", detail),
        kind=kind,
        required_by=_require_str_list(item, "required_by", detail),
        optional_for=_require_str_list(item, "optional_for", detail),
        constraints=constraints,
        rejected=rejected,
        publisher_id=_require_str(item, "publisher_id", detail),
        signature=_require_str(item, "signature", detail),
    )


@dataclass(frozen=True)
class _Selection:
    """Internal: one chosen version plus the evidence explaining it."""

    entry: CatalogEntry | None  # ``None`` for a pinned identity match
    constraints: tuple[ConstraintRecord, ...]
    rejected: tuple[RejectedCandidate, ...]
    pinned: bool = False
    pinned_identity: PackageIdentity | None = None

    @property
    def version(self) -> SemVer:
        """The selected (or pinned) semantic version."""
        if self.entry is not None:
            return self.entry.version
        assert self.pinned_identity is not None, "pinned selection without an identity"
        return SemVer.parse(self.pinned_identity.semantic_version)

    @property
    def identity(self) -> PackageIdentity:
        if self.entry is not None:
            return self.entry.identity
        assert self.pinned_identity is not None, "pinned selection without an identity"
        return self.pinned_identity


def _candidate_order(entry: CatalogEntry) -> tuple[str, str, str, str]:
    """Total selection order: version, then digests, then source, descending."""
    return (
        entry.identity.semantic_version,
        entry.identity.package_sha256,
        entry.identity.manifest_sha256,
        entry.source,
    )


class _CatalogIndex:
    """Name-indexed view of the catalog snapshot, sorted deterministically."""

    def __init__(self, catalog: ExtensionCatalog) -> None:
        by_name: dict[str, list[CatalogEntry]] = {}
        for entry in catalog.entries:
            by_name.setdefault(entry.identity.extension_name, []).append(entry)
        for versions in by_name.values():
            versions.sort(key=_candidate_order)
        self._by_name = by_name

    def versions(self, extension_name: str) -> tuple[CatalogEntry, ...]:
        """Every catalog version of one extension, in deterministic order."""
        return tuple(self._by_name.get(extension_name, ()))


class _Engine:
    """Single-pass required-constraint resolver over one catalog index.

    One engine per resolution scope: the outer install resolves with no
    pinned identities; an optional branch resolves with the entries already
    locked supplied as ``pinned`` (it may constrain them but never re-select
    them). Raises :class:`ResolutionConflict` / :class:`DependencyCycle`;
    optional-branch callers catch and convert to a skip.
    """

    def __init__(self, index: _CatalogIndex, *, pinned: Mapping[str, PackageIdentity]) -> None:
        self._index = index
        self._pinned = dict(pinned)
        self._constraints: dict[str, list[ConstraintRecord]] = {}
        self._ranges: dict[str, list[VersionRange]] = {}
        self._selected: dict[str, _Selection] = {}
        self.optional_edges: list[tuple[str, ExtensionDependency]] = []

    def require(self, target: str, range_text: str, *, origin: str, required: bool = True) -> None:
        """Accumulate one constraint; validate immediately against selections.

        A constraint on an already-selected extension is checked on the spot:
        violated, it is a conflict with a full explanation — the no-backtracking
        policy made visible at the moment it bites.
        """
        if not target.strip():
            raise UnresolvableDependency(f"{origin} declares a dependency with an empty target id")
        try:
            version_range = parse_range(range_text)
        except InvalidVersionRange as exc:
            raise UnresolvableDependency(
                f"{origin} declares an unusable version range {range_text!r} for {target!r}: {exc}"
            ) from exc
        record = ConstraintRecord(origin=origin, range_text=range_text, required=required)
        self._constraints.setdefault(target, []).append(record)
        self._ranges.setdefault(target, []).append(version_range)
        self._check_against(target, record, version_range)

    def _check_against(
        self, target: str, record: ConstraintRecord, version_range: VersionRange
    ) -> None:
        selected = self._selected.get(target)
        if selected is not None:
            if not version_range.satisfied_by(selected.version):
                raise ResolutionConflict(
                    f"cannot reconcile constraints for {target!r}: "
                    f"{selected.version} was already selected, but "
                    f"{record.origin} requires '{record.range_text}'; "
                    f"resolution does not backtrack ({SELECTION_POLICY})"
                )
            return
        pinned = self._pinned.get(target)
        if pinned is not None:
            if not version_range.satisfied_by(SemVer.parse(pinned.semantic_version)):
                raise ResolutionConflict(
                    f"cannot reconcile constraints for {target!r}: the lock already pins "
                    f"{pinned.semantic_version}, but {record.origin} requires "
                    f"'{record.range_text}'; a new selection would override pinned authority"
                )
            self._selected[target] = _Selection(
                entry=None,
                constraints=(record,),
                rejected=(),
                pinned=True,
                pinned_identity=pinned,
            )

    def run(self) -> dict[str, _Selection]:
        """Resolve everything constrained so far; refuse cycles."""
        while True:
            pending = sorted(name for name in self._constraints if name not in self._selected)
            if not pending:
                break
            self._select(pending[0])
        cycle = _find_required_cycle(self._selected)
        if cycle is not None:
            raise DependencyCycle(
                f"required dependency cycle: {' -> '.join(cycle)}; a cyclic ecosystem "
                "cannot be activated in dependency order, so nothing is installed"
            )
        return self._selected

    def _select(self, name: str) -> None:
        constraints = tuple(self._constraints[name])
        ranges = tuple(self._ranges[name])
        available = self._index.versions(name)
        candidates = [
            entry for entry in available if all(r.satisfied_by(entry.version) for r in ranges)
        ]
        if not candidates:
            raise _conflict(name, constraints, ranges, available)
        chosen = max(candidates, key=_candidate_order)
        self._selected[name] = _Selection(
            entry=chosen,
            constraints=constraints,
            rejected=_rejected_candidates(available, chosen, constraints, ranges),
        )
        self._enqueue_declared(name, chosen)

    def _enqueue_declared(self, name: str, chosen: CatalogEntry) -> None:
        """Fan one selection's manifest declarations out to the engine."""
        for dependency in sorted(chosen.dependencies, key=ExtensionDependency.sort_key):
            if dependency.required:
                self.require(dependency.target, dependency.range_text, origin=name)
                continue
            # Validate the optional range eagerly too: a malformed declared
            # range is a broken manifest on a *required* selection, so it
            # fails resolution here rather than surfacing mid-optional-phase.
            try:
                parse_range(dependency.range_text)
            except InvalidVersionRange as exc:
                raise UnresolvableDependency(
                    f"{name} declares an unusable optional version range "
                    f"{dependency.range_text!r} for {dependency.target!r}: {exc}"
                ) from exc
            self.optional_edges.append((name, dependency))


def _rejected_candidates(
    available: tuple[CatalogEntry, ...],
    chosen: CatalogEntry,
    constraints: tuple[ConstraintRecord, ...],
    ranges: tuple[VersionRange, ...],
) -> tuple[RejectedCandidate, ...]:
    """Every non-selected catalog version, with the reason it lost.

    A version that failed a constraint quotes that constraint and its origin;
    a version that satisfied everything but lost the deterministic tie-break
    is recorded as exactly that, so an operator is never left guessing why a
    plausible-looking version was passed over.
    """
    return tuple(
        RejectedCandidate(
            semantic_version=candidate.identity.semantic_version,
            package_sha256=candidate.identity.package_sha256,
            reason=_first_violation(candidate, constraints, ranges) or _tie_break_sentence(),
        )
        for candidate in available
        if candidate != chosen
    )


def _first_violation(
    candidate: CatalogEntry,
    constraints: tuple[ConstraintRecord, ...],
    ranges: tuple[VersionRange, ...],
) -> str | None:
    """The first constraint a candidate fails, with its origin; ``None`` if none."""
    for record, version_range in zip(constraints, ranges, strict=True):
        reason = version_range.violated_by_reason(candidate.version)
        if reason is not None:
            authority = "required by" if record.required else "allowed by"
            return f"{reason} ({authority} {record.origin}: '{record.range_text}')"
    return None


def _tie_break_sentence() -> str:
    return (
        "satisfied every constraint; not selected — lost the deterministic "
        "tie-break (version, digest, source order)"
    )


def _conflict(
    name: str,
    constraints: tuple[ConstraintRecord, ...],
    ranges: tuple[VersionRange, ...],
    available: tuple[CatalogEntry, ...],
) -> ResolutionConflict:
    """The full diagnostic for an unsatisfiable constraint set."""
    lines = [f"cannot resolve {name!r}: no catalog version satisfies every constraint"]
    for record in constraints:
        polarity = "" if record.required else " (optional)"
        lines.append(f"  constraint: '{record.range_text}' — {record.origin}{polarity}")
    if not available:
        lines.append("  the catalog offers no versions of this extension")
    for candidate in available:
        reason = _first_violation(candidate, constraints, ranges) or _tie_break_sentence()
        lines.append(
            f"  candidate {candidate.identity.semantic_version} "
            f"(package sha256:{candidate.identity.package_sha256[:12]}…): {reason}"
        )
    lines.append(f"  policy: {SELECTION_POLICY}")
    return ResolutionConflict("\n".join(lines))


def _required_dependency_graph(selected: Mapping[str, _Selection]) -> dict[str, list[str]]:
    """Requirer → required-target edges between selected entries, sorted."""
    graph: dict[str, list[str]] = {}
    for name, selection in selected.items():
        if selection.entry is None:
            continue
        graph[name] = sorted(
            dependency.target
            for dependency in selection.entry.dependencies
            if dependency.required and dependency.target in selected
        )
    return graph


def _find_required_cycle(selected: Mapping[str, _Selection]) -> list[str] | None:
    """First required-edge cycle in deterministic DFS order, or ``None``.

    Edges run requirer → required target between *selected* entries; every
    required target of a selected entry is itself selected (otherwise
    resolution already raised), so the graph is closed. Nodes and neighbors
    are visited sorted, so the reported cycle is stable across runs.
    """
    graph = _required_dependency_graph(selected)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(sorted(graph), WHITE)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for neighbor in graph.get(node, ()):
            if color[neighbor] == GRAY:
                return [*stack[stack.index(neighbor) :], neighbor]
            if color[neighbor] == WHITE:
                found = visit(neighbor)
                if found is not None:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            found = visit(node)
            if found is not None:
                return found
    return None


def resolve_lock(requests: Sequence[RootRequest], catalog: ExtensionCatalog) -> LockState:
    """Resolve install requests against a catalog snapshot into a lock.

    Deterministic: identical (request, catalog) inputs always yield an equal
    — byte-identical under :meth:`LockState.to_json` — lock, regardless of
    the order entries appear in the catalog. Raises :class:`ResolutionConflict`
    (unsatisfiable or late-violating constraints), :class:`DependencyCycle`
    (required cycle), or :class:`UnresolvableDependency` (malformed
    declaration) before any lock exists — and therefore before any extension
    is fetched or activated.
    """
    index = _CatalogIndex(catalog)
    engine = _Engine(index, pinned={})
    for request in requests:
        engine.require(request.extension_name, request.range_text, origin=ROOT_REQUEST_ORIGIN)
    selected = engine.run()

    entries: dict[str, LockEntry] = {}
    for name in sorted(selected):
        selection = selected[name]
        assert selection.entry is not None, "outer resolution never pins"
        entries[name] = _lock_entry(selection, kind=LockKind.REQUIRED, optional_for=())
    skips, entries = _resolve_optionals(engine.optional_edges, index, entries)
    return LockState(
        format_version=LOCK_FORMAT,
        requests=tuple(
            sorted(requests, key=lambda request: (request.extension_name, request.range_text))
        ),
        entries=tuple(sorted(entries.values(), key=LockEntry.sort_key)),
        skipped_optional=tuple(
            sorted(skips, key=lambda skip: (skip.requirer, skip.target, skip.range_text))
        ),
    )


def _lock_entry(
    selection: _Selection, *, kind: LockKind, optional_for: tuple[str, ...]
) -> LockEntry:
    """Materialize one lock entry from a selection and its evidence."""
    assert selection.entry is not None
    identity = selection.entry.identity
    required_by = tuple(
        dict.fromkeys(
            constraint.origin for constraint in selection.constraints if constraint.required
        )
    )
    return LockEntry(
        extension_name=identity.extension_name,
        semantic_version=identity.semantic_version,
        package_sha256=identity.package_sha256,
        manifest_sha256=identity.manifest_sha256,
        source=selection.entry.source,
        catalog_snapshot_sha256=selection.entry.catalog_snapshot_sha256,
        kind=kind,
        required_by=required_by,
        optional_for=optional_for,
        constraints=selection.constraints,
        rejected=selection.rejected,
        publisher_id=selection.entry.publisher_id,
        signature=selection.entry.signature,
    )


def _resolve_optionals(
    edges: Sequence[tuple[str, ExtensionDependency]],
    index: _CatalogIndex,
    entries: dict[str, LockEntry],
) -> tuple[list[SkippedOptional], dict[str, LockEntry]]:
    """Attempt every optional edge; pin clean branches, record the rest.

    Runs to a fixpoint after the required graph is fixed: a freshly pinned
    optional branch contributes its own optional edges, processed in
    deterministic order. Nothing here can raise — every failure mode of an
    optional branch becomes a :class:`SkippedOptional` with its reason,
    which is exactly the "optional never becomes required authority" rule.
    """
    skips: list[SkippedOptional] = []
    optional_for: dict[str, set[str]] = {}
    extra_constraints: dict[str, list[ConstraintRecord]] = {}
    queue = list(edges)
    processed: set[tuple[str, str, str, bool]] = set()
    while queue:
        queue.sort(key=lambda edge: (edge[0], edge[1].sort_key()))
        requirer, dependency = queue.pop(0)
        edge_key = (requirer, dependency.target, dependency.range_text, dependency.required)
        if edge_key in processed:
            continue
        processed.add(edge_key)
        queue.extend(
            _process_optional_edge(
                requirer,
                dependency,
                index,
                entries,
                skips,
                optional_for,
                extra_constraints,
            )
        )
    for name, requirers in optional_for.items():
        entries[name] = replace(
            entries[name],
            optional_for=tuple(sorted(requirers)),
            constraints=entries[name].constraints + tuple(extra_constraints.get(name, ())),
        )
    return skips, entries


def _process_optional_edge(
    requirer: str,
    dependency: ExtensionDependency,
    index: _CatalogIndex,
    entries: dict[str, LockEntry],
    skips: list[SkippedOptional],
    optional_for: dict[str, set[str]],
    extra_constraints: dict[str, list[ConstraintRecord]],
) -> list[tuple[str, ExtensionDependency]]:
    """One optional edge: satisfy, associate, or skip — never fail.

    Returns the optional edges of any entries the branch newly pinned, so the
    caller's fixpoint loop can process them.
    """
    locked = entries.get(dependency.target)
    if locked is not None:
        _associate_locked_optional(
            requirer, dependency, locked, skips, optional_for, extra_constraints
        )
        return []
    return _pin_optional_branch(requirer, dependency, index, entries, skips)


def _associate_locked_optional(
    requirer: str,
    dependency: ExtensionDependency,
    locked: LockEntry,
    skips: list[SkippedOptional],
    optional_for: dict[str, set[str]],
    extra_constraints: dict[str, list[ConstraintRecord]],
) -> None:
    """Record an optional edge onto an already-locked target.

    A satisfying locked version gains the association and the verbatim
    (optional) constraint; a violating one is a recorded skip. Either way the
    locked identity is untouched — optional authority never re-selects.
    """
    target = dependency.target
    version_range = parse_range(dependency.range_text)
    if version_range.satisfied_by(locked.version):
        optional_for.setdefault(target, set()).add(requirer)
        extra_constraints.setdefault(target, []).append(
            ConstraintRecord(origin=requirer, range_text=dependency.range_text, required=False)
        )
        return
    skips.append(
        SkippedOptional(
            requirer=requirer,
            target=target,
            range_text=dependency.range_text,
            reason=(
                f"locked {target}@{locked.semantic_version} does not satisfy "
                f"'{dependency.range_text}'"
            ),
        )
    )


def _pin_optional_branch(
    requirer: str,
    dependency: ExtensionDependency,
    index: _CatalogIndex,
    entries: dict[str, LockEntry],
    skips: list[SkippedOptional],
) -> list[tuple[str, ExtensionDependency]]:
    """Resolve the optional target's own required graph, all-or-nothing.

    Any resolution failure — absent, unsatisfiable, cyclic, or incompatible
    with what the lock already pins — becomes a recorded skip; the requiring
    extension stays installable. Newly pinned entries are returned together
    with their optional edges for the caller's fixpoint loop.
    """
    target = dependency.target
    branch = _Engine(index, pinned={name: entry.identity for name, entry in entries.items()})
    try:
        branch.require(target, dependency.range_text, origin=requirer)
        selected = branch.run()
    except ResolutionError as exc:
        skips.append(
            SkippedOptional(
                requirer=requirer,
                target=target,
                range_text=dependency.range_text,
                reason=str(exc).splitlines()[0],
            )
        )
        return []
    return _merge_branch(requirer, target, selected, entries)


def _merge_branch(
    requirer: str,
    target: str,
    selected: dict[str, _Selection],
    entries: dict[str, LockEntry],
) -> list[tuple[str, ExtensionDependency]]:
    """Add the branch's fresh selections as optional entries.

    Pinned selections are already in the lock and are left alone. The branch
    head is marked ``optional_for`` the requirer; its transitive required
    members point at their in-branch requirer instead, so ``explain`` shows
    the full chain.
    """
    new_edges: list[tuple[str, ExtensionDependency]] = []
    for name in sorted(selected):
        selection = selected[name]
        if selection.pinned:
            continue  # already locked; the branch only constrained it
        assert selection.entry is not None
        entries[name] = _lock_entry(
            selection, kind=LockKind.OPTIONAL, optional_for=(requirer,) if name == target else ()
        )
        new_edges.extend(
            (name, declared) for declared in selection.entry.dependencies if not declared.required
        )
    return new_edges


@dataclass(frozen=True)
class LockArtifacts:
    """The bytes a lock entry needs to become an installed record."""

    package_bytes: bytes
    manifest_body: str


@runtime_checkable
class LockArtifactFetcher(Protocol):
    """Where materialization gets the locked bytes from.

    Returns ``None`` for "unavailable" — a missing artifact is an expected,
    diagnosable outcome of reproducing an old lock, not an exception, so the
    caller can report *all* missing entries at once.
    """

    async def fetch_lock_artifact(self, entry: LockEntry) -> LockArtifacts | None: ...


async def materialize_lock(
    lock: LockState,
    store: ExtensionInstallStore,
    fetcher: LockArtifactFetcher,
    *,
    now: datetime | None = None,
    activate: ActivationCallback | None = None,
) -> list[InstallRecord]:
    """Reinstall every locked identity through the real install store.

    The reproducibility half of the contract: given the lock, fetch each
    entry's artifacts and drive it through the store's digest and signature
    verification. If *any* artifact is unavailable, raise
    :class:`MissingLockArtifacts` naming every missing entry — before a
    single record is written or ``activate`` runs — so a restart either
    recreates the exact extension set or fails explicitly. Verification
    failures (wrong bytes, bad signature) raise from the store before
    persistence and activation, exactly as a first-time install would.
    """
    fetched: list[tuple[LockEntry, LockArtifacts]] = []
    missing: list[LockEntry] = []
    for entry in lock.entries:
        artifacts = await fetcher.fetch_lock_artifact(entry)
        if artifacts is None:
            missing.append(entry)
        else:
            fetched.append((entry, artifacts))
    if missing:
        detail = "; ".join(
            f"{entry.extension_name}@{entry.semantic_version} "
            f"(package sha256:{entry.package_sha256[:12]}…, source {entry.source})"
            for entry in missing
        )
        raise MissingLockArtifacts(
            f"cannot recreate {len(missing)} of {len(lock.entries)} locked extensions — "
            f"artifacts unavailable: {detail}. Nothing was installed or activated."
        )
    if now is None:
        now = datetime.now(UTC)
    records: list[InstallRecord] = []
    for entry, artifacts in fetched:
        request = InstallRequest(
            identity=entry.identity,
            publisher_id=entry.publisher_id,
            signature=entry.signature,
            manifest_body=artifacts.manifest_body,
            provenance=RegistryProvenance(
                catalog_url=entry.source,
                catalog_snapshot_sha256=entry.catalog_snapshot_sha256,
                retrieved_at=now,
            ),
        )
        records.append(
            await store.record_install(
                request, package_bytes=artifacts.package_bytes, activate=activate
            )
        )
    return records


@dataclass(frozen=True)
class LockDiff:
    """What an update changes between two locks, as exact identities."""

    added: tuple[PackageIdentity, ...]
    removed: tuple[PackageIdentity, ...]
    changed: tuple[tuple[PackageIdentity, PackageIdentity], ...]


def diff_locks(old: LockState, new: LockState) -> LockDiff:
    """Compare two locks by immutable identity — the update-time view.

    An extension whose name/version/digests all match is unchanged even if
    its justification changed; a same-name entry with a different identity is
    a *change* (old → new), which is what an upgrade or a downgrade looks
    like here. Nothing about ordering or reasons is compared: identity is the
    only thing installs are pinned to.
    """
    old_by_name = {entry.extension_name: entry for entry in old.entries}
    new_by_name = {entry.extension_name: entry for entry in new.entries}
    added = tuple(
        sorted(
            (entry.identity for name, entry in new_by_name.items() if name not in old_by_name),
            key=lambda identity: (identity.extension_name, identity.semantic_version),
        )
    )
    removed = tuple(
        sorted(
            (entry.identity for name, entry in old_by_name.items() if name not in new_by_name),
            key=lambda identity: (identity.extension_name, identity.semantic_version),
        )
    )
    changed = tuple(
        sorted(
            (
                (old_by_name[name].identity, entry.identity)
                for name, entry in new_by_name.items()
                if name in old_by_name
                and identity_key(old_by_name[name].identity) != identity_key(entry.identity)
            ),
            key=lambda pair: (pair[0].extension_name, pair[1].semantic_version),
        )
    )
    return LockDiff(added=added, removed=removed, changed=changed)
