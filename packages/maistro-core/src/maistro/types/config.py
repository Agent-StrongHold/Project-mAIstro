"""Configuration types.

Pydantic-validated config loaded from YAML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from maistro.memory.exposure import MemoryExposureMode


class RoutingConfig(BaseModel):
    """Model routing parameters."""

    quality_weight: float = 0.6
    cost_weight: float = 0.4
    reserve_pct: float = 0.05
    priority_multipliers: dict[str, float] = Field(
        default_factory=lambda: {
            "P0": 1.5,
            "P1": 1.2,
            "P2": 1.0,
            "P3": 0.9,
            "P4": 0.8,
            "P5": 0.7,
        }
    )


class TaskTypeConfig(BaseModel):
    """Configuration for a single task type."""

    keywords: list[str] = Field(default_factory=list)
    min_tier: str = "small"
    preferred_strengths: list[str] = Field(default_factory=lambda: ["chat"])


class SessionsConfig(BaseModel):
    """Session memory configuration."""

    max_messages: int = 20
    ttl_seconds: int = 86400


class LearningsConfig(BaseModel):
    """Learning-store knobs: RCA gating + promotion threshold."""

    rca_enabled: bool = True
    rca_model: str = ""
    promotion_threshold: int = 5


class MemoryConfig(BaseModel):
    """Deployment-level memory posture (ADR-057 / SPEC-062126-6a31).

    ``exposure_mode`` is the declaration the write-authority gate requires: the
    container passes it to every memory store it builds, and a store that
    receives none refuses to mutate at all (the store-level default is ``None``
    — fail-closed — so bypassing this config never silently inherits a mode).

    The config-level default is ``AGENT_MANAGED``: that is the engine's existing
    posture, declared here explicitly rather than inherited silently — the same
    move SPEC-062126-6a31 made for maistro-turing's recipes. A curated-context
    deployment sets ``system_managed`` and the agent loop loses all memory
    write and promotion authority at the store boundary.
    """

    exposure_mode: MemoryExposureMode = MemoryExposureMode.AGENT_MANAGED


class SecurityConfig(BaseModel):
    """Security configuration."""

    warden_enabled: bool = True
    gate_query_improve: bool = True
    gate_model: str = "auto"

    @field_validator("warden_enabled")
    @classmethod
    def _refuse_to_pretend_to_disable(cls, value: bool) -> bool:
        """Inert despite living on the config `create_container` receives.

        Nothing reads it, so `warden_enabled=False` silently leaves every
        trust boundary scanning. Refuse the weakening value rather than let
        an operator believe they turned scanning off.
        """
        if not value:
            msg = (
                "warden_enabled=False is not implemented — nothing reads this field, "
                "and Warden scans at every trust boundary regardless. Remove the "
                "setting rather than relying on it to turn protection off."
            )
            raise ValueError(msg)
        return value

    # Selects a maistro.security.permission_policy.PERMISSION_PRESETS entry.
    # Deliberately "none" (empty table) at shipped defaults. Under the
    # fail-closed default (ADR-072726-0d6b, implemented for #1165) an empty
    # table DENIES every permission-table lookup, so a deployment that wants
    # tool authority must configure it explicitly here (preset or
    # permissions) -- the previous allow-all-on-empty posture is gone and can
    # no longer be armed by omission. Tracked in the security remediation
    # backlog history for the original armable-not-armed decision.
    permission_preset: str = "none"
    # Explicit tool_name -> [role, ...] overrides, applied on top of the preset.
    permissions: dict[str, list[str]] = Field(default_factory=dict)
    # Defaults False: no admin unlock path exists yet for the 3-strike ladder
    # (InMemoryStrikeTracker.unlock()/.enable() have no HTTP route, CLI
    # command, or admin surface) -- enabling this can lock an owner out of
    # their own homelab instance with no recovery short of a process restart.
    strike_tracking_enabled: bool = False


class CORSConfig(BaseModel):
    """CORS configuration for browser-based clients."""

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3200"])
    allowed_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    allowed_headers: list[str] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
        ]
    )
    allow_credentials: bool = True


class RateLimitConfig(BaseModel):
    """Per-user rate limiting configuration."""

    requests_per_minute: int = 300
    burst_limit: int = 50
    enabled: bool = True


class AuthConfig(BaseModel):
    """Authentication provider configuration."""

    jwt_secret: str = ""
    jwks_url: str = ""
    issuer: str = ""
    audience: str = ""
    client_id: str = ""
    client_secret: str = ""
    authorization_url: str = ""
    token_url: str = ""
    session_cookie_name: str = "maistro_session"
    session_max_age: int = 3600


class ModelBindingConfig(BaseModel):
    """Operator-declared authorization for the canonical ``model.chat`` capability.

    This is authorization/configuration, not a credential container. A blank
    ``workspace_id`` inherits the deployment's canonical ``AgentConfig.workspace_id``;
    ``project_id`` and ``binding_id`` remain explicit so a Graph cannot authorize
    itself merely by choosing a model name. ``provider_name`` is the canonical
    Binding pin used by model routing and may be blank to allow normal router
    selection.
    """

    binding_id: str
    project_id: str
    workspace_id: str = ""
    node_id: str = ""
    provider_name: str = ""
    # Operator kill-switch carried onto the registered Binding: a declared
    # Binding can be disabled without deleting it, and resolution then refuses
    # instead of authorizing (#56).
    disabled: bool = False
    credential_refs: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()

    @field_validator("binding_id", "project_id")
    @classmethod
    def _require_scope_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model Binding identity/scope fields must be non-empty")
        return value

    @field_validator("credential_refs", "policy_refs")
    @classmethod
    def _reject_empty_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not ref.strip() for ref in value):
            raise ValueError("model Binding refs cannot contain empty values")
        return value


class AdapterInstanceConfig(BaseModel):
    """Operator-declared wiring for one registered provider adapter (M9-E1).

    This is deployment configuration, never adapter-package configuration: the
    adapter package declares *that* it needs a credential and under which
    logical reference; only the operator's own configuration supplies the
    secret material (``adapter_key``), and it is provisioned into the scoped
    credential router, not stored on the adapter or the Binding.
    """

    adapter_id: str
    binding_id: str
    project_id: str
    workspace_id: str = ""
    provider_name: str = ""
    disabled: bool = False
    adapter_key: str = ""
    credential_refs: tuple[str, ...] = ()
    probe_health_at_boot: bool = False

    @field_validator("adapter_id", "binding_id", "project_id")
    @classmethod
    def _require_adapter_scope_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("adapter wiring identity/scope fields must be non-empty")
        return value

    @field_validator("credential_refs")
    @classmethod
    def _reject_empty_adapter_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not ref.strip() for ref in value):
            raise ValueError("adapter wiring credential refs cannot be empty")
        return value


if TYPE_CHECKING:

    def _vulture_pydantic_contract_usage() -> None:
        """Keep reflection-owned Pydantic surface visible to production-only Vulture scans."""
        _ = ModelBindingConfig._require_scope_identity
        _ = ModelBindingConfig._reject_empty_refs
        _ = AdapterInstanceConfig._require_adapter_scope_identity
        _ = AdapterInstanceConfig._reject_empty_adapter_refs

    _ = _vulture_pydantic_contract_usage


class AgentConfig(BaseModel):
    """Root configuration. Validated at startup."""

    providers: dict[str, dict[str, object]] = Field(default_factory=dict)
    models: dict[str, dict[str, object]] = Field(default_factory=dict)
    task_types: dict[str, TaskTypeConfig] = Field(default_factory=dict)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    learnings: LearningsConfig = Field(default_factory=LearningsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    model_groups: dict[str, dict[str, object]] = Field(default_factory=dict)
    # Explicit canonical model authorizations loaded by create_container (#1079).
    # Empty by default: configuring a Provider/model does not itself grant any
    # Workspace/Project the right to invoke it.
    model_bindings: list[ModelBindingConfig] = Field(default_factory=list)
    # Operator wiring for registered provider-adapter packages (M9-E1, #961).
    # Empty by default: a deployment with no adapter configuration routes every
    # model through the shipped gateway exactly as before the SDK existed.
    provider_adapters: list[AdapterInstanceConfig] = Field(default_factory=list)
    database_url: str = ""
    # The Workspace this instance admits work into (#41). Core keeps the soft
    # scope axes only (ADR-019/ADR-068), and a single-instance deployment is one
    # Workspace — hard tenancy is Stronghold's, which supplies its own value per
    # tenant rather than inheriting this default.
    workspace_id: str = "default"
    # Where cold records live (ADR-082226-f436). Empty means no archive tier at
    # all, which is the default and not a degraded mode. `file:///path`,
    # `s3://bucket`, or `s3+http(s)://bucket?endpoint=host:port`. Never
    # credentials — those resolve through the vault (SPEC-011).
    archive_url: str = ""
    redis_url: str = ""
    agents_dir: str = ""
    provider_config_path: str = ""
    litellm_url: str = "http://litellm:4000"
    litellm_key: str = ""
    router_api_key: str = ""
    jwt_secret: str = ""
    phoenix_endpoint: str = ""

    cors_origins: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = 1_048_576
    webhook_secret: str = ""
    cache_breakpoints_enabled: bool = False


# ── Backwards compat aliases ─────────────────────────────────────
#
# `AgentConfig` is the canonical name. This alias exists so pre-consolidation
# importers keep working; new code must not use it. Marked here because an
# unlabelled alias reads as a second canonical name to anyone opening this file
# — the shape #36's sixth invariant exists to prevent. `types/errors.py` carries
# the same banner over its own aliases.

MaistroConfig = AgentConfig
