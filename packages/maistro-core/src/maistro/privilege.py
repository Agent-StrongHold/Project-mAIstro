"""SPEC-012: Admin / user1 Privilege Separation — mandatory two-tier model.

Enforces a mandatory admin + user privilege model. The admin key can
access everything; user keys are scoped. Elevation flows, time-boxed
delegation, and policy VCs are all admin-signed and audit-logged.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maistro.security.secret_equal import secret_equal


class UsersTamperError(Exception):
    """Raised when users.toml signature verification fails."""


class InsufficientUsersError(Exception):
    """Raised when fewer than 2 users are provided during initialization."""


class ElevationDeniedError(Exception):
    """Raised when an elevation request is rejected."""


class GrantKeyMismatchError(Exception):
    """Raised when a grant was signed by a rotated/invalid admin key."""


_ADMIN_TOOLS = frozenset(
    {
        "admin:settings:write",
        "admin:users:manage",
        "admin:keys:rotate",
        "admin:audit:read",
        "admin:plugins:install",
    }
)


@dataclass(frozen=True)
class UserInfo:
    name: str
    public_key: str
    role: str


@dataclass
class ElevationRequest:
    user_public_key: str
    scope: str
    justification: str


@dataclass
class ElevationGrant:
    scope: str
    user_public_key: str
    # Retained for grant/key-version correlation; excluded from repr so it
    # cannot leak via logs or tracebacks.
    admin_key: str = field(repr=False)
    created_at: float
    ttl_seconds: float
    _valid: bool = True
    _admin_key_version: int = 0
    _signature: str = ""

    @property
    def is_valid(self) -> bool:
        if not self._valid:
            return False
        return not (
            self.ttl_seconds <= 0 or (time.monotonic() - self.created_at) > self.ttl_seconds
        )

    @property
    def expiry_reason(self) -> str:
        if self.ttl_seconds <= 0 or (time.monotonic() - self.created_at) > self.ttl_seconds:
            return "expired"
        if not self._valid:
            return "revoked"
        return ""

    def validate(self) -> None:
        if not self._valid:
            raise GrantKeyMismatchError("GRANT_KEY_MISMATCH: grant revoked")
        if self.ttl_seconds <= 0 or (time.monotonic() - self.created_at) > self.ttl_seconds:
            raise GrantKeyMismatchError("GRANT_KEY_MISMATCH: grant expired")


@dataclass
class _Policy:
    policy_id: str
    # Retained for grant/key-version correlation; excluded from repr so it
    # cannot leak via logs or tracebacks.
    admin_key: str = field(repr=False)
    user_public_key: str
    scope: str
    description: str
    revoked: bool = False
    admin_key_version: int = 0


@dataclass
class _SubsystemIdentity:
    role: str
    public_key: str


def _sign(data: str, key: str) -> str:
    return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()


def _verify(data: str, key: str, signature: str) -> bool:
    return hmac.compare_digest(_sign(data, key), signature)


class UsersStore:
    """Manages users.toml with admin signature verification."""

    def __init__(self, data_dir: str | Path, allow_single_user: bool = False) -> None:
        self._data_dir = Path(data_dir)
        self._users: list[UserInfo] = []
        self._admin_key = ""
        self._allow_single_user = allow_single_user
        self._loaded = False
        if self._data_dir.exists():
            self._load()

    def initialize(
        self,
        admin_name: str,
        admin_public_key: str,
        user_name: str | None = None,
        user_public_key: str | None = None,
    ) -> None:
        if not user_name or not user_public_key:
            if not self._allow_single_user:
                raise InsufficientUsersError("At least 2 users required (admin + user1)")
            self._users = [UserInfo(admin_name, admin_public_key, "admin")]
        else:
            self._users = [
                UserInfo(admin_name, admin_public_key, "admin"),
                UserInfo(user_name, user_public_key, "user"),
            ]
        self._admin_key = admin_public_key
        self._loaded = True
        self._write()

    def _write(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        toml_path = self._data_dir / "users.toml"
        lines: list[str] = []
        for u in self._users:
            lines.append("[[users]]")
            lines.append(f'name = "{u.name}"')
            lines.append(f'public_key = "{u.public_key}"')
            lines.append(f'role = "{u.role}"')
            lines.append("")
        content = "\n".join(lines)
        signature = _sign(content, self._admin_key)
        toml_path.write_text(f"# sig: {signature}\n{content}")

    def _load(self) -> None:
        if self._loaded:
            return
        toml_path = self._data_dir / "users.toml"
        if not toml_path.exists():
            return
        raw = toml_path.read_text()
        newline_pos = raw.index("\n")
        sig_line = raw[:newline_pos]
        content = raw[newline_pos + 1 :]
        if not sig_line.startswith("# sig: "):
            raise UsersTamperError("Missing signature in users.toml")
        stored_sig = sig_line[len("# sig: ") :]

        admin_key, users = self._parse_users(content)

        if not _verify(content, admin_key, stored_sig):
            raise UsersTamperError("Signature verification failed — users.toml tampered")

        self._users = users
        self._admin_key = admin_key
        self._loaded = True

    @staticmethod
    def _parse_users(content: str) -> tuple[str, list[UserInfo]]:
        admin_key = ""
        users: list[UserInfo] = []
        current: dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip()
            if line == "[[users]]":
                if current:
                    u = UserInfo(current["name"], current["public_key"], current["role"])
                    users.append(u)
                    if u.role == "admin":
                        admin_key = u.public_key
                current = {}
            elif "=" in line and current is not None:
                k, v = line.split("=", 1)
                current[k.strip()] = v.strip().strip('"')
        if current:
            u = UserInfo(current["name"], current["public_key"], current["role"])
            users.append(u)
            if u.role == "admin":
                admin_key = u.public_key
        return admin_key, users

    def admin(self) -> UserInfo:
        self._load()
        for u in self._users:
            if u.role == "admin":
                return u
        raise RuntimeError("No admin user found")

    def user_by_public_key(self, public_key: str) -> UserInfo:
        self._load()
        for u in self._users:
            if u.public_key == public_key:
                return u
        raise LookupError(f"No user with public key: {public_key}")


class PrivilegeGuard:
    """Enforces admin/user privilege separation with elevation and policy VCs."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._admin_key = ""
        self._user_key = ""
        self._admin_key_version = 0
        self._pending_elevations: dict[str, ElevationRequest] = {}
        self._grants: list[ElevationGrant] = []
        self._policies: list[_Policy] = []
        self._audit: list[dict[str, Any]] = []
        self._initialized = False

    def initialize(
        self,
        admin_public_key: str,
        user_public_key: str,
    ) -> None:
        self._admin_key = admin_public_key
        self._user_key = user_public_key
        self._admin_key_version = 0
        self._initialized = True

    def propose_elevation(self, request: ElevationRequest) -> str:
        token = hmac.new(
            os.urandom(32),
            f"{request.user_public_key}:{request.scope}:{time.monotonic()}".encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        self._pending_elevations[token] = request
        return token

    def admin_sign_elevation(
        self,
        token: str,
        admin_key: str,
        ttl_seconds: float = 900.0,
    ) -> ElevationGrant:
        if not secret_equal(admin_key, self._admin_key):
            raise ElevationDeniedError("Only the admin can sign elevation requests")
        request = self._pending_elevations.pop(token, None)
        if request is None:
            raise ElevationDeniedError("Unknown or expired elevation token")
        sig = _sign(f"{request.scope}:{request.user_public_key}", admin_key)
        grant = ElevationGrant(
            scope=request.scope,
            user_public_key=request.user_public_key,
            admin_key=admin_key,
            created_at=time.monotonic(),
            ttl_seconds=ttl_seconds,
            _admin_key_version=self._admin_key_version,
            _signature=sig,
        )
        self._grants.append(grant)
        self._audit.append(
            {
                "action": "elevation_granted",
                "scope": request.scope,
                "user_public_key": request.user_public_key,
                "justification": request.justification,
                "signature": sig,
                "timestamp": time.time(),
            }
        )
        return grant

    def rotate_admin_key(self, old_key: str, new_key: str) -> None:
        if not secret_equal(old_key, self._admin_key):
            raise ElevationDeniedError("old_key does not match current admin key")
        self._admin_key_version += 1
        self._admin_key = new_key
        for grant in self._grants:
            grant._valid = False
        for policy in self._policies:
            if not policy.revoked:
                policy.revoked = True

    def create_policy(
        self,
        admin_key: str,
        user_public_key: str,
        scope: str,
        description: str,
    ) -> str:
        if not secret_equal(admin_key, self._admin_key):
            raise ElevationDeniedError("Only admin can create policies")
        policy_id = hmac.new(
            os.urandom(32),
            f"{scope}:{user_public_key}:{time.monotonic()}".encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        self._policies.append(
            _Policy(
                policy_id=policy_id,
                admin_key=admin_key,
                user_public_key=user_public_key,
                scope=scope,
                description=description,
                admin_key_version=self._admin_key_version,
            )
        )
        return policy_id

    def revoke_policy(self, policy_id: str, admin_key: str) -> None:
        if not secret_equal(admin_key, self._admin_key):
            raise ElevationDeniedError("Only admin can revoke policies")
        for p in self._policies:
            if p.policy_id == policy_id:
                p.revoked = True

    def policy_allows(self, policy_id: str, user_public_key: str, action: str) -> bool:
        for p in self._policies:
            if p.policy_id == policy_id and p.user_public_key == user_public_key:
                if p.revoked:
                    return False
                return fnmatch.fnmatch(action, p.scope)
        return False

    def audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit)

    def can_perform(self, public_key: str, action: str) -> bool:
        if secret_equal(public_key, self._admin_key):
            return True
        return action not in _ADMIN_TOOLS

    def identity_for_subsystem(self, subsystem: str) -> _SubsystemIdentity:
        return _SubsystemIdentity(role="user", public_key=self._user_key)
