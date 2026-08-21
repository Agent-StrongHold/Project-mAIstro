"""Validated install answers (v1) — shared by TTY, `--answers-file`, and HTTP plan API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SchemaVersion = Literal["1"]

InstallMode = Literal["preview", "apply"]
LlmGateway = Literal["litellm", "direct", "other"]
ObservabilityBackend = Literal["none", "langfuse_v2", "langfuse_v3", "arize"]
DeploymentTier = Literal["local_docker", "local_podman", "vm", "lxc", "proxmox", "bare_metal"]
ContainerRuntime = Literal["docker", "podman", "auto"]
UsersIntent = Literal["bootstrap_admin", "sso_later", "skip"]
StackBringup = Literal["none", "root_full"]
SandboxProfile = Literal["safe", "developer"]
InstallSurface = Literal["curl", "checkout"]
CryptoProfile = Literal["distributed_identity_root", "no_crypto", "full_all_crypto"]
DeliveryMode = Literal["image_pull", "source_build"]


class InstallAnswersV1(BaseModel):
    """Answers file / wizard payload. Do not store API keys here (names and flags only)."""

    schema_version: SchemaVersion = "1"
    install_mode: InstallMode = "preview"
    features: list[str] = Field(default_factory=list)
    compose_addons: list[str] = Field(default_factory=list)
    product: str | None = None
    dry_run: bool = True
    llm_gateway: LlmGateway = "litellm"
    observability_backend: ObservabilityBackend = "none"
    deployment_tier: DeploymentTier = "local_docker"
    container_runtime: ContainerRuntime = "auto"
    users_intent: UsersIntent = "skip"
    stack_bringup: StackBringup = "none"
    install_surface: InstallSurface = "curl"
    delivery_mode: DeliveryMode = "image_pull"
    sandbox_profile: SandboxProfile = "safe"
    crypto_profile: CryptoProfile = "distributed_identity_root"
    admin_user: str = "maistro-admin"
    daily_driver_user: str = "maistro-user"
    additional_users: list[str] = Field(default_factory=list)
    first_agents: list[str] = Field(default_factory=lambda: ["guide", "operator", "builder"])
    reactor_enabled: bool = True
    provider_accounts: dict[str, bool] = Field(
        default_factory=dict,
        description="Which cloud accounts the operator intends to use (no secrets).",
    )

    @field_validator(
        "features", "compose_addons", "additional_users", "first_agents", mode="before"
    )
    @classmethod
    def _coerce_str_lists(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("expected a list of strings")
        return [str(x) for x in v]

    @field_validator("provider_accounts", mode="before")
    @classmethod
    def _coerce_provider_accounts(cls, v: object) -> dict[str, bool]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("expected a mapping")
        out: dict[str, bool] = {}
        for k, val in v.items():
            out[str(k)] = bool(val)
        return out

    @field_validator("product", mode="before")
    @classmethod
    def _empty_product(cls, v: object) -> str | None:
        if v is None or v == "" or v == "none" or v == "null":
            return None
        return str(v)


def parse_answers_dict(data: dict[str, object]) -> InstallAnswersV1:
    """Parse and validate a YAML-loaded mapping."""
    return InstallAnswersV1.model_validate(data)


def merge_session_payload(data: dict[str, object]) -> InstallAnswersV1:
    """Merge partial JSON (e.g. from Hive draft wizard) with defaults; validates full answers."""
    defaults = InstallAnswersV1().model_dump(mode="json")
    merged: dict[str, object] = {**defaults}
    for key, val in data.items():
        if key == "provider_accounts" and isinstance(val, dict):
            base_pa = merged.get("provider_accounts")
            if isinstance(base_pa, dict):
                merged["provider_accounts"] = {**base_pa, **{str(k): v for k, v in val.items()}}
            else:
                merged["provider_accounts"] = val
        else:
            merged[key] = val
    return InstallAnswersV1.model_validate(merged)
