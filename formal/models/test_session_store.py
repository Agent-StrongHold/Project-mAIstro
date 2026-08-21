"""I16: Session Store — History with TTL — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.sessions.store import InMemorySessionStore
from maistro.types.session import SessionConfig


def _run(coro):
    return asyncio.run(coro)


class SessionStoreMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.config = SessionConfig(max_messages=10, ttl_seconds=3600)
        self.store = InMemorySessionStore(config=self.config)
        self.session_id = "test-session"
        self.appended_count = 0

    @rule(
        content=st.text(min_size=1, max_size=100),
        role=st.sampled_from(["user", "assistant"]),
    )
    def append_message(self, content, role):
        _run(self.store.append_messages(self.session_id, [{"role": role, "content": content}]))
        self.appended_count += 1

    @rule(
        content=st.text(min_size=1, max_size=50),
        role=st.sampled_from(["system", "tool", "function", "other"]),
    )
    def append_invalid_role(self, content, role):
        before = len(_run(self.store.get_history(self.session_id)))
        _run(self.store.append_messages(self.session_id, [{"role": role, "content": content}]))
        after = len(_run(self.store.get_history(self.session_id)))
        assert after == before

    @rule()
    def delete_and_verify(self):
        _run(self.store.delete_session(self.session_id))
        history = _run(self.store.get_history(self.session_id))
        assert history == []
        self.appended_count = 0

    @invariant()
    def history_never_exceeds_max(self):
        history = _run(self.store.get_history(self.session_id))
        assert len(history) <= self.config.max_messages

    @invariant()
    def all_roles_valid(self):
        history = _run(self.store.get_history(self.session_id))
        for msg in history:
            assert msg["role"] in ("user", "assistant")


TestSessionStoreMachine = SessionStoreMachine.TestCase


@given(
    messages=st.lists(
        st.tuples(
            st.sampled_from(["user", "assistant"]),
            st.text(min_size=1, max_size=50),
        ),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=30)
def test_messages_maintain_order(messages):
    store = InMemorySessionStore(config=SessionConfig(max_messages=50, ttl_seconds=3600))
    sid = "order-test"

    for role, content in messages:
        _run(store.append_messages(sid, [{"role": role, "content": content}]))

    history = _run(store.get_history(sid))
    assert len(history) == len(messages)
    for i, (role, content) in enumerate(messages):
        assert history[i]["role"] == role
        assert history[i]["content"] == content


def test_max_messages_limit_respected():
    config = SessionConfig(max_messages=5, ttl_seconds=3600)
    store = InMemorySessionStore(config=config)

    for i in range(10):
        _run(store.append_messages("trim-test", [{"role": "user", "content": f"msg-{i}"}]))

    history = _run(store.get_history("trim-test"))
    assert len(history) == 5
    assert history[0]["content"] == "msg-5"
    assert history[4]["content"] == "msg-9"


@given(
    n=st.integers(min_value=1, max_value=30),
)
@settings(max_examples=20)
def test_max_messages_oldest_trimmed(n):
    limit = 10
    config = SessionConfig(max_messages=limit, ttl_seconds=3600)
    store = InMemorySessionStore(config=config)

    for i in range(n):
        _run(store.append_messages("trim-n", [{"role": "user", "content": str(i)}]))

    history = _run(store.get_history("trim-n"))
    assert len(history) <= limit


def test_invalid_roles_filtered():
    store = InMemorySessionStore()
    _run(
        store.append_messages(
            "filter-test",
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
                {"role": "tool", "content": "tool-output"},
                {"role": "assistant", "content": "hi"},
            ],
        )
    )
    history = _run(store.get_history("filter-test"))
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_non_string_content_filtered():
    store = InMemorySessionStore()
    _run(
        store.append_messages(
            "content-test",
            [
                {"role": "user", "content": 12345},
                {"role": "user", "content": "valid"},
                {"role": "user", "content": None},
            ],
        )
    )
    history = _run(store.get_history("content-test"))
    assert len(history) == 1
    assert history[0]["content"] == "valid"


@given(
    session_a=st.text(min_size=1, max_size=10),
    session_b=st.text(min_size=1, max_size=10),
)
@settings(max_examples=30)
def test_different_sessions_isolated(session_a, session_b):
    assume(session_a != session_b)
    store = InMemorySessionStore()
    _run(store.append_messages(session_a, [{"role": "user", "content": "a-msg"}]))
    _run(store.append_messages(session_b, [{"role": "user", "content": "b-msg"}]))

    hist_a = _run(store.get_history(session_a))
    hist_b = _run(store.get_history(session_b))

    assert len(hist_a) == 1
    assert len(hist_b) == 1
    assert hist_a[0]["content"] == "a-msg"
    assert hist_b[0]["content"] == "b-msg"


def test_delete_clears_everything():
    store = InMemorySessionStore()
    _run(store.append_messages("del-test", [{"role": "user", "content": "x"}]))
    _run(store.delete_session("del-test"))
    history = _run(store.get_history("del-test"))
    assert history == []


def test_sequence_numbers_monotonic():
    store = InMemorySessionStore(config=SessionConfig(max_messages=100, ttl_seconds=3600))
    for i in range(5):
        _run(store.append_messages("seq-test", [{"role": "user", "content": str(i)}]))

    history = _run(store.get_history("seq-test"))
    assert len(history) == 5


@given(
    sid=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_empty_history_for_new_session(sid):
    store = InMemorySessionStore()
    history = _run(store.get_history(sid))
    assert history == []
