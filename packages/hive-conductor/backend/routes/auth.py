"""Auth routes — login, logout, whoami, elevate (2FA stub).

Elevation is task-scoped: permissions are bound to a task_id and revoked
when the task completes, fails, or is cancelled.
"""

from __future__ import annotations

import asyncio
import re
import time as _time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeGuard, cast
from uuid import uuid4

import stores
from config import get_settings, is_valid_oauth_provider_name
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from models.schemas import HiveUser
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from services import registration_policy, username_registry
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

from maistro.security.auth_throttle import (  # pyright: ignore[reportMissingImports]
    AuthLimits,
    AuthThrottle,
    StricterLimits,
)
from maistro.security.passwords import (  # pyright: ignore[reportMissingImports]
    equal_cost_verify,
    hash_password,
    needs_rehash,
)
from maistro.security.passwords import (  # pyright: ignore[reportMissingImports]
    validate_password as validate_canonical_password,
)
from maistro.security.transport import (  # pyright: ignore[reportMissingImports]
    is_trusted_proxy,
    parse_trusted_proxies,
)
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
# Governed session policy: production sessions expire after 30 minutes without
# eligible authenticated activity and never live longer than seven days.
# These are server-side limits; browser restoration/preferences cannot change them.
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7
_SESSION_IDLE_TIMEOUT = 60 * 30
_SESSION_ABSOLUTE_TTL = _COOKIE_MAX_AGE
_SESSION_ACTIVITY_EXCLUDED_PATHS = frozenset({"/v1/auth/whoami"})
_SESSION_LOCK = threading.RLock()
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
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
        return validate_canonical_password(value)

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


def _session_now() -> datetime:
    """Return the server clock used for every session decision."""
    return datetime.now(UTC)


def _session_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _session_expiries(sess: dict[str, Any], now: datetime) -> tuple[datetime, datetime] | None:
    created = _session_timestamp(sess.get("created_at"))
    last_activity = _session_timestamp(sess.get("last_activity_at"))
    if created is None:
        return None
    # Records written before idle expiry shipped are treated as having been
    # active at creation, rather than being granted an unbounded lifetime.
    if last_activity is None:
        last_activity = created
    return (
        created + timedelta(seconds=_SESSION_ABSOLUTE_TTL),
        last_activity + timedelta(seconds=_SESSION_IDLE_TIMEOUT),
    )


def _is_session_record(sess: object) -> TypeGuard[dict[str, Any]]:
    """Whether a record in the sessions store claims to be an auth session.

    The sessions store is a shared KV, not a session-only table: the setup
    wizard keeps its durable one-shot first-run claim (``claimed_at``) and the
    completed-setup config marker (``completed_at``) there, and neither has a
    session shape. Anything without the session shape fails resolution closed
    — and must never be *deleted* by resolution: popping records that do not
    parse as sessions would let any unauthenticated request name a marker in
    its session cookie and evict a one-shot boundary it could never read.
    Eviction is reserved for records that resolve as real sessions.
    """
    return (
        isinstance(sess, dict)
        and isinstance(sess.get("created_at"), str)
        and isinstance(sess.get("user_id"), str)
        and bool(sess["user_id"])
    )


def _resolve_session(
    session_id: str,
    *,
    refresh_activity: bool = False,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve and optionally touch one session as one locked operation.

    The lock makes expiry, revocation, and the sliding timestamp a single
    server-side decision for this process; a late request cannot resurrect an
    expired or revoked record. ``whoami`` deliberately calls this without a
    refresh because it is a health probe, not user activity.
    """
    if not session_id:
        return None
    current = now or _session_now()
    with _SESSION_LOCK:
        sess = stores.sessions.get(session_id)
        if not _is_session_record(sess):
            # Fail closed WITHOUT deleting: the store also holds the setup
            # claim/config markers, and destroying those on an unparseable
            # record would release the first-run one-shot boundary (#1187).
            return None
        expiries = _session_expiries(sess, current)
        if expiries is None or current >= min(expiries):
            stores.sessions.pop(session_id, None)
            return None
        # Deactivation is revocation: remove the opaque session while the
        # account is inactive so reactivation cannot resurrect it.
        user = stores.users.get(sess.get("user_id"))
        if user is None or not user.is_active:
            stores.sessions.pop(session_id, None)
            return None
        if refresh_activity:
            previous = _session_timestamp(sess.get("last_activity_at"))
            # A wall-clock correction must not move activity backwards. The
            # absolute expiry remains anchored to the original creation time.
            if previous is None or current > previous:
                stores.sessions[session_id] = {**sess, "last_activity_at": current.isoformat()}
        return stores.sessions.get(session_id)


def _active_grants(sess: dict[str, Any]) -> dict[str, list[str]]:
    grants = sess.get("elevated_grants", {})
    return {tid: perms for tid, perms in grants.items() if isinstance(perms, list)}


def refresh_session_activity(session_id: str | None) -> bool:
    """Refresh one eligible session, failing closed on concurrent revocation."""
    return _resolve_session(session_id or "", refresh_activity=True) is not None


def get_current_user(
    session_id: str | None,
    *,
    refresh_activity: bool = False,
) -> dict[str, Any] | None:
    if not session_id:
        return None
    current = _session_now()
    sess = _resolve_session(session_id, refresh_activity=refresh_activity, now=current)
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
    expiries = _session_expiries(sess, current)
    if expiries is None:
        return None
    absolute_expires_at, idle_expires_at = expiries
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "permissions": user.permissions,
        "did": user.did,
        "elevated_permissions": all_elevated,
        "elevated_tasks": list(grants.keys()),
        # This is policy/health metadata only. The opaque session id is never
        # included in the response.
        "session_policy": {
            "idle_timeout_seconds": _SESSION_IDLE_TIMEOUT,
            "absolute_ttl_seconds": _SESSION_ABSOLUTE_TTL,
            "idle_expires_at": idle_expires_at.isoformat(),
            "absolute_expires_at": absolute_expires_at.isoformat(),
            "effective_expires_at": min(absolute_expires_at, idle_expires_at).isoformat(),
        },
    }


def user_has_permission(session_id: str | None, perm: str) -> bool:
    if not session_id:
        return False
    sess = _resolve_session(session_id)
    if sess is None:
        return False
    user = stores.users.get(sess["user_id"])
    if user is None or not user.is_active:
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
    # This is an indexed lookup, retained as the policy-facing availability
    # helper. It is only advisory: the atomic account allocation below is the
    # authority under concurrency.
    return username_registry.is_claimed(username)


def _issue_session(user: Any, response: Response) -> dict[str, Any]:
    # SECURITY-REVIEW: This is the canonical Hive authentication/session
    # issuance boundary used by both password and verified OAuth login.
    session_id = str(uuid4())
    issued_at = _session_now()
    with _SESSION_LOCK:
        stores.sessions[session_id] = {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "permissions": user.permissions,
            "elevated_grants": {},
            "created_at": issued_at.isoformat(),
            "last_activity_at": issued_at.isoformat(),
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
    with _SESSION_LOCK:
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
    # Handle invitation redemption before password hashing to avoid wasted work
    # on invalid invitations. The redemption is atomic via JsonStore.put_if_absent.
    if (
        body.invitation_token is not None
        and decision.reason == "invitation"
        and not registration_policy.redeem_invitation(body.invitation_token, username=body.username)
    ):
        log_audit(
            "register_blocked",
            body.username,
            detail={"reason": "invitation_race"},
            severity="warning",
        )
        raise HTTPException(status_code=403, detail="Invalid or expired invitation.")
    # Allocate username and create user atomically.
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
    try:
        username_registry.create_users([user])
    except username_registry.UsernameTakenError as exc:
        _REGISTER_THROTTLE.record_failure(client_key=_client_key(request), account=body.username)
        raise HTTPException(status_code=409, detail="Username is already taken.") from exc
    except username_registry.UsernameAllocationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Account could not be durably allocated; please retry.",
        ) from exc
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
    # Username identity is resolved through the canonical claim index. A
    # quarantined historical duplicate therefore fails closed rather than
    # selecting whichever user a storage iteration happens to return.
    match = username_registry.resolve(body.username)
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
        with _SESSION_LOCK:
            user_info = _resolve_session(hive_session)
            actor = user_info.get("username", "unknown") if user_info else "unknown"
            # Pop only what resolved as a live session: the pop keys off the
            # raw presented cookie value, which any caller can name, while the
            # store also holds the setup claim/config markers — deleting those
            # on an unresolvable cookie would let a request evict a one-shot
            # boundary it could never read. Expired or revoked sessions are
            # already evicted by the resolution above, so real sessions are
            # invalidated here exactly as before.
            if user_info is not None:
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
    # Intentionally observational: the SPA may call this during restoration,
    # but a health check must not keep an unattended session alive.
    user = get_current_user(hive_session, refresh_activity=False)
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": user}


@router.post("/elevate")
def elevate(
    body: ElevateBody, request: Request, hive_session: str | None = Cookie(None)
) -> dict[str, Any]:
    if not hive_session:
        raise HTTPException(status_code=401, detail="No session")
    sess = _resolve_session(hive_session)
    if sess is None:
        raise HTTPException(status_code=401, detail="No session")
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
    with _SESSION_LOCK:
        # Re-read under the same lock as expiry/revocation so an elevation
        # cannot overwrite a concurrent logout or session purge.
        current = _resolve_session(hive_session)
        if current is None:
            raise HTTPException(status_code=401, detail="No session")
        stores.sessions[hive_session] = {**current, "elevated_grants": grants}
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
