"""Auth middleware — session cookies, role-based access, task-scoped elevation.

Public paths (setup, login, health, static) bypass auth.
Admin role is blocked from /v1/chat/ routes (break-glass only).
Protected ops require elevation bound to a task — permissions die with the task.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from config import get_settings, is_valid_oauth_provider_name
from fastapi import Request
from routes import auth as auth_routes
from routes import setup as setup_routes
from services import voice_identity
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("hive.auth_middleware")

_PUBLIC_PREFIXES = (
    "/v1/setup/",
    "/health",
)

#: Authenticated like everything else, but by a device credential rather than a
#: session — see `services/voice_identity.py`. This is not an exemption: with
#: no credential configured the prefix answers 401 like any other `/v1/` path.
_VOICE_PREFIX = "/v1/voice/"

# FastAPI's default docs/openapi paths don't end in "/" (the real route is
# /openapi.json), so they can't use the boundary-safe prefix check below —
# keep them on a plain startswith() match.
_PUBLIC_PREFIXES_LOOSE = (
    "/docs",
    "/openapi",
    "/redoc",
)
_OAUTH_PUBLIC_GET_RE = re.compile(r"^/v1/auth/oauth/(?P<provider>[^/]{1,128})/(?:start|callback)$")

_PUBLIC_EXACT = frozenset(
    {
        "/",
        "/v1/setup/status",
        "/v1/setup/presets",
        "/v1/auth/login",
        "/v1/auth/register",
        "/v1/auth/whoami",
        "/favicon.ico",
    }
)

_ADMIN_CHAT_BLOCKED = ("/v1/chat/",)

_PROTECTED_OPS: dict[str, dict[str, str]] = {
    "GET": {
        # Reading another principal's harness/RSI session stream exposes
        # in-flight code, agent reasoning, and secrets in transit — the same
        # sensitivity as starting the run, so it takes the same scope. Plain
        # authentication is not enough for these read routes.
        "/v1/harness": "harness.execute",
        "/v1/rsi": "rsi.execute",
        "/v1/evolution": "rsi.execute",
        # The pending-work queue names which Runs are blocked and carries the
        # payload each node is asking a human — in-flight graph execution
        # content, the same sensitivity as the harness stream above. Scoped to
        # match the answer route: seeing a question you have no scope to answer
        # serves nobody and leaks what the Run is doing (#244).
        "/v1/hitl": "dags.write",
    },
    "DELETE": {
        "/v1/settings": "config.delete",
        "/v1/agents": "agents.delete",
        "/v1/skills": "skills.delete",
        "/v1/mcp": "mcp.delete",
        # Killing another principal's harness session is a denial of service on
        # in-flight work, so it needs the same scope that starting one does.
        "/v1/harness": "harness.execute",
        "/v1/containers": "containers.control",
        "/v1/credentials": "credentials.write",
        "/v1/dags": "dags.write",
        "/v1/schedules": "schedules.write",
        # Removing a workspace member is the same write-scope decision as
        # creating the workspace in the first place (Persona/Workspace Phase G).
        "/v1/workspaces": "workspaces.write",
    },
    "POST": {
        "/v1/settings": "config.write",
        # The whole /v1/mcp mutating surface, not just /servers: discover and
        # test connect to operator-supplied endpoints, which is the same
        # trust decision as registering one.
        "/v1/mcp": "mcp.write",
        "/v1/agents": "agents.write",
        "/v1/skills": "skills.write",
        # Talks to the Docker socket directly — host infrastructure control.
        "/v1/containers": "containers.control",
        # DAGs execute graphs whose nodes include harness/synth-DAG kinds:
        # creating or running one is agent execution, and an unscoped DAG run
        # would be a bypass of harness.execute via composition.
        "/v1/dags": "dags.write",
        # Accepting an optimizer proposal rewrites a DAG — same surface.
        "/v1/optimizer": "dags.write",
        # Answering a human pause resumes the Run that was waiting on it, and
        # the nodes that run next are the same graph nodes `/v1/dags` gates —
        # so an unscoped answer would be DAG execution reached by replying to
        # a prompt instead of by starting a run (#244). The answer is also
        # untrusted input written into graph state that later nodes read,
        # which is why the route Warden-scans it as well.
        "/v1/hitl": "dags.write",
        # A schedule is recurring autonomous execution.
        "/v1/schedules": "schedules.write",
        # Workspace sub-resource mutations (membership, persona authoring, etc.)
        # remain privileged. Creating one's own workspace tab is handled as an
        # ordinary authenticated operation in _required_permission() below.
        "/v1/workspaces": "workspaces.write",
        # The evolution tournament is the self-improvement loop's other door.
        "/v1/evolution": "rsi.execute",
        # Executes GitHub/GitLab tools with stored credentials against real
        # external trackers.
        # Audit entries name an arbitrary `actor`: an unscoped writer is a
        # log-forgery primitive, and the app writes its own entries in-process,
        # not over HTTP — no product flow needs this route unelevated.
        "/v1/audit": "audit.write",
        # The inbound harness starts a coding agent against an operator-supplied
        # `workdir`: POST /v1/harness/sessions is code execution on this host,
        # and .../send steers it. Authentication alone was already required
        # (dispatch 401s any unauthenticated /v1/ path), but *every*
        # authenticated principal could reach it — including a role="user"
        # account with permissions=[]. Deliberately its own scope rather than
        # agents.write: being cleared to edit an agent's configuration is not
        # the same as being cleared to execute code as it.
        "/v1/harness": "harness.execute",
        # RSI runs are the self-modification loop — they push branches and can
        # open PRs. Separate scope again, because granting code execution on a
        # scratch workdir is a smaller decision than granting the loop that
        # rewrites this repository.
        "/v1/rsi": "rsi.execute",
        # Capability discovery + approval resolution (approving a destructive
        # infra action is high-stakes) — gate behind config.write.
        "/v1/capabilities": "config.write",
        # Provider activation uses the LiteLLM master key, mutates the global
        # model registry, and can trigger billed calls (SPEC-072726-3439).
        "/v1/providers": "config.write",
    },
    "PUT": {
        "/v1/settings": "config.write",
        # Storing a deployment-wide LLM key in the vault — same decision
        # weight as activating it.
        "/v1/providers": "config.write",
        "/v1/mcp/servers": "mcp.write",
        "/v1/agents": "agents.write",
        "/v1/skills": "skills.write",
        "/v1/credentials": "credentials.write",
        "/v1/dags": "dags.write",
        "/v1/schedules": "schedules.write",
        # Setting a workspace's sticky per-agent tool bindings changes what
        # tools that agent may call — same write-scope posture as every
        # other workspace-settings mutation (Persona/Workspace system).
        "/v1/workspaces": "workspaces.write",
    },
    "PATCH": {
        "/v1/settings": "config.write",
        "/v1/mcp/servers": "mcp.write",
        "/v1/capabilities": "config.write",
        # Toggling a skill changes what every future agent run may do.
        "/v1/skills": "skills.write",
        # Archiving a workspace is the same write-scope decision as creating
        # or deleting one (Persona/Workspace system).
        "/v1/workspaces": "workspaces.write",
    },
}


def _matches_public_prefix(path: str, prefix: str) -> bool:
    """True if path is exactly prefix, or prefix followed by '/'.

    Plain str.startswith() would also match unrelated sibling routes that
    merely share the prefix as a string (e.g. "/healthcheck-internal"
    starting with "/health"). Mirrors the boundary fix in
    tools/sandbox/workspace.py's path-prefix allowlist.
    """
    stripped = prefix.rstrip("/")
    return path == stripped or path.startswith(stripped + "/")


def _is_public_oauth_get(method: str, path: str) -> bool:
    """Expose only exact GET routes for providers enabled in typed settings."""
    if method != "GET":
        return False
    match = _OAUTH_PUBLIC_GET_RE.fullmatch(path)
    if match is None:
        return False
    provider = match.group("provider")
    if not is_valid_oauth_provider_name(provider):
        return False
    # SECURITY-REVIEW: This is the anonymous authentication boundary. A path
    # parameter is public only after exact syntax and configured-provider checks.
    return provider in get_settings().oauth_providers


def resolve_principal(
    cookies: Mapping[str, str], authorization: str | None
) -> dict[str, Any] | None:
    session_id = cookies.get("hive_session")
    if not session_id:
        auth_header = authorization or ""
        if auth_header.startswith("Bearer "):
            session_id = auth_header[7:]
    if not session_id:
        return None
    try:
        return auth_routes.get_current_user(session_id)
    except Exception:
        return None


_ELEVATED_TASK_HEADER = "x-elevated-task"
_ELEVATED_TASK_MAX = 128


def _requested_task(request: Request) -> str | None:
    """The task id a request claims to act under, or None.

    Taken from `X-Elevated-Task`. The value is only ever used as a lookup key
    into the session's own grant map, so a forged id simply finds no grant;
    it is length-bounded anyway so a huge header cannot be carried into logs
    or comparisons. Task ids are syntax-validated at elevation time
    (`ElevateBody.validate_task_id`); anything else matches nothing.
    """
    value = request.headers.get(_ELEVATED_TASK_HEADER, "").strip()
    if not value or len(value) > _ELEVATED_TASK_MAX:
        return None
    # Keep request-side bindings on the same grammar as elevation and stored
    # grants. Length alone would still permit a malformed persisted key to be
    # addressed if it ever entered the session store.
    if not auth_routes.is_valid_task_id(value):
        return None
    return value


def principal_has_permission(user: dict[str, Any], perm: str, task_id: str | None = None) -> bool:
    """May this principal act with `perm`, under the task the request names?

    Elevation is task-scoped (#1239): a grant satisfies a check only when the
    request names the very task the grant was issued for, and only while that
    grant is still valid (`elevated_grants` is expiry-filtered upstream in
    `routes.auth.get_current_user`, which also prunes dead grants). The old
    check read a session-wide union of every task's grants, so one elevation
    covered every later request for the session's whole lifetime — the
    flattening the audit flagged. Admin keeps its bypass: that is the
    break-glass role, not an elevation.
    """
    if user.get("role") == "admin":
        return True
    user_perms = user.get("permissions", [])
    if perm not in user_perms:
        return False
    if not task_id:
        # No task named, no elevation. An unnamed request cannot be bound to
        # a grant, so answering from the union would reintroduce the
        # session-wide set this check exists to prevent.
        return False
    if not auth_routes.is_active_task_for_user(task_id, str(user.get("id") or "")):
        return False
    grants = user.get("elevated_grants") or {}
    if not isinstance(grants, dict):
        return False
    grant = grants.get(task_id)
    if not isinstance(grant, dict):
        return False
    # The grant itself is the action association: only the exact permission
    # requested by this protected operation may be exercised under this task.
    return perm in grant.get("permissions", [])


def origin_allowed(origin: str | None, host: str | None = None) -> bool:
    """Is `origin` permitted to open a credentialed connection to this server?

    Three ways to pass, in order of how often they matter:

    1. **Same-origin.** The page that opened the socket is served by this very
       server (`Origin`'s authority == the request's own `Host`). CORS never
       applies to same-origin requests, so a deployment reached at
       `http://192.0.2.1:8101` — where the SPA and the API share an origin —
       has never had any reason to list itself in `CORS_ORIGINS`, and most
       don't. Checking the configured list alone would reject the app's own
       front end on every non-localhost deployment, because the defaults in
       `config.py` only cover localhost.
    2. **No Origin at all.** curl and other non-browser callers send none.
       Origin-based rules only bind browsers; such a caller still needs a valid
       session.
    3. **Explicitly configured**, including the `"*"` wildcard that
       `CORSMiddleware` already honours for HTTP. Not honouring it here would
       mean a deployment that deliberately opened CORS still had its sockets
       refused.
    """
    if not origin:
        return True
    allowed = get_settings().cors_origins
    if "*" in allowed or origin in allowed:
        return True

    if host:
        _, _, origin_authority = origin.partition("://")
        if origin_authority and origin_authority == host:
            return True

    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if (
            path in _PUBLIC_EXACT
            or _is_public_oauth_get(request.method, path)
            or any(_matches_public_prefix(path, p) for p in _PUBLIC_PREFIXES)
            or any(path.startswith(p) for p in _PUBLIC_PREFIXES_LOOSE)
        ):
            return await call_next(request)

        # The install wizard API is only useful before first-run provisioning,
        # when no account exists yet to authenticate with. Public pre-setup;
        # normal auth applies once setup completes (same one-shot boundary as
        # /v1/setup/complete's 409 guard).
        if _matches_public_prefix(path, "/v1/install/") and not self._setup_complete():
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        if path.startswith("/v1/"):
            user = self._get_user(request)
            if user is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )

            request.state.user = user

            if user["role"] == "admin" and self._is_chat(path):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Admin account cannot use chat. Use your daily user account."
                    },
                )

            # Persona-level feedback aggregates raw entries across all
            # workspaces using that persona. A normal workspace member may not
            # inspect other workspaces' user ids, comments, or identifiers.
            # Keep the aggregate endpoint available to operators only.
            if (
                request.method == "GET"
                and path.startswith("/v1/workspaces/persona-templates/")
                and path.endswith("/feedback")
                and user.get("role") != "admin"
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Admin permission required for persona-wide feedback"},
                )

            required_perm = self._required_permission(request)
            if required_perm and not self._check_permission(
                user, required_perm, _requested_task(request)
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"Permission '{required_perm}' required. Elevate to proceed."
                    },
                )

        return await call_next(request)

    def _setup_complete(self) -> bool:
        try:
            return bool(setup_routes._is_setup_complete())
        except Exception:
            # Fail closed: if setup state can't be read, require auth.
            return True

    def _get_user(self, request: Request) -> dict[str, Any] | None:
        authorization = request.headers.get("Authorization")
        user = resolve_principal(request.cookies, authorization)
        if user is not None:
            return user
        # Scoped to the voice prefix on purpose. Resolving the device
        # credential for every path would make one key a second way into the
        # whole API; here it opens the surface it was issued for and nothing
        # else, and a caller holding it still gets that account's own
        # authorization for everything downstream.
        if _matches_public_prefix(request.url.path, _VOICE_PREFIX):
            return voice_identity.principal_for(authorization)
        return None

    def _is_chat(self, path: str) -> bool:
        return any(path.startswith(p) for p in _ADMIN_CHAT_BLOCKED)

    def _required_permission(self, request: Request) -> str | None:
        method_perms = _PROTECTED_OPS.get(request.method, {})
        path = request.url.path
        # Creating a workspace tab is a normal authenticated-user action. The
        # route makes the caller its owner, so requiring task-scoped elevation
        # here made the first-run daily account's workspace UI unusable.
        if request.method == "POST" and path.rstrip("/") == "/v1/workspaces":
            return None
        # Agent invoke (POST /v1/agents/{id}/invoke) is autonomous read — don't
        # gate behind elevation. Match the trailing segment, not a bare
        # substring: "in path" would also exempt any future route that merely
        # contains "/invoke" elsewhere (e.g. "/v1/agents/invoke-history").
        if path.endswith("/invoke"):
            return None
        # Thumbs +/- feedback (POST /v1/dag-runs/{id}/feedback,
        # POST /v1/workspaces/{id}/feedback) is a low-stakes reaction, not a
        # mutating operation on the thing itself — any authenticated member
        # can leave it, same posture as dag-runs' pre-existing unrestricted
        # feedback route. The route itself still checks workspace membership.
        if path.endswith("/feedback"):
            return None
        # DAG-Run inspection — GET /v1/dag-runs (list), GET /v1/dag-runs/{id}
        # (detail), GET /v1/dag-runs/{id}/events (SSE) — and the eval-judge
        # read side over the same runs (GET /v1/eval-judge verdict list,
        # GET /v1/eval-judge/{run_id}) — is deliberately NOT elevation-gated,
        # because elevation adds no boundary here: the responses are scoped to
        # the caller's canonical Workspace universe inside the routes
        # themselves, through services/dag_run_inspection (#1174) — the same
        # authority the workspace/agents routes answer through. Authentication
        # alone is not authorization: a member of no Workspace sees an empty
        # list, and an out-of-scope run id gets the same 404 a missing run
        # gets, so the response never confirms a run exists beyond the
        # caller's boundary. (Spell the GET match out rather than listing the
        # routes in _PROTECTED_OPS: these routes stay None on purpose, and the
        # comment above is the reason.) The /feedback POST sub-routes above
        # keep their own pre-existing posture; /v1/dag-runs/retention is
        # covered by this match too and carries deployment constants, not run
        # data. The eval-judge trigger (POST /v1/eval-judge/{run_id}) is
        # likewise authenticated-only and scoped in-route by the same
        # inspection door before anything is scored.
        if request.method == "GET" and (path == "/v1/dag-runs" or path.startswith("/v1/dag-runs/")):
            return None
        if request.method == "GET" and (
            path == "/v1/eval-judge" or path.startswith("/v1/eval-judge/")
        ):
            return None
        for prefix, perm in method_perms.items():
            if path.startswith(prefix):
                return perm
        return None

    def _check_permission(
        self, user: dict[str, Any], perm: str, task_id: str | None = None
    ) -> bool:
        return principal_has_permission(user, perm, task_id)
