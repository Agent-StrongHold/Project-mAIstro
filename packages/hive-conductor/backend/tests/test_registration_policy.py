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
