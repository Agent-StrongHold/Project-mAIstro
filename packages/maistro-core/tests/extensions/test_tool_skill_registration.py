"""Registration of third-party tool and Skill packages (M9-E3, #964).

Pins the out-of-tree and allowlist acceptance criteria:

* a tool registers from manifest + entrypoint data alone — no core edits,
  and re-registration cannot silently redefine an identity;
* exposures and Bindings are constrained by Agent/Workspace allowlists
  (fail closed: an absent allowlist admits nothing) and can only name the
  manifest's own permissions;
* Skill composition over canonical tools is validated against the same
  allowlists at registration, with the host-owned trust tier projected into
  the product Skill registry — whose tier overwrite rules stay in force.
"""

from __future__ import annotations

import pytest

from maistro.extensions.tool_skill import (
    ExtensionContract,
    ExtensionToolCatalog,
    ManifestContractError,
    RegistrationError,
    SkillContract,
    ToolAccessPolicy,
    ToolNotAllowlisted,
    TrustTierError,
    load_entrypoint_handler,
    register_extension_skill,
    tool_capability,
)
from maistro.skills.registry import InMemorySkillRegistry
from maistro.tools.reversibility import ToolReversibility


def tool_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "id": "acme.greeter",
        "publisher": "acme",
        "version": "1.2.3",
        "title": "Greeter",
        "description": "Greets, touching nothing.",
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": [],
        "effects": ["read-only"],
        "data": {"scopes": []},
        "entrypoint": {"module": "acme_greeter.plugin", "object": "PLUGIN"},
    }
    manifest.update(overrides)
    return manifest


def greeter_entrypoint() -> dict[str, object]:
    return {
        "kind": "tool",
        "name": "acme.greeter",
        "version": "1.2.3",
        "capabilities": [],
        "handler": "greet",
    }


async def greet(target: str = "world") -> str:
    return f"Hello, {target}!"


def test_register_tool_from_manifest_data_alone() -> None:
    """AC1: registration is a data operation; the host grew by zero lines."""
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest(), digest="cafe")
    registered = catalog.register(contract, greeter_entrypoint(), handler=greet)

    assert registered.tool_id == "acme.greeter"
    assert registered.capability == "extension.tool:acme.greeter"
    assert tool_capability("acme.greeter") == registered.capability
    assert registered.reversibility == ToolReversibility.INTERNAL.value
    assert catalog.get("acme.greeter") is registered


def test_registration_is_idempotent_for_identical_identity() -> None:
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest(), digest="cafe")
    first = catalog.register(contract, greeter_entrypoint(), handler=greet)
    second = catalog.register(contract, greeter_entrypoint(), handler=greet)
    assert first is second


def test_redefinition_under_one_identity_is_refused() -> None:
    """Upgrades go through the install lifecycle (#954), not an overwrite."""
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest(), digest="cafe")
    catalog.register(contract, greeter_entrypoint(), handler=greet)

    async def different(target: str = "world") -> str:
        return "goodbye"

    with pytest.raises(RegistrationError, match="upgrades"):
        catalog.register(contract, greeter_entrypoint(), handler=different)


def test_non_tool_family_cannot_register_as_tool() -> None:
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(
        tool_manifest(family="skill", id="acme.sk", effects=[])
    )
    with pytest.raises(RegistrationError, match="'tool'"):
        catalog.register(contract, greeter_entrypoint(), handler=greet)


def test_non_callable_handler_refused() -> None:
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest())
    with pytest.raises(RegistrationError, match="not callable"):
        catalog.register(contract, greeter_entrypoint(), handler="greet")


def test_entrypoint_cannot_exceed_manifest_at_registration() -> None:
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest())
    sneaky = greeter_entrypoint()
    sneaky["capabilities"] = ["filesystem.write"]
    with pytest.raises(ManifestContractError, match="beyond the manifest"):
        catalog.register(contract, sneaky, handler=greet)


def test_default_policy_admits_nothing() -> None:
    """Fail closed: a Workspace without an allowlist has zero third-party
    tools, not all of them."""
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest(), digest="cafe")
    catalog.register(contract, greeter_entrypoint(), handler=greet)

    assert catalog.exposed_tools(ToolAccessPolicy()) == ()
    assert (
        catalog.exposed_tools(ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"}))) != ()
    )


def test_agent_allowlist_narrows_workspace_allowlist() -> None:
    catalog = ExtensionToolCatalog()
    for name in ("acme.greeter", "acme.scribe"):
        c = ExtensionContract.from_manifest(
            tool_manifest(id=name, effects=["read-only"]), digest="cafe"
        )
        catalog.register(c, {**greeter_entrypoint(), "name": name}, handler=greet)

    workspace = ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter", "acme.scribe"}))
    agent = ToolAccessPolicy(
        workspace_allowed=workspace.workspace_allowed,
        agent_allowed=frozenset({"acme.greeter"}),
    )
    exposed = catalog.exposed_tools(agent)
    assert [tool["tool_id"] for tool in exposed] == ["acme.greeter"]


def test_exposure_descriptor_carries_host_classification_and_permissions() -> None:
    """The descriptor names what review and policy reasoned about — never
    anything the package invented at runtime."""
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(
        tool_manifest(
            capabilities=["network.outbound"],
            effects=["read-only"],
            network={"allow": ["api.example"], "allowed_ports": [443]},
            secrets=[{"name": "EXAMPLE_KEY"}],
        ),
        digest="cafe",
    )
    catalog.register(contract, greeter_entrypoint(), handler=greet)
    policy = ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"}))
    (descriptor,) = catalog.exposed_tools(policy)

    assert descriptor["reversibility"] == ToolReversibility.REVERSIBLE.value
    assert descriptor["capabilities"] == ["network.outbound"]
    assert descriptor["network_allow"] == ["api.example"]
    assert descriptor["network_ports"] == [443]
    assert descriptor["secret_refs"] == ["EXAMPLE_KEY"]
    assert descriptor["manifest_sha256"] == "cafe"
    assert descriptor["effects"] == ["read-only"]
    assert descriptor["data_scopes"] == []


def test_tool_binding_carries_host_classification_and_scope() -> None:
    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(tool_manifest(effects=["mutating"]), digest="cafe")
    tool = catalog.register(contract, greeter_entrypoint(), handler=greet)
    binding = catalog.tool_binding(tool, workspace_id="ws-1", project_id="pr-1", node_id="node-7")

    assert binding.capability == "extension.tool:acme.greeter"
    assert binding.workspace_id == "ws-1"
    assert binding.project_id == "pr-1"
    assert binding.node_id == "node-7"
    # The classification in config is the HOST's derived tier, not a string
    # the extension supplied.
    assert binding.config["effect"] == ToolReversibility.REVERSIBLE.value
    assert binding.config["extension"] == "acme.greeter"
    assert binding.config["manifest_sha256"] == "cafe"
    assert binding.config["permissions"]["capabilities"] == []


def skill_manifest() -> dict[str, object]:
    return {
        "id": "acme.reporter",
        "publisher": "acme",
        "version": "0.1.0",
        "title": "Reporter",
        "description": "Composes tools into a report.",
        "contract": ">=1.0.0,<2.0.0",
        "family": "skill",
        "capabilities": ["tool.invoke", "workspace.read"],
        "effects": ["read-only"],
        "data": {"scopes": ["workspace", "run"]},
        "entrypoint": {"module": "acme_reporter.plugin", "object": "SKILL"},
    }


def skill_entrypoint() -> dict[str, object]:
    return {
        "kind": "skill",
        "name": "acme.reporter",
        "version": "0.1.0",
        "capabilities": ["tool.invoke"],
        "tools": ["acme.greeter"],
        "handler": "compose",
    }


def test_register_skill_projects_into_product_registry() -> None:
    registry = InMemorySkillRegistry()
    skill = SkillContract.from_manifest(skill_manifest(), skill_entrypoint())
    policy = ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"}))

    definition = register_extension_skill(
        skill,
        skill_entrypoint(),
        policy=policy,
        trust_tier="t2",
        skill_registry=registry,
    )

    assert definition.name == "acme.reporter"
    assert definition.trust_tier == "t2"
    assert "extension" in definition.groups
    assert definition.source.startswith("extension:0.1.0:")
    assert registry.get("acme.reporter") is not None


def test_skill_composition_outside_allowlist_refused_with_names() -> None:
    """AC4 for skills: composition over canonical tools is allowlist-bound."""
    registry = InMemorySkillRegistry()
    skill = SkillContract.from_manifest(
        skill_manifest(),
        {**skill_entrypoint(), "tools": ["acme.greeter", "acme.missing"]},
    )
    policy = ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"}))

    with pytest.raises(ToolNotAllowlisted) as excinfo:
        register_extension_skill(
            skill,
            skill_entrypoint() | {"tools": ["acme.greeter", "acme.missing"]},
            policy=policy,
            trust_tier="t2",
            skill_registry=registry,
        )
    assert "acme.missing" in str(excinfo.value)
    assert registry.get("acme.reporter") is None


def test_skill_trust_tier_is_host_owned() -> None:
    skill = SkillContract.from_manifest(skill_manifest(), skill_entrypoint())
    with pytest.raises(TrustTierError):
        register_extension_skill(
            skill,
            skill_entrypoint(),
            policy=ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"})),
            trust_tier="publisher-claims-t0",
        )


def test_product_registry_tier_rule_still_applies_to_extension_skills() -> None:
    """An extension skill cannot overwrite a t0 built-in — the product
    registry's own rule, reached through the extension projection."""
    registry = InMemorySkillRegistry()
    from maistro.types.skill import SkillDefinition

    registry.register(
        SkillDefinition(
            name="acme.reporter",
            description="built-in",
            trust_tier="t0",
        )
    )
    skill = SkillContract.from_manifest(skill_manifest(), skill_entrypoint())
    register_extension_skill(
        skill,
        skill_entrypoint(),
        policy=ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"})),
        trust_tier="t2",
        skill_registry=registry,
    )
    still_built_in = registry.get("acme.reporter")
    assert still_built_in is not None
    assert still_built_in.description == "built-in"


def test_mismatched_entrypoint_object_refused_at_registration() -> None:
    skill = SkillContract.from_manifest(skill_manifest(), skill_entrypoint())
    with pytest.raises(RegistrationError, match="does not match"):
        register_extension_skill(
            skill,
            {**skill_entrypoint(), "handler": "something_else"},
            policy=ToolAccessPolicy(workspace_allowed=frozenset({"acme.greeter"})),
            trust_tier="t2",
        )


def test_load_entrypoint_handler_resolves_from_module_namespace() -> None:
    """The host's code-import boundary resolves the handler by name on the
    entrypoint module — data accepted first, code loaded second."""
    contract = ExtensionContract.from_manifest(
        tool_manifest(
            id="acme.loader",
            entrypoint={"module": "json", "object": "not_used"},
        )
    )
    handler = load_entrypoint_handler(
        contract,
        {
            "kind": "tool",
            "name": "acme.loader",
            "version": "1.2.3",
            "capabilities": [],
            "handler": "dumps",
        },
    )
    assert callable(handler)
    assert handler({"k": 1}) == '{"k": 1}'


def test_load_entrypoint_handler_refuses_missing_handler() -> None:
    contract = ExtensionContract.from_manifest(
        tool_manifest(
            id="acme.loader",
            entrypoint={"module": "json", "object": "not_used"},
        )
    )
    with pytest.raises(RegistrationError, match="not callable"):
        load_entrypoint_handler(
            contract,
            {
                "kind": "tool",
                "name": "acme.loader",
                "version": "1.2.3",
                "capabilities": [],
                "handler": "no_such_function",
            },
        )
