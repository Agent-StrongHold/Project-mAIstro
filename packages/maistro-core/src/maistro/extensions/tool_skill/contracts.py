"""Canonical third-party tool and Skill contracts (M9-E3, issue #964).

A third-party package declares behavior in its ``extension.json`` manifest and
an entrypoint object the host loads only after the manifest was accepted. This
module is the host side of that contract for the ``tool`` and ``skill``
families: it parses the manifest fail-closed against the published closed
vocabularies, and it computes the **canonical capability/effect
classification** policy acts on.

Classification is host-owned. The manifest is an extension's *claim* about
what it does; the host never takes that claim at face value:

* the effect floor is derived from the *union* of everything the manifest asks
  for — its declared ``effects`` **and** its ``capabilities`` — so a manifest
  cannot claim ``read-only`` while requesting ``network.outbound`` and be
  classified as internal;
* at invocation time the extension may state an effect claim (what this one
  call does). :func:`validate_effect_claim` refuses any claim below the host
  floor, so a higher-risk effect can never relabel itself reversible to evade
  policy; raising a claim above the floor is accepted and immediately adopted
  as the classification this call is authorized under;
* the only way a classification moves downward is a host-side override, which
  is operator configuration, not extension input.

Reversibility uses the ADR-050 three-tier taxonomy
(:class:`maistro.tools.reversibility.ToolReversibility`) so extension tools
and built-in tools share one vocabulary at the Binding/policy seam
(ADR-081226-6b46, ADR-051).

Nothing here imports or executes extension code: parsing is data-only, and
``entrypoint.module`` is validated lexically (never imported) exactly like the
M9-A3 gate treats it.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from maistro.tools.reversibility import ToolReversibility

#: Publisher/name segments of an extension id: slug-cased, per the manifest
#: reference (`publisher.name`, both segments ``[a-z0-9-]``).
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Semver as manifests must spell it (no ranges here — the ``contract`` field
#: is the range; the package ``version`` is a concrete release).
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

#: Named secret references, per the manifest reference:
#: ``[A-Z][A-Z0-9_]*`` env-style names, never values.
_SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: A manifest-contract range pins exactly one major, per the versioning rule:
#: ``>=X.Y.Z,<X+1.0.0`` (whitespace tolerated). Anything else claims
#: compatibility with a schema that does not exist yet.
_CONTRACT_RANGE = re.compile(r"^>=\s*(\d+)\.\d+\.\d+\s*,\s*<\s*(\d+)\.0\.0$")

#: Dotted module path, lexical only — validation never resolves it.
_MODULE_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_EFFECT_FLOOR_FOR_REVERSIBILITY: dict[str, ToolReversibility] = {
    # read-only: no external side effect — safe to re-issue freely.
    "read-only": ToolReversibility.INTERNAL,
    # mutating: changes host state; reversible in the ADR-050 sense that a
    # compensating host write exists, so policy may retry/rollback.
    "mutating": ToolReversibility.REVERSIBLE,
    # external-side-effect: reaches outside the deployment. Classified
    # REVERSIBLE as a floor (an idempotent GET is a legitimate external read),
    # not because callers are trusted — policy narrows from here, and the
    # runtime claim check can only raise it.
    "external-side-effect": ToolReversibility.REVERSIBLE,
    # irreversible: cannot be undone. Approval gate per ADR-051.
    "irreversible": ToolReversibility.IRREVERSIBLE,
}


class ContractError(RuntimeError):
    """Base class for tool/Skill contract failures."""


class ManifestContractError(ContractError):
    """A manifest (or entrypoint object) violates the published contract.

    Every field error names its manifest path so an author can fix the
    document without reading host code. Validation is fail-closed: an unknown
    capability, effect, or scope is an error, never an ignored line.
    """


class EffectDowngradeRefused(ContractError):
    """An effect claim classifies the call as lower-risk than the host floor.

    This is the runtime half of "an extension cannot label a higher-risk
    effect as reversible to evade policy without host validation": the claim
    is discarded and the call stays classified at the floor.
    """


class EffectClass(StrEnum):
    """The published effect vocabulary an extension manifest declares from."""

    READ_ONLY = "read-only"
    MUTATING = "mutating"
    EXTERNAL_SIDE_EFFECT = "external-side-effect"
    IRREVERSIBLE = "irreversible"


#: Risk order over the effect vocabulary. "Higher" means "harder to undo".
_EFFECT_RISK: dict[EffectClass, int] = {
    EffectClass.READ_ONLY: 0,
    EffectClass.MUTATING: 1,
    EffectClass.EXTERNAL_SIDE_EFFECT: 2,
    EffectClass.IRREVERSIBLE: 3,
}


class ExtensionFamily:
    """The closed extension families (manifest reference, M9-A3).

    Plain string constants rather than an enum: a manifest's ``family`` is
    one closed vocabulary token, and the host only branches on the two
    families this contract module owns (``tool``, ``skill``) while refusing
    nothing else here — the other families belong to their own lifecycle
    contracts.
    """

    TOOL = "tool"
    SKILL = "skill"
    MCP_GATEWAY = "mcp-gateway"
    CAPABILITY_PROVIDER = "capability-provider"
    RENDERER_PLUGIN = "renderer-plugin"


#: The closed family vocabulary, for validation.
FAMILY_VOCABULARY: frozenset[str] = frozenset(
    {
        ExtensionFamily.TOOL,
        ExtensionFamily.SKILL,
        ExtensionFamily.MCP_GATEWAY,
        ExtensionFamily.CAPABILITY_PROVIDER,
        ExtensionFamily.RENDERER_PLUGIN,
    }
)


#: The closed capability authority vocabulary. Names an extension may request;
#: anything else fails validation instead of inventing authority by
#: misspelling. Anchors are tabled in ``docs/extensions/manifest-reference.md``.
CAPABILITY_VOCABULARY: frozenset[str] = frozenset(
    {
        "workspace.read",
        "workspace.write",
        "agent.read",
        "run.read",
        "memory.read",
        "memory.write",
        "tool.invoke",
        "network.outbound",
        "filesystem.read",
        "filesystem.write",
        "secrets.read",
    }
)

#: The closed data-scope vocabulary.
DATA_SCOPE_VOCABULARY: frozenset[str] = frozenset(
    {"workspace", "agent", "run", "memory", "messages", "artifacts"}
)

#: Capabilities that raise the effect floor regardless of the declared
#: ``effects`` list. Writing anything is at least ``mutating``; reaching
#: outside the deployment — directly via the network, or by sending named
#: secret material along — is at least ``external-side-effect``.
_CAPABILITY_EFFECT_FLOOR: dict[str, EffectClass] = {
    "workspace.write": EffectClass.MUTATING,
    "memory.write": EffectClass.MUTATING,
    "filesystem.write": EffectClass.MUTATING,
    # An orchestrating tool composes other tools' authority (the one
    # capability that can cause others' effects), so its own floor is at
    # least mutating; each composed call is classified on its own Binding.
    "tool.invoke": EffectClass.MUTATING,
    "network.outbound": EffectClass.EXTERNAL_SIDE_EFFECT,
    "secrets.read": EffectClass.EXTERNAL_SIDE_EFFECT,
}


def effect_risk(effect: EffectClass) -> int:
    """Risk rank of one effect class; higher means harder to undo."""
    return _EFFECT_RISK[effect]


def highest_risk(effects: Iterable[EffectClass]) -> EffectClass | None:
    """The highest-risk effect in ``effects``, or ``None`` when empty."""
    ordered = sorted(effects, key=effect_risk, reverse=True)
    return ordered[0] if ordered else None


def max_effect(left: EffectClass, right: EffectClass) -> EffectClass:
    """The higher-risk of two effect classes."""
    return left if effect_risk(left) >= effect_risk(right) else right


def to_reversibility(effect: EffectClass) -> ToolReversibility:
    """Map an effect class onto the canonical ADR-050 reversibility tier."""
    return _EFFECT_FLOOR_FOR_REVERSIBILITY[effect.value]


@dataclass(frozen=True)
class EntrypointSpec:
    """A manifest-declared entrypoint: dotted module and attribute name.

    Lexical only. A host imports the module only after the manifest was
    accepted — validation here never does.
    """

    module: str
    object: str


@dataclass(frozen=True)
class ExtensionContract:
    """The host-side contract for one installed tool or Skill package.

    Built by :meth:`from_manifest` from the parsed ``extension.json``. Every
    vocabulary is validated closed, and the *effective* effect floor is a
    derived property: the host's classification, computed from both the
    declared effects and the requested capabilities, and never taken from the
    extension's self-description alone.
    """

    extension_id: str
    publisher: str
    version: str
    title: str
    description: str
    contract_range: str
    family: str
    capabilities: tuple[str, ...]
    effects: tuple[EffectClass, ...]
    data_scopes: tuple[str, ...]
    entrypoint: EntrypointSpec
    network_allow: tuple[str, ...]
    network_ports: tuple[int, ...]
    secret_refs: tuple[str, ...]
    manifest_sha256: str

    @classmethod
    def from_manifest(
        cls,
        manifest: Mapping[str, Any],
        *,
        digest: str = "",
    ) -> ExtensionContract:
        """Parse one ``extension.json`` mapping fail-closed.

        ``digest`` is the manifest's sha256 as the install record snapshotted
        it; the contract carries it so a registered tool stays attributable to
        the exact bytes it was installed from.
        """
        publisher = _require_slug(manifest, "publisher")
        extension_id = _require_str(manifest, "id")
        _require_id_shape(extension_id, publisher)
        version = _require_semver(manifest, "version")
        _require_str(manifest, "title")
        _require_str(manifest, "description")
        _validate_contract_range(_require_str(manifest, "contract"))
        family = _require_vocab(manifest, "family", FAMILY_VOCABULARY)
        capabilities = _require_string_list(manifest, "capabilities")
        _require_closed(capabilities, CAPABILITY_VOCABULARY, "capabilities")
        effects_raw = _require_string_list(manifest, "effects")
        known_effects = {effect.value for effect in EffectClass}
        unknown_effects = sorted(set(effects_raw) - known_effects)
        if unknown_effects:
            raise ManifestContractError(
                f"manifest: unknown effects: {', '.join(unknown_effects)} "
                f"(closed vocabulary: {sorted(known_effects)})"
            )
        effects = tuple(EffectClass(name) for name in effects_raw)
        data_raw = manifest.get("data")
        if not isinstance(data_raw, Mapping):
            raise ManifestContractError("data: required object with a 'scopes' list")
        scopes = _require_string_list(data_raw, "scopes", path="data")
        _require_closed(scopes, DATA_SCOPE_VOCABULARY, "data.scopes")
        entrypoint_raw = manifest.get("entrypoint")
        if not isinstance(entrypoint_raw, Mapping):
            raise ManifestContractError("entrypoint: required object")
        module = _require_pattern(entrypoint_raw, "module", _MODULE_PATH, path="entrypoint")
        object_name = _require_pattern(entrypoint_raw, "object", _IDENTIFIER, path="entrypoint")
        network_allow, network_ports = _parse_network(manifest)
        secret_refs = _parse_secrets(manifest)
        return cls(
            extension_id=extension_id,
            publisher=publisher,
            version=version,
            title=str(manifest["title"]),
            description=str(manifest["description"]),
            contract_range=str(manifest["contract"]),
            family=family,
            capabilities=tuple(capabilities),
            effects=effects,
            data_scopes=tuple(scopes),
            entrypoint=EntrypointSpec(module=module, object=object_name),
            network_allow=network_allow,
            network_ports=network_ports,
            secret_refs=secret_refs,
            manifest_sha256=digest,
        )

    @property
    def effect_floor(self) -> EffectClass:
        """The host-computed effect floor for this contract.

        The maximum of what the manifest *declares* and what its requested
        *capabilities* imply. An honest empty ``effects`` list does not lower
        this below what the capabilities demand, and a ``read-only`` claim
        next to ``network.outbound`` still classifies as
        ``external-side-effect``. A package that genuinely does nothing and
        asks for nothing classifies ``read-only``.
        """
        declared = highest_risk(self.effects)
        implied = highest_risk(
            EffectClass(floor)
            for floor in map(_CAPABILITY_EFFECT_FLOOR.get, self.capabilities)
            if floor
        )
        if declared is None and implied is None:
            # Nothing declared and nothing implied: an extension that
            # promises nothing and touches nothing. A tool family package
            # with no declaration is still an executable call, so it takes
            # the ADR-050 safe default (undeclared -> irreversible) unless it
            # says otherwise; the skill family is not executed directly and
            # stays read-only at the floor.
            return (
                EffectClass.READ_ONLY
                if self.family == ExtensionFamily.SKILL
                else EffectClass.IRREVERSIBLE
            )
        floor = declared or EffectClass.READ_ONLY
        if implied is not None:
            floor = max_effect(floor, implied)
        return floor

    @property
    def reversibility(self) -> ToolReversibility:
        """The canonical ADR-050 tier policy acts on for this contract."""
        return to_reversibility(self.effect_floor)

    def requires(self, capability: str) -> bool:
        """Whether the manifest requests ``capability``."""
        return capability in self.capabilities


def validate_effect_claim(contract: ExtensionContract, claim: EffectClass) -> EffectClass:
    """Host-validate a runtime effect claim against the contract floor.

    Returns the *effective* classification the call is authorized under: the
    higher of the floor and the claim. A claim below the floor raises
    :class:`EffectDowngradeRefused` — the extension does not get to relabel
    this call reversible; the host's classification wins. A claim above the
    floor is accepted and becomes the classification, so an extension that
    knows one call is destructive can say so and take the stricter gate.
    """
    floor = contract.effect_floor
    if effect_risk(claim) < effect_risk(floor):
        raise EffectDowngradeRefused(
            f"{contract.extension_id}: effect claim {claim.value!r} is below the "
            f"host floor {floor.value!r}; the host classification stands"
        )
    return claim


@dataclass(frozen=True)
class ToolEntrypoint:
    """The parsed entrypoint *object* of a ``tool``-family extension.

    Shape (mirrors the reference extension's ``PLUGIN``): ``kind`` ==
    ``"tool"``, ``name`` equal to the manifest id, ``version`` equal to the
    manifest version, ``capabilities`` a subset of the manifest's requested
    authorities, and ``handler`` naming an attribute on the entrypoint module.
    The entrypoint object is data the host validates before the module is
    imported — code runs only after data about the code was accepted.
    """

    kind: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    handler: str

    @classmethod
    def from_object(cls, obj: Mapping[str, Any], contract: ExtensionContract) -> ToolEntrypoint:
        """Validate an entrypoint object against its accepted manifest."""
        if not isinstance(obj, Mapping):
            raise ManifestContractError("entrypoint object must be a mapping")
        kind = _require_literal(obj, "kind", "tool", path="entrypoint object")
        del kind
        name = _require_str(obj, "name", path="entrypoint object")
        if name != contract.extension_id:
            raise ManifestContractError(
                f"entrypoint object: name {name!r} does not match the manifest id "
                f"{contract.extension_id!r}"
            )
        version = _require_str(obj, "version", path="entrypoint object")
        if version != contract.version:
            raise ManifestContractError(
                f"entrypoint object: version {version!r} does not match the manifest "
                f"version {contract.version!r}"
            )
        capabilities = _require_string_list(obj, "capabilities", path="entrypoint object")
        undeclared = sorted(set(capabilities) - set(contract.capabilities))
        if undeclared:
            raise ManifestContractError(
                "entrypoint object: capabilities beyond the manifest: " + ", ".join(undeclared)
            )
        handler = _require_pattern(obj, "handler", _IDENTIFIER, path="entrypoint object")
        return cls(
            kind="tool",
            name=name,
            version=version,
            capabilities=tuple(capabilities),
            handler=handler,
        )


@dataclass(frozen=True)
class SkillEntrypoint:
    """The parsed entrypoint *object* of a ``skill``-family extension.

    A Skill composes canonical tools and Graphs rather than owning effects of
    its own, so its entrypoint object declares ``tools`` — the canonical tool
    names it invokes. Composition authority is *not* granted here: the host
    checks every composed name against the Workspace/Agent allowlist when the
    skill is registered for use (:mod:`.registration`).
    """

    kind: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    handler: str

    @classmethod
    def from_object(cls, obj: Mapping[str, Any], contract: ExtensionContract) -> SkillEntrypoint:
        """Validate an entrypoint object against its accepted manifest."""
        if not isinstance(obj, Mapping):
            raise ManifestContractError("entrypoint object must be a mapping")
        _require_literal(obj, "kind", "skill", path="entrypoint object")
        name = _require_str(obj, "name", path="entrypoint object")
        if name != contract.extension_id:
            raise ManifestContractError(
                f"entrypoint object: name {name!r} does not match the manifest id "
                f"{contract.extension_id!r}"
            )
        version = _require_str(obj, "version", path="entrypoint object")
        if version != contract.version:
            raise ManifestContractError(
                f"entrypoint object: version {version!r} does not match the manifest "
                f"version {contract.version!r}"
            )
        capabilities = _require_string_list(obj, "capabilities", path="entrypoint object")
        undeclared = sorted(set(capabilities) - set(contract.capabilities))
        if undeclared:
            raise ManifestContractError(
                "entrypoint object: capabilities beyond the manifest: " + ", ".join(undeclared)
            )
        tools = _require_string_list(obj, "tools", path="entrypoint object")
        if any(not tool.strip() for tool in tools):
            raise ManifestContractError("entrypoint object: tools cannot contain empty names")
        handler = _require_pattern(obj, "handler", _IDENTIFIER, path="entrypoint object")
        return cls(
            kind="skill",
            name=name,
            version=version,
            capabilities=tuple(capabilities),
            tools=tuple(tools),
            handler=handler,
        )


@dataclass(frozen=True)
class SkillContract:
    """A ``skill``-family contract: the manifest plus its declared composition."""

    contract: ExtensionContract
    entrypoint: SkillEntrypoint

    @classmethod
    def from_manifest(
        cls,
        manifest: Mapping[str, Any],
        entrypoint_object: Mapping[str, Any],
        *,
        digest: str = "",
    ) -> SkillContract:
        """Parse one skill-family manifest plus its entrypoint object."""
        contract = ExtensionContract.from_manifest(manifest, digest=digest)
        if contract.family != ExtensionFamily.SKILL:
            raise ManifestContractError(
                f"family must be 'skill' for a Skill contract, got {contract.family!r}"
            )
        return cls(
            contract=contract,
            entrypoint=SkillEntrypoint.from_object(entrypoint_object, contract),
        )

    def __getattr__(self, name: str) -> Any:
        """Delegate contract fields so callers read ``skill.version`` naturally."""
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return getattr(self.__dict__["contract"], name)
        except KeyError:
            raise AttributeError(name) from None


def _require_str(manifest: Mapping[str, Any], key: str, *, path: str = "manifest") -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestContractError(f"{path}: {key} must be a non-empty string")
    return value


def _require_slug(manifest: Mapping[str, Any], key: str) -> str:
    value = _require_str(manifest, key)
    if not _SLUG.match(value):
        raise ManifestContractError(f"manifest: {key} {value!r} must be slug-cased ([a-z0-9-])")
    return value


def _require_id_shape(extension_id: str, publisher: str) -> None:
    if "." not in extension_id:
        raise ManifestContractError(f"manifest: id {extension_id!r} must be 'publisher.name'")
    prefix, _, name = extension_id.partition(".")
    if prefix != publisher or not _SLUG.match(name):
        raise ManifestContractError(
            f"manifest: id {extension_id!r} must be the publisher slug "
            f"{publisher!r} followed by a slug-cased name"
        )


def _require_semver(manifest: Mapping[str, Any], key: str) -> str:
    value = _require_str(manifest, key)
    if not _SEMVER.match(value):
        raise ManifestContractError(f"manifest: {key} {value!r} must be MAJOR.MINOR.PATCH")
    return value


def _validate_contract_range(value: str) -> None:
    match = _CONTRACT_RANGE.match(value)
    if match is None:
        raise ManifestContractError(
            f"manifest: contract {value!r} must pin exactly one major, e.g. '>=1.0.0,<2.0.0'"
        )
    lower, upper = int(match.group(1)), int(match.group(2))
    if upper != lower + 1:
        raise ManifestContractError(f"manifest: contract {value!r} must span exactly one major")


def _require_string_list(
    manifest: Mapping[str, Any], key: str, *, path: str = "manifest"
) -> list[str]:
    value = manifest.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManifestContractError(f"{path}: {key} must be a list of strings")
    return value


def _require_vocab(manifest: Mapping[str, Any], key: str, names: Collection[str]) -> str:
    value = _require_str(manifest, key)
    if value not in names:
        raise ManifestContractError(f"manifest: {key} {value!r} is not one of {sorted(names)}")
    return value


def _require_literal(obj: Mapping[str, Any], key: str, expected: str, *, path: str) -> str:
    value = obj.get(key)
    if value != expected:
        raise ManifestContractError(f"{path}: {key} must be {expected!r}, got {value!r}")
    return str(value)


def _require_pattern(
    obj: Mapping[str, Any], key: str, pattern: re.Pattern[str], *, path: str
) -> str:
    value = _require_str(obj, key, path=path)
    if not pattern.match(value):
        raise ManifestContractError(f"{path}: {key} {value!r} is not a valid value")
    return value


def _require_closed(values: Iterable[str], closed: frozenset[str], what: str) -> None:
    unknown = sorted(set(values) - closed)
    if unknown:
        raise ManifestContractError(
            f"manifest: unknown {what}: {', '.join(unknown)} (closed vocabulary: {sorted(closed)})"
        )


def _parse_network(
    manifest: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    network = manifest.get("network")
    if network is None:
        return (), ()
    if not isinstance(network, Mapping):
        raise ManifestContractError("network: must be an object")
    return tuple(_parse_allow_hosts(network)), tuple(_parse_allowed_ports(network))


def _parse_allow_hosts(network: Mapping[str, Any]) -> list[str]:
    allow = _require_string_list(network, "allow", path="network")
    if any(not host.strip() for host in allow):
        raise ManifestContractError("network.allow: hosts cannot be empty")
    return allow


def _parse_allowed_ports(network: Mapping[str, Any]) -> list[int]:
    ports_raw = network.get("allowed_ports", [])
    if not isinstance(ports_raw, list) or any(not _is_tcp_port(port) for port in ports_raw):
        raise ManifestContractError("network.allowed_ports: must be a list of TCP ports (1-65535)")
    return [int(port) for port in ports_raw]


def _is_tcp_port(port: Any) -> bool:
    return isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536


def _parse_secrets(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    secrets = manifest.get("secrets")
    if secrets is None:
        return ()
    if not isinstance(secrets, list):
        raise ManifestContractError("secrets: must be a list of {name} references")
    names: list[str] = []
    for entry in secrets:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("name"), str):
            raise ManifestContractError("secrets: each entry must be an object with a 'name'")
        name = entry["name"]
        if not _SECRET_NAME.match(name):
            raise ManifestContractError(
                f"secrets: {name!r} must be an env-style name ([A-Z][A-Z0-9_]*); "
                "manifests name secret references, never values"
            )
        names.append(name)
    return tuple(names)
