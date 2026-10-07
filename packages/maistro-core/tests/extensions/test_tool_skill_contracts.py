"""Tool/Skill contract parsing and host-owned effect classification (M9-E3, #964).

Each test names the acceptance criterion or published rule it pins:

* manifests validate fail-closed against the published closed vocabularies;
* the effect floor is derived from declared effects AND requested
  capabilities — an extension cannot label a higher-risk effect as
  reversible by what it declares (AC3);
* runtime effect claims below the host floor are refused (AC3);
* entrypoint objects cannot exceed their manifest's authority;
* skill contracts carry their tool composition.
"""

from __future__ import annotations

import pytest

from maistro.extensions.tool_skill import (
    CAPABILITY_VOCABULARY,
    DATA_SCOPE_VOCABULARY,
    EffectClass,
    EffectDowngradeRefused,
    ExtensionContract,
    ManifestContractError,
    SkillContract,
    ToolEntrypoint,
    effect_risk,
    highest_risk,
    max_effect,
    to_reversibility,
    validate_effect_claim,
)
from maistro.tools.reversibility import ToolReversibility


def tool_manifest(**overrides: object) -> dict[str, object]:
    """A minimal valid tool-family manifest; tests overlay violations."""
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


def test_valid_manifest_parses_with_identity_and_digest() -> None:
    contract = ExtensionContract.from_manifest(tool_manifest(), digest="deadbeef")
    assert contract.extension_id == "acme.greeter"
    assert contract.publisher == "acme"
    assert contract.version == "1.2.3"
    assert contract.family == "tool"
    assert contract.entrypoint.module == "acme_greeter.plugin"
    assert contract.entrypoint.object == "PLUGIN"
    assert contract.manifest_sha256 == "deadbeef"


def test_read_only_tool_with_no_capabilities_classifies_internal() -> None:
    """An honest read-only declaration is honored: INTERNAL, free retry."""
    contract = ExtensionContract.from_manifest(tool_manifest())
    assert contract.effect_floor is EffectClass.READ_ONLY
    assert contract.reversibility is ToolReversibility.INTERNAL


def test_undeclared_tool_defaults_to_irreversible() -> None:
    """ADR-050's safe default: a tool declaring nothing classifies irreversible."""
    contract = ExtensionContract.from_manifest(tool_manifest(effects=[]))
    assert contract.effect_floor is EffectClass.IRREVERSIBLE
    assert contract.reversibility is ToolReversibility.IRREVERSIBLE


def test_read_only_claim_cannot_hide_network_outbound() -> None:
    """AC3: the floor comes from capabilities too — `read-only` + outbound
    network classifies external-side-effect, not internal."""
    contract = ExtensionContract.from_manifest(tool_manifest(capabilities=["network.outbound"]))
    assert contract.effect_floor is EffectClass.EXTERNAL_SIDE_EFFECT
    assert contract.reversibility is ToolReversibility.REVERSIBLE


def test_write_capabilities_floor_at_mutating() -> None:
    contract = ExtensionContract.from_manifest(
        tool_manifest(
            capabilities=["workspace.read", "memory.write"],
            effects=["read-only"],
        )
    )
    assert contract.effect_floor is EffectClass.MUTATING
    assert contract.reversibility is ToolReversibility.REVERSIBLE


def test_irreversible_declaration_classifies_irreversible() -> None:
    contract = ExtensionContract.from_manifest(tool_manifest(effects=["irreversible"]))
    assert contract.reversibility is ToolReversibility.IRREVERSIBLE


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (["filesystem.write"], EffectClass.MUTATING),
        (["tool.invoke"], EffectClass.MUTATING),
        (["secrets.read"], EffectClass.EXTERNAL_SIDE_EFFECT),
        (
            ["workspace.write", "network.outbound"],
            EffectClass.EXTERNAL_SIDE_EFFECT,
        ),
    ],
)
def test_capability_implied_floors(capabilities: list[str], expected: EffectClass) -> None:
    contract = ExtensionContract.from_manifest(
        tool_manifest(capabilities=capabilities, effects=["read-only"])
    )
    assert contract.effect_floor is expected


def test_runtime_downgrade_claim_is_refused() -> None:
    """AC3: a call-time claim below the host floor never relabels the call."""
    contract = ExtensionContract.from_manifest(tool_manifest(capabilities=["network.outbound"]))
    with pytest.raises(EffectDowngradeRefused) as excinfo:
        validate_effect_claim(contract, EffectClass.READ_ONLY)
    assert "host floor" in str(excinfo.value)


def test_runtime_claim_at_or_above_floor_is_adopted() -> None:
    """A claim at the floor passes through; a higher claim is adopted so the
    extension can take the *stricter* gate for one destructive call."""
    contract = ExtensionContract.from_manifest(tool_manifest(effects=["mutating"]))
    assert validate_effect_claim(contract, EffectClass.MUTATING) is EffectClass.MUTATING
    assert validate_effect_claim(contract, EffectClass.IRREVERSIBLE) is (EffectClass.IRREVERSIBLE)


def test_to_reversibility_covers_the_published_vocabulary() -> None:
    assert to_reversibility(EffectClass.READ_ONLY) is ToolReversibility.INTERNAL
    assert to_reversibility(EffectClass.MUTATING) is ToolReversibility.REVERSIBLE
    assert to_reversibility(EffectClass.EXTERNAL_SIDE_EFFECT) is ToolReversibility.REVERSIBLE
    assert to_reversibility(EffectClass.IRREVERSIBLE) is ToolReversibility.IRREVERSIBLE


def test_risk_ordering_helpers() -> None:
    assert effect_risk(EffectClass.READ_ONLY) < effect_risk(EffectClass.IRREVERSIBLE)
    assert highest_risk([EffectClass.READ_ONLY, EffectClass.MUTATING]) is EffectClass.MUTATING
    assert highest_risk([]) is None
    assert max_effect(EffectClass.READ_ONLY, EffectClass.IRREVERSIBLE) is (EffectClass.IRREVERSIBLE)


def test_vocabularies_match_the_published_reference() -> None:
    """The closed vocabularies are the ones docs/extensions publishes."""
    assert "network.outbound" in CAPABILITY_VOCABULARY
    assert "tool.invoke" in CAPABILITY_VOCABULARY
    assert "secrets.read" in CAPABILITY_VOCABULARY
    assert (
        frozenset({"workspace", "agent", "run", "memory", "messages", "artifacts"})
        == DATA_SCOPE_VOCABULARY
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"capabilities": ["totally.unknown"]},
        {"effects": ["kind-of-readonly"]},
        {"family": "mobile-app"},
        {"data": {"scopes": ["everything"]}},
        {"publisher": "Acme"},
        {"id": "other.greeter"},
        {"id": "nonamespaced"},
        {"id": "acme.Greeter"},
        {"version": "1.2"},
        {"contract": ">=1.0.0,<3.0.0"},
        {"contract": ">=1.0.0"},
        {"entrypoint": {"module": "no object key", "object": "PLUGIN"}},
        {"entrypoint": {"module": "ok_module", "object": "0bad"}},
    ],
)
def test_malformed_manifests_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ManifestContractError):
        ExtensionContract.from_manifest(tool_manifest(**overrides))


def test_secret_refs_must_be_env_style_names() -> None:
    manifest = tool_manifest(secrets=[{"name": "lowercase_key"}])
    with pytest.raises(ManifestContractError, match="env-style"):
        ExtensionContract.from_manifest(manifest)


def test_secret_values_are_never_a_manifest_shape() -> None:
    """A manifest entry with a value-looking field is still names-only."""
    manifest = tool_manifest(
        capabilities=["secrets.read"],
        secrets=[{"name": "WEATHER_API_KEY", "value": "sk-live-123"}],
    )
    contract = ExtensionContract.from_manifest(manifest)
    assert contract.secret_refs == ("WEATHER_API_KEY",)


def test_network_ports_must_be_real_ports() -> None:
    with pytest.raises(ManifestContractError, match="ports"):
        ExtensionContract.from_manifest(
            tool_manifest(network={"allow": ["api.example"], "allowed_ports": [70000]})
        )
    contract = ExtensionContract.from_manifest(
        tool_manifest(network={"allow": ["api.example"], "allowed_ports": [443]})
    )
    assert contract.network_allow == ("api.example",)
    assert contract.network_ports == (443,)


def test_tool_entrypoint_object_validated_against_manifest() -> None:
    contract = ExtensionContract.from_manifest(tool_manifest())
    entrypoint = ToolEntrypoint.from_object(
        {
            "kind": "tool",
            "name": "acme.greeter",
            "version": "1.2.3",
            "capabilities": [],
            "handler": "greet",
        },
        contract,
    )
    assert entrypoint.handler == "greet"


def test_tool_entrypoint_cannot_claim_undeclared_capabilities() -> None:
    """The entrypoint object is data about the code: it cannot exceed the
    authority the manifest requested."""
    contract = ExtensionContract.from_manifest(tool_manifest())
    with pytest.raises(ManifestContractError, match="beyond the manifest"):
        ToolEntrypoint.from_object(
            {
                "kind": "tool",
                "name": "acme.greeter",
                "version": "1.2.3",
                "capabilities": ["filesystem.write"],
                "handler": "greet",
            },
            contract,
        )


@pytest.mark.parametrize(
    "object_patch",
    [
        {"kind": "skill"},
        {"name": "other.greeter"},
        {"version": "9.9.9"},
    ],
)
def test_tool_entrypoint_identity_must_match_manifest(
    object_patch: dict[str, str],
) -> None:
    contract = ExtensionContract.from_manifest(tool_manifest())
    obj: dict[str, object] = {
        "kind": "tool",
        "name": "acme.greeter",
        "version": "1.2.3",
        "capabilities": [],
        "handler": "greet",
    }
    obj.update(object_patch)
    with pytest.raises(ManifestContractError):
        ToolEntrypoint.from_object(obj, contract)


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
        "tools": ["reference.greeter", "builtin.web_search"],
        "handler": "compose",
    }


def test_skill_contract_parses_composition() -> None:
    skill = SkillContract.from_manifest(skill_manifest(), skill_entrypoint())
    assert skill.contract.family == "skill"
    assert skill.entrypoint.tools == ("reference.greeter", "builtin.web_search")
    assert skill.entrypoint.handler == "compose"
    # Delegated contract fields read naturally.
    assert skill.version == "0.1.0"
    assert skill.requires("tool.invoke")


def test_skill_contract_refuses_tool_family() -> None:
    with pytest.raises(ManifestContractError, match="'skill'"):
        SkillContract.from_manifest(tool_manifest(), skill_entrypoint())


def test_skill_composition_names_must_be_non_empty() -> None:
    entrypoint = skill_entrypoint()
    entrypoint["tools"] = ["ok", "  "]
    with pytest.raises(ManifestContractError, match="empty"):
        SkillContract.from_manifest(skill_manifest(), entrypoint)
