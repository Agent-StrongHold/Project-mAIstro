"""External Agent discovery — remote descriptor ingestion and canonical projection.

M9-D1 (issue #958, epic M9-D #941): an external Agent endpoint/protocol
descriptor (an A2A-style card, where applicable) can be registered, inspected,
refreshed, and projected into canonical Agent/capability metadata without the
remote protocol ever becoming a second Agent-definition authority.

The rules this module enforces, each pinned by a test in
``packages/maistro-core/tests/a2a/test_external_agents.py``:

* **Ingestion is pure data.** Parsing never contacts the endpoint; inspection
  and projection are read-only over stored records.
* **Unknown/unsupported capability semantics fail explicitly**
  (:class:`UnsupportedCapability`) — a card declaring capability semantics this
  build cannot honor is rejected at ingestion instead of silently degraded.
* **A remote card never mints canonical Workspace root authority.** The
  projected :class:`~maistro.agents.catalog.AgentCard` is clamped: least
  privileged trust tier, ``delegation_mode="none"``, no sub-agents, and
  ``scope="external"``.
* **Projection retains remote provenance/version** — the remote version,
  publisher, protocol version, source URL, payload digest, and ingestion
  timestamps stay on the projection record.
* **Availability is evidence-based and distinct from authorization.** A fresh
  record is availability-unknown and never eligible until health is reported;
  capability authorization comes only from the injected
  :class:`ProjectionPolicy`, never from the card itself.
* **Refresh cannot silently broaden effective authority.** A candidate
  descriptor whose capability surface exceeds the current record's declared
  surface requires the policy's explicit approval
  (:meth:`ProjectionPolicy.allows_refresh`); otherwise
  :class:`AuthorityEscalationRefused`. Effective capabilities are re-evaluated
  (declared ∩ authorized) on every accepted refresh.
* **Refresh never re-identifies the registration.** A candidate whose agent
  id — explicit or name-derived — differs from the id it is refreshed under is
  refused (:class:`DescriptorIdentityMismatch`); the lookup key, descriptor,
  and projected ``AgentCard.id`` cannot drift apart, and a refresh can never
  mint or spoof a second canonical identity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from maistro.a2a.broker import A2AError
from maistro.agents.catalog import AgentCard

__all__ = [
    "EXTERNAL_PRIORITY_TIER",
    "EXTERNAL_TRUST_TIER",
    "AuthorityEscalationRefused",
    "Availability",
    "AvailabilityState",
    "CapabilityAuthorization",
    "DefaultDenyProjectionPolicy",
    "DescriptorAlreadyRegistered",
    "DescriptorIdentityMismatch",
    "DescriptorInvalid",
    "DescriptorProvenance",
    "EndpointConflict",
    "ExternalAgentRegistry",
    "ProjectionPolicy",
    "RegisteredExternalAgent",
    "RemoteAgentDescriptor",
    "RemoteCapabilities",
    "SpecialistProjection",
    "UnknownExternalAgent",
    "UnsupportedCapability",
    "parse_remote_card",
    "payload_digest",
]


#: The trust tier every projected external specialist receives, regardless of
#: what its card implies. ``t0`` is the most privileged canonical tier and the
#: numeric rank grows as privilege shrinks, so the least-privileged tier is the
#: only tier a remote descriptor can never escalate away from.
EXTERNAL_TRUST_TIER = "t9"

#: The lowest canonical priority tier: external specialists are picked last.
EXTERNAL_PRIORITY_TIER = "P5"

#: The A2A-style card capability flags this build can actually honor. Anything
#: else a card declares is either a known-unsupported feature (refused when
#: asserted) or an unknown key (always refused).
SUPPORTED_CARD_FEATURES = frozenset({"streaming"})

#: Capability flags whose semantics are known but not implemented here. A card
#: asserting one is refused rather than served with degraded fidelity.
_KNOWN_UNSUPPORTED_FEATURES = frozenset({"pushNotifications", "stateTransitionHistory"})


class DescriptorError(A2AError):
    """Base class for external descriptor ingestion/registry failures."""


class DescriptorInvalid(DescriptorError):
    """The payload is not a well-formed external Agent descriptor."""


class UnsupportedCapability(DescriptorError):
    """The card declares capability semantics this build cannot honor.

    Raised instead of silently ignoring the declaration: a card MAIstro cannot
    serve truthfully must fail ingestion loudly, not project as a specialist
    that quietly lacks what it advertised.
    """


class UnknownExternalAgent(DescriptorError):
    """No external Agent is registered under the requested id."""


class EndpointConflict(DescriptorError):
    """A descriptor for an already-registered agent id names another endpoint.

    One registered agent id permanently names one endpoint. A different
    endpoint under the same id is a re-pointing of canonical delegation
    targets — a lifecycle decision with its own auditable flow, never a silent
    registry overwrite.
    """


class DescriptorAlreadyRegistered(DescriptorError):
    """Fresh bytes for an already-registered agent id arrived via ``register``.

    Re-registration is reserved for the idempotent identical payload; changed
    bytes must go through :meth:`ExternalAgentRegistry.refresh_descriptor`, the path that
    evaluates policy before anything broadens.
    """


class DescriptorIdentityMismatch(DescriptorError):
    """A refresh payload carries a different agent id than the registration.

    One registered id permanently names one canonical identity. A card whose
    explicit ``id`` — or name-derived slug — differs from the id it is
    refreshed under would leave the record keyed under the requested id while
    its descriptor and projected :class:`~maistro.agents.catalog.AgentCard.id`
    answer to another, splitting lookups from projections. Renaming is a
    lifecycle decision (deregister and register the new identity), never a
    silent refresh side effect.
    """


class AuthorityEscalationRefused(DescriptorError):
    """A descriptor refresh would broaden authority without policy approval."""


def payload_digest(payload: Mapping[str, Any] | str) -> str:
    """Digest the descriptor payload exactly as it was received.

    Strings digest as their encoded bytes; mappings digest as canonical JSON
    (sorted keys, compact separators) so equal mappings always agree. The
    digest covers the payload as received — the provenance anchor saying
    *which* descriptor a record was ingested from.
    """
    if isinstance(payload, str):
        data = payload.encode()
    else:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class RemoteCapabilities:
    """Canonical projection of a remote card's capability declarations.

    ``tools`` and ``skills`` are names the remote declares it can exercise or
    perform; ``input_modes``/``output_modes`` are the payload modalities it
    accepts and produces; ``streaming`` is the one card feature flag this
    build honors. Nothing here is authority — the projection intersects these
    declarations with the policy's authorization.
    """

    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    input_modes: tuple[str, ...] = ("text",)
    output_modes: tuple[str, ...] = ("text",)
    streaming: bool = False

    def surface(self) -> frozenset[str]:
        """Capability tokens naming everything this descriptor declares.

        The refresh gate compares candidate surfaces with these tokens, so a
        broadening is any token the current descriptor did not declare.
        """
        tokens = {f"tool:{name}" for name in self.tools}
        tokens |= {f"skill:{name}" for name in self.skills}
        tokens |= {f"modality:in:{mode}" for mode in self.input_modes}
        tokens |= {f"modality:out:{mode}" for mode in self.output_modes}
        if self.streaming:
            tokens.add("feature:streaming")
        return frozenset(tokens)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for inspection surfaces."""
        return {
            "tools": list(self.tools),
            "skills": list(self.skills),
            "input_modes": list(self.input_modes),
            "output_modes": list(self.output_modes),
            "streaming": self.streaming,
        }


@dataclass(frozen=True)
class RemoteAgentDescriptor:
    """One parsed external Agent descriptor (an A2A-style card, where applicable).

    Pure data: carrying this object never implies reachability of, or authority
    for, the remote agent. ``version`` is the *remote's* version and is
    retained verbatim through projection.
    """

    agent_id: str
    name: str
    description: str
    version: str
    protocol_version: str
    endpoint_url: str
    publisher: str
    capabilities: RemoteCapabilities


@dataclass(frozen=True)
class DescriptorProvenance:
    """Where a descriptor came from, snapshotted at ingestion time.

    Recorded once per registration/refresh: if the remote later rewrites or
    withdraws its card, the record still says what was ingested, when, from
    where, and under which digest.
    """

    source_url: str
    payload_sha256: str
    ingested_at: datetime
    publisher: str
    protocol_version: str
    remote_version: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for inspection surfaces."""
        return {
            "source_url": self.source_url,
            "payload_sha256": self.payload_sha256,
            "ingested_at": self.ingested_at.isoformat(),
            "publisher": self.publisher,
            "protocol_version": self.protocol_version,
            "remote_version": self.remote_version,
        }


@dataclass(frozen=True)
class CapabilityAuthorization:
    """The policy's capability grant for one descriptor, at one moment.

    Authorization is decided by the injected :class:`ProjectionPolicy` only —
    never derived from the card's own claims — and is recorded so a projection
    can always answer *who authorized this, and when*.
    """

    authorized: bool
    capabilities: frozenset[str]
    policy_id: str
    decided_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for inspection surfaces."""
        return {
            "authorized": self.authorized,
            "capabilities": sorted(self.capabilities),
            "policy_id": self.policy_id,
            "decided_at": self.decided_at.isoformat(),
        }


class AvailabilityState(StrEnum):
    """Evidence-based reachability of the external endpoint.

    Deliberately disjoint from capability authorization: an endpoint can be
    up while unauthorized, or authorized while down. ``UNKNOWN`` is the
    truthful initial state — a record never claims availability without a
    reported probe.
    """

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Availability:
    """The last reported health of the external endpoint."""

    state: AvailabilityState = AvailabilityState.UNKNOWN
    detail: str = ""
    probed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for inspection surfaces."""
        return {
            "state": self.state.value,
            "detail": self.detail,
            "probed_at": self.probed_at.isoformat() if self.probed_at else None,
        }


@runtime_checkable
class ProjectionPolicy(Protocol):
    """The one policy authority over external-specialist authorization.

    The card never authorizes itself: every grant and every broadening
    refresh passes through this protocol, so a deployment plugs in its own
    governance without touching ingestion.
    """

    def policy_id(self) -> str:
        """Stable identifier recorded on every authorization decision."""
        ...

    def authorize(
        self, descriptor: RemoteAgentDescriptor, *, now: datetime
    ) -> CapabilityAuthorization:
        """Decide which declared capabilities are authorized, if any."""
        ...

    def allows_refresh(
        self, current: RemoteAgentDescriptor, candidate: RemoteAgentDescriptor
    ) -> bool:
        """Approve or refuse a candidate descriptor that broadens the surface."""
        ...


class DefaultDenyProjectionPolicy:
    """Default-deny policy: nothing is authorized; broadening refreshes refused.

    The shipped floor. A deployment that wants external specialists eligible
    injects a policy that says exactly which declared capabilities it grants —
    silence must never widen what a remote descriptor can do.
    """

    def policy_id(self) -> str:
        """Stable identifier recorded on every authorization decision."""
        return "external-default-deny"

    def authorize(
        self, descriptor: RemoteAgentDescriptor, *, now: datetime
    ) -> CapabilityAuthorization:
        """Authorize nothing: the remote card is never self-certifying."""
        return CapabilityAuthorization(
            authorized=False,
            capabilities=frozenset(),
            policy_id=self.policy_id(),
            decided_at=now,
        )

    def allows_refresh(
        self, current: RemoteAgentDescriptor, candidate: RemoteAgentDescriptor
    ) -> bool:
        """Refuse every broadening; narrowing refreshes need no approval."""
        return False


@dataclass(frozen=True)
class RegisteredExternalAgent:
    """One registered external Agent: descriptor, provenance, and decisions."""

    descriptor: RemoteAgentDescriptor
    provenance: DescriptorProvenance
    authorization: CapabilityAuthorization
    availability: Availability
    active: bool = True


@dataclass(frozen=True)
class SpecialistProjection:
    """Canonical Agent/capability projection of one external Agent record.

    Inspection surface and projection in one immutable record: ``card`` is the
    canonical :class:`~maistro.agents.catalog.AgentCard` (clamped, authorized
    subset only), and the remaining fields keep the remote provenance, the
    authorization decision, and the availability evidence distinct.
    """

    card: AgentCard
    descriptor: RemoteAgentDescriptor
    provenance: DescriptorProvenance
    authorization: CapabilityAuthorization
    availability: Availability
    declared_surface: frozenset[str]

    @property
    def eligible(self) -> bool:
        """Authorized, active, *and* currently reported available.

        The conjunction is the point: availability alone is not authorization,
        authorization alone is not availability, and only their conjunction
        makes an external specialist eligible.
        """
        return (
            self.card.active
            and self.authorization.authorized
            and self.availability.state is AvailabilityState.AVAILABLE
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form for inspection surfaces."""
        # AgentCard.to_dict() omits scope; the external clamp is a
        # security-relevant classification, so re-attach it explicitly
        # instead of letting consumers fall back to the ``builtin`` default.
        card = {**self.card.to_dict(), "scope": self.card.scope}
        return {
            "card": card,
            "descriptor": {
                "agent_id": self.descriptor.agent_id,
                "name": self.descriptor.name,
                "endpoint_url": self.descriptor.endpoint_url,
                "capabilities": self.descriptor.capabilities.to_dict(),
            },
            "declared_surface": sorted(self.declared_surface),
            "provenance": self.provenance.to_dict(),
            "authorization": self.authorization.to_dict(),
            "availability": self.availability.to_dict(),
            "eligible": self.eligible,
        }


def _payload_mapping(payload: Mapping[str, Any] | str) -> Mapping[str, Any]:
    """Coerce a payload to a mapping, failing loudly on anything else."""
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DescriptorInvalid(f"descriptor payload is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise DescriptorInvalid("descriptor payload must be a JSON object")
        return data
    raise DescriptorInvalid(
        f"descriptor payload must be a mapping or JSON string, got {type(payload).__name__}"
    )


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    """A required non-empty string field."""
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DescriptorInvalid(
            f"descriptor field {key!r} is required and must be a non-empty string"
        )
    return value.strip()


def _text_tuple(raw: Any, *, field: str) -> tuple[str, ...]:
    """A list of non-empty strings; anything else fails the descriptor."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise DescriptorInvalid(f"descriptor field {field!r} must be a list of non-empty strings")
    return tuple(item.strip() for item in raw)


def _modalities(raw: Mapping[str, Any], *, modern_key: str, legacy_key: str) -> tuple[str, ...]:
    """Read payload modality declarations (modern A2A key, then legacy).

    A card that declares no modalities defaults to ``text`` — the A2A baseline
    — rather than projecting a specialist that accepts nothing.
    """
    value = raw.get(modern_key, raw.get(legacy_key))
    modes = _text_tuple(value, field=modern_key)
    return modes or ("text",)


def _skills(raw: Any) -> tuple[str, ...]:
    """Canonical skill names from A2A-style skill entries (or plain strings)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise DescriptorInvalid("descriptor field 'skills' must be a list")
    names: list[str] = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, Mapping):
            candidate = item.get("id", item.get("name"))
            name = candidate.strip() if isinstance(candidate, str) else ""
        else:
            name = ""
        if not name:
            raise DescriptorInvalid("every skills entry needs a non-empty 'id' or 'name' string")
        names.append(name)
    return tuple(names)


def _reject_extensions(value: Any) -> None:
    """Refuse capability-extension declarations explicitly."""
    if value is None:
        return
    if not isinstance(value, list):
        raise DescriptorInvalid("card capability 'extensions' must be a list")
    uris = [
        str(item.get("uri")) if isinstance(item, Mapping) and item.get("uri") else "<unnamed>"
        for item in value
    ]
    if uris:
        raise UnsupportedCapability(
            f"card declares capability extension(s) {uris}; extension semantics "
            "are not supported by this build and are not silently ignored"
        )


def _parse_capabilities(raw: Mapping[str, Any]) -> RemoteCapabilities:
    """Parse the card's capability block, refusing unsupported semantics."""
    block = raw.get("capabilities", {})
    if not isinstance(block, Mapping):
        raise DescriptorInvalid("descriptor field 'capabilities' must be an object")
    streaming = False
    for key, value in block.items():
        key_text = str(key)
        if key_text == "extensions":
            _reject_extensions(value)
        elif key_text in SUPPORTED_CARD_FEATURES:
            if not isinstance(value, bool):
                raise DescriptorInvalid(
                    f"card capability {key_text!r} must be a boolean, got {type(value).__name__}"
                )
            streaming = streaming or value
        elif key_text in _KNOWN_UNSUPPORTED_FEATURES:
            if value:
                raise UnsupportedCapability(
                    f"card capability {key_text!r} is declared but not supported by "
                    "this build; refusing to project a specialist that cannot honor it"
                )
        else:
            raise UnsupportedCapability(
                f"unknown card capability {key_text!r}; refusing to guess its semantics"
            )
    return RemoteCapabilities(
        tools=_text_tuple(raw.get("tools"), field="tools"),
        skills=_skills(raw.get("skills")),
        input_modes=_modalities(raw, modern_key="defaultInputModes", legacy_key="inputModes"),
        output_modes=_modalities(raw, modern_key="defaultOutputModes", legacy_key="outputModes"),
        streaming=streaming,
    )


def _slugify(name: str) -> str:
    """A stable id from the card name when the card carries no explicit id."""
    slug = ""
    for char in name.lower():
        slug += char if char.isalnum() else "-"
    return slug.strip("-")


def parse_remote_card(payload: Mapping[str, Any] | str) -> RemoteAgentDescriptor:
    """Parse an external Agent descriptor payload (A2A-style card, where applicable).

    Pure: never contacts the endpoint. Raises:

    * :class:`DescriptorInvalid` — malformed payload or missing required fields;
    * :class:`UnsupportedCapability` — the card declares capability semantics
      this build cannot honor.
    """
    raw = _payload_mapping(payload)
    name = _required_text(raw, "name")
    version = _required_text(raw, "version")
    endpoint_url = _required_text(raw, "url")
    provider = raw.get("provider")
    publisher = ""
    if isinstance(provider, Mapping):
        organization = provider.get("organization", "")
        if not isinstance(organization, str):
            raise DescriptorInvalid(
                f"descriptor field 'provider.organization' must be a string, "
                f"got {type(organization).__name__}"
            )
        publisher = organization.strip()
    explicit_id = raw.get("id")
    agent_id = (
        explicit_id.strip()
        if isinstance(explicit_id, str) and explicit_id.strip()
        else _slugify(name)
    )
    if not agent_id:
        raise DescriptorInvalid(f"cannot derive an agent id from card name {name!r}")
    return RemoteAgentDescriptor(
        agent_id=agent_id,
        name=name,
        description=str(raw.get("description", "")).strip(),
        version=version,
        protocol_version=str(raw.get("protocolVersion", "1.0")).strip() or "1.0",
        endpoint_url=endpoint_url,
        publisher=publisher or "unknown",
        capabilities=_parse_capabilities(raw),
    )


class ExternalAgentRegistry:
    """Registers, inspects, refreshes, and projects external Agent descriptors.

    The registry is the discovery boundary: descriptors come in as payloads
    (already fetched by the operator or an upstream fetcher), are parsed and
    snapshotted with provenance, and are projected to canonical specialists
    only through the injected :class:`ProjectionPolicy`. It never invokes a
    remote agent — that is delegation (M9-D2), not discovery.

    M1 product-local projection: Agent

    This is not a second Agent-definition authority: the canonical Agent
    model stays owned by ``maistro.agents``. The registry holds only
    remote-descriptor snapshots keyed by their external agent id and renders
    them as provisional specialists through the injected policy; every
    projected card is clamped (no workspace root, no delegation, external
    scope) so a remote card can never mint canonical authority.
    """

    def __init__(
        self,
        *,
        policy: ProjectionPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy: ProjectionPolicy = (
            policy if policy is not None else DefaultDenyProjectionPolicy()
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: dict[str, RegisteredExternalAgent] = {}

    def register(
        self,
        payload: Mapping[str, Any] | str,
        *,
        source_url: str = "",
        active: bool = True,
    ) -> RegisteredExternalAgent:
        """Ingest and register a descriptor payload.

        Idempotent for the identical payload; changed bytes for a registered
        id must go through :meth:`refresh_descriptor`. Raises :class:`EndpointConflict`
        when the id is already registered against a different endpoint.
        """
        descriptor = parse_remote_card(payload)
        digest = payload_digest(payload)
        existing = self._records.get(descriptor.agent_id)
        if existing is not None:
            if existing.provenance.payload_sha256 == digest:
                return existing
            if existing.descriptor.endpoint_url != descriptor.endpoint_url:
                raise EndpointConflict(
                    f"agent id {descriptor.agent_id!r} is already registered against "
                    f"{existing.descriptor.endpoint_url!r}; re-pointing it at "
                    f"{descriptor.endpoint_url!r} is a lifecycle decision, not an overwrite"
                )
            raise DescriptorAlreadyRegistered(
                f"agent id {descriptor.agent_id!r} already holds different bytes; "
                "changed descriptors go through refresh_descriptor() so policy can evaluate them"
            )
        record = self._build_record(descriptor, source_url=source_url, digest=digest, active=active)
        self._records[descriptor.agent_id] = record
        return record

    def refresh_descriptor(
        self,
        agent_id: str,
        payload: Mapping[str, Any] | str,
        *,
        source_url: str = "",
    ) -> RegisteredExternalAgent:
        """Refresh a registered descriptor from new bytes.

        A candidate that re-identifies itself (a card whose explicit ``id`` or
        name-derived slug differs from ``agent_id``) is refused with
        :class:`DescriptorIdentityMismatch` — identity changes are a lifecycle
        decision, not a refresh. A candidate that stays within the current
        declared surface is accepted and re-authorized (policy evaluation runs
        on every refresh). A broadening candidate is accepted only when the
        policy approves it; otherwise :class:`AuthorityEscalationRefused` — a
        refresh can never silently widen what the remote can do.
        """
        current = self._lookup(agent_id)
        candidate = parse_remote_card(payload)
        if candidate.agent_id != agent_id:
            raise DescriptorIdentityMismatch(
                f"refresh for {agent_id!r} carries card id {candidate.agent_id!r}; "
                "identity changes are a lifecycle decision, not a refresh"
            )
        if candidate.endpoint_url != current.descriptor.endpoint_url:
            raise EndpointConflict(
                f"refresh for {agent_id!r} names endpoint {candidate.endpoint_url!r} "
                f"but the registration holds {current.descriptor.endpoint_url!r}"
            )
        digest = payload_digest(payload)
        if digest == current.provenance.payload_sha256:
            return current
        gained_surface = (
            candidate.capabilities.surface() - current.descriptor.capabilities.surface()
        )
        if gained_surface and not self._policy.allows_refresh(current.descriptor, candidate):
            raise AuthorityEscalationRefused(
                f"refresh for {agent_id!r} would add capability surface "
                f"{sorted(gained_surface)} and policy {self._policy.policy_id()!r} "
                "did not approve it"
            )
        record = self._build_record(
            candidate,
            source_url=source_url or current.provenance.source_url,
            digest=digest,
            active=current.active,
        )
        # Availability evidence belongs to the endpoint, not to this payload;
        # it is retained (with its probed_at stamp) rather than reset to
        # unknown, so staleness stays visible instead of silently vanishing.
        record = replace(record, availability=current.availability)
        self._records[agent_id] = record
        return record

    def report_availability(
        self, agent_id: str, *, available: bool, detail: str = ""
    ) -> Availability:
        """Record the latest probe result for the endpoint.

        The registry never probes by itself: availability claims come from the
        caller's health check and always carry their check time, so a stale
        claim is visible as stale rather than silently trusted.
        """
        current = self._lookup(agent_id)
        availability = Availability(
            state=AvailabilityState.AVAILABLE if available else AvailabilityState.UNAVAILABLE,
            detail=detail,
            probed_at=self._clock(),
        )
        self._records[agent_id] = replace(current, availability=availability)
        return availability

    def agents(self) -> tuple[str, ...]:
        """All registered external agent ids."""
        return tuple(self._records)

    def project(self, agent_id: str) -> SpecialistProjection:
        """Project one registered external Agent to canonical specialist metadata.

        Read-only inspection plus projection in one step — no invocation, no
        endpoint contact. Raises :class:`UnknownExternalAgent` when unregistered.
        """
        record = self._lookup(agent_id)
        return self._project(record)

    def eligible_specialists(self, *, require_available: bool = True) -> list[SpecialistProjection]:
        """Projections that may actually be delegated to, filtered truthfully.

        With ``require_available`` (the default) only authorized+active
        specialists whose latest probe reports *available* are returned; with
        ``require_available=False`` the authorized set is returned regardless
        of health, so a caller can see authorization and availability as the
        distinct axes they are.
        """
        projections = [self._project(record) for record in self._records.values()]
        if require_available:
            return [projection for projection in projections if projection.eligible]
        return [
            projection
            for projection in projections
            if projection.card.active and projection.authorization.authorized
        ]

    def _lookup(self, agent_id: str) -> RegisteredExternalAgent:
        record = self._records.get(agent_id)
        if record is None:
            raise UnknownExternalAgent(f"no external Agent registered under {agent_id!r}")
        return record

    def _build_record(
        self,
        descriptor: RemoteAgentDescriptor,
        *,
        source_url: str,
        digest: str,
        active: bool,
    ) -> RegisteredExternalAgent:
        now = self._clock()
        return RegisteredExternalAgent(
            descriptor=descriptor,
            provenance=DescriptorProvenance(
                source_url=source_url,
                payload_sha256=digest,
                ingested_at=now,
                publisher=descriptor.publisher,
                protocol_version=descriptor.protocol_version,
                remote_version=descriptor.version,
            ),
            # The card never authorizes itself: every grant comes from the policy —
            # clamped to the declared surface before storage, so the record (and
            # every projection/serialization derived from it) can never claim a
            # capability the descriptor does not declare, whatever a policy returns.
            authorization=self._effective_authorization(descriptor, now=now),
            availability=Availability(),
            active=active,
        )

    def _effective_authorization(
        self, descriptor: RemoteAgentDescriptor, *, now: datetime
    ) -> CapabilityAuthorization:
        """The policy's decision, clamped to the declared capability surface.

        The policy decides *which declared* capabilities are granted; it can
        never widen what the descriptor declares. Grants outside
        ``descriptor.capabilities.surface()`` are dropped here — centrally, at
        the single point where records are built — and ``authorized`` is
        derived from the effective grant, so a policy whose grants all fall
        outside the surface cannot mark a specialist eligible.
        """
        raw = self._policy.authorize(descriptor, now=now)
        effective = frozenset(raw.capabilities & descriptor.capabilities.surface())
        return replace(
            raw,
            authorized=raw.authorized and bool(effective),
            capabilities=effective,
        )

    def _project(self, record: RegisteredExternalAgent) -> SpecialistProjection:
        descriptor = record.descriptor
        return SpecialistProjection(
            card=self._project_card(record),
            descriptor=descriptor,
            provenance=record.provenance,
            authorization=record.authorization,
            availability=record.availability,
            declared_surface=descriptor.capabilities.surface(),
        )

    def _project_card(self, record: RegisteredExternalAgent) -> AgentCard:
        """The canonical card: clamped, and capped at the authorized subset."""
        descriptor = record.descriptor
        authorized = record.authorization.capabilities
        return AgentCard(
            id=descriptor.agent_id,
            name=descriptor.name,
            description=descriptor.description,
            version=descriptor.version,
            tools=tuple(
                name for name in descriptor.capabilities.tools if f"tool:{name}" in authorized
            ),
            skills=tuple(
                name for name in descriptor.capabilities.skills if f"skill:{name}" in authorized
            ),
            trust_tier=EXTERNAL_TRUST_TIER,
            priority_tier=EXTERNAL_PRIORITY_TIER,
            delegation_mode="none",
            sub_agents=(),
            model="auto",
            active=record.active and record.authorization.authorized,
            scope="external",
            user_id="",
        )
