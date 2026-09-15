"""The credential authority has one owner per responsibility (#1186)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "credential-authority.json"
CHECKER = ROOT / "scripts" / "check-credential-authority.py"

_spec = importlib.util.spec_from_file_location("credential_authority_checker", CHECKER)
assert _spec is not None and _spec.loader is not None
_checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _checker
_spec.loader.exec_module(_checker)


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_credential_authority_ledger_records_live_and_retired_surfaces() -> None:
    ledger = _ledger()
    canonical = ledger["canonical"]
    retired = ledger["retired"]

    assert Path(ROOT / canonical["product_crud"]).is_file()
    store_path, store_class = canonical["encrypted_store"].split("::", 1)
    assert store_class == "UserCredentialStore"
    assert Path(ROOT / store_path).is_file()
    assert canonical["runtime_selection"].startswith(
        "packages/maistro-core/src/maistro/credentials/router.py::"
    )
    assert retired == [
        {
            "path": "packages/hive-conductor/backend/services/credential_store_v2.py",
            "disposition": "RETIRE",
            "replacement": "services.user_credentials -> maistro.credentials.store.UserCredentialStore",
            "reason": "The v2 PostgREST service exposed id-only reads, secret reads, updates, and deletes without a principal predicate. It had no production callers and is deleted rather than made into a second credential authority.",
            "issue": "#1186",
        }
    ]
    assert not (ROOT / retired[0]["path"]).exists()


def test_reachable_credential_surfaces_are_classified_and_scoped() -> None:
    """The authority ledger must be joined to the production import graph."""
    assert _checker.audit() == []


def test_canonical_store_isolation_has_uniform_missing_record_behavior() -> None:
    """The replacement store scopes every record operation by principal.

    Retirement removes the unsafe id-only API rather than preserving it under a
    new name. Keep the canonical replacement's two-user contract explicit: an
    owner-id guess cannot read or delete another user's record, and the missing
    result is indistinguishable from an actually absent provider.
    """
    from cryptography.fernet import Fernet

    from maistro.credentials.store import CredentialNotFound, UserCredentialStore

    with tempfile.TemporaryDirectory() as directory:
        store = UserCredentialStore(Path(directory), master_key=Fernet.generate_key())
        store.set_secret("alice", "jira", "alice-secret")

        assert store.list_providers_for_user("bob") == {}
        assert not store.has_secret("bob", "jira")
        assert store.delete_secret("bob", "jira") is False
        assert store.has_secret("alice", "jira")

        with pytest.raises(CredentialNotFound) as guessed:
            store.use_secret("bob", "jira", lambda secret: secret)
        with pytest.raises(CredentialNotFound) as absent:
            store.use_secret("carol", "jira", lambda secret: secret)
        assert str(guessed.value) == str(absent.value)
        assert store.use_secret("alice", "jira", lambda secret: secret) == "alice-secret"


def test_retired_module_cannot_be_imported_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retirement ledger also blocks stale production imports."""
    with tempfile.TemporaryDirectory() as directory:
        package_root = Path(directory) / "packages" / "demo" / "src"
        package_fixture = package_root / "demo" / "adapter.py"
        package_fixture.parent.mkdir(parents=True)
        package_fixture.write_text(
            "from services.credential_store_v2 import CredentialV2\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(_checker, "ROOT", Path(directory))
        failures = _checker.audit(
            {
                "reachable": [],
                "retired": [{"path": "packages/demo/credential_store_v2.py"}],
            },
            modules={"demo.adapter": package_fixture},
            reachable=set(),
        )
        assert any("imports retired credential module" in failure for failure in failures)


def test_renamed_reachable_style_store_is_detected_by_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store cannot evade review by dropping ``credential_store`` from its name."""
    source = """
import httpx
from cryptography.fernet import Fernet

class Repository:
    def __init__(self):
        self._fernet = Fernet.generate_key()

    def get(self, record_id):
        return httpx.get('/records', params={'id': record_id})

    def rotate(self, record_id, secret):
        return self._fernet.encrypt(secret.encode())

    def delete(self, record_id):
        return httpx.delete('/records', params={'id': record_id})
"""
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "repository.py"
        fixture.write_text(source, encoding="utf-8")
        assert _checker.is_credential_surface(fixture)

        # Feed the renamed implementation through the ledger join as a
        # reachable module. Detection alone is not enough: the gate must reject
        # a reachable surface that has no authority classification.
        package_root = Path(directory) / "packages" / "demo" / "src"
        package_fixture = package_root / "demo" / "repository.py"
        package_fixture.parent.mkdir(parents=True)
        package_fixture.write_text(source, encoding="utf-8")
        monkeypatch.setattr(_checker, "ROOT", Path(directory))
        failures = _checker.audit(
            {"reachable": [], "retired": [{"path": "deleted.py"}]},
            modules={"demo.repository": package_fixture},
            reachable={"demo.repository"},
        )
        assert any("not classified" in failure for failure in failures)
