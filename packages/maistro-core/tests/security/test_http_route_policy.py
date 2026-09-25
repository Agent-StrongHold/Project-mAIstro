"""Behavioral tests for the shared HTTP route-declaration matcher (#1140).

``maistro.security.http_routes`` is the one matcher both live middlewares and
the CI route gate execute. Its contract is fail-closed: an unusable registry is
a startup failure, not an allow, and an ambiguous declaration is a refusal, not
a choice. These tests pin that contract at the library level so the publish-set
coverage producer measures the module its own package ships.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro.auth import Scope, canonical_permission
from maistro.security.http_routes import (
    RoutePolicyError,
    load_route_policy,
    matches_prefix,
    route_policy,
)


def _write_registry(tmp_path: Path, application: str, entries: object) -> Path:
    path = tmp_path / "route-permissions.json"
    path.write_text(
        json.dumps({"routes": {application: entries}}),
        encoding="utf-8",
    )
    return path


def _permission(path: str = "/v1/state", **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "methods": ["GET"],
        "path": path,
        "kind": "exact",
        "access": "permission",
        "permission": "turing.vault_read",
    }
    entry.update(overrides)
    return entry


def _public(path: str = "/health", **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "methods": ["GET"],
        "path": path,
        "kind": "exact",
        "access": "public",
        "owner": "@someone",
        "risk": "low",
        "disposition": "permanent",
        "reason": "liveness",
    }
    entry.update(overrides)
    return entry


# ---------------------------------------------------------------- loading ---


class TestLoadRoutePolicyFailsClosed:
    def test_an_unreadable_file_is_a_startup_failure(self, tmp_path: Path) -> None:
        with pytest.raises(RoutePolicyError, match="registry unavailable"):
            load_route_policy(tmp_path / "absent.json", "turing")

    def test_a_missing_application_list_is_a_startup_failure(self, tmp_path: Path) -> None:
        path = _write_registry(tmp_path, "turing", {"path": "/"})
        with pytest.raises(RoutePolicyError, match="has no 'turing' list"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize("payload", [('"routes": 3'), "{}"])
    def test_a_malformed_registry_is_a_startup_failure(self, tmp_path: Path, payload: str) -> None:
        path = tmp_path / "route-permissions.json"
        path.write_text("{" + payload + "}", encoding="utf-8")
        with pytest.raises(RoutePolicyError, match="registry unavailable"):
            load_route_policy(path, "turing")

    def test_a_non_object_declaration_is_rejected(self, tmp_path: Path) -> None:
        path = _write_registry(tmp_path, "turing", ["exact"])
        with pytest.raises(RoutePolicyError, match=r"turing\[0\] is not an object"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize("path_value", ["v1/state", 7, None])
    def test_a_relative_or_non_string_path_is_rejected(
        self, tmp_path: Path, path_value: object
    ) -> None:
        entry = _permission()
        entry["path"] = path_value
        path = _write_registry(tmp_path, "turing", [entry])
        with pytest.raises(RoutePolicyError, match="has an invalid path"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize("kind", ["glob", "suffix", None])
    def test_an_unknown_matching_kind_is_rejected(self, tmp_path: Path, kind: object) -> None:
        path = _write_registry(tmp_path, "turing", [_permission(kind=kind)])
        with pytest.raises(RoutePolicyError, match="has an invalid kind"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize("methods", [None, [], ["GET", 7], "GET"])
    def test_declarations_without_concrete_methods_are_rejected(
        self, tmp_path: Path, methods: object
    ) -> None:
        path = _write_registry(tmp_path, "turing", [_permission(methods=methods)])
        with pytest.raises(RoutePolicyError, match="has invalid methods"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize("access", ["allow", "anonymous", None])
    def test_an_unknown_access_kind_is_rejected(self, tmp_path: Path, access: object) -> None:
        path = _write_registry(tmp_path, "turing", [_permission(access=access)])
        with pytest.raises(RoutePolicyError, match="has invalid access"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize(
        "permission", [None, "VaultRead", "turing", "turing.vault_read.extra", ""]
    )
    def test_a_permission_declaration_needs_canonical_scope_verb_vocabulary(
        self, tmp_path: Path, permission: object
    ) -> None:
        path = _write_registry(tmp_path, "turing", [_permission(permission=permission)])
        with pytest.raises(RoutePolicyError, match="has an invalid permission"):
            load_route_policy(path, "turing")

    @pytest.mark.parametrize("field", ["owner", "reason", "expires"])
    def test_an_exemption_must_name_owner_reason_and_expiry(
        self, tmp_path: Path, field: str
    ) -> None:
        entry = _permission(
            access="exempt", owner="@someone", reason="mid-migration", expires="2027-01-31"
        )
        entry[field] = "  "  # present but blank is still unnamed
        path = _write_registry(tmp_path, "turing", [entry])
        with pytest.raises(RoutePolicyError, match="has an incomplete exemption"):
            load_route_policy(path, "turing")

    def test_a_valid_registry_loads_with_its_declarations_intact(self, tmp_path: Path) -> None:
        entries = [
            _permission(),
            _public("/health", kind="prefix"),
        ]
        path = _write_registry(tmp_path, "turing", entries)

        loaded = load_route_policy(path, "turing")

        assert loaded == tuple(entries)


# --------------------------------------------------------------- matching ---


class TestMatchesPrefixIsBoundarySafe:
    @pytest.mark.parametrize(
        ("prefix", "path", "expected"),
        [
            ("/docs", "/docs", True),
            ("/docs", "/docs/reference", True),
            ("/docs", "/docs", True),
            ("/docs/", "/docs/reference", True),
            ("/docs", "/docsy", False),
            ("/docs", "/doc", False),
        ],
    )
    def test_a_prefix_ends_at_a_path_boundary(self, prefix: str, path: str, expected: bool) -> None:
        assert matches_prefix(path, prefix) is expected


class TestRoutePolicySelection:
    def test_an_unmatched_path_has_no_declaration(self) -> None:
        assert route_policy((_public("/health"),), "GET", "/v1/anything") is None

    def test_a_path_on_an_undeclared_method_has_no_declaration(self) -> None:
        assert route_policy((_public("/health"),), "DELETE", "/health") is None

    def test_a_wildcard_method_declaration_matches_any_method(self) -> None:
        entry = _permission(methods=["*"])

        assert route_policy((entry,), "POST", "/v1/state") is entry

    def test_exact_beats_boundary_prefix(self) -> None:
        entries = (_permission("/v1/state", kind="prefix"), _public("/v1/state"))

        assert route_policy(entries, "GET", "/v1/state")["access"] == "public"

    def test_the_longest_prefix_wins(self) -> None:
        entries = (
            _permission("/v1", kind="prefix"),
            _public("/v1/state", kind="prefix"),
        )

        assert route_policy(entries, "GET", "/v1/state/feed")["access"] == "public"

    def test_a_head_request_is_served_by_the_get_declaration(self) -> None:
        entries = (_public("/health"),)

        assert route_policy(entries, "HEAD", "/health") is not None
        assert route_policy(entries, "POST", "/health") is None

    def test_a_template_matches_one_segment_and_not_a_lookalike(self) -> None:
        entries = (_permission("/v1/items/{item_id}", kind="template"),)

        assert route_policy(entries, "GET", "/v1/items/42") is not None
        assert route_policy(entries, "GET", "/v1/items/42/parts") is None
        assert route_policy(entries, "GET", "/v1/items") is None

    def test_equally_specific_conflicting_declarations_are_refused(self) -> None:
        entries = (
            _permission("/v1/state"),
            _permission("/v1/state", permission="turing.vault_write"),
        )

        assert route_policy(entries, "GET", "/v1/state") is None


class TestCanonicalPermissionVocabulary:
    def test_scope_transport_spelling_maps_to_the_route_permission_spelling(self) -> None:
        assert canonical_permission(Scope.TURING_VAULT_READ) == "turing.vault_read"
        assert canonical_permission(Scope.TURING_CHAT) == "turing.chat"
