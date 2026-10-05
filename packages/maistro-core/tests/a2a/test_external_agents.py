"""External Agent discovery/card adapter and canonical projection (M9-D1, #958).

Each test names the acceptance criterion it pins. The module under test is
``maistro.a2a.external``; the registry ingests descriptors as pure data and
never contacts an endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.a2a.external import (
    EXTERNAL_PRIORITY_TIER,
    EXTERNAL_TRUST_TIER,
    AuthorityEscalationRefused,
    CapabilityAuthorization,
    DefaultDenyProjectionPolicy,
    DescriptorAlreadyRegistered,
    DescriptorInvalid,
    EndpointConflict,
    ExternalAgentRegistry,
    RemoteAgentDescriptor,
    UnknownExternalAgent,
    UnsupportedCapability,
    parse_remote_card,
    payload_digest,
)

FROZEN_NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def _clock() -> datetime:
    return FROZEN_NOW


def _card(**overrides: Any) -> dict[str, Any]:
    """A well-formed A2A-style card; keyword overrides per test."""
    card: dict[str, Any] = {
        "name": "Deep Researcher",
        "version": "2.4.1",
        "url": "https://agents.example.com/researcher",
        "protocolVersion": "0.2.9",
        "description": "External research specialist",
        "provider": {"organization": "Example Labs"},
        "capabilities": {"streaming": True},
        "tools": ["web_search", "crawl"],
        "skills": [{"id": "literature-review", "tags": ["research"]}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text", "file"],
    }
    card.update(overrides)
    return card


@dataclass
class StaticPolicy:
    """Test policy granting an explicit capability-token set.

    ``approve_broadening`` mirrors a policy decision on refresh: off by
    default, so broadening refreshes are refused unless the test turns it on.
    """

    capabilities: frozenset[str]
    policy_id_value: str = "static-test-policy"
    approve_broadening: bool = False

    def policy_id(self) -> str:
        return self.policy_id_value

    def authorize(
        self, descriptor: RemoteAgentDescriptor, *, now: datetime
    ) -> CapabilityAuthorization:
        declared = descriptor.capabilities.surface()
        granted = frozenset(self.capabilities & declared)
        return CapabilityAuthorization(
            authorized=bool(granted),
            capabilities=granted,
            policy_id=self.policy_id(),
            decided_at=now,
        )

    def allows_refresh(
        self, current: RemoteAgentDescriptor, candidate: RemoteAgentDescriptor
    ) -> bool:
        return self.approve_broadening


def _registry(**kwargs: Any) -> ExternalAgentRegistry:
    return ExternalAgentRegistry(clock=_clock, **kwargs)


# AC: "external Agent descriptor can be inspected without invoking it"


def test_descriptor_parses_from_json_string_and_dict_identically() -> None:
    import json

    from_dict = parse_remote_card(_card())
    from_str = parse_remote_card(json.dumps(_card()))
    assert from_dict == from_str


def test_registry_holds_no_invoker_and_projects_without_endpoint_contact() -> None:
    """Inspection is structural: the registry takes no transport/invoker at all."""
    registry = _registry()
    registry.register(_card(), source_url="https://agents.example.com/.well-known/agent.json")
    projection = registry.project("deep-researcher")
    assert projection.descriptor.endpoint_url == "https://agents.example.com/researcher"
    assert projection.descriptor.version == "2.4.1"
    assert projection.descriptor.capabilities.tools == ("web_search", "crawl")
    assert projection.descriptor.capabilities.skills == ("literature-review",)
    assert projection.to_dict()["descriptor"]["endpoint_url"].startswith("https://")


def test_slug_id_is_derived_when_card_carries_no_id() -> None:
    descriptor = parse_remote_card(_card())
    assert descriptor.agent_id == "deep-researcher"
    explicit = parse_remote_card(_card(id="researcher-7"))
    assert explicit.agent_id == "researcher-7"


def test_legacy_modality_keys_and_defaults() -> None:
    card = _card()
    del card["defaultInputModes"], card["defaultOutputModes"]
    legacy = parse_remote_card({**card, "inputModes": ["text"], "outputModes": ["text"]})
    assert legacy.capabilities.input_modes == ("text",)
    assert legacy.capabilities.output_modes == ("text",)
    bare = parse_remote_card(card)
    assert bare.capabilities.input_modes == ("text",)
    assert bare.capabilities.output_modes == ("text",)


def test_payload_digest_is_stable_for_equal_mappings() -> None:
    assert payload_digest(_card()) == payload_digest(dict(_card()))
    assert payload_digest(_card()) != payload_digest(_card(version="9.9.9"))


def test_unknown_agent_id_fails_loudly() -> None:
    with pytest.raises(UnknownExternalAgent):
        _registry().project("nope")


def test_malformed_payloads_fail_with_the_field_named() -> None:
    for bad, field in (
        (_card(name=""), "name"),
        (_card(version=""), "version"),
        (_card(url=""), "url"),
        (_card(tools=["ok", 3]), "tools"),
        (_card(skills=[{"nope": 1}]), "skills"),
        (_card(skills="literature-review"), "skills"),
        (_card(capabilities="streaming"), "capabilities"),
        ({**_card(), "name": "!!!"}, "agent id"),
    ):
        with pytest.raises(DescriptorInvalid, match=field):
            parse_remote_card(bad)
    with pytest.raises(DescriptorInvalid, match="valid JSON"):
        parse_remote_card("{not json")
    with pytest.raises(DescriptorInvalid, match="JSON object"):
        parse_remote_card("[1, 2]")


# AC: "unsupported/unknown capabilities fail explicitly"


@pytest.mark.parametrize(
    ("capabilities", "offender"),
    (
        ({"pushNotifications": True}, "pushNotifications"),
        ({"stateTransitionHistory": True}, "stateTransitionHistory"),
        ({"telepathy": True}, "telepathy"),
        ({"extensions": [{"uri": "https://example.com/ext"}]}, "https://example.com/ext"),
        ({"extensions": [{"other": 1}]}, "<unnamed>"),
    ),
)
def test_unsupported_or_unknown_capabilities_are_refused_at_ingestion(
    capabilities: dict[str, Any], offender: str
) -> None:
    with pytest.raises(UnsupportedCapability, match=offender):
        parse_remote_card(_card(capabilities=capabilities))


def test_unasserted_unsupported_flags_and_off_extensions_are_tolerated() -> None:
    parsed = parse_remote_card(_card(capabilities={"streaming": False, "pushNotifications": False}))
    assert parsed.capabilities.streaming is False
    parsed = parse_remote_card(_card(capabilities={"streaming": True, "extensions": None}))
    assert parsed.capabilities.streaming is True


# AC: "remote card/descriptor does not mint canonical Workspace root authority"


def test_projection_is_clamped_to_least_privilege_regardless_of_policy() -> None:
    registry = _registry(
        policy=StaticPolicy(
            capabilities=frozenset({"tool:web_search", "tool:crawl", "skill:literature-review"})
        )
    )
    registry.register(_card())
    card = registry.project("deep-researcher").card
    assert card.trust_tier == EXTERNAL_TRUST_TIER == "t9"
    assert card.delegation_mode == "none"
    assert card.sub_agents == ()
    assert card.priority_tier == EXTERNAL_PRIORITY_TIER == "P5"
    assert card.scope == "external"
    # The card's own claims granted it nothing: only the policy's grant shows.
    assert card.active is True
    assert card.tools == ("web_search", "crawl")
    assert card.skills == ("literature-review",)


def test_default_deny_policy_authorizes_nothing() -> None:
    registry = _registry()
    record = registry.register(_card())
    assert record.authorization.authorized is False
    assert record.authorization.capabilities == frozenset()
    projection = registry.project("deep-researcher")
    assert projection.card.active is False
    assert projection.card.tools == ()


def test_policy_cannot_mint_capabilities_the_card_does_not_declare() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:shell"})))
    registry.register(_card())
    card = registry.project("deep-researcher").card
    assert card.tools == ()


# AC: "canonical Agent/capability projection retains remote provenance/version"


def test_projection_retains_remote_version_publisher_and_payload_digest() -> None:
    payload = _card()
    registry = _registry()
    registry.register(payload, source_url="https://agents.example.com/.well-known/agent.json")
    projection = registry.project("deep-researcher")
    assert projection.card.version == "2.4.1"
    assert projection.provenance.remote_version == "2.4.1"
    assert projection.provenance.publisher == "Example Labs"
    assert projection.provenance.protocol_version == "0.2.9"
    assert projection.provenance.source_url == "https://agents.example.com/.well-known/agent.json"
    assert projection.provenance.payload_sha256 == payload_digest(payload)
    assert projection.provenance.ingested_at == FROZEN_NOW


def test_refresh_updates_provenance_to_the_new_payload_snapshot() -> None:
    registry = _registry()
    registry.register(_card())
    updated = registry.refresh_descriptor("deep-researcher", _card(version="2.5.0"))
    assert updated.provenance.remote_version == "2.5.0"
    assert updated.provenance.payload_sha256 == payload_digest(_card(version="2.5.0"))
    assert registry.project("deep-researcher").card.version == "2.5.0"


def test_registration_is_idempotent_for_identical_payload() -> None:
    registry = _registry()
    first = registry.register(_card())
    second = registry.register(_card())
    assert first is second
    assert registry.agents() == ("deep-researcher",)


# AC: "availability is truthful and distinct from capability authorization"


def test_fresh_record_is_unknown_and_never_eligible() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:web_search"})))
    registry.register(_card())
    projection = registry.project("deep-researcher")
    assert projection.availability.state.value == "unknown"
    assert projection.availability.probed_at is None
    assert projection.eligible is False
    assert registry.eligible_specialists() == []


def test_available_but_unauthorized_is_not_eligible() -> None:
    registry = _registry()
    registry.register(_card())
    registry.report_availability("deep-researcher", available=True, detail="probe ok")
    projection = registry.project("deep-researcher")
    assert projection.availability.state.value == "available"
    assert projection.availability.probed_at == FROZEN_NOW
    assert projection.eligible is False


def test_authorized_but_unavailable_is_not_eligible() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:web_search"})))
    registry.register(_card())
    registry.report_availability("deep-researcher", available=False, detail="5xx")
    projection = registry.project("deep-researcher")
    assert projection.eligible is False
    # The two axes stay independently visible:
    assert projection.authorization.authorized is True
    assert projection.availability.state.value == "unavailable"
    # ...and the authorized set is still listable without pretending health:
    without_health = registry.eligible_specialists(require_available=False)
    assert [p.card.id for p in without_health] == ["deep-researcher"]


def test_authorized_and_available_is_eligible() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:web_search"})))
    registry.register(_card())
    registry.report_availability("deep-researcher", available=True)
    eligible = registry.eligible_specialists()
    assert [p.card.id for p in eligible] == ["deep-researcher"]
    assert eligible[0].eligible is True


def test_inactive_registration_is_never_eligible() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:web_search"})))
    registry.register(_card(), active=False)
    registry.report_availability("deep-researcher", available=True)
    assert registry.project("deep-researcher").card.active is False
    assert registry.eligible_specialists() == []


def test_availability_reported_on_unknown_agent_fails() -> None:
    with pytest.raises(UnknownExternalAgent):
        _registry().report_availability("nope", available=True)


# AC: "descriptor refresh cannot silently broaden effective authority without
# policy evaluation"


def test_broadening_refresh_is_refused_under_default_policy() -> None:
    registry = _registry()
    registry.register(_card())
    with pytest.raises(AuthorityEscalationRefused, match="tool:shell"):
        registry.refresh_descriptor(
            "deep-researcher", _card(tools=["web_search", "crawl", "shell"])
        )
    # The refusal left the record untouched:
    assert registry.project("deep-researcher").descriptor.capabilities.tools == (
        "web_search",
        "crawl",
    )


def test_broadening_refresh_without_policy_approval_is_refused_even_for_granting_policies() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:shell"})))
    registry.register(_card())
    with pytest.raises(AuthorityEscalationRefused):
        registry.refresh_descriptor(
            "deep-researcher", _card(tools=["web_search", "crawl", "shell"])
        )


def test_policy_approved_broadening_is_re_authorized_and_effective() -> None:
    registry = _registry(
        policy=StaticPolicy(
            capabilities=frozenset({"tool:web_search", "tool:shell"}), approve_broadening=True
        )
    )
    registry.register(_card())
    refreshed = registry.refresh_descriptor(
        "deep-researcher", _card(tools=["web_search", "crawl", "shell"])
    )
    assert refreshed.descriptor.capabilities.tools == ("web_search", "crawl", "shell")
    card = registry.project("deep-researcher").card
    # Effective capabilities were re-evaluated: declared ∩ authorized.
    assert card.tools == ("web_search", "shell")
    assert refreshed.authorization.policy_id == "static-test-policy"


def test_narrowing_refresh_needs_no_policy_approval() -> None:
    registry = _registry()
    registry.register(_card())
    refreshed = registry.refresh_descriptor("deep-researcher", _card(tools=["web_search"]))
    assert refreshed.descriptor.capabilities.tools == ("web_search",)
    # Authorization is re-evaluated on every accepted refresh, narrowing too:
    assert refreshed.authorization.authorized is False


def test_identical_refresh_payload_is_a_no_op() -> None:
    registry = _registry()
    record = registry.register(_card())
    assert registry.refresh_descriptor("deep-researcher", _card()) is record


def test_refresh_to_a_different_endpoint_is_conflict_not_overwrite() -> None:
    registry = _registry()
    registry.register(_card())
    with pytest.raises(EndpointConflict, match="names endpoint"):
        registry.refresh_descriptor("deep-researcher", _card(url="https://other.example.com/agent"))


def test_registering_changed_bytes_for_a_registered_id_sends_the_caller_to_refresh() -> None:
    registry = _registry()
    registry.register(_card())
    with pytest.raises(DescriptorAlreadyRegistered, match="refresh"):
        registry.register(_card(version="3.0.0"))
    with pytest.raises(EndpointConflict, match="lifecycle decision"):
        registry.register(_card(url="https://elsewhere.example.com/"))


def test_default_policy_object_satisfies_the_protocol_directly() -> None:
    policy = DefaultDenyProjectionPolicy()
    descriptor = parse_remote_card(_card())
    decision = policy.authorize(descriptor, now=FROZEN_NOW)
    assert decision.authorized is False
    assert decision.decided_at == FROZEN_NOW
    assert policy.allows_refresh(descriptor, descriptor) is False
    assert policy.policy_id() == "external-default-deny"


def test_serialization_surfaces_render_decisions() -> None:
    registry = _registry(policy=StaticPolicy(capabilities=frozenset({"tool:web_search"})))
    registry.register(_card())
    registry.report_availability("deep-researcher", available=True)
    blob = registry.project("deep-researcher").to_dict()
    assert blob["authorization"]["authorized"] is True
    assert blob["authorization"]["capabilities"] == ["tool:web_search"]
    assert blob["availability"]["state"] == "available"
    assert blob["provenance"]["publisher"] == "Example Labs"
    assert blob["eligible"] is True
    assert blob["declared_surface"]  # capability tokens, sorted


def test_ingestion_of_unreachable_type_fails_closed() -> None:
    with pytest.raises(DescriptorInvalid, match="mapping or JSON string"):
        parse_remote_card(123)  # type: ignore[arg-type]
