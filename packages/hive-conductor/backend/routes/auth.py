"""Auth routes — login, logout, whoami, elevate (2FA stub).

Elevation is task-scoped: permissions are bound to a task_id and revoked
when the task completes, fails, or is cancelled.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from maistro.security.auth_throttle import AuthThrottle, StricterLimits
from maistro.security.transport import is_trusted_proxy, parse_trusted_proxies
from routes.audit import log_audit

router = APIRouter(tags=["auth"])

# One throttle per endpoint class, because their budgets differ and sharing
# state would let cheap registration attempts consume a login budget (#366).
_STRICTER = StricterLimits()
_LOGIN_THROTTLE = AuthThrottle()
_REGISTER_THROTTLE = AuthThrottle(_STRICTER.register)
_ELEVATE_THROTTLE = AuthThrottle(_STRICTER.elevate)


def _client_key(request: Request) -> str:
    """The address an attempt is charged to.

    The socket peer, unless it is a proxy this deployment named — in which case
    the leftmost `X-Forwarded-For` entry, which is the address that proxy saw.
    Anyone can append to that header, so believing it from an untrusted peer
    would let an attacker mint a fresh budget per request by varying it, which
    is the same as having no per-client limit at all (#369 established the
    trusted-proxy check; this is the second thing that needs it).
    """
    from config import get_settings

    peer = request.client.host if request.client else ""
    if not peer:
        # No peer address (a Unix socket, say). One shared bucket rather than
        # an empty key per request: unattributable attempts must still be
        # bounded together.
        return "unattributed"
    trusted = parse_trusted_proxies(get_settings().trusted_proxy_ips)
    if not is_trusted_proxy(peer, trusted):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or peer


def _enforce(throttle: AuthThrottle, request: Request, account: str, action: str) -> None:
    """Charge an attempt, or refuse it. Always pays the progressive delay.

    The delay is applied whether or not the attempt is allowed, so how long an
    answer takes never says which limit a caller is near — and never says
    whether the account exists.

    The refusal body says nothing about *which* scope ran out: "you hit the
    per-account limit" confirms the account is real, which is the enumeration
    this endpoint is being hardened against. The reason goes to the audit log,
    where a defender can read it and an attacker cannot.
    """
    import time as _time

    decision = throttle.check(client_key=_client_key(request), account=account)
    if decision.delay_seconds:
        _time.sleep(decision.delay_seconds)
    if not decision.allowed:
        log_audit(f"{action}_throttled", account, severity="warning")
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Wait a few minutes and try again.",
            headers={"Retry-After": "60"},
        )


_SESSION_COOKIE = "hive_session"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
_MIN_PASSWORD_LEN = 8


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str
    password: str


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        name = value.strip()
        if not _USERNAME_RE.match(name):
            msg = "Username must be 3-32 characters (letters, numbers, underscore, hyphen)."
            raise ValueError(msg)
        return name

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < _MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be at least {_MIN_PASSWORD_LEN} characters.")
        return value

    @model_validator(mode="after")
    def passwords_match(self) -> RegisterBody:
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class ElevateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    password: str
    permissions: list[str] = Field(default_factory=list)
    task_id: str


def _resolve_session(session_id: str) -> dict[str, Any] | None:
    import stores

    if not session_id or session_id not in stores.sessions:
        return None
    sess = stores.sessions[session_id]
    if not isinstance(sess, dict):
        return None
    created_at = sess.get("created_at")
    if isinstance(created_at, str):
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            created = None
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - created).total_seconds()
            if age > _COOKIE_MAX_AGE:
                stores.sessions.pop(session_id, None)
                return None
    user_id = sess.get("user_id")
    if not user_id or user_id not in stores.users:
        return None
    return sess


def _active_grants(sess: dict[str, Any]) -> dict[str, list[str]]:
    grants = sess.get("elevated_grants", {})
    return {tid: perms for tid, perms in grants.items() if isinstance(perms, list)}


def get_current_user(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    sess = _resolve_session(session_id)
    if sess is None:
        return None
    import stores

    user = stores.users.get(sess["user_id"])
    if user is None or not user.is_active:
        return None
    grants = _active_grants(sess)
    all_elevated: list[str] = []
    for perms in grants.values():
        for p in perms:
            if p not in all_elevated:
                all_elevated.append(p)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "permissions": user.permissions,
        "did": user.did,
        "elevated_permissions": all_elevated,
        "elevated_tasks": list(grants.keys()),
    }


def user_has_permission(session_id: str | None, perm: str) -> bool:
    if not session_id:
        return False
    sess = _resolve_session(session_id)
    if sess is None:
        return False
    import stores

    user = stores.users.get(sess["user_id"])
    if user is None:
        return False
    return user.has_permission(perm)


def _registration_allowed() -> bool:
    """Signup only after initial hive setup (at least one account exists)."""
    import stores

    return len(stores.users) > 0


def _cookie_secure() -> bool:
    """Read the Secure flag at call time, not import time, so tests and
    deployments can set SESSION_COOKIE_SECURE without re-importing this module."""
    from config import get_settings

    return bool(get_settings().session_cookie_secure)


def _cookie_samesite() -> str:
    """Read SameSite at call time, for the same reason as Secure (#369).

    Configurable rather than the hardcoded `"lax"` it was, because a deployment
    that fronts the Conductor with nothing cross-site wants `strict` and had no
    way to ask for it. The default stays `lax`, which is what makes an emailed
    link to a Conductor page work.
    """
    from config import get_settings

    return str(get_settings().session_cookie_samesite)


def _username_taken(username: str) -> bool:
    import stores

    return any(u.username.lower() == username.lower() for u in stores.users.values())


def _issue_session(user: Any, response: Response) -> dict[str, Any]:
    import stores

    session_id = str(uuid4())
    stores.sessions[session_id] = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "permissions": user.permissions,
        "elevated_grants": {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=session_id,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite=_cookie_samesite(),
        secure=_cookie_secure(),
        path="/",
    )
    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "permissions": user.permissions,
            "did": user.did,
        },
    }


def revoke_task_elevation(session_id: str, task_id: str) -> None:
    import stores

    if session_id not in stores.sessions:
        return
    sess = stores.sessions[session_id]
    grants = sess.get("elevated_grants", {})
    if task_id in grants:
        del grants[task_id]
        stores.sessions[session_id] = {**sess, "elevated_grants": grants}


@router.post("/register")
def register(body: RegisterBody, request: Request, response: Response) -> dict[str, Any]:
    # SECURITY-REVIEW: public signup creates role=user only; passwords hashed with Argon2id.
    #
    # Throttled before the availability check and before hashing (#366).
    # Registration hashes unconditionally on the success path, so it is the
    # same 64 MiB primitive as login, reachable by the same anonymous caller —
    # and it also creates rows, so an unbounded stream is a storage attack as
    # well as a memory one.
    _enforce(_REGISTER_THROTTLE, request, body.username, "register")
    if not _registration_allowed():
        raise HTTPException(
            status_code=403,
            detail="Registration is unavailable until initial hive setup is complete.",
        )
    if _username_taken(body.username):
        # Charged as a failure: "is this name taken?" is itself an enumeration
        # primitive, and an unbudgeted one would let someone walk the user list
        # for free.
        _REGISTER_THROTTLE.record_failure(client_key=_client_key(request), account=body.username)
        raise HTTPException(status_code=409, detail="Username is already taken.")

    import stores
    from models.schemas import HiveUser

    from maistro.security.passwords import hash_password

    user_id = str(uuid4())
    password_hash = hash_password(body.password)
    now_ts = datetime.now(UTC)
    user = HiveUser(
        id=user_id,
        username=body.username,
        password_hash=password_hash,
        role="user",
        is_active=True,
        permissions=[],
        did=None,
        created_at=now_ts,
    )
    stores.users[user_id] = user
    log_audit("user_register", body.username, target=user_id)
    result = _issue_session(user, response)
    return result


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    import stores

    from maistro.security.passwords import equal_cost_verify, hash_password, needs_rehash

    _enforce(_LOGIN_THROTTLE, request, body.username, "login")

    # Find the account first, then ALWAYS verify exactly once — against a decoy
    # when there is no account (#366). The previous form was:
    #
    #     if user.username == body.username and user.verify_password(...)
    #
    # and `and` short-circuits, so an unknown username never reached Argon2.
    # Measured: 87.6 ms for a known username with the wrong password, ~0 ms for
    # an unknown one. Four orders of magnitude, readable from one request.
    match = next((u for u in stores.users.values() if u.username == body.username), None)
    verified = equal_cost_verify(body.password, match.password_hash if match else None)

    if match is not None and verified:
        if not match.is_active:
            # A disabled account is told apart from a wrong password on
            # purpose: the person holding the right credential needs to know
            # why they are out, and they have already proved they own it.
            log_audit("login_disabled", match.username, severity="warning")
            raise HTTPException(status_code=403, detail="Account disabled")
        if needs_rehash(match.password_hash):
            stores.users[match.id] = match.model_copy(
                update={"password_hash": hash_password(body.password)}
            )
            match = stores.users[match.id]
        _LOGIN_THROTTLE.record_success(client_key=_client_key(request), account=body.username)
        log_audit("login", match.username)
        return _issue_session(match, response)

    _LOGIN_THROTTLE.record_failure(client_key=_client_key(request), account=body.username)
    log_audit("login_failed", body.username, severity="warning")
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/logout")
def logout(response: Response, hive_session: str | None = Cookie(None)) -> dict[str, Any]:
    if hive_session:
        import stores

        user_info = _resolve_session(hive_session)
        actor = user_info.get("username", "unknown") if user_info else "unknown"
        stores.sessions.pop(hive_session, None)
        log_audit("logout", actor)
    # A cookie is only cleared when the delete matches the attributes it was set
    # with. Dropping path/secure/samesite here left the original cookie in place
    # on any deployment where they differed, so `logout` returned ok:true while
    # the browser kept sending a session id the server had already discarded —
    # harmless today only because `stores.sessions.pop` above invalidates it
    # server-side too.
    response.delete_cookie(
        key=_SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite=_cookie_samesite(),
        secure=_cookie_secure(),
    )
    return {"ok": True}


@router.get("/whoami")
def whoami(hive_session: str | None = Cookie(None)) -> dict[str, Any]:
    user = get_current_user(hive_session)
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": user}


@router.post("/elevate")
def elevate(
    body: ElevateBody, request: Request, hive_session: str | None = Cookie(None)
) -> dict[str, Any]:
    import stores

    from maistro.security.passwords import equal_cost_verify

    if not hive_session or hive_session not in stores.sessions:
        raise HTTPException(status_code=401, detail="No session")
    sess = stores.sessions[hive_session]
    user = stores.users.get(sess["user_id"])

    # Bounded separately and far more tightly than login (#366). This is only
    # reachable with a valid session, so the budget is not about anonymous
    # guessing — it is about stopping a *stolen* session from grinding against
    # the privilege check that stands between it and elevated permissions. A
    # legitimate user elevates rarely, so a small budget costs them nothing.
    #
    # Keyed on the session rather than the username: two people are not
    # sharing a session, and keying on the account would let one compromised
    # session lock out the real owner's other ones.
    _enforce(_ELEVATE_THROTTLE, request, hive_session, "elevate")

    if user is None or not equal_cost_verify(body.password, user.password_hash if user else None):
        # Equal cost here too: a session whose user row has been deleted must
        # not answer faster than one whose password is merely wrong.
        _ELEVATE_THROTTLE.record_failure(client_key=_client_key(request), account=hive_session)
        log_audit("elevate_failed", sess.get("username", "unknown"), severity="warning")
        raise HTTPException(status_code=401, detail="Invalid password")
    _ELEVATE_THROTTLE.record_success(client_key=_client_key(request), account=hive_session)

    requested = body.permissions if body.permissions else list(user.permissions)
    granted = [p for p in requested if user.has_permission(p)]
    if body.permissions and not granted:
        raise HTTPException(
            status_code=403,
            detail="None of the requested permissions are assigned to your account",
        )

    grants: dict[str, list[str]] = sess.get("elevated_grants", {})
    grants[body.task_id] = granted
    stores.sessions[hive_session] = {**sess, "elevated_grants": grants}
    log_audit(
        "elevate",
        user.username,
        target=body.task_id,
        detail={"permissions": granted},
        severity="warning",
    )
    return {
        "ok": True,
        "task_id": body.task_id,
        "elevated_permissions": granted,
        "message": "Permissions elevated for this task. They will be revoked when the task completes.",
    }


class GrantPermissionsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    permissions: list[str]


@router.patch("/users/{user_id}/permissions")
def set_user_permissions(
    user_id: str, body: GrantPermissionsBody, hive_session: str | None = Cookie(None)
) -> dict[str, Any]:
    """Admin-only: replace a user's assigned permission set.

    This is the assignment half of the two-step model that /elevate is the
    other half of: elevate can only raise permissions the account already
    HOLDS, and registration assigns none — so before this route existed there
    was no supported way for the daily account to ever satisfy a scope like
    `rsi.execute` or `harness.execute`. The admin (break-glass) account
    assigns; the daily account then elevates per task with its password.
    """
    import stores

    actor = get_current_user(hive_session)
    if actor is None:
        raise HTTPException(status_code=401, detail="No session")
    if actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin role required to assign permissions")

    target = stores.users.get(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Unknown user")

    updated = target.model_copy(update={"permissions": sorted(set(body.permissions))})
    stores.users[user_id] = updated
    log_audit(
        "permissions_assigned",
        actor["username"],
        target=user_id,
        detail={"permissions": updated.permissions},
        severity="warning",
    )
    return {"ok": True, "user_id": user_id, "permissions": updated.permissions}
