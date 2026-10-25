"""Config loader: YAML file -> validated MaistroYamlConfig with env overrides."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from maistro.config.database import resolve_database_url
from maistro.config.settings import MaistroYamlConfig, set_yaml_config, validate_cors_origins

logger = logging.getLogger(__name__)


def _validate_url_not_private(url: str, field_name: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        msg = f"{field_name} must use HTTPS scheme, got {parsed.scheme!r}: {url}"
        raise ValueError(msg)

    hostname = parsed.hostname
    if not hostname:
        msg = f"{field_name} has no hostname: {url}"
        raise ValueError(msg)

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        logger.warning(
            "%s hostname %r could not be resolved — "
            "skipping private-IP check (will be enforced at connect time)",
            field_name,
            hostname,
        )
        return

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            msg = f"{field_name} resolves to private/loopback/link-local address {ip_str}: {url}"
            raise ValueError(msg)


def _load_raw_yaml(config_path: Path) -> dict[str, Any]:
    """Read + parse the YAML config file, returning {} if it does not exist."""
    if not config_path.exists():
        return {}
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in {config_path}: {e}"
        raise ValueError(msg) from e


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, str | None]:
    """Overlay top-level secret/URL env vars onto ``raw``. Returns the override map."""
    env_overrides: dict[str, str | None] = {
        # Not a bare `os.getenv("DATABASE_URL")`: the resolver also composes
        # one from `DB_*` when `DATABASE_URL` is unset, which is what stops
        # alembic and the container from targeting different databases (#187).
        # `or None` preserves the "no override" contract of this map -- an
        # unresolvable database leaves whatever the YAML said.
        "database_url": resolve_database_url() or None,
        "litellm_url": os.getenv("LITELLM_URL"),
        "litellm_key": os.getenv("LITELLM_MASTER_KEY"),
        "router_api_key": os.getenv("ROUTER_API_KEY"),
        "jwt_secret": os.getenv("JWT_SECRET"),
        "phoenix_endpoint": os.getenv("PHOENIX_COLLECTOR_ENDPOINT"),
        "webhook_secret": os.getenv("MAISTRO_WEBHOOK_SECRET"),
    }
    for key, val in env_overrides.items():
        if val is not None:
            raw[key] = val
    return env_overrides


def _validate_secrets(env_overrides: dict[str, str | None]) -> None:
    """Enforce minimum-length rules on secret env vars."""
    router_key = env_overrides.get("router_api_key")
    if router_key and len(router_key) < 32:
        logger.warning(
            "ROUTER_API_KEY is shorter than 32 characters (%d) — "
            "this is insecure and may be rejected in a future version",
            len(router_key),
        )

    jwt_secret = env_overrides.get("jwt_secret")
    if jwt_secret and len(jwt_secret) < 32:
        msg = f"JWT_SECRET must be at least 32 characters, got {len(jwt_secret)}"
        raise ValueError(msg)

    webhook_secret = env_overrides.get("webhook_secret")
    if webhook_secret and len(webhook_secret) < 16:
        msg = f"MAISTRO_WEBHOOK_SECRET must be at least 16 characters, got {len(webhook_secret)}"
        raise ValueError(msg)


def _apply_cors_and_limits(raw: dict[str, Any]) -> None:
    """Validate + apply CORS origins and request-limit env vars onto ``raw``."""
    cors_origins = os.getenv("MAISTRO_CORS_ORIGINS")
    if cors_origins:
        # Same validator the live `Settings.cors_origins` path uses — one
        # implementation, so the two paths cannot drift apart again.
        origins = validate_cors_origins(cors_origins.split(","))
        raw.setdefault("cors", {})["allowed_origins"] = origins

    rate_limit_rpm = os.getenv("MAISTRO_RATE_LIMIT_RPM")
    if rate_limit_rpm:
        raw.setdefault("rate_limit", {})["requests_per_minute"] = int(rate_limit_rpm)

    max_body = os.getenv("MAISTRO_MAX_REQUEST_BODY_BYTES")
    if max_body:
        raw["max_request_body_bytes"] = int(max_body)


def _apply_auth_env(raw: dict[str, Any]) -> None:
    """Validate + apply OAuth/JWKS auth env vars onto ``raw``."""
    # (env var, auth-config key, whether the URL must not be private)
    auth_url_vars = (
        ("MAISTRO_JWKS_URL", "jwks_url", True),
        ("MAISTRO_AUTH_ISSUER", "issuer", True),
        ("MAISTRO_AUTH_AUDIENCE", "audience", False),
        ("MAISTRO_AUTH_CLIENT_ID", "client_id", False),
        ("MAISTRO_AUTH_AUTHORIZATION_URL", "authorization_url", True),
        ("MAISTRO_AUTH_TOKEN_URL", "token_url", True),
        ("MAISTRO_AUTH_CLIENT_SECRET", "client_secret", False),
    )
    for env_name, config_key, must_be_public in auth_url_vars:
        value = os.getenv(env_name)
        if not value:
            continue
        if must_be_public:
            _validate_url_not_private(value, env_name)
        raw.setdefault("auth", {})[config_key] = value


def load_yaml_config(path: str | Path | None = None) -> MaistroYamlConfig:
    config_path = path or os.getenv("MAISTRO_CONFIG", "config/maistro.yaml")
    config_path = Path(str(config_path))

    raw = _load_raw_yaml(config_path)

    env_overrides = _apply_env_overrides(raw)
    _validate_secrets(env_overrides)
    _apply_cors_and_limits(raw)
    _apply_auth_env(raw)

    config = MaistroYamlConfig(**raw)
    set_yaml_config(config)
    return config
