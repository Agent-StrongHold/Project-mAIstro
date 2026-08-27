"""Environment-backed settings for Hive Conductor backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
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


class Settings(BaseSettings):
    """Load from process env and `.env` (backend dir, then repo root)."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
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
