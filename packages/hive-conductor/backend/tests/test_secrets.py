"""services/secrets.py — vault-first secret resolution (SPEC-003)."""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


class _FakeVault:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def use(self, name: str, callback):
        if name not in self._secrets:
            raise KeyError(name)
        return callback(self._secrets[name])


class _FakeFoundation:
    def __init__(self, vault, *, vault_available: bool) -> None:
        self.vault = vault
        self.vault_available = vault_available


@pytest.fixture(autouse=True)
def _reset_singleton():
    import services.foundation as f

    prev = f._singleton
    f._singleton = None
    yield
    f._singleton = prev


def test_resolve_secret_prefers_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.foundation as f
    from services.secrets import resolve_secret

    f._singleton = _FakeFoundation(_FakeVault({"K": "from-vault"}), vault_available=True)
    monkeypatch.setenv("K", "from-env")
    assert resolve_secret("K", config_value="from-config", env_var="K") == "from-vault"


def test_resolve_secret_falls_back_to_config_then_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.secrets import resolve_secret

    monkeypatch.setenv("K", "from-env")
    assert resolve_secret("K", config_value="from-config", env_var="K") == "from-config"
    assert resolve_secret("K", config_value=None, env_var="K") == "from-env"


def test_resolve_secret_no_vault_no_value_returns_none() -> None:
    from services.secrets import resolve_secret

    assert resolve_secret("MISSING_KEY") is None


def test_resolve_secret_required_and_missing_raises() -> None:
    from services.secrets import resolve_secret

    with pytest.raises(SystemExit, match="SECRET_MISSING: MISSING_KEY"):
        resolve_secret("MISSING_KEY", required=True)


def test_resolve_secret_required_and_present_in_vault_does_not_raise() -> None:
    import services.foundation as f
    from services.secrets import resolve_secret

    f._singleton = _FakeFoundation(_FakeVault({"K": "v"}), vault_available=True)
    assert resolve_secret("K", required=True) == "v"


def test_vault_unavailable_falls_through_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.foundation as f
    from services.secrets import resolve_secret

    f._singleton = _FakeFoundation(_FakeVault({"K": "from-vault"}), vault_available=False)
    assert resolve_secret("K", config_value="from-config") == "from-config"
