"""Configuration types.

Pydantic-validated config loaded from YAML.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
    # Deliberately "none" (empty table = permissive) at shipped defaults: the
    # "armable, not armed" posture is an ADR-backed design decision
    # (ADR-072726-0d6b), not an oversight. Arming a preset by default risks
    # locking a single-user homelab owner out of their own dangerous tools;
    # do it explicitly per that ADR's preconditions. Tracked in
    # docs/audit/SECURITY-REMEDIATION-BACKLOG.md.
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


class AgentConfig(BaseModel):
    """Root configuration. Validated at startup."""

    providers: dict[str, dict[str, object]] = Field(default_factory=dict)
    models: dict[str, dict[str, object]] = Field(default_factory=dict)
    task_types: dict[str, TaskTypeConfig] = Field(default_factory=dict)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    learnings: LearningsConfig = Field(default_factory=LearningsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    model_groups: dict[str, dict[str, object]] = Field(default_factory=dict)
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
