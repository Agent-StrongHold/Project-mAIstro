"""Registration policy (#313): closed after setup, opened only by admin or invitation.

The defect these tests pin: `_registration_allowed()` answered
`len(stores.users) > 0`, so on a provisioned instance — the exact state
conftest seeds — the unauthenticated register route stayed open forever.
Completing initial setup *enabled* public signup instead of closing it.

The policy under test inverts the default: registration is closed unless a
durable record says otherwise, bootstrap mints the first owner exactly once
through a conflict-safe setup claim, invitations are single-use by atomic
insert, and every corrupt-or-missing shape of the policy record reads as
"closed". Covers the issue's six required scenarios: first setup,
post-setup registration, invitation, restart, concurrent bootstrap, and
corrupted state — plus the public-surface leak rule (`/v1/setup/status`
publishes the mode, not the accounts).

HTTP tests use `TestClient(app)` without entering it as a context manager,
matching this suite's convention (see test_security_headers.py): entering it
would run the real lifespan, which starts a Foundation against the host.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture(autouse=True)
def _isolated_registration_state(monkeypatch: pytest.MonkeyPatch):
    """Each test gets a fresh policy, invitation store, and setup markers.

    `stores.registration_invitations` and the setup records in
    `stores.sessions` are process-global in memory mode; users are
    snapshotted because the invitation tests create real (Argon2-hashed)
    accounts that must not leak into other suites' assumptions.
    """
    import stores
    from services import registration_policy
    from services.model_store import JsonStore

    registration_policy.reset()
    fresh_invitations = JsonStore("registration_invitations")
    monkeypatch.setattr(stores, "registration_invitations", fresh_invitations)
    for key in stores.sessions.keys() & {"__hive_setup__", "__hive_setup_claim__"}:
        stores.sessions.pop(key, None)
    users_snapshot = copy.deepcopy(dict(stores.users.items()))

    yield

    registration_policy.reset()
    # A durability test may leave `stores.registration_invitations` pointing at
    # a store whose SQLite writer is closed; clear the unpersisted one this
    # fixture installed instead, and let monkeypatch restore the module global.
    stores.registration_invitations = fresh_invitations
    for key in list(fresh_invitations.keys()):
        fresh_invitations.pop(key, None)
    for key in stores.sessions.keys() & {"__hive_setup__", "__hive_setup_claim__"}:
        stores.sessions.pop(key, None)
    for key in list(stores.users.keys()):
        if key not in users_snapshot:
            stores.users.pop(key, None)
    for key, value in users_snapshot.items():
        stores.users[key] = value


def _register_body(username: str, invitation: str | None = None) -> dict:
    body = {
        "username": username,
        "password": "securepass1",
        "confirm_password": "securepass1",
    }
    if invitation is not None:
        body["invitation_token"] = invitation
    return body


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


class TestPostSetupRegistrationIsClosed:
    """The headline fix: a provisioned hive refuses anonymous signup."""

    def test_stranger_cannot_register_after_setup(self) -> None:
        """conftest seeds users — the state the old gate read as 'open'."""
        from main import app

        client = TestClient(app)
        r = client.post("/v1/auth/register", json=_register_body("stranger"))

        assert r.status_code == 403
        assert r.json()["detail"] == "Registration is closed on this hive."

    def test_blocked_attempts_are_audited_with_a_reason(self) -> None:
        import stores
        from main import app

        client = TestClient(app)
        client.post("/v1/auth/register", json=_register_body("stranger2"))

        blocked = [
            entry
            for entry in stores.audit_log.values()
            if isinstance(entry, dict) and entry.get("action") == "register_blocked"
        ]
        assert blocked, "a refused registration must reach the audit log"
        assert blocked[-1]["detail"]["reason"] == "closed"

    def test_missing_record_means_closed(self) -> None:
        from services import registration_policy as rp

        decision = rp.evaluate_registration(None)
        assert decision.allowed is False
        assert decision.reason == "closed"

    def test_open_policy_cannot_mint_the_first_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bootstrap belongs to the one-shot setup state alone: even a forced
        `open` record is inert while no account exists (#313 AC)."""
        import stores
        from models.schemas import HiveUser
        from services import registration_policy as rp
        from services.model_store import ModelStore

        monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))
        rp.set_mode("open", actor="admin:test")

        decision = rp.evaluate_registration(None)
        assert decision.allowed is False
        assert decision.reason == "bootstrap_incomplete"

    def test_invitation_cannot_mint_the_first_owner_either(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import stores
        from models.schemas import HiveUser
        from services import registration_policy as rp
        from services.model_store import ModelStore

        monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))
        token = rp.issue_invitation(actor="admin:test")["token"]

        decision = rp.evaluate_registration(token)
        assert decision.allowed is False
        assert decision.reason == "bootstrap_incomplete"


class TestAdminPolicySurface:
    """Registration opens only by explicit, auditable admin action."""

    def test_admin_can_open_and_then_close_registration(self) -> None:
        from main import app

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")

        opened = admin.put("/v1/auth/registration/policy", json={"mode": "open"})
        assert opened.status_code == 200, opened.text
        assert opened.json()["policy"]["mode"] == "open"

        stranger = TestClient(app)
        allowed = stranger.post("/v1/auth/register", json=_register_body("invited-by-policy"))
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["user"]["role"] == "user"

        closed = admin.put("/v1/auth/registration/policy", json={"mode": "closed"})
        assert closed.status_code == 200
        late = TestClient(app)
        refused = late.post("/v1/auth/register", json=_register_body("late-stranger"))
        assert refused.status_code == 403
        assert refused.json()["detail"] == "Registration is closed on this hive."

    def test_daily_account_cannot_change_the_policy(self) -> None:
        from main import app

        daily = TestClient(app)
        _login(daily, "testuser", "testpass")

        r = daily.put("/v1/auth/registration/policy", json={"mode": "open"})
        assert r.status_code == 403

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")
        view = admin.get("/v1/auth/registration/policy")
        assert view.json()["policy"]["mode"] == "closed"

    def test_anonymous_cannot_read_the_admin_policy_view(self) -> None:
        from main import app

        client = TestClient(app)
        assert client.get("/v1/auth/registration/policy").status_code == 401

    def test_unknown_mode_is_refused_without_touching_the_record(self) -> None:
        from main import app

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")

        r = admin.put("/v1/auth/registration/policy", json={"mode": "banana"})
        assert r.status_code == 422

        view = admin.get("/v1/auth/registration/policy").json()["policy"]
        assert view["mode"] == "closed"

    def test_admin_view_reports_record_health(self) -> None:
        from main import app

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")
        view = admin.get("/v1/auth/registration/policy").json()["policy"]

        assert view["mode"] == "closed"
        assert view["record_valid"] is True
        assert view["durable"] is False  # tests run the ephemeral record store
        assert "updated_by" in view


class TestInvitations:
    """A valid invitation is the only anonymous path when the policy is closed."""

    def test_invitation_permits_exactly_one_registration(self) -> None:
        from main import app

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")
        issued = admin.post("/v1/auth/registration/invitations", json={})
        assert issued.status_code == 200, issued.text
        token = issued.json()["token"]

        stranger = TestClient(app)
        first = stranger.post("/v1/auth/register", json=_register_body("invited-friend", token))
        assert first.status_code == 200, first.text
        who = stranger.get("/v1/auth/whoami").json()
        assert who["authenticated"] is True
        assert who["user"]["username"] == "invited-friend"

        replay = stranger.post("/v1/auth/register", json=_register_body("replay-user", token))
        assert replay.status_code == 403
        assert replay.json()["detail"] == "Invalid or expired invitation."

        listing = admin.get("/v1/auth/registration/invitations").json()["invitations"]
        assert listing[0]["redeemed"] is True
        assert "token" not in listing[0]

    def test_garbage_tokens_are_refused_uniformly(self) -> None:
        from main import app

        client = TestClient(app)
        for bogus in ("not-a-token", "deadbeef", "A" * 128):
            r = client.post("/v1/auth/register", json=_register_body(f"u-{bogus[:4]}", bogus))
            assert r.status_code == 403, bogus
            assert r.json()["detail"] == "Invalid or expired invitation."
        # An over-long code is refused by validation before it reaches the
        # policy — same answer, and it leaks no account information either.
        oversized = client.post("/v1/auth/register", json=_register_body("u-huge", "x" * 512))
        assert oversized.status_code == 422

    def test_expired_invitation_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services import registration_policy as rp

        token = rp.issue_invitation(actor="admin:test")["token"]
        # The default TTL is 7 days; move the policy clock past it.
        monkeypatch.setattr(rp, "_now", lambda: datetime.now(UTC) + timedelta(days=8))

        decision = rp.evaluate_registration(token)
        assert decision.allowed is False
        assert decision.reason == "invalid_invitation"
        assert rp.redeem_invitation(token, username="too-late") is False

    def test_non_admin_cannot_issue_invitations(self) -> None:
        from main import app

        daily = TestClient(app)
        _login(daily, "testuser", "testpass")
        r = daily.post("/v1/auth/registration/invitations", json={})
        assert r.status_code == 403

    def test_out_of_range_ttl_and_long_notes_are_refused(self) -> None:
        from main import app

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")

        too_short = admin.post("/v1/auth/registration/invitations", json={"ttl_seconds": 1})
        assert too_short.status_code == 422
        long_note = admin.post("/v1/auth/registration/invitations", json={"note": "n" * 201})
        assert long_note.status_code == 422

    def test_issued_tokens_are_not_readable_back(self) -> None:
        from services import registration_policy as rp

        issued = rp.issue_invitation(actor="admin:test", note="for the demo")
        listing = rp.list_invitations()

        assert len(listing) == 1
        assert "token" not in listing[0]
        assert issued["token"] not in json.dumps(listing)
        assert listing[0]["note"] == "for the demo"
        assert listing[0]["invitation_id"] == issued["invitation_id"]

    def test_concurrent_redemption_creates_exactly_one_account(self) -> None:
        """One invitation, four simultaneous strangers: the conflict-safe
        insert spends it exactly once, and the losers create nothing."""
        import stores
        from main import app
        from services import registration_policy as rp

        token = rp.issue_invitation(actor="admin:test")["token"]
        before = len(stores.users)
        outcomes: list[int] = []
        barrier = threading.Barrier(4)

        def attempt(i: int) -> None:
            client = TestClient(app)
            barrier.wait()
            r = client.post("/v1/auth/register", json=_register_body(f"race-{i}", token))
            outcomes.append(r.status_code)

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert outcomes.count(200) == 1
        assert outcomes.count(403) == 3
        assert len(stores.users) == before + 1

    def test_invitation_that_loses_the_redemption_race_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The spend must win, not the check: a token that passed
        `evaluate_registration` but fails `redeem_invitation` — the window a
        concurrent redemption or a just-landed expiry opens — is refused, and
        audited as `invitation_race` rather than as a closed hive."""
        import stores
        from main import app
        from services import registration_policy as rp

        token = rp.issue_invitation(actor="admin:test")["token"]
        before = len(stores.users)
        # Deterministic stand-in for losing the race: the check already said
        # yes, so only the spend's verdict can refuse the attempt now.
        monkeypatch.setattr(rp, "redeem_invitation", lambda *_args, **_kwargs: False)

        client = TestClient(app)
        r = client.post("/v1/auth/register", json=_register_body("race-loser", token))

        assert r.status_code == 403
        assert r.json()["detail"] == "Invalid or expired invitation."
        blocked = [
            entry
            for entry in stores.audit_log.values()
            if isinstance(entry, dict) and entry.get("action") == "register_blocked"
        ]
        assert blocked, "the race refusal must reach the audit log"
        assert blocked[-1]["detail"]["reason"] == "invitation_race"
        assert len(stores.users) == before


class TestRegisterBodyNormalizesInvitationTokens:
    """A blank code is the absence of a code, not an invalid one.

    The validator folds `null` and whitespace-only tokens to `None`, so they
    meet the same "closed" refusal as no token at all — the uniform refusal,
    with no account information carried back either way.
    """

    def test_explicit_null_invitation_token_reads_as_absent(self) -> None:
        from main import app

        client = TestClient(app)
        r = client.post(
            "/v1/auth/register",
            json={
                "username": "null-token",
                "password": "securepass1",
                "confirm_password": "securepass1",
                "invitation_token": None,
            },
        )

        assert r.status_code == 403
        assert r.json()["detail"] == "Registration is closed on this hive."

    def test_whitespace_invitation_token_reads_as_absent(self) -> None:
        from main import app

        client = TestClient(app)
        r = client.post(
            "/v1/auth/register",
            json={
                "username": "blank-token",
                "password": "securepass1",
                "confirm_password": "securepass1",
                "invitation_token": "   ",
            },
        )

        assert r.status_code == 403
        assert r.json()["detail"] == "Registration is closed on this hive."


class TestAdminSurfaceFailClosedOnLostWrites:
    """The admin surface refuses loudly when a write cannot be trusted."""

    def test_bearer_only_auth_does_not_satisfy_the_route_level_guard(self) -> None:
        """The middleware honours `Authorization: Bearer <session>`; the
        registration-policy routes read only the `hive_session` cookie. A
        bearer-only caller passes the middleware and is still refused by the
        route's own 401 — a different detail than the middleware's, which is
        how the guard under test is the one answering."""
        from main import app

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")
        session_id = admin.cookies.get("hive_session")
        assert session_id, "login must set the session cookie the routes read"

        bearer_only = TestClient(app)
        r = bearer_only.get(
            "/v1/auth/registration/policy",
            headers={"Authorization": f"Bearer {session_id}"},
        )

        assert r.status_code == 401
        assert r.json()["detail"] == "No session"

    def test_policy_change_that_cannot_persist_answers_503(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mode change whose write was not observed back is reported as
        `not persisted`, never as success (#334's rule, applied to #313)."""
        from main import app
        from services import registration_policy

        def _lost(*_args: object, **_kwargs: object) -> dict:
            raise registration_policy.RegistrationPolicyError("simulated write loss")

        monkeypatch.setattr(registration_policy, "set_mode", _lost)

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")
        r = admin.put("/v1/auth/registration/policy", json={"mode": "open"})

        assert r.status_code == 503
        assert "registration policy was not persisted" in r.json()["detail"]
        # And the record did not move.
        view = admin.get("/v1/auth/registration/policy").json()["policy"]
        assert view["mode"] == "closed"

    def test_invitation_issue_that_cannot_persist_answers_503(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from main import app
        from services import registration_policy

        def _lost(*_args: object, **_kwargs: object) -> dict:
            raise registration_policy.RegistrationPolicyError("simulated write loss")

        monkeypatch.setattr(registration_policy, "issue_invitation", _lost)

        admin = TestClient(app)
        _login(admin, "testadmin", "adminpass")
        r = admin.post("/v1/auth/registration/invitations", json={})

        assert r.status_code == 503
        assert "invitation was not persisted" in r.json()["detail"]
        assert registration_policy.list_invitations() == []


class TestFirstSetupIsOneShot:
    """Bootstrap: first owner via setup only, exactly once, retryably."""

    @staticmethod
    def _fresh_instance(monkeypatch: pytest.MonkeyPatch) -> None:
        import stores
        from models.schemas import HiveUser
        from routes import setup as setup_routes
        from services.model_store import ModelStore

        monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))
        monkeypatch.setattr(setup_routes, "_get_kv", lambda: None)

    def test_first_setup_creates_the_owner_and_closes_registration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import stores
        from routes.setup import complete_setup
        from services import registration_policy as rp

        self._fresh_instance(monkeypatch)

        out = complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "firstadmin",
                "admin_password": "s3cret-admin",
                "user_username": "firstuser",
                "user_password": "s3cret-user",
            }
        )

        assert out["setup_complete"] is True
        assert stores.users["admin"].username == "firstadmin"
        policy = rp.describe()
        assert policy["mode"] == "closed"
        assert policy["updated_by"] == "setup"

    def test_failed_first_run_releases_the_claim_so_setup_stays_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Partial initialization must not brick bootstrap (#313: the failure
        direction is closed-for-registration, never locked-for-setup)."""
        import stores
        from routes.setup import complete_setup

        self._fresh_instance(monkeypatch)

        # A None entry makes `from maistro.identity import ...` raise
        # ImportError — the missing-extra failure setup must survive.
        saved = sys.modules.get("maistro.identity")
        sys.modules["maistro.identity"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(HTTPException) as exc_info:
                complete_setup(
                    {
                        "hardware_preset": "auto",
                        "admin_username": "firsttry",
                        "admin_password": "s3cret-admin",
                        "user_username": "firstuser",
                        "user_password": "s3cret-user",
                        "optional_modules": ["crypto_identity"],
                    }
                )
            assert exc_info.value.status_code == 503
        finally:
            if saved is None:
                del sys.modules["maistro.identity"]
            else:
                sys.modules["maistro.identity"] = saved

        assert "__hive_setup_claim__" not in stores.sessions
        assert len(stores.users) == 0

        retry = complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "secondtry",
                "admin_password": "s3cret-admin",
                "user_username": "u2",
                "user_password": "s3cret-user",
            }
        )
        assert retry["setup_complete"] is True
        assert stores.users["admin"].username == "secondtry"

    def test_concurrent_first_user_attempts_create_exactly_one_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import stores
        from routes.setup import complete_setup

        self._fresh_instance(monkeypatch)
        outcomes: list[tuple[str, int]] = []
        barrier = threading.Barrier(4)

        def attempt(i: int) -> None:
            try:
                barrier.wait()
                complete_setup(
                    {
                        "hardware_preset": "auto",
                        "admin_username": f"racer-{i}",
                        "admin_password": "s3cret-admin",
                        "user_username": f"raceru-{i}",
                        "user_password": "s3cret-user",
                    }
                )
                outcomes.append(("ok", i))
            except HTTPException as exc:
                outcomes.append(("refused", exc.status_code))

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert [outcome for outcome, _ in outcomes].count("ok") == 1
        assert {status for outcome, status in outcomes if outcome == "refused"} == {409}
        # Exactly one owner: the winner's two accounts, nobody else's.
        assert len(stores.users) == 2
        admins = [user for user in stores.users.values() if user.role == "admin"]
        assert len(admins) == 1
        winner = next(i for outcome, i in outcomes if outcome == "ok")
        assert admins[0].username == f"racer-{winner}"


class TestSetupGuardEdges:
    """The one-shot guard's refusal shapes, each pinned deterministically.

    The barrier test above exercises the claim race statistically; here each
    loser shape is forced on purpose, because a race whose timing CI never
    produced reads as covered-in-principle and uncovered-in-fact — exactly
    the hole the diff-coverage gate exists to name.
    """

    @staticmethod
    def _retryable_instance(monkeypatch: pytest.MonkeyPatch) -> None:
        """A first-run-shaped instance: guard says incomplete, users empty.

        Same arrangement as test_settings_durability.py's direct-call tests:
        the conftest-seeded session is always past setup, and un-provisioning
        the app would test the fixture rather than the handler.
        """
        import stores
        from models.schemas import HiveUser
        from routes import setup as setup_routes
        from services.model_store import ModelStore

        monkeypatch.setattr(setup_routes, "_is_setup_complete", lambda: False)
        monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))

    @staticmethod
    def _full_body() -> dict:
        return {
            "hardware_preset": "auto",
            "admin_username": "guardadmin",
            "admin_password": "s3cret-admin",
            "user_username": "guarduser",
            "user_password": "s3cret-user",
        }

    @pytest.mark.parametrize(
        "missing",
        ["hardware_preset", "admin_password", "user_password"],
    )
    def test_missing_required_fields_are_refused_422(
        self, monkeypatch: pytest.MonkeyPatch, missing: str
    ) -> None:
        from routes.setup import complete_setup

        self._retryable_instance(monkeypatch)
        body = self._full_body()
        del body[missing]

        with pytest.raises(HTTPException) as exc_info:
            complete_setup(body)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == f"{missing} required"
        # Refused before the claim, so before any account exists.
        import stores

        assert "__hive_setup_claim__" not in stores.sessions
        assert len(stores.users) == 0

    def test_first_run_that_loses_the_claim_race_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard passed, insert lost: the deterministic shape of the race —
        another writer claimed between the completeness check and the
        conflict-safe insert, and this attempt must be refused before it can
        write an admin credential over the winner's."""
        import stores
        from routes.setup import complete_setup

        self._retryable_instance(monkeypatch)
        monkeypatch.setattr(stores.sessions, "put_if_absent", lambda *_a, **_k: False)

        with pytest.raises(HTTPException) as exc_info:
            complete_setup(self._full_body())

        assert exc_info.value.status_code == 409
        assert "Setup already complete" in exc_info.value.detail
        assert len(stores.users) == 0

    def test_policy_closeout_that_cannot_persist_fails_setup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The #313 close-out write is part of setup's contract: if the
        registration-policy record cannot be persisted, setup must not
        report success — and must stay retryable (the claim is released)."""
        import stores
        from routes.setup import complete_setup
        from services import registration_policy as rp

        self._retryable_instance(monkeypatch)

        def _lost() -> None:
            raise rp.RegistrationPolicyError("simulated write loss")

        monkeypatch.setattr(rp, "close_after_setup", _lost)
        with pytest.raises(HTTPException) as exc_info:
            complete_setup(self._full_body())

        assert exc_info.value.status_code == 503
        assert "registration policy was not persisted" in str(exc_info.value.detail)
        # The rollback released the claim: a failed first run stays retryable.
        assert "__hive_setup_claim__" not in stores.sessions


class TestPersistedSetupIsOneShot:
    """A persisted run: the setup record in the KV store, not the account
    list, is the "setup happened" signal (#313's inversion of #334's
    loud-failure pattern)."""

    def test_setup_is_one_shot_against_the_persisted_record(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        import stores
        from models.schemas import HiveUser
        from routes import setup as setup_routes
        from services.model_store import JsonStore, ModelStore

        from maistro.state import PersistedStore, State

        state = State(db_path=tmp_path / "one-shot.db")
        persisted = PersistedStore(state)
        persisted.initialize()
        monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))
        kv_sessions = JsonStore("sessions", persisted=persisted)
        kv_sessions.initialize()
        # Restored by hand rather than monkeypatch: the module autouse fixture
        # pops the setup markers from whatever `stores.sessions` is at ITS
        # teardown, which runs after monkeypatch's — popping from a KV store
        # whose State is already closed would raise. Restoring first keeps the
        # fixture's teardown on the ephemeral store it expects.
        original_sessions = stores.sessions
        stores.sessions = kv_sessions
        try:
            body = {
                "hardware_preset": "auto",
                "admin_username": "kv-admin",
                "admin_password": "s3cret-admin",
                "user_username": "kv-user",
                "user_password": "s3cret-user",
            }
            out = setup_routes.complete_setup(body)
            assert out["setup_complete"] is True
            # The durable marker is what the guard reads now, not the users it
            # created: the record is present, so the answer is one-shot.
            assert setup_routes._is_setup_complete() is True

            with pytest.raises(HTTPException) as exc_info:
                setup_routes.complete_setup({**body, "admin_username": "second-run"})
            assert exc_info.value.status_code == 409
            assert "Setup already complete" in exc_info.value.detail
            # The winner's accounts survived the refused re-run.
            assert stores.users["admin"].username == "kv-admin"
        finally:
            stores.sessions = original_sessions
            state.flush()
            state.close()


class TestCorruptedStateFailsClosed:
    """Every unreadable record shape reads as `closed`."""

    class _JunkRecordStore:
        """A record store holding exactly the corrupt document given."""

        def __init__(self, document: str) -> None:
            self._document = document

        @property
        def durable(self) -> bool:
            return False

        def read(self) -> str | None:
            return self._document

        def write(self, document: str) -> None:  # pragma: no cover - read-side fixture
            self._document = document

    @pytest.mark.parametrize(
        "document",
        [
            "not json at all {{{",
            '"closed"',  # valid JSON, not an object
            '{"schema_version": 1, "mode": "banana"}',  # unknown mode
            '{"schema_version": 2, "mode": "closed"}',  # newer build's record
            '{"mode": "open"}',  # missing envelope version
        ],
    )
    def test_corrupt_records_read_as_closed(self, document: str) -> None:
        from services import registration_policy as rp

        rp.configure(store=self._JunkRecordStore(document))

        assert rp.current_mode() == "closed"
        decision = rp.evaluate_registration(None)
        assert decision.allowed is False
        assert decision.reason == "closed"
        view = rp.describe()
        assert view["record_present"] is True
        assert view["record_valid"] is False

    def test_corrupt_record_does_not_stop_an_admin_repair(self) -> None:
        from services import registration_policy as rp

        rp.configure(store=self._JunkRecordStore('{"schema_version": 1, "mode": "banana"}'))
        policy = rp.set_mode("closed", actor="admin:testadmin")
        assert policy["record_valid"] is True
        assert rp.current_mode() == "closed"


class TestRestartDurability:
    """The policy and its invitations are records, not process state."""

    def test_policy_and_invitations_survive_a_restart(self, tmp_path: pathlib.Path) -> None:
        import stores
        from services import registration_policy as rp
        from services.model_store import JsonStore

        from maistro.state import PersistedStore, State

        db = tmp_path / "restart.db"

        first = State(db_path=db)
        persisted_first = PersistedStore(first)
        persisted_first.initialize()
        rp.configure(store=rp.PersistedRegistrationRecordStore(persisted_first, first.flush))
        invitations_first = JsonStore("registration_invitations", persisted=persisted_first)
        invitations_first.initialize()
        stores.registration_invitations = invitations_first

        rp.set_mode("open", actor="admin:before-restart")
        token = rp.issue_invitation(actor="admin:before-restart")["token"]
        first.flush()
        first.close()

        second = State(db_path=db)
        persisted_second = PersistedStore(second)
        persisted_second.initialize()
        rp.configure(store=rp.PersistedRegistrationRecordStore(persisted_second, second.flush))
        rehydrated = JsonStore("registration_invitations", persisted=persisted_second)
        rehydrated.initialize()
        stores.registration_invitations = rehydrated

        # Neither an admin's "open" nor the token was process state.
        assert rp.current_mode() == "open"
        assert rp.redeem_invitation(token, username="after-restart") is True
        assert rp.redeem_invitation(token, username="after-restart-2") is False

        # And a restart cannot reopen what an administrator closed.
        rp.set_mode("closed", actor="admin:after-restart")
        second.flush()
        second.close()

        third = State(db_path=db)
        persisted_third = PersistedStore(third)
        persisted_third.initialize()
        rp.configure(store=rp.PersistedRegistrationRecordStore(persisted_third, third.flush))
        closed_invitations = JsonStore("registration_invitations", persisted=persisted_third)
        closed_invitations.initialize()
        stores.registration_invitations = closed_invitations

        assert rp.current_mode() == "closed"
        third.close()


class TestPublicSurfaceDoesNotLeakAccounts:
    """`/v1/setup/status` publishes the mode, not the user list (#313 AC)."""

    def test_status_has_no_config_and_no_usernames(self) -> None:
        from main import app

        client = TestClient(app)
        r = client.get("/v1/setup/status")

        assert r.status_code == 200
        body = r.json()
        assert body["setup_complete"] is True
        assert body["registration"]["mode"] == "closed"
        assert "config" not in body
        assert "testadmin" not in r.text
        assert "testuser" not in r.text

    def test_public_view_carries_the_mode_only(self) -> None:
        from services import registration_policy as rp

        rp.set_mode("open", actor="admin:test")
        assert rp.public_view() == {"mode": "open"}
