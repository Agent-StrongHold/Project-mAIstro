"""Extension contract compatibility: versioning, negotiation, deprecation (M9-C1, #955).

This module is the host half of the extension contract policy. It defines how
MAIstro and an extension agree on supported public contracts over time,
without ever consulting private implementation details:

* **The contract is versioned on its own semantic axis.** The extension
  contract — the manifest fields, the authority vocabulary, the negotiation
  behavior an extension author codes against — versions independently of the
  application. ADR-073126-c4e1's lockstep rule governs *published package*
  versions (sourced from the root ``VERSION`` file); it does not govern
  contract semantics. This module adds that second axis explicitly, exactly as
  ADR-076 did for the HTTP surface: a manifest written against contract 1.x
  keeps negotiating no matter how many application releases ship in between.

* **Compatibility is decided from metadata, before any code import.** Every
  input to :func:`negotiate` is plain data — a version, a range, a feature
  name. There is no field anywhere in the model that carries a module path, an
  entrypoint, or an importable name, so a host can reject or accept an
  extension before the extension's code exists on disk, let alone executes.

* **Optional features degrade explicitly.** A feature the host will not
  provide lands in the report's ``degradations`` and is *absent* from
  ``supported_features`` — the machine-readable set a runtime grants from.
  Pretending support is structurally impossible: the only way a feature name
  reaches the granted set is by passing the same checks a required feature
  passes.

* **Unsupported contract combinations fail with actionable reasons.** A
  verdict of ``incompatible`` always carries reasons naming the extension's
  declared range, the host's contract version, and which boundary was missed
  (a contract-major break, or a same-major window the manifest requires and
  the host does not implement). :func:`ensure_compatible` turns those reasons
  into one exception for hosts that prefer fail-fast.

* **Deprecations are machine-readable with documented removal targets.** A
  feature moves through the closed status set ``supported → deprecated →
  removed``. ``deprecated`` *requires* a ``removal_target`` and migration
  prose; the removal target must be a future contract major (removing a
  feature is a breaking change, and breaking changes only land at major
  boundaries), so the support window is enforced by construction, not by
  promise. ``removed`` rows stay in the host table so a manifest can be told
  *when* a feature went away and where to migrate, instead of discovering a
  bare unknown-feature error.

* **Compatibility never depends on the application patch version or private
  module paths.** :class:`HostContractMetadata` has no application-version
  field — the negotiation is a pure function of contract metadata, so two
  hosts that implement the same contract behave identically regardless of what
  application release carries them. Error text names versions and feature
  names only.

Reconciliation note: the author-facing SDK (``maistro-ext-sdk``, M9-A1)
publishes the manifest and validates its ``contract`` range at authoring time
with the same range grammar this module parses. The two modules version the
same contract from opposite sides and intentionally agree on syntax; when both
trees are co-installed, the SDK's manifest layer feeds
:func:`parse_compat_metadata` and this module remains the deciding authority.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from maistro.extensions.types import ExtensionRegistryError

__all__ = [
    "CONTRACT_VERSION",
    "HOST_FEATURES",
    "SUPPORTED_CONTRACT_MAJORS",
    "CompatError",
    "CompatMetadataError",
    "CompatibilityReport",
    "ContractRange",
    "ContractVersion",
    "Degradation",
    "DeprecationNotice",
    "ExtensionCompatMetadata",
    "FeatureStatus",
    "FeatureSupport",
    "HostContractMetadata",
    "IncompatibleContract",
    "Verdict",
    "ensure_compatible",
    "negotiate",
    "parse_compat_metadata",
    "parse_contract_range",
    "parse_contract_version",
]


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class CompatError(ExtensionRegistryError):
    """Base class for contract-compatibility failures."""


class CompatMetadataError(CompatError):
    """An extension's compatibility metadata is malformed.

    Raised by :func:`parse_compat_metadata` for unknown keys, wrong types, bad
    feature names, and unparsable contract ranges. The message names the
    offending token so an author can fix the manifest without reading host
    source.
    """


class IncompatibleContract(CompatError):
    """Negotiation produced an ``incompatible`` verdict.

    Raised by :func:`ensure_compatible`; the message is the report's reasons
    joined, so what the caller sees is exactly what the report said.
    """


# ---------------------------------------------------------------------------
# contract version policy — the semantic axis, independent of the app
# ---------------------------------------------------------------------------

#: Strict ``MAJOR.MINOR.PATCH`` grammar for contract versions: no leading
#: zeros, no empty components, no prerelease/build suffixes. A contract
#: version names a schema, and a schema version that parses two ways would let
#: a manifest mean different things to the author and the host.
_CONTRACT_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

#: The extension contract version this host implements. A literal on purpose —
#: never derived from the package version, the root ``VERSION`` file, or any
#: installed distribution (see the module docstring for the ADR-073126-c4e1
#: reconciliation). Bump the major only for a breaking change to the contract
#: vocabulary; add fields and features with defaults without bumping.
CONTRACT_VERSION = "1.0.0"

#: Every contract major this host can load. A manifest whose range resolves
#: only to an unsupported major is refused before any code runs; a future 2.x
#: contract lands behind a new row here, never by silently reinterpreting 1.x
#: documents.
SUPPORTED_CONTRACT_MAJORS = (1,)


@dataclass(frozen=True, order=True)
class ContractVersion:
    """A parsed contract version — ``(major, minor, patch)``, ordered.

    Major bumps mark breaking changes to the contract; minor bumps add
    features backward-compatibly; patch bumps fix the contract text without
    changing it. ``order=True`` gives the lexicographic ordering the range
    arithmetic needs.
    """

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_contract_version(value: str) -> ContractVersion:
    """Parse a strict ``MAJOR.MINOR.PATCH`` contract version.

    Raises :class:`CompatMetadataError` on anything else — a malformed version
    is an explicit failure naming the expectation, never a silent coercion
    (``"1.04.0"`` is not ``1.4.0``).
    """
    if not _CONTRACT_VERSION_RE.match(value):
        raise CompatMetadataError(
            f"contract version must be MAJOR.MINOR.PATCH without leading zeros "
            f"or prerelease suffixes, got {value!r} (host implements {CONTRACT_VERSION})"
        )
    major, minor, patch = (int(part) for part in value.split("."))
    return ContractVersion(major=major, minor=minor, patch=patch)


_RANGE_SPEC_RE = re.compile(r"^(>=|<=|==|>|<)(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

_OPS = (">=", "<=", "==", ">", "<")


@dataclass(frozen=True)
class ContractRange:
    """A comma-joined set of version specifiers over contract versions.

    The grammar is the capping convention this monorepo already uses
    (``>=X,<X+1`` per ADR-073126-c4e1): ``>=``, ``>``, ``==``, ``<``, ``<=``
    over strict contract versions, comma-joined, conjunction semantics. An
    empty range parses as an error — a manifest that declares no constraint
    has not opted out of compatibility, it has failed to state it.
    """

    text: str
    specs: tuple[tuple[str, ContractVersion], ...]

    @staticmethod
    def parse(text: str) -> ContractRange:
        """Parse a ``">=1.0.0,<2.0.0"``-style range; explicit errors otherwise."""
        if not isinstance(text, str) or not text.strip():
            raise CompatMetadataError(
                "contract range must be a non-empty comma-joined set of "
                "specifiers (>=, >, ==, <, <= over MAJOR.MINOR.PATCH)"
            )
        specs: list[tuple[str, ContractVersion]] = []
        for raw in text.split(","):
            token = raw.strip()
            match = _RANGE_SPEC_RE.match(token)
            if match is None:
                raise CompatMetadataError(
                    f"unsupported contract specifier {token!r} in range {text!r}: expected "
                    f">=, >, ==, <, or <= over MAJOR.MINOR.PATCH"
                )
            specs.append((match.group(1), parse_contract_version(token[len(match.group(1)) :])))
        return ContractRange(text=text, specs=tuple(specs))

    def satisfied_by(self, version: ContractVersion) -> bool:
        """Whether ``version`` satisfies every specifier in the range."""
        return all(_spec_satisfied(op, bound, version) for op, bound in self.specs)

    def explain(self, version: ContractVersion, *, supported_majors: Sequence[int]) -> str:
        """An actionable reason the range excludes ``version``.

        Meaningful only when :meth:`satisfied_by` is false. Names the declared
        range, the host's contract version, the supported majors, and which
        policy boundary was missed: a contract-major break (never bridgeable
        by a host patch) or a same-major window the manifest requires and the
        host does not implement.
        """
        failing = [
            (op, bound) for op, bound in self.specs if not _spec_satisfied(op, bound, version)
        ]
        detail = ", ".join(f"{op}{bound}" for op, bound in failing)
        majors = ", ".join(str(major) for major in supported_majors)
        boundary = _missed_boundary(failing, version)
        return (
            f"extension requires contract range {self.text}, which excludes this "
            f"host's contract version {version} (supported contract majors: "
            f"{majors}; failing constraints: {detail}) — {boundary}"
        )


def _spec_satisfied(op: str, bound: ContractVersion, version: ContractVersion) -> bool:
    if op == ">=":
        return version >= bound
    if op == ">":
        return version > bound
    if op == "==":
        return version == bound
    if op == "<":
        return version < bound
    if op == "<=":
        return version <= bound
    raise CompatError(f"unknown range operator {op!r}")  # pragma: no cover - grammar-closed


def _missed_boundary(
    failing: Sequence[tuple[str, ContractVersion]], version: ContractVersion
) -> str:
    """Which policy boundary the failing specifiers put this host behind."""
    floors = [bound for op, bound in failing if op in (">=", ">")]
    caps = [bound for op, bound in failing if op in ("<", "<=")]
    if floors and all(bound.major > version.major for bound in floors):
        return (
            "the range requires a newer contract major than this host "
            "implements — a breaking boundary no host patch can bridge"
        )
    if floors:
        return "the manifest requires a same-major contract floor this host does not implement"
    if caps:
        return (
            "the manifest's range ended before this host's contract version — "
            "the extension predates the contract this host implements"
        )
    return "the manifest pins an exact contract version this host does not implement"


def parse_contract_range(text: str) -> ContractRange:
    """Named parse surface for :class:`ContractRange` (mirrors the SDK's)."""
    return ContractRange.parse(text)


# ---------------------------------------------------------------------------
# feature declarations — required vs optional, with machine-readable status
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureStatus:
    """The closed lifecycle of a host feature, machine-readable by design.

    ``FEATURE_SUPPORTED`` → ``FEATURE_DEPRECATED`` (removal target declared,
    migration path documented) → ``FEATURE_REMOVED`` (gone; the row remains so
    manifests can be told when it went away and where to migrate). Nothing
    outside this set can describe a feature, and the transitions carry
    evidence — see :class:`FeatureSupport` for what each state must carry.

    A closed set of singletons rather than an enum so the *value* — the
    machine-readable string reports emit — is the only spelling of the
    vocabulary, and no member can be constructed ad hoc.
    """

    value: str

    def __str__(self) -> str:
        return self.value


FEATURE_SUPPORTED = FeatureStatus("supported")
FEATURE_DEPRECATED = FeatureStatus("deprecated")
FEATURE_REMOVED = FeatureStatus("removed")

#: The closed status set; :func:`parse_feature_status` is the only string→
#: status path, so tooling cannot mint a status the policy does not define.
FEATURE_STATUSES: tuple[FeatureStatus, ...] = (
    FEATURE_SUPPORTED,
    FEATURE_DEPRECATED,
    FEATURE_REMOVED,
)


def parse_feature_status(value: str) -> FeatureStatus:
    """Parse a machine-readable feature status; explicit error otherwise."""
    for status in FEATURE_STATUSES:
        if status.value == value:
            return status
    raise CompatError(
        f"unknown feature status {value!r}; expected one of "
        f"{[status.value for status in FEATURE_STATUSES]}"
    )


#: Feature names are lowercase slugs. A dotted or underscored name would blur
#: into a module path — exactly the private-implementation channel this policy
#: exists to close.
_FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


@dataclass(frozen=True)
class FeatureSupport:
    """One host feature and its lifecycle evidence.

    ``since`` is the contract version that introduced the feature; a manifest
    requiring it against an older host is told the minimum. ``removal_target``
    (deprecated only) is the *documented removal target* — a specific future
    contract major, validated to be strictly beyond the host's current major,
    so the support window is a fact in the table rather than a promise in
    prose. ``removed_in`` (removed only) records when it actually went away.
    ``migration`` says where to go; it is required exactly when the feature is
    no longer plainly supported.
    """

    name: str
    status: FeatureStatus
    since: ContractVersion
    removal_target: ContractVersion | None = None
    removed_in: ContractVersion | None = None
    migration: str = ""

    def __post_init__(self) -> None:
        if not _FEATURE_NAME_RE.match(self.name):
            raise CompatError(
                f"feature name must be a lowercase slug (^[a-z][a-z0-9-]{{0,62}}$), "
                f"got {self.name!r}"
            )
        _validate_feature_shape(self)


def _validate_feature_shape(feature: FeatureSupport) -> None:
    """Each lifecycle state carries exactly its own evidence — no more, no less."""
    _ROW_SHAPE_VALIDATORS[feature.status](feature)


def _validate_supported_row(feature: FeatureSupport) -> None:
    if feature.removal_target is not None or feature.removed_in is not None:
        raise CompatError(
            f"feature {feature.name!r} is supported and cannot carry a removal "
            "target or a removal record — only deprecated/removed features do"
        )
    if feature.migration:
        raise CompatError(
            f"feature {feature.name!r} is supported; a migration path is only "
            "meaningful once it is deprecated or removed"
        )


def _validate_deprecated_row(feature: FeatureSupport) -> None:
    if feature.removal_target is None:
        raise CompatError(
            f"deprecated feature {feature.name!r} must declare a removal_target — "
            "a deprecation without a documented removal target is a threat, "
            "not a policy"
        )
    if feature.removed_in is not None:
        raise CompatError(f"deprecated feature {feature.name!r} cannot also carry removed_in")
    if not feature.migration:
        raise CompatError(f"deprecated feature {feature.name!r} must document a migration path")


def _validate_removed_row(feature: FeatureSupport) -> None:
    if feature.removed_in is None:
        raise CompatError(f"removed feature {feature.name!r} must record removed_in")
    if feature.removal_target is not None:
        raise CompatError(
            f"removed feature {feature.name!r} already has removed_in; removal_target is superseded"
        )
    if not feature.migration:
        raise CompatError(f"removed feature {feature.name!r} must document a migration path")


#: Dispatched by status, so each lifecycle state's evidence contract is one
#: small, independently readable function.
_ROW_SHAPE_VALIDATORS: dict[FeatureStatus, Callable[[FeatureSupport], None]] = {
    FEATURE_SUPPORTED: _validate_supported_row,
    FEATURE_DEPRECATED: _validate_deprecated_row,
    FEATURE_REMOVED: _validate_removed_row,
}


def _validate_removal_window(feature: FeatureSupport, host_version: ContractVersion) -> None:
    """Feature rows must carry lifecycle evidence this host's version allows.

    The support-window rule: removing a feature is a breaking change, and
    breaking changes land only at contract-major boundaries — so a documented
    removal target must be a *future* major, which is what makes the deprecation
    window a fact in the table rather than a promise in prose.
    """
    if feature.status is FEATURE_DEPRECATED:
        assert feature.removal_target is not None  # validated by FeatureSupport
        if feature.removal_target.major <= host_version.major:
            raise CompatError(
                f"deprecated feature {feature.name!r} targets removal in "
                f"contract {feature.removal_target}, which is not a future "
                f"major beyond the contract this host implements "
                f"({host_version}); features are removed only at "
                "contract-major boundaries"
            )
    elif feature.status is FEATURE_REMOVED:
        assert feature.removed_in is not None  # validated by FeatureSupport
        if feature.removed_in > host_version:
            raise CompatError(
                f"feature {feature.name!r} records removal in contract "
                f"{feature.removed_in}, which is newer than the contract "
                f"this host implements ({host_version})"
            )


@dataclass(frozen=True)
class HostContractMetadata:
    """The compatibility metadata a host exposes — by contrast, nothing else.

    Deliberately *no application-version field*: compatibility is a function
    of the contract this metadata describes, so two hosts implementing the
    same contract negotiate identically no matter which application release
    carries them (and no matter the patch). The metadata is the host side of
    the negotiation; the extension side is
    :class:`ExtensionCompatMetadata`.
    """

    contract_version: ContractVersion
    supported_majors: tuple[int, ...]
    features: tuple[FeatureSupport, ...]

    def __post_init__(self) -> None:
        if not self.supported_majors:
            raise CompatError("a host must support at least one contract major")
        if tuple(sorted(set(self.supported_majors))) != self.supported_majors:
            raise CompatError(
                f"supported contract majors must be strictly increasing and unique, "
                f"got {self.supported_majors}"
            )
        if self.contract_version.major not in self.supported_majors:
            raise CompatError(
                f"host implements contract {self.contract_version} but does not list "
                f"major {self.contract_version.major} among its supported majors "
                f"{self.supported_majors}"
            )
        seen: set[str] = set()
        for feature in self.features:
            if feature.name in seen:
                raise CompatError(f"duplicate feature {feature.name!r} in host metadata")
            seen.add(feature.name)
            # No invariant ties `since` to this host's contract version: a
            # host may implement a feature before the contract formally
            # reserves it (a backport, a preview). Granting it is still gated
            # on the *contract* version during negotiation — see
            # _check_feature — because an extension may only assume semantics
            # the contract version it targets has defined, not implementation
            # accidents.
            _validate_removal_window(feature, self.contract_version)

    def feature(self, name: str) -> FeatureSupport | None:
        """The host's support row for ``name``, or ``None`` when unimplemented."""
        for feature in self.features:
            if feature.name == name:
                return feature
        return None

    @staticmethod
    def current() -> HostContractMetadata:
        """This host's metadata, from the module policy constants."""
        return HostContractMetadata(
            contract_version=parse_contract_version(CONTRACT_VERSION),
            supported_majors=SUPPORTED_CONTRACT_MAJORS,
            features=HOST_FEATURES,
        )


#: The features this host implements, with their contract lifecycle. Nothing
#: is deprecated or removed today; the machinery above is exercised by tests,
#: so the first real deprecation needs a table row (status, removal target,
#: migration), not new code — the same shape ADR-076 chose for its version
#: table.
HOST_FEATURES: tuple[FeatureSupport, ...] = (
    FeatureSupport(name="background", status=FEATURE_SUPPORTED, since=ContractVersion(1, 0, 0)),
    FeatureSupport(name="interactive", status=FEATURE_SUPPORTED, since=ContractVersion(1, 0, 0)),
    FeatureSupport(name="scheduled", status=FEATURE_SUPPORTED, since=ContractVersion(1, 0, 0)),
    FeatureSupport(name="streaming", status=FEATURE_SUPPORTED, since=ContractVersion(1, 0, 0)),
)


# ---------------------------------------------------------------------------
# extension compatibility metadata — parsed from manifest data, never code
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtensionCompatMetadata:
    """The compatibility slice an extension declares, as pure data.

    This model deliberately has *no entrypoint field*: the fields are exactly
    what compatibility is decided from, and none of them names anything
    importable. A manifest's entrypoint lives in the manifest layer (M9-A1);
    the negotiation never sees it.
    """

    contract: ContractRange
    required_features: tuple[str, ...] = ()
    optional_features: tuple[str, ...] = ()


_ALLOWED_METADATA_KEYS = ("contract", "required_features", "optional_features")


def parse_compat_metadata(mapping: Mapping[str, object]) -> ExtensionCompatMetadata:
    """Parse an extension's compatibility metadata from a plain mapping.

    Strict by design: an unknown key is an error naming the key (a manifest
    field the host silently ignored would show review one contract and enforce
    another), a missing or malformed ``contract`` is an error, and feature
    lists must be slug-named and non-duplicated. A feature name the *host*
    has never heard of is *not* a parse error — a newer SDK may declare
    features an older host does not define, and that is a negotiation
    outcome (incompatible when required, degraded when optional), not a
    crash.
    """
    if not isinstance(mapping, Mapping):
        raise CompatMetadataError(
            f"extension compatibility metadata must be a JSON object, got {type(mapping).__name__}"
        )
    unknown = sorted(set(mapping) - set(_ALLOWED_METADATA_KEYS))
    if unknown:
        raise CompatMetadataError(
            f"unknown compatibility metadata keys {unknown}; allowed keys are "
            f"{list(_ALLOWED_METADATA_KEYS)}"
        )
    contract_raw = mapping.get("contract")
    if not isinstance(contract_raw, str):
        raise CompatMetadataError(
            f"compatibility metadata requires a 'contract' range string, got {contract_raw!r}"
        )
    contract = parse_contract_range(contract_raw)
    required = _parse_feature_list(mapping, "required_features")
    optional = _parse_feature_list(mapping, "optional_features")
    overlap = sorted(set(required) & set(optional))
    if overlap:
        raise CompatMetadataError(
            f"features {overlap} appear in both required_features and "
            "optional_features; a feature is one or the other"
        )
    return ExtensionCompatMetadata(
        contract=contract,
        required_features=required,
        optional_features=optional,
    )


def _parse_feature_list(mapping: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = mapping.get(key, ())
    if not isinstance(raw, (list, tuple)):
        raise CompatMetadataError(
            f"{key} must be a list of feature names, got {type(raw).__name__}"
        )
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not _FEATURE_NAME_RE.match(item):
            raise CompatMetadataError(
                f"{key} entries must be lowercase-slug feature names "
                f"(^[a-z][a-z0-9-]{{0,62}}$), got {item!r}"
            )
        if item in names:
            raise CompatMetadataError(f"duplicate feature {item!r} in {key}")
        names.append(item)
    return tuple(names)


# ---------------------------------------------------------------------------
# negotiation — the pure, metadata-only compatibility decision
# ---------------------------------------------------------------------------


class Verdict(StrEnum):
    """The negotiation outcome, machine-readable.

    ``compatible`` — everything declared is provided. ``degraded`` — the
    extension runs, but declared *optional* features will not be provided and
    the extension is expected to degrade without them. ``incompatible`` — the
    extension must not be activated; ``reasons`` says why, actionably.
    """

    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class Degradation:
    """One optional feature the host will not provide.

    The record *is* the explicit degradation: the feature is absent from
    ``supported_features``, so no runtime path can grant it while claiming the
    extension was taken at face value.
    """

    feature: str
    reason: str


@dataclass(frozen=True)
class DeprecationNotice:
    """One feature the extension uses whose host support is deprecated/removed."""

    feature: str
    status: FeatureStatus
    removal_target: ContractVersion | None
    migration: str


@dataclass(frozen=True)
class CompatibilityReport:
    """The full negotiation outcome — data in both directions.

    ``reasons`` (incompatible only) are actionable: each names the declared
    constraint, the host's version, and the missed policy boundary.
    ``degradations`` are the optional features that will *not* be provided.
    ``deprecations`` carry the machine-readable status and documented removal
    target for every used feature on its way out. ``supported_features`` is
    the effective grant set: the only names a runtime may enable, and never a
    superset of what negotiation proved.
    """

    verdict: Verdict
    reasons: tuple[str, ...] = ()
    degradations: tuple[Degradation, ...] = ()
    deprecations: tuple[DeprecationNotice, ...] = ()
    supported_features: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """JSON-safe projection — the machine-readable report surface."""
        return {
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "degradations": [{"feature": d.feature, "reason": d.reason} for d in self.degradations],
            "deprecations": [
                {
                    "feature": n.feature,
                    "status": n.status.value,
                    "removal_target": None if n.removal_target is None else str(n.removal_target),
                    "migration": n.migration,
                }
                for n in self.deprecations
            ],
            "supported_features": list(self.supported_features),
        }


def negotiate(
    host: HostContractMetadata, extension: ExtensionCompatMetadata
) -> CompatibilityReport:
    """Decide compatibility from metadata alone — before any code import.

    The rules, in order:

    1. The extension's contract range must include the host's contract
       version. This gate **short-circuits**: an extension whose range
       excludes the host is not interpreted any further, because its feature
       declarations were written against a contract this host does not
       implement — evaluating them against this host's vocabulary would be
       fiction. The report is incompatible with one actionable reason that
       distinguishes a contract-major break from a same-major window.
    2. Every *required* feature must be implemented by the host, not removed,
       and introduced no later than the host's contract version; any miss is
       incompatible with a reason naming the feature and the boundary. This
       is the minor-version axis: a manifest may name a feature this host's
       implementation predates.
    3. Every *optional* feature gets the same check; a miss is a recorded
       degradation (the feature is withheld), never an incompatibility and
       never a silent success.
    4. Features used while deprecated (required or optional) still negotiate
       as available, and the report carries their deprecation notices with the
       documented removal target and migration path.

    Feature-gate failures accumulate: one negotiation tells the author
    everything wrong with its feature set, not the first thing.
    """
    if not extension.contract.satisfied_by(host.contract_version):
        # The contract gate short-circuits — see the docstring for why the
        # feature declarations are not interpreted past this point.
        return CompatibilityReport(
            verdict=Verdict.INCOMPATIBLE,
            reasons=(
                extension.contract.explain(
                    host.contract_version, supported_majors=host.supported_majors
                ),
            ),
        )

    req_reasons, req_degraded, req_noticed, req_granted = _walk_features(
        host, extension.required_features, required=True
    )
    # Optional features never produce refusal reasons (an unavailable
    # optional feature degrades instead), so that column is ignored here.
    _opt_reasons, opt_degraded, opt_noticed, opt_granted = _walk_features(
        host, extension.optional_features, required=False
    )

    reasons = tuple(req_reasons)
    degradations = tuple(req_degraded + opt_degraded)
    deprecations = tuple(req_noticed + opt_noticed)
    supported = tuple(req_granted + opt_granted)
    verdict = (
        Verdict.INCOMPATIBLE
        if reasons
        else Verdict.DEGRADED
        if degradations
        else Verdict.COMPATIBLE
    )
    return CompatibilityReport(
        verdict=verdict,
        reasons=reasons,
        degradations=degradations,
        deprecations=deprecations,
        supported_features=supported,
    )


def ensure_compatible(
    host: HostContractMetadata, extension: ExtensionCompatMetadata
) -> CompatibilityReport:
    """Negotiate, raising :class:`IncompatibleContract` on an incompatible verdict.

    The fail-fast form of :func:`negotiate` for hosts that refuse to activate;
    compatible and degraded reports pass through unchanged (a degradation is a
    runtime fact to carry, not an error).
    """
    report = negotiate(host, extension)
    if report.verdict is Verdict.INCOMPATIBLE:
        raise IncompatibleContract("\n".join(f"- {reason}" for reason in report.reasons))
    return report


# ---------------------------------------------------------------------------
# negotiation internals
# ---------------------------------------------------------------------------


class _FeatureOutcome(StrEnum):
    PROVIDED = "provided"
    UNAVAILABLE = "unavailable"
    PROVIDED_WITH_NOTICE = "provided-with-notice"


#: One walk's accumulated outcome, in report-field order.
_FeatureWalk = tuple[list[str], list[Degradation], list[DeprecationNotice], list[str]]


def _walk_features(
    host: HostContractMetadata, names: Sequence[str], *, required: bool
) -> _FeatureWalk:
    """Check ``names`` against host metadata, accumulating in report order.

    Required and optional declarations differ only in what an unavailable
    feature means — a refusal reason for the former, a recorded degradation
    for the latter — so one walker carries both and the flag picks the
    outcome. Deprecated features still negotiate as available, with their
    notice recorded either way.
    """
    reasons: list[str] = []
    degradations: list[Degradation] = []
    deprecations: list[DeprecationNotice] = []
    supported: list[str] = []

    for name in names:
        outcome, reason = _check_feature(host, name)
        if outcome is _FeatureOutcome.PROVIDED:
            supported.append(name)
        elif outcome is _FeatureOutcome.UNAVAILABLE:
            assert reason is not None
            if required:
                reasons.append(_required_failure(name, reason))
            else:
                degradations.append(Degradation(feature=name, reason=reason.message))
        else:
            assert reason is not None
            deprecations.append(
                DeprecationNotice(
                    feature=name,
                    status=FEATURE_DEPRECATED,
                    removal_target=reason.removal_target,
                    migration=reason.migration,
                )
            )
            supported.append(name)
    return reasons, degradations, deprecations, supported


@dataclass(frozen=True)
class _Unavailable:
    """Why the host will not provide one feature (actionable, self-contained)."""

    message: str
    removal_target: ContractVersion | None = None
    migration: str = ""


def _check_feature(
    host: HostContractMetadata, name: str
) -> tuple[_FeatureOutcome, _Unavailable | None]:
    """One feature against host metadata, shared by required/optional paths."""
    feature = host.feature(name)
    if feature is None:
        implemented = ", ".join(f.name for f in host.features) or "none"
        return _FeatureOutcome.UNAVAILABLE, _Unavailable(
            f"this host does not implement feature {name!r} "
            f"(implements: {implemented}); it will not be provided"
        )
    if feature.status is FEATURE_REMOVED:
        assert feature.removed_in is not None
        return _FeatureOutcome.UNAVAILABLE, _Unavailable(
            f"feature {name!r} was removed in contract {feature.removed_in} "
            f"(this host implements {host.contract_version}); migration: "
            f"{feature.migration}",
            removal_target=feature.removed_in,
            migration=feature.migration,
        )
    if feature.since > host.contract_version:
        return _FeatureOutcome.UNAVAILABLE, _Unavailable(
            f"feature {name!r} requires contract >= {feature.since}, but this host "
            f"implements {host.contract_version}; it will not be provided"
        )
    if feature.status is FEATURE_DEPRECATED:
        assert feature.removal_target is not None
        return _FeatureOutcome.PROVIDED_WITH_NOTICE, _Unavailable(
            f"feature {name!r} is deprecated and will be removed in contract "
            f"{feature.removal_target}; migration: {feature.migration}",
            removal_target=feature.removal_target,
            migration=feature.migration,
        )
    return _FeatureOutcome.PROVIDED, None


def _required_failure(name: str, reason: _Unavailable) -> str:
    return f"required feature {name!r} cannot be provided: {reason.message}"
