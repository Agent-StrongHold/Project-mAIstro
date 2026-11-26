"""Cross-scope isolation and bounded-state tests for Turing cognitive state (#859).

These tests are the acceptance evidence for scoping Turing's self-model and
chat state to canonical Workspace principals:

- two users (and their two canonical Workspaces) cannot read or mutate each
  other's self-model state over the real HTTP surface;
- a client-supplied session id never decides ownership: guessing another
  user's session id yields an isolated fresh session in the guesser's own
  scope, never the other user's conversation;
- session cardinality and lifetime are bounded, and session ids are validated
  at the one registry seam;
- scope-less access is refused instead of falling back to a process-global
  self model;
- a multi-replica declaration cannot be enabled against the divergent
  process-local authority, and a shared ``SelfModelStateStore`` composes;
- a fresh composition starts every Workspace from documented defaults, which
  is the truthful restart semantic for the ephemeral store.
"""

from __future__ import annotations

from typing import Any

import pytest

# --------------------------------------------------------- two-user HTTP ----


def test_two_users_have_isolated_self_model_snapshots(admin_client, authed_client):
    admin_patch = admin_client.patch("/v1/admin/mood", json={"valence": -0.9, "focus": 0.1})
    assert admin_patch.status_code == 200

    admin_view = admin_client.get("/v1/state/snapshot").json()
    user_view = authed_client.get("/v1/state/snapshot").json()

    assert admin_view["workspace_id"] != user_view["workspace_id"]
    assert admin_view["mood"]["valence"] == -0.9
    assert admin_view["mood"]["focus"] == 0.1
    # The other principal's snapshot keeps the documented defaults, untouched.
    assert user_view["mood"]["valence"] == 0.2
    assert user_view["mood"]["focus"] == 0.6


def test_admin_facet_patch_cannot_reach_another_users_scope(admin_client, authed_client):
    patch = admin_client.patch("/v1/admin/facet", json={"facet_id": "creativity", "score": 4.9})
    assert patch.status_code == 200

    admin_facets = admin_client.get("/v1/state/snapshot").json()["personality"]
    user_facets = authed_client.get("/v1/state/snapshot").json()["personality"]

    assert admin_facets["openness"]["creativity"] == 4.9
    assert user_facets["openness"]["creativity"] == 3.0


def test_admin_self_model_view_is_the_admins_own_scope(admin_client, authed_client):
    admin_client.patch("/v1/admin/mood", json={"arousal": 0.9})

    admin_view = admin_client.get("/v1/admin/self-model").json()
    user_view = authed_client.get("/v1/state/snapshot").json()

    assert admin_view["workspace_id"] != user_view["workspace_id"]
    assert admin_view["mood"]["arousal"] == 0.9
    assert user_view["mood"]["arousal"] == 0.5


# ------------------------------------------------- session-id isolation -----


@pytest.fixture()
def prompt_capturing_provider(monkeypatch):
    """Capture the exact prompts each session's provider call receives."""
    from ..state import get_state

    prompts: list[str] = []

    async def capture(prompt: str, *args: Any, **kwargs: Any) -> str:
        prompts.append(prompt)
        return f"reply {len(prompts)}"

    # The session's provider seam is async (#397): handle_message awaits
    # ``acomplete``, so the capture must sit on that method.
    monkeypatch.setattr(get_state().provider, "acomplete", capture, raising=True)
    return prompts


def test_guessed_session_id_cannot_attach_to_another_users_session(
    authed_client,
    admin_client,
    prompt_capturing_provider,
):
    """Session-id guessing collapses into an isolated fresh session.

    The admin chats twice in session "shared-secret", building history. The
    other user then posts with the exact same session id. Because sessions are
    keyed by the canonical Workspace resolved from the authenticated
    principal, the guesser gets their own empty session — the admin's
    conversation (its prior context) never leaks into the guesser's prompt,
    and the admin's own session is untouched.
    """
    first = admin_client.post(
        "/v1/chat", json={"message": "keeper turn one", "session_id": "shared-secret"}
    )
    assert first.status_code == 200
    second = admin_client.post(
        "/v1/chat", json={"message": "keeper turn two", "session_id": "shared-secret"}
    )
    assert second.status_code == 200

    # The admin's second turn saw their own prior context.
    assert "Previous context:" in prompt_capturing_provider[1]
    assert "keeper turn one" in prompt_capturing_provider[1]
    admin_prompts = len(prompt_capturing_provider)

    guessed = authed_client.post(
        "/v1/chat", json={"message": "attacher turn", "session_id": "shared-secret"}
    )
    assert guessed.status_code == 200

    # The guessed id did NOT join the admin's conversation: the guesser's
    # prompt carries no prior context, and the admin's history was neither
    # extended nor read by the foreign turn.
    guesser_prompt = prompt_capturing_provider[-1]
    assert "Previous context:" not in guesser_prompt
    assert "keeper turn one" not in guesser_prompt
    assert "keeper turn two" not in guesser_prompt
    assert len(prompt_capturing_provider) == admin_prompts + 1

    from ..state import get_state

    entries = get_state().sessions
    assert entries.active_count() == 2  # one session per Workspace, same id


def test_same_session_id_per_scope_stays_continuous(prompt_capturing_provider, authed_client):
    """Within one caller's scope, a session id still reconnects to the
    conversation (turn history carries), proving scoping did not break the
    session contract — it only bound it to the caller's Workspace."""
    first = authed_client.post("/v1/chat", json={"message": "turn one", "session_id": "mine"})
    second = authed_client.post("/v1/chat", json={"message": "turn two", "session_id": "mine"})
    assert first.status_code == 200 and second.status_code == 200
    assert "turn one" in prompt_capturing_provider[1]
    assert "Previous context:" in prompt_capturing_provider[1]


def test_invalid_session_id_is_refused_at_the_chat_boundary(authed_client):
    """The route maps the registry's session-id validation to a 400 (#859).

    The registry refuses an oversized session id; the HTTP seam must surface
    that refusal to the client instead of creating an unbounded session.
    """
    refused = authed_client.post("/v1/chat", json={"message": "hi", "session_id": "x" * 129})
    assert refused.status_code == 400
    assert "128 characters" in refused.json()["detail"]
    # Nothing was admitted and no session exists for the refused id.
    from ..state import get_state

    assert get_state().sessions.active_count() == 0


# ------------------------------------------------------- registry bounds ----


class TestChatSessionRegistry:
    def _factory(self, counter: list[int]):
        from ..state import get_state

        def make():
            counter.append(1)
            return get_state().new_chat_session()

        return make

    def test_scope_and_session_id_are_validated_at_the_registry(self):
        from ..state import ChatSessionRegistry

        registry = ChatSessionRegistry()
        made: list[int] = []
        factory = self._factory(made)

        with pytest.raises(LookupError, match="Workspace scope is required"):
            registry.resolve(workspace_id="", session_id="s", factory=factory)
        with pytest.raises(LookupError, match="Workspace scope is required"):
            registry.resolve(workspace_id="  ", session_id="s", factory=factory)
        with pytest.raises(ValueError, match="non-empty"):
            registry.resolve(workspace_id="ws", session_id="   ", factory=factory)
        with pytest.raises(ValueError, match="128 characters"):
            registry.resolve(workspace_id="ws", session_id="x" * 129, factory=factory)
        assert made == [] and registry.active_count() == 0

    def test_sessions_are_keyed_by_workspace_not_by_client_id_alone(self):
        from ..state import ChatSessionRegistry

        registry = ChatSessionRegistry()
        made: list[int] = []
        factory = self._factory(made)

        a = registry.resolve(workspace_id="ws-a", session_id="s1", factory=factory)
        b = registry.resolve(workspace_id="ws-b", session_id="s1", factory=factory)
        assert a is not b
        # Reconnecting inside the same scope returns the same session.
        assert registry.resolve(workspace_id="ws-a", session_id="s1", factory=factory) is a
        assert made == [1, 1]

    def test_cardinality_is_bounded_with_lru_eviction(self):
        from ..state import ChatSessionRegistry

        registry = ChatSessionRegistry(max_sessions=2)
        made: list[int] = []
        factory = self._factory(made)

        oldest = registry.resolve(workspace_id="ws", session_id="old", factory=factory)
        registry.resolve(workspace_id="ws", session_id="mid", factory=factory)
        registry.resolve(workspace_id="ws", session_id="new", factory=factory)

        assert registry.active_count() == 2
        fresh_old = registry.resolve(workspace_id="ws", session_id="old", factory=factory)
        assert fresh_old is not oldest  # the LRU entry was evicted, not reused

    def test_lifetime_is_ttl_bounded(self, monkeypatch):
        from .. import state as state_module
        from ..state import ChatSessionRegistry

        registry = ChatSessionRegistry(ttl_seconds=60)
        made: list[int] = []
        factory = self._factory(made)

        first = registry.resolve(workspace_id="ws", session_id="s", factory=factory)
        real_now = state_module._now

        class FakeClock:
            def __init__(self) -> None:
                self.offset = 0.0

            def __call__(self):
                from datetime import timedelta

                return real_now() + timedelta(seconds=self.offset)

        clock = FakeClock()
        monkeypatch.setattr(state_module, "_now", clock)

        clock.offset = 61.0  # past the TTL: the entry is truthfully expired
        second = registry.resolve(workspace_id="ws", session_id="s", factory=factory)
        assert second is not first
        assert made == [1, 1]

        clock.offset = 61.5  # within the new entry's TTL: it survives
        assert registry.resolve(workspace_id="ws", session_id="s", factory=factory) is second
        assert made == [1, 1]


# ------------------------------------------------ scope-less state access ---


class TestScopelessAccessIsRefused:
    """There is no process-global self model to fall back on (#859)."""

    def test_every_accessor_requires_an_explicit_workspace_scope(self):
        from ..state import get_state

        st = get_state()
        with pytest.raises(LookupError, match="Workspace scope is required"):
            st.mood_snapshot("")
        with pytest.raises(LookupError, match="Workspace scope is required"):
            st.facet_scores("")
        with pytest.raises(LookupError, match="Workspace scope is required"):
            st.set_mood("", valence=0.1)
        with pytest.raises(LookupError, match="Workspace scope is required"):
            st.set_facet("", "creativity", 4.0)

    def test_scopes_are_never_inherited_from_another_workspace(self):
        from ..state import get_state

        st = get_state()
        st.set_mood("ws-a", valence=-0.7)
        st.set_facet("ws-a", "creativity", 5.0)

        fresh_b_mood = st.mood_snapshot("ws-b")
        assert fresh_b_mood.valence == 0.2
        assert st.facet_scores("ws-b")["creativity"] == 3.0
        # ...and the write landed only in ws-a.
        assert st.mood_snapshot("ws-a").valence == -0.7


# --------------------------------------------- write-seam value boundaries ---


class TestWriteSeamValueBoundaries:
    """Out-of-range values are rejected at the authoritative write seam itself,
    not only by request validation upstream of it (#859).

    A caller that bypasses HTTP (a producer, a future internal lane) still
    cannot persist an out-of-range mood/facet value: every write traverses
    ``set_mood``/``set_facet``, and a rejected write leaves the scope's state
    exactly as it was.
    """

    def test_set_mood_rejects_out_of_range_values_at_the_seam(self):
        from ..state import get_state

        st = get_state()
        st.set_mood("ws-bounds", valence=0.3)
        before = st.mood_snapshot("ws-bounds")

        for proposal in ({"valence": 1.5}, {"valence": -1.5}, {"arousal": 2.0}, {"focus": -0.1}):
            with pytest.raises(ValueError, match="out of range"):
                st.set_mood("ws-bounds", **proposal)

        # A rejected write persisted nothing: the scope's mood is untouched.
        after = st.mood_snapshot("ws-bounds")
        assert (after.valence, after.arousal, after.focus) == (
            before.valence,
            before.arousal,
            before.focus,
        )

    def test_set_facet_rejects_out_of_range_scores_at_the_seam(self):
        from ..state import get_state

        st = get_state()
        st.set_facet("ws-bounds", "creativity", 4.0)

        for bad_score in (0.5, 5.5):
            with pytest.raises(ValueError, match="out of range"):
                st.set_facet("ws-bounds", "creativity", bad_score)
        with pytest.raises(KeyError):
            st.set_facet("ws-bounds", "not-a-facet", 3.0)

        # Rejected writes persisted nothing.
        assert st.facet_scores("ws-bounds")["creativity"] == 4.0
        assert "not-a-facet" not in st.facet_scores("ws-bounds")


# ------------------------------------------------- bounded published feed ---


def test_artifact_payload_bounds_are_enforced_at_the_write_seam():
    from ..state import get_state

    st = get_state()
    assert st.add_artifact("blog", "t", "b") is not None
    with pytest.raises(ValueError, match="title"):
        st.add_artifact("blog", "x" * 201, "b")
    with pytest.raises(ValueError, match="body"):
        st.add_artifact("blog", "t", "x" * 20_001)


def test_oversized_artifact_publish_is_rejected_over_http(turing_service_client):
    r = turing_service_client.post(
        "/v1/feed", json={"kind": "blog", "title": "x" * 201, "body": "b"}
    )
    assert r.status_code == 400
    assert "title" in r.json()["detail"]


def test_feed_count_is_bounded():
    from ..state import MAX_ARTIFACTS, get_state

    st = get_state()
    for i in range(MAX_ARTIFACTS + 10):
        st.add_artifact("reflection", f"t{i}", "b")
    items, total = st.list_artifacts(limit=MAX_ARTIFACTS + 10)
    assert total == MAX_ARTIFACTS
    # Oldest fell off first; the newest survived.
    assert items[0].title == f"t{MAX_ARTIFACTS + 9}"


# ------------------------------------------- restart / replica semantics ----


class SharedFakeStore:
    """Minimal shared ``SelfModelStateStore`` double for composition tests."""

    is_shared_across_replicas = True

    def __init__(self) -> None:
        self.scopes: dict[str, Any] = {}

    def load_scope(self, workspace_id: str):
        return self.scopes.get(workspace_id)

    def save_scope(self, workspace_id: str, state):
        self.scopes[workspace_id] = state


class TestRestartAndReplicaSemantics:
    def test_fresh_composition_starts_every_scope_from_documented_defaults(self):
        from ..main import app
        from ..state import reset_state

        first = reset_state(inbound_security=app.state.turing_security)
        first.set_mood("ws-restart", valence=-1.0)

        second = reset_state(inbound_security=app.state.turing_security)
        # Truthful ephemeral semantics: the new process-wide composition does
        # NOT silently carry the old process's mood. Defaults it is.
        assert second.mood_snapshot("ws-restart").valence == 0.2
        assert second.sessions.active_count() == 0

    def test_multi_replica_declaration_refuses_the_process_local_authority(self, monkeypatch):
        from ..main import app
        from ..state import InProcessSelfModelStateStore, reset_state

        monkeypatch.setenv("TURING_REPLICA_COUNT", "2")
        with pytest.raises(RuntimeError, match="not declared shared"):
            reset_state(inbound_security=app.state.turing_security)
        with pytest.raises(RuntimeError, match="not declared shared"):
            reset_state(
                inbound_security=app.state.turing_security,
                state_store=InProcessSelfModelStateStore(),
            )

    def test_unclassified_store_cannot_enable_replicas(self, monkeypatch):
        from ..main import app
        from ..state import TuringState

        class UnclassifiedStore(SharedFakeStore):
            is_shared_across_replicas = False

        monkeypatch.setenv("TURING_REPLICA_COUNT", "2")
        with pytest.raises(RuntimeError, match="not declared shared"):
            TuringState(
                inbound_security=app.state.turing_security,
                state_store=UnclassifiedStore(),
            )

    def test_replica_count_is_validated(self, monkeypatch):
        from ..config import replica_count

        monkeypatch.setenv("TURING_REPLICA_COUNT", "0")
        with pytest.raises(RuntimeError, match=">= 1"):
            replica_count()
        monkeypatch.setenv("TURING_REPLICA_COUNT", "two")
        with pytest.raises(RuntimeError, match="integer"):
            replica_count()
        monkeypatch.setenv("TURING_REPLICA_COUNT", "3")
        assert replica_count() == 3
        monkeypatch.delenv("TURING_REPLICA_COUNT")
        assert replica_count() == 1

    def test_a_shared_store_backs_replicas_without_divergence(self, monkeypatch):
        """The replica seam: one shared store, N state facades, one truth."""
        from ..main import app
        from ..state import TuringState

        monkeypatch.setenv("TURING_REPLICA_COUNT", "2")
        shared = SharedFakeStore()

        replica_one = TuringState(inbound_security=app.state.turing_security, state_store=shared)
        replica_two = TuringState(inbound_security=app.state.turing_security, state_store=shared)

        replica_one.set_mood("ws-shared", valence=0.9)
        # The other replica reads the same authoritative scope — no
        # process-local divergence is possible over the shared store.
        assert replica_two.mood_snapshot("ws-shared").valence == 0.9
        replica_two.set_facet("ws-shared", "creativity", 4.2)
        assert replica_one.facet_scores("ws-shared")["creativity"] == 4.2


# ------------------------------------------- deterministic scope resolution --


class TestDeterministicWorkspaceResolution:
    """The Workspace scope id is a function of the principal, not of the
    process (#859).

    A shared ``SelfModelStateStore`` only converges replicas if every process
    resolves the SAME canonical Workspace id for the same principal. A
    per-process random mint would make two replicas disagree on keys even
    over one shared store, so the resolution is derived deterministically
    (uuid5, namespaced) from the authenticated principal id.
    """

    def test_the_same_principal_resolves_the_same_scope_in_every_process(self):
        import uuid

        from ..execution import TuringExecutionPlane
        from ..main import app

        async def scenario() -> None:
            # Two independently composed planes stand in for two replica
            # processes: private stores, no shared in-memory state.
            plane_one = TuringExecutionPlane(inbound_security=app.state.turing_security)
            plane_two = TuringExecutionPlane(inbound_security=app.state.turing_security)

            first_ws, _first_proj = await plane_one.scope_for("user-replica")
            second_ws, _second_proj = await plane_two.scope_for("user-replica")

            # The cognitive-state key converges across processes; only the
            # Workspace id is asserted because it is the seam the scoped
            # state store (and the chat-session registry) is keyed by.
            assert first_ws == second_ws
            # The id is canonical UUID-shaped, not a per-process random mint.
            assert str(uuid.UUID(first_ws)) == first_ws

            # A different principal resolves a different scope: isolation is
            # preserved by the same determinism.
            other_ws, _other_proj = await plane_one.scope_for("user-other")
            assert other_ws != first_ws

        import asyncio

        asyncio.run(scenario())
