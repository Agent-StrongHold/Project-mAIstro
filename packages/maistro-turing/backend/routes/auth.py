"""Human session auth for the Turing backend.

Minimal session-cookie login mirroring hive-conductor's posture: POST credentials
→ opaque session id in the `turing_session` cookie; the middleware resolves the
cookie back to a user via get_current_user().

GAP: users and password checks are an in-memory dev stub. A production deployment
reuses hive-conductor's user store + Argon2id verification (the same accounts the
rest of the system uses) rather than this local table. The session/cookie shape
is kept identical so that swap touches only the user lookup.

The stub accounts below are only registered when TURING_ALLOW_DEV_AUTH=1 is set
(tests set this via conftest). Without it, `_USERS` is empty and every login
attempt 401s — there is no universal known admin login reachable by default.
"""

from __future__ import annotations

import os
from secrets import token_urlsafe

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["auth"])

# user_id -> {username, role}
_DEV_USERS: dict[str, dict[str, str]] = {
    "user": {"username": "testuser", "password": "testpass", "role": "user"},
    "admin": {"username": "testadmin", "password": "adminpass", "role": "admin"},
}
_USERS: dict[str, dict[str, str]] = (
    _DEV_USERS if os.environ.get("TURING_ALLOW_DEV_AUTH") == "1" else {}
)

# session_id -> user_id
_SESSIONS: dict[str, str] = {}


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str
    password: str


def get_current_user(session_id: str) -> dict | None:
    user_id = _SESSIONS.get(session_id)
    if user_id is None:
        return None
    record = _USERS.get(user_id)
    if record is None:
        return None
    return {"id": user_id, "username": record["username"], "role": record["role"]}


@router.post("/login")
def login(body: LoginBody, response: Response) -> dict:
    for user_id, record in _USERS.items():
        if record["username"] == body.username and record["password"] == body.password:
            session_id = token_urlsafe(32)
            _SESSIONS[session_id] = user_id
            response.set_cookie(
                "turing_session",
                session_id,
                httponly=True,
                samesite="lax",
            )
            return {"id": user_id, "username": record["username"], "role": record["role"]}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/whoami")
def whoami(request: Request) -> dict:
    # whoami is a public path (the middleware skips it), so resolve the cookie
    # here rather than relying on request.state.user.
    session_id = request.cookies.get("turing_session", "")
    user = get_current_user(session_id) if session_id else None
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, **user}
