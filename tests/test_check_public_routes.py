"""Tests for the unauthenticated-route registry gate (#316).

The gate's job is to make a bypass impossible to add quietly, so the tests are
about the ways a bypass could still get through: a path the registry does not
mention, a registry entry describing a different kind of match than the one the
middleware actually performs, and a "temporary" exemption that has quietly
become permanent by outliving its own date.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-public-routes.py"

_ENTRY = {
    "kind": "prefix",
    "owner": "@someone",
    "risk": "low",
    "disposition": "permanent",
    "reason": "because",
}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_public_routes", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bench(tmp_path: Path, gate, monkeypatch: pytest.MonkeyPatch):
    """Point the gate at a middleware source and a registry we control."""

    def _set(source: str, routes: dict) -> None:
        middleware = tmp_path / "auth.py"
        registry = tmp_path / "public-routes.json"
        middleware.write_text(source, encoding="utf-8")
        registry.write_text(json.dumps({"routes": routes}), encoding="utf-8")
        monkeypatch.setattr(gate, "MIDDLEWARE", middleware)
        monkeypatch.setattr(gate, "REGISTRY", registry)

    return _set


class TestItReadsTheDeclarationsAsTheyAreWritten:
    def test_each_tuple_contributes_its_own_kind(self, gate) -> None:
        """The kinds match differently — `prefix` is boundary-safe, the loose
        one is a bare `startswith` — so which list a path is in is part of what
        the exemption *is*."""
        source = (
            '_PUBLIC_PREFIXES = ("/health",)\n'
            '_PUBLIC_PREFIXES_LOOSE = ("/docs",)\n'
            '_PUBLIC_EXACT = frozenset({"/"})\n'
        )

        assert gate.declared_paths(source) == {
            "/health": "prefix",
            "/docs": "loose-prefix",
            "/": "exact",
        }

    def test_a_path_named_anywhere_else_is_not_a_declaration(self, gate) -> None:
        """`_ADMIN_CHAT_BLOCKED` and `_PROTECTED_OPS` are full of route strings
        and none of them are public."""
        source = '_ADMIN_CHAT_BLOCKED = ("/v1/chat/",)\nOTHER = ("/v1/voice/",)\n'

        assert gate.declared_paths(source) == {}


class TestABypassCannotArriveUnannounced:
    def test_a_path_the_registry_does_not_mention_fails(self, gate, bench) -> None:
        bench('_PUBLIC_PREFIXES = ("/v1/voice/",)\n', {})

        failures = gate.audit()

        assert len(failures) == 1
        assert "/v1/voice/" in failures[0]
        assert "nobody signed" in failures[0]

    def test_a_registry_entry_with_no_matching_path_fails(self, gate, bench) -> None:
        """A stale entry is worse than none: it is a standing approval for
        whoever next adds that string back."""
        bench("_PUBLIC_PREFIXES = ()\n", {"/v1/voice/": dict(_ENTRY)})

        failures = gate.audit()

        assert len(failures) == 1
        assert "stale entry" in failures[0]

    def test_the_declared_kind_must_be_the_kind_that_matches(self, gate, bench) -> None:
        """Declaring a boundary-safe prefix while the middleware does a bare
        `startswith` describes an exemption narrower than the real one."""
        bench('_PUBLIC_PREFIXES_LOOSE = ("/health",)\n', {"/health": dict(_ENTRY)})

        failures = gate.audit()

        assert len(failures) == 1
        assert "loose-prefix" in failures[0]

    @pytest.mark.parametrize("field", ["owner", "risk", "disposition", "reason"])
    def test_every_entry_names_who_and_why(self, gate, bench, field: str) -> None:
        entry = dict(_ENTRY)
        del entry[field]
        bench('_PUBLIC_PREFIXES = ("/health",)\n', {"/health": entry})

        failures = gate.audit()

        assert any(field in message for message in failures)

    def test_an_unknown_risk_is_not_a_risk_assessment(self, gate, bench) -> None:
        bench('_PUBLIC_PREFIXES = ("/health",)\n', {"/health": {**_ENTRY, "risk": "fine"}})

        assert any("risk" in message for message in gate.audit())

    def test_an_unknown_disposition_is_not_a_decision(self, gate, bench) -> None:
        """ "permanent" and "temporary" are the two the gate can reason about.
        Anything else — "review", "wontfix", a typo — would otherwise be read as
        "not temporary" and skip the expiry check entirely."""
        bench(
            '_PUBLIC_PREFIXES = ("/health",)\n',
            {"/health": {**_ENTRY, "disposition": "under review"}},
        )

        failures = gate.audit()

        assert len(failures) == 1
        assert "disposition" in failures[0]

    def test_an_entry_that_is_not_an_object_fails(self, gate, bench) -> None:
        bench('_PUBLIC_PREFIXES = ("/health",)\n', {"/health": "it's fine"})

        assert gate.audit() == ["  /health: registry entry is not an object"]


class TestATemporaryExemptionStaysTemporary:
    def _temporary(self, **overrides) -> dict:
        entry = {**_ENTRY, "disposition": "temporary", "issue": 313, "expires": "2099-01-01"}
        entry.update(overrides)
        return entry

    def test_it_must_name_the_issue_that_removes_it(self, gate, bench) -> None:
        entry = self._temporary()
        del entry["issue"]
        bench('_PUBLIC_PREFIXES = ("/x/",)\n', {"/x/": entry})

        assert any("issue" in message for message in gate.audit())

    def test_it_must_name_a_date(self, gate, bench) -> None:
        entry = self._temporary()
        del entry["expires"]
        bench('_PUBLIC_PREFIXES = ("/x/",)\n', {"/x/": entry})

        assert any("expires" in message for message in gate.audit())

    def test_an_unparseable_date_is_not_a_date(self, gate, bench) -> None:
        bench('_PUBLIC_PREFIXES = ("/x/",)\n', {"/x/": self._temporary(expires="soon")})

        assert any("YYYY-MM-DD" in message for message in gate.audit())

    def test_a_live_date_passes(self, gate, bench) -> None:
        bench('_PUBLIC_PREFIXES = ("/x/",)\n', {"/x/": self._temporary(expires="2026-12-31")})

        assert gate.audit(today=date(2026, 8, 26)) == []

    def test_an_expired_exemption_fails_and_names_its_issue(self, gate, bench) -> None:
        """The point of the date: past it the exemption stops approving itself
        and someone has to look again."""
        bench('_PUBLIC_PREFIXES = ("/x/",)\n', {"/x/": self._temporary(expires="2026-08-25")})

        failures = gate.audit(today=date(2026, 8, 26))

        assert len(failures) == 1
        assert "expired on 2026-08-25" in failures[0]
        assert "#313" in failures[0]

    def test_a_permanent_entry_needs_no_date(self, gate, bench) -> None:
        bench('_PUBLIC_PREFIXES = ("/x/",)\n', {"/x/": dict(_ENTRY)})

        assert gate.audit() == []


class TestTheRepositorysOwnRegistry:
    def test_it_agrees_with_the_middleware(self, gate) -> None:
        assert gate.audit() == []

    def test_no_voice_path_is_public(self, gate) -> None:
        """The bypass this gate was built for, asserted against the real files
        rather than a fixture."""
        declared = gate.declared_paths(gate.MIDDLEWARE.read_text(encoding="utf-8"))

        assert not [path for path in declared if "voice" in path]

    def test_every_temporary_exemption_points_at_an_open_issue(self, gate) -> None:
        """A number, not a placeholder. The gate accepts any truthy value;
        this is the part a human would otherwise have to remember to check."""
        registry = json.loads(gate.REGISTRY.read_text(encoding="utf-8"))["routes"]

        for path, entry in registry.items():
            if entry["disposition"] == "temporary":
                assert isinstance(entry["issue"], int), path
                assert entry["issue"] > 0, path

    def test_main_passes_and_says_how_many(self, gate, capsys) -> None:
        assert gate.main() == 0
        assert "unauthenticated path(s) are declared" in capsys.readouterr().out

    def test_main_fails_when_a_source_file_is_missing(
        self, gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A gate that cannot find what it governs must go red, not report
        `ok` over a file it never opened."""
        monkeypatch.setattr(gate, "REGISTRY", tmp_path / "not-here.json")

        assert gate.main() == 1

    def test_main_reports_each_problem(self, gate, bench, capsys) -> None:
        bench('_PUBLIC_PREFIXES = ("/v1/voice/",)\n', {})

        assert gate.main() == 1
        assert "/v1/voice/" in capsys.readouterr().out
