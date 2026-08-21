"""Agnostic credential store v2 — multiple instances per type, PostgreSQL-backed."""

import json
import os
from typing import Any
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet

_MASTER_KEY_ENV = "HIVE_CREDENTIALS_MASTER_KEY"
POSTGREST_URL = (
    os.environ.get("POSTGREST_URL") or os.environ.get("DEPLOY_TARGET_POSTGREST_URL") or ""
)
TABLE = "hive_credentials_v2"


class CredentialV2:
    """A single credential instance."""

    def __init__(self, data: dict):
        self.id = data["id"]
        self.user_id = data["user_id"]
        self.name = data["name"]
        self.type = data["type"]
        self.api_base = data.get("api_base", "")
        self.credential_type = data.get("credential_type", "api_key")
        self.metadata = data.get("metadata", {})
        if isinstance(self.metadata, str):
            self.metadata = json.loads(self.metadata)
        self.created_at = data.get("created_at")
        self.updated_at = data.get("updated_at")


class AgnosticCredentialStore:
    """Multi-instance credential store. Each credential has a name, type, and encrypted secret."""

    def __init__(self):
        key = os.environ.get(_MASTER_KEY_ENV, "").strip()
        if not key:
            raise RuntimeError(f"{_MASTER_KEY_ENV} env var required")
        self._fernet = Fernet(key.encode())

    def _encrypt(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode()).decode()

    def _decrypt(self, encrypted: str) -> str:
        return self._fernet.decrypt(encrypted.encode()).decode()

    def create(
        self,
        user_id: str,
        name: str,
        type: str,
        secret: str,
        api_base: str = "",
        credential_type: str = "api_key",
        metadata: dict | None = None,
    ) -> CredentialV2:
        """Create a new credential instance."""
        cred_id = str(uuid4())
        row = {
            "id": cred_id,
            "user_id": user_id,
            "name": name,
            "type": type,
            "api_base": api_base,
            "credential_type": credential_type,
            "secret_enc": self._encrypt(secret),
            "metadata": json.dumps(metadata or {}),
        }
        r = httpx.post(
            f"{POSTGREST_URL}/{TABLE}",
            json=row,
            headers={"Prefer": "return=representation", "Content-Type": "application/json"},
            timeout=10,
        )
        rows = r.json() if r.status_code in (200, 201) else [row]
        return CredentialV2(rows[0] if rows else row)

    def list(self, user_id: str, type: str | None = None) -> list[CredentialV2]:
        """List all credentials for a user, optionally filtered by type."""
        params: dict[str, str] = {"user_id": f"eq.{user_id}"}
        if type:
            params["type"] = f"eq.{type}"
        params["order"] = "created_at.desc"
        r = httpx.get(f"{POSTGREST_URL}/{TABLE}", params=params, timeout=10)
        rows = r.json() if r.status_code == 200 else []
        return [CredentialV2(row) for row in rows]

    def get(self, cred_id: str) -> CredentialV2 | None:
        """Get a credential by ID (without secret)."""
        r = httpx.get(f"{POSTGREST_URL}/{TABLE}", params={"id": f"eq.{cred_id}"}, timeout=5)
        rows = r.json() if r.status_code == 200 else []
        return CredentialV2(rows[0]) if rows else None

    def get_secret(self, cred_id: str) -> str | None:
        """Get the decrypted secret for a credential."""
        r = httpx.get(
            f"{POSTGREST_URL}/{TABLE}",
            params={"id": f"eq.{cred_id}", "select": "secret_enc"},
            timeout=5,
        )
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return None
        return self._decrypt(rows[0]["secret_enc"])

    def update(self, cred_id: str, **kwargs) -> None:
        """Update credential fields (name, api_base, metadata, secret)."""
        data: dict[str, Any] = {}
        if "name" in kwargs:
            data["name"] = kwargs["name"]
        if "api_base" in kwargs:
            data["api_base"] = kwargs["api_base"]
        if "metadata" in kwargs:
            data["metadata"] = json.dumps(kwargs["metadata"])
        if "secret" in kwargs:
            data["secret_enc"] = self._encrypt(kwargs["secret"])
        if data:
            data["updated_at"] = "now()"
            httpx.patch(
                f"{POSTGREST_URL}/{TABLE}",
                params={"id": f"eq.{cred_id}"},
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

    def delete(self, cred_id: str) -> bool:
        """Delete a credential by ID."""
        r = httpx.delete(f"{POSTGREST_URL}/{TABLE}", params={"id": f"eq.{cred_id}"}, timeout=10)
        return r.status_code in (200, 204)

    def find_by_type(self, user_id: str, type: str) -> list[CredentialV2]:
        """Find all credentials of a given type for a user."""
        return self.list(user_id, type=type)

    def get_first_secret_by_type(self, user_id: str, type: str) -> str | None:
        """Convenience: get the first credential's secret for a type."""
        creds = self.find_by_type(user_id, type)
        if not creds:
            return None
        return self.get_secret(creds[0].id)
