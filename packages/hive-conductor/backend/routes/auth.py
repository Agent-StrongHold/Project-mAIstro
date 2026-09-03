"""Auth routes — login, logout, whoami, elevate (2FA stub).

Elevation is task-scoped: permissions are bound to a task_id and revoked
when the task completes, fails, or is cancelled.
"""

from __future__ import annotations

import asyncio
import re
import time as _time
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

import stores
from config import get_settings, is_valid_oauth_provider_name
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from models.schemas import HiveUser
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from services import registration_policy
from services.human_auth_mode import HumanAuthModePolicy
from services.oauth_login import (
    OAUTH_MAX_PENDING_STATES,
    OAUTH_STATE_MAX_LENGTH,
    OAUTH_STATE_TTL_SECONDS,
    OAuthLoginDenied,
    get_oauth_login_service,
    oauth_state_cookie_name,
)
from starlette.responses import JSONResponse, RedirectResponse

from maistro.security.auth_throttle import AuthLimits, AuthThrottle, StricterLimits
from maistro.security.passwords import equal_cost_verify, hash_password, needs_rehash
from maistro.security.transport import is_trusted_proxy, parse_trusted_proxies
from routes.audit import log_audit

router = APIRouter(tags=["auth"])

# One throttle per endpoint class, because their budgets differ and sharing
# state would let cheap registration attempts consume a login budget (#366).
_STRICTER = StricterLimits()
_LOGIN_THROTTLE = AuthThrottle()
_REGISTER_THROTTLE = AuthThrottle(_STRICTER.register)
_ELEVATE_THROTTLE = AuthThrottle(_STRICTER.elevate)
# In one state lifetime, anonymous starts cannot fill the bounded state store
# even when distributed across client addresses.
_OAUTH_START_GLOBAL_LIMIT = OAUTH_MAX_PENDING_STATES // 2
_OAUTH_START_LIMITS = AuthLimits(
    per_client=10,
    per_account=_OAUTH_START_GLOBAL_LIMIT,
    global_failures=_OAUTH_START_GLOBAL_LIMIT,
    window_seconds=float(OAUTH_STATE_TTL_SECONDS),
    max_delay_seconds=0.5,
)
_OAUTH_START_THROTTLE = AuthThrottle(_OAUTH_START_LIMITS)
_OAUTH_CALLBACK_THROTTLE = AuthThrottle(_OAUTH_START_LIMITS)
_OAUTH_START_ACCOUNT = "oauth-start"
_OAUTH_CALLBACK_ACCOUNT = "oauth-callback"


def _client_key(request: Request) -> str:
    """The address an attempt is charged to.

    The socket peer, unless it is a proxy this deployment named — in which case
    the leftmost `X-Forwarded-For` entry, which is the address that proxy saw.
    Anyone can append to that header, so believing it from an untrusted peer
    would let an attacker mint a fresh budget per request by varying it, which
    is the same as having no per-client limit at all (#369 established the
    trusted-proxy check; this is the second thing that needs it).
    """
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
_OAUTH_CODE_MAX_LENGTH = 4096
_OAUTH_FAILURE_DETAIL = "OAuth authentication failed"
_OAUTH_LINK_COOKIE_PREFIX = "__Host-hive_oauth_link_"


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str
    password: str


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str
    password: str
    confirm_password: str
    #: A one-time invitation code (#313). Optional because an administrator
    #: may have opened registration outright; when the policy is closed this
    #: is the only thing that makes the attempt succeed.
    invitation_token: str | None = None

    @field_validator("invitation_token")
    @classmethod
    def validate_invitation_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = value.strip()
        if not token:
            return None
        if len(token) > 128:
            raise ValueError("Invitation code is too long.")
        return token

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
    user = stores.users.get(sess["user_id"])
    if user is None:
        return False
    return bool(user.has_permission(perm))


def _cookie_secure() -> bool:
    """Read the Secure flag at call time, not import time, so tests and
    deployments can set SESSION_COOKIE_SECURE without re-importing this module."""
    return bool(get_settings().session_cookie_secure)


def _cookie_samesite() -> Literal["lax", "strict", "none"]:
    """Read SameSite at call time, for the same reason as Secure (#369).

    Configurable rather than the hardcoded `"lax"` it was, because a deployment
    that fronts the Conductor with nothing cross-site wants `strict` and had no
    way to ask for it. The default stays `lax`, which is what makes an emailed
    link to a Conductor page work.
    """
    return get_settings().session_cookie_samesite


def _human_auth_policy() -> HumanAuthModePolicy:
    return HumanAuthModePolicy(mode=get_settings().human_auth_mode)


def _users() -> list[HiveUser]:
    return cast(list[HiveUser], list(stores.users.values()))


def _username_taken(username: str) -> bool:
    return any(user.username.lower() == username.lower() for user in _users())


def _issue_session(user: Any, response: Response) -> dict[str, Any]:
    # SECURITY-REVIEW: This is the canonical Hive authentication/session
    # issuance boundary used by both password and verified OAuth login.
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
    if session_id not in stores.sessions:
        return
    sess = stores.sessions[session_id]
    grants = sess.get("elevated_grants", {})
    if task_id in grants:
        del grants[task_id]
        stores.sessions[session_id] = {**sess, "elevated_grants": grants}


def _normalized_oauth_provider(provider: str) -> str:
    return provider if is_valid_oauth_provider_name(provider) else "unknown"


def _oauth_link_cookie_name(provider: str) -> str:
    return f"{_OAUTH_LINK_COOKIE_PREFIX}{provider}"


async def _charge_oauth_start(request: Request) -> None:
    """Count each anonymous state allocation before it can reach the store."""
    # SECURITY-REVIEW: This anonymous authentication boundary trusts only the
    # canonical proxy-aware client key and charges before allocating state.
    client_key = _client_key(request)
    decision = _OAUTH_START_THROTTLE.check(
        client_key=client_key,
        account=_OAUTH_START_ACCOUNT,
    )
    if decision.delay_seconds:
        await asyncio.sleep(decision.delay_seconds)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Wait a few minutes and try again.",
            headers={"Retry-After": "60"},
        )
    # AuthThrottle calls this a failure because password routes charge only
    # failed credentials. A start is itself the bounded resource spend, so
    # every allowed allocation is charged.
    _OAUTH_START_THROTTLE.record_failure(
        client_key=client_key,
        account=_OAUTH_START_ACCOUNT,
    )


async def _charge_oauth_callback(request: Request) -> None:
    """Count each anonymous callback before it can reach audit or state work."""
    # SECURITY-REVIEW: This anonymous authentication boundary trusts only the
    # canonical proxy-aware client key and charges before audit amplification.
    client_key = _client_key(request)
    decision = _OAUTH_CALLBACK_THROTTLE.check(
        client_key=client_key,
        account=_OAUTH_CALLBACK_ACCOUNT,
    )
    if decision.delay_seconds:
        await asyncio.sleep(decision.delay_seconds)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Wait a few minutes and try again.",
            headers={"Retry-After": "60"},
        )
    _OAUTH_CALLBACK_THROTTLE.record_failure(
        client_key=client_key,
        account=_OAUTH_CALLBACK_ACCOUNT,
    )


def _audit_oauth_failure(provider: str, failure: OAuthLoginDenied) -> None:
    normalized_provider = _normalized_oauth_provider(provider)
    detail = {
        "provider": normalized_provider,
        "stage": failure.stage,
        "reason": failure.reason,
    }
    if failure.subject is not None:
        detail["subject"] = failure.subject
    if failure.local_user_id is not None:
        detail["local_user_id"] = failure.local_user_id
    log_audit(
        "auth.oauth.failed",
        failure.local_user_id or "oauth",
        target=normalized_provider,
        detail=detail,
        severity="warning",
    )


def _oauth_response_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _clear_oauth_state_cookie(response: Response, provider: str) -> None:
    safe_provider = _normalized_oauth_provider(provider)
    response.set_cookie(
        key=oauth_state_cookie_name(safe_provider),
        value="",
        max_age=0,
        expires=0,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _clear_oauth_link_cookie(response: Response, provider: str) -> None:
    safe_provider = _normalized_oauth_provider(provider)
    response.set_cookie(
        key=_oauth_link_cookie_name(safe_provider),
        value="",
        max_age=0,
        expires=0,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _oauth_failure_response(provider: str, failure: OAuthLoginDenied) -> Response:
    _audit_oauth_failure(provider, failure)
    response = JSONResponse(status_code=401, content={"detail": _OAUTH_FAILURE_DETAIL})
    _clear_oauth_state_cookie(response, provider)
    _clear_oauth_link_cookie(response, provider)
    return _oauth_response_headers(response)


def _single_callback_value(request: Request, name: str, max_length: int) -> str | None:
    values = request.query_params.getlist(name)
    if len(values) != 1 or not values[0] or len(values[0]) > max_length:
        return None
    return values[0]


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, request: Request) -> Response:
    """Begin fixed-redirect Authorization Code + PKCE login."""
    await _charge_oauth_start(request)
    if not _human_auth_policy().oauth_provider_enabled(provider):
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="configuration", reason="unknown_provider"),
        )
    try:
        service = get_oauth_login_service()
        authorization_url, state = await service.start(provider)
    except OAuthLoginDenied as failure:
        return _oauth_failure_response(provider, failure)
    except Exception:
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="configuration", reason="missing"),
        )

    response = RedirectResponse(authorization_url, status_code=303)
    safe_provider = _normalized_oauth_provider(provider)
    response.set_cookie(
        key=oauth_state_cookie_name(safe_provider),
        value=state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return _oauth_response_headers(response)


@router.post("/oauth/{provider}/link/start")
async def oauth_link_start(
    provider: str,
    request: Request,
    hive_session: str | None = Cookie(None),
) -> Response:
    """Start an explicit provider-link flow for the authenticated Hive user."""
    await _charge_oauth_start(request)
    current = get_current_user(hive_session)
    if current is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not _human_auth_policy().oauth_provider_enabled(provider):
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="configuration", reason="unknown_provider"),
        )
    try:
        service = get_oauth_login_service()
        authorization_url, state = await service.start(provider)
    except OAuthLoginDenied as failure:
        return _oauth_failure_response(provider, failure)
    except Exception:
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="configuration", reason="missing"),
        )

    response = RedirectResponse(authorization_url, status_code=303)
    safe_provider = _normalized_oauth_provider(provider)
    response.set_cookie(
        key=oauth_state_cookie_name(safe_provider),
        value=state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    # Marker only. The authoritative link target is re-resolved from the
    # authenticated hive_session at callback time; no user id is client-carried.
    response.set_cookie(
        key=_oauth_link_cookie_name(safe_provider),
        value="1",
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return _oauth_response_headers(response)


async def _oauth_provider_error_callback(provider: str, request: Request) -> Response:
    """Consume a failed authorization response's state, then fail closed.

    The state must still be burned even when the provider reports `error`:
    otherwise a denied authorization leaves a pending state that could be
    replayed against a later attempt.
    """
    state = _single_callback_value(request, "state", OAUTH_STATE_MAX_LENGTH)
    if state is None:
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="state", reason="missing"),
        )
    safe_provider = _normalized_oauth_provider(provider)
    browser_state = request.cookies.get(oauth_state_cookie_name(safe_provider))
    try:
        service = get_oauth_login_service()
        await service.consume_failed_callback(
            provider=provider,
            state=state,
            browser_state=browser_state,
        )
    except OAuthLoginDenied as failure:
        return _oauth_failure_response(provider, failure)
    except Exception:
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="provider", reason="provider_rejected"),
        )
    return _oauth_failure_response(
        provider,
        OAuthLoginDenied(stage="provider", reason="provider_rejected"),
    )


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request) -> Response:
    """Verify an OIDC callback and issue or link the existing Hive identity."""
    # SECURITY-REVIEW: OAuth query/cookie values are untrusted authentication
    # inputs. They are bounded, browser-bound, single-use, and never logged.
    await _charge_oauth_callback(request)
    if not _human_auth_policy().oauth_provider_enabled(provider):
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="configuration", reason="unknown_provider"),
        )
    if request.query_params.getlist("error"):
        return await _oauth_provider_error_callback(provider, request)

    code = _single_callback_value(request, "code", _OAUTH_CODE_MAX_LENGTH)
    state = _single_callback_value(request, "state", OAUTH_STATE_MAX_LENGTH)
    if code is None or state is None:
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(
                stage="exchange" if code is None else "state",
                reason="missing",
            ),
        )

    safe_provider = _normalized_oauth_provider(provider)
    browser_state = request.cookies.get(oauth_state_cookie_name(safe_provider))
    link_requested = request.cookies.get(_oauth_link_cookie_name(safe_provider)) == "1"
    try:
        service = get_oauth_login_service()
        if link_requested:
            current = get_current_user(request.cookies.get(_SESSION_COOKIE))
            if current is None:
                raise OAuthLoginDenied(stage="identity", reason="unknown_user")
            result = await service.link_authenticated_user(
                provider=provider,
                code=code,
                state=state,
                browser_state=browser_state,
                user_id=current["id"],
            )
        else:
            result = await service.authenticate(
                provider=provider,
                code=code,
                state=state,
                browser_state=browser_state,
            )
    except OAuthLoginDenied as failure:
        return _oauth_failure_response(provider, failure)
    except Exception:
        return _oauth_failure_response(
            provider,
            OAuthLoginDenied(stage="provider", reason="provider_rejected"),
        )

    response = RedirectResponse(service.success_path, status_code=303)
    if link_requested:
        log_audit(
            "auth.oauth.link.complete",
            result.user.id,
            target=result.provider,
            detail={
                "provider": result.provider,
                "stage": "identity",
                "reason": "success",
                "subject": result.subject,
                "local_user_id": result.user.id,
            },
        )
    else:
        _issue_session(result.user, response)
        log_audit(
            "auth.oauth.login",
            result.user.id,
            target=result.provider,
            detail={
                "provider": result.provider,
                "stage": "session",
                "reason": "success",
                "subject": result.subject,
                "local_user_id": result.user.id,
            },
        )
    _clear_oauth_state_cookie(response, provider)
    _clear_oauth_link_cookie(response, provider)
    return _oauth_response_headers(response)


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
    # #313: the durable policy decides, and it fails closed — no record,
    # unreadable record, or an instance still mid-bootstrap all read as
    # "closed". The old gate here was `len(stores.users) > 0`, which meant
    # finishing setup turned public signup ON forever; this is the inversion
    # of that. Reasons stay uniform in the response (an enumeration oracle
    # #366 closed for login); the machine-readable reason goes to the audit
    # log, where a defender can read it and an attacker cannot.
    decision = registration_policy.evaluate_registration(body.invitation_token)
    if not decision.allowed:
        log_audit(
            "register_blocked",
            body.username,
            detail={"reason": decision.reason},
            severity="warning",
        )
        if body.invitation_token:
            raise HTTPException(status_code=403, detail="Invalid or expired invitation.")
        raise HTTPException(status_code=403, detail="Registration is closed on this hive.")
    if _username_taken(body.username):
        # Charged as a failure: "is this name taken?" is itself an enumeration
        # primitive, and an unbudgeted one would let someone walk the user list
        # for free.
        _REGISTER_THROTTLE.record_failure(client_key=_client_key(request), account=body.username)
        raise HTTPException(status_code=409, detail="Username is already taken.")
    if (
        body.invitation_token is not None
        and decision.reason == "invitation"
        and not registration_policy.redeem_invitation(body.invitation_token, username=body.username)
    ):
        # The invitation lost a redemption race (or expired between the check
        # and the spend). Anything that fails after a successful spend leaves
        # the token spent — fail-closed; an operator reissues.
        log_audit(
            "register_blocked",
            body.username,
            detail={"reason": "invitation_race"},
            severity="warning",
        )
        raise HTTPException(status_code=403, detail="Invalid or expired invitation.")

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
    if decision.reason == "invitation":
        log_audit(
            "registration_invitation_redeemed",
            body.username,
            target=decision.invitation_id,
            detail={"invitation_id": decision.invitation_id},
        )
    log_audit("user_register", body.username, target=user_id)
    result = _issue_session(user, response)
    return result


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
    _enforce(_LOGIN_THROTTLE, request, body.username, "login")
    policy = _human_auth_policy()
    if not policy.ordinary_password_login_enabled:
        log_audit(
            "login_auth_mode_denied",
            "password",
            target=policy.mode,
            severity="warning",
        )
        raise HTTPException(
            status_code=403, detail="Password login is disabled for this deployment."
        )

    # Find the account first, then ALWAYS verify exactly once — against a decoy
    # when there is no account (#366). The previous form was:
    #
    #     if user.username == body.username and user.verify_password(...)
    #
    # and `and` short-circuits, so an unknown username never reached Argon2.
    # Measured: 87.6 ms for a known username with the wrong password, ~0 ms for
    # an unknown one. Four orders of magnitude, readable from one request.
    match = next((user for user in _users() if user.username == body.username), None)
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


# --- Registration policy (#313) ---------------------------------------------
#
# Admin-only surface over the durable registration policy. These are NOT in
# AuthMiddleware's public table: dispatch 401s them without a session, and
# the in-route role check is the same shape `set_user_permissions` above uses.
# The anonymous surface is exactly two things — the register route itself,
# which enforces the policy, and the `registration.mode` bit published by
# `/v1/setup/status` so the login page need not offer a form that cannot
# succeed.


class RegistrationPolicyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str


def _require_admin(hive_session: str | None) -> dict[str, Any]:
    actor = get_current_user(hive_session)
    if actor is None:
        raise HTTPException(status_code=401, detail="No session")
    if actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin role required to change registration")
    return actor


@router.get("/registration/policy")
def get_registration_policy(hive_session: str | None = Cookie(None)) -> dict[str, Any]:
    """The active registration policy and the health of its durable record."""
    _require_admin(hive_session)
    return {"ok": True, "policy": registration_policy.describe()}


@router.put("/registration/policy")
def put_registration_policy(
    body: RegistrationPolicyBody, hive_session: str | None = Cookie(None)
) -> dict[str, Any]:
    """Open or close public registration. Durable, and audited."""
    actor = _require_admin(hive_session)
    try:
        policy = registration_policy.set_mode(body.mode, actor=f"admin:{actor['username']}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except registration_policy.RegistrationPolicyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"registration policy was not persisted: {exc}",
        ) from exc
    log_audit(
        "registration_policy_changed",
        actor["username"],
        detail={"mode": body.mode},
        severity="warning",
    )
    return {"ok": True, "policy": policy}


class InvitationBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ttl_seconds: int | None = None
    note: str | None = None


@router.post("/registration/invitations")
def create_invitation(
    body: InvitationBody, hive_session: str | None = Cookie(None)
) -> dict[str, Any]:
    """Issue one single-use registration invitation.

    The token is returned exactly once and stored only as a digest — this
    response is the only place it can be read.
    """
    actor = _require_admin(hive_session)
    try:
        invitation = registration_policy.issue_invitation(
            actor=f"admin:{actor['username']}",
            ttl_seconds=body.ttl_seconds,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except registration_policy.RegistrationPolicyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"invitation was not persisted: {exc}",
        ) from exc
    log_audit(
        "registration_invitation_issued",
        actor["username"],
        target=invitation["invitation_id"],
        detail={"ttl_seconds": invitation["ttl_seconds"]},
        severity="warning",
    )
    return {
        "ok": True,
        **invitation,
        "warning": (
            "Show the invitation code now — it is stored only as a hash and "
            "cannot be retrieved again."
        ),
    }


@router.get("/registration/invitations")
def list_registration_invitations(
    hive_session: str | None = Cookie(None),
) -> dict[str, Any]:
    """List issued invitations: statuses and metadata, never tokens."""
    _require_admin(hive_session)
    return {"ok": True, "invitations": registration_policy.list_invitations()}
