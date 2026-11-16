"""``Principal.from_legacy_dict`` narrowing semantics (issue #1790, correction 2).

The refactor that removed the C(14) block made two behaviours explicit; these
tests pin them so a later refactor cannot quietly reopen either:

* a bare string is **not** iterated character-wise. A ``str`` is not a
  collection of roles, so ``{"roles": "admin"}`` yields the empty set -- not
  ``{"a", "d", "m", "i", "n"}``. It matters for a roles field, where the
  character-split reading would silently invent four bogus roles.
* a singular ``role`` beats a plural ``roles`` when a dict carries both: the
  dict was narrowed upstream, and reading the plural would widen it back.
"""

from __future__ import annotations

from maistro.identity.principal import Principal


def test_bare_string_yields_empty_set_not_characters() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "roles": "admin"})
    assert principal.roles == frozenset()


def test_bare_string_is_empty_for_every_repeated_field() -> None:
    principal = Principal.from_legacy_dict(
        {"id": "u1", "scopes": "read", "team_ids": "team-a", "workspace_ids": "ws-1"}
    )
    assert principal.scopes == frozenset()
    assert principal.team_ids == frozenset()
    assert principal.workspace_ids == frozenset()


def test_singular_role_beats_plural_roles() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "role": "editor", "roles": ["viewer"]})
    assert principal.roles == frozenset({"editor"})


def test_plural_roles_used_when_singular_absent() -> None:
    principal = Principal.from_legacy_dict({"id": "u1", "roles": ["viewer", "editor"]})
    assert principal.roles == frozenset({"viewer", "editor"})


def test_real_collections_still_parse() -> None:
    """Control: the narrowing rules never rejected legitimate collections."""
    principal = Principal.from_legacy_dict(
        {
            "id": "u1",
            "scopes": ("read", "write"),
            "team_ids": {"team-a"},
            "workspace_ids": ["ws-1"],
        }
    )
    assert principal.scopes == frozenset({"read", "write"})
    assert principal.team_ids == frozenset({"team-a"})
    assert principal.workspace_ids == frozenset({"ws-1"})
