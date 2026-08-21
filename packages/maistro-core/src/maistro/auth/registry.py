"""Service key registry: load and validate service keys from YAML/env/dict."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from maistro.auth._types import ServiceIdentity, expand_scopes

logger = logging.getLogger("maistro.auth.registry")


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class ServiceKeyRegistry:
    """Registry of service keys. Loaded once at startup.

    Sources (in priority order):
      1. Direct dict via load_dict()
      2. YAML file via load_yaml() (path from SERVICE_KEYS_FILE env or explicit)
      3. Environment variables SERVICE_KEY_<NAME> (e.g. SERVICE_KEY_CONDUCTOR)
    """

    def __init__(self) -> None:
        self._services: dict[str, ServiceIdentity] = {}
        self._key_to_name: dict[str, str] = {}

    @property
    def services(self) -> dict[str, ServiceIdentity]:
        return dict(self._services)

    def _register_key(self, name: str, key: str) -> None:
        """Register key -> name, dropping any stale key(s) previously mapped to name."""
        stale = [k for k, n in self._key_to_name.items() if n == name and k != key]
        for k in stale:
            del self._key_to_name[k]
        self._key_to_name[key] = name

    def load_dict(self, data: dict[str, dict[str, Any]]) -> None:
        """Load from a dict: {service_name: {key: str, scopes: [str, ...]}}."""
        for name, cfg in data.items():
            key = cfg.get("key", "")
            if not key:
                logger.warning("Skipping service %s: no key", name)
                continue
            raw_scopes = cfg.get("scopes", [])
            scopes = expand_scopes(raw_scopes)
            identity = ServiceIdentity(
                name=name,
                key_hash=_hash_key(key),
                scopes=scopes,
            )
            self._services[name] = identity
            self._register_key(name, key)
            logger.info("Registered service %s with %d scopes", name, len(scopes))

    def load_yaml(self, path: str | Path) -> None:
        """Load from a YAML file with top-level 'services' key.

        Never raises — malformed YAML or a malshaped 'services' value is logged
        and skipped, matching discover_into's resilience philosophy.
        """
        path = Path(path)
        if not path.exists():
            logger.warning("Service keys file not found: %s", path)
            return
        try:
            import yaml
        except ImportError:
            logger.error("PyYAML not installed, cannot load %s", path)
            return

        try:
            with path.open() as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            logger.error("Malformed YAML in %s: %s", path, exc)
            return

        if not isinstance(data, dict) or "services" not in data:
            logger.warning("No 'services' key in %s", path)
            return

        services = data["services"]
        if not isinstance(services, dict):
            logger.error("'services' in %s is not a mapping, skipping", path)
            return

        try:
            self.load_dict(services)
        except (AttributeError, TypeError) as exc:
            logger.error("Malformed 'services' entries in %s: %s", path, exc)

    def load_env(self) -> None:
        """Load from SERVICE_KEY_<NAME> env vars with optional SERVICE_SCOPES_<NAME>."""
        prefix = "SERVICE_KEY_"
        scopes_prefix = "SERVICE_SCOPES_"
        for env_key, value in os.environ.items():
            if not env_key.startswith(prefix) or not value:
                continue
            name = env_key[len(prefix) :].lower().replace("_", "-")
            scopes_str = os.environ.get(f"{scopes_prefix}{env_key[len(prefix) :]}", "")
            raw_scopes = (
                [s.strip() for s in scopes_str.split(",") if s.strip()] if scopes_str else []
            )
            scopes = expand_scopes(raw_scopes)
            identity = ServiceIdentity(
                name=name,
                key_hash=_hash_key(value),
                scopes=scopes,
            )
            self._services[name] = identity
            self._register_key(name, value)
            logger.info("Registered service %s from env with %d scopes", name, len(scopes))

    def load_all(self, yaml_path: str | Path | None = None) -> None:
        """Load from all sources: dict (already loaded), YAML file, env vars."""
        if yaml_path:
            self.load_yaml(yaml_path)
        elif os.environ.get("SERVICE_KEYS_FILE"):
            self.load_yaml(os.environ["SERVICE_KEYS_FILE"])
        self.load_env()

    def validate(self) -> list[str]:
        """Check for issues: duplicate keys, services with no scopes."""
        issues: list[str] = []
        seen_hashes: dict[str, str] = {}
        for name, identity in self._services.items():
            if not identity.scopes:
                issues.append(f"Service {name} has no scopes")
            if identity.key_hash in seen_hashes:
                issues.append(f"Duplicate key between {name} and {seen_hashes[identity.key_hash]}")
            seen_hashes[identity.key_hash] = name
        return issues

    def authenticate(self, key: str) -> ServiceIdentity | None:
        """Look up a service by key. Returns None if not found."""
        name = self._key_to_name.get(key)
        if name is None:
            return None
        return self._services.get(name)
