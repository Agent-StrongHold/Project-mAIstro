"""Credential security audit — task #26.

The user's iron rules (verbatim from session memory):
- 'only the user can see their own — NOT EVEN IN LOGS OR ADMIN SECTION'
- 'they need to be encrypted at rest and in transit'
- 'we don't put the pats in the env'

This test file pins those invariants so any regression on a future PR
fails CI:

  1. An admin login CANNOT read another user's credentials list
  2. An admin login CANNOT decrypt another user's secrets
  3. The /v1/audit log NEVER contains the plaintext secret in any
     entry (action 'credential_save' has the provider id only)
  4. The /v1/credentials response NEVER contains a 'secret' field for
     any provider — only `configured: bool` + non-secret metadata
  5. The /v1/credentials/{id}/config payload is scoped to the calling
     user; another user cannot read it (the per-user store key)
  6. CredentialStore.use_secret is the ONLY path that returns the
     decrypted value, and it MUST be via callback (not return)
"""

from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient
from main import app


def _login(username: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return c


def _register(username: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post(
        "/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
        },
    )
    assert r.status_code == 200, r.text
    return c


def test_admin_cannot_read_other_users_credentials_list() -> None:
    """The 'NOT EVEN IN ADMIN SECTION' rule. Admin sees their OWN
    credentials only, never anyone else's. The /v1/credentials response
    must reflect the session-bound user, not be admin-elevated."""
    alice = _register("audit_alice", "securepass1")
    alice.put("/v1/credentials/jira", json={"secret": "alice-only-secret"})

    admin = _login("testadmin", "adminpass")
    listing = admin.get("/v1/credentials")
    assert listing.status_code == 200
    rows = listing.json()["credentials"]
    # The admin's view of "jira" is THEIR own (which is unconfigured).
    # Critically: the response must NOT carry alice's plaintext.
    blob = listing.text
    assert "alice-only-secret" not in blob
    jira_row = next(r for r in rows if r["id"] == "jira")
    # Admin's own row is unconfigured (admin hasn't set their own jira PAT)
    assert jira_row["configured"] is False


def test_audit_log_never_contains_plaintext_secret() -> None:
    """credential_save audit entries record the provider id only.
    The secret string must NEVER appear in any audit detail / target."""
    c = _register("audit_log_user", "securepass1")
    secret = "audit-log-secret-xyz-789"
    c.put("/v1/credentials/jira", json={"secret": secret})

    audit = c.get("/v1/audit").json()
    blob = str(audit)
    assert secret not in blob


def test_credentials_list_response_carries_no_secret_field() -> None:
    """The /v1/credentials list response is sent to the BROWSER. It must
    never echo back the plaintext (or any encoding of it)."""
    c = _register("audit_no_echo", "securepass1")
    secret = "no-echo-secret" + "-abc-456"
    c.put("/v1/credentials/airtable", json={"secret": secret})

    listing = c.get("/v1/credentials")
    blob = listing.text
    assert secret not in blob
    # Per-row shape: configured + metadata, never 'secret'
    for row in listing.json()["credentials"]:
        assert "secret" not in row


def test_credentials_config_does_not_leak_across_users() -> None:
    """The non-secret per-user config (e.g. Airtable base_id) is still
    user-scoped — another user cannot read alice's base_id."""
    alice = _register("audit_cfg_alice", "securepass1")
    alice.put(
        "/v1/credentials/airtable/config",
        json={"config": {"base_id": "appALICE", "table": "Alice's Table"}},
    )
    bob = _register("audit_cfg_bob", "securepass1")
    bob_cfg = bob.get("/v1/credentials/airtable/config").json()
    assert bob_cfg["config"] == {}  # bob has no config; not alice's
    # And the cross-user list endpoint shouldn't surface alice's config either
    bob_list = bob.get("/v1/credentials").json()
    airtable = next(r for r in bob_list["credentials"] if r["id"] == "airtable")
    assert airtable["config_values"] == {}


def test_credential_store_use_secret_passes_to_callback_only() -> None:
    """The store-level invariant: use_secret returns the CALLBACK's
    return value, not the secret. The secret never escapes the closure."""
    import tempfile

    from cryptography.fernet import Fernet

    from maistro.credentials.store import UserCredentialStore as CredentialStore

    with tempfile.TemporaryDirectory() as tmp:
        # Direct unit test on the store — bypasses HTTP, isolates the
        # invariant.
        master_key = Fernet.generate_key()
        store = CredentialStore(
            data_dir=pathlib.Path(tmp),
            master_key=master_key,
        )
        store.set_secret("u1", "jira", "real-secret-here")

        # Callback returns a derived value; the secret string is never
        # returned to the caller.
        was_called_with = []
        derived = store.use_secret(
            "u1",
            "jira",
            lambda s: (was_called_with.append(len(s)), "DERIVED")[1],
        )
        assert derived == "DERIVED"
        assert was_called_with == [len("real-secret-here")]


def test_admin_session_cannot_call_use_secret_for_other_user() -> None:
    """The store keys on user_id literally. There is no admin override."""
    import tempfile

    from cryptography.fernet import Fernet

    from maistro.credentials.store import (
        CredentialNotFound,
    )
    from maistro.credentials.store import (
        UserCredentialStore as CredentialStore,
    )

    with tempfile.TemporaryDirectory() as tmp:
        store = CredentialStore(
            data_dir=pathlib.Path(tmp),
            master_key=Fernet.generate_key(),
        )
        store.set_secret("alice", "jira", "alice-secret")

        # Even if a route handler bug used the wrong user_id, the store
        # raises — admin cannot read alice's secret by guessing user IDs.
        try:
            store.use_secret("admin", "jira", lambda s: s)
            raise AssertionError("expected CredentialNotFound")
        except CredentialNotFound:
            pass
        try:
            store.use_secret("bob", "jira", lambda s: s)
            raise AssertionError("expected CredentialNotFound")
        except CredentialNotFound:
            pass


# --- Architecture fitness: the lambda-s-s anti-pattern -----------------


def test_no_new_lambda_s_s_in_critical_callsites() -> None:
    """Architecture fitness test: locate every `lambda s: s` call to
    use_secret in the codebase. The pattern is permitted ONLY in the
    legacy locations that are tracked for refactor; any NEW callsite
    must use a proper async-callback form so the secret never escapes
    the closure.

    Allowlist baseline (2026-05-22) — these are tracked for refactor in
    the audit follow-up (separate task). Any NEW usage fails the gate.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    hits: list[str] = []
    for py in repo_root.rglob("*.py"):
        if any(part in {".venv", "tests", "__pycache__", "build"} for part in py.parts):
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ln, line in enumerate(src.splitlines(), 1):
            if "use_secret" in line and "lambda s: s" in line:
                rel = str(py.relative_to(repo_root))
                hits.append(f"{rel}:{ln}")

    # Allowlist — files known to use the pattern; tracked for refactor.
    # Paths are relative to repo_root = parents[3] (the `packages/` dir).
    ALLOWLIST = {
        "hive-conductor/backend/services/mcp_client.py:51",
        # Centralised secret helpers — one lambda per file (refactored from inline callsites).
        # `routes/agents.py` left this list in #129: `_build_invoke_context` read
        # Atlassian PATs only for `POST /{agent_id}/invoke`, and both went with
        # POC mode. One fewer place a secret is read, not one fewer line pinned.
        "hive-conductor/backend/services/program_hyperagent.py:28",
        "hive-conductor/backend/services/tool_primitives.py:66",
    }
    new = [h for h in hits if h not in ALLOWLIST]
    assert not new, (
        f"NEW 'use_secret(..., lambda s: s)' callsite(s) detected — secrets "
        f"must use a proper callback so they never escape the closure. "
        f"Offending: {new}"
    )
