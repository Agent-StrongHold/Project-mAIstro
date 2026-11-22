"""Per-principal cognitive-state scoping and bounded chat sessions (#27/#859).

The backend's self-model used to be one process-global snapshot — any admin's
mood PATCH changed what every other user read — and the chat session map was
an unbounded module global. These tests pin the repaired contract:

- self-model reads/writes are keyed by the authenticated canonical principal;
  there is no zero-argument fallback to a shared snapshot;
- the authoritative write seam itself rejects out-of-range values (not just
  the HTTP layer's pydantic schema);
- chat sessions are (principal, session)-keyed — a client-supplied session id
  alone never selects a session — and the registry is bounded by idle TTL and
  capacity.
"""

from __future__ import annotations

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
        except ValueError as exc:
            assert "no process-global fallback" in str(exc)
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

    Regression: _self_model_scope() used to install the default scope before
    the Mood constructor / facet bounds validated, so every rejected write on
    a previously unseen principal leaked a map entry.
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

    with st._lock:
        assert "ghost-a" not in st._scopes
        assert "ghost-b" not in st._scopes


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


class _Clock:
    """Fake monotonic clock the tests can advance."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _registry(**kwargs: Any) -> tuple[Any, list[dict[str, int]]]:
    from ..state import ChatSessionRegistry

    made: list[dict[str, int]] = []

    def factory() -> dict[str, int]:
        marker = {"n": len(made)}
        made.append(marker)
        return marker

    reg = ChatSessionRegistry(factory=factory, **kwargs)
    return reg, made


def test_chat_sessions_are_keyed_by_principal_not_session_id():
    reg, made = _registry()

    a = reg.get_or_create("principal-a", "shared-session")
    b = reg.get_or_create("principal-b", "shared-session")

    assert a is not b  # a guessed session id never crosses principals
    assert a is made[0] and b is made[1]
    # Same principal + same id reuses the principal's own session.
    assert reg.get_or_create("principal-a", "shared-session") is a


def test_chat_session_registry_is_bounded_by_capacity():
    reg, _made = _registry(max_sessions=2)

    first = reg.get_or_create("p", "s1")
    reg.get_or_create("p", "s2")
    reg.get_or_create("p", "s3")  # exceeds capacity -> LRU (s1) evicted

    replacement = reg.get_or_create("p", "s1")
    assert replacement is not first


def test_chat_session_eviction_never_crosses_principals():
    # A process-wide capacity would let one principal flood distinct session
    # ids and evict other principals' LRU sessions (review P1), so capacity
    # and LRU are enforced within each principal's own partition.
    reg, made = _registry(max_sessions=2)

    victim0 = reg.get_or_create("victim", "v0")
    victim1 = reg.get_or_create("victim", "v1")
    flooded = [reg.get_or_create("attacker", f"a{i}") for i in range(4)]

    # The attacker is capped inside their own partition: the flood evicts
    # only the attacker's own LRU session.
    assert reg.get_or_create("attacker", "a0") is not flooded[0]
    assert len(made) == 7  # v0, v1, a0..a3, plus a0 recreated post-eviction

    # ...and no victim session was evicted by the flood.
    assert reg.get_or_create("victim", "v0") is victim0
    assert reg.get_or_create("victim", "v1") is victim1


def test_chat_session_registry_lru_order_survives_timestamp_ties():
    # A frozen (or coarse) clock gives every operation the same timestamp, so
    # eviction must follow tracked recency order, not timestamp comparison
    # falling back to insertion order (review P2).
    clock = _Clock()
    reg, _made = _registry(max_sessions=2, clock=clock)

    first = reg.get_or_create("p", "s1")
    second = reg.get_or_create("p", "s2")
    assert reg.get_or_create("p", "s1") is first  # s1 is now the LRU-ordered MRU
    reg.get_or_create("p", "s3")  # at capacity -> the true LRU (s2) is evicted

    assert reg.get_or_create("p", "s1") is first  # s1 survived: it was just used
    assert reg.get_or_create("p", "s2") is not second  # s2 was the one evicted


def test_chat_session_registry_expires_idle_sessions():
    clock = _Clock()
    reg, made = _registry(idle_ttl_seconds=10.0, clock=clock)

    original = reg.get_or_create("p", "s1")
    clock.now += 11.0  # idle past the TTL
    assert reg.get_or_create("p", "s1") is not original
    assert len(made) == 2


def test_chat_session_registry_requires_principal_and_session_ids():
    reg, _made = _registry()

    for principal_id, session_id in (("", "s1"), ("p", ""), ("", "")):
        try:
            reg.get_or_create(principal_id, session_id)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"({principal_id!r}, {session_id!r}) must be refused: "
                "sessions are principal-scoped, never process-global"
            )
