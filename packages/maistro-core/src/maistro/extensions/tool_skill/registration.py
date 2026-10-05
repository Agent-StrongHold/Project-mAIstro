"""Host registration for third-party tool and Skill packages (M9-E3, #964).

Registration is data-driven: a host feeds an accepted manifest plus its
entrypoint object into :class:`ExtensionToolCatalog` /
:class:`register_extension_skill` and the package is usable — no core edits,
no per-tool code in this repository. That is the out-of-tree acceptance
criterion: adding a tool or Skill is adding a package, not editing the host.

Two gates apply at registration, both fail-closed:

* **Allowlists.** Tool access is constrained by Agent/Workspace allowlists
  (:class:`ToolAccessPolicy`) — a tool outside the allowlist is registered as
  a fact but is never exposed or bound — and Skill composition over canonical
  tools is refused unless every composed tool is allowlisted.
* **Manifest permissions.** A registered tool's exposure can only ever name
  authorities its own manifest requested; the entrypoint object was already
  validated against the manifest (contracts), and the Binding this module
  builds carries the manifest's identity, classification and permissions
  forward to the Invocation seam, where policy sees them.

The Binding this module builds is a normal canonical Binding
(ADR-081226-6b46): capability ``extension.tool:<id>``, config carrying the
host classification and manifest permissions, resolvable only in the
Workspace scope it was granted in, and revocable like any other Binding.
Skills are projected into the existing :class:`~maistro.skills.registry`
surface with a host-owned trust tier — the product registry's own rule that
marketplace tiers cannot overwrite ``t0``/``t1`` stays in force.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.extensions.tool_skill.contracts import (
    ContractError,
    ExtensionContract,
    ExtensionFamily,
    SkillContract,
    SkillEntrypoint,
    ToolEntrypoint,
)
from maistro.types.skill import SkillDefinition

#: Canonical capability namespace for registered third-party tools. Policy
#: evaluators, allowlists and audit readers key on this prefix.
TOOL_CAPABILITY_PREFIX = "extension.tool"


class RegistrationError(ContractError):
    """Base class for registration failures."""


class ToolNotAllowlisted(RegistrationError):
    """A tool (or a Skill's composed tool) is outside the access allowlist."""


class TrustTierError(RegistrationError):
    """A Skill registration names a trust tier the host does not define."""


@dataclass(frozen=True)
class ToolAccessPolicy:
    """Agent/Workspace tool allowlists (fail closed).

    A third-party tool is accessible in a Workspace only if its extension id
    is in that Workspace's allowlist, and visible to an Agent only if the
    Agent's allowlist (when one is set) admits it too. An absent allowlist
    admits nothing: the default for a new Workspace is zero third-party
    tools, not all of them.
    """

    workspace_allowed: frozenset[str] = frozenset()
    agent_allowed: frozenset[str] | None = None

    def allows(self, tool_id: str) -> bool:
        """Whether this policy admits ``tool_id`` right now."""
        if tool_id not in self.workspace_allowed:
            return False
        return self.agent_allowed is None or tool_id in self.agent_allowed

    def denied_tools(self, tool_ids: tuple[str, ...]) -> tuple[str, ...]:
        """The subset of ``tool_ids`` this policy does not admit."""
        return tuple(tool for tool in tool_ids if not self.allows(tool))


@dataclass(frozen=True)
class RegisteredExtensionTool:
    """One registered third-party tool and everything policy needs about it."""

    contract: ExtensionContract
    entrypoint: ToolEntrypoint
    handler: Any  # the callable the entrypoint names; loaded by the host

    @property
    def tool_id(self) -> str:
        """Canonical tool id — the extension id."""
        return self.contract.extension_id

    @property
    def capability(self) -> str:
        """The canonical capability this tool's Bindings carry."""
        return f"{TOOL_CAPABILITY_PREFIX}:{self.tool_id}"

    @property
    def reversibility(self) -> str:
        """The host classification (ADR-050 tier) as a plain value."""
        return self.contract.reversibility.value

    def describe(self) -> dict[str, Any]:
        """The model-facing exposure descriptor for this tool.

        Deliberately exposes what review and policy reasoned about at
        registration: identity, schema-ish description, classification, and
        the manifest permissions. Nothing here is runtime-discoverable beyond
        what the manifest already declared.
        """
        return {
            "tool_id": self.tool_id,
            "name": self.tool_id,
            "description": self.contract.description,
            "version": self.contract.version,
            "contract": self.contract.contract_range,
            "capability": self.capability,
            "reversibility": self.reversibility,
            "capabilities": list(self.contract.capabilities),
            "effects": [effect.value for effect in self.contract.effects],
            "data_scopes": list(self.contract.data_scopes),
            "network_allow": list(self.contract.network_allow),
            "network_ports": list(self.contract.network_ports),
            "secret_refs": list(self.contract.secret_refs),
            "manifest_sha256": self.contract.manifest_sha256,
        }


class ExtensionToolCatalog:
    """The host-side catalog of registered third-party tools.

    Registration order is deterministic (sorted by tool id) so exposure
    listings are stable across processes. Adding a tool never touches core
    code: a host registers a new package by calling :meth:`register` with its
    accepted manifest and entrypoint object.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredExtensionTool] = {}

    def register(
        self,
        contract: ExtensionContract,
        entrypoint_object: Mapping[str, Any],
        *,
        handler: Any,
    ) -> RegisteredExtensionTool:
        """Register one tool-family package.

        The same identity re-registers idempotently; a different package
        under an id that is already registered is refused — a registration
        conflict is an install-lifecycle problem (#954 owns upgrades), never
        a silent overwrite.
        """
        if contract.family != ExtensionFamily.TOOL:
            raise RegistrationError(
                f"family must be 'tool' for a tool registration, got {contract.family!r}"
            )
        entrypoint = ToolEntrypoint.from_object(entrypoint_object, contract)
        if not callable(handler):
            raise RegistrationError(
                f"{contract.extension_id}: entrypoint handler "
                f"{entrypoint.handler!r} is not callable"
            )
        existing = self._tools.get(contract.extension_id)
        if existing is not None:
            if (
                existing.contract.version == contract.version
                and existing.contract.manifest_sha256 == contract.manifest_sha256
                and existing.entrypoint == entrypoint
                and existing.handler is handler
            ):
                return existing
            raise RegistrationError(
                f"{contract.extension_id}: already registered as "
                f"{existing.contract.version!r}; upgrades go through the "
                "install lifecycle, not a registration overwrite"
            )
        registered = RegisteredExtensionTool(
            contract=contract, entrypoint=entrypoint, handler=handler
        )
        self._tools[registered.tool_id] = registered
        return registered

    def get(self, tool_id: str) -> RegisteredExtensionTool | None:
        """The registered tool with ``tool_id``, or ``None``."""
        return self._tools.get(tool_id)

    def registered(self) -> tuple[RegisteredExtensionTool, ...]:
        """All registered tools, sorted by id."""
        return tuple(self._tools[tool_id] for tool_id in sorted(self._tools))

    def exposed_tools(
        self, policy: ToolAccessPolicy, *, workspace_id: str = ""
    ) -> tuple[dict[str, Any], ...]:
        """Model-facing exposures this policy admits, sorted and stable.

        This is the seam Agent/Workspace allowlists constrain: a tool outside
        the policy is absent — not present-but-denied — so the model never
        sees a name it could not lawfully call.
        """
        del workspace_id  # scope is enforced again at Binding resolution
        return tuple(tool.describe() for tool in self.registered() if policy.allows(tool.tool_id))

    def tool_binding(
        self,
        tool: RegisteredExtensionTool,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str = "",
        policy_refs: tuple[str, ...] = (),
    ) -> Binding:
        """Build the canonical Binding one authorized use of ``tool`` runs under.

        The Binding carries the host classification in ``config["effect"]``
        and the manifest permissions in ``config["permissions"]``, so every
        downstream policy evaluator reasons from host-computed facts rather
        than from anything the extension said at call time.
        """
        return Binding(
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=tool.capability,
            config={
                "extension": tool.tool_id,
                "version": tool.contract.version,
                "manifest_sha256": tool.contract.manifest_sha256,
                "effect": tool.reversibility,
                "permissions": {
                    "capabilities": list(tool.contract.capabilities),
                    "network_allow": list(tool.contract.network_allow),
                    "network_ports": list(tool.contract.network_ports),
                    "secret_refs": list(tool.contract.secret_refs),
                },
            },
            policy_refs=policy_refs,
        )


def composition_denials(skill: SkillContract, policy: ToolAccessPolicy) -> tuple[str, ...]:
    """Composed tools the allowlist does not admit.

    A Skill composes canonical tools; the authority it exercises is the union
    of its own manifest permissions and the composed tools' own Bindings, so
    composition is constrained by the same Agent/Workspace allowlists as
    direct tool access (AC: tool access is constrained by allowlists).
    """
    return policy.denied_tools(skill.entrypoint.tools)


def register_extension_skill(
    skill: SkillContract,
    entrypoint_object: Mapping[str, Any],
    *,
    policy: ToolAccessPolicy,
    trust_tier: str,
    skill_registry: Any = None,
    parameters: Mapping[str, Any] | None = None,
) -> SkillDefinition:
    """Register one skill-family package into the host Skill surface.

    ``trust_tier`` is the *host's* publisher-trust decision — never read from
    the package. The product skill registry's overwrite rules still apply
    (a higher-tier skill cannot be replaced by a lower-tier install).

    Composition over canonical tools is validated here against the allowlist:
    a Skill whose composed tools are not admitted fails registration with the
    denied names listed, rather than failing later per-call in front of a
    model. Returns the projected :class:`SkillDefinition` the registry stored.
    """
    # The entrypoint object is re-validated fail-closed against the accepted
    # contract: a caller handing a different object than the manifest produced
    # is a registration error, not a silent substitution.
    parsed = SkillEntrypoint.from_object(entrypoint_object, skill.contract)
    if parsed != skill.entrypoint:
        raise RegistrationError(
            f"{skill.contract.extension_id}: entrypoint object does not match the "
            "contract the manifest produced"
        )
    denied = composition_denials(skill, policy)
    if denied:
        raise ToolNotAllowlisted(
            f"{skill.contract.extension_id}: composition not allowed; tools outside "
            f"the access allowlist: {', '.join(denied)}"
        )
    definition = _build_skill_definition(skill, trust_tier=trust_tier, parameters=parameters or {})
    if skill_registry is not None:
        skill_registry.register(definition)
    return definition


def load_entrypoint_handler(
    contract: ExtensionContract, entrypoint_object: Mapping[str, Any]
) -> Any:
    """Import a *validated* entrypoint and return its handler callable.

    This is the host's code-import boundary: the module named by an accepted
    manifest is imported here and only here, after the document was validated
    and its identity resolved — data about the code before the code. The
    handler is resolved from the module namespace exactly as the reference
    extension's ``HANDLERS`` contract describes.
    """
    entrypoint = ToolEntrypoint.from_object(entrypoint_object, contract)
    module = import_module(contract.entrypoint.module)
    handler = getattr(module, entrypoint.handler, None)
    if not callable(handler):
        raise RegistrationError(
            f"{contract.extension_id}: entrypoint handler "
            f"{entrypoint.handler!r} is not callable on "
            f"{contract.entrypoint.module}"
        )
    return handler


def _build_skill_definition(
    skill: SkillContract, *, trust_tier: str, parameters: Mapping[str, Any]
) -> SkillDefinition:
    """Project a Skill contract onto the product SkillDefinition surface."""
    if trust_tier not in {"t0", "t1", "t2", "t3"}:
        raise TrustTierError(f"{skill.contract.extension_id}: unknown trust tier {trust_tier!r}")
    return SkillDefinition(
        name=skill.contract.extension_id,
        description=skill.contract.description,
        groups=("extension", skill.contract.publisher),
        parameters=dict(parameters)
        or {"type": "object", "properties": {}, "additionalProperties": True},
        endpoint="",
        auth_key_env="",
        system_prompt=skill.contract.description,
        source=f"extension:{skill.contract.version}:{skill.contract.manifest_sha256[:12]}",
        trust_tier=trust_tier,
    )
