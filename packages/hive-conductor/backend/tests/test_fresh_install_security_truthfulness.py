"""Fresh-install truthfulness of the security surface (#399).

``stores._seed_messages`` used to run on every boot regardless of mode, and
one of its rows was a fabricated CRITICAL security finding ("XSS in
/v1/auth/callback" from "RedTeam", priority critical, category security).
A security-focused product therefore looked compromised the moment it was
installed, and no reviewer could tell that fiction from a real finding.

The fix follows the #840 precedent for the fabricated agent roster:

- production (the default) seeds no messages at all -- an empty inbox
  renders as "no messages", the same honesty rule the audit log already
  follows;
- the fixture survives only behind the explicit demo mode
  (``hive_mode == "demo"``), every row stamped ``synthetic=True``
  (machine-readable provenance) with deterministic ``msg-seed-*`` ids so
  it is unmistakable and trivially removable;
- the API offers no way to forge the stamp: ``CreateMessageBody`` has
  ``extra="ignore"``, so a POST body naming ``synthetic`` silently drops
  it and the stored row reads ``synthetic=False``.

These tests drive both the store layer and the HTTP surface (the E2E
fresh-install assertion) so the regression is pinned at the same boundary
a user or reviewer would meet it.
"""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402


def _clear_messages() -> None:
    for key in list(stores.messages.keys()):
        stores.messages.pop(key, None)


@pytest.fixture(autouse=True)
def _clean_inbox():
    """Keep the shared session store clean: no test inherits seeded rows."""
    _clear_messages()
    yield
    _clear_messages()


def _production_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.get_settings", lambda: SimpleNamespace(hive_mode="production"))


def _demo_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.get_settings", lambda: SimpleNamespace(hive_mode="demo"))


class TestFreshInstallSeedsNoSecurityEvents:
    """A normal first boot must contain no fabricated vulnerability."""

    def test_full_boot_in_production_leaves_the_inbox_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _production_settings(monkeypatch)

        stores.initialize_stores()

        assert len(stores.messages) == 0

    def test_no_fabricated_critical_xss_row_after_boot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _production_settings(monkeypatch)

        stores.initialize_stores()

        # Named explicitly because this exact row is the regression: a
        # fabricated CRITICAL finding is absent, not merely reduced.
        fabricated = [
            msg
            for msg in stores.messages.values()
            if msg.get("category") == "security"
            and msg.get("priority") == "critical"
            and "XSS" in str(msg.get("body", ""))
        ]
        assert fabricated == []

    def test_demo_gating_survives_a_second_boot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The empty result is the seed's choice, not a one-boot accident."""
        _production_settings(monkeypatch)

        for _ in range(2):
            stores.initialize_stores()
        assert len(stores.messages) == 0


class TestDemoModeFixture:
    """The fixture survives -- isolated, stamped, and removable."""

    def test_demo_mode_still_seeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _demo_settings(monkeypatch)

        stores._seed_messages()

        assert set(stores.messages.keys()) == {"msg-seed-1", "msg-seed-2", "msg-seed-3"}
        assert any(msg["body"] == "XSS in /v1/auth/callback" for msg in stores.messages.values())

    def test_every_demo_row_carries_machine_readable_synthetic_provenance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _demo_settings(monkeypatch)

        stores._seed_messages()

        assert stores.messages, "demo seed produced nothing to stamp"
        for row in stores.messages.values():
            assert row["synthetic"] is True
            assert row["id"].startswith("msg-seed-")

    def test_reseeding_in_demo_mode_is_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fixture is a when-empty guard, so re-seeding restores the same
        stamped rows -- and never invents a row without the stamp."""
        _demo_settings(monkeypatch)
        stores._seed_messages()
        first_ids = set(stores.messages.keys())
        _clear_messages()

        stores._seed_messages()

        assert set(stores.messages.keys()) == first_ids
        assert all(row["synthetic"] is True for row in stores.messages.values())


class TestApiSurface:
    """The HTTP boundary agrees with the store: empty when fresh, stamped
    when demo, and impossible to forge."""

    def test_fresh_install_api_reports_an_empty_truthful_security_state(
        self, monkeypatch: pytest.MonkeyPatch, authed_client
    ) -> None:
        _production_settings(monkeypatch)
        stores.initialize_stores()

        r_all = authed_client.get("/v1/messages")
        assert r_all.status_code == 200
        assert r_all.json() == []

        r_security = authed_client.get("/v1/messages", params={"category": "security"})
        assert r_security.status_code == 200
        assert r_security.json() == []

        r_unread = authed_client.get("/v1/messages/unread-count")
        assert r_unread.status_code == 200
        assert r_unread.json() == {"count": 0}

    def test_api_cannot_forge_the_synthetic_stamp(self, authed_client) -> None:
        r = authed_client.post(
            "/v1/messages",
            json={
                "from_agent": "RedTeam",
                "to": "admin",
                "subject": "forged",
                "body": "XSS in /v1/auth/callback",
                "priority": "critical",
                "category": "security",
                "synthetic": True,
            },
        )
        assert r.status_code == 201
        stored = stores.messages[r.json()["id"]]
        assert stored["synthetic"] is False
        assert r.json()["synthetic"] is False

    def test_demo_rows_are_readable_and_removable_over_the_api(
        self, monkeypatch: pytest.MonkeyPatch, authed_client
    ) -> None:
        _demo_settings(monkeypatch)
        stores._seed_messages()

        r = authed_client.get("/v1/messages")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 3
        assert all(row["synthetic"] is True for row in rows)

        r_del = authed_client.delete("/v1/messages/msg-seed-1")
        assert r_del.status_code == 204
        assert "msg-seed-1" not in stores.messages

        r_after = authed_client.get("/v1/messages", params={"category": "security"})
        assert r_after.status_code == 200
        assert r_after.json() == []
