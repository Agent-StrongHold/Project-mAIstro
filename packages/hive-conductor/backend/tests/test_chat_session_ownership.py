"""Two users, every chat operation, and nothing crosses between them (#312).

`test_chat_routes.py` covers the route surface for one user and passes
unchanged against this fix — a single user's experience of chat is the same as
it was. What it cannot show is the defect, because a defect about *whose* data
a handler returns is invisible until there are two people's data in the store.

So every test here has both. `alice` is the conftest `testuser`; `bob` is a
second ordinary account this module creates, because the only other seeded
account is the admin, and the admin is refused the whole `/v1/chat/` surface.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from main import app  # noqa: E402

BOB_ID = "user-bob-312"
BOB_USERNAME = "bob-312"
BOB_PASSWORD = "bob-password-312"

#: Distinguishes "no `user` attribute at all" from "an attribute set to None".
_MISSING = object()


def _clear_chat() -> None:
    for key in list(stores.chat_sessions.keys()):
        stores.chat_sessions.pop(key, None)


@pytest.fixture(autouse=True)
def _empty_chat_store():
    _clear_chat()
    yield
    _clear_chat()


@pytest.fixture
def bob() -> Any:
    """A second ordinary user, logged in.

    Created directly in the store rather than through `/v1/auth/register`,
    which is closed once setup completes and would make this fixture depend on
    first-run state that has nothing to do with chat.
    """
    from maistro.security.passwords import hash_password

    stores.users[BOB_ID] = stores.users._model_class(
        id=BOB_ID,
        username=BOB_USERNAME,
        password_hash=hash_password(BOB_PASSWORD),
        role="user",
        is_active=True,
        permissions=[],
        created_at=datetime.now(UTC),
    )
    client = TestClient(app)
    response = client.post(
        "/v1/auth/login", json={"username": BOB_USERNAME, "password": BOB_PASSWORD}
    )
    assert response.status_code == 200, response.text
    yield client
    stores.users.pop(BOB_ID, None)


def _create(client: Any, title: str = "a chat") -> str:
    response = client.post("/v1/chat/sessions", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["id"]


class TestASessionIsBoundToWhoeverCreatedIt:
    def test_the_new_session_carries_the_callers_id(self, authed_client: Any) -> None:
        body = authed_client.post("/v1/chat/sessions", json={"title": "mine"}).json()

        assert body["user_id"]
        assert stores.chat_sessions[body["id"]].user_id == body["user_id"]

    def test_a_user_id_in_the_body_is_not_believed(self, authed_client: Any, bob: Any) -> None:
        """The client naming an owner is the whole failure mode this prevents.
        Whether the field is dropped by the schema or overwritten on write, the
        stored owner must be the authenticated one."""
        sid = authed_client.post(
            "/v1/chat/sessions", json={"title": "stolen", "user_id": BOB_ID}
        ).json()["id"]

        assert stores.chat_sessions[sid].user_id != BOB_ID

    def test_the_owner_is_the_session_not_the_first_writer(
        self, authed_client: Any, bob: Any
    ) -> None:
        """Appending does not re-stamp: a message from the owner leaves the
        owner alone, and nobody else can append at all."""
        sid = _create(authed_client)
        before = stores.chat_sessions[sid].user_id

        authed_client.post(f"/v1/chat/sessions/{sid}/messages", json={"content": "hi"})

        assert stores.chat_sessions[sid].user_id == before


class TestOneUsersSessionIsInvisibleToAnother:
    def test_the_list_holds_only_your_own(self, authed_client: Any, bob: Any) -> None:
        mine = _create(authed_client, "alice's")
        theirs = _create(bob, "bob's")

        alice_ids = {s["id"] for s in authed_client.get("/v1/chat/sessions").json()}
        bob_ids = {s["id"] for s in bob.get("/v1/chat/sessions").json()}

        assert mine in alice_ids and mine not in bob_ids
        assert theirs in bob_ids and theirs not in alice_ids

    def test_reading_someone_elses_by_exact_id_is_a_404(self, authed_client: Any, bob: Any) -> None:
        theirs = _create(bob, "bob's")

        assert authed_client.get(f"/v1/chat/sessions/{theirs}").status_code == 404

    def test_appending_to_someone_elses_is_a_404_and_writes_nothing(
        self, authed_client: Any, bob: Any
    ) -> None:
        theirs = _create(bob, "bob's")

        response = authed_client.post(
            f"/v1/chat/sessions/{theirs}/messages", json={"content": "not yours"}
        )

        assert response.status_code == 404
        assert stores.chat_sessions[theirs].messages == []

    def test_deleting_someone_elses_leaves_it_where_it_was(
        self, authed_client: Any, bob: Any
    ) -> None:
        """204 either way — see the enumeration test below — so the assertion
        that matters is on the store, not the status."""
        theirs = _create(bob, "bob's")

        authed_client.delete(f"/v1/chat/sessions/{theirs}")

        assert theirs in stores.chat_sessions
        assert bob.get(f"/v1/chat/sessions/{theirs}").status_code == 200


class TestGuessingIdsTellsYouNothing:
    def test_someone_elses_session_answers_exactly_like_a_missing_one(
        self, authed_client: Any, bob: Any
    ) -> None:
        """Status *and* body. A 403 here, or a differently-worded 404, turns id
        guessing into a census of who has how many chats."""
        theirs = _create(bob, "bob's")

        foreign = authed_client.get(f"/v1/chat/sessions/{theirs}")
        absent = authed_client.get("/v1/chat/sessions/definitely-not-a-session")

        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()

    def test_appending_answers_the_same_either_way(self, authed_client: Any, bob: Any) -> None:
        theirs = _create(bob, "bob's")
        payload = {"role": "user", "content": "x"}

        foreign = authed_client.post(f"/v1/chat/sessions/{theirs}/messages", json=payload)
        absent = authed_client.post("/v1/chat/sessions/no-such-thing/messages", json=payload)

        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()

    def test_deleting_answers_the_same_either_way(self, authed_client: Any, bob: Any) -> None:
        theirs = _create(bob, "bob's")

        foreign = authed_client.delete(f"/v1/chat/sessions/{theirs}")
        absent = authed_client.delete("/v1/chat/sessions/no-such-thing")

        assert foreign.status_code == absent.status_code == 204
        assert foreign.content == absent.content


class TestARowWithNoOwnerBelongsToNobody:
    """The disposition for sessions written before ownership was bound: they
    are quarantined, not adopted by the first caller and not deleted."""

    @pytest.fixture
    def legacy(self) -> str:
        from models.schemas import ChatSession

        now = datetime.now(UTC)
        stores.chat_sessions["legacy-unowned"] = ChatSession(
            id="legacy-unowned",
            title="from before",
            messages=[],
            created_at=now,
            updated_at=now,
        )
        return "legacy-unowned"

    def test_it_is_in_nobodys_list(self, legacy: str, authed_client: Any, bob: Any) -> None:
        assert legacy not in {s["id"] for s in authed_client.get("/v1/chat/sessions").json()}
        assert legacy not in {s["id"] for s in bob.get("/v1/chat/sessions").json()}

    def test_nobody_can_read_it(self, legacy: str, authed_client: Any, bob: Any) -> None:
        assert authed_client.get(f"/v1/chat/sessions/{legacy}").status_code == 404
        assert bob.get(f"/v1/chat/sessions/{legacy}").status_code == 404

    def test_it_is_still_there_afterwards(self, legacy: str, authed_client: Any) -> None:
        """Unreachable through the API, intact on disk. Discarding someone's
        history to fix our own bookkeeping is the worse failure."""
        authed_client.delete(f"/v1/chat/sessions/{legacy}")

        assert legacy in stores.chat_sessions


class TestTheWelcomeSeedIsPerUser:
    def test_each_user_gets_their_own(self, authed_client: Any, bob: Any) -> None:
        """A single deployment-wide seed row would belong to nobody once
        ownership is enforced, so it would be seeded and then invisible."""
        alice_titles = [s["title"] for s in authed_client.get("/v1/chat/sessions").json()]
        bob_titles = [s["title"] for s in bob.get("/v1/chat/sessions").json()]

        assert "Welcome" in alice_titles
        assert "Welcome" in bob_titles

    def test_they_are_different_rows(self, authed_client: Any, bob: Any) -> None:
        alice_ids = {s["id"] for s in authed_client.get("/v1/chat/sessions").json()}
        bob_ids = {s["id"] for s in bob.get("/v1/chat/sessions").json()}

        assert alice_ids.isdisjoint(bob_ids)

    def test_seeding_is_not_repeated_for_a_user_who_has_one(self, authed_client: Any) -> None:
        first = authed_client.get("/v1/chat/sessions").json()
        second = authed_client.get("/v1/chat/sessions").json()

        assert len(first) == len(second) == 1


class TestTheAdminIsNotAnExceptionHere:
    def test_the_admin_role_cannot_reach_chat_at_all(self, admin_client: Any) -> None:
        """Why `Owner` carries no role: the middleware settles the admin
        question before a handler runs, so there is no admin-sees-everything
        branch in the ownership check to get wrong."""
        assert admin_client.get("/v1/chat/sessions").status_code == 403


class TestTheChecklistCountsChatsYouWrote:
    def test_a_seed_alone_does_not_complete_the_item(self, authed_client: Any) -> None:
        from routes.setup_checklist import _has_chat_session

        authed_client.get("/v1/chat/sessions")  # seeds

        assert _has_chat_session("user") is False

    def test_a_session_you_created_does(self, authed_client: Any) -> None:
        from routes.setup_checklist import _has_chat_session

        _create(authed_client)

        assert _has_chat_session("user") is True

    def test_someone_elses_session_does_not_complete_it_for_you(
        self, authed_client: Any, bob: Any
    ) -> None:
        from routes.setup_checklist import _has_chat_session

        _create(bob)

        assert _has_chat_session("user") is False


class TestTheViewFailsClosedWithoutAPrincipal:
    """`AuthMiddleware` rejects an unauthenticated `/v1/` request before any
    handler runs, so these branches are unreachable through the routes today.
    They are the answer to a route that escapes the middleware — a new public
    prefix, a router mounted outside `/v1/` — and an unreachable branch that
    has never run is a guess, not a guarantee."""

    def _request(self, user: object) -> object:
        class _State:
            pass

        state = _State()
        if user is not _MISSING:
            state.user = user

        class _Request:
            pass

        request = _Request()
        request.state = state
        return request

    def test_no_attached_user_is_a_401(self) -> None:
        from fastapi import HTTPException
        from services.owned_records import owner_of

        with pytest.raises(HTTPException) as caught:
            owner_of(self._request(_MISSING))

        assert caught.value.status_code == 401

    def test_a_user_that_is_not_a_mapping_is_a_401(self) -> None:
        """Anything that is not the middleware's dict — a model, a string, a
        `None` left by a half-written dependency — is not a principal."""
        from fastapi import HTTPException
        from services.owned_records import owner_of

        with pytest.raises(HTTPException) as caught:
            owner_of(self._request("testuser"))

        assert caught.value.status_code == 401

    def test_a_user_with_no_id_is_a_401(self) -> None:
        """The one that would be silent: an empty id compares equal to the
        `user_id` every legacy row carries, so admitting it would hand the
        quarantined rows to whoever arrived without one."""
        from fastapi import HTTPException
        from services.owned_records import owner_of

        with pytest.raises(HTTPException) as caught:
            owner_of(self._request({"id": "", "role": "user"}))

        assert caught.value.status_code == 401


class TestSeedingNeedsSomeoneToSeedFor:
    def test_an_empty_user_id_seeds_nothing(self) -> None:
        """Otherwise the guard above would be the only thing between an
        unattributed caller and a row keyed on the empty string."""
        stores.seed_chat_for("")

        assert list(stores.chat_sessions.keys()) == []
