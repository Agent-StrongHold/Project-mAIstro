"""Per-Workspace cognitive-state scoping and bounded chat sessions (#27/#859).

The backend's self-model used to be one process-global snapshot — any admin's
mood PATCH changed what every other user read — and the chat session map was
an unbounded module global. These tests pin the repaired contract:

- self-model reads/writes are keyed by the authenticated canonical principal's
  Workspace; there is no zero-argument fallback to a shared snapshot;
- the authoritative write seam itself rejects out-of-range values (not just
  the HTTP layer's pydantic schema), and a rejected write persists nothing —
  not even a default scope entry for a previously unseen Workspace;
- chat sessions are (Workspace, session)-keyed — a client-supplied session id
  alone never selects a session — and the registry is bounded by idle TTL and
  per-Workspace capacity, so one scope's flood cannot evict another scope's
  live session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------- state seam --


def test_self_model_state_is_scoped_per_principal():
    from ..state import get_state

    st = get_state()

    st.set_mood("admin-a", valence=0.9)
    st.set_facet("admin-a", "creativity", 4.5)

    # Another principal's scope keeps the untouched defaults.
    b_mood = st.mood_snapshot("admin-b")
    assert (b_mood.valence, b_mood.arousal, b_mood.focus) == (0.2, 0.5, 0.6)
    assert st.facet_scores("admin-b")["creativity"] == 3.0

    # And each scope reads back its own mutations.
    assert st.mood_snapshot("admin-a").valence == 0.9
    assert st.facet_scores("admin-a")["creativity"] == 4.5


def test_self_model_state_requires_an_explicit_principal_scope():
    from ..state import get_state

    st = get_state()

    def expect_refusal(blank: str, call) -> None:  # type: ignore[no-untyped-def]
        try:
            call(blank)
        except LookupError as exc:
            assert "no process-global" in str(exc)
        else:
            raise AssertionError(f"blank scope {blank!r} must be refused")

    for blank in ("", "   "):
        expect_refusal(blank, st.mood_snapshot)
        expect_refusal(blank, st.facet_scores)
        expect_refusal(blank, lambda scope: st.set_mood(scope, valence=0.1))
        expect_refusal(blank, lambda scope: st.set_facet(scope, "creativity", 3.0))


def test_set_mood_rejects_out_of_range_values_at_the_seam_without_mutating():
    """Bounds live on the write seam itself, not only the HTTP schema."""
    from ..state import get_state

    st = get_state()

    for bad in ({"valence": 5.0}, {"arousal": -0.1}, {"focus": 1.5}):
        try:
            st.set_mood("admin-a", **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"out-of-range mood {bad} must be refused")

    mood = st.mood_snapshot("admin-a")
    assert (mood.valence, mood.arousal, mood.focus) == (0.2, 0.5, 0.6)


def test_set_facet_rejects_out_of_range_and_unknown_facets_at_the_seam():
    from ..state import get_state

    st = get_state()

    try:
        st.set_facet("admin-a", "creativity", 9.0)
    except ValueError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("out-of-range facet score must be refused")

    try:
        st.set_facet("admin-a", "not-a-facet", 3.0)
    except KeyError:
        pass
    else:
        raise AssertionError("unknown facet must be refused")

    assert st.facet_scores("admin-a")["creativity"] == 3.0


def test_rejected_writes_do_not_install_a_scope_for_an_unseen_principal():
    """A rejected write leaves no default entry behind for a new principal.

    Regression: the write seam used to materialize the default scope before
    the Mood constructor / facet bounds validated, so every rejected write on
    a previously unseen principal leaked a persisted scope entry.
    """
    from ..state import get_state

    st = get_state()

    def refuse(call, exc_type, match):  # type: ignore[no-untyped-def]
        try:
            call()
        except exc_type as exc:
            assert match in str(exc)
        else:
            raise AssertionError(f"{call} must be refused")

    refuse(lambda: st.set_mood("ghost-a", valence=5.0), ValueError, "out of range")
    refuse(
        lambda: st.set_facet("ghost-b", "not-a-facet", 3.0),
        KeyError,
        "not-a-facet",
    )
    refuse(lambda: st.set_facet("ghost-b", "creativity", 9.0), ValueError, "out of range")

    # Nothing was persisted for the refused principals: the state store — the
    # one authority behind the seam — holds no scope for either.
    assert st.state_store.load_scope("ghost-a") is None
    assert st.state_store.load_scope("ghost-b") is None


# ------------------------------------------------------------ route wiring --


def test_admin_mood_patch_is_invisible_to_other_principals(admin_client, authed_client):
    """The audit's exact defect: one admin's PATCH changing another user's view."""
    assert admin_client.patch("/v1/admin/mood", json={"valence": 0.9}).status_code == 200

    # The calling admin sees their own mutation...
    admin_view = admin_client.get("/v1/admin/self-model").json()
    assert admin_view["mood"]["valence"] == 0.9
    assert admin_client.get("/v1/state/snapshot").json()["mood"]["valence"] == 0.9

    # ...another principal does not.
    user_view = authed_client.get("/v1/state/snapshot").json()
    assert user_view["mood"]["valence"] == 0.2


# ------------------------------------------------------- chat session bounds --


class _FakeWall:
    """Fake UTC wall clock the tests can freeze or advance."""

    def __init__(self) -> None:
        self.moment = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment = self.moment + timedelta(seconds=seconds)


def _registry(monkeypatch, **kwargs: Any) -> tuple[Any, list[dict[str, int]], _FakeWall, Any]:
    """A registry over the module's ``_now`` clock, with session spying."""
    from .. import state as state_module
    from ..state import ChatSessionRegistry

    made: list[dict[str, int]] = []

    def factory() -> dict[str, int]:
        marker = {"n": len(made)}
        made.append(marker)
        return marker

    clock = _FakeWall()
    monkeypatch.setattr(state_module, "_now", clock)
    reg = ChatSessionRegistry(**kwargs)
    return reg, made, clock, factory


def test_chat_sessions_are_keyed_by_workspace_not_session_id(monkeypatch):
    reg, made, _clock, factory = _registry(monkeypatch)

    def resolve(workspace_id: str, session_id: str):  # type: ignore[no-untyped-def]
        return reg.resolve(workspace_id=workspace_id, session_id=session_id, factory=factory)

    a = resolve("workspace-a", "shared-session")
    b = resolve("workspace-b", "shared-session")

    assert a is not b  # a guessed session id never crosses Workspaces
    assert a is made[0] and b is made[1]
    # Same Workspace + same id reuses that scope's own session.
    assert resolve("workspace-a", "shared-session") is a
    assert len(made) == 2


def test_chat_session_registry_is_bounded_by_capacity(monkeypatch):
    reg, made, _clock, factory = _registry(monkeypatch, max_sessions=2)

    def resolve(session_id: str):  # type: ignore[no-untyped-def]
        return reg.resolve(workspace_id="ws", session_id=session_id, factory=factory)

    first = resolve("s1")
    resolve("s2")
    resolve("s3")  # exceeds capacity -> this Workspace's LRU (s1) evicted

    replacement = resolve("s1")
    assert replacement is not first
    assert len(made) == 4


def test_chat_session_eviction_never_crosses_workspaces(monkeypatch):
    # A process-wide capacity would let one Workspace flood distinct session
    # ids and evict other Workspaces' LRU sessions, so capacity and LRU are
    # enforced within each Workspace's own partition.
    reg, made, _clock, factory = _registry(monkeypatch, max_sessions=2)

    def resolve(workspace_id: str, session_id: str):  # type: ignore[no-untyped-def]
        return reg.resolve(workspace_id=workspace_id, session_id=session_id, factory=factory)

    victim0 = resolve("victim", "v0")
    victim1 = resolve("victim", "v1")
    flooded = [resolve("attacker", f"a{i}") for i in range(4)]

    # The attacker is capped inside their own partition: the flood evicts
    # only the attacker's own LRU session.
    assert resolve("attacker", "a0") is not flooded[0]
    assert len(made) == 7  # v0, v1, a0..a3, plus a0 recreated post-eviction

    # ...and no victim session was evicted by the flood.
    assert resolve("victim", "v0") is victim0
    assert resolve("victim", "v1") is victim1


def test_chat_session_registry_lru_order_survives_timestamp_ties(monkeypatch):
    # A frozen (or coarse) clock gives every operation the same timestamp, so
    # eviction must follow tracked recency order, not timestamp comparison
    # falling back to insertion order.
    reg, made, _clock, factory = _registry(monkeypatch, max_sessions=2)

    def resolve(session_id: str):  # type: ignore[no-untyped-def]
        return reg.resolve(workspace_id="ws", session_id=session_id, factory=factory)

    first = resolve("s1")
    second = resolve("s2")
    assert resolve("s1") is first  # s1 is now the LRU-ordered MRU
    resolve("s3")  # at capacity -> the true LRU (s2) is evicted

    assert resolve("s1") is first  # s1 survived: it was just used
    assert resolve("s2") is not second  # s2 was the one evicted
    assert len(made) == 4


def test_chat_session_registry_expires_idle_sessions(monkeypatch):
    reg, made, clock, factory = _registry(monkeypatch, ttl_seconds=10.0)

    original = reg.resolve(workspace_id="ws", session_id="s1", factory=factory)
    clock.advance(11.0)  # idle past the TTL
    assert reg.resolve(workspace_id="ws", session_id="s1", factory=factory) is not original
    assert len(made) == 2


def test_chat_session_registry_requires_scope_and_valid_session_ids(monkeypatch):
    reg, made, _clock, factory = _registry(monkeypatch)

    def resolve(workspace_id: str, session_id: str):  # type: ignore[no-untyped-def]
        return reg.resolve(workspace_id=workspace_id, session_id=session_id, factory=factory)

    for workspace_id, session_id in (("", "s1"), ("   ", "s1"), ("ws", ""), ("ws", "   ")):
        try:
            resolve(workspace_id, session_id)
        except (LookupError, ValueError):
            pass
        else:
            raise AssertionError(
                f"({workspace_id!r}, {session_id!r}) must be refused: "
                "sessions are Workspace-scoped, never process-global"
            )
    # A client may not spend unbounded key space either: oversized ids are
    # refused at this one registry seam.
    try:
        resolve("ws", "x" * 129)
    except ValueError as exc:
        assert "128" in str(exc)
    else:
        raise AssertionError("oversized session id must be refused")
    assert made == [] and reg.active_count() == 0
