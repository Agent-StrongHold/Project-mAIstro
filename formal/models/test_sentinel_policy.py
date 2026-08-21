"""I6: Sentinel Permission Enforcement — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security._types import AuthContext, WardenVerdict
from maistro.security.sentinel.policy import Sentinel, check_permission


def _run(coro):
    return asyncio.run(coro)


class _StubWarden:
    async def scan(self, content, boundary):
        return WardenVerdict(clean=True)


class _StubAuditLog:
    def __init__(self):
        self.entries = []

    async def log(self, entry):
        self.entries.append(entry)


_STUB_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


class SentinelPermissionMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.permission_table = {}
        self.warden = _StubWarden()
        self.audit = _StubAuditLog()
        self.sentinel = Sentinel(
            warden=self.warden,
            permission_table=self.permission_table,
            audit_log=self.audit,
        )
        self.denied_count = 0
        self.allowed_count = 0

    @rule(
        tool_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
        role=st.sampled_from(["admin", "user", "viewer", "editor"]),
    )
    def add_permission(self, tool_name, role):
        existing = self.permission_table.get(tool_name, frozenset())
        self.permission_table[tool_name] = existing | frozenset({role})
        self.sentinel._permission_table = self.permission_table

    @rule(
        user_id=st.text(min_size=1, max_size=10),
        role=st.sampled_from(["admin", "user", "viewer", "editor"]),
        tool_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
    )
    def pre_call_check(self, user_id, role, tool_name):
        auth = AuthContext(user_id=user_id, roles=frozenset({role}))
        verdict = _run(self.sentinel.pre_call(tool_name, {}, auth, _STUB_SCHEMA))
        if verdict.allowed:
            self.allowed_count += 1
        else:
            self.denied_count += 1

    @invariant()
    def audit_log_entries_match(self):
        assert len(self.audit.entries) == self.denied_count + self.allowed_count


TestSentinelPermissionMachine = SentinelPermissionMachine.TestCase


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
    role=st.sampled_from(["admin", "user", "viewer"]),
)
@settings(max_examples=50)
def test_no_permission_entry_means_allowed(user_id, tool_name, role):
    auth = AuthContext(user_id=user_id, roles=frozenset({role}))
    table = {}

    assert check_permission(auth, tool_name, table) is True


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
    allowed_role=st.sampled_from(["admin", "user"]),
)
@settings(max_examples=30)
def test_user_with_matching_role_allowed(user_id, tool_name, allowed_role):
    auth = AuthContext(user_id=user_id, roles=frozenset({allowed_role}))
    table = {tool_name: frozenset({allowed_role})}

    assert check_permission(auth, tool_name, table) is True


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_user_without_matching_role_denied(user_id, tool_name):
    auth = AuthContext(user_id=user_id, roles=frozenset({"user"}))
    table = {tool_name: frozenset({"admin"})}

    assert check_permission(auth, tool_name, table) is False


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_pre_call_denied_without_permission(user_id, tool_name):
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={tool_name: frozenset({"admin"})},
    )
    auth = AuthContext(user_id=user_id, roles=frozenset({"user"}))

    verdict = _run(sentinel.pre_call(tool_name, {}, auth, _STUB_SCHEMA))
    assert not verdict.allowed
    assert any(v.rule == "permission_denied" for v in verdict.violations)


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
    role=st.sampled_from(["admin", "user", "editor"]),
)
@settings(max_examples=30)
def test_pre_call_allowed_with_permission(user_id, tool_name, role):
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={tool_name: frozenset({role})},
    )
    auth = AuthContext(user_id=user_id, roles=frozenset({role}))

    verdict = _run(sentinel.pre_call(tool_name, {}, auth, _STUB_SCHEMA))
    assert verdict.allowed


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_pre_call_open_by_default(user_id, tool_name):
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
    )
    auth = AuthContext(user_id=user_id, roles=frozenset())

    verdict = _run(sentinel.pre_call(tool_name, {}, auth, _STUB_SCHEMA))
    assert verdict.allowed


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_pre_call_user_with_multiple_roles(user_id, tool_name):
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={tool_name: frozenset({"admin", "editor"})},
    )
    auth = AuthContext(user_id=user_id, roles=frozenset({"user", "editor"}))

    verdict = _run(sentinel.pre_call(tool_name, {}, auth, _STUB_SCHEMA))
    assert verdict.allowed


@given(
    user_id=st.text(min_size=1, max_size=20),
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_pre_call_empty_roles_denied_when_restricted(user_id, tool_name):
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={tool_name: frozenset({"admin"})},
    )
    auth = AuthContext(user_id=user_id, roles=frozenset())

    verdict = _run(sentinel.pre_call(tool_name, {}, auth, _STUB_SCHEMA))
    assert not verdict.allowed


@given(
    user_id=st.text(min_size=1, max_size=20),
    result_text=st.text(min_size=1, max_size=100),
)
@settings(max_examples=30)
def test_post_call_clean_result(user_id, result_text):
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
    )
    auth = AuthContext(user_id=user_id, roles=frozenset({"user"}))

    processed = _run(sentinel.post_call("some_tool", result_text, auth))
    assert isinstance(processed, str)
    assert len(processed) > 0


@given(
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=20)
def test_can_use_tool_no_entry(tool_name):
    auth = AuthContext(user_id="u1", roles=frozenset({"user"}))
    assert auth.can_use_tool(tool_name, {})


@given(
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=20)
def test_can_use_tool_entry_with_matching_role(tool_name):
    auth = AuthContext(user_id="u1", roles=frozenset({"admin", "user"}))
    table = {tool_name: frozenset({"admin"})}
    assert auth.can_use_tool(tool_name, table)


@given(
    tool_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=20)
def test_can_use_tool_entry_no_matching_role(tool_name):
    auth = AuthContext(user_id="u1", roles=frozenset({"user"}))
    table = {tool_name: frozenset({"admin"})}
    assert not auth.can_use_tool(tool_name, table)
