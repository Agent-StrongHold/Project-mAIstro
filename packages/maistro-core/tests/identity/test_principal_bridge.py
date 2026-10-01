"""Legacy-dict bridge behavior for the HTTP Principal (P0.1 / ADR-068).

``Principal.from_legacy_dict`` / ``to_legacy_dict`` are the cutover adapters
between hive ``request.state.user`` dicts and the canonical principal type.
This file pins their parsing precedence and round-trip so the ratchet-driven
decomposition of ``from_legacy_dict`` cannot silently change behavior. It
imports ``maistro.identity.principal`` directly: the bridge must work without
the optional ``identity`` crypto extra (tests/identity/test_extra_guard.py).
"""

from __future__ import annotations

from maistro.identity.principal import Principal


def test_user_id_prefers_id_over_user_id() -> None:
    assert Principal.from_legacy_dict({"id": "u1", "user_id": "u2"}).user_id == "u1"
    assert Principal.from_legacy_dict({"user_id": "u2"}).user_id == "u2"


def test_user_id_missing_yields_empty_string() -> None:
    assert Principal.from_legacy_dict({}).user_id == ""


def test_user_id_falsy_id_falls_through() -> None:
    assert Principal.from_legacy_dict({"id": "", "user_id": "u2"}).user_id == "u2"
    assert Principal.from_legacy_dict({"id": ""}).user_id == ""


def test_single_role_wins_over_roles_collection() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "role": "admin", "roles": ["viewer"]})
    assert principal.roles == frozenset({"admin"})


def test_roles_collection_without_single_role() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "roles": ["viewer", "editor"]})
    assert principal.roles == frozenset({"viewer", "editor"})


def test_roles_non_collection_is_ignored() -> None:
    assert Principal.from_legacy_dict({"id": "u1", "roles": "viewer"}).roles == frozenset()
    assert Principal.from_legacy_dict({"id": "u1", "roles": None}).roles == frozenset()


def test_roles_accepts_any_iterable_collection() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "roles": ("viewer",)})
    assert principal.roles == frozenset({"viewer"})


def test_scopes_require_collection() -> None:
    parsed = Principal.from_legacy_dict({"id": "u1", "scopes": ["read", "write"]})
    assert parsed.scopes == frozenset({"read", "write"})
    assert Principal.from_legacy_dict({"id": "u1", "scopes": "read"}).scopes == frozenset()


def test_workspace_ids_alias_and_precedence() -> None:
    assert Principal.from_legacy_dict({"id": "u1", "workspace_ids": ["w1"]}).workspace_ids == (
        frozenset({"w1"})
    )
    assert Principal.from_legacy_dict({"id": "u1", "workspaces": ["w2"]}).workspace_ids == (
        frozenset({"w2"})
    )
    both = Principal.from_legacy_dict({"id": "u1", "workspace_ids": ["w1"], "workspaces": ["w2"]})
    assert both.workspace_ids == frozenset({"w1"})
    # An empty (falsy) workspace_ids still falls through to the alias.
    empty = Principal.from_legacy_dict({"id": "u1", "workspace_ids": [], "workspaces": ["w2"]})
    assert empty.workspace_ids == frozenset({"w2"})


def test_org_id_coerced_to_str_or_none() -> None:
    assert Principal.from_legacy_dict({"id": "u1", "org_id": 42}).org_id == "42"
    assert Principal.from_legacy_dict({"id": "u1", "org_id": None}).org_id is None
    assert Principal.from_legacy_dict({"id": "u1"}).org_id is None


def test_team_ids_items_coerced_to_str() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "team_ids": ["t1", 2]})
    assert principal.team_ids == frozenset({"t1", "2"})


def test_unknown_keys_ignored() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "email": "a@b.c", "admin": True})
    assert principal == Principal(user_id="u1")


def test_to_legacy_dict_minimal_omits_empty_optionals() -> None:
    payload = Principal(user_id="u1").to_legacy_dict()
    assert payload == {"id": "u1", "roles": []}


def test_to_legacy_dict_full_payload() -> None:
    principal = Principal(
        user_id="u1",
        roles=frozenset({"viewer", "admin"}),
        scopes=frozenset({"read"}),
        workspace_ids=frozenset({"w1"}),
        org_id="o1",
        team_ids=frozenset({"t1"}),
    )
    assert principal.to_legacy_dict() == {
        "id": "u1",
        "roles": ["admin", "viewer"],
        "role": "admin",
        "scopes": ["read"],
        "workspace_ids": ["w1"],
        "org_id": "o1",
        "team_ids": ["t1"],
    }


def test_to_legacy_dict_primary_role_is_sorted_first() -> None:
    principal = Principal(user_id="u1", roles=frozenset({"viewer", "admin"}))
    assert principal.primary_role == "admin"
    assert Principal(user_id="u1").primary_role is None


def test_bridge_round_trips() -> None:
    principal = Principal(
        user_id="u1",
        roles=frozenset({"admin"}),
        scopes=frozenset({"read", "write"}),
        workspace_ids=frozenset({"w1"}),
        org_id="o1",
        team_ids=frozenset({"t1"}),
    )
    assert Principal.from_legacy_dict(principal.to_legacy_dict()) == principal
