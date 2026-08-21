"""Boy Scout coverage: services/user_credentials.py (was 77%)."""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _isolate_store():
    """Snapshot + restore the module-level _store reference."""
    import services.user_credentials as cred_svc

    prev = cred_svc._store
    yield
    cred_svc._store = prev


def test_init_credential_store_success(tmp_path: Path) -> None:
    import services.user_credentials as cred_svc

    cred_svc._store = None
    ok = cred_svc.init_credential_store(tmp_path)
    assert ok is True
    assert cred_svc.get_credential_store() is not None


def test_init_credential_store_failure_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If UserCredentialStore.open raises, init returns False + store stays None."""
    import services.user_credentials as cred_svc

    from maistro.credentials.store import UserCredentialStore

    def _boom(path):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(UserCredentialStore, "open", classmethod(lambda cls, p: _boom(p)))
    cred_svc._store = None
    ok = cred_svc.init_credential_store("/nonexistent/path/xyz")
    assert ok is False
    assert cred_svc.get_credential_store() is None


def test_require_store_raises_when_uninitialized() -> None:
    import services.user_credentials as cred_svc

    from maistro.credentials import CredentialStoreUnavailable

    cred_svc._store = None
    with pytest.raises(CredentialStoreUnavailable, match="not initialized"):
        cred_svc.require_store()


def test_require_store_returns_instance_when_initialized(
    tmp_path: Path,
) -> None:
    import services.user_credentials as cred_svc

    cred_svc._store = None
    cred_svc.init_credential_store(tmp_path)
    assert cred_svc.require_store() is cred_svc._store


def test_list_provider_catalog_returns_known_providers() -> None:
    from services.user_credentials import list_provider_catalog

    from maistro.credentials import PM_CREDENTIAL_PROVIDERS

    catalog = list_provider_catalog()
    assert len(catalog) == len(PM_CREDENTIAL_PROVIDERS)
    ids = {entry["id"] for entry in catalog}
    assert "jira" in ids
    assert "airtable" in ids
    # Each entry has the canonical fields
    for entry in catalog:
        assert set(entry.keys()) >= {"id", "label", "description", "help_url", "placeholder"}
