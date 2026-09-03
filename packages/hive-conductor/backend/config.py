"""Environment-backed settings for Hive Conductor backend."""

from __future__ import annotations

import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from maistro.config.settings import validate_cors_origins

_BACKEND_DIR = Path(__file__).resolve().parent
# Repo root `.env` (PM POC flags) — uvicorn cwd is usually `backend/`.
_ENV_FILES: tuple[str, ...] = tuple(
    str(p)
    for p in (
        _BACKEND_DIR / ".env",
        _BACKEND_DIR.parent.parent.parent / ".env",
        Path.cwd() / ".env",
    )
    if p.is_file()
)

_OAUTH_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_OAUTH_SCOPE_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


def is_valid_oauth_provider_name(value: str) -> bool:
    """Return whether ``value`` is the canonical provider URL slug."""
    return bool(_OAUTH_PROVIDER_RE.fullmatch(value))


def _https_url(value: str, *, field_name: str, origin_only: bool = False) -> str:
    candidate = value.strip()
    if len(candidate) > 2048 or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise ValueError(f"{field_name} has an invalid length or control character")
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid URL") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{field_name} must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError(f"{field_name} must not contain credentials or a fragment")
    if parsed.query:
        raise ValueError(f"{field_name} must not contain a query")
    if origin_only and parsed.path not in ("", "/"):
        raise ValueError(f"{field_name} must be an HTTPS origin without a path or query")
    return candidate.rstrip("/") if origin_only else candidate


class OAuthProviderSettings(BaseModel):
    """Validated non-secret configuration for one OIDC login provider.

    A provider either names its four endpoint URLs explicitly (the generic
    OIDC contract) or names exactly one ``entra_tenant_id`` and derives every
    endpoint from Microsoft's tenant-specific v2 endpoints. Mixing the two
    would let a drifted URL quietly disagree with the tenant the verifier
    admits, so the combination is refused rather than resolved.
    """

    # SECURITY-REVIEW: Environment JSON is an external deserialization
    # boundary; unknown fields and input-bearing validation errors are refused.
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    authorization_url: str | None = None
    token_url: str | None = None
    client_id: str = Field(min_length=1, max_length=256)
    jwks_url: str | None = None
    issuer: str | None = None
    userinfo_url: str | None = None
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    client_secret_vault_key: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{0,127}$",
    )
    # One concrete Entra directory UUID. ``common`` / ``organizations`` and
    # every other multi-tenant alias are non-UUID strings and are rejected
    # here, before any token is accepted (#491 tenant admission).
    entra_tenant_id: str | None = None

    @field_validator("authorization_url", "token_url", "jwks_url", "issuer", "userinfo_url")
    @classmethod
    def validate_provider_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        field_name = info.field_name or "OAuth provider URL"
        return _https_url(value, field_name=field_name)

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str) -> str:
        client_id = value.strip()
        if not client_id:
            raise ValueError("client_id must not be blank")
        return client_id

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > 16:
            raise ValueError("scopes must contain between 1 and 16 entries")
        if "openid" not in value:
            raise ValueError("scopes must include openid for verified OIDC login")
        if len(set(value)) != len(value) or any(not _OAUTH_SCOPE_RE.fullmatch(v) for v in value):
            raise ValueError("scopes must be unique OAuth scope tokens")
        return value

    @field_validator("entra_tenant_id")
    @classmethod
    def validate_entra_tenant_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            # Canonical lowercase: alternate spellings of one directory must
            # not configure (or link) as two different tenants.
            return str(uuid.UUID(value.strip()))
        except ValueError as exc:
            raise ValueError(
                "entra_tenant_id must be one concrete directory UUID; multi-tenant "
                "aliases such as 'common' or 'organizations' are not admitted"
            ) from exc

    @model_validator(mode="after")
    def endpoints_are_explicit_or_entra_derived(self) -> OAuthProviderSettings:
        explicit = (self.authorization_url, self.token_url, self.jwks_url, self.issuer)
        if self.entra_tenant_id is not None:
            if any(url is not None for url in explicit):
                raise ValueError(
                    "entra_tenant_id derives all endpoints; do not also set "
                    "authorization_url, token_url, jwks_url, or issuer"
                )
            return self
        if any(url is None for url in explicit):
            raise ValueError(
                "authorization_url, token_url, jwks_url, and issuer are required "
                "unless entra_tenant_id derives them"
            )
        return self


class Settings(BaseSettings):
    """Load from process env and `.env` (backend dir, then repo root)."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    # One canonical gateway field, with every deployment spelling accepted at
    # the settings boundary. Code below this layer must not inspect the alias
    # environment variables independently or the outbound SSRF allowance and
    # the request destination can disagree (#285).
    litellm_api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "litellm_api_base",
            "LITELLM_API_BASE",
            "LITELLM_PROXY_URL",
            "LITELLM_BASE_URL",
            "LITELLM_URL",
            "maistro_llm_base_url",
            "MAISTRO_LLM_BASE_URL",
        ),
    )
    litellm_api_key: SecretStr | None = None
    # Must exist in litellm_config.yaml; compose passes CHAT_DEFAULT_MODEL with
    # the same value. setup.py's first-run fallback reads this field — change it
    # here, not there. (The old cerebras- alias was not in the gateway config.)
    chat_default_model: str = "gemini/gemini-2.5-flash"
    llm_http_variant: Literal["auto", "responses", "chat_completions"] = "auto"

    # F3 (loud degraded modes): with no LLM gateway configured the graph runner
    # refuses to run rather than handing back a success-shaped stub answer.
    # Set ALLOW_STUB_LLM=true to opt in to stub responses — they are then
    # labelled `"stub": true` in the payload so nothing downstream can mistake
    # one for a real result (same noise flag maistro-evolve uses,
    # SPEC-202 signal honesty). Same vocabulary as `maistro-rsi --allow-stub-llm`.
    allow_stub_llm: bool = False

    maistro_router_api_key: str | None = None
    # The Workspace a submission that names none lands in (#158). Passed
    # explicitly into `AgentConfig.workspace_id` rather than left to core's own
    # default, so "which Workspace did this Run go to" has one answer this
    # deployment states, not two that happen to agree.
    hive_default_workspace_id: str = "default"
    maistro_agents_dir: str = "agents"
    maistro_llm_api_key: SecretStr | None = None
    maistro_model: str = "mistral-large"

    conductor_data_dir: str = "~/.conductor"
    conductor_vault_path: str | None = None
    conductor_identity_path: str | None = None
    conductor_state_db: str | None = None
    conductor_admin_public_key: str | None = None
    conductor_user_public_key: str | None = None

    # A voice satellite is a device, not a person, so it holds a service
    # credential rather than a session. Both fields are required before
    # /v1/voice/ answers at all: the prefix used to skip authentication
    # entirely, and an unset key must never be what makes a route public
    # (#316). The key resolves through the vault first (SPEC-003), so
    # rotating it takes effect on the next call rather than the next restart.
    voice_service_key: SecretStr | None = None
    voice_service_account: str | None = None

    # Serve the Content-Security-Policy under the report-only header instead of
    # enforcing it (#310). The rollout instrument, not a weaker setting: the
    # browser evaluates the same policy and reports what it would have blocked.
    # Off by default, because a report-only policy nobody promotes is a header
    # that protects nothing while looking like it does.
    csp_report_only: bool = False

    # Open Design renderer plugin (SPEC-070426-6ea8). Off by default; when enabled the
    # design service registers the provider and /design/skills gains web/video skills.
    open_design_enabled: bool = False
    open_design_url: str = "http://127.0.0.1:7456"
    open_design_token: SecretStr | None = None

    # CORS allow-list. Defaults to local-dev origins; set CORS_ORIGINS (JSON list)
    # in deployment.
    #
    # This is the field `main.py` hands to CORSMiddleware — alongside
    # allow_credentials=True and allow_methods/allow_headers of ["*"] — so it
    # is the most exposed CORS surface in the repo, and it is validated by the
    # same `validate_cors_origins` the engine's own settings use. A comment
    # saying a wildcard "is rejected by browsers" used to stand in for that
    # check; it does not hold. Starlette answers wildcard-plus-credentials by
    # echoing the request's Origin back with
    # `Access-Control-Allow-Credentials: true`, so the browser accepts it and
    # any site can make credentialed cross-origin requests.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:8101",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8101",
    ]

    _check_cors_origins = field_validator("cors_origins")(validate_cors_origins)

    # Mark the session cookie Secure so browsers refuse to send it over plain
    # HTTP. **On by default** (#369). It used to default off, with the reason
    # given as the documented dev loop being http://localhost:8101 — where a
    # Secure cookie is silently dropped and login looks like it does nothing.
    #
    # That reason is real and it is an argument for a local-development escape,
    # not for the default. A default is the shape every deployment that did not
    # think about it takes, and "every deployment that did not think about it
    # sends its session cookie in the clear" is the wrong way round. The escape
    # is `allow_insecure_transport` below, which a local run sets deliberately
    # and a reviewer can grep for.
    session_cookie_secure: bool = True

    # `lax` lets the cookie ride a top-level navigation from another site,
    # which is what makes an emailed link to a Conductor page work. `strict`
    # would break that; `none` would send it on every cross-site subrequest and
    # is only meaningful with Secure, so it is not offered as a default.
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # OIDC human-login providers. This object contains public endpoints,
    # client ids, and an optional *vault key name* only. Client secrets are
    # deliberately not settings values and are resolved at exchange time.
    oauth_providers: dict[str, OAuthProviderSettings] = Field(default_factory=dict)
    oauth_public_origin: str | None = None
    oauth_success_path: str = "/"

    # Explicit human-login mode (#491): `local` keeps password login, `entra`
    # denies ordinary password login (Entra-only), `hybrid` allows both. The
    # route layer reads this through HumanAuthModePolicy instead of inferring
    # login availability from whether a provider happens to be configured, so
    # a misconfigured Entra-only deployment cannot silently fall back to
    # passwords. Break-glass recovery stays a distinct operator-controlled
    # seam, never a request parameter.
    human_auth_mode: Literal["local", "entra", "hybrid"] = "local"

    # The single, explicit, greppable local-development escape. Startup refuses
    # a Secure-disabled session cookie unless this is set — see
    # `maistro.security.transport.assert_session_transport_is_safe`.
    #
    # Deliberately its own flag rather than another value of
    # `session_cookie_secure`: turning off a security control and declaring a
    # development run are different statements, and collapsing them into one
    # setting is how the first becomes invisible inside the second.
    allow_insecure_transport: bool = False

    # Addresses or CIDR blocks allowed to set `X-Forwarded-Proto`. Empty means
    # no forwarded header is believed from anyone, which is the safe default: a
    # deployment that forgets to name its proxy loses HSTS rather than gaining
    # a header any caller can forge (#369).
    trusted_proxy_ips: str = ""

    hardware_preset: Literal["potato", "laptop", "desktop", "beast"] = "laptop"
    poc_mode: str = ""
    maistro_base_url: str = "http://localhost:8000"
    # ADR-096: maistro-server is the canonical backend for production task
    # execution. "demo" is the only mode allowed to run an in-process
    # in-process LocalTaskBackend — see SPEC-226.
    hive_mode: Literal["production", "demo"] = "production"

    # Host-health API (:8150) backing the infra_monitor / infra_action capability
    # slots. Token is read from the vault (key HOST_HEALTH_TOKEN) with this env as
    # fallback. URL empty → infra providers are not wired (slots stay SAFE_NOOP).
    host_health_url: str | None = None
    host_health_token: SecretStr | None = None
    infra_autonomy: Literal["approve_all", "auto_safe", "detect_only"] = "auto_safe"
    # Directories an HTTP-initiated RSI run may target, os.pathsep-separated
    # (#305). Empty means no repository is authorized -- POST /v1/rsi/runs
    # refuses every path until an operator names one. The unset state has to be
    # the refusing one: this is the difference between "run the loop on our
    # checkout" and "run a command against any directory on the box".
    rsi_repo_roots: str = ""
    # Optional JSON file of extra RSI test profiles (name -> argv list). The
    # request names a profile; it never carries a command. A missing or
    # malformed file is an error rather than an empty overlay.
    rsi_test_profiles_file: str = ""

    # self_repair (SPEC-188) cadence; <=0 disables the periodic loop (API still works).
    self_repair_interval_s: int = 90

    # Episodic memory-decay cadence (SPEC-080126-9e42). This is what makes
    # README's "decays without reinforcement" and CLAUDE.md decision #5 true at
    # runtime — the decay primitives had no production caller before it (#344).
    # <=0 disables the driver, and per the F3 precedent that is a *loud* degraded
    # mode: startup logs a warning and /health reports `degraded: true` with
    # `memory_decay.state == "disabled"`. A silent off switch here would look
    # exactly like the bug this closes.
    memory_decay_interval_s: int = 3600

    @field_validator("oauth_providers")
    @classmethod
    def validate_oauth_provider_names(
        cls, value: dict[str, OAuthProviderSettings]
    ) -> dict[str, OAuthProviderSettings]:
        if len(value) > 16:
            raise ValueError("at most 16 OAuth providers may be configured")
        if any(not is_valid_oauth_provider_name(name) for name in value):
            raise ValueError("OAuth provider names must be lowercase URL-safe slugs")
        return value

    @field_validator("oauth_public_origin", mode="before")
    @classmethod
    def empty_oauth_public_origin_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("oauth_public_origin")
    @classmethod
    def validate_oauth_public_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _https_url(value, field_name="oauth_public_origin", origin_only=True)

    @field_validator("oauth_success_path")
    @classmethod
    def validate_oauth_success_path(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or any(ord(char) < 32 for char in value)
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("oauth_success_path must be one fixed local path")
        return value

    @model_validator(mode="after")
    def validate_oauth_wiring(self) -> Settings:
        if self.oauth_providers and self.oauth_public_origin is None:
            raise ValueError("oauth_public_origin is required when OAuth providers are configured")
        return self

    @property
    def maistro_llm_base_url(self) -> str | None:
        """Compatibility view of the canonical gateway endpoint.

        Older callers used a second settings field for the same OpenAI-
        compatible service. Keeping a read-only view avoids breaking those
        callers while ensuring every environment alias seeds one value.
        """
        return self.litellm_api_base


@lru_cache
def get_settings() -> Settings:
    return Settings()
