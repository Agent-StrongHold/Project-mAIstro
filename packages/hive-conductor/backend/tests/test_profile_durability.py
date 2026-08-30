"""A user profile is durable, deletable, and has exactly one owner (#699).

`PUT /v1/profile` wrote `chat_completion._PROFILE_CACHE`, a module global, then
mirrored to a PostgREST `user_profiles` table inside `contextlib.suppress`, then
returned the body it had been handed. The chat tools read *only* that table.
No migration, model or DDL in this repository creates it, and PostgREST is
unconfigured in every tracked Compose profile — so the tools read `{}` and
`profile_set` wrote that `{}` plus one field back, erasing whatever the panel
had saved. Every layer answered success.

`services/profile_store.py` owns the record now. These tests hold the three
properties that close the defect: it survives the process, it refuses to
acknowledge a write it cannot read back, and both surfaces reach it.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import ClassVar

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services import profile_store  # noqa: E402
from services.profile_store import (  # noqa: E402
    STORE_NAME,
    EphemeralProfileRecordStore,
    PersistedProfileRecordStore,
    ProfilePersistenceError,
    ProfileSchemaError,
)

pytestmark = [pytest.mark.contract("behavioral")]


class FakeRecords:
    """`PersistedStore` narrowed to the four calls the record store makes.

    Documents are held as the strings they were written as, because that is
    what the real store holds. A double that kept the dict would let a record
    carrying something unserialisable pass here and fail in production.
    """

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], str] = {}
        self.flushes = 0

    def put_raw(self, store_name: str, key: str, json_str: str) -> None:
        self.documents[(store_name, key)] = json_str

    def get_raw(self, store_name: str, key: str) -> str | None:
        return self.documents.get((store_name, key))

    def delete(self, store_name: str, key: str) -> None:
        self.documents.pop((store_name, key), None)

    def list_all_raw(self, store_name: str) -> list[tuple[str, str]]:
        return [(key, doc) for (name, key), doc in self.documents.items() if name == store_name]

    def flush(self, timeout: float = 10.0) -> None:
        self.flushes += 1


class ForgetfulRecords(FakeRecords):
    """Accepts every write and keeps none.

    This is the only way to exercise the acknowledgement rule from the outside.
    `State._writer_loop` swallows what its closures raise, so a real failed
    write looks exactly like this from the caller's side: accepted, then absent.
    """

    def put_raw(self, store_name: str, key: str, json_str: str) -> None:
        return None


class RefusingRecords(FakeRecords):
    """Raises on write, the way `State.submit` does when the writer is closed."""

    def put_raw(self, store_name: str, key: str, json_str: str) -> None:
        raise RuntimeError("state writer is closed")


class UndeletableRecords(FakeRecords):
    """Accepts a delete and keeps the record anyway."""

    def delete(self, store_name: str, key: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _fresh_store():
    """Every test starts on its own store and leaves nothing behind."""
    profile_store.reset()
    yield
    profile_store.reset()


def _persisted(records: FakeRecords) -> PersistedProfileRecordStore:
    return PersistedProfileRecordStore(records, records.flush)


class TestAProfileOutlivesTheProcessThatWroteIt:
    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_a_new_store_over_the_same_records_reads_the_saved_profile(self) -> None:
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        profile_store.save("u-1", {"name": "Blake", "role": "operator"})

        # The restart: a second record store, built over the same rows, with
        # nothing carried across in the process.
        profile_store.reset(store=_persisted(records))
        assert profile_store.preferences("u-1") == {"name": "Blake", "role": "operator"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_a_real_sqlite_state_round_trips_a_profile(self, tmp_path) -> None:
        """The same claim against the real writer thread, not a double.

        The doubles above cannot show that `flush` actually drains before the
        read-back, which is the whole reason `PersistedProfileRecordStore` calls
        it. This one can.
        """
        from maistro.state import PersistedStore, State

        state = State(db_path=str(tmp_path / "state.db"))
        try:
            persisted = PersistedStore(state)
            persisted.initialize()
            profile_store.configure(PersistedProfileRecordStore(persisted, state.flush))
            profile_store.save("u-1", {"name": "Blake"})
            assert profile_store.preferences("u-1") == {"name": "Blake"}
            assert persisted.get_raw(STORE_NAME, "u-1") is not None
        finally:
            state.close()

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_a_store_without_records_reports_itself_not_durable(self) -> None:
        profile_store.configure(EphemeralProfileRecordStore())
        assert profile_store.durable() is False
        profile_store.configure(_persisted(FakeRecords()))
        assert profile_store.durable() is True

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_the_default_store_is_the_ephemeral_one(self) -> None:
        """A Conductor that never configured a store still answers honestly."""
        assert profile_store.durable() is False
        profile_store.save("u-1", {"name": "Blake"})
        assert profile_store.preferences("u-1") == {"name": "Blake"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_a_record_from_a_newer_build_refuses_to_load(self) -> None:
        """Refused, not coerced. `ProfileRecord` forbids extras, so validating a
        newer envelope would drop its unknown fields and the next write would
        persist the loss."""
        records = FakeRecords()
        records.put_raw(
            STORE_NAME,
            "u-1",
            json.dumps({"schema_version": 99, "user_id": "u-1", "preferences": {"name": "Blake"}}),
        )
        profile_store.configure(_persisted(records))
        with pytest.raises(ProfileSchemaError, match="schema version 99"):
            profile_store.load("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_an_unreadable_record_refuses_rather_than_reading_as_empty(self) -> None:
        records = FakeRecords()
        records.put_raw(STORE_NAME, "u-1", "not json at all")
        profile_store.configure(_persisted(records))
        with pytest.raises(ProfileSchemaError):
            profile_store.load("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_reading_an_absent_profile_stores_nothing(self) -> None:
        """A `GET` must not create a record, or a read against a failing store
        would report a success it never had."""
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        assert profile_store.preferences("u-1") == {}
        assert records.documents == {}


class TestAWriteThatDidNotLandIsNotAcknowledged:
    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_store_that_forgets_the_write_raises(self) -> None:
        profile_store.configure(_persisted(ForgetfulRecords()))
        with pytest.raises(ProfilePersistenceError, match="not observed"):
            profile_store.save("u-1", {"name": "Blake"})

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_store_that_refuses_the_write_raises_our_error_not_its_own(self) -> None:
        profile_store.configure(_persisted(RefusingRecords()))
        with pytest.raises(ProfilePersistenceError, match="refused the write"):
            profile_store.save("u-1", {"name": "Blake"})

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_store_that_keeps_something_else_raises(self) -> None:
        """Read-back compares the record, not the bytes. A store is entitled to
        re-serialise; it is not entitled to change a value."""
        records = FakeRecords()
        profile_store.configure(_persisted(records))

        original = records.put_raw

        def swap(store_name: str, key: str, json_str: str) -> None:
            payload = json.loads(json_str)
            payload["preferences"] = {"name": "someone else"}
            original(store_name, key, json.dumps(payload))

        records.put_raw = swap  # type: ignore[method-assign]
        with pytest.raises(ProfilePersistenceError, match="read back different"):
            profile_store.save("u-1", {"name": "Blake"})

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_write_flushes_before_it_reads_back(self) -> None:
        """Without the drain, the read-back races the writer thread and the
        check passes or fails on timing."""
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        profile_store.save("u-1", {"name": "Blake"})
        assert records.flushes == 1

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_delete_that_left_the_record_raises(self) -> None:
        records = UndeletableRecords()
        profile_store.configure(_persisted(records))
        profile_store.save("u-1", {"name": "Blake"})
        with pytest.raises(ProfilePersistenceError, match="still stored"):
            profile_store.delete("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_the_put_route_answers_503_rather_than_the_payload(self, authed_client) -> None:
        profile_store.configure(_persisted(ForgetfulRecords()))
        response = authed_client.put("/v1/profile", json={"preferences": {"name": "Blake"}})
        assert response.status_code == 503
        assert "name" not in response.text

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_the_delete_route_answers_503_when_the_record_survives(self, authed_client) -> None:
        records = UndeletableRecords()
        profile_store.configure(_persisted(records))
        authed_client.put("/v1/profile", json={"preferences": {"name": "Blake"}})
        assert authed_client.delete("/v1/profile").status_code == 503

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    async def test_the_chat_tool_reports_a_failed_write_rather_than_updated(self) -> None:
        from services.chat_completion import _tool_profile_set

        profile_store.configure(_persisted(ForgetfulRecords()))
        result = await _tool_profile_set({"field": "name", "value": "Blake"}, "u-1")
        assert "error" in result
        assert result.get("updated") is not True


class TestNoProfilePathReachesTheAbsentPostgrestTable:
    """Parsed, not grepped.

    A substring scan would flag this file, and the comment in
    `chat_completion.py` that explains why the cache is gone — which invites an
    allowlist that would have to name the real call sites to work. The AST
    carries no comments, so it answers the question the criterion actually
    asks: does any code still name that table.
    """

    @staticmethod
    def _string_constants(path: pathlib.Path) -> set[str]:
        import ast

        return {
            node.value
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

    @pytest.mark.ac("SPEC-083026-ef62/AC-3")
    @pytest.mark.parametrize("module", ["services/chat_completion.py", "routes/profile.py"])
    def test_no_code_names_the_user_profiles_table(self, module: str) -> None:
        assert "user_profiles" not in self._string_constants(_BACKEND / module)

    @pytest.mark.ac("SPEC-083026-ef62/AC-3")
    def test_the_profile_cache_and_its_hydrator_are_gone(self) -> None:
        """Removed rather than wrapped, so a missed call site is an
        `AttributeError` at import and not a write that quietly does not
        land (ADR-082926-0b72)."""
        import services.chat_completion as chat

        assert not hasattr(chat, "_PROFILE_CACHE")
        assert not hasattr(chat, "hydrate_profile_cache")

    @pytest.mark.ac("SPEC-083026-ef62/AC-3")
    def test_the_route_suppresses_nothing(self) -> None:
        """Parsed, again: the route's own docstring says the word `contextlib`
        to explain what it stopped doing, so a text scan would fail on the
        explanation."""
        import ast

        tree = ast.parse((_BACKEND / "routes/profile.py").read_text())
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert "suppress" not in called
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "contextlib" not in imported


class TestTheRouteAndTheChatToolsReachTheSameOwner:
    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_a_tool_reads_what_the_store_holds(self) -> None:
        from services.chat_completion import _tool_profile_get

        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        assert (await _tool_profile_get({}, "u-1"))["profile"] == {"name": "Blake"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_a_tool_set_does_not_erase_what_was_already_there(self) -> None:
        """The defect itself. `profile_set` read the empty PostgREST table, so
        it wrote `{}` plus its one field over everything the panel had saved."""
        from services.chat_completion import _tool_profile_set

        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake", "role": "operator"})
        await _tool_profile_set({"field": "team", "value": "platform"}, "u-1")
        assert profile_store.preferences("u-1") == {
            "name": "Blake",
            "role": "operator",
            "team": "platform",
        }

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_a_tool_delete_removes_the_field_from_the_shared_record(self) -> None:
        from services.chat_completion import _tool_profile_delete

        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake", "role": "operator"})
        assert (await _tool_profile_delete({"field": "role"}, "u-1"))["deleted"] is True
        assert profile_store.preferences("u-1") == {"name": "Blake"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_a_tool_delete_of_an_unset_field_says_so(self) -> None:
        from services.chat_completion import _tool_profile_delete

        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        assert "not found" in (await _tool_profile_delete({"field": "role"}, "u-1"))["error"]

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_the_model_curation_tool_writes_where_the_route_reads(self) -> None:
        from services.chat_completion import _tool_favorite_model

        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        await _tool_favorite_model({"model": "gemini-3-flash", "action": "add"}, "u-1")
        stored = profile_store.preferences("u-1")
        assert stored["favorite_models"] == ["gemini-3-flash"]
        assert stored["name"] == "Blake", "curation must not drop the rest of the profile"

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_the_route_sees_what_a_tool_set(self, authed_client) -> None:
        from services.chat_completion import _tool_profile_set

        profile_store.configure(_persisted(FakeRecords()))
        user_id = authed_client.get("/v1/auth/whoami").json()["user"]["id"]
        await _tool_profile_set({"field": "name", "value": "Blake"}, user_id)
        assert authed_client.get("/v1/profile").json()["preferences"] == {"name": "Blake"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    async def test_a_tool_sees_what_the_route_wrote(self, authed_client) -> None:
        from services.chat_completion import _tool_profile_get

        profile_store.configure(_persisted(FakeRecords()))
        user_id = authed_client.get("/v1/auth/whoami").json()["user"]["id"]
        authed_client.put("/v1/profile", json={"preferences": {"name": "Blake"}})
        assert (await _tool_profile_get({}, user_id))["profile"] == {"name": "Blake"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    def test_the_system_prompt_carries_the_stored_profile(self) -> None:
        """The reader that made the split-brain visible to the model: it read
        the cache the tools never wrote."""
        from services.chat_completion import _build_system_prompt

        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        assert "name: Blake" in _build_system_prompt("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    def test_every_read_goes_to_the_store_rather_than_a_cache(self) -> None:
        """The property the whole module turns on.

        A process cache is what let the panel and the tools disagree without
        either noticing, and it is what makes a second replica serve a profile
        its owner has already changed (#703, one family over). Writing behind
        the module's back and reading through it is the only way to show the
        cache is absent rather than merely unused in this test.
        """
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        profile_store.save("u-1", {"name": "Blake"})
        records.put_raw(
            STORE_NAME,
            "u-1",
            json.dumps({"schema_version": 1, "user_id": "u-1", "preferences": {"name": "Sam"}}),
        )
        assert profile_store.preferences("u-1") == {"name": "Sam"}

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    def test_two_reads_do_not_hand_back_the_same_dict(self) -> None:
        """So a caller that edits what it was handed changes nothing shared."""
        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        assert profile_store.preferences("u-1") is not profile_store.preferences("u-1")


class TestAProfileIsDeletableAndBelongsToItsPrincipal:
    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_delete_removes_the_record_rather_than_emptying_it(self) -> None:
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        profile_store.save("u-1", {"name": "Blake"})
        assert profile_store.delete("u-1") is True
        assert records.get_raw(STORE_NAME, "u-1") is None
        assert profile_store.user_ids() == []

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_deleting_an_absent_profile_says_there_was_none(self) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        assert profile_store.delete("u-1") is False

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_one_principals_delete_leaves_anothers_profile_alone(self) -> None:
        """Retention is by owner: a profile is kept until *its* owner removes
        it, and nothing else expires it."""
        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        profile_store.save("u-2", {"name": "Sam"})
        profile_store.delete("u-1")
        assert profile_store.preferences("u-2") == {"name": "Sam"}
        assert profile_store.user_ids() == ["u-2"]

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_two_principals_do_not_share_a_profile(self) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        profile_store.save("u-1", {"name": "Blake"})
        assert profile_store.preferences("u-2") == {}

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_an_unnamed_principal_is_refused_rather_than_given_a_shared_profile(self) -> None:
        """`_user_id` used to return the literal `"dev"` here, pointing every
        such caller at one record."""
        from fastapi import HTTPException
        from routes.profile import _user_id

        class _State:
            #: A principal with a role and nothing to address a profile by.
            user: ClassVar[dict[str, str]] = {"role": "user"}

        class _Request:
            state = _State()

        with pytest.raises(HTTPException) as raised:
            _user_id(_Request())  # type: ignore[arg-type]
        assert raised.value.status_code == 401

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_the_delete_route_removes_the_callers_own_profile(self, authed_client) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        authed_client.put("/v1/profile", json={"preferences": {"name": "Blake"}})
        assert authed_client.delete("/v1/profile").json() == {"deleted": True}
        assert authed_client.get("/v1/profile").json()["preferences"] == {}

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_the_route_reports_whether_what_it_saved_is_durable(self, authed_client) -> None:
        profile_store.configure(EphemeralProfileRecordStore())
        assert authed_client.get("/v1/profile").json()["durable"] is False
        profile_store.configure(_persisted(FakeRecords()))
        assert authed_client.get("/v1/profile").json()["durable"] is True

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    def test_an_unauthenticated_request_is_refused(self) -> None:
        from fastapi.testclient import TestClient
        from main import app

        assert TestClient(app).get("/v1/profile").status_code == 401


class TestThePanelReportsASaveItCouldNotMake:
    """Read from the source, because there is no JS runner in this suite.

    Narrow on purpose: the criterion is that the failure reaches the user, so
    what is asserted is that the swallow is gone and that something renders
    from the failure — not the wording or the styling.
    """

    SOURCE = _BACKEND.parents[0] / "frontend" / "src" / "pages" / "KnowledgeBase.tsx"

    @pytest.mark.ac("SPEC-083026-ef62/AC-6")
    def test_the_profile_save_no_longer_ends_in_an_empty_catch(self) -> None:
        source = self.SOURCE.read_text()
        save = source[source.index("const savePrompt") : source.index("const addEntry")]
        assert ".catch(() => {})" not in save
        assert "setSaveError" in save

    @pytest.mark.ac("SPEC-083026-ef62/AC-6")
    def test_a_non_ok_response_is_treated_as_a_failure(self) -> None:
        source = self.SOURCE.read_text()
        save = source[source.index("const savePrompt") : source.index("const addEntry")]
        assert "res.ok" in save

    @pytest.mark.ac("SPEC-083026-ef62/AC-6")
    def test_the_panel_saves_one_field_rather_than_the_whole_document(self) -> None:
        """A `PUT` of the page's own snapshot deletes whatever changed since it
        loaded — a fact set in chat, or a second tab (Codex, #699)."""
        source = self.SOURCE.read_text()
        save = source[source.index("const savePrompt") : source.index("const addEntry")]
        assert '"PATCH"' in save
        assert "preferences" not in save, "a whole-document body is the lost update"

    @pytest.mark.ac("SPEC-083026-ef62/AC-6")
    def test_a_failed_load_is_not_read_as_an_empty_profile(self) -> None:
        """Asserted on the branch, not on the words `r.ok`.

        The first version of this test looked for that substring, and the
        comment above the check contains it — so deleting the check itself left
        the test passing. Mutation-checking caught that; reading did not.
        """
        source = self.SOURCE.read_text()
        load = source[source.index("const load = useCallback") : source.index("const savePrompt")]
        profile = load[load.index('fetch("/v1/profile"') :]
        assert "if (!r.ok) throw" in profile
        assert "setLoadError" in load
        assert "{loadError && (" in source

    @pytest.mark.ac("SPEC-083026-ef62/AC-6")
    def test_the_failure_is_rendered(self) -> None:
        source = self.SOURCE.read_text()
        assert "{saveError && (" in source
        assert 'role="alert"' in source

    @pytest.mark.ac("SPEC-083026-ef62/AC-6")
    def test_an_undurable_conductor_is_declared_in_the_panel(self) -> None:
        source = self.SOURCE.read_text()
        assert "{!profileDurable && (" in source
        assert "p?.durable !== false" in source


class BrokenRecords(FakeRecords):
    """A reader that fails the way a real one can: I/O, permissions, a
    malformed file, no descriptors left. All of them arrive here as some
    exception that is not ours."""

    def get_raw(self, store_name: str, key: str) -> str | None:
        raise OSError("disk I/O error")

    def list_all_raw(self, store_name: str) -> list[tuple[str, str]]:
        raise OSError("disk I/O error")


class TestAStorageFailureIsReportedAsOne:
    """The read half of the acknowledgement rule (Codex, #699).

    The write path was wrapped from the start; the read path let a raw
    `sqlite3` or `OSError` escape, so the `GET` route answered 500 where the
    `PUT` beside it answered the documented 503, and a chat tool aborted its
    loop instead of returning an error.
    """

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_failing_reader_raises_our_error_not_its_own(self) -> None:
        profile_store.configure(_persisted(BrokenRecords()))
        with pytest.raises(ProfilePersistenceError, match="could not be read"):
            profile_store.load("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_failing_listing_raises_our_error_not_its_own(self) -> None:
        profile_store.configure(_persisted(BrokenRecords()))
        with pytest.raises(ProfilePersistenceError, match="could not be listed"):
            profile_store.user_ids()

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_the_get_route_answers_503_for_an_unreadable_record(self, authed_client) -> None:
        profile_store.configure(_persisted(BrokenRecords()))
        assert authed_client.get("/v1/profile").status_code == 503

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_the_get_route_answers_503_for_a_record_it_cannot_parse(self, authed_client) -> None:
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        user_id = authed_client.get("/v1/auth/whoami").json()["user"]["id"]
        records.put_raw(STORE_NAME, user_id, "not json at all")
        assert authed_client.get("/v1/profile").status_code == 503

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_delete_over_a_failing_reader_raises_our_error(self) -> None:
        profile_store.configure(_persisted(BrokenRecords()))
        with pytest.raises(ProfilePersistenceError):
            profile_store.delete("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_record_that_is_not_an_object_refuses(self) -> None:
        records = FakeRecords()
        records.put_raw(STORE_NAME, "u-1", json.dumps(["not", "an", "object"]))
        profile_store.configure(_persisted(records))
        with pytest.raises(ProfileSchemaError, match="not an object"):
            profile_store.load("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_non_integer_schema_version_refuses(self) -> None:
        records = FakeRecords()
        records.put_raw(STORE_NAME, "u-1", json.dumps({"schema_version": "one", "user_id": "u-1"}))
        profile_store.configure(_persisted(records))
        with pytest.raises(ProfileSchemaError, match="non-integer schema version"):
            profile_store.load("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_record_that_fails_validation_refuses(self) -> None:
        """`ProfileRecord` forbids extras, so a record from a *newer* build at
        the *same* version number fails here rather than being read with its
        unknown fields dropped."""
        records = FakeRecords()
        records.put_raw(
            STORE_NAME,
            "u-1",
            json.dumps({"schema_version": 1, "user_id": "u-1", "invented_by_a_newer_build": 1}),
        )
        profile_store.configure(_persisted(records))
        with pytest.raises(ProfileSchemaError, match="failed validation"):
            profile_store.load("u-1")

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_a_write_read_back_unreadable_is_a_persistence_failure(self) -> None:
        """Not a schema failure: from the caller's side the write is what did
        not land, and the route that hears about it is the writing one."""
        records = FakeRecords()
        profile_store.configure(_persisted(records))
        original = records.put_raw
        records.put_raw = lambda store, key, doc: original(store, key, "not json at all")  # type: ignore[method-assign]
        with pytest.raises(ProfilePersistenceError, match="read back unreadable"):
            profile_store.save("u-1", {"name": "Blake"})


class TestOneFieldAtATime:
    """`PATCH /v1/profile`, and the guards around the field name."""

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    def test_patching_one_field_leaves_the_others_alone(self, authed_client) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        authed_client.put("/v1/profile", json={"preferences": {"name": "Blake", "role": "op"}})
        response = authed_client.patch("/v1/profile", json={"field": "team", "value": "platform"})
        assert response.status_code == 200
        assert response.json()["preferences"] == {
            "name": "Blake",
            "role": "op",
            "team": "platform",
        }

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    def test_patching_with_no_field_name_is_refused(self, authed_client) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        assert authed_client.patch("/v1/profile", json={"field": "", "value": 1}).status_code == 400

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    def test_the_patch_route_answers_503_when_the_write_does_not_land(self, authed_client) -> None:
        profile_store.configure(_persisted(ForgetfulRecords()))
        response = authed_client.patch("/v1/profile", json={"field": "name", "value": "Blake"})
        assert response.status_code == 503

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    @pytest.mark.parametrize("call", ["set_field", "delete_field"])
    def test_a_field_operation_needs_a_field_name(self, call: str) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        with pytest.raises(ValueError, match="must be named"):
            if call == "set_field":
                profile_store.set_field("u-1", "", "x")
            else:
                profile_store.delete_field("u-1", "")

    @pytest.mark.ac("SPEC-083026-ef62/AC-5")
    @pytest.mark.parametrize("call", ["load", "delete"])
    def test_a_profile_operation_needs_a_principal(self, call: str) -> None:
        profile_store.configure(_persisted(FakeRecords()))
        with pytest.raises(ValueError, match="addressed by a principal"):
            getattr(profile_store, call)("")


class TestTheHandlersDoNotBlockTheEventLoop:
    """A profile write waits in `State.flush()` — up to ten seconds when the
    writer queue is backed up. Inside an `async` handler that stalls every other
    request on the loop (Codex, #699). Asserted structurally because the cost is
    a property of the declaration, and a timing test for it would be a flake.
    """

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_every_profile_route_handler_is_synchronous(self) -> None:
        import ast

        tree = ast.parse((_BACKEND / "routes/profile.py").read_text())
        routed = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and any(isinstance(d, ast.Call) for d in node.decorator_list)
        ]
        assert not routed, f"async route handlers block the loop on flush: {routed}"

    @pytest.mark.ac("SPEC-083026-ef62/AC-2")
    def test_every_chat_tool_write_goes_through_a_worker_thread(self) -> None:
        import ast

        source = (_BACKEND / "services/chat_completion.py").read_text()
        writes = {"set_field", "delete_field", "save"}
        offloaded = {
            node.args[0].attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
            and node.args
            and isinstance(node.args[0], ast.Attribute)
        }
        assert writes <= offloaded, f"blocking profile writes: {writes - offloaded}"


class TestTheCutoverFromPostgrestIsAnnounced:
    """No automatic import, and not silence either (Codex, #699).

    Nothing in this repository creates `user_profiles`, so no deployment it
    provisions can hold a row there. An operator who created the table by hand
    is the one case where rows exist — and their column shapes are whatever
    that operator chose, so reading them back would be guessing and writing the
    guess into the durable record.
    """

    @pytest.mark.ac("SPEC-083026-ef62/AC-3")
    def test_a_configured_postgrest_is_warned_about(self, monkeypatch, caplog) -> None:
        import logging

        from services.foundation import _warn_if_postgrest_profiles_are_being_left_behind

        monkeypatch.setenv("POSTGREST_URL", "http://postgrest.invalid")
        with caplog.at_level(logging.WARNING):
            _warn_if_postgrest_profiles_are_being_left_behind()
        assert "PROFILE_STORE_CUTOVER" in caplog.text

    @pytest.mark.ac("SPEC-083026-ef62/AC-3")
    def test_no_warning_when_postgrest_is_not_configured(self, monkeypatch, caplog) -> None:
        import logging

        from services.foundation import _warn_if_postgrest_profiles_are_being_left_behind

        monkeypatch.delenv("POSTGREST_URL", raising=False)
        monkeypatch.delenv("DEPLOY_TARGET_POSTGREST_URL", raising=False)
        with caplog.at_level(logging.WARNING):
            _warn_if_postgrest_profiles_are_being_left_behind()
        assert "PROFILE_STORE_CUTOVER" not in caplog.text


class TestTheEphemeralStoreIsAWholeStore:
    """It is what every test and every `memory://` deployment runs on, so its
    delete and its listing have to work, not merely exist."""

    @pytest.mark.ac("SPEC-083026-ef62/AC-1")
    def test_it_removes_and_lists(self) -> None:
        store = EphemeralProfileRecordStore()
        profile_store.configure(store)
        profile_store.save("u-1", {"name": "Blake"})
        profile_store.save("u-2", {"name": "Sam"})
        assert profile_store.user_ids() == ["u-1", "u-2"]
        assert profile_store.delete("u-1") is True
        assert profile_store.user_ids() == ["u-2"]
        assert store.read("u-1") is None


class TestATooldCallMissingItsArgumentsSaysSo:
    """The model composes these calls, so a malformed one is routine rather
    than exceptional — and the answer has to be an error the model can read,
    not a write of an empty field name."""

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    @pytest.mark.parametrize(
        "args", [{}, {"field": "name"}, {"value": "Blake"}, {"field": "", "value": ""}]
    )
    async def test_profile_set_needs_a_field_and_a_value(self, args: dict) -> None:
        from services.chat_completion import _tool_profile_set

        records = FakeRecords()
        profile_store.configure(_persisted(records))
        assert "error" in await _tool_profile_set(args, "u-1")
        assert records.documents == {}, "a malformed call must not write"

    @pytest.mark.ac("SPEC-083026-ef62/AC-4")
    @pytest.mark.parametrize("args", [{}, {"field": ""}])
    async def test_profile_delete_needs_a_field(self, args: dict) -> None:
        from services.chat_completion import _tool_profile_delete

        records = FakeRecords()
        profile_store.configure(_persisted(records))
        assert "error" in await _tool_profile_delete(args, "u-1")
        assert records.documents == {}, "a malformed call must not write"
