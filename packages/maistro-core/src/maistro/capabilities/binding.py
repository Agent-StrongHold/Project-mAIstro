"""Canonical consumer Binding and immutable resolved-provider snapshot.

A Binding records what capability a consumer is authorized/configured to use.
Provider resolution remains slot-specific so existing safety wrappers cannot be
bypassed. Each actual Invocation persists a :class:`ResolvedBinding` snapshot
showing the exact provider/configuration decision that was used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _id() -> str:
    return uuid4().hex


def _require(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


@runtime_checkable
class ResolvedCapabilityProvider(Protocol):
    """Metadata every slot-specific resolved provider exposes."""

    @property
    def name(self) -> str: ...

    @property
    def slot(self) -> str: ...

    @property
    def trust_tier(self) -> str: ...


class Binding(BaseModel):
    """Consumer-owned capability authorization/configuration.

    ``provider_name`` is optional. An empty value means normal provider
    selection/fallback policy applies. A non-empty value pins this Binding and
    must be honored by the slot-specific resolver before an Invocation starts.
    Secrets are never stored here; only credential references are allowed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(default_factory=_id)
    workspace_id: str
    project_id: str
    capability: str
    node_id: str = ""
    provider_name: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    credential_refs: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_binding(self) -> Binding:
        _require(self.binding_id, "binding_id")
        _require(self.workspace_id, "workspace_id")
        _require(self.project_id, "project_id")
        _require(self.capability, "capability")
        if any(not ref.strip() for ref in self.credential_refs):
            raise ValueError("credential_refs cannot contain empty values")
        if any(not ref.strip() for ref in self.policy_refs):
            raise ValueError("policy_refs cannot contain empty values")
        return self


class ResolvedBinding(BaseModel):
    """Immutable provider/configuration decision persisted with an Invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str
    capability: str
    provider_name: str
    provider_trust_tier: str
    config: dict[str, Any] = Field(default_factory=dict)
    credential_refs: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_resolved(self) -> ResolvedBinding:
        _require(self.binding_id, "binding_id")
        _require(self.capability, "capability")
        _require(self.provider_name, "provider_name")
        return self

    @classmethod
    def from_provider(
        cls,
        binding: Binding,
        provider: ResolvedCapabilityProvider,
    ) -> ResolvedBinding:
        """Capture a slot-specific resolution without creating a bypass path."""

        if provider.slot != binding.capability:
            raise ValueError(
                f"resolved provider slot {provider.slot!r} does not match "
                f"Binding capability {binding.capability!r}"
            )
        if binding.provider_name and provider.name != binding.provider_name:
            raise ValueError(
                f"Binding pins provider {binding.provider_name!r}, "
                f"but resolver selected {provider.name!r}"
            )
        return cls(
            binding_id=binding.binding_id,
            capability=binding.capability,
            provider_name=provider.name,
            provider_trust_tier=provider.trust_tier,
            config=binding.config,
            credential_refs=binding.credential_refs,
            policy_refs=binding.policy_refs,
        )


__all__ = ["Binding", "ResolvedBinding", "ResolvedCapabilityProvider"]
