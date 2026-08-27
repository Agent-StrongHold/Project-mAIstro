"""Application settings loaded from environment variables and optional YAML config."""

from __future__ import annotations

import functools
import logging
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from maistro.quota.rate_profile import LimitUnit, LimitWindow
from maistro.security.resource_policy import (
    BASELINE_CIRCUIT_FAILURE_THRESHOLD,
    BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
    BASELINE_MAX_REQUEST_BODY_BYTES,
    BASELINE_MAX_WEBHOOK_BODY_BYTES,
    BASELINE_RATE_LIMIT_BURST,
    BASELINE_RATE_LIMIT_PER_MINUTE,
    EffectiveResourcePolicy,
    validate_resource_policy,
)

logger = logging.getLogger(__name__)


def validate_cors_origins(origins: list[str]) -> list[str]:
    """Reject CORS origins that would defeat the browser's same-origin policy.

    Lives here rather than in ``config.loader`` because the loader is only one
    of two config paths, and not the one the servers read. Both paths call
    this so the guard cannot again end up on the door nobody uses.

    ``"*"`` is refused outright: every app pairs its origin list with
    ``allow_credentials=True``, and Starlette responds to a wildcard-plus-
    credentials config by echoing the request's ``Origin`` header back with
    ``Access-Control-Allow-Credentials: true`` — which lets any site on the
    internet make credentialed cross-origin requests.
    """
    cleaned: list[str] = []
    for raw in origins:
        origin = raw.strip()
        if not origin:
            continue
        if origin == "*":
            msg = (
                "CORS origins must not contain '*' — use exact origins. "
                "The apps send allow_credentials=True, so a wildcard makes every "
                "site a permitted credentialed origin."
            )
            raise ValueError(msg)
        if origin.lower() == "null":
            # Browsers serialize *opaque* origins as the literal string
            # "null": sandboxed iframes, file: pages, data: documents, and
            # some redirect chains all send `Origin: null`. Allowing it with
            # credentials grants every one of them credentialed access, and
            # they are mutually indistinguishable — there is no such thing as
            # trusting one opaque origin.
            msg = (
                "CORS origins must not contain 'null' — every sandboxed frame, "
                "file: page and data: document shares that origin, so allowing "
                "it grants them all credentialed access."
            )
            raise ValueError(msg)
        if origin.startswith("javascript:") or origin.startswith("data:"):
            msg = f"CORS origins contains unsafe origin: {origin!r}"
            raise ValueError(msg)
        if not origin.startswith("https://") and not origin.startswith("http://localhost"):
            logger.warning("CORS origin %r is not HTTPS — use HTTPS in production", origin)
        cleaned.append(origin)
    return cleaned


class RateConstraintConfig(BaseModel):
    """YAML-config counterpart of `quota.rate_profile.RateConstraint`."""

    unit: LimitUnit
    window: LimitWindow
    limit: int


class ModelRateProfileConfig(BaseModel):
    """YAML-config counterpart of `quota.rate_profile.ModelRateProfile`.

    `model` is matched against a model alias string (`models.toml`'s `alias`
    field, e.g. `"cerebras-qwen-3-235b-a22b-2507"`) by `config.rate_limits`'s
    resolver -- not a display name.
    """

    provider: str
    model: str
    constraints: list[RateConstraintConfig] = Field(default_factory=list)
    scope_key_fields: list[str] = Field(default_factory=lambda: ["provider", "model"])


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    name: str = "maistro"
    user: str = "maistro"
    password: str = "maistro"

    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle: int = 1800

    # asyncpg pool bounds, applied by `persistence.get_pool`. Distinct from
    # pool_size/max_overflow above, which are SQLAlchemy-shaped and unused by
    # the asyncpg path.
    asyncpg_min_size: int = 2
    asyncpg_max_size: int = 50

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_url(self) -> str:
        """Synchronous URL, used by Alembic (`alembic/env.py`).

        The driver is named explicitly. Bare `postgresql://` makes SQLAlchemy
        reach for psycopg2, which this project has never declared as a
        dependency — so `alembic upgrade head`, the schema-evolution path
        ADR-087 documents, failed with ModuleNotFoundError on any clean install.
        psycopg 3 is the maintained driver and is what the lock now carries.
        """
        return (
            f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        )


class LiteLLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LITELLM_")

    base_url: str = "http://localhost:4000"
    master_key: str = ""


class MistralSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MISTRAL_")

    # A separate Admin Console credential -- NOT the regular completions key
    # used for chat requests -- required by MistralAdminApiVerifier
    # (quota/verifiers/mistral.py). Optional: unset means that verifier is
    # unavailable/skipped rather than an error, since not every deployment
    # needs standalone balance verification.
    admin_api_key: str = ""


class LangfuseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_")

    host: str = "http://localhost:3000"
    public_key: str = ""
    secret_key: str = ""
    enabled: bool = True


class SandboxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOX_")

    image: str = "python:3.12-slim"
    memory_limit: str = "512m"
    cpu_count: int = 2
    timeout: int = 300
    network_disabled: bool = True
    readiness_required: bool = False
    # microVM backend (SPEC-190): Firecracker / Cloud-Hypervisor boot a kernel +
    # ext4 rootfs, NOT an OCI image, so these are separate from `image` (the
    # Docker ref). Using `image` as a VM rootfs would fail to boot.
    vm_kernel_image: str = "vmlinux"
    vm_rootfs_image: str = "rootfs.ext4"


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLLAMA_")

    base_url: str = "http://localhost:11434/v1"


class NtfySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NTFY_")

    base_url: str = ""
    default_topic: str = ""
    access_token: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "maistro-engine"
    debug: bool = False
    # The Workspace this instance admits work into (#41), mirroring
    # AgentConfig.workspace_id. One instance is one Workspace; hard tenancy is
    # Stronghold's (ADR-019/ADR-068).
    workspace_id: str = "default"
    # This is intentionally separate from ``debug``. Weakening a security
    # resource limit requires an explicit operator statement, not an incidental
    # development flag that another subsystem may set for unrelated reasons.
    allow_unsafe_resource_overrides: bool = False
    # Default to loopback so a careless dev-server start doesn't expose the
    # API on every interface. Container deployments override this via the
    # HOST env var (e.g. HOST=0.0.0.0 in docker-compose for the server svc).
    host: str = "127.0.0.1"
    port: int = 8000

    api_keys: list[str] = Field(default_factory=list, description="Valid API bearer tokens")
    require_auth: bool = Field(
        default=True,
        description="Refuse to start without API keys. Set REQUIRE_AUTH=false for local dev only.",
    )
    github_webhook_secret: str = ""
    ci_webhook_secret: str = ""
    require_webhook_secrets: bool = Field(
        default=False,
        description="Refuse to start unless both webhook secrets are set. Off by "
        "default because the webhook routes already reject unsigned requests; "
        "turn it on to convert a runtime 503 into a boot failure.",
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3080"],
        description="Allowed CORS origins. This is the field the FastAPI apps "
        "actually pass to CORSMiddleware — validated here, at the boundary "
        "that is read.",
    )

    _check_cors_origins = field_validator("cors_origins")(validate_cors_origins)

    default_model: str = "anthropic/claude-sonnet-4-20250514"

    max_tokens_per_task: int = Field(default=100_000, description="Max LLM tokens per task")

    ollama_base_url: str = "http://localhost:11434/v1"
    maistro_dry_run: bool = False
    poc_mode: str = Field(
        default="",
        description="POC mode: empty=engineering, pm=project-management fleet",
        validation_alias="MAISTRO_POC_MODE",
    )

    tier_1_model: str = ""
    tier_2_model: str = ""
    tier_3_model: str = ""
    tier_4_model: str = ""

    max_webhook_body_bytes: int = BASELINE_MAX_WEBHOOK_BODY_BYTES
    max_request_body_bytes: int = Field(
        default=BASELINE_MAX_REQUEST_BODY_BYTES,
        description="Global HTTP request body size limit enforced by PayloadSizeLimitMiddleware "
        "(distinct from max_webhook_body_bytes, which the webhook routes enforce specifically).",
    )

    rate_limit_per_minute: int = BASELINE_RATE_LIMIT_PER_MINUTE
    rate_limit_burst: int = BASELINE_RATE_LIMIT_BURST
    circuit_breaker_failure_threshold: int = BASELINE_CIRCUIT_FAILURE_THRESHOLD
    circuit_breaker_recovery_timeout_s: float = BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S

    # Shared outbound HTTP pool (see maistro.http). Ceilings against fd
    # exhaustion, NOT a load throttle — a small cap here was measured as the
    # worst option for interactive latency (chat p50 24.14s vs 2.03s).
    http_max_connections: int = 100
    http_max_keepalive_connections: int = 50
    http_keepalive_expiry_s: float = 30.0

    task_progress_webhook_url: str = Field(
        default="",
        description="Full URL for optional task progress POST (legacy conductor-router). Empty disables.",
    )
    task_progress_webhook_api_key: str = Field(
        default="",
        description="Bearer token sent with progress webhook requests when non-empty.",
    )

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    litellm: LiteLLMSettings = Field(default_factory=LiteLLMSettings)
    mistral: MistralSettings = Field(default_factory=MistralSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    ntfy: NtfySettings = Field(default_factory=NtfySettings)

    @model_validator(mode="after")
    def _enforce_resource_security_floors(self) -> Self:
        validate_resource_policy(self.effective_resource_policy())
        return self

    def effective_resource_policy(self) -> EffectiveResourcePolicy:
        """Expose the exact values enforced by runtime resource boundaries."""
        return EffectiveResourcePolicy(
            max_request_body_bytes=self.max_request_body_bytes,
            max_webhook_body_bytes=self.max_webhook_body_bytes,
            rate_limit_per_minute=self.rate_limit_per_minute,
            rate_limit_burst=self.rate_limit_burst,
            circuit_breaker_failure_threshold=self.circuit_breaker_failure_threshold,
            circuit_breaker_recovery_timeout_s=self.circuit_breaker_recovery_timeout_s,
            unsafe_overrides_enabled=self.allow_unsafe_resource_overrides,
        )


class RoutingConfig(BaseModel):
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
    keywords: list[str] = Field(default_factory=list)
    min_tier: str = "small"
    preferred_strengths: list[str] = Field(default_factory=lambda: ["chat"])


class SessionsConfig(BaseModel):
    max_messages: int = 20
    ttl_seconds: int = 86400


class LearningsConfig(BaseModel):
    rca_enabled: bool = True
    rca_model: str = ""
    promotion_threshold: int = 5


class SecurityConfig(BaseModel):
    warden_enabled: bool = True
    sentinel_enabled: bool = True
    gate_query_improve: bool = True
    gate_model: str = "auto"

    @field_validator("warden_enabled", "sentinel_enabled")
    @classmethod
    def _refuse_to_pretend_to_disable(cls, value: bool, info: Any) -> bool:
        """These read as off-switches but nothing consults them.

        Leaving that silent is the dangerous direction: an operator sets
        ``warden_enabled: false``, sees no error, and reasonably concludes
        scanning is off — while every trust boundary is still scanning. The
        opposite mistake is worse still, if someone later wires the field up
        as a real disable path. Refusing the weakening value keeps the config
        honest until the knob is actually implemented.
        """
        if not value:
            msg = (
                f"{info.field_name}=false is not implemented — nothing reads this field, "
                "and the subsystem stays on regardless. Remove the setting rather than "
                "relying on it to turn protection off."
            )
            raise ValueError(msg)
        return value

    # NOTE: permission_preset / permissions / strike_tracking_enabled are
    # deliberately NOT mirrored here. They live on maistro.types.config
    # SecurityConfig, which is what create_container actually receives.
    # Nothing reads MaistroYamlConfig.security -- the four fields above are
    # already declared-but-inert -- so adding security knobs here would ship
    # settings an operator could set in maistro.yaml and watch do nothing.
    # Wire MaistroYamlConfig -> AgentConfig first; then mirror them.


class CORSConfig(BaseModel):
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
    requests_per_minute: int = 300
    burst_limit: int = 50
    enabled: bool = True


class AuthConfig(BaseModel):
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


class MaistroYamlConfig(BaseModel):
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    models: dict[str, dict[str, Any]] = Field(default_factory=dict)
    task_types: dict[str, TaskTypeConfig] = Field(default_factory=dict)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    learnings: LearningsConfig = Field(default_factory=LearningsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    model_groups: dict[str, dict[str, Any]] = Field(default_factory=dict)
    permissions: dict[str, list[str]] = Field(default_factory=dict)
    rate_profiles: list[ModelRateProfileConfig] = Field(default_factory=list)
    database_url: str = ""
    redis_url: str = ""
    agents_dir: str = ""
    litellm_url: str = "http://litellm:4000"
    litellm_key: str = ""
    router_api_key: str = ""
    jwt_secret: str = ""
    phoenix_endpoint: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = 1_048_576
    webhook_secret: str = ""
    cache_breakpoints_enabled: bool = False


_yaml_config: MaistroYamlConfig | None = None


def get_yaml_config() -> MaistroYamlConfig | None:
    return _yaml_config


def set_yaml_config(cfg: MaistroYamlConfig | None) -> None:
    global _yaml_config
    _yaml_config = cfg


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
